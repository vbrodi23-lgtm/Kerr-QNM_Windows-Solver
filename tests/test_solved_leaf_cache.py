from __future__ import annotations

from dataclasses import replace
import io
import json
from fractions import Fraction
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from windows_solver.contracts import canonical_json_bytes
from windows_solver.response_batches import (
    PrecisionCapabilities,
    StageOutcome,
    _authenticated_solved_leaf_lookup,
    _validate_cacheable_leaf_record,
    build_campaign_plan,
    build_campaign_selection,
    import_campaign_checkpoint_to_solved_leaf_store,
    scientific_computation_identity_sha256,
    run_campaign_selection,
    synthetic_stage_signed_error_channels,
)
from windows_solver.response_engine import (
    BackendIdentity,
    ComponentResult,
    ComponentStatus,
    NumericalPolicy,
    RootReadout,
    VettedNativeDeterminantKernel,
)
from windows_solver.progress import activate_progress
from windows_solver.progress_output import CampaignProgressReporter
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


_POLISHED_BASELINES = {
    "b-prime-leaf-4c8594e4a59486a1c56206e41cd7f7f3ff1ab5193a5ff6b699cbe9492bc45355": complex(
        0.9558544196294082, -0.010530589036141928
    ),
    "b-prime-leaf-0f36daefa853de1280f17c8b8ef89bbaf9b34f5e5044a5eb85bc563d3896b60d": complex(
        0.95585441962906326, -0.010530589035773716
    ),
    "b-prime-leaf-08b8dc3df83fc1304a61d8b6105c412a316a44816ca229d375573fdf72ac0a57": complex(
        0.9558544196284392, -0.010530589035175312
    ),
}
_POLISHED_IDENTITIES = {
    "b-prime-leaf-4c8594e4a59486a1c56206e41cd7f7f3ff1ab5193a5ff6b699cbe9492bc45355": "f8a27f26f8f4ddef54f8854d7aba0056ce654bfaac91a27ed19386f0f872ff3d",
    "b-prime-leaf-0f36daefa853de1280f17c8b8ef89bbaf9b34f5e5044a5eb85bc563d3896b60d": "3d3eb67100cfaf0a1e898eaf64b31ab8a3732ec45eb882e9e8a641972ff015de",
    "b-prime-leaf-08b8dc3df83fc1304a61d8b6105c412a316a44816ca229d375573fdf72ac0a57": "f44a0eebeebe14035fcb21aecf894a9d3fef9ad0701f9c756c5e17bb5f1193ad",
}


def _production_outcome(
    leaf,
    *,
    baseline_omega=None,
    root_reference_id=None,
    branch_id=None,
    root_identity_sha256=None,
    seed_path_radius=8.0e-12,
):
    job = leaf.job
    baseline = RootReadout(
        omega=job.root.omega if baseline_omega is None else baseline_omega,
        determinant_residual_abs=2.0e-13,
        determinant_derivative_abs=1.0,
        converged=True,
        root_reference_id=(
            job.root.root_reference_id
            if root_reference_id is None
            else root_reference_id
        ),
        branch_id=job.root.branch_id if branch_id is None else branch_id,
        equation_id=job.equation_id,
        truncation_radius=3.0e-12,
        resolution_radius=5.0e-12,
        seed_path_radius=seed_path_radius,
        source_root_mapping=job.source_root_mapping,
    )
    result = ComponentResult(
        job_id=job.job_id,
        leaf_id=job.leaf_id,
        mechanism_id=job.mechanism_id,
        status=ComponentStatus.CONVERGED,
        convergence_basis="ORDER_RESOLVED",
        response=complex(1.0, -0.5),
        signed_root_crosscheck=complex(1.0, -0.5),
        closed_form_response=None,
        error_channels={
            "signed-root": 1.0e-9,
            "truncation": 1.0e-9,
            "resolution": 1.0e-9,
            "seed-path": 1.0e-9,
            "axis": 1.0e-9,
            "amplitude": 1.0e-9,
        },
        baseline=baseline,
        levels=(),
        lineage={
            "leaf_id": job.leaf_id,
            "root_reference_id": job.root.root_reference_id,
            "root_identity_sha256": (
                job.root.identity_sha256
                if root_identity_sha256 is None
                else root_identity_sha256
            ),
            "policy_sha256": job.policy.identity_sha256,
            "backend_identity_sha256": job.backend_identity.identity_sha256,
            "equation_id": job.equation_id,
            "sampling_coordinate": job.sampling_coordinate.to_mapping(),
            "source_root_mapping": job.source_root_mapping,
        },
    )
    component = {
        "evidence_kind": "authenticated-polished-baseline-regression",
        "result": result.to_mapping(),
    }
    return StageOutcome(
        digits=64,
        numerical_state="CONVERGED",
        component_result=component,
        local_disk_radius_abs=1.0e-8,
        signed_error_channels=synthetic_stage_signed_error_channels(
            component, 1.0e-8
        ),
    )


