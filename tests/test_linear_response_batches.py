from __future__ import annotations

from fractions import Fraction
import json
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from windows_solver.contracts import canonical_json_bytes, canonical_text_sha256
from windows_solver.linear_response import B_PRIME_RELEASE_DOMAIN
from windows_solver.response_batches import (
    CAMPAIGN_SCHEMA_VERSION,
    CampaignStageRecord,
    PrecisionCapabilities,
    PrecisionFactoryIdentity,
    StageOutcome,
    _campaign_execution_leaf_ids,
    _checkpoint_mapping,
    build_campaign_plan,
    build_campaign_selection,
    import_campaign_checkpoint_to_solved_leaf_store,
    synthetic_stage_signed_error_channels,
    merge_campaign_checkpoints,
    resolve_campaign_relative_path,
    run_campaign_selection,
    validate_campaign_checkpoint,
)
from windows_solver.response_engine import (
    ComponentResult,
    ComponentStatus,
    NumericalPolicy,
    RootReadout,
    VettedNativeDeterminantKernel,
)
from windows_solver.solved_leaf_cache import SolvedLeafStore


def reseal_campaign_checkpoint(value):
    for record in value["records"]:
        for stage in record["stages"]:
            content = {
                key: item for key, item in stage.items() if key != "stage_sha256"
            }
            stage["stage_sha256"] = hashlib.sha256(
                canonical_json_bytes(content)
            ).hexdigest()
        content = {
            key: item for key, item in record.items() if key != "record_sha256"
        }
        record["record_sha256"] = hashlib.sha256(
            canonical_json_bytes(content)
        ).hexdigest()
    value["records_sha256"] = hashlib.sha256(
        canonical_json_bytes(value["records"])
    ).hexdigest()


def _synthetic_stage_outcome(**values):
    component_result = values["component_result"]
    radius = values["local_disk_radius_abs"]
    return StageOutcome(
        **values,
        signed_error_channels=synthetic_stage_signed_error_channels(
            component_result, radius
        ),
    )


def _produced_stage_outcome(leaf, response, *, baseline_delta=0.0j):
    job = leaf.job
    result = ComponentResult(
        job_id=job.job_id,
        leaf_id=job.leaf_id,
        mechanism_id=job.mechanism_id,
        status=ComponentStatus.CONVERGED,
        convergence_basis="ORDER_RESOLVED",
        response=response,
        signed_root_crosscheck=response,
        closed_form_response=None,
        error_channels={
            "signed-root": 1.0e-9,
            "truncation": 1.0e-9,
            "resolution": 1.0e-9,
            "seed-path": 1.0e-9,
            "axis": 1.0e-9,
            "amplitude": 1.0e-9,
        },
        baseline=RootReadout(
            omega=job.root.omega + baseline_delta,
            determinant_residual_abs=1.0e-12,
            determinant_derivative_abs=2.0,
            converged=True,
            root_reference_id=job.root.root_reference_id,
            branch_id=job.root.branch_id,
            equation_id=job.equation_id,
        ),
        levels=(),
        lineage={
            "leaf_id": job.leaf_id,
            "root_reference_id": job.root.root_reference_id,
            "root_identity_sha256": job.root.identity_sha256,
            "policy_sha256": job.policy.identity_sha256,
            "backend_identity_sha256": job.backend_identity.identity_sha256,
            "equation_id": job.equation_id,
            "sampling_coordinate": job.sampling_coordinate.to_mapping(),
            "source_root_mapping": None,
        },
    )
    component_result = {
        "evidence_kind": "authenticated-test-component",
        "result": result.to_mapping(),
    }
    return _synthetic_stage_outcome(
        digits=64,
        numerical_state="CONVERGED",
        component_result=component_result,
        local_disk_radius_abs=6.0e-9,
    )


