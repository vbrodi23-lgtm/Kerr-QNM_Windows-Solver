"""PR66 R2: production terminal-cache discovery and reuse wiring."""

from __future__ import annotations

import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from windows_solver.campaign_policy import (
    PromotionQueueDisposition,
    PromotionQueueKind,
    SurveyDisposition,
    add_numerical_record,
    append_promotion,
    empty_schema11_checkpoint,
)
from windows_solver.campaign_failures import CampaignSystemFailure
from windows_solver.campaign_recovery import RecoverySelection
from windows_solver.campaign_runtime import (
    run_native_binary64_pass,
    run_native_promoted_pass,
)
from windows_solver.campaign_survey import Binary64PassOutcome, Binary64SurveyRun
from windows_solver.contracts import canonical_json_bytes
from windows_solver.evidence_discovery import EvidenceDiscoveryTotals
from windows_solver.native_response_kernel import VettedNativeDeterminantKernel
from windows_solver.response_batches import (
    PrecisionCapabilities,
    build_campaign_plan,
    build_campaign_selection,
    scientific_computation_identity_sha256,
)
from windows_solver.response_engine import NumericalPolicy
from windows_solver.solved_leaf_cache import SolvedLeafStore


def _sha256(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _recovery_selection(plan: object, selection: object) -> RecoverySelection:
    leaves = {leaf.leaf_id: leaf for leaf in plan.leaves}
    return RecoverySelection(
        campaign_id=plan.campaign_id,
        selection_id=selection.selection_id,
        ordered_leaf_ids=tuple(selection.leaf_ids),
        roles={leaf_id: leaves[leaf_id].role for leaf_id in selection.leaf_ids},
        scientific_identities={
            leaf_id: scientific_computation_identity_sha256(plan, leaves[leaf_id])
            for leaf_id in selection.leaf_ids
        },
    )


def _terminal_survey_record(
    plan: object, leaf: object, *, centre_real_shift: float = 0.0
) -> dict[str, object]:
    """A deterministic authenticated schema-11 terminal fixture, not physics."""

    centre = {
        "real": float(leaf.job.root.omega.real) + centre_real_shift,
        "imaginary": float(leaf.job.root.omega.imag),
    }
    stage_content = {
        "schema": "windows-solver.fixed-root-screening-stage/1",
        "operation_identity": "pr66-terminal-cache-fixture/v1",
        "precision_tier": "binary64",
        "fixed_root": dict(centre),
        "root_seal_sha256": "a" * 64,
        "branch_identity": leaf.job.root.branch_id,
        "batch": {
            "leaf_id": leaf.leaf_id,
            "job_id": leaf.job.job_id,
            "mechanism_id": leaf.mechanism_id,
            "branch_identity": leaf.job.root.branch_id,
        },
        "response_disk": {"centre": dict(centre)},
        "frequency_derivative_disk": {},
        "coordinate_derivative_disk": {},
        "root_correction_upper_bound": None,
        "determinant_certificate_status": "not-claimed",
    }
    stage = {**stage_content, "stage_sha256": _sha256(stage_content)}
    content = {
        "schema": "windows-solver.schema11-numerical-record/1",
        "leaf_id": leaf.leaf_id,
        "role": leaf.role,
        "state": "PRODUCED",
        "scientific_computation_identity": scientific_computation_identity_sha256(
            plan, leaf
        ),
        "retained_centre": dict(centre),
        "stages": [stage],
    }
    return {**content, "record_sha256": _sha256(content)}


class PromotedTerminalCacheWiringTests(unittest.TestCase):
    @staticmethod
    def _cache_context() -> tuple[object, object, object, object]:
        plan = build_campaign_plan(
            policy=NumericalPolicy(),
            backend_identity=VettedNativeDeterminantKernel.identity,
            precision_capabilities=PrecisionCapabilities((64, 80)),
        )
        leaves = tuple(
            item
            for item in plan.leaves
            if item.mechanism_id != "horizon-admittance" and item.role == "primary"
        )
        if len(leaves) < 2:
            raise AssertionError("test plan lacks two exterior leaves")
        return plan, leaves[0], leaves[1], leaves[2] if len(leaves) > 2 else leaves[1]

    def test_terminal_cache_discovery_reports_empty(self) -> None:
        """A fresh configured store is an attempted lookup, not a failure."""

        plan, leaf, _other, _third = self._cache_context()
        with tempfile.TemporaryDirectory() as temporary:
            store = SolvedLeafStore(Path(temporary) / "solved-leaves")
            lookup = store.lookup_readonly(
                scientific_computation_identity_sha256(plan, leaf), leaf.leaf_id
            )

        self.assertEqual("EMPTY", lookup.discovery.status.value)
        self.assertEqual(
            (0, 0, 0),
            (
                lookup.discovery.discovered_count,
                lookup.discovery.compatible_count,
                lookup.discovery.rejected_count,
            ),
        )

    def test_terminal_cache_discovery_reports_one_exact_match(self) -> None:
        """One exact terminal record is the one compatible reusable candidate."""

        plan, leaf, _other, _third = self._cache_context()
        identity = scientific_computation_identity_sha256(plan, leaf)
        with tempfile.TemporaryDirectory() as temporary:
            store = SolvedLeafStore(Path(temporary) / "solved-leaves")
            store.publish(
                scientific_identity_sha256=identity,
                leaf_id=leaf.leaf_id,
                record=_terminal_survey_record(plan, leaf),
                source_type="originating-campaign",
            )
            lookup = store.lookup_readonly(identity, leaf.leaf_id)

        self.assertEqual("HIT", lookup.discovery.status.value)
        self.assertEqual(
            (1, 1, 0),
            (
                lookup.discovery.discovered_count,
                lookup.discovery.compatible_count,
                lookup.discovery.rejected_count,
            ),
        )

    def test_terminal_cache_discovery_reports_nonmatching_content(self) -> None:
        """An unrelated terminal record is rejected rather than opportunistically reused."""

        plan, leaf, other, _third = self._cache_context()
        identity = scientific_computation_identity_sha256(plan, leaf)
        with tempfile.TemporaryDirectory() as temporary:
            store = SolvedLeafStore(Path(temporary) / "solved-leaves")
            store.publish(
                scientific_identity_sha256=scientific_computation_identity_sha256(
                    plan, other
                ),
                leaf_id=other.leaf_id,
                record=_terminal_survey_record(plan, other),
                source_type="originating-campaign",
            )
            lookup = store.lookup_readonly(identity, leaf.leaf_id)

        self.assertEqual("MISS", lookup.discovery.status.value)
        self.assertEqual(
            (1, 0, 1),
            (
                lookup.discovery.discovered_count,
                lookup.discovery.compatible_count,
                lookup.discovery.rejected_count,
            ),
        )

    def test_terminal_cache_discovery_reports_mixed_content(self) -> None:
        """Only the exact member of a mixed store becomes a reuse candidate."""

        plan, leaf, other, _third = self._cache_context()
        identity = scientific_computation_identity_sha256(plan, leaf)
        with tempfile.TemporaryDirectory() as temporary:
            store = SolvedLeafStore(Path(temporary) / "solved-leaves")
            for selected in (leaf, other):
                store.publish(
                    scientific_identity_sha256=scientific_computation_identity_sha256(
                        plan, selected
                    ),
                    leaf_id=selected.leaf_id,
                    record=_terminal_survey_record(plan, selected),
                    source_type="originating-campaign",
                )
            lookup = store.lookup_readonly(identity, leaf.leaf_id)

        self.assertEqual("HIT", lookup.discovery.status.value)
        self.assertEqual(
            (2, 1, 1),
            (
                lookup.discovery.discovered_count,
                lookup.discovery.compatible_count,
                lookup.discovery.rejected_count,
            ),
        )

    def test_terminal_cache_discovery_fails_closed_for_trusted_corruption(self) -> None:
        """Malformed data at the expected content address is not converted to a miss."""

        plan, leaf, _other, _third = self._cache_context()
        identity = scientific_computation_identity_sha256(plan, leaf)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "solved-leaves"
            root.mkdir()
            (root / f"{identity}.json").write_text("{broken", encoding="utf-8")
            lookup = SolvedLeafStore(root).lookup_readonly(identity, leaf.leaf_id)

        self.assertEqual("CORRUPT", lookup.discovery.status.value)

    def test_terminal_cache_discovery_is_cardinality_agnostic(self) -> None:
        """The store uses the same EMPTY/HIT accounting from zero to all 212 leaves."""

        plan = build_campaign_plan(
            policy=NumericalPolicy(),
            backend_identity=VettedNativeDeterminantKernel.identity,
            precision_capabilities=PrecisionCapabilities((64, 80)),
        )
        leaves = tuple(plan.leaves)
        self.assertGreaterEqual(len(leaves), 212)
        target = leaves[0]
        target_identity = scientific_computation_identity_sha256(plan, target)
        for count in (0, 1, 7, 20, 42, 212):
            with self.subTest(count=count), tempfile.TemporaryDirectory() as temporary:
                store = SolvedLeafStore(Path(temporary) / "solved-leaves")
                selected = leaves[:count]
                for leaf in selected:
                    store.publish(
                        scientific_identity_sha256=scientific_computation_identity_sha256(
                            plan, leaf
                        ),
                        leaf_id=leaf.leaf_id,
                        record=_terminal_survey_record(plan, leaf),
                        source_type="originating-campaign",
                    )
                lookup = store.lookup_readonly(target_identity, target.leaf_id)
                self.assertEqual(
                    "EMPTY" if count == 0 else "HIT",
                    lookup.discovery.status.value,
                )
                self.assertEqual(count, lookup.discovery.discovered_count)
                self.assertEqual(0 if count == 0 else 1, lookup.discovery.compatible_count)
                self.assertEqual(0 if count == 0 else count - 1, lookup.discovery.rejected_count)

    def test_conflicting_exact_terminal_sources_abort_before_backend_construction(
        self,
    ) -> None:
        """Two distinct records for one exact identity are a system failure, never newest-wins."""

        plan, leaf, _other, _third = self._cache_context()
        selection = build_campaign_selection(
            plan, role=leaf.role, leaf_ids=(leaf.leaf_id,)
        )
        recovery = _recovery_selection(plan, selection)
        identity = recovery.scientific_identities[leaf.leaf_id]
        checkpoint = add_numerical_record(
            append_promotion(
                empty_schema11_checkpoint(plan.campaign_id, selection.selection_id),
                leaf_id=leaf.leaf_id,
                queue_kind=PromotionQueueKind.RESPONSE,
                reason_code="PR66_TERMINAL_CACHE_CONFLICT_REGRESSION",
                minimum_requested_tier="BF40",
                scientific_computation_identity=identity,
                source_root_seal_sha256="b" * 64,
            ),
            _terminal_survey_record(plan, leaf),
        )

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = SolvedLeafStore(root / "solved-leaves")
            store.publish(
                scientific_identity_sha256=identity,
                leaf_id=leaf.leaf_id,
                record=_terminal_survey_record(plan, leaf, centre_real_shift=1.0e-6),
                source_type="originating-campaign",
            )
            with patch(
                "windows_solver.campaign_runtime.NativeCampaignStageBackend"
                ".from_selection",
                side_effect=AssertionError("conflict constructed a backend"),
            ), patch(
                "windows_solver.campaign_runtime._refresh_runtime_reports",
                side_effect=lambda _plan, _selection, _path, value, **_kwargs: dict(
                    value
                ),
            ):
                with self.assertRaisesRegex(
                    CampaignSystemFailure, "TERMINAL_CACHE_CONFLICT"
                ) as raised:
                    run_native_promoted_pass(
                        plan,
                        selection,
                        recovery,
                        checkpoint,
                        checkpoint_path=root / "checkpoint.json",
                        solved_leaf_store=store,
                    )

        self.assertEqual(
            "TerminalCacheConflictError", raised.exception.receipt["cause_type"]
        )

    def test_exact_terminal_cache_supersedes_promotion_before_backend_construction(
        self,
    ) -> None:
        """A valid terminal record makes a stale promoted request zero-work."""

        plan = build_campaign_plan(
            policy=NumericalPolicy(),
            backend_identity=VettedNativeDeterminantKernel.identity,
            precision_capabilities=PrecisionCapabilities((64, 80)),
        )
        leaf = next(
            item
            for item in plan.leaves
            if item.mechanism_id != "horizon-admittance" and item.role == "primary"
        )
        selection = build_campaign_selection(
            plan, role=leaf.role, leaf_ids=(leaf.leaf_id,)
        )
        recovery = _recovery_selection(plan, selection)
        identity = recovery.scientific_identities[leaf.leaf_id]
        checkpoint = append_promotion(
            empty_schema11_checkpoint(plan.campaign_id, selection.selection_id),
            leaf_id=leaf.leaf_id,
            queue_kind=PromotionQueueKind.RESPONSE,
            reason_code="PR66_TERMINAL_CACHE_REGRESSION",
            minimum_requested_tier="BF40",
            scientific_computation_identity=identity,
            source_root_seal_sha256="b" * 64,
        )

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = SolvedLeafStore(root / "solved-leaves")
            store.publish(
                scientific_identity_sha256=identity,
                leaf_id=leaf.leaf_id,
                record=_terminal_survey_record(plan, leaf),
                source_type="originating-campaign",
            )
            with patch(
                "windows_solver.campaign_runtime.SolvedLeafStore.default",
                return_value=store,
            ), patch(
                "windows_solver.campaign_runtime.NativeCampaignStageBackend"
                ".from_selection",
                side_effect=AssertionError("terminal cache constructed a backend"),
            ), patch(
                "windows_solver.campaign_runtime._refresh_runtime_reports",
                side_effect=lambda _plan, _selection, _path, value, **_kwargs: dict(
                    value
                ),
            ):
                result = run_native_promoted_pass(
                    plan,
                    selection,
                    recovery,
                    checkpoint,
                    checkpoint_path=root / "checkpoint.json",
                )

        entry = result.checkpoint["promotion_queue"]["entries"][0]
        pass_entry = result.checkpoint["survey_pass_ledger"]["promoted"][
            leaf.leaf_id
        ]
        self.assertEqual(1, result.cache_reused_count)
        self.assertEqual(
            {
                "lookup_count": 1,
                "empty_count": 0,
                "miss_count": 0,
                "hit_count": 1,
                "corrupt_count": 0,
                "conflict_count": 0,
                "discovered_count": 1,
                "compatible_count": 1,
                "reused_count": 1,
                "rejected_count": 0,
            },
            result.terminal_cache_discovery.to_mapping(),
        )
        self.assertEqual(PromotionQueueDisposition.SUPERSEDED_BY_CACHE.value, entry["disposition"])
        self.assertEqual(SurveyDisposition.SUPERSEDED_BY_CACHE.value, pass_entry["disposition"])
        self.assertEqual(0, pass_entry["sample_count"])
        self.assertEqual(0, pass_entry["root_read_count"])
        self.assertEqual(0, pass_entry["worker_launch_count"])

    def test_binary64_adapter_reuses_terminal_cache_before_root_or_backend(
        self,
    ) -> None:
        """The real binary64 adapter sees exact terminal evidence before work owners."""

        plan, leaf, _other, _third = self._cache_context()
        selection = build_campaign_selection(
            plan, role=leaf.role, leaf_ids=(leaf.leaf_id,)
        )
        recovery = _recovery_selection(plan, selection)
        identity = recovery.scientific_identities[leaf.leaf_id]
        checkpoint = empty_schema11_checkpoint(plan.campaign_id, selection.selection_id)

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = SolvedLeafStore(root / "solved-leaves")
            store.publish(
                scientific_identity_sha256=identity,
                leaf_id=leaf.leaf_id,
                record=_terminal_survey_record(plan, leaf),
                source_type="originating-campaign",
            )
            with patch(
                "windows_solver.campaign_runtime._root_index",
                side_effect=AssertionError("terminal cache consulted root provider"),
            ), patch(
                "windows_solver.campaign_runtime._binary64_backend",
                side_effect=AssertionError("terminal cache constructed a backend"),
            ), patch(
                "windows_solver.campaign_runtime._refresh_runtime_reports",
                side_effect=lambda _plan, _selection, _path, value, **_kwargs: dict(
                    value
                ),
            ):
                result = run_native_binary64_pass(
                    plan,
                    selection,
                    recovery,
                    checkpoint,
                    checkpoint_path=root / "checkpoint.json",
                    solved_leaf_store=store,
                )

        pass_entry = result.checkpoint["survey_pass_ledger"]["binary64"][
            leaf.leaf_id
        ]
        self.assertEqual(1, result.cache_reused_count)
        self.assertEqual(SurveyDisposition.CACHE_REUSED.value, pass_entry["disposition"])
        self.assertEqual(0, pass_entry["sample_count"])
        self.assertEqual(0, pass_entry["root_read_count"])
        self.assertEqual(0, pass_entry["worker_launch_count"])

    def test_empty_terminal_store_runs_only_the_ordinary_cold_path(self) -> None:
        """An empty configured cache is an honest zero-reuse cold start."""

        plan = build_campaign_plan(
            policy=NumericalPolicy(),
            backend_identity=VettedNativeDeterminantKernel.identity,
            precision_capabilities=PrecisionCapabilities((64, 80)),
        )
        leaf = next(
            item
            for item in plan.leaves
            if item.mechanism_id == "horizon-admittance" and item.role == "primary"
        )
        selection = build_campaign_selection(
            plan, role=leaf.role, leaf_ids=(leaf.leaf_id,)
        )
        recovery = _recovery_selection(plan, selection)
        checkpoint = empty_schema11_checkpoint(plan.campaign_id, selection.selection_id)
        backend_factory = Mock(return_value=object())
        outcome = Binary64PassOutcome(
            disposition=SurveyDisposition.PROMOTION_PENDING_RESPONSE,
            operation_identity="pr66-empty-terminal-cache-fixture/v1",
            reason_code="DETERMINANT_ERROR_EVIDENCE_UNAVAILABLE",
            queue_kind=PromotionQueueKind.RESPONSE,
        )

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = SolvedLeafStore(root / "solved-leaves")
            with patch(
                "windows_solver.campaign_runtime._binary64_backend",
                backend_factory,
            ), patch(
                "windows_solver.campaign_runtime._horizon_outcome",
                return_value=outcome,
            ), patch(
                "windows_solver.campaign_runtime._refresh_runtime_reports",
                side_effect=lambda _plan, _selection, _path, value, **_kwargs: dict(
                    value
                ),
            ):
                result = run_native_binary64_pass(
                    plan,
                    selection,
                    recovery,
                    checkpoint,
                    checkpoint_path=root / "checkpoint.json",
                    solved_leaf_store=store,
                )

        backend_factory.assert_called_once_with(plan, selection)
        self.assertEqual(0, result.cache_reused_count)
        self.assertEqual(
            {
                "lookup_count": 1,
                "empty_count": 1,
                "miss_count": 0,
                "hit_count": 0,
                "corrupt_count": 0,
                "conflict_count": 0,
                "discovered_count": 0,
                "compatible_count": 0,
                "reused_count": 0,
                "rejected_count": 0,
            },
            result.terminal_cache_discovery.to_mapping(),
        )
        self.assertEqual(
            SurveyDisposition.PROMOTION_PENDING_RESPONSE.value,
            result.checkpoint["survey_pass_ledger"]["binary64"][leaf.leaf_id][
                "disposition"
            ],
        )

    def test_promoted_adapter_reports_mixed_store_cardinality_once(self) -> None:
        """A two-record store is discovered once, not once per queued leaf."""

        plan, first, second, _third = self._cache_context()
        selection = build_campaign_selection(
            plan,
            role=first.role,
            leaf_ids=(first.leaf_id, second.leaf_id),
        )
        recovery = _recovery_selection(plan, selection)
        checkpoint = empty_schema11_checkpoint(plan.campaign_id, selection.selection_id)
        for leaf in (first, second):
            checkpoint = append_promotion(
                checkpoint,
                leaf_id=leaf.leaf_id,
                queue_kind=PromotionQueueKind.RESPONSE,
                reason_code="PR66_MIXED_TERMINAL_CACHE_REGRESSION",
                minimum_requested_tier="BF40",
                scientific_computation_identity=recovery.scientific_identities[
                    leaf.leaf_id
                ],
                source_root_seal_sha256="b" * 64,
            )

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = SolvedLeafStore(root / "solved-leaves")
            for leaf in (first, second):
                store.publish(
                    scientific_identity_sha256=recovery.scientific_identities[
                        leaf.leaf_id
                    ],
                    leaf_id=leaf.leaf_id,
                    record=_terminal_survey_record(plan, leaf),
                    source_type="originating-campaign",
                )
            with patch(
                "windows_solver.campaign_runtime.NativeCampaignStageBackend"
                ".from_selection",
                side_effect=AssertionError("terminal cache constructed a backend"),
            ), patch(
                "windows_solver.campaign_runtime._refresh_runtime_reports",
                side_effect=lambda _plan, _selection, _path, value, **_kwargs: dict(
                    value
                ),
            ):
                result = run_native_promoted_pass(
                    plan,
                    selection,
                    recovery,
                    checkpoint,
                    checkpoint_path=root / "checkpoint.json",
                    solved_leaf_store=store,
                )

        self.assertEqual(2, result.cache_reused_count)
        self.assertEqual(
            {
                "lookup_count": 1,
                "empty_count": 0,
                "miss_count": 0,
                "hit_count": 1,
                "corrupt_count": 0,
                "conflict_count": 0,
                "discovered_count": 2,
                "compatible_count": 2,
                "reused_count": 2,
                "rejected_count": 0,
            },
            result.terminal_cache_discovery.to_mapping(),
        )

    def test_public_binary64_result_includes_terminal_cache_accounting(self) -> None:
        """The public pass result exposes exact discovery counts to the operator."""

        from windows_solver import cli

        plan, leaf, _other, _third = self._cache_context()
        selection = build_campaign_selection(
            plan, role=leaf.role, leaf_ids=(leaf.leaf_id,)
        )
        recovery = _recovery_selection(plan, selection)
        checkpoint = empty_schema11_checkpoint(plan.campaign_id, selection.selection_id)
        totals = EvidenceDiscoveryTotals(
            lookup_count=1,
            empty_count=1,
            discovered_count=0,
            compatible_count=0,
            reused_count=0,
            rejected_count=0,
        )
        result = Binary64SurveyRun(
            checkpoint=checkpoint,
            completed_count=0,
            queued_count=1,
            cache_reused_count=0,
            skipped_count=0,
            terminal_cache_discovery=totals,
        )

        class _Reporter:
            def publish(self, _event: object) -> None:
                return None

            def close(self) -> None:
                return None

        with patch(
            "windows_solver.cli._load_schema11_campaign",
            return_value=(
                plan,
                selection,
                object(),
                recovery,
                Path("/tmp/pr66-terminal-cache-checkpoint.json"),
                checkpoint,
            ),
        ), patch(
            "windows_solver.cli.Schema11ProgressReporter",
            return_value=_Reporter(),
        ), patch(
            "windows_solver.campaign_runtime.run_native_binary64_pass",
            return_value=result,
        ):
            status, payload = cli._campaign_schema11_pass(
                "campaign-survey-binary64",
                Path("selection.json"),
                Path("checkpoint.json"),
                queue_path=None,
                progress_mode="quiet",
                calibration_receipt_path=None,
                calibration_receipt_sha256=None,
            )

        self.assertEqual(0, status)
        self.assertIsInstance(payload, dict)
        self.assertEqual(totals.to_mapping(), payload["terminal_cache_discovery"])


if __name__ == "__main__":
    unittest.main()
