from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import unittest
from unittest.mock import patch

import tests.test_promoted_exterior_campaign_flow as flow_canary
import windows_solver.response_batches as response_batches
from windows_solver.contracts import canonical_json_bytes
from windows_solver.response_batches import (
    CampaignLeafRecord,
    _authenticated_solved_leaf_lookup,
    _component_stage_signed_error_channels,
    _validate_component_result,
    build_campaign_selection,
    run_campaign_selection,
    scientific_computation_identity_sha256,
    validate_campaign_checkpoint,
)
from windows_solver.response_engine import ComponentResult
from windows_solver.solved_leaf_cache import (
    SolvedLeafLookupStatus,
    SolvedLeafStore,
)


class PromotedExteriorPersistenceTamperTests(unittest.TestCase):
    """Persistence must not turn coherently resealed forgeries into evidence."""

    def setUp(self) -> None:
        # Reuse the full-chain canary as a utility by composition.  Importing its
        # module (rather than its TestCase class) avoids collecting its tests here.
        self.canary = flow_canary.PromotedExteriorCampaignFlowCanary(
            "test_leaf42_native_80_stage_uses_explicit_na_response_comparison"
        )
        self.canary.setUp()
        self.addCleanup(self.canary.doCleanups)

        self.plan = self.canary.plan
        self.leaf = self.canary.leaf
        self.selection = build_campaign_selection(
            self.plan,
            role="primary",
            leaf_ids=(self.leaf.leaf_id,),
        )
        self.backend = self.canary._native_backend()
        workers = {
            digits: self.canary._precision_backend(self.leaf, digits)
            for digits in (80, 120)
        }
        self.honest_checkpoint = self.canary.root / "honest-leaf-42.json"
        with patch(
            "windows_solver.response_batches.run_component",
            return_value=self.canary._binary_result(),
        ), patch.object(
            self.backend,
            "_julia_precision_backend_for",
            side_effect=lambda job, digits, refinement=0: workers[digits],
        ):
            self.summary = run_campaign_selection(
                self.plan,
                self.selection,
                self.backend,
                self.honest_checkpoint,
                resume=False,
            )

        validated = validate_campaign_checkpoint(
            self.plan, self.honest_checkpoint
        )
        self.assertEqual(validated.records, self.summary.records)
        self.assertEqual(len(self.summary.records), 1)
        self.record = self.summary.records[0]
        self.assertEqual(
            tuple(stage.outcome.digits for stage in self.record.stages),
            (64, 80),
        )
        self.assertTrue(
            _validate_component_result(
                self.leaf, self.record.stages[1].outcome
            )
        )

    def _rebuild_promoted_outcome(
        self,
        *,
        component_changes: dict[str, object] | None = None,
        precision_delta: complex = 0.0j,
        precision_ladder_applicable: bool = False,
        self_refinement_enclosed: bool | None = None,
        discrepancy_from_previous_abs: float | None = None,
        discrepancy_enclosed: bool | None = None,
    ):
        honest = self.record.stages[1].outcome
        component = dict(honest.component_result)
        component.update(component_changes or {})
        result = ComponentResult.from_mapping(component["result"])
        local_radius = sum(result.error_channels.values()) + abs(precision_delta)
        return replace(
            honest,
            component_result=component,
            local_disk_radius_abs=local_radius,
            signed_error_channels=_component_stage_signed_error_channels(
                component,
                result,
                repeat_applicable=False,
                precision_delta=precision_delta,
                precision_ladder_applicable=precision_ladder_applicable,
            ),
            self_refinement_enclosed=self_refinement_enclosed,
            discrepancy_from_previous_abs=discrepancy_from_previous_abs,
            discrepancy_enclosed=discrepancy_enclosed,
        )

    def _resealed_record(self, promoted_outcome) -> CampaignLeafRecord:
        promoted_stage = replace(
            self.record.stages[1], outcome=promoted_outcome
        )
        record = replace(
            self.record,
            stages=(self.record.stages[0], promoted_stage),
        )
        # This parser verifies the recomputed stage and leaf seals.  A failure
        # below therefore cannot be attributed to stale inner digests.
        self.assertEqual(
            CampaignLeafRecord.from_mapping(record.to_mapping()), record
        )
        return record

    def _write_resealed_checkpoint(
        self, name: str, record: CampaignLeafRecord
    ) -> Path:
        value = response_batches._checkpoint_mapping(
            self.plan,
            self.selection,
            (record,),
            self.summary.attempts,
        )
        path = self.canary.root / f"{name}.json"
        path.write_bytes(canonical_json_bytes(value))
        return path

    def _root_delta_forgery(self):
        promoted = self.record.stages[1].outcome
        promoted_result = ComponentResult.from_mapping(
            promoted.component_result["result"]
        )
        binary_result = ComponentResult.from_mapping(
            self.record.stages[0].outcome.component_result["result"]
        )
        comparison_root_omega = (
            binary_result.baseline.omega + complex(1.0e-12, 0.0)
        )
        root_delta = promoted_result.baseline.omega - comparison_root_omega
        self.assertGreater(abs(root_delta), 0.0)
        self.assertIsNone(binary_result.response)
        forged = self._rebuild_promoted_outcome(
            component_changes={
                "precision_ladder_discrepancy_applicable": True,
                "precision_ladder_discrepancy_reason": None,
            },
            precision_delta=root_delta,
            precision_ladder_applicable=True,
            self_refinement_enclosed=None,
            discrepancy_from_previous_abs=abs(root_delta),
            discrepancy_enclosed=(
                abs(root_delta)
                <= sum(promoted_result.error_channels.values())
                + self.record.stages[0].outcome.local_disk_radius_abs
            ),
        )
        # The fixed-root payload is locally well formed.  Its only lie is that a
        # root-frequency delta came from response space, whose predecessor value
        # is unavailable.  Keep this explicit to prevent a refinement false
        # positive from weakening the test.
        self.assertIsNone(forged.self_refinement_enclosed)
        self.assertTrue(_validate_component_result(self.leaf, forged))
        return forged

    def test_resealed_fixed_root_semantic_tampering_fails_checkpoint_reload(self):
        """Catches validators that trust canonical bytes without stage semantics."""

        applicability = self._rebuild_promoted_outcome(
            component_changes={
                "precision_ladder_discrepancy_applicable": True,
                "precision_ladder_discrepancy_reason": None,
            },
            precision_delta=0.0j,
            precision_ladder_applicable=True,
            self_refinement_enclosed=None,
            discrepancy_from_previous_abs=0.0,
            discrepancy_enclosed=True,
        )
        self.assertTrue(_validate_component_result(self.leaf, applicability))

        cases = {
            "skip-reason": self._rebuild_promoted_outcome(
                component_changes={
                    "self_refinement_skipped_reason": "NOT_REQUIRED",
                },
                precision_ladder_applicable=False,
            ),
            "applicability": applicability,
            "fabricated-refinement": self._rebuild_promoted_outcome(
                precision_ladder_applicable=False,
                self_refinement_enclosed=True,
            ),
            "root-delta-as-response-delta": self._root_delta_forgery(),
        }
        expected_error = {
            "skip-reason": "execution evidence is invalid",
            "applicability": "precision applicability is inconsistent",
            "fabricated-refinement": "execution evidence is invalid",
            "root-delta-as-response-delta": (
                "precision applicability is inconsistent"
            ),
        }
        for name, forged_outcome in cases.items():
            with self.subTest(name=name):
                forged_record = self._resealed_record(forged_outcome)
                path = self._write_resealed_checkpoint(name, forged_record)
                with self.assertRaisesRegex(ValueError, expected_error[name]):
                    validate_campaign_checkpoint(self.plan, path)

    def test_semantically_tampered_published_record_is_quarantined(self):
        """Catches solved-cache reuse that authenticates only receipt hashes."""

        forged_record = self._resealed_record(self._root_delta_forgery())
        contract = self.backend.scientific_execution_contract_for(self.leaf)
        identity = scientific_computation_identity_sha256(
            self.plan,
            self.leaf,
            scientific_execution_contract=contract,
        )
        store = SolvedLeafStore(self.canary.root / "tampered-solved-cache")
        published_path = store.publish(
            scientific_identity_sha256=identity,
            leaf_id=self.leaf.leaf_id,
            record=forged_record.to_mapping(),
            source_type="originating-campaign",
        )
        published_bytes = published_path.read_bytes()
        self.assertIs(
            store.lookup(identity, self.leaf.leaf_id).status,
            SolvedLeafLookupStatus.HIT,
        )

        authenticated = _authenticated_solved_leaf_lookup(
            self.plan,
            self.leaf,
            store,
            scientific_execution_contract=contract,
        )

        self.assertIs(
            authenticated.status, SolvedLeafLookupStatus.CORRUPT
        )
        self.assertFalse(published_path.exists())
        quarantined = tuple(
            (store.root / "quarantine").glob(
                f"{identity}.corrupt-*.json"
            )
        )
        self.assertEqual(len(quarantined), 1)
        self.assertEqual(quarantined[0].read_bytes(), published_bytes)


if __name__ == "__main__":
    unittest.main()