class CampaignPlanTests(unittest.TestCase):
    def test_enclosed_baseline_polish_is_published_to_solved_leaf_store(self) -> None:
        """Catches requiring a polished zero-amplitude root to equal its seed."""

        plan = build_campaign_plan(
            policy=NumericalPolicy(),
            backend_identity=VettedNativeDeterminantKernel.identity,
            precision_capabilities=PrecisionCapabilities((64,)),
        )
        leaf = next(item for item in plan.leaves if item.role == "primary")
        selection = build_campaign_selection(
            plan, role="primary", leaf_ids=(leaf.leaf_id,)
        )

        class Backend:
            identity = plan.backend_identity
            precision_capabilities = plan.precision_capabilities

            def __init__(self, baseline_delta):
                self.baseline_delta = baseline_delta

            def execute_stage(self, selected, digits):
                return _produced_stage_outcome(
                    selected,
                    complex(1.0, -0.5),
                    baseline_delta=self.baseline_delta,
                )

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = SolvedLeafStore(root / "solved-leaves")
            checkpoint = root / "checkpoint.json"
            run_campaign_selection(
                plan,
                selection,
                Backend(complex(1.0e-12, -2.0e-12)),
                checkpoint,
                resume=False,
                solved_leaf_store=store,
            )

            self.assertEqual(store.stored_count, 1)
            imported_store = SolvedLeafStore(root / "imported-solved-leaves")
            imported = import_campaign_checkpoint_to_solved_leaf_store(
                plan, checkpoint, imported_store
            )
            self.assertEqual(imported.imported_count, 1)
            self.assertEqual(imported_store.stored_count, 1)

            escaped_store = SolvedLeafStore(root / "escaped-solved-leaves")
            escaped_checkpoint = root / "escaped-checkpoint.json"
            run_campaign_selection(
                plan,
                selection,
                Backend(complex(1.0e-2, 0.0)),
                escaped_checkpoint,
                resume=False,
                solved_leaf_store=escaped_store,
            )
            self.assertEqual(escaped_store.stored_count, 0)
            with self.assertRaisesRegex(
                ValueError,
                "campaign production baseline root readout evidence is invalid",
            ):
                import_campaign_checkpoint_to_solved_leaf_store(
                    plan,
                    escaped_checkpoint,
                    SolvedLeafStore(root / "escaped-import"),
                )

    def test_source_identity_is_stable_across_checkout_line_endings(self) -> None:
        """Catches Windows checkout conversion changing campaign lineage."""

        source_lf = b"first = 1\nsecond = 2\n"
        source_crlf = source_lf.replace(b"\n", b"\r\n")
        self.assertEqual(
            canonical_text_sha256(source_lf),
            canonical_text_sha256(source_crlf),
        )

    def test_stage_digest_owns_complete_signed_channels_and_v1_is_stale(self) -> None:
        """Catches caller-injected or undigested signed numerical evidence."""

        families = (
            "signed-root", "centred-step-amplitude", "refinement-holdout",
            "truncation", "resolution-angular-refinement",
            "continuation-seed-path", "repeat-polish",
            "precision-ladder-discrepancy",
        )
        component_result = {"leaf_id": "leaf-1"}
        component_sha256 = hashlib.sha256(
            canonical_json_bytes(component_result)
        ).hexdigest()
        channels = tuple({
            "channel_id": f"local:leaf-1:{family}",
            "family": family,
            "shared_group": "leaf-1",
            "provenance": {
                "source_kind": "synthetic-test-stage",
                "source_id": family,
                "source_sha256": component_sha256,
                "derivation": "literal-signed-contract",
            },
            "units": "synthetic-dimensionless-response",
            "signed_delta": {"real": 1.0e-8, "imaginary": 0.0},
            "scope": "local",
        } for family in families)
        outcome = StageOutcome(
            digits=64,
            numerical_state="CONVERGED",
            component_result=component_result,
            local_disk_radius_abs=8.0e-8,
            signed_error_channels=channels,
        )
        record = CampaignStageRecord(outcome, {
            "precision_factory_identity": {
                "factory": "fixture:create_backend", "module_sha256": "b" * 64,
            },
            "available_precision_digits": [64],
        })

        self.assertEqual(CAMPAIGN_SCHEMA_VERSION, 2)
        self.assertEqual(record.to_mapping()["signed_error_channels"], list(channels))
        forged = record.to_mapping()
        injected = dict(forged["signed_error_channels"][0])
        injected["channel_id"] = "local:leaf-1:injected-signed-root"
        injected["signed_delta"] = {"real": 0.0, "imaginary": 0.0}
        forged["signed_error_channels"].append(injected)
        forged["stage_sha256"] = hashlib.sha256(canonical_json_bytes({
            key: value for key, value in forged.items() if key != "stage_sha256"
        })).hexdigest()
        with self.assertRaisesRegex(ValueError, "signed|disk"):
            CampaignStageRecord.from_mapping(forged)

    def test_plan_is_the_exact_ordered_212_leaf_contract(self) -> None:
        """Catches Cartesian completion, dropped roles, or reordered B-prime leaves."""

        plan = build_campaign_plan(
            policy=NumericalPolicy(),
            backend_identity=VettedNativeDeterminantKernel.identity,
            precision_capabilities=PrecisionCapabilities((64,)),
        )
        self.assertEqual(
            tuple(leaf.leaf_id for leaf in plan.leaves),
            B_PRIME_RELEASE_DOMAIN.production_leaf_ids,
        )
        self.assertEqual(plan.role_counts, {
            "primary": 140,
            "control": 24,
            "deep": 48,
        })
        self.assertEqual(plan.mechanism_counts, {
            "horizon-admittance": 40,
            "exterior-fixed-r3": 36,
            "exterior-alpha-half": 28,
            "exterior-light-ring": 48,
            "exterior-throat-kappa": 48,
            "exterior-alpha-one": 12,
        })
        self.assertEqual(len(plan.cohorts), 15)
        self.assertEqual(len(plan.bindings["campaign_source_sha256"]), 64)

    def test_selection_is_canonical_role_bounded_and_rejected_before_work(self) -> None:
        plan = build_campaign_plan(
            policy=NumericalPolicy(),
            backend_identity=VettedNativeDeterminantKernel.identity,
            precision_capabilities=PrecisionCapabilities((64,)),
        )
        primary = [leaf.leaf_id for leaf in plan.leaves if leaf.role == "primary"]
        selection = build_campaign_selection(
            plan, role="primary", leaf_ids=primary[:2]
        )
        self.assertEqual(selection.leaf_ids, tuple(primary[:2]))
        for invalid in (
            (),
            (primary[0], primary[0]),
            tuple(reversed(primary[:2])),
            ("b-prime-leaf-" + "0" * 64,),
            (primary[0], next(
                leaf.leaf_id for leaf in plan.leaves if leaf.role == "control"
            )),
        ):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                build_campaign_selection(plan, role="primary", leaf_ids=invalid)

    def test_full_selection_expands_to_the_exact_ordered_campaign(self) -> None:
        plan = build_campaign_plan(
            policy=NumericalPolicy(),
            backend_identity=VettedNativeDeterminantKernel.identity,
            precision_capabilities=PrecisionCapabilities((64, 80, 120)),
        )

        selection = build_campaign_selection(
            plan, role="all", leaf_ids=None, cohort_ids=None
        )

        self.assertEqual(selection.role, "all")
        self.assertEqual(
            selection.leaf_ids, B_PRIME_RELEASE_DOMAIN.production_leaf_ids
        )
        self.assertEqual(len(selection.leaf_ids), 212)
        with self.assertRaisesRegex(ValueError, "does not accept subset"):
            build_campaign_selection(
                plan,
                role="all",
                leaf_ids=(selection.leaf_ids[0],),
                cohort_ids=None,
            )

    def test_primary_execution_is_mechanism_mode_then_ascending_spin(self) -> None:
        """Catches regression to mode/spin/all-mechanisms campaign traversal."""

        plan = build_campaign_plan(
            policy=NumericalPolicy(),
            backend_identity=VettedNativeDeterminantKernel.identity,
            precision_capabilities=PrecisionCapabilities((64,)),
        )
        primary_ids = tuple(
            leaf.leaf_id for leaf in plan.leaves if leaf.role == "primary"
        )
        selection = build_campaign_selection(
            plan, role="primary", leaf_ids=primary_ids
        )

        class Backend:
            identity = plan.backend_identity
            precision_capabilities = plan.precision_capabilities

            def __init__(self):
                self.calls = []

            def execute_stage(self, leaf, digits):
                self.calls.append((
                    leaf.mechanism_id,
                    leaf.leaf.mode_label,
                    leaf.leaf.coordinate,
                ))
                return _synthetic_stage_outcome(
                    digits=digits,
                    numerical_state="CONVERGED",
                    component_result={"leaf_id": leaf.leaf_id},
                    local_disk_radius_abs=1.0e-8,
                )

        backend = Backend()
        with tempfile.TemporaryDirectory() as temporary:
            checkpoint = Path(temporary) / "checkpoint.json"
            summary = run_campaign_selection(
                plan,
                selection,
                backend,
                checkpoint,
                resume=False,
            )
            authenticated = validate_campaign_checkpoint(plan, checkpoint)

        expected = tuple(
            (mechanism, mode, spin)
            for mechanism in (
                "horizon-admittance",
                "exterior-light-ring",
                "exterior-throat-kappa",
                "exterior-alpha-half",
                "exterior-fixed-r3",
            )
            for mode in ("220", "440", "330", "221", "441", "331", "222")
            for spin in (
                Fraction(19, 20),
                Fraction(99, 100),
                Fraction(999, 1000),
                Fraction(9999, 10000),
            )
        )
        self.assertEqual(tuple(backend.calls), expected)
        self.assertEqual(
            tuple(record.leaf_id for record in summary.records), primary_ids
        )
        self.assertEqual(
            tuple(record.leaf_id for record in authenticated.records), primary_ids
        )

    def test_response_continuation_stays_in_one_mode_mechanism_chain(self) -> None:
        """Catches absolute-root seeding or continuation across scientific chains."""

        plan = build_campaign_plan(
            policy=NumericalPolicy(),
            backend_identity=VettedNativeDeterminantKernel.identity,
            precision_capabilities=PrecisionCapabilities((64,)),
        )
        selected_ids = tuple(
            leaf.leaf_id
            for leaf in plan.leaves
            if leaf.role == "primary"
            and (
                (
                    leaf.mechanism_id == "horizon-admittance"
                    and leaf.leaf.mode_label == "220"
                    and leaf.leaf.coordinate
                    in {Fraction(19, 20), Fraction(99, 100)}
                )
                or (
                    leaf.mechanism_id == "horizon-admittance"
                    and leaf.leaf.mode_label == "440"
                    and leaf.leaf.coordinate == Fraction(19, 20)
                )
                or (
                    leaf.mechanism_id == "exterior-light-ring"
                    and leaf.leaf.mode_label == "220"
                    and leaf.leaf.coordinate == Fraction(19, 20)
                )
            )
        )
        selection = build_campaign_selection(
            plan, role="primary", leaf_ids=selected_ids
        )

        class Backend:
            identity = plan.backend_identity
            precision_capabilities = plan.precision_capabilities

            def __init__(self):
                self.calls = []

            def execute_stage(self, leaf, digits):
                return self.execute_stage_with_predictor(leaf, digits, None)

            def execute_stage_with_predictor(
                self, leaf, digits, response_predictor
            ):
                response = complex(len(self.calls) + 1, -(len(self.calls) + 1))
                self.calls.append((
                    leaf.mechanism_id,
                    leaf.leaf.mode_label,
                    leaf.leaf.coordinate,
                    response_predictor,
                ))
                return _produced_stage_outcome(leaf, response)

        backend = Backend()
        with tempfile.TemporaryDirectory() as temporary:
            run_campaign_selection(
                plan,
                selection,
                backend,
                Path(temporary) / "checkpoint.json",
                resume=False,
            )

        self.assertEqual(tuple(backend.calls), (
            (
                "horizon-admittance",
                "220",
                Fraction(19, 20),
                None,
            ),
            (
                "horizon-admittance",
                "220",
                Fraction(99, 100),
                complex(1.0, -1.0),
            ),
            (
                "horizon-admittance",
                "440",
                Fraction(19, 20),
                None,
            ),
            (
                "exterior-light-ring",
                "220",
                Fraction(19, 20),
                None,
            ),
        ))

    def test_resumed_produced_record_advances_its_response_chain(self) -> None:
        """Catches discarding authenticated continuation state on resume."""

        plan = build_campaign_plan(
            policy=NumericalPolicy(),
            backend_identity=VettedNativeDeterminantKernel.identity,
            precision_capabilities=PrecisionCapabilities((64,)),
        )
        selected_ids = tuple(
            leaf.leaf_id
            for leaf in plan.leaves
            if leaf.role == "primary"
            and leaf.mechanism_id == "horizon-admittance"
            and leaf.leaf.mode_label == "220"
            and leaf.leaf.coordinate
            in {Fraction(19, 20), Fraction(99, 100)}
        )
        selection = build_campaign_selection(
            plan, role="primary", leaf_ids=selected_ids
        )

        class Backend:
            identity = plan.backend_identity
            precision_capabilities = plan.precision_capabilities

            def __init__(self, fail_after=None):
                self.calls = []
                self.fail_after = fail_after

            def execute_stage(self, leaf, digits):
                return self.execute_stage_with_predictor(leaf, digits, None)

            def execute_stage_with_predictor(
                self, leaf, digits, response_predictor
            ):
                if (
                    self.fail_after is not None
                    and len(self.calls) >= self.fail_after
                ):
                    raise RuntimeError("synthetic interruption")
                response = complex(len(self.calls) + 1, -(len(self.calls) + 1))
                self.calls.append((leaf.leaf.coordinate, response_predictor))
                return _produced_stage_outcome(leaf, response)

        with tempfile.TemporaryDirectory() as temporary:
            checkpoint = Path(temporary) / "checkpoint.json"
            with self.assertRaisesRegex(RuntimeError, "interruption"):
                run_campaign_selection(
                    plan,
                    selection,
                    Backend(fail_after=1),
                    checkpoint,
                    resume=False,
                )
            resumed = Backend()
            run_campaign_selection(
                plan,
                selection,
                resumed,
                checkpoint,
                resume=True,
            )

        self.assertEqual(resumed.calls, [
            (Fraction(99, 100), complex(1.0, -1.0)),
        ])

    def test_cached_produced_record_advances_its_response_chain(self) -> None:
        """Catches persistent cache reuse dropping valid continuation state."""

        plan = build_campaign_plan(
            policy=NumericalPolicy(),
            backend_identity=VettedNativeDeterminantKernel.identity,
            precision_capabilities=PrecisionCapabilities((64,)),
        )
        chain_ids = tuple(
            leaf.leaf_id
            for leaf in plan.leaves
            if leaf.role == "primary"
            and leaf.mechanism_id == "horizon-admittance"
            and leaf.leaf.mode_label == "220"
            and leaf.leaf.coordinate
            in {Fraction(19, 20), Fraction(99, 100)}
        )
        first = build_campaign_selection(
            plan, role="primary", leaf_ids=(chain_ids[0],)
        )
        both = build_campaign_selection(
            plan, role="primary", leaf_ids=chain_ids
        )

        class Backend:
            identity = plan.backend_identity
            precision_capabilities = plan.precision_capabilities

            def __init__(self):
                self.calls = []

            def execute_stage(self, leaf, digits):
                return self.execute_stage_with_predictor(leaf, digits, None)

            def execute_stage_with_predictor(
                self, leaf, digits, response_predictor
            ):
                response = complex(len(self.calls) + 1, -(len(self.calls) + 1))
                self.calls.append((leaf.leaf.coordinate, response_predictor))
                return _produced_stage_outcome(leaf, response)

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = SolvedLeafStore(root / "solved-leaves")
            run_campaign_selection(
                plan,
                first,
                Backend(),
                root / "first.json",
                resume=False,
                solved_leaf_store=store,
            )
            warm = Backend()
            run_campaign_selection(
                plan,
                both,
                warm,
                root / "warm.json",
                resume=False,
                solved_leaf_store=store,
            )

        self.assertEqual(warm.calls, [
            (Fraction(99, 100), complex(1.0, -1.0)),
        ])

    def test_old_order_prefix_resumes_into_canonical_sparse_checkpoint(self) -> None:
        """Catches traversal changes invalidating or overwriting solved prefixes."""

        plan = build_campaign_plan(
            policy=NumericalPolicy(),
            backend_identity=VettedNativeDeterminantKernel.identity,
            precision_capabilities=PrecisionCapabilities((64,)),
        )
        primary_ids = tuple(
            leaf.leaf_id for leaf in plan.leaves if leaf.role == "primary"
        )
        full_selection = build_campaign_selection(
            plan, role="primary", leaf_ids=primary_ids
        )

        class Backend:
            identity = plan.backend_identity
            precision_capabilities = plan.precision_capabilities

            def __init__(self, fail_after=None):
                self.calls = []
                self.fail_after = fail_after

            def execute_stage(self, leaf, digits):
                if self.fail_after is not None and len(self.calls) >= self.fail_after:
                    raise RuntimeError("stop after one newly scheduled leaf")
                self.calls.append(leaf.leaf_id)
                return _synthetic_stage_outcome(
                    digits=digits,
                    numerical_state="CONVERGED",
                    component_result={"leaf_id": leaf.leaf_id},
                    local_disk_radius_abs=1.0e-8,
                )

        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            prefix_selection = build_campaign_selection(
                plan, role="primary", leaf_ids=primary_ids[:2]
            )
            prefix_summary = run_campaign_selection(
                plan,
                prefix_selection,
                Backend(),
                directory / "prefix-source.json",
                resume=False,
            )
            checkpoint = directory / "checkpoint.json"
            checkpoint.write_bytes(canonical_json_bytes(
                _checkpoint_mapping(
                    plan, full_selection, prefix_summary.records
                )
            ))

            resumed = Backend(fail_after=1)
            with self.assertRaisesRegex(RuntimeError, "one newly scheduled"):
                run_campaign_selection(
                    plan,
                    full_selection,
                    resumed,
                    checkpoint,
                    resume=True,
                )
            try:
                authenticated = validate_campaign_checkpoint(plan, checkpoint)
            except ValueError as error:
                self.fail(f"sparse resumed checkpoint was rejected: {error}")

        leaf_by_id = {leaf.leaf_id: leaf for leaf in plan.leaves}
        self.assertEqual(len(resumed.calls), 1)
        newly_scheduled = leaf_by_id[resumed.calls[0]]
        self.assertEqual(newly_scheduled.mechanism_id, "horizon-admittance")
        self.assertEqual(newly_scheduled.leaf.mode_label, "220")
        self.assertEqual(newly_scheduled.leaf.coordinate, Fraction(99, 100))
        expected_ids = tuple(
            leaf_id
            for leaf_id in primary_ids
            if leaf_id in {*primary_ids[:2], resumed.calls[0]}
        )
        self.assertEqual(
            tuple(record.leaf_id for record in authenticated.records),
            expected_ids,
        )

    def test_full_execution_prioritizes_projective_roles_and_physical_spin(self) -> None:
        """Catches controls delaying projective rows or Mκ running away from extremality."""

        plan = build_campaign_plan(
            policy=NumericalPolicy(),
            backend_identity=VettedNativeDeterminantKernel.identity,
            precision_capabilities=PrecisionCapabilities((64, 80, 120)),
        )
        selection = build_campaign_selection(
            plan, role="all", leaf_ids=None, cohort_ids=None
        )
        leaf_by_id = {leaf.leaf_id: leaf for leaf in plan.leaves}
        ordered = tuple(
            leaf_by_id[leaf_id]
            for leaf_id in _campaign_execution_leaf_ids(plan, selection)
        )

        self.assertEqual(
            tuple(leaf.role for leaf in ordered),
            ("primary",) * 140 + ("deep",) * 48 + ("control",) * 24,
        )
        first_deep_chain = tuple(
            leaf.leaf.coordinate
            for leaf in ordered
            if leaf.role == "deep"
            and leaf.mechanism_id == "horizon-admittance"
            and leaf.leaf.mode_label == "220"
        )
        self.assertEqual(
            first_deep_chain,
            (Fraction(1, 100), Fraction(1, 500), Fraction(1, 1000)),
        )
        control_mechanisms = tuple(dict.fromkeys(
            leaf.mechanism_id for leaf in ordered if leaf.role == "control"
        ))
        self.assertEqual(control_mechanisms, (
            "exterior-light-ring",
            "exterior-throat-kappa",
            "exterior-fixed-r3",
        ))

    def test_checkpoint_resume_zero_work_and_tamper_are_strict(self) -> None:
        plan = build_campaign_plan(
            policy=NumericalPolicy(),
            backend_identity=VettedNativeDeterminantKernel.identity,
            precision_capabilities=PrecisionCapabilities((64,)),
        )
        primary = [leaf.leaf_id for leaf in plan.leaves if leaf.role == "primary"]

        class Backend:
            identity = plan.backend_identity
            precision_capabilities = plan.precision_capabilities

            def __init__(self, fail_after=None):
                self.calls = []
                self.fail_after = fail_after

            def execute_stage(self, leaf, digits):
                if self.fail_after is not None and len(self.calls) >= self.fail_after:
                    raise RuntimeError("synthetic interruption")
                self.calls.append((leaf.leaf_id, digits))
                return _synthetic_stage_outcome(
                    digits=digits,
                    numerical_state="CONVERGED",
                    component_result={
                        "kind": "deterministic-contract",
                        "leaf_id": leaf.leaf_id,
                        "digits": digits,
                    },
                    local_disk_radius_abs=1.0e-8,
                )

        left = build_campaign_selection(plan, role="primary", leaf_ids=primary[:2])
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            left_path = directory / "left.json"
            interrupted = Backend(fail_after=1)
            with self.assertRaisesRegex(RuntimeError, "synthetic interruption"):
                run_campaign_selection(
                    plan, left, interrupted, left_path, resume=False
                )
            self.assertEqual(len(interrupted.calls), 1)

            resumed = Backend()
            summary = run_campaign_selection(
                plan, left, resumed, left_path, resume=True
            )
            self.assertEqual(summary.executed_stage_count, 1)
            self.assertEqual(summary.reused_stage_count, 1)
            warm = Backend()
            zero = run_campaign_selection(plan, left, warm, left_path, resume=True)
            self.assertEqual(zero.executed_stage_count, 0)
            self.assertEqual(len(warm.calls), 0)

            forged = json.loads(left_path.read_text(encoding="utf-8"))
            forged["records"][0]["stages"][0]["component_result"]["digits"] = 80
            forged["records_sha256"] = hashlib.sha256(
                canonical_json_bytes(forged["records"])
            ).hexdigest()
            tampered = directory / "tampered.json"
            tampered.write_bytes(canonical_json_bytes(forged))
            with self.assertRaises(ValueError):
                validate_campaign_checkpoint(plan, tampered)

    def test_resealed_checkpoint_rejects_swapped_component_lineage(self) -> None:
        """Catches content-digest resealing after a result is moved to another leaf."""

        plan = build_campaign_plan(
            policy=NumericalPolicy(),
            backend_identity=VettedNativeDeterminantKernel.identity,
            precision_capabilities=PrecisionCapabilities((64,)),
        )
        primary = [leaf for leaf in plan.leaves if leaf.role == "primary"]
        selection = build_campaign_selection(
            plan, role="primary", leaf_ids=(primary[0].leaf_id,)
        )

        class Backend:
            identity = plan.backend_identity
            precision_capabilities = plan.precision_capabilities

            def execute_stage(self, leaf, digits):
                return _synthetic_stage_outcome(
                    digits=digits,
                    numerical_state="CONVERGED",
                    component_result={
                        "evidence_kind": "synthetic-orchestration-contract",
                        "leaf_id": leaf.leaf_id,
                        "role": leaf.role,
                        "mechanism_id": leaf.mechanism_id,
                        "job_id": leaf.job.job_id,
                        "root_identity_sha256": leaf.job.root.identity_sha256,
                        "policy_sha256": leaf.job.policy.identity_sha256,
                        "backend_identity_sha256": (
                            leaf.job.backend_identity.identity_sha256
                        ),
                    },
                    local_disk_radius_abs=1.0e-8,
                )

        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            checkpoint = directory / "checkpoint.json"
            run_campaign_selection(
                plan, selection, Backend(), checkpoint, resume=False
            )
            forged = json.loads(checkpoint.read_text(encoding="utf-8"))
            forged["records"][0]["stages"][0]["component_result"][
                "leaf_id"
            ] = primary[1].leaf_id
            reseal_campaign_checkpoint(forged)
            swapped = directory / "swapped.json"
            swapped.write_bytes(canonical_json_bytes(forged))
            with self.assertRaisesRegex(ValueError, "lineage|component"):
                validate_campaign_checkpoint(plan, swapped)

    def test_merge_is_zero_work_and_rejects_disagreement_or_stale_policy(self) -> None:
        plan = build_campaign_plan(
            policy=NumericalPolicy(),
            backend_identity=VettedNativeDeterminantKernel.identity,
            precision_capabilities=PrecisionCapabilities((64,)),
        )

        class Backend:
            identity = plan.backend_identity
            precision_capabilities = plan.precision_capabilities

            def __init__(self):
                self.calls = []

            def execute_stage(self, leaf, digits):
                self.calls.append((leaf.leaf_id, digits))
                return _synthetic_stage_outcome(
                    digits=digits,
                    numerical_state="CONVERGED",
                    component_result={"leaf_id": leaf.leaf_id, "value": 1},
                    local_disk_radius_abs=1.0e-8,
                )

        primary = [leaf.leaf_id for leaf in plan.leaves if leaf.role == "primary"]
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            paths = []
            for index, leaf_id in enumerate(primary[:2]):
                selection = build_campaign_selection(
                    plan, role="primary", leaf_ids=(leaf_id,)
                )
                path = directory / f"part-{index}.json"
                run_campaign_selection(plan, selection, Backend(), path, resume=False)
                paths.append(path)
            merged = merge_campaign_checkpoints(
                plan, (*paths, paths[0]), directory / "merged.json"
            )
            self.assertEqual(merged.result_count, 2)
            self.assertEqual(merged.executed_stage_count, 0)

            forged = json.loads(paths[0].read_text(encoding="utf-8"))
            stage = forged["records"][0]["stages"][0]
            stage["component_result"]["value"] = 2
            component_sha256 = hashlib.sha256(
                canonical_json_bytes(stage["component_result"])
            ).hexdigest()
            for channel in stage["signed_error_channels"]:
                channel["provenance"]["source_sha256"] = component_sha256
            reseal_campaign_checkpoint(forged)
            disagree = directory / "disagree.json"
            disagree.write_bytes(canonical_json_bytes(forged))
            with self.assertRaisesRegex(ValueError, "overlap disagrees"):
                merge_campaign_checkpoints(
                    plan, (paths[0], disagree), directory / "bad.json"
                )

            stale = build_campaign_plan(
                policy=NumericalPolicy(ode_relative_tolerance=1.0e-10),
                backend_identity=plan.backend_identity,
                precision_capabilities=plan.precision_capabilities,
            )
            with self.assertRaisesRegex(ValueError, "invalid|stale"):
                merge_campaign_checkpoints(
                    stale, (paths[0],), directory / "stale.json"
                )

    def test_manifest_paths_and_full_validation_fail_closed(self) -> None:
        plan = build_campaign_plan(
            policy=NumericalPolicy(),
            backend_identity=VettedNativeDeterminantKernel.identity,
            precision_capabilities=PrecisionCapabilities((64,)),
        )
        first = next(leaf.leaf_id for leaf in plan.leaves if leaf.role == "primary")

        class Backend:
            identity = plan.backend_identity
            precision_capabilities = plan.precision_capabilities

            def execute_stage(self, leaf, digits):
                return _synthetic_stage_outcome(
                    digits=digits,
                    numerical_state="CONVERGED",
                    component_result={"leaf_id": leaf.leaf_id},
                    local_disk_radius_abs=1.0e-8,
                )

        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            safe = resolve_campaign_relative_path(directory, "parts/one.json")
            self.assertTrue(safe.is_relative_to(directory.resolve()))
            for unsafe in (
                "/absolute.json",
                "C:\\absolute.json",
                "C:relative.json",
                "\\\\server\\share.json",
                "../escape.json",
                "part.json:stream",
            ):
                with self.subTest(unsafe=unsafe), self.assertRaises(ValueError):
                    resolve_campaign_relative_path(directory, unsafe)
            target = directory / "target.json"
            target.write_text("{}", encoding="utf-8")
            link = directory / "link.json"
            link.symlink_to(target)
            with self.assertRaises(ValueError):
                resolve_campaign_relative_path(directory, "link.json")

            selection = build_campaign_selection(
                plan, role="primary", leaf_ids=(first,)
            )
            checkpoint = directory / "partial.json"
            run_campaign_selection(plan, selection, Backend(), checkpoint, resume=False)
            with self.assertRaisesRegex(ValueError, "exact ordered"):
                validate_campaign_checkpoint(
                    plan, checkpoint, require_complete_campaign=True
                )

    def test_campaign_plan_and_smoke_commands_emit_one_canonical_object(self) -> None:
        plan = build_campaign_plan(
            policy=NumericalPolicy(),
            backend_identity=VettedNativeDeterminantKernel.identity,
            precision_capabilities=PrecisionCapabilities((64,)),
        )
        first = next(leaf.leaf_id for leaf in plan.leaves if leaf.role == "primary")
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            config = directory / "selection.json"
            config.write_bytes(canonical_json_bytes({
                "schema_version": 1,
                "backend_id": VettedNativeDeterminantKernel.identity.backend_id,
                "precision_digits": [64],
                "precision_backend": None,
                "role": "primary",
                "leaf_ids": [first],
                "cohort_ids": None,
            }))

            def invoke(*arguments):
                return subprocess.run(
                    [sys.executable, "-m", "windows_solver", *arguments],
                    cwd=directory,
                    env={
                        "PYTHONPATH": str(
                            Path(__file__).resolve().parents[1] / "src"
                        ),
                        "LOCALAPPDATA": str(directory),
                    },
                    text=True,
                    capture_output=True,
                )

            planned = invoke("campaign-plan", str(config))
            self.assertEqual(planned.returncode, 0, planned.stderr)
            self.assertEqual(len(planned.stdout.splitlines()), 1)
            payload = json.loads(planned.stdout)
            self.assertEqual(payload["leaf_count"], 212)
            self.assertEqual(payload["selected_leaf_count"], 1)

            class Backend:
                identity = plan.backend_identity
                precision_capabilities = plan.precision_capabilities

                def execute_stage(self, leaf, digits):
                    return _synthetic_stage_outcome(
                        digits=digits,
                        numerical_state="CONVERGED",
                        component_result={"leaf_id": leaf.leaf_id},
                        local_disk_radius_abs=1.0e-8,
                    )

            selection = build_campaign_selection(
                plan, role="primary", leaf_ids=(first,)
            )
            checkpoint = directory / "checkpoint.json"
            run_campaign_selection(
                plan, selection, Backend(), checkpoint, resume=False
            )
            resumed = invoke(
                "campaign-resume", str(config), "--checkpoint", checkpoint.name
            )
            self.assertEqual(resumed.returncode, 0, resumed.stderr)
            resumed_payload = json.loads(resumed.stdout)
            self.assertEqual(resumed_payload["executed_stage_count"], 0)
            self.assertNotIn("records", resumed_payload)
            validated = invoke(
                "campaign-validate", str(config), "--checkpoint", checkpoint.name
            )
            self.assertEqual(validated.returncode, 0, validated.stderr)

            merge_manifest = directory / "merge.json"
            merge_manifest.write_bytes(canonical_json_bytes({
                "schema_version": 1,
                "backend_id": plan.backend_identity.backend_id,
                "precision_digits": [64],
                "precision_backend": None,
                "checkpoint_paths": ["checkpoint.json", "checkpoint.json"],
            }))
            merged = invoke(
                "campaign-merge",
                str(merge_manifest),
                "--output",
                "merged.json",
            )
            self.assertEqual(merged.returncode, 0, merged.stderr)
            self.assertEqual(json.loads(merged.stdout)["result_count"], 1)

            cold = invoke(
                "campaign-run",
                str(config),
                "--checkpoint",
                "cold.json",
            )
            self.assertEqual(cold.returncode, 3)
            self.assertFalse((directory / "cold.json").exists())
            self.assertEqual(
                json.loads(cold.stderr.splitlines()[-1])["error"]["code"],
                "PROVIDER_UNAVAILABLE",
            )
            failed_status = json.loads(
                (directory / "cold.json.status.json").read_text(encoding="utf-8")
            )
            self.assertEqual(failed_status["kind"], "request_failed")

            smoke = invoke("campaign-smoke")
            self.assertEqual(smoke.returncode, 0, smoke.stderr)
            self.assertEqual(len(smoke.stdout.splitlines()), 1)
            self.assertEqual(json.loads(smoke.stdout)["smoke_case_count"], 10)

            invalid = json.loads(config.read_text(encoding="utf-8"))
            second = next(
                leaf.leaf_id
                for leaf in plan.leaves
                if leaf.role == "primary" and leaf.leaf_id != first
            )
            invalid["leaf_ids"] = [second, first]
            config.write_bytes(canonical_json_bytes(invalid))
            rejected = invoke("campaign-plan", str(config))
            self.assertEqual(rejected.returncode, 2)
            self.assertEqual(len(rejected.stderr.splitlines()), 1)
            self.assertEqual(json.loads(rejected.stderr)["error"]["code"], "INVALID_INPUT")

    def test_cli_authenticates_precision_factory_and_paths_before_import(self) -> None:
        """Catches unauthenticated plugins and unsafe output paths reaching imports."""

        root = Path(__file__).resolve().parents[1]
        identity = VettedNativeDeterminantKernel.identity
        plan = build_campaign_plan(
            policy=NumericalPolicy(),
            backend_identity=identity,
            precision_capabilities=PrecisionCapabilities((64, 80)),
        )
        first = next(leaf.leaf_id for leaf in plan.leaves if leaf.role == "primary")
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            marker = directory / "imported.txt"
            module = directory / "operator_backend.py"
            source = (
                "from pathlib import Path\n"
                "from windows_solver.response_batches import PrecisionCapabilities\n"
                "from windows_solver.response_engine import VettedNativeDeterminantKernel\n"
                f"Path({str(marker)!r}).write_text('imported', encoding='utf-8')\n"
                "class Backend:\n"
                "    identity = VettedNativeDeterminantKernel.identity\n"
                "    precision_capabilities = PrecisionCapabilities((64,))\n"
                "def create_backend():\n"
                "    return Backend()\n"
            )
            module.write_text(source, encoding="utf-8")
            descriptor = {
                "factory": "operator_backend:create_backend",
                "module_path": "operator_backend.py",
                "module_sha256": hashlib.sha256(module.read_bytes()).hexdigest(),
                "backend_identity": identity.to_mapping(),
                "available_precision_digits": [64, 80],
            }
            descriptor_plan = build_campaign_plan(
                policy=NumericalPolicy(),
                backend_identity=identity,
                precision_capabilities=PrecisionCapabilities((64, 80)),
                precision_factory_identity=PrecisionFactoryIdentity(
                    descriptor["factory"], descriptor["module_sha256"]
                ),
            )
            selection = directory / "selection.json"
            selection.write_bytes(canonical_json_bytes({
                "schema_version": 1,
                "backend_id": identity.backend_id,
                "precision_digits": [64, 80],
                "precision_backend": descriptor,
                "role": "primary",
                "leaf_ids": [first],
                "cohort_ids": None,
            }))

            def invoke(*arguments):
                return subprocess.run(
                    [sys.executable, "-m", "windows_solver", *arguments],
                    cwd=directory,
                    env={"PYTHONPATH": str(root / "src")},
                    text=True,
                    capture_output=True,
                )

            planned = invoke("campaign-plan", "selection.json")
            self.assertEqual(planned.returncode, 0, planned.stderr)
            self.assertFalse(marker.exists(), "plan imported the operator backend")

            class ContractBackend:
                identity = descriptor_plan.backend_identity
                precision_capabilities = PrecisionCapabilities((64,))

                def execute_stage(self, leaf, digits):
                    return _synthetic_stage_outcome(
                        digits=64,
                        numerical_state="CONVERGED",
                        component_result={
                            "evidence_kind": "synthetic-orchestration-contract",
                            "leaf_id": leaf.leaf_id,
                            "role": leaf.role,
                            "mechanism_id": leaf.mechanism_id,
                            "digits": 64,
                        },
                        local_disk_radius_abs=1.0e-8,
                    )

            direct_selection = build_campaign_selection(
                descriptor_plan, role="primary", leaf_ids=(first,)
            )
            run_campaign_selection(
                descriptor_plan,
                direct_selection,
                ContractBackend(),
                directory / "validated.json",
                resume=False,
            )
            validated = invoke(
                "campaign-validate",
                "selection.json",
                "--checkpoint",
                "validated.json",
            )
            self.assertEqual(validated.returncode, 0, validated.stderr)
            self.assertFalse(marker.exists(), "validate imported the operator backend")

            unsafe = invoke(
                "campaign-run", "selection.json", "--checkpoint", "../escape.json"
            )
            self.assertEqual(unsafe.returncode, 2, unsafe.stderr)
            self.assertIn("unsafe", unsafe.stderr)
            self.assertFalse(marker.exists(), "unsafe path reached backend import")

            capability = invoke(
                "campaign-run", "selection.json", "--checkpoint", "checkpoint.json"
            )
            self.assertEqual(capability.returncode, 2, capability.stderr)
            self.assertIn("capabil", capability.stderr)
            self.assertTrue(marker.exists(), "validated run did not load the factory")
            self.assertFalse((directory / "checkpoint.json").exists())

            marker.unlink()
            forged = json.loads(selection.read_text(encoding="utf-8"))
            forged["precision_backend"]["module_sha256"] = "0" * 64
            selection.write_bytes(canonical_json_bytes(forged))
            rejected = invoke("campaign-plan", "selection.json")
            self.assertEqual(rejected.returncode, 2, rejected.stderr)
            self.assertFalse(marker.exists(), "hash mismatch reached backend import")

            merge = directory / "merge.json"
            merge.write_bytes(canonical_json_bytes({
                "schema_version": 1,
                "backend_id": identity.backend_id,
                "precision_digits": [64, 80],
                "precision_backend": descriptor,
                "checkpoint_paths": ["missing.json"],
            }))
            unsafe_output = invoke(
                "campaign-merge", "merge.json", "--output", "C:relative.json"
            )
            self.assertEqual(unsafe_output.returncode, 2, unsafe_output.stderr)
            self.assertIn("unsafe", unsafe_output.stderr)

    def test_stage_factory_binding_is_plan_bound_and_resealed_tamper_rejected(self) -> None:
        """Catches removal or resealed replacement of runner-stamped factory identity."""

        plan = build_campaign_plan(
            policy=NumericalPolicy(),
            backend_identity=VettedNativeDeterminantKernel.identity,
            precision_capabilities=PrecisionCapabilities((64,)),
        )
        self.assertIn("precision_factory_identity", plan.bindings)
        leaf = next(item for item in plan.leaves if item.role == "primary")
        selection = build_campaign_selection(
            plan, role="primary", leaf_ids=(leaf.leaf_id,)
        )

        class Backend:
            identity = plan.backend_identity
            precision_capabilities = plan.precision_capabilities

            def execute_stage(self, selected, digits):
                return _synthetic_stage_outcome(
                    digits=64,
                    numerical_state="CONVERGED",
                    component_result={"leaf_id": selected.leaf_id},
                    local_disk_radius_abs=1.0e-8,
                )

        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            checkpoint = directory / "checkpoint.json"
            run_campaign_selection(
                plan, selection, Backend(), checkpoint, resume=False
            )
            forged = json.loads(checkpoint.read_text(encoding="utf-8"))
            provenance = forged["records"][0]["stages"][0]["runner_provenance"]
            provenance["precision_factory_identity"]["module_sha256"] = "0" * 64
            reseal_campaign_checkpoint(forged)
            tampered = directory / "tampered.json"
            tampered.write_bytes(canonical_json_bytes(forged))
            with self.assertRaisesRegex(ValueError, "factory|provenance"):
                validate_campaign_checkpoint(plan, tampered)

    def test_same_backend_identity_different_factory_rejects_resume_and_merge(self) -> None:
        """Catches a substituted module claiming an unchanged BackendIdentity."""

        root = Path(__file__).resolve().parents[1]
        fixture = (root / "tests/fixtures/campaign_precision_backend.py").read_bytes()
        fixture = fixture.replace(
            b"PrecisionCapabilities((64,))",
            b"PrecisionCapabilities((64, 80))",
        )
        identity = VettedNativeDeterminantKernel.identity
        plan = build_campaign_plan(
            policy=NumericalPolicy(),
            backend_identity=identity,
            precision_capabilities=PrecisionCapabilities((64,)),
        )
        leaf_id = next(leaf.leaf_id for leaf in plan.leaves if leaf.role == "primary")
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            module_a = directory / "backend_a.py"
            module_b = directory / "backend_b.py"
            module_a.write_bytes(fixture + b"\n# factory-a\n")
            module_b.write_bytes(fixture + b"\n# factory-b\n")

            def descriptor(name, path, digits=(64, 80)):
                return {
                    "factory": f"{name}:create_backend",
                    "module_path": path.name,
                    "module_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    "backend_identity": identity.to_mapping(),
                    "available_precision_digits": list(digits),
                }

            def selection(backend):
                return {
                    "schema_version": 1,
                    "backend_id": identity.backend_id,
                    "precision_digits": [64],
                    "precision_backend": backend,
                    "role": "primary",
                    "leaf_ids": [leaf_id],
                    "cohort_ids": None,
                }

            selection_path = directory / "selection.json"
            selection_path.write_bytes(canonical_json_bytes(
                selection(descriptor("backend_a", module_a))
            ))

            def invoke(*arguments):
                return subprocess.run(
                    [sys.executable, "-m", "windows_solver", *arguments],
                    cwd=directory,
                    env={
                        "PYTHONPATH": str(root / "src"),
                        "LOCALAPPDATA": str(directory),
                    },
                    text=True,
                    capture_output=True,
                )

            cold = invoke(
                "campaign-run", "selection.json", "--checkpoint", "checkpoint.json"
            )
            self.assertEqual(cold.returncode, 0, cold.stderr)
            downgraded = descriptor("backend_a", module_a, (64,))
            selection_path.write_bytes(canonical_json_bytes(selection(downgraded)))
            regressed = invoke(
                "campaign-resume", "selection.json", "--checkpoint", "checkpoint.json"
            )
            substituted = descriptor("backend_b", module_b)
            selection_path.write_bytes(canonical_json_bytes(selection(substituted)))
            resumed = invoke(
                "campaign-resume", "selection.json", "--checkpoint", "checkpoint.json"
            )
            merge_path = directory / "merge.json"
            merge_path.write_bytes(canonical_json_bytes({
                "schema_version": 1,
                "backend_id": identity.backend_id,
                "precision_digits": [64],
                "precision_backend": substituted,
                "checkpoint_paths": ["checkpoint.json"],
            }))
            merged = invoke(
                "campaign-merge", "merge.json", "--output", "merged.json"
            )
            self.assertEqual(regressed.returncode, 2, regressed.stderr)
            self.assertEqual(resumed.returncode, 2, resumed.stderr)
            self.assertEqual(merged.returncode, 2, merged.stderr)
            self.assertFalse((directory / "merged.json").exists())

    def test_precision_factory_executes_the_verified_bytes_after_path_race(self) -> None:
        """Catches reopening a changed module after its authenticated read."""

        from windows_solver.cli import (
            _campaign_backend_descriptor,
            _load_campaign_backend,
        )

        root = Path(__file__).resolve().parents[1]
        fixture = (root / "tests/fixtures/campaign_precision_backend.py").read_bytes()
        identity = VettedNativeDeterminantKernel.identity
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            module = directory / "race_backend.py"
            marker = directory / "marker.txt"
            module.write_bytes(fixture)
            value = {
                "factory": "race_backend:create_backend",
                "module_path": module.name,
                "module_sha256": hashlib.sha256(fixture).hexdigest(),
                "backend_identity": identity.to_mapping(),
                "available_precision_digits": [64],
            }
            _, descriptor = _campaign_backend_descriptor(value, directory)
            module.write_bytes(fixture.replace(b'"verified"', b'"changed"'))
            with patch.dict(
                os.environ,
                {"CAMPAIGN_PRECISION_FIXTURE_MARKER": str(marker)},
            ):
                backend = _load_campaign_backend(descriptor)
            self.assertEqual(backend.identity, identity)
            self.assertEqual(marker.read_text(encoding="utf-8"), "verified")


if __name__ == "__main__":
    unittest.main()
