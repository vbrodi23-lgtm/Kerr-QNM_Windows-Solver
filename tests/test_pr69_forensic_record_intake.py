"""PR69 regression matrix for mixed-version record intake and root salvage."""

from __future__ import annotations

import ast
import copy
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from windows_solver.campaign_policy import (
    PromotionQueueKind,
    SurveyDisposition,
    add_numerical_record,
    append_promotion,
    empty_schema11_checkpoint,
)
from windows_solver.campaign_record_intake import (
    CampaignRecordScientificStatus,
    assess_campaign_record_for_current_runtime,
)
from windows_solver.campaign_recovery import RecoverySelection
from windows_solver.campaign_recovery import recover_campaign
from windows_solver.campaign_runtime import (
    AuthenticatedRootSealProvider,
    run_native_binary64_pass,
)
from windows_solver.campaign_survey import (
    AuthenticatedRootSeal,
    Binary64PassOutcome,
    PromotedPassOutcome,
    run_binary64_survey,
    run_promoted_survey,
)
from windows_solver.contracts import canonical_json_bytes
from windows_solver.native_response_kernel import VettedNativeDeterminantKernel
from windows_solver.response_batches import (
    PrecisionCapabilities,
    build_campaign_plan,
    build_campaign_selection,
    forensic_v2_scientific_computation_identity_sha256,
    import_campaign_checkpoint_to_solved_leaf_store,
    scientific_computation_identity_material,
    scientific_computation_identity_sha256,
)
from windows_solver.response_engine import (
    BINARY64_HORIZON_COMPONENT,
    BINARY64_HORIZON_OPERATION_V3,
    BINARY64_HORIZON_RESPONSE_METHOD,
    FINITE_RADIUS_ENDPOINT_WEDGE_DETERMINANT_CONVENTION,
    M02_HORIZON_EXTERIOR_RESPONSE_MATH_IDENTITY,
    NumericalPolicy,
    PR69_COMMIT9_HUMAN_MATH_REVIEW_SHA256,
)
from windows_solver.root_evidence import AuthenticatedRootEvidence
from windows_solver.root_readout_cache import RootEvidenceStore
from windows_solver.solved_leaf_cache import SolvedLeafLookupStatus, SolvedLeafStore
from windows_solver.structural_diagnostics import StructuralDiagnosticSession

from tests.test_pr66_terminal_cache_wiring import _terminal_survey_record
from tests.test_pr69_commit10_recovery import Commit10RecoveryTests


_V2_OPERATION = "binary64-horizon-production/" + "v2"
_V2_COMPONENT = "binary64-horizon-analytic-component/" + "v1"
_V2_METHOD = "binary64-fixed-root-horizon-response/" + "v1"
_FROZEN_V2_IDENTITY = (
    "84f765093afa21f76ba4d150e8613d100c6bbaa6b1109283092c0d3ed2f3cdbe"
)
_FROZEN_IDENTITY_TEST_BACKEND = replace(
    VettedNativeDeterminantKernel.identity,
    runtime_fingerprint=(
        "cpython-3.12.13-linux-python-64bit-"
        "gsn-input-julia-exact-f-u-cache-contract-1-"
        "adapted-source-native-gsn-adapter-contract-2"
    ),
)


