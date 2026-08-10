from __future__ import annotations

from dataclasses import replace
import json
from fractions import Fraction
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from windows_solver.contracts import canonical_json_bytes
from windows_solver.response_batches import (
    PrecisionCapabilities,
    StageOutcome,
    build_campaign_plan,
    build_campaign_selection,
    import_campaign_checkpoint_to_solved_leaf_store,
    scientific_computation_identity_sha256,
    run_campaign_selection,
    synthetic_stage_signed_error_channels,
)
from windows_solver.response_engine import (
    BackendIdentity,
    NumericalPolicy,
    VettedNativeDeterminantKernel,
)
from windows_solver.solved_leaf_cache import SolvedLeafLookupStatus, SolvedLeafStore


def _outcome(leaf, digits=64):
    component = {
        "evidence_kind": "synthetic-cache-orchestration-contract",
        "leaf_id": leaf.leaf_id,
        "role": leaf.role,
        "mechanism_id": leaf.mechanism_id,
        "digits": digits,
    }
    return StageOutcome(
        digits=digits,
        numerical_state="CONVERGED",
        component_result=component,
        local_disk_radius_abs=1.0e-8,
        signed_error_channels=synthetic_stage_signed_error_channels(
            component, 1.0e-8
        ),
    )


class _Backend:
    def __init__(self, plan, *, fail_after=None):
        self.identity = plan.backend_identity
        self.precision_capabilities = plan.precision_capabilities
        self.calls = []
        self.fail_after = fail_after

    def execute_stage(self, leaf, digits):
        if self.fail_after is not None and len(self.calls) >= self.fail_after:
            raise RuntimeError("synthetic interruption")
        self.calls.append((leaf.leaf_id, digits))
        return _outcome(leaf, digits)


def _plan(*, tolerance=2.0e-10):
    return build_campaign_plan(
        policy=NumericalPolicy(ode_relative_tolerance=tolerance),
        backend_identity=VettedNativeDeterminantKernel.identity,
        precision_capabilities=PrecisionCapabilities((64,)),
    )


def _primary(plan, count):
    ids = tuple(leaf.leaf_id for leaf in plan.leaves if leaf.role == "primary")[:count]
    return build_campaign_selection(plan, role="primary", leaf_ids=ids)


