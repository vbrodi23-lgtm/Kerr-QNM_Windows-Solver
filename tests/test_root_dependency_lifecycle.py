"""Deterministic production-boundary coverage for root-only lifecycle state."""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from windows_solver.campaign_policy import (
    PromotionQueueKind,
    SurveyDisposition,
    empty_schema11_checkpoint,
)
from windows_solver.campaign_recovery import RecoverySelection
from windows_solver.campaign_runtime import AuthenticatedRootSealProvider
from windows_solver.campaign_survey import Binary64PassOutcome, run_binary64_survey
from windows_solver.response_batches import (
    PrecisionCapabilities,
    build_campaign_plan,
    build_campaign_selection,
    scientific_computation_identity_sha256,
)
from windows_solver.response_engine import NumericalPolicy, VettedNativeDeterminantKernel
from windows_solver.root_evidence import AuthenticatedRootEvidence
from windows_solver.root_readout_cache import RootEvidenceStore
from windows_solver.solved_leaf_cache import SolvedLeafStore


class RootDependencyLifecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.plan = build_campaign_plan(
            policy=NumericalPolicy(),
            backend_identity=VettedNativeDeterminantKernel.identity,
            precision_capabilities=PrecisionCapabilities((64, 80)),
        )
        horizon = next(
            leaf for leaf in self.plan.leaves
            if leaf.mechanism_id == "horizon-admittance" and leaf.role == "primary"
        )
        self.horizon = horizon
        self.siblings = tuple(
            leaf for leaf in self.plan.leaves
            if leaf.leaf.mode == horizon.leaf.mode
            and leaf.job.sampling_coordinate == horizon.job.sampling_coordinate
            and leaf.mechanism_id != "horizon-admittance"
        )[:4]
        self.assertEqual(4, len(self.siblings))
        self.selection = build_campaign_selection(
            self.plan,
            role=horizon.role,
            leaf_ids=(horizon.leaf_id,),
        )
        self.recovery = RecoverySelection(
            campaign_id=self.plan.campaign_id,
            selection_id=self.selection.selection_id,
            ordered_leaf_ids=(horizon.leaf_id,),
            roles={horizon.leaf_id: horizon.role},
            scientific_identities={
                horizon.leaf_id: scientific_computation_identity_sha256(
                    self.plan, horizon
                )
            },
        )

    def test_root_publishes_before_horizon_response_and_survives_restart(self) -> None:
        """A horizon response promotion cannot withhold its background root."""

        calls: list[str] = []
        with tempfile.TemporaryDirectory() as temporary:
            checkpoint_path = Path(temporary) / "checkpoint.json"
            checkpoint = empty_schema11_checkpoint(
                self.plan.campaign_id, self.selection.selection_id
            )
            evidence_store = RootEvidenceStore.for_checkpoint(checkpoint_path)
            provider = AuthenticatedRootSealProvider(
                self.plan,
                self.selection,
                checkpoint,
                SolvedLeafStore(Path(temporary) / "solved-leaves"),
                evidence_store,
            )

            def lookup(leaf):
                calls.append(f"root:{leaf.leaf_id}")
                return provider.lookup(leaf)

            def horizon_response(leaf) -> Binary64PassOutcome:
                self.assertEqual([f"root:{leaf.leaf_id}"], calls)
                calls.append(f"response:{leaf.leaf_id}")
                return Binary64PassOutcome(
                    disposition=SurveyDisposition.PROMOTION_PENDING_RESPONSE,
                    operation_identity="binary64-horizon-production/v2",
                    reason_code="HORIZON_ARITHMETIC_INADEQUATE",
                    queue_kind=PromotionQueueKind.RESPONSE,
                    minimum_requested_tier="BF80",
                )

            result = run_binary64_survey(
                self.plan,
                self.recovery,
                checkpoint,
                checkpoint_path=checkpoint_path,
                root_seal_lookup=lookup,
                native_backend_factory=lambda: self.fail(
                    "horizon-only lifecycle test must not construct an exterior backend"
                ),
                horizon_runner=horizon_response,
                produced_record_builder=lambda *args: self.fail(
                    "horizon-only lifecycle test must not build an exterior record"
                ),
            )

            horizon_seal = provider.lookup(self.horizon)
            sibling_seals = tuple(provider.lookup(leaf) for leaf in self.siblings)
            restarted = AuthenticatedRootSealProvider(
                self.plan,
                self.selection,
                result.checkpoint,
                SolvedLeafStore(Path(temporary) / "solved-leaves"),
                evidence_store,
            )
            restarted_sibling = restarted.lookup(self.siblings[0])
            evidence_count = evidence_store.stored_count

        self.assertEqual(
            [f"root:{self.horizon.leaf_id}", f"response:{self.horizon.leaf_id}"],
            calls,
        )
        self.assertIsNotNone(horizon_seal)
        self.assertTrue(all(seal == horizon_seal for seal in sibling_seals))
        self.assertEqual(horizon_seal, restarted_sibling)
        self.assertEqual(1, evidence_count)
        self.assertEqual([], result.checkpoint["system_failures"])
        self.assertEqual(
            horizon_seal.root_seal_sha256,
            result.checkpoint["promotion_queue"]["entries"][0]["source_root_seal_sha256"],
        )

    def test_conflicting_root_evidence_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = RootEvidenceStore(Path(temporary) / "root-evidence")
            original = AuthenticatedRootEvidence.from_bound_leaf(self.horizon)
            store.publish(original)
            conflict = AuthenticatedRootEvidence.from_seal(
                self.horizon,
                fixed_root=self.horizon.job.root.omega + 0.125,
                branch_identity=self.horizon.job.root.branch_id,
                source_receipt_sha256="f" * 64,
            )

            with self.assertRaisesRegex(ValueError, "ROOT_SEAL_CONFLICT"):
                store.publish(conflict)

    def test_static_guard_root_publication_precedes_horizon_response(self) -> None:
        """Keep root lifecycle independent from the horizon-response branch."""

        source_root = Path(__file__).parents[1] / "src" / "windows_solver"
        survey_source = (source_root / "campaign_survey.py").read_text(encoding="utf-8")
        runtime_source = (source_root / "campaign_runtime.py").read_text(
            encoding="utf-8"
        )

        self.assertLess(
            survey_source.index("seal = guarded(lambda: root_seal_lookup(leaf))"),
            survey_source.index("outcome = guarded(lambda: horizon_runner(leaf))"),
        )
        self.assertIn(
            "root_evidence_store = RootEvidenceStore.for_checkpoint(checkpoint_path)",
            runtime_source,
        )
        self.assertIn("AuthenticatedRootEvidence.from_bound_leaf", runtime_source)
        self.assertIn("self._root_evidence_store.publish(evidence)", runtime_source)


if __name__ == "__main__":
    unittest.main()