def _sha256(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _rehash_stage(stage: dict[str, object]) -> None:
    stage["stage_sha256"] = _sha256(
        {key: value for key, value in stage.items() if key != "stage_sha256"}
    )


def _rehash_record(record: dict[str, object]) -> None:
    record["record_sha256"] = _sha256(
        {key: value for key, value in record.items() if key != "record_sha256"}
    )


def _plan_leaf_and_records():
    fixture = Commit10RecoveryTests()
    plan, leaf = fixture._plan_and_leaf()
    v2 = fixture._authenticated_v2_horizon_record(plan, leaf)
    v2["scientific_computation_identity"] = (
        forensic_v2_scientific_computation_identity_sha256(plan, leaf)
    )
    _rehash_record(v2)

    current = copy.deepcopy(v2)
    stage = current["stages"][0]
    result = stage["component_result"]["result"]
    stage["operation_identity"] = BINARY64_HORIZON_OPERATION_V3
    result["component_scientific_identity"] = BINARY64_HORIZON_COMPONENT
    result["response_method"] = BINARY64_HORIZON_RESPONSE_METHOD
    _rehash_stage(stage)
    current["scientific_computation_identity"] = (
        scientific_computation_identity_sha256(plan, leaf)
    )
    current["horizon_mathematics"] = copy.deepcopy(
        result["analytic_horizon_evidence"]["mathematics"]
    )
    _rehash_record(current)
    return plan, leaf, v2, current


def _frozen_identity_plan_and_horizon_leaf():
    plan = build_campaign_plan(
        policy=NumericalPolicy(),
        backend_identity=_FROZEN_IDENTITY_TEST_BACKEND,
        precision_capabilities=PrecisionCapabilities((64, 80)),
    )
    leaf = next(
        item
        for item in plan.leaves
        if item.role == "primary" and item.mechanism_id == "horizon-admittance"
    )
    return plan, leaf


def _one_leaf_recovery(plan, selection, leaf) -> RecoverySelection:
    return RecoverySelection(
        campaign_id=plan.campaign_id,
        selection_id=selection.selection_id,
        ordered_leaf_ids=(leaf.leaf_id,),
        roles={leaf.leaf_id: leaf.role},
        scientific_identities={
            leaf.leaf_id: scientific_computation_identity_sha256(plan, leaf)
        },
    )


def _queue_checkpoint(plan, selection, leaf):
    return append_promotion(
        empty_schema11_checkpoint(plan.campaign_id, selection.selection_id),
        leaf_id=leaf.leaf_id,
        queue_kind=PromotionQueueKind.RESPONSE,
        reason_code="HORIZON_ARITHMETIC_INADEQUATE",
        minimum_requested_tier="BF80",
        scientific_computation_identity=scientific_computation_identity_sha256(
            plan, leaf
        ),
        source_root_seal_sha256="a" * 64,
    )


def _pending_horizon_outcome() -> Binary64PassOutcome:
    return Binary64PassOutcome(
        disposition=SurveyDisposition.PROMOTION_PENDING_RESPONSE,
        operation_identity=BINARY64_HORIZON_OPERATION_V3,
        reason_code="HORIZON_ARITHMETIC_INADEQUATE",
        queue_kind=PromotionQueueKind.RESPONSE,
        minimum_requested_tier="BF80",
    )


class HorizonScientificIdentityTests(unittest.TestCase):
    def test_v3_horizon_identity_differs_from_frozen_v2_identity(self) -> None:
        plan, leaf = _frozen_identity_plan_and_horizon_leaf()

        self.assertEqual(
            _FROZEN_V2_IDENTITY,
            forensic_v2_scientific_computation_identity_sha256(plan, leaf),
        )
        self.assertNotEqual(
            _FROZEN_V2_IDENTITY,
            scientific_computation_identity_sha256(plan, leaf),
        )

    def test_horizon_identity_binds_operation_component_method_math_and_review_receipt(
        self,
    ) -> None:
        plan, leaf = _frozen_identity_plan_and_horizon_leaf()

        material = scientific_computation_identity_material(plan, leaf)

        self.assertEqual(
            {
                "binary64_operation": BINARY64_HORIZON_OPERATION_V3,
                "component_identity": BINARY64_HORIZON_COMPONENT,
                "response_method": BINARY64_HORIZON_RESPONSE_METHOD,
                "mathematical_decision": (
                    M02_HORIZON_EXTERIOR_RESPONSE_MATH_IDENTITY
                ),
                "determinant_convention": (
                    FINITE_RADIUS_ENDPOINT_WEDGE_DETERMINANT_CONVENTION
                ),
                "human_review_receipt": PR69_COMMIT9_HUMAN_MATH_REVIEW_SHA256,
            },
            material["binary64_horizon_mathematics"],
        )

    def test_horizon_identity_change_does_not_change_exterior_identities(self) -> None:
        plan, _leaf = _frozen_identity_plan_and_horizon_leaf()
        exterior = next(
            item
            for item in plan.leaves
            if item.role == "primary" and item.mechanism_id != "horizon-admittance"
        )

        self.assertNotIn(
            "binary64_horizon_mathematics",
            scientific_computation_identity_material(plan, exterior),
        )
        self.assertEqual(
            "0fa77aea7602286a511fc48056d64196dbdcec904e1a4ff4ca14ba5c5dd669c6",
            scientific_computation_identity_sha256(plan, exterior),
        )


class CampaignRecordIntakeTests(unittest.TestCase):
    def test_authenticated_v2_horizon_is_forensic_not_corrupt(self) -> None:
        plan, leaf, v2, _current = _plan_leaf_and_records()

        intake = assess_campaign_record_for_current_runtime(
            plan, leaf.leaf_id, v2
        )

        self.assertEqual(
            CampaignRecordScientificStatus.FORENSIC_V2_STALE,
            intake.scientific_status,
        )
        self.assertFalse(intake.response_admissible)
        self.assertTrue(intake.forensic_only)
        self.assertEqual(
            "HORIZON_RESPONSE_V2_SCIENTIFICALLY_STALE", intake.reason_code
        )
        self.assertIsNotNone(intake.root_seed)
        self.assertEqual("SEED_ONLY", intake.root_seed.evidence_level)
        self.assertIsNone(intake.root_seed.root_uncertainty_radius)
        self.assertIsNone(intake.root_seed.root_disk)

    def test_corrupt_v2_horizon_fails_closed(self) -> None:
        plan, leaf, v2, _current = _plan_leaf_and_records()
        v2["stages"][0]["stage_sha256"] = "0" * 64
        _rehash_record(v2)

        with self.assertRaisesRegex(ValueError, "CORRUPT"):
            assess_campaign_record_for_current_runtime(plan, leaf.leaf_id, v2)

    def test_mixed_v2_v3_horizon_fails_closed(self) -> None:
        plan, leaf, v2, current = _plan_leaf_and_records()
        mixed = copy.deepcopy(current)
        mixed["stages"] = [copy.deepcopy(v2["stages"][0]), mixed["stages"][0]]
        _rehash_record(mixed)

        with self.assertRaisesRegex(ValueError, "MIXED_V2_V3_INVALID"):
            assess_campaign_record_for_current_runtime(plan, leaf.leaf_id, mixed)

    def test_current_v3_horizon_remains_admissible(self) -> None:
        plan, leaf, _v2, current = _plan_leaf_and_records()

        intake = assess_campaign_record_for_current_runtime(
            plan, leaf.leaf_id, current
        )

        self.assertEqual(CampaignRecordScientificStatus.CURRENT, intake.scientific_status)
        self.assertTrue(intake.response_admissible)
        self.assertFalse(intake.forensic_only)
        self.assertIsNone(intake.reason_code)


class RootProviderForensicTests(unittest.TestCase):
    def _provider(self, *, checkpoint_record: bool, solved_record: bool):
        plan, leaf, v2, _current = _plan_leaf_and_records()
        selection = build_campaign_selection(
            plan, role=leaf.role, leaf_ids=(leaf.leaf_id,)
        )
        temporary = tempfile.TemporaryDirectory()
        root = Path(temporary.name)
        checkpoint = empty_schema11_checkpoint(plan.campaign_id, selection.selection_id)
        if checkpoint_record:
            checkpoint = add_numerical_record(checkpoint, v2)
        solved = SolvedLeafStore(root / "solved")
        if solved_record:
            solved.publish(
                scientific_identity_sha256=(
                    forensic_v2_scientific_computation_identity_sha256(plan, leaf)
                ),
                leaf_id=leaf.leaf_id,
                record=v2,
                source_type="originating-campaign",
            )
        evidence = RootEvidenceStore(root / "root-evidence")
        provider = AuthenticatedRootSealProvider(
            plan, selection, checkpoint, solved, evidence
        )
        return temporary, plan, leaf, provider, evidence

    def test_root_provider_does_not_abort_on_v2_record_in_checkpoint(self) -> None:
        temporary, _plan, leaf, provider, _evidence = self._provider(
            checkpoint_record=True, solved_record=False
        )
        with temporary:
            self.assertIsNotNone(provider.lookup(leaf))

    def test_root_provider_does_not_abort_on_v2_record_in_solved_leaf_store(self) -> None:
        temporary, _plan, leaf, provider, _evidence = self._provider(
            checkpoint_record=False, solved_record=True
        )
        with temporary:
            self.assertIsNotNone(provider.lookup(leaf))

    def test_root_provider_salvages_at_most_seed_only_root_from_v2(self) -> None:
        temporary, _plan, leaf, provider, _evidence = self._provider(
            checkpoint_record=True, solved_record=False
        )
        with temporary:
            provider.lookup(leaf)
            evidence = provider.evidence_for(leaf)
            self.assertEqual("SEED_ONLY", evidence.evidence_level)
            self.assertIsNone(evidence.root_uncertainty_radius)

    def test_root_provider_never_salvages_v2_response_or_root_uncertainty(self) -> None:
        temporary, _plan, leaf, provider, _evidence = self._provider(
            checkpoint_record=False, solved_record=True
        )
        with temporary:
            provider.lookup(leaf)
            evidence = provider.evidence_for(leaf)
            self.assertIsNone(evidence.root_disk)
            self.assertFalse(hasattr(evidence, "response_disk"))
            self.assertFalse(hasattr(evidence, "horizon_response"))

    def test_root_provider_still_aborts_on_conflicting_authenticated_roots(self) -> None:
        plan, leaf, v2, _current = _plan_leaf_and_records()
        sibling = next(
            item
            for item in plan.leaves
            if item.leaf.mode == leaf.leaf.mode
            and item.job.sampling_coordinate == leaf.job.sampling_coordinate
            and item.mechanism_id != "horizon-admittance"
        )
        selection = build_campaign_selection(
            plan, role=leaf.role, leaf_ids=(leaf.leaf_id, sibling.leaf_id)
        )
        checkpoint = add_numerical_record(
            empty_schema11_checkpoint(plan.campaign_id, selection.selection_id), v2
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            solved = SolvedLeafStore(root / "solved")
            exterior = _terminal_survey_record(
                plan, sibling, centre_real_shift=0.125
            )
            solved.publish(
                scientific_identity_sha256=scientific_computation_identity_sha256(
                    plan, sibling
                ),
                leaf_id=sibling.leaf_id,
                record=exterior,
                source_type="originating-campaign",
            )
            provider = AuthenticatedRootSealProvider(
                plan,
                selection,
                checkpoint,
                solved,
                RootEvidenceStore(root / "root-evidence"),
            )

            with self.assertRaisesRegex(ValueError, "ROOT_SEAL_CONFLICT"):
                provider.lookup(leaf)


class SchedulerForensicTests(unittest.TestCase):
    def test_v2_cache_record_is_not_counted_as_cache_reuse(self) -> None:
        plan, leaf, v2, _current = _plan_leaf_and_records()
        selection = build_campaign_selection(
            plan, role=leaf.role, leaf_ids=(leaf.leaf_id,)
        )
        recovery = _one_leaf_recovery(plan, selection, leaf)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = SolvedLeafStore(root / "solved")
            store.publish(
                scientific_identity_sha256=(
                    forensic_v2_scientific_computation_identity_sha256(plan, leaf)
                ),
                leaf_id=leaf.leaf_id,
                record=v2,
                source_type="originating-campaign",
            )
            session = StructuralDiagnosticSession.open(
                checkpoint_path=root / "checkpoint.json",
                session_id="v2-binary64-cache",
                campaign_id=plan.campaign_id,
                selection_id=selection.selection_id,
            )
            result = run_binary64_survey(
                plan,
                recovery,
                empty_schema11_checkpoint(plan.campaign_id, selection.selection_id),
                checkpoint_path=root / "checkpoint.json",
                root_seal_lookup=lambda _leaf: AuthenticatedRootSeal(
                    fixed_root=leaf.job.root.omega,
                    branch_identity=leaf.job.root.branch_id,
                    root_seal_sha256="a" * 64,
                ),
                native_backend_factory=lambda: self.fail("unexpected backend"),
                horizon_runner=lambda _leaf: _pending_horizon_outcome(),
                produced_record_builder=lambda *_args: self.fail("unexpected record"),
                provisional_stage_committed=lambda *_args: self.fail(
                    "unexpected provisional stage"
                ),
                solved_leaf_store=store,
                diagnostic_session=session,
            )
            events = session.final_events(100)
            session.close_completed()

        self.assertEqual(0, result.cache_reused_count)
        self.assertEqual([], result.checkpoint["records"])
        self.assertEqual({}, result.checkpoint["evidence_ledger"])
        self.assertEqual(
            "PROMOTION_PENDING_RESPONSE",
            result.checkpoint["survey_pass_ledger"]["binary64"][leaf.leaf_id][
                "disposition"
            ],
        )
        self.assertTrue(
            any(event["event_kind"] == "FORENSIC_RECORD_EXCLUDED" for event in events)
        )

    def test_v2_cache_record_does_not_enter_current_checkpoint(self) -> None:
        self.test_v2_cache_record_is_not_counted_as_cache_reuse()

    def test_v2_cache_record_does_not_enter_evidence_ledger(self) -> None:
        self.test_v2_cache_record_is_not_counted_as_cache_reuse()

    def test_v2_cache_record_does_not_satisfy_binary64_pass(self) -> None:
        self.test_v2_cache_record_is_not_counted_as_cache_reuse()

    def test_current_v3_cache_hit_remains_zero_backend_work(self) -> None:
        plan, leaf, _v2, current = _plan_leaf_and_records()
        selection = build_campaign_selection(
            plan, role=leaf.role, leaf_ids=(leaf.leaf_id,)
        )
        recovery = _one_leaf_recovery(plan, selection, leaf)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = SolvedLeafStore(root / "solved")
            store.publish(
                scientific_identity_sha256=scientific_computation_identity_sha256(
                    plan, leaf
                ),
                leaf_id=leaf.leaf_id,
                record=current,
                source_type="originating-campaign",
            )
            result = run_binary64_survey(
                plan,
                recovery,
                empty_schema11_checkpoint(plan.campaign_id, selection.selection_id),
                checkpoint_path=root / "checkpoint.json",
                root_seal_lookup=lambda _leaf: self.fail("unexpected root lookup"),
                native_backend_factory=lambda: self.fail("unexpected backend"),
                horizon_runner=lambda _leaf: self.fail("unexpected horizon work"),
                produced_record_builder=lambda *_args: self.fail("unexpected record"),
                provisional_stage_committed=lambda *_args: self.fail(
                    "unexpected provisional stage"
                ),
                solved_leaf_store=store,
            )

        self.assertEqual(1, result.cache_reused_count)
        self.assertEqual(
            canonical_json_bytes([current]),
            canonical_json_bytes(result.checkpoint["records"]),
        )

    def test_v2_cache_record_cannot_supersede_pending_promotion(self) -> None:
        plan, leaf, v2, _current = _plan_leaf_and_records()
        selection = build_campaign_selection(
            plan, role=leaf.role, leaf_ids=(leaf.leaf_id,)
        )
        recovery = _one_leaf_recovery(plan, selection, leaf)
        calls: list[str] = []
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = SolvedLeafStore(root / "solved")
            store.publish(
                scientific_identity_sha256=(
                    forensic_v2_scientific_computation_identity_sha256(plan, leaf)
                ),
                leaf_id=leaf.leaf_id,
                record=v2,
                source_type="originating-campaign",
            )
            result = run_promoted_survey(
                plan,
                recovery,
                _queue_checkpoint(plan, selection, leaf),
                checkpoint_path=root / "checkpoint.json",
                root_seal_lookup=lambda *_args: self.fail("unexpected root lookup"),
                provisional_stage_lookup=lambda *_args: None,
                backend_factory=lambda *_args: self.fail("unexpected backend"),
                primary_root_runner=lambda *_args: self.fail("unexpected root work"),
                horizon_runner=lambda _leaf: (
                    calls.append("horizon")
                    or PromotedPassOutcome(
                        disposition=SurveyDisposition.UNRESOLVED,
                        reason_code="HORIZON_LADDER_EXHAUSTED",
                        precision_tiers=("BF80",),
                    )
                ),
                produced_record_builder=lambda *_args: self.fail("unexpected record"),
                root_seal_publish=lambda *_args: self.fail("unexpected publish"),
                solved_leaf_store=store,
            )

        self.assertEqual(["horizon"], calls)
        self.assertEqual(0, result.cache_reused_count)
        self.assertEqual(
            "UNRESOLVED",
            result.checkpoint["promotion_queue"]["entries"][0]["disposition"],
        )

    def test_current_v3_terminal_record_can_supersede_pending_promotion(self) -> None:
        plan, leaf, _v2, current = _plan_leaf_and_records()
        selection = build_campaign_selection(
            plan, role=leaf.role, leaf_ids=(leaf.leaf_id,)
        )
        recovery = _one_leaf_recovery(plan, selection, leaf)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = SolvedLeafStore(root / "solved")
            store.publish(
                scientific_identity_sha256=scientific_computation_identity_sha256(
                    plan, leaf
                ),
                leaf_id=leaf.leaf_id,
                record=current,
                source_type="originating-campaign",
            )
            result = run_promoted_survey(
                plan,
                recovery,
                _queue_checkpoint(plan, selection, leaf),
                checkpoint_path=root / "checkpoint.json",
                root_seal_lookup=lambda *_args: self.fail("unexpected root lookup"),
                provisional_stage_lookup=lambda *_args: self.fail(
                    "unexpected predecessor"
                ),
                backend_factory=lambda *_args: self.fail("unexpected backend"),
                primary_root_runner=lambda *_args: self.fail("unexpected root work"),
                horizon_runner=lambda _leaf: self.fail("unexpected horizon work"),
                produced_record_builder=lambda *_args: self.fail("unexpected record"),
                root_seal_publish=lambda *_args: self.fail("unexpected publish"),
                solved_leaf_store=store,
            )

        self.assertEqual(1, result.cache_reused_count)
        self.assertEqual(
            "SUPERSEDED_BY_CACHE",
            result.checkpoint["promotion_queue"]["entries"][0]["disposition"],
        )


class CheckpointAndProductionShapeTests(unittest.TestCase):
    def _run_native(self, checkpoint, plan, selection, recovery, store, path, session=None):
        fake_backend = SimpleNamespace(
            adapter=SimpleNamespace(kernel=object())
        )
        with (
            patch("windows_solver.campaign_runtime._binary64_backend", return_value=fake_backend),
            patch(
                "windows_solver.campaign_runtime._horizon_outcome",
                return_value=_pending_horizon_outcome(),
            ),
        ):
            return run_native_binary64_pass(
                plan,
                selection,
                recovery,
                checkpoint,
                checkpoint_path=path,
                solved_leaf_store=store,
                diagnostic_session=session,
            )

    def test_v2_checkpoint_record_is_not_republished_under_current_identity(self) -> None:
        plan, leaf, v2, _current = _plan_leaf_and_records()
        selection = build_campaign_selection(
            plan, role=leaf.role, leaf_ids=(leaf.leaf_id,)
        )
        recovery = _one_leaf_recovery(plan, selection, leaf)
        checkpoint = add_numerical_record(
            empty_schema11_checkpoint(plan.campaign_id, selection.selection_id), v2
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = SolvedLeafStore(root / "solved")
            result = self._run_native(
                checkpoint,
                plan,
                selection,
                recovery,
                store,
                root / "checkpoint.json",
            )
            lookup = store.lookup_readonly(
                scientific_computation_identity_sha256(plan, leaf), leaf.leaf_id
            )

        self.assertIsNot(lookup.status, SolvedLeafLookupStatus.HIT)
        self.assertEqual([], result.checkpoint["records"])

    def test_current_v3_checkpoint_record_is_republished_exactly(self) -> None:
        plan, leaf, _v2, current = _plan_leaf_and_records()
        selection = build_campaign_selection(
            plan, role=leaf.role, leaf_ids=(leaf.leaf_id,)
        )
        recovery = _one_leaf_recovery(plan, selection, leaf)
        checkpoint = add_numerical_record(
            empty_schema11_checkpoint(plan.campaign_id, selection.selection_id),
            current,
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = SolvedLeafStore(root / "solved")
            result = self._run_native(
                checkpoint,
                plan,
                selection,
                recovery,
                store,
                root / "checkpoint.json",
            )
            lookup = store.lookup_readonly(
                scientific_computation_identity_sha256(plan, leaf), leaf.leaf_id
            )

        self.assertIs(lookup.status, SolvedLeafLookupStatus.HIT)
        self.assertEqual(
            canonical_json_bytes(current),
            canonical_json_bytes(lookup.receipt["record"]),
        )
        self.assertEqual(
            canonical_json_bytes([current]),
            canonical_json_bytes(result.checkpoint["records"]),
        )

    def test_full_212_leaf_store_shape_excludes_v2_without_system_failure(self) -> None:
        plan, leaf, v2, _current = _plan_leaf_and_records()
        selection = build_campaign_selection(plan, role="all")
        self.assertEqual(212, len(selection.leaf_ids))
        recovery = _one_leaf_recovery(plan, selection, leaf)
        checkpoint = empty_schema11_checkpoint(plan.campaign_id, selection.selection_id)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            checkpoint_path = root / "checkpoint.json"
            store = SolvedLeafStore(root / "persistent-solved-leaves")
            store.publish(
                scientific_identity_sha256=(
                    forensic_v2_scientific_computation_identity_sha256(plan, leaf)
                ),
                leaf_id=leaf.leaf_id,
                record=v2,
                source_type="originating-campaign",
            )
            session = StructuralDiagnosticSession.open(
                checkpoint_path=checkpoint_path,
                session_id="full-forensic-production-shape",
                campaign_id=plan.campaign_id,
                selection_id=selection.selection_id,
            )
            result = self._run_native(
                checkpoint,
                plan,
                selection,
                recovery,
                store,
                checkpoint_path,
                session,
            )
            events = session.final_events(200)
            counters = session.forensic_record_counters()
            session.close_completed()

        self.assertIn(leaf.leaf_id, result.checkpoint["survey_pass_ledger"]["binary64"])
        self.assertEqual([], result.checkpoint["records"])
        self.assertEqual({}, result.checkpoint["evidence_ledger"])
        self.assertEqual([], result.checkpoint["system_failures"])
        forensic = [
            event for event in events
            if event["event_kind"] == "FORENSIC_RECORD_EXCLUDED"
        ]
        self.assertTrue(forensic)
        self.assertEqual(leaf.leaf_id, forensic[0]["leaf"]["leaf_id"])
        self.assertFalse(
            forensic[0]["compact_diagnostics"]["current_response_admissible"]
        )
        self.assertEqual(1, counters["forensic_records_discovered"])
        self.assertEqual(1, counters["forensic_records_excluded"])
        self.assertEqual(1, counters["forensic_root_seeds_salvaged"])
        self.assertEqual(1, counters["stale_cache_hits_prevented"])


class RecoveryAndImportIntakeTests(unittest.TestCase):
    def test_recovery_excludes_v2_from_solved_leaf_store(self) -> None:
        plan, leaf, v2, _current = _plan_leaf_and_records()
        selection = RecoverySelection(
            campaign_id=plan.campaign_id,
            selection_id="forensic-solved-recovery",
            ordered_leaf_ids=(leaf.leaf_id,),
            roles={leaf.leaf_id: leaf.role},
            scientific_identities={
                leaf.leaf_id: scientific_computation_identity_sha256(plan, leaf)
            },
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = SolvedLeafStore(root / "solved")
            store.publish(
                scientific_identity_sha256=(
                    forensic_v2_scientific_computation_identity_sha256(plan, leaf)
                ),
                leaf_id=leaf.leaf_id,
                record=v2,
                source_type="originating-campaign",
            )
            before = {
                path.name: path.read_bytes() for path in store.root.glob("*.json")
            }
            summary = recover_campaign(
                selection,
                output_path=root / "recovered.json",
                receipt_path=root / "receipt.json",
                solved_leaf_stores=(store.root,),
                record_intake_assessor=lambda leaf_id, record: (
                    assess_campaign_record_for_current_runtime(
                        plan, leaf_id, record
                    )
                ),
            )
            checkpoint = json.loads(
                (root / "recovered.json").read_text(encoding="utf-8")
            )
            after = {
                path.name: path.read_bytes() for path in store.root.glob("*.json")
            }

        self.assertEqual(0, summary.recovered_count)
        self.assertEqual(before, after)
        self.assertEqual([], checkpoint["records"])

    def test_cache_import_excludes_v2_and_publishes_current_v3(self) -> None:
        plan, leaf, v2, current = _plan_leaf_and_records()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            v2_path = root / "v2.json"
            current_path = root / "current.json"
            v2_checkpoint = add_numerical_record(
                empty_schema11_checkpoint(plan.campaign_id, "v2-import"), v2
            )
            current_checkpoint = add_numerical_record(
                empty_schema11_checkpoint(plan.campaign_id, "v3-import"), current
            )
            v2_path.write_bytes(canonical_json_bytes(v2_checkpoint))
            current_path.write_bytes(canonical_json_bytes(current_checkpoint))
            store = SolvedLeafStore(root / "solved")

            stale_summary = import_campaign_checkpoint_to_solved_leaf_store(
                plan, v2_path, store
            )
            current_summary = import_campaign_checkpoint_to_solved_leaf_store(
                plan, current_path, store
            )
            lookup = store.lookup_readonly(
                scientific_computation_identity_sha256(plan, leaf), leaf.leaf_id
            )

        self.assertEqual(0, stale_summary.imported_count)
        self.assertEqual(1, stale_summary.skipped_count)
        self.assertEqual(1, current_summary.imported_count)
        self.assertIs(SolvedLeafLookupStatus.HIT, lookup.status)
        self.assertEqual(
            canonical_json_bytes(current),
            canonical_json_bytes(lookup.receipt["record"]),
        )


class IntakeStaticGuardTests(unittest.TestCase):
    def test_stale_version_policy_has_one_owner(self) -> None:
        package = Path(__file__).parents[1] / "src" / "windows_solver"
        owner = (package / "campaign_record_intake.py").read_text(encoding="utf-8")
        survey = (package / "campaign_survey.py").read_text(encoding="utf-8")
        runtime = (package / "campaign_runtime.py").read_text(encoding="utf-8")

        self.assertIn("FORENSIC_V2_STALE", owner)
        self.assertNotIn("horizon_record_scientific_status", survey)
        self.assertNotIn("horizon_record_scientific_status", runtime)
        provider = ast.get_source_segment(
            runtime,
            next(
                node
                for node in ast.walk(ast.parse(runtime))
                if isinstance(node, ast.ClassDef)
                and node.name == "AuthenticatedRootSealProvider"
            ),
        )
        self.assertNotIn("validate_campaign_recovery_record", provider)
        for source in (survey, provider):
            tree = ast.parse(source)
            forbidden_comparisons = [
                node
                for node in ast.walk(tree)
                if isinstance(node, ast.Compare)
                and any(
                    isinstance(item, ast.Constant)
                    and item.value in {
                        "FORENSIC_V2_STALE",
                        _V2_OPERATION,
                    }
                    for item in (node.left, *node.comparators)
                )
            ]
            self.assertEqual([], forbidden_comparisons)


if __name__ == "__main__":
    unittest.main()