class SolvedLeafCacheTests(unittest.TestCase):
    def test_reduced_domain_preserves_retained_leaf_scientific_identities(self):
        plan = _plan()
        expected = {
            "horizon-admittance": "b-prime-leaf-9e5777728144433e089f9559b92b6e139e16115a5a53099f40403a45297aa3c3",
            "exterior-fixed-r3": "b-prime-leaf-21a31df9512726338ff0920025fd5e5c42e67ef7d603130e822b3a2798b5aed5",
            "exterior-alpha-half": "b-prime-leaf-4eb508d767bea5cddc3f7c0eb120c1a9cc184122900f4d7ec86b56c98ddab596",
            "exterior-light-ring": "b-prime-leaf-3ee2b2dcdc5276cbcd51264f1210002314acd3ff845bb7a464f1e9333e9115c5",
            "exterior-throat-kappa": "b-prime-leaf-fc5998bf989465575d276b6a1ad4758dbb1cdacc25e1c7554185f0c38e170332",
        }
        retained = {
            leaf.mechanism_id: leaf
            for leaf in plan.leaves
            if (
                leaf.role == "primary"
                and leaf.leaf.mode_label == "220"
                and leaf.leaf.coordinate == Fraction(19, 20)
            )
        }

        self.assertEqual(set(retained), set(expected))
        for mechanism_id, leaf_id in expected.items():
            with self.subTest(mechanism_id=mechanism_id):
                leaf = retained[mechanism_id]
                self.assertEqual(leaf.leaf_id, leaf_id)
                isolated_plan = replace(plan, leaves=(leaf,), cohorts=())
                self.assertEqual(
                    scientific_computation_identity_sha256(plan, leaf),
                    scientific_computation_identity_sha256(isolated_plan, leaf),
                )

    def test_empty_store_writes_through_then_identical_run_reuses_exact_record(self):
        historical_backend = BackendIdentity(
            backend_id="cache-compatibility-fixture",
            implementation_version="1",
            source_commit="0c1e8a3d3bca6e608c34e111476a4f6dcb73e86e",
            source_blobs=((
                "fixture",
                "b65f2236f828204aa21dfa8d9bc79c8a1c66ca3b",
            ),),
            runtime_fingerprint="platform-independent-cache-fixture",
        )
        plan = build_campaign_plan(
            policy=NumericalPolicy(ode_relative_tolerance=2.0e-10),
            backend_identity=historical_backend,
            precision_capabilities=PrecisionCapabilities((64,)),
        )
        selection = _primary(plan, 1)
        leaf = next(
            item for item in plan.leaves if item.leaf_id == selection.leaf_ids[0]
        )
        self.assertEqual(
            scientific_computation_identity_sha256(plan, leaf),
            "82dd7b5fc50fa17b3ebbded02a3ea83b827f8e9c2c4f47679ffe462b142b640c",
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = SolvedLeafStore(root / "solved")
            first_backend = _Backend(plan)
            with patch(
                "windows_solver.response_batches._validate_record_semantics",
                return_value=True,
            ):
                first = run_campaign_selection(
                    plan,
                    selection,
                    first_backend,
                    root / "first.json",
                    resume=False,
                    solved_leaf_store=store,
                )
                second_backend = _Backend(plan)
                second = run_campaign_selection(
                    plan,
                    selection,
                    second_backend,
                    root / "second.json",
                    resume=False,
                    solved_leaf_store=store,
                )

            self.assertEqual(first_backend.calls, [(selection.leaf_ids[0], 64)])
            self.assertEqual(second_backend.calls, [])
            self.assertEqual(
                second.records[0].to_mapping(), first.records[0].to_mapping()
            )
            self.assertEqual(second.executed_stage_count, 0)
            self.assertEqual(second.reused_stage_count, 1)

    def test_scientific_change_misses_but_telemetry_change_does_not_change_identity(self):
        plan = _plan()
        changed = _plan(tolerance=1.0e-10)
        leaf = next(item for item in plan.leaves if item.role == "primary")
        changed_leaf = next(item for item in changed.leaves if item.leaf_id == leaf.leaf_id)
        baseline = scientific_computation_identity_sha256(plan, leaf)
        self.assertNotEqual(
            baseline,
            scientific_computation_identity_sha256(changed, changed_leaf),
        )
        with patch(
            "windows_solver.response_batches._campaign_source_sha256",
            return_value="f" * 64,
        ):
            self.assertEqual(
                baseline, scientific_computation_identity_sha256(plan, leaf)
            )

    def test_changed_science_executes_and_deleted_store_leaves_originating_path_intact(self):
        plan = _plan()
        selection = _primary(plan, 1)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            cache_root = root / "solved"
            store = SolvedLeafStore(cache_root)
            with patch(
                "windows_solver.response_batches._validate_record_semantics",
                return_value=True,
            ):
                run_campaign_selection(
                    plan, selection, _Backend(plan), root / "a.json",
                    resume=False, solved_leaf_store=store,
                )
                changed = _plan(tolerance=1.0e-10)
                changed_selection = build_campaign_selection(
                    changed, role="primary", leaf_ids=selection.leaf_ids
                )
                changed_backend = _Backend(changed)
                run_campaign_selection(
                    changed, changed_selection, changed_backend, root / "b.json",
                    resume=False, solved_leaf_store=store,
                )
                shutil.rmtree(cache_root)
                cold_backend = _Backend(plan)
                run_campaign_selection(
                    plan, selection, cold_backend, root / "c.json",
                    resume=False, solved_leaf_store=store,
                )
            self.assertEqual(changed_backend.calls, [(selection.leaf_ids[0], 64)])
            self.assertEqual(cold_backend.calls, [(selection.leaf_ids[0], 64)])

    def test_tampered_entry_is_quarantined_and_never_reused(self):
        plan = _plan()
        selection = _primary(plan, 1)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = SolvedLeafStore(root / "solved")
            with patch(
                "windows_solver.response_batches._validate_record_semantics",
                return_value=True,
            ):
                run_campaign_selection(
                    plan, selection, _Backend(plan), root / "first.json",
                    resume=False, solved_leaf_store=store,
                )
                entry = next(store.root.glob("*.json"))
                forged = json.loads(entry.read_text(encoding="utf-8"))
                forged["record"]["stages"][0]["component_result"]["digits"] = 80
                entry.write_bytes(canonical_json_bytes(forged))
                backend = _Backend(plan)
                run_campaign_selection(
                    plan, selection, backend, root / "second.json",
                    resume=False, solved_leaf_store=store,
                )
            self.assertEqual(backend.calls, [(selection.leaf_ids[0], 64)])
            self.assertTrue(entry.exists())
            self.assertTrue(any((store.root / "quarantine").iterdir()))

    def test_nonterminal_record_cannot_publish_and_stale_lookup_is_distinct(self):
        plan = _plan()
        selection = _primary(plan, 1)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = SolvedLeafStore(root / "solved")
            backend = _Backend(plan, fail_after=1)
            with patch(
                "windows_solver.response_batches._validate_record_semantics",
                return_value=True,
            ):
                completed = run_campaign_selection(
                    plan, selection, backend, root / "done.json",
                    resume=False, solved_leaf_store=store,
                )
            changed = _plan(tolerance=1.0e-10)
            changed_leaf = next(
                item for item in changed.leaves if item.leaf_id == selection.leaf_ids[0]
            )
            lookup = store.lookup(
                scientific_computation_identity_sha256(changed, changed_leaf),
                changed_leaf.leaf_id,
            )
            self.assertIs(lookup.status, SolvedLeafLookupStatus.STALE)
            partial = completed.records[0].to_mapping()
            partial["state"] = "IN_PROGRESS"
            partial["computed"] = False
            with self.assertRaisesRegex(ValueError, "terminal"):
                store.publish(
                    scientific_identity_sha256="a" * 64,
                    leaf_id=selection.leaf_ids[0],
                    record=partial,
                    source_type="originating-campaign",
                )

    def test_partial_checkpoint_imports_only_authenticated_terminal_records(self):
        plan = _plan()
        selection = _primary(plan, 3)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "partial.json"
            with patch(
                "windows_solver.response_batches._validate_record_semantics",
                return_value=True,
            ):
                with self.assertRaisesRegex(RuntimeError, "interruption"):
                    run_campaign_selection(
                        plan, selection, _Backend(plan, fail_after=2), source,
                        resume=False,
                    )
                imported = import_campaign_checkpoint_to_solved_leaf_store(
                    plan, source, SolvedLeafStore(root / "solved")
                )
            self.assertEqual(imported.imported_count, 2)
            self.assertEqual(imported.leaf_ids, selection.leaf_ids[:2])

            status = root / "status.json"
            status.write_text(
                '{"schema":"windows-solver.progress/1","kind":"request_failed"}',
                encoding="utf-8",
            )
            diagnostic = import_campaign_checkpoint_to_solved_leaf_store(
                plan, status, SolvedLeafStore(root / "other")
            )
            self.assertEqual(diagnostic.imported_count, 0)
            self.assertFalse((root / "other").exists())

    def test_current_checkpoint_precedes_cache_and_order_is_canonical(self):
        plan = _plan()
        selection = _primary(plan, 2)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = SolvedLeafStore(root / "solved")
            checkpoint = root / "current.json"
            with patch(
                "windows_solver.response_batches._validate_record_semantics",
                return_value=True,
            ):
                with self.assertRaises(RuntimeError):
                    run_campaign_selection(
                        plan, selection, _Backend(plan, fail_after=1), checkpoint,
                        resume=False, solved_leaf_store=store,
                    )
                second_only = build_campaign_selection(
                    plan, role="primary", leaf_ids=(selection.leaf_ids[1],)
                )
                run_campaign_selection(
                    plan, second_only, _Backend(plan), root / "second-only.json",
                    resume=False, solved_leaf_store=store,
                )
                backend = _Backend(plan)
                result = run_campaign_selection(
                    plan, selection, backend, checkpoint,
                    resume=True, solved_leaf_store=store,
                )
            self.assertEqual(backend.calls, [])
            self.assertEqual(
                tuple(record.leaf_id for record in result.records), selection.leaf_ids
            )


if __name__ == "__main__":
    unittest.main()