def _windows_production_plan():
    identity = replace(
        VettedNativeDeterminantKernel.identity,
        runtime_fingerprint=(
            "cpython-3.12.13-windows-python-64bit-"
            "gsn-input-julia-exact-f-u-cache-contract-1-"
            "adapted-source-native-gsn-adapter-contract-1"
        ),
    )
    return build_campaign_plan(
        policy=NumericalPolicy(),
        backend_identity=identity,
        precision_capabilities=PrecisionCapabilities((64,)),
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
    def test_polished_production_baseline_is_cacheable_without_changing_identity(self):
        plan = _windows_production_plan()
        leaf = next(
            item for item in plan.leaves if item.leaf_id in _POLISHED_BASELINES
        )
        selection = build_campaign_selection(
            plan, role="primary", leaf_ids=(leaf.leaf_id,)
        )

        class Backend:
            identity = plan.backend_identity
            precision_capabilities = plan.precision_capabilities

            def execute_stage(self, selected, digits):
                return _production_outcome(
                    selected,
                    baseline_omega=_POLISHED_BASELINES[selected.leaf_id],
                )

        with tempfile.TemporaryDirectory() as temporary:
            store = SolvedLeafStore(Path(temporary) / "solved-leaves-v1")
            summary = run_campaign_selection(
                plan,
                selection,
                Backend(),
                Path(temporary) / "checkpoint.json",
                resume=False,
                solved_leaf_store=store,
            )
            stored_count = store.stored_count

        _validate_cacheable_leaf_record(plan, leaf, summary.records[0])
        self.assertEqual(
            scientific_computation_identity_sha256(plan, leaf),
            _POLISHED_IDENTITIES[leaf.leaf_id],
        )
        self.assertEqual(stored_count, 1)

    def test_tiny_displacement_does_not_authenticate_wrong_root_identity_or_branch(self):
        plan = _windows_production_plan()
        leaf = next(
            item for item in plan.leaves if item.leaf_id in _POLISHED_BASELINES
        )
        selection = build_campaign_selection(
            plan, role="primary", leaf_ids=(leaf.leaf_id,)
        )

        class Backend:
            identity = plan.backend_identity
            precision_capabilities = plan.precision_capabilities

            def __init__(self, mutation):
                self.mutation = mutation

            def execute_stage(self, selected, digits):
                return _production_outcome(
                    selected,
                    baseline_omega=_POLISHED_BASELINES[selected.leaf_id],
                    **self.mutation,
                )

        for mutation, message in (
            ({"root_reference_id": "wrong-root-reference"}, "readout lineage"),
            ({"branch_id": "wrong-branch"}, "readout lineage"),
            ({"root_identity_sha256": "f" * 64}, "component lineage"),
        ):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as temporary:
                summary = run_campaign_selection(
                    plan,
                    selection,
                    Backend(mutation),
                    Path(temporary) / "checkpoint.json",
                    resume=False,
                )
                with self.assertRaisesRegex(ValueError, message):
                    _validate_cacheable_leaf_record(
                        plan, leaf, summary.records[0]
                    )

    def test_baseline_outside_its_branch_diagnostic_evidence_is_not_cacheable(self):
        plan = _windows_production_plan()
        leaf = next(
            item for item in plan.leaves if item.leaf_id in _POLISHED_BASELINES
        )
        selection = build_campaign_selection(
            plan, role="primary", leaf_ids=(leaf.leaf_id,)
        )

        class Backend:
            identity = plan.backend_identity
            precision_capabilities = plan.precision_capabilities

            def execute_stage(self, selected, digits):
                return _production_outcome(
                    selected,
                    baseline_omega=_POLISHED_BASELINES[selected.leaf_id],
                    seed_path_radius=1.0e-2,
                )

        with tempfile.TemporaryDirectory() as temporary:
            summary = run_campaign_selection(
                plan,
                selection,
                Backend(),
                Path(temporary) / "checkpoint.json",
                resume=False,
            )
        with self.assertRaisesRegex(
            ValueError, "baseline root readout evidence is invalid"
        ):
            _validate_cacheable_leaf_record(plan, leaf, summary.records[0])

    def test_three_polished_checkpoint_records_import_and_lookup_as_hits(self):
        plan = _windows_production_plan()
        leaves = tuple(
            item for item in plan.leaves if item.leaf_id in _POLISHED_BASELINES
        )
        selection = build_campaign_selection(
            plan, role="primary", leaf_ids=tuple(item.leaf_id for item in leaves)
        )

        class Backend:
            identity = plan.backend_identity
            precision_capabilities = plan.precision_capabilities

            def execute_stage(self, selected, digits):
                return _production_outcome(
                    selected,
                    baseline_omega=_POLISHED_BASELINES[selected.leaf_id],
                )

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            checkpoint = root / "checkpoint.json"
            run_campaign_selection(
                plan, selection, Backend(), checkpoint, resume=False
            )
            store = SolvedLeafStore(root / "solved-leaves-v1")
            imported = import_campaign_checkpoint_to_solved_leaf_store(
                plan, checkpoint, store
            )

            self.assertEqual(imported.imported_count, 3)
            self.assertEqual(store.stored_count, 3)
            self.assertEqual(
                {path.stem for path in store.root.glob("*.json")},
                set(_POLISHED_IDENTITIES.values()),
            )
            for leaf in leaves:
                with self.subTest(leaf_id=leaf.leaf_id):
                    self.assertEqual(
                        scientific_computation_identity_sha256(plan, leaf),
                        _POLISHED_IDENTITIES[leaf.leaf_id],
                    )
                    lookup = _authenticated_solved_leaf_lookup(
                        plan, leaf, store
                    )
                    self.assertIs(lookup.status, SolvedLeafLookupStatus.HIT)
                    self.assertTrue(lookup.path.is_file())
                    self.assertFalse((store.root / "quarantine").exists())

    def test_publication_failure_remains_in_status_after_leaf_completion(self):
        plan = _windows_production_plan()
        leaf = next(
            item for item in plan.leaves if item.leaf_id in _POLISHED_BASELINES
        )
        selection = build_campaign_selection(
            plan, role="primary", leaf_ids=(leaf.leaf_id,)
        )

        class Backend:
            identity = plan.backend_identity
            precision_capabilities = plan.precision_capabilities

            def execute_stage(self, selected, digits):
                return _production_outcome(
                    selected,
                    baseline_omega=_POLISHED_BASELINES[selected.leaf_id],
                )

        class FailingStore(SolvedLeafStore):
            def publish(self, **kwargs):
                raise OSError("synthetic persistent-store failure")

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            checkpoint = root / "checkpoint.json"
            stream = io.StringIO()
            reporter = CampaignProgressReporter("normal", checkpoint, stream)
            store = FailingStore(root / "persistent-solved-leaves-v1")
            with activate_progress(reporter):
                run_campaign_selection(
                    plan,
                    selection,
                    Backend(),
                    checkpoint,
                    resume=False,
                    solved_leaf_store=store,
                )
            status = json.loads(
                Path(f"{checkpoint}.status.json").read_text(encoding="utf-8")
            )

        self.assertIn("leaf_cache_publication_failed", stream.getvalue())
        self.assertEqual(status["persistence"]["publication_failure_count"], 1)
        failure = status["persistence"]["publication_failures"][0]
        self.assertEqual(failure["leaf_id"], leaf.leaf_id)
        self.assertEqual(failure["leaf_index"], 1)
        self.assertEqual(failure["store_path"], str(store.root))
        self.assertEqual(failure["error_type"], "OSError")
        self.assertEqual(failure["message"], "synthetic persistent-store failure")
        self.assertEqual(
            status["persistence"]["current_leaf"],
            {
                "leaf_id": leaf.leaf_id,
                "terminal_computed": True,
                "checkpoint_saved": True,
                "receipt_published": False,
                "publication_failed": True,
            },
        )

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

    def test_windows_campaign_store_cannot_be_redirected_from_local_app_data(self):
        """Catches split read/write stores caused by an inherited override."""

        plan = _plan()
        selection = _primary(plan, 2)
        first_only = build_campaign_selection(
            plan, role="primary", leaf_ids=(selection.leaf_ids[0],)
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            local_app_data = root / "LocalAppData"
            required_root = (
                local_app_data
                / "Kerr-QNM_Windows-Solver"
                / "solved-leaves-v1"
            )
            redirected_root = root / "wrong-store"
            required_store = SolvedLeafStore(required_root)
            with patch(
                "windows_solver.response_batches._validate_record_semantics",
                return_value=True,
            ):
                run_campaign_selection(
                    plan,
                    first_only,
                    _Backend(plan),
                    root / "seed.json",
                    resume=False,
                    solved_leaf_store=required_store,
                )
                with patch.dict(
                    os.environ,
                    {
                        "LOCALAPPDATA": str(local_app_data),
                        "KERR_QNM_SOLVED_LEAF_STORE": str(redirected_root),
                    },
                    clear=True,
                ):
                    production_store = SolvedLeafStore.default()
                    backend = _Backend(plan)
                    summary = run_campaign_selection(
                        plan,
                        selection,
                        backend,
                        root / "campaign.json",
                        resume=False,
                        solved_leaf_store=production_store,
                    )

            self.assertEqual(production_store.root, required_root)
            self.assertEqual(
                backend.calls,
                [(selection.leaf_ids[1], 64)],
            )
            self.assertEqual(summary.executed_stage_count, 1)
            self.assertEqual(summary.reused_stage_count, 1)
            self.assertEqual(required_store.stored_count, 2)
            self.assertFalse(redirected_root.exists())

    def test_resume_backfills_terminal_checkpoint_records_to_default_windows_store(self):
        """Catches checkpoint reuse that skips persistent solved-leaf publication."""

        plan = _plan()
        selection = _primary(plan, 3)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            checkpoint = (
                root
                / "Downloads"
                / "extracted-copy"
                / "m02-output"
                / "m02-campaign-checkpoint.json"
            )
            local_app_data = root / "LocalAppData"
            with patch.dict(
                os.environ,
                {"LOCALAPPDATA": str(local_app_data)},
                clear=True,
            ), patch(
                "windows_solver.response_batches._validate_record_semantics",
                return_value=True,
            ):
                with self.assertRaisesRegex(RuntimeError, "interruption"):
                    run_campaign_selection(
                        plan,
                        selection,
                        _Backend(plan, fail_after=2),
                        checkpoint,
                        resume=False,
                    )

                store = SolvedLeafStore.default()
                resumed = run_campaign_selection(
                    plan,
                    selection,
                    _Backend(plan),
                    checkpoint,
                    resume=True,
                    solved_leaf_store=store,
                )

            self.assertEqual(
                store.root,
                local_app_data
                / "Kerr-QNM_Windows-Solver"
                / "solved-leaves-v1",
            )
            self.assertEqual(resumed.result_count, 3)
            self.assertEqual(store.stored_count, 3)
            stored_leaf_ids = {
                json.loads(path.read_text(encoding="utf-8"))["leaf_id"]
                for path in store.root.glob("*.json")
            }
            self.assertEqual(stored_leaf_ids, set(selection.leaf_ids))

    def test_complete_cli_resume_backfills_default_windows_store(self):
        """Catches the complete-checkpoint fast path bypassing persistence."""

        from windows_solver.cli import _campaign_selected

        plan = _plan()
        selection = _primary(plan, 1)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            checkpoint = root / "m02-output" / "m02-campaign-checkpoint.json"
            local_app_data = root / "LocalAppData"
            with patch(
                "windows_solver.response_batches._validate_record_semantics",
                return_value=True,
            ):
                run_campaign_selection(
                    plan,
                    selection,
                    _Backend(plan),
                    checkpoint,
                    resume=False,
                )
                with patch.dict(
                    os.environ,
                    {"LOCALAPPDATA": str(local_app_data)},
                    clear=True,
                ), patch(
                    "windows_solver.cli._campaign_plan_and_selection",
                    return_value=(plan, selection, None),
                ), patch(
                    "windows_solver.cli.Path.cwd",
                    return_value=root,
                ):
                    status, output = _campaign_selected(
                        "campaign-resume",
                        root / "selection.json",
                        Path("m02-output/m02-campaign-checkpoint.json"),
                    )

            store = SolvedLeafStore(
                local_app_data
                / "Kerr-QNM_Windows-Solver"
                / "solved-leaves-v1"
            )
            self.assertEqual(status, 0)
            self.assertEqual(output["state"], "COMPLETE")
            self.assertEqual(store.stored_count, 1)

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
            self.assertEqual(imported.leaf_ids, (
                "b-prime-leaf-9e5777728144433e089f9559b92b6e139e16115a5a53099f40403a45297aa3c3",
                "b-prime-leaf-4eb508d767bea5cddc3f7c0eb120c1a9cc184122900f4d7ec86b56c98ddab596",
            ))

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
