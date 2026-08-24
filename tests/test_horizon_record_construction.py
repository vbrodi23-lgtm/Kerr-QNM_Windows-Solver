"""Regression: horizon record construction uses CampaignLeafRecord defaults."""

from __future__ import annotations

import unittest

from windows_solver.campaign_runtime import _produced_horizon_record
from windows_solver.native_response_kernel import VettedNativeDeterminantKernel
from windows_solver.response_batches import (
    CampaignLeafRecord,
    CampaignStageRecord,
    PrecisionCapabilities,
    build_campaign_plan,
    synthetic_stage_signed_error_channels,
    validate_campaign_recovery_record,
)
from windows_solver.response_engine import NumericalPolicy


def _plan_and_horizon_leaf():
    plan = build_campaign_plan(
        policy=NumericalPolicy(),
        backend_identity=VettedNativeDeterminantKernel.identity,
        precision_capabilities=PrecisionCapabilities((64, 80)),
    )
    leaf = next(
        item for item in plan.leaves
        if item.mechanism_id == "horizon-admittance"
    )
    return plan, leaf


def _synthetic_stage(plan, leaf, digits=64):
    from windows_solver.response_batches import StageOutcome

    payload = {
        "evidence_kind": "synthetic-horizon-record-regression",
        "leaf_id": leaf.leaf_id,
        "digits": digits,
    }
    outcome = StageOutcome(
        digits=digits,
        numerical_state="CONVERGED",
        component_result=payload,
        local_disk_radius_abs=1.0e-6,
        signed_error_channels=synthetic_stage_signed_error_channels(
            payload, 1.0e-6
        ),
    )
    available = [64] if digits == 64 else list(plan.precision_capabilities.digits)
    return CampaignStageRecord(
        outcome,
        {
            "precision_factory_identity": plan.precision_factory_identity.to_mapping(),
            "available_precision_digits": available,
        },
    )


class HorizonRecordConstructionTests(unittest.TestCase):
    def test_produced_horizon_record_uses_canonical_defaults(self) -> None:
        plan, leaf = _plan_and_horizon_leaf()
        stage = _synthetic_stage(plan, leaf)
        record = _produced_horizon_record(leaf, stage)

        self.assertEqual(record.leaf_id, leaf.leaf_id)
        self.assertEqual(record.role, leaf.role)
        self.assertEqual(record.state, "PRODUCED")
        self.assertEqual(record.trigger_ids, ())
        self.assertIs(record.sentinel, False)

    def test_campaign_leaf_plan_has_no_trigger_ids_or_sentinel(self) -> None:
        _plan, leaf = _plan_and_horizon_leaf()

        self.assertFalse(hasattr(leaf, "trigger_ids"))
        self.assertFalse(hasattr(leaf, "sentinel"))

    def test_horizon_record_round_trips_through_from_mapping(self) -> None:
        plan, leaf = _plan_and_horizon_leaf()
        stage = _synthetic_stage(plan, leaf)
        record = _produced_horizon_record(leaf, stage)
        mapping = record.to_mapping()
        restored = CampaignLeafRecord.from_mapping(mapping)

        self.assertEqual(restored.leaf_id, leaf.leaf_id)
        self.assertEqual(restored.role, leaf.role)
        self.assertEqual(restored.state, "PRODUCED")
        self.assertEqual(restored.trigger_ids, ())
        self.assertIs(restored.sentinel, False)

    def test_no_leaf_trigger_ids_or_sentinel_in_campaign_runtime(self) -> None:
        import re
        from pathlib import Path

        source = Path("src/windows_solver/campaign_runtime.py").read_text()
        matches = re.findall(r"leaf\.(trigger_ids|sentinel)", source)
        self.assertEqual(
            matches, [],
            "campaign_runtime.py must not access leaf.trigger_ids or leaf.sentinel",
        )


if __name__ == "__main__":
    unittest.main()
