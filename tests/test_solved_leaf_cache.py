from __future__ import annotations

from dataclasses import replace
from copy import deepcopy
from decimal import Decimal
import hashlib
import io
import json
from fractions import Fraction
import os
from pathlib import Path
import shutil
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import windows_solver.solved_leaf_cache as solved_leaf_cache_module
import windows_solver.response_batches as response_batches
from windows_solver.contracts import canonical_json_bytes
from windows_solver.linear_response import B_PRIME_RELEASE_DOMAIN
from windows_solver.response_batches import (
    CampaignLeafRecord,
    CampaignStageRecord,
    NativeCampaignStageBackend,
    PrecisionCapabilities,
    StageOutcome,
    _authenticated_solved_leaf_lookup,
    _validate_record_scientific_execution_contract,
    _validate_component_result,
    _validate_cacheable_leaf_record,
    build_campaign_plan,
    build_campaign_selection,
    import_campaign_checkpoint_to_solved_leaf_store,
    scientific_computation_identity_sha256,
    run_campaign_selection,
    synthetic_stage_signed_error_channels,
)
from windows_solver.julia_response_backend import (
    JuliaPrecisionRootBackend,
    JuliaResponseBackendError,
)
from windows_solver.response_engine import (
    BackendIdentity,
    ComponentResult,
    ComponentStatus,
    DiagnosticRootReadout,
    LadderLevel,
    NumericalPolicy,
    NumericalConditioningEvidence,
    RootReadout,
    VettedNativeDeterminantKernel,
)
from windows_solver.progress import activate_progress
from windows_solver.progress_output import CampaignProgressReporter
from windows_solver.root_readout_cache import (
    RootReadoutLookupStatus,
    RootReadoutStore,
    runtime_identity_sha256,
)
from windows_solver.solved_leaf_cache import SolvedLeafLookupStatus, SolvedLeafStore
from windows_solver.promoted_control_calibration import (
    EXTERIOR_DETERMINANT_ABSOLUTE_ERROR_CERTIFICATE,
)
from tests.fixtures import (
    current_promoted_component_payload,
    frozen_pr58_native_backend_identity,
    synthetic_ode_error_budget,
    valid_numerical_conditioning,
)


_FROZEN_MIGRATION_BACKEND_IDENTITY = frozen_pr58_native_backend_identity()


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
    "b-prime-leaf-4c8594e4a59486a1c56206e41cd7f7f3ff1ab5193a5ff6b699cbe9492bc45355": "ec654b7047015d7d38963416bd7625742f84f6c85fbb5a2479adc5ad65597fc7",
    "b-prime-leaf-0f36daefa853de1280f17c8b8ef89bbaf9b34f5e5044a5eb85bc563d3896b60d": "0c5a5c15ccf2ef29e7937c4a75266043043c3238075eb4b169652b09af73d9c2",
    "b-prime-leaf-08b8dc3df83fc1304a61d8b6105c412a316a44816ca229d375573fdf72ac0a57": "779da2d453b4492e8f9a847d768362c2d902e4fa8c3846e3dab9a6aa8a6da023",
}


def _production_outcome(
    leaf,
    *,
    digits=64,
    status=ComponentStatus.CONVERGED,
    baseline_omega=None,
    root_reference_id=None,
    branch_id=None,
    root_identity_sha256=None,
    seed_path_radius=8.0e-12,
    determinant_residual_abs=2.0e-13,
    determinant_derivative_abs=1.0,
):
    job = leaf.job
    baseline = RootReadout(
        omega=job.root.omega if baseline_omega is None else baseline_omega,
        determinant_residual_abs=determinant_residual_abs,
        determinant_derivative_abs=determinant_derivative_abs,
        converged=status is not ComponentStatus.NOT_CONVERGED,
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
    levels = ()
    if status is ComponentStatus.CONVERGED:
        diagnostic_deltas = {
            "truncation": complex(3.0e-12, -1.0e-12),
            "resolution": complex(-2.0e-12, 2.0e-12),
            "seed-path": complex(1.0e-12, 3.0e-12),
        }

        def signed_readout(amplitude):
            omega = job.root.omega + complex(2.0e-4, -1.0e-4) * amplitude
            return RootReadout(
                omega=omega,
                determinant_residual_abs=2.0e-13,
                determinant_derivative_abs=1.0,
                converged=True,
                root_reference_id=job.root.root_reference_id,
                branch_id=job.root.branch_id,
                equation_id=job.equation_id,
                truncation_radius=abs(diagnostic_deltas["truncation"]),
                resolution_radius=abs(diagnostic_deltas["resolution"]),
                seed_path_radius=abs(diagnostic_deltas["seed-path"]),
                diagnostic_readouts={
                    family: DiagnosticRootReadout(
                        omega_delta_from_primary=delta,
                        determinant_residual_abs=1.0e-13,
                        determinant_derivative_abs=1.0,
                        converged=True,
                    )
                    for family, delta in diagnostic_deltas.items()
                },
                source_root_mapping=job.source_root_mapping,
            )

        levels = tuple(
            LadderLevel(
                epsilon=epsilon,
                real_plus=signed_readout(complex(epsilon, 0.0)),
                real_minus=signed_readout(complex(-epsilon, 0.0)),
                imaginary_plus=signed_readout(complex(0.0, epsilon)),
                imaginary_minus=signed_readout(complex(0.0, -epsilon)),
            )
            for epsilon in job.policy.epsilons[:4]
        )
    result = ComponentResult(
        job_id=job.job_id,
        leaf_id=job.leaf_id,
        mechanism_id=job.mechanism_id,
        status=status,
        convergence_basis=(
            "ORDER_RESOLVED" if status is ComponentStatus.CONVERGED else "UNRESOLVED"
        ),
        response=(
            complex(1.0, -0.5) if status is ComponentStatus.CONVERGED else None
        ),
        signed_root_crosscheck=(
            complex(1.0, -0.5) if status is ComponentStatus.CONVERGED else None
        ),
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
        levels=levels,
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
    if digits in (80, 120):
        component = current_promoted_component_payload(
            result,
            digits,
            precision_limited=(
                digits == 80 and status is ComponentStatus.NOT_CONVERGED
            ),
            leaf=leaf,
        )
    return StageOutcome(
        digits=digits,
        numerical_state=status.value,
        component_result=component,
        local_disk_radius_abs=1.0e-8,
        signed_error_channels=synthetic_stage_signed_error_channels(
            component, 1.0e-8
        ),
    )


def _legacy_primary_record(plan, leaf, status, **outcome_changes):
    """Seal the predecessor's binary64-only PRIMARY record.

    The approved migration contract changes PRIMARY orchestration policy only:
    leaf/job/root/policy/backend/readout and precision-factory identities stay
    exact.  The legacy identity supplied by each test is therefore the only
    predecessor-only value; this stage provenance deliberately remains current.
    """

    outcome = _production_outcome(leaf, status=status, **outcome_changes)
    return CampaignLeafRecord(
        leaf_id=leaf.leaf_id,
        role="primary",
        state=("PRODUCED" if status is ComponentStatus.CONVERGED else "UNRESOLVED"),
        stages=(CampaignStageRecord(
            outcome,
            {
                "precision_factory_identity": (
                    plan.precision_factory_identity.to_mapping()
                ),
                "available_precision_digits": [64],
            },
        ),),
    )


def _replace_component_result_fields(outcome, **changes):
    """Reseal a synthetic outcome containing a deliberately impossible body."""

    component = dict(outcome.component_result)
    component["result"] = replace(
        ComponentResult.from_mapping(component["result"]),
        **changes,
    ).to_mapping()
    return replace(
        outcome,
        component_result=component,
        signed_error_channels=synthetic_stage_signed_error_channels(
            component, outcome.local_disk_radius_abs
        ),
    )


def _frozen_predecessor_precision_contract(leaf):
    """The M01 contract, frozen independently of production policy helpers."""

    return {
        "binary64_stage_required": True,
        "deep_leaf": leaf.role == "deep",
        "promotion_digits": [80, 120] if leaf.role == "deep" else [],
        "promotion_gates": list(B_PRIME_RELEASE_DOMAIN.precision_promotion_gates),
        "fixed_precision_sentinel": leaf.leaf_id in set(
            B_PRIME_RELEASE_DOMAIN.fixed_precision_sentinel_leaf_ids
        ),
    }


def _frozen_previous_recovery_contract():
    """The pre-PR-33 PRIMARY recovery contract, independent of production."""

    return {
        "binary64_trigger": {
            "component_status": ComponentStatus.NOT_CONVERGED.value,
            "requires_canonical_production_evidence": True,
        },
        "recovery_digits": [80, 120],
        "precision120_gates": {
            "component_status": ComponentStatus.NOT_CONVERGED.value,
            "self_refinement_enclosed": False,
            "discrepancy_enclosed": False,
        },
        "precision120_terminal_success": {
            "component_status": ComponentStatus.CONVERGED.value,
            "discrepancy_enclosed": True,
        },
    }


def _frozen_raw_residual_promoted_controls():
    """The immediate-main promoted controls, independent of production."""

    return {
        "80": {
            "base": {
                "root_tolerance": "1e-18",
                "ode_relative_tolerance": "1e-18",
                "ode_absolute_tolerance": "1e-20",
                "frequency_step": "1e-6",
            },
            "refinement": {
                "root_tolerance": "1e-20",
                "ode_relative_tolerance": "1e-20",
                "ode_absolute_tolerance": "1e-20",
                "frequency_step": "1e-7",
            },
        },
        "120": {
            "base": {
                "root_tolerance": "1e-102",
                "ode_relative_tolerance": "1e-102",
                "ode_absolute_tolerance": "1e-104",
                "frequency_step": "1e-60",
            },
            "refinement": {
                "root_tolerance": "1e-106",
                "ode_relative_tolerance": "1e-106",
                "ode_absolute_tolerance": "1e-108",
                "frequency_step": "1e-60",
            },
        },
    }


def _frozen_response_uncertainty_contract():
    return {
        "version": 2,
        "primary_disk": "combined_signed_secant_two_finest_level_richardson",
        "diagnostic_phases": ["TRUNCATION", "RESOLUTION", "SEED-PATH"],
        "diagnostic_disk": "signed_phase_secants_two_finest_level_richardson",
        "containment_increment": (
            "max_axis_of_max_zero_control_distance_plus_control_radius_"
            "minus_primary_combined_radius"
        ),
        "baseline_diagnostic_displacement_excluded": True,
        "root_space_displacements": "branch_continuation_only",
        "units": "dimensionless_response",
    }


def _frozen_scientific_identity(
    plan, leaf, precision_contract, *, corrected_uncertainty=True
):
    """Build an independently frozen one-leaf scientific identity."""

    material = {
        "schema_version": 1,
        "leaf_id": leaf.leaf_id,
        "role": leaf.role,
        "mode_label": leaf.leaf.mode_label,
        "mode": list(leaf.leaf.mode),
        "spin_role": leaf.leaf.spin_role,
        "coordinate_exact": {
            "numerator": leaf.leaf.coordinate.numerator,
            "denominator": leaf.leaf.coordinate.denominator,
        },
        "spin_binary64_hex": leaf.leaf.spin.hex(),
        "mechanism_id": leaf.mechanism_id,
        "response_job": leaf.job.to_mapping(),
        "precision_factory_identity": plan.precision_factory_identity.to_mapping(),
        "precision_contract": precision_contract,
    }
    if corrected_uncertainty:
        material["response_uncertainty_contract"] = (
            _frozen_response_uncertainty_contract()
        )
    return hashlib.sha256(canonical_json_bytes(material)).hexdigest()


def _frozen_predecessor_scientific_identity(plan, leaf):
    """Rebuild the exact pre-recovery identity without production helpers."""

    return _frozen_scientific_identity(
        plan,
        leaf,
        _frozen_predecessor_precision_contract(leaf),
        corrected_uncertainty=False,
    )


def _frozen_previous_recovery_scientific_identity(plan, leaf):
    """Rebuild the exact pre-PR-33 PRIMARY identity independently."""

    contract = _frozen_predecessor_precision_contract(leaf)
    contract["primary_recovery"] = _frozen_previous_recovery_contract()
    return _frozen_scientific_identity(plan, leaf, contract)


def _frozen_raw_residual_scientific_identity(plan, leaf):
    """Rebuild the exact immediate-main PRIMARY identity independently."""

    contract = _frozen_predecessor_precision_contract(leaf)
    contract["primary_recovery"] = {
        **_frozen_previous_recovery_contract(),
        "promoted_numerical_controls": _frozen_raw_residual_promoted_controls(),
    }
    return _frozen_scientific_identity(plan, leaf, contract)


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


def _primary_migration_context():
    plan = build_campaign_plan(
        policy=NumericalPolicy(),
        backend_identity=_FROZEN_MIGRATION_BACKEND_IDENTITY,
        precision_capabilities=PrecisionCapabilities((64, 80)),
    )
    leaf = next(item for item in plan.leaves if item.role == "primary")
    legacy_plan = build_campaign_plan(
        policy=plan.policy,
        backend_identity=plan.backend_identity,
        precision_capabilities=PrecisionCapabilities((64,)),
    )
    legacy_leaf = next(
        item for item in legacy_plan.leaves if item.leaf_id == leaf.leaf_id
    )
    legacy_identity = _frozen_scientific_identity(
        legacy_plan,
        legacy_leaf,
        _frozen_predecessor_precision_contract(legacy_leaf),
    )
    selection = build_campaign_selection(
        plan, role="primary", leaf_ids=(leaf.leaf_id,)
    )
    return plan, leaf, legacy_plan, legacy_leaf, legacy_identity, selection


class _ConvergedProductionBackend:
    def __init__(self, plan):
        self.identity = plan.backend_identity
        self.precision_capabilities = plan.precision_capabilities
        self.calls = []

    def execute_stage(self, leaf, digits):
        self.calls.append((leaf.leaf_id, digits))
        return _production_outcome(leaf, digits=digits)


class SolvedLeafCacheTests(unittest.TestCase):
    def test_typed_raw_overflow_round_trips_through_solved_leaf_store(self):
        """Catches solved-cache sealing or reload dropping the raw status."""

        capabilities = PrecisionCapabilities((64, 80, 120))
        plan = build_campaign_plan(
            policy=NumericalPolicy(),
            backend_identity=VettedNativeDeterminantKernel.identity,
            precision_capabilities=capabilities,
        )
        leaf = next(
            item
            for item in plan.leaves
            if item.job.mechanism_id == "horizon-admittance"
        )
        outcome = _production_outcome(
            leaf,
            digits=80,
            status=ComponentStatus.NOT_CONVERGED,
        )
        component = dict(outcome.component_result)
        result = ComponentResult.from_mapping(component["result"])
        evidence = NumericalConditioningEvidence.from_mapping(
            valid_numerical_conditioning("horizon-admittance")
        )
        receipt = {
            **dict(result.baseline.worker_response_receipt),
            "request_binding": dict(
                result.baseline.worker_response_receipt["request_binding"]
            ),
            "raw_determinant_abs_text": None,
            "raw_determinant_evidence_status": "unavailable-overflow/v1",
        }
        receipt["receipt_sha256"] = hashlib.sha256(
            canonical_json_bytes({
                key: value
                for key, value in receipt.items()
                if key != "receipt_sha256"
            })
        ).hexdigest()
        baseline = replace(
            result.baseline,
            truncation_radius=None,
            resolution_radius=None,
            seed_path_radius=None,
            diagnostic_readouts=None,
            diagnostics_skipped_reason="PRIMARY_NOT_CONVERGED",
            numerical_conditioning=evidence,
            normalised_determinant_abs=Decimal(
                str(result.baseline.determinant_residual_abs)
            ),
            raw_determinant_abs=None,
            raw_determinant_evidence_status="unavailable-overflow/v1",
            worker_response_receipt=receipt,
        )
        component["result"] = replace(result, baseline=baseline).to_mapping()
        outcome = replace(
            outcome,
            component_result=component,
            signed_error_channels=synthetic_stage_signed_error_channels(
                component, outcome.local_disk_radius_abs
            ),
        )
        record = CampaignLeafRecord(
            leaf_id=leaf.leaf_id,
            role=leaf.role,
            state="UNRESOLVED",
            stages=(CampaignStageRecord(
                outcome,
                {
                    "precision_factory_identity": (
                        plan.precision_factory_identity.to_mapping()
                    ),
                    "available_precision_digits": list(capabilities.digits),
                },
            ),),
        )

        with tempfile.TemporaryDirectory() as temporary:
            store = SolvedLeafStore(Path(temporary) / "solved")
            identity = "f" * 64
            store.publish(
                scientific_identity_sha256=identity,
                leaf_id=leaf.leaf_id,
                record=record.to_mapping(),
                source_type="originating-campaign",
            )
            lookup = store.lookup(identity, leaf.leaf_id)

        self.assertIs(lookup.status, SolvedLeafLookupStatus.HIT)
        restored_record = CampaignLeafRecord.from_mapping(
            lookup.receipt["record"]
        )
        restored_result = ComponentResult.from_mapping(
            restored_record.stages[-1].outcome.component_result["result"]
        )
        self.assertEqual(
            restored_result.baseline.raw_determinant_evidence_status,
            "unavailable-overflow/v1",
        )
        self.assertIsNone(restored_result.baseline.raw_determinant_abs)
        self.assertEqual(lookup.receipt["record"], record.to_mapping())

    def test_corrected_live_converged_result_requires_diagnostic_ladder(self):
        plan = build_campaign_plan(
            policy=NumericalPolicy(),
            backend_identity=VettedNativeDeterminantKernel.identity,
            precision_capabilities=PrecisionCapabilities((64,)),
        )
        leaf = next(item for item in plan.leaves if item.role == "primary")
        outcome = _production_outcome(leaf)
        forged = _replace_component_result_fields(outcome, levels=())

        with self.assertRaisesRegex(
            ValueError,
            "diagnostic root evidence is incomplete",
        ):
            _validate_component_result(leaf, forged)

    def test_polished_production_baseline_is_cacheable_under_correction_identity(self):
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
            "d87307db60bbd8a5f4bfcbadf60eb2272aceddffa2e3bcffa7bbfd6fc88403dd",
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

    def test_pre_uncertainty_primary_success_stays_stale_and_recomputes(self):
        """Catches migrating a scalar-only receipt into corrected uncertainty."""

        plan = build_campaign_plan(
            policy=NumericalPolicy(),
            backend_identity=_FROZEN_MIGRATION_BACKEND_IDENTITY,
            precision_capabilities=PrecisionCapabilities((64, 80)),
        )
        leaf = next(item for item in plan.leaves if item.role == "primary")
        legacy_plan = build_campaign_plan(
            policy=plan.policy,
            backend_identity=plan.backend_identity,
            precision_capabilities=PrecisionCapabilities((64,)),
        )
        legacy_leaf = next(
            item for item in legacy_plan.leaves if item.leaf_id == leaf.leaf_id
        )
        legacy_identity = _frozen_predecessor_scientific_identity(
            legacy_plan, legacy_leaf
        )
        self.assertEqual(
            legacy_identity,
            "885c3d1880fdb4cce1f9dfa2d6a5e14eaaae9405f89988d11460d29ff546d8b7",
        )
        selection = build_campaign_selection(
            plan, role="primary", leaf_ids=(leaf.leaf_id,)
        )

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = SolvedLeafStore(root / "solved")
            legacy = _legacy_primary_record(
                legacy_plan, legacy_leaf, ComponentStatus.CONVERGED
            )
            self.assertEqual(legacy_leaf.job.to_mapping(), leaf.job.to_mapping())
            self.assertEqual(
                legacy_plan.precision_factory_identity.to_mapping(),
                plan.precision_factory_identity.to_mapping(),
            )
            self.assertEqual(
                legacy.stages[0].runner_provenance["available_precision_digits"],
                [64],
            )
            self.assertEqual(tuple(stage.outcome.digits for stage in legacy.stages), (64,))
            self.assertEqual(legacy.trigger_ids, ())
            self.assertFalse(legacy.sentinel)
            self.assertIsNone(legacy.missing_precision_digits)
            self.assertIsNone(legacy.sentinel_comparison)
            self.assertIsNone(legacy.stages[0].outcome.deep_diagnostics)
            self.assertIsNone(legacy.stages[0].outcome.self_refinement_enclosed)
            self.assertIsNone(
                legacy.stages[0].outcome.discrepancy_from_previous_abs
            )
            self.assertIsNone(legacy.stages[0].outcome.discrepancy_enclosed)
            store.publish(
                scientific_identity_sha256=legacy_identity,
                leaf_id=leaf.leaf_id,
                record=legacy.to_mapping(),
                source_type="imported-authenticated-checkpoint",
            )
            backend = _ConvergedProductionBackend(plan)
            summary = run_campaign_selection(
                plan,
                selection,
                backend,
                root / "migrated.json",
                resume=False,
                solved_leaf_store=store,
            )

            current_identity = scientific_computation_identity_sha256(plan, leaf)
            self.assertNotEqual(current_identity, legacy_identity)
            self.assertEqual(backend.calls, [(leaf.leaf_id, 64)])
            self.assertEqual(summary.executed_stage_count, 1)
            self.assertNotEqual(summary.records[0].to_mapping(), legacy.to_mapping())
            self.assertEqual(store.stored_count, 2)
            legacy_lookup = store.lookup(legacy_identity, leaf.leaf_id)
            current_lookup = _authenticated_solved_leaf_lookup(plan, leaf, store)
            self.assertIs(legacy_lookup.status, SolvedLeafLookupStatus.HIT)
            self.assertIs(current_lookup.status, SolvedLeafLookupStatus.HIT)
            self.assertEqual(legacy_lookup.receipt["record"], legacy.to_mapping())
            self.assertEqual(
                current_lookup.receipt["record"],
                summary.records[0].to_mapping(),
            )
            self.assertEqual(
                legacy_lookup.receipt["source_type"],
                "imported-authenticated-checkpoint",
            )
            self.assertEqual(current_lookup.receipt["source_type"], "originating-campaign")

    def test_all_pre_uncertainty_predecessor_identities_remain_stale(self):
        plan = build_campaign_plan(
            policy=NumericalPolicy(),
            backend_identity=VettedNativeDeterminantKernel.identity,
            precision_capabilities=PrecisionCapabilities((64, 80)),
        )
        leaf = next(item for item in plan.leaves if item.role == "primary")
        base = _frozen_predecessor_precision_contract(leaf)
        previous = dict(base)
        previous["primary_recovery"] = _frozen_previous_recovery_contract()
        raw_residual = dict(base)
        raw_residual["primary_recovery"] = {
            **_frozen_previous_recovery_contract(),
            "promoted_numerical_controls": _frozen_raw_residual_promoted_controls(),
        }
        old_identities = tuple(
            _frozen_scientific_identity(
                plan,
                leaf,
                contract,
                corrected_uncertainty=False,
            )
            for contract in (base, previous, raw_residual)
        )
        self.assertEqual(len(set(old_identities)), 3)

        for old_identity in old_identities:
            with self.subTest(old_identity=old_identity), tempfile.TemporaryDirectory() as temporary:
                store = SolvedLeafStore(Path(temporary) / "solved")
                record = _legacy_primary_record(
                    plan, leaf, ComponentStatus.CONVERGED
                )
                store.publish(
                    scientific_identity_sha256=old_identity,
                    leaf_id=leaf.leaf_id,
                    record=record.to_mapping(),
                    source_type="originating-campaign",
                )

                lookup = _authenticated_solved_leaf_lookup(plan, leaf, store)

                self.assertIs(lookup.status, SolvedLeafLookupStatus.STALE)
                self.assertTrue((store.root / f"{old_identity}.json").is_file())
                self.assertFalse(
                    (
                        store.root
                        / f"{scientific_computation_identity_sha256(plan, leaf)}.json"
                    ).exists()
                )
                self.assertFalse((store.root / "quarantine").exists())

    def test_exact_previous_recovery_binary64_success_migrates_without_execution(self):
        """Catches invalidating the three clean preloaded binary64 successes."""

        plan = build_campaign_plan(
            policy=NumericalPolicy(),
            backend_identity=VettedNativeDeterminantKernel.identity,
            precision_capabilities=PrecisionCapabilities((64, 80)),
        )
        leaf = next(item for item in plan.leaves if item.role == "primary")
        selection = build_campaign_selection(
            plan, role="primary", leaf_ids=(leaf.leaf_id,)
        )
        previous_identity = _frozen_previous_recovery_scientific_identity(
            plan, leaf
        )
        current_identity = scientific_computation_identity_sha256(plan, leaf)
        self.assertNotEqual(current_identity, previous_identity)

        class Backend:
            identity = plan.backend_identity
            precision_capabilities = plan.precision_capabilities

            def execute_stage(self, selected, digits):
                raise AssertionError(
                    "previous-policy binary64 success reached stage execution"
                )

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = SolvedLeafStore(root / "solved")
            previous = _legacy_primary_record(
                plan, leaf, ComponentStatus.CONVERGED
            )
            store.publish(
                scientific_identity_sha256=previous_identity,
                leaf_id=leaf.leaf_id,
                record=previous.to_mapping(),
                source_type="originating-campaign",
            )

            summary = run_campaign_selection(
                plan,
                selection,
                Backend(),
                root / "migrated.json",
                resume=False,
                solved_leaf_store=store,
            )

            self.assertEqual(summary.executed_stage_count, 0)
            self.assertEqual(summary.records[0].to_mapping(), previous.to_mapping())
            self.assertIs(
                store.lookup(previous_identity, leaf.leaf_id).status,
                SolvedLeafLookupStatus.HIT,
            )
            self.assertIs(
                store.lookup(current_identity, leaf.leaf_id).status,
                SolvedLeafLookupStatus.HIT,
            )

    def test_immediate_raw_residual_success_migrates_on_stored_correction(self):
        """Catches recomputing an old success with valid correction evidence."""

        plan = build_campaign_plan(
            policy=NumericalPolicy(),
            backend_identity=VettedNativeDeterminantKernel.identity,
            precision_capabilities=PrecisionCapabilities((64, 80)),
        )
        leaf = next(item for item in plan.leaves if item.role == "primary")
        selection = build_campaign_selection(
            plan, role="primary", leaf_ids=(leaf.leaf_id,)
        )
        predecessor_identity = _frozen_raw_residual_scientific_identity(
            plan, leaf
        )
        current_identity = scientific_computation_identity_sha256(plan, leaf)
        self.assertNotEqual(current_identity, predecessor_identity)

        class Backend:
            identity = plan.backend_identity
            precision_capabilities = plan.precision_capabilities

            def execute_stage(self, selected, digits):
                raise AssertionError(
                    "correction-qualified predecessor reached stage execution"
                )

        record = _legacy_primary_record(
            plan,
            leaf,
            ComponentStatus.CONVERGED,
            determinant_residual_abs=1.42e-11,
            determinant_derivative_abs=7.8,
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = SolvedLeafStore(root / "solved")
            store.publish(
                scientific_identity_sha256=predecessor_identity,
                leaf_id=leaf.leaf_id,
                record=record.to_mapping(),
                source_type="originating-campaign",
            )

            summary = run_campaign_selection(
                plan,
                selection,
                Backend(),
                root / "migrated.json",
                resume=False,
                solved_leaf_store=store,
            )

            self.assertEqual(summary.executed_stage_count, 0)
            self.assertEqual(summary.records[0].to_mapping(), record.to_mapping())
            self.assertIs(
                store.lookup(current_identity, leaf.leaf_id).status,
                SolvedLeafLookupStatus.HIT,
            )

    def test_immediate_raw_residual_success_recomputes_if_correction_fails(self):
        """Catches migrating old success solely because its receipt is canonical."""

        plan = build_campaign_plan(
            policy=NumericalPolicy(),
            backend_identity=VettedNativeDeterminantKernel.identity,
            precision_capabilities=PrecisionCapabilities((64, 80)),
        )
        leaf = next(item for item in plan.leaves if item.role == "primary")
        selection = build_campaign_selection(
            plan, role="primary", leaf_ids=(leaf.leaf_id,)
        )
        predecessor_identity = _frozen_raw_residual_scientific_identity(
            plan, leaf
        )
        current_identity = scientific_computation_identity_sha256(plan, leaf)
        record = _legacy_primary_record(
            plan,
            leaf,
            ComponentStatus.CONVERGED,
            determinant_residual_abs=1.0e-11,
            determinant_derivative_abs=0.25,
        )

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = SolvedLeafStore(root / "solved")
            store.publish(
                scientific_identity_sha256=predecessor_identity,
                leaf_id=leaf.leaf_id,
                record=record.to_mapping(),
                source_type="originating-campaign",
            )
            backend = _ConvergedProductionBackend(plan)

            summary = run_campaign_selection(
                plan,
                selection,
                backend,
                root / "recomputed.json",
                resume=False,
                solved_leaf_store=store,
            )

            self.assertEqual(backend.calls, [(leaf.leaf_id, 64)])
            self.assertEqual(summary.executed_stage_count, 1)
            self.assertIs(
                store.lookup(predecessor_identity, leaf.leaf_id).status,
                SolvedLeafLookupStatus.HIT,
            )
            self.assertIs(
                store.lookup(current_identity, leaf.leaf_id).status,
                SolvedLeafLookupStatus.HIT,
            )
            self.assertFalse((store.root / "quarantine").exists())

    def test_previous_recovery_promoted_receipt_stays_stale_and_recomputes(self):
        """Catches reusing a 10⁻⁶²-stage result under the practical policy."""

        plan = build_campaign_plan(
            policy=NumericalPolicy(),
            backend_identity=VettedNativeDeterminantKernel.identity,
            precision_capabilities=PrecisionCapabilities((64, 80)),
        )
        leaf = next(item for item in plan.leaves if item.role == "primary")
        selection = build_campaign_selection(
            plan, role="primary", leaf_ids=(leaf.leaf_id,)
        )
        previous_identity = _frozen_previous_recovery_scientific_identity(
            plan, leaf
        )
        current_identity = scientific_computation_identity_sha256(plan, leaf)
        self.assertNotEqual(current_identity, previous_identity)
        stage64 = _production_outcome(
            leaf, status=ComponentStatus.NOT_CONVERGED
        )
        stage80 = replace(
            _production_outcome(leaf, digits=80),
            self_refinement_enclosed=True,
            discrepancy_from_previous_abs=1.0e-19,
            discrepancy_enclosed=True,
        )
        provenance = {
            "precision_factory_identity": (
                plan.precision_factory_identity.to_mapping()
            ),
            "available_precision_digits": [64, 80],
        }
        previous = CampaignLeafRecord(
            leaf_id=leaf.leaf_id,
            role="primary",
            state="PRODUCED",
            stages=(
                CampaignStageRecord(stage64, provenance),
                CampaignStageRecord(stage80, provenance),
            ),
        )

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = SolvedLeafStore(root / "solved")
            store.publish(
                scientific_identity_sha256=previous_identity,
                leaf_id=leaf.leaf_id,
                record=previous.to_mapping(),
                source_type="originating-campaign",
            )
            backend = _ConvergedProductionBackend(plan)

            summary = run_campaign_selection(
                plan,
                selection,
                backend,
                root / "recomputed.json",
                resume=False,
                solved_leaf_store=store,
            )

            self.assertEqual(backend.calls, [(leaf.leaf_id, 64)])
            self.assertEqual(summary.executed_stage_count, 1)
            self.assertEqual(len(summary.records[0].stages), 1)
            self.assertIs(
                store.lookup(previous_identity, leaf.leaf_id).status,
                SolvedLeafLookupStatus.HIT,
            )
            self.assertIs(
                store.lookup(current_identity, leaf.leaf_id).status,
                SolvedLeafLookupStatus.HIT,
            )
            self.assertFalse((store.root / "quarantine").exists())

    def test_legacy_primary_unresolved_record_recomputes_through_recovery_ladder(self):
        """Catches reusing a legacy UNRESOLVED record that must enter recovery."""

        plan = build_campaign_plan(
            policy=NumericalPolicy(),
            backend_identity=_FROZEN_MIGRATION_BACKEND_IDENTITY,
            precision_capabilities=PrecisionCapabilities((64, 80)),
        )
        leaf = next(item for item in plan.leaves if item.role == "primary")
        legacy_plan = build_campaign_plan(
            policy=plan.policy,
            backend_identity=plan.backend_identity,
            precision_capabilities=PrecisionCapabilities((64,)),
        )
        legacy_leaf = next(
            item for item in legacy_plan.leaves if item.leaf_id == leaf.leaf_id
        )
        legacy_identity = _frozen_predecessor_scientific_identity(
            legacy_plan, legacy_leaf
        )
        self.assertEqual(
            legacy_identity,
            "885c3d1880fdb4cce1f9dfa2d6a5e14eaaae9405f89988d11460d29ff546d8b7",
        )
        selection = build_campaign_selection(
            plan, role="primary", leaf_ids=(leaf.leaf_id,)
        )

        class Backend:
            identity = plan.backend_identity
            precision_capabilities = plan.precision_capabilities

            def __init__(self):
                self.calls = []

            def execute_stage(self, selected, digits):
                self.calls.append((selected.leaf_id, digits))
                if digits == 64:
                    return _production_outcome(
                        selected, status=ComponentStatus.NOT_CONVERGED
                    )
                return replace(
                    _production_outcome(selected, digits=80),
                    self_refinement_enclosed=True,
                    discrepancy_from_previous_abs=1.0e-9,
                    discrepancy_enclosed=True,
                )

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = SolvedLeafStore(root / "solved")
            legacy = _legacy_primary_record(
                legacy_plan, legacy_leaf, ComponentStatus.NOT_CONVERGED
            )
            self.assertEqual(legacy_leaf.job.to_mapping(), leaf.job.to_mapping())
            self.assertEqual(
                legacy_plan.precision_factory_identity.to_mapping(),
                plan.precision_factory_identity.to_mapping(),
            )
            self.assertEqual(
                legacy.stages[0].runner_provenance["available_precision_digits"],
                [64],
            )
            self.assertEqual(tuple(stage.outcome.digits for stage in legacy.stages), (64,))
            self.assertEqual(legacy.trigger_ids, ())
            self.assertFalse(legacy.sentinel)
            self.assertIsNone(legacy.missing_precision_digits)
            self.assertIsNone(legacy.sentinel_comparison)
            store.publish(
                scientific_identity_sha256=legacy_identity,
                leaf_id=leaf.leaf_id,
                record=legacy.to_mapping(),
                source_type="originating-campaign",
            )
            backend = Backend()
            summary = run_campaign_selection(
                plan,
                selection,
                backend,
                root / "recomputed.json",
                resume=False,
                solved_leaf_store=store,
            )

        self.assertEqual(backend.calls, [(leaf.leaf_id, 64), (leaf.leaf_id, 80)])
        self.assertEqual(summary.state, "COMPLETE")
        self.assertEqual(summary.records[0].state, "PRODUCED")
        self.assertEqual(
            tuple(stage.outcome.digits for stage in summary.records[0].stages),
            (64, 80),
        )

    def test_arbitrary_same_leaf_stale_success_does_not_authorize_migration(self):
        """Catches treating the cache's generic same-leaf STALE as predecessor proof."""

        plan, leaf, legacy_plan, legacy_leaf, legacy_identity, selection = (
            _primary_migration_context()
        )
        arbitrary_identity = "a" * 64
        self.assertNotEqual(arbitrary_identity, legacy_identity)

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = SolvedLeafStore(root / "solved")
            stale = _legacy_primary_record(
                legacy_plan, legacy_leaf, ComponentStatus.CONVERGED
            )
            store.publish(
                scientific_identity_sha256=arbitrary_identity,
                leaf_id=leaf.leaf_id,
                record=stale.to_mapping(),
                source_type="originating-campaign",
            )
            backend = _ConvergedProductionBackend(plan)
            summary = run_campaign_selection(
                plan,
                selection,
                backend,
                root / "recomputed.json",
                resume=False,
                solved_leaf_store=store,
            )

            current_identity = scientific_computation_identity_sha256(plan, leaf)
            self.assertEqual(backend.calls, [(leaf.leaf_id, 64)])
            self.assertEqual(summary.executed_stage_count, 1)
            self.assertTrue((store.root / f"{arbitrary_identity}.json").is_file())
            self.assertFalse((store.root / f"{legacy_identity}.json").exists())
            self.assertIs(
                store.lookup(current_identity, leaf.leaf_id).status,
                SolvedLeafLookupStatus.HIT,
            )

    def test_semantically_corrupt_exact_legacy_receipt_is_quarantined(self):
        """Catches migrating exact-path evidence sealed for the wrong current job."""

        plan, leaf, _, _, legacy_identity, selection = (
            _primary_migration_context()
        )
        wrong_plan = build_campaign_plan(
            policy=NumericalPolicy(ode_relative_tolerance=1.0e-10),
            backend_identity=plan.backend_identity,
            precision_capabilities=PrecisionCapabilities((64,)),
        )
        wrong_leaf = next(
            item for item in wrong_plan.leaves if item.leaf_id == leaf.leaf_id
        )

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = SolvedLeafStore(root / "solved")
            corrupt = _legacy_primary_record(
                wrong_plan, wrong_leaf, ComponentStatus.NOT_CONVERGED
            )
            store.publish(
                scientific_identity_sha256=legacy_identity,
                leaf_id=leaf.leaf_id,
                record=corrupt.to_mapping(),
                source_type="originating-campaign",
            )
            backend = _ConvergedProductionBackend(plan)
            summary = run_campaign_selection(
                plan,
                selection,
                backend,
                root / "recomputed.json",
                resume=False,
                solved_leaf_store=store,
            )

            current_identity = scientific_computation_identity_sha256(plan, leaf)
            quarantined = tuple((store.root / "quarantine").glob("*.json"))
            self.assertEqual(backend.calls, [(leaf.leaf_id, 64)])
            self.assertEqual(summary.executed_stage_count, 1)
            self.assertFalse((store.root / f"{legacy_identity}.json").exists())
            self.assertEqual(len(quarantined), 1)
            self.assertIs(
                store.lookup(current_identity, leaf.leaf_id).status,
                SolvedLeafLookupStatus.HIT,
            )

    def test_impossible_exact_legacy_produced_receipt_is_quarantined_and_recomputed(self):
        """Catches migrating a CONVERGED record with no consumable response."""

        plan, leaf, legacy_plan, legacy_leaf, legacy_identity, selection = (
            _primary_migration_context()
        )
        legacy = _legacy_primary_record(
            legacy_plan, legacy_leaf, ComponentStatus.CONVERGED
        )
        corrupt_stage = CampaignStageRecord(
            _replace_component_result_fields(
                legacy.stages[0].outcome,
                response=None,
            ),
            legacy.stages[0].runner_provenance,
        )
        corrupt = replace(legacy, stages=(corrupt_stage,))

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = SolvedLeafStore(root / "solved")
            store.publish(
                scientific_identity_sha256=legacy_identity,
                leaf_id=leaf.leaf_id,
                record=corrupt.to_mapping(),
                source_type="originating-campaign",
            )
            backend = _ConvergedProductionBackend(plan)
            summary = run_campaign_selection(
                plan,
                selection,
                backend,
                root / "recomputed.json",
                resume=False,
                solved_leaf_store=store,
            )

            current_identity = scientific_computation_identity_sha256(plan, leaf)
            self.assertEqual(backend.calls, [(leaf.leaf_id, 64)])
            self.assertEqual(summary.records[0].state, "PRODUCED")
            self.assertFalse((store.root / f"{legacy_identity}.json").exists())
            self.assertEqual(
                len(tuple((store.root / "quarantine").glob("*.json"))), 1
            )
            self.assertIs(
                store.lookup(current_identity, leaf.leaf_id).status,
                SolvedLeafLookupStatus.HIT,
            )

    def test_corrupt_current_receipt_is_not_bypassed_by_exact_legacy_success(self):
        """Catches consulting the predecessor after current evidence fails semantics."""

        plan, leaf, legacy_plan, legacy_leaf, legacy_identity, selection = (
            _primary_migration_context()
        )
        current_identity = scientific_computation_identity_sha256(plan, leaf)
        wrong_plan = build_campaign_plan(
            policy=NumericalPolicy(ode_relative_tolerance=1.0e-10),
            backend_identity=plan.backend_identity,
            precision_capabilities=PrecisionCapabilities((64, 80)),
        )
        wrong_leaf = next(
            item for item in wrong_plan.leaves if item.leaf_id == leaf.leaf_id
        )

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = SolvedLeafStore(root / "solved")
            store.publish(
                scientific_identity_sha256=current_identity,
                leaf_id=leaf.leaf_id,
                record=_legacy_primary_record(
                    wrong_plan, wrong_leaf, ComponentStatus.CONVERGED
                ).to_mapping(),
                source_type="originating-campaign",
            )
            store.publish(
                scientific_identity_sha256=legacy_identity,
                leaf_id=leaf.leaf_id,
                record=_legacy_primary_record(
                    legacy_plan, legacy_leaf, ComponentStatus.CONVERGED
                ).to_mapping(),
                source_type="originating-campaign",
            )
            backend = _ConvergedProductionBackend(plan)
            run_campaign_selection(
                plan,
                selection,
                backend,
                root / "recomputed.json",
                resume=False,
                solved_leaf_store=store,
            )

            self.assertEqual(backend.calls, [(leaf.leaf_id, 64)])
            self.assertTrue((store.root / f"{legacy_identity}.json").is_file())
            self.assertEqual(
                len(tuple((store.root / "quarantine").glob("*.json"))), 1
            )

    def test_impossible_current_produced_receipt_is_quarantined_without_legacy_fallback(self):
        """Catches accepting or replacing corrupt current evidence from legacy."""

        plan, leaf, legacy_plan, legacy_leaf, legacy_identity, selection = (
            _primary_migration_context()
        )
        current_identity = scientific_computation_identity_sha256(plan, leaf)
        current = _legacy_primary_record(plan, leaf, ComponentStatus.CONVERGED)
        corrupt_stage = CampaignStageRecord(
            _replace_component_result_fields(
                current.stages[0].outcome,
                signed_root_crosscheck=None,
            ),
            current.stages[0].runner_provenance,
        )
        corrupt = replace(current, stages=(corrupt_stage,))
        legacy = _legacy_primary_record(
            legacy_plan, legacy_leaf, ComponentStatus.CONVERGED
        )

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = SolvedLeafStore(root / "solved")
            store.publish(
                scientific_identity_sha256=current_identity,
                leaf_id=leaf.leaf_id,
                record=corrupt.to_mapping(),
                source_type="originating-campaign",
            )
            store.publish(
                scientific_identity_sha256=legacy_identity,
                leaf_id=leaf.leaf_id,
                record=legacy.to_mapping(),
                source_type="originating-campaign",
            )
            backend = _ConvergedProductionBackend(plan)
            summary = run_campaign_selection(
                plan,
                selection,
                backend,
                root / "recomputed.json",
                resume=False,
                solved_leaf_store=store,
            )

            current_lookup = store.lookup(current_identity, leaf.leaf_id)
            self.assertEqual(backend.calls, [(leaf.leaf_id, 64)])
            self.assertEqual(
                current_lookup.receipt["record"], summary.records[0].to_mapping()
            )
            self.assertNotEqual(current_lookup.receipt["record"], legacy.to_mapping())
            self.assertTrue((store.root / f"{legacy_identity}.json").is_file())
            self.assertEqual(
                len(tuple((store.root / "quarantine").glob("*.json"))), 1
            )

    def test_legacy_migration_race_preserves_authenticated_current_evidence(self):
        """Catches overwriting a current receipt published during migration."""

        plan, leaf, legacy_plan, legacy_leaf, legacy_identity, _ = (
            _primary_migration_context()
        )
        current_identity = scientific_computation_identity_sha256(plan, leaf)
        competing = CampaignLeafRecord(
            leaf_id=leaf.leaf_id,
            role="primary",
            state="PRODUCED",
            stages=(CampaignStageRecord(
                _production_outcome(
                    leaf,
                    baseline_omega=leaf.job.root.omega + complex(1.0e-13, 0.0),
                ),
                {
                    "precision_factory_identity": (
                        plan.precision_factory_identity.to_mapping()
                    ),
                    "available_precision_digits": [64, 80],
                },
            ),),
        )
        _validate_cacheable_leaf_record(plan, leaf, competing)

        class RacingStore(SolvedLeafStore):
            raced = False

            def publish_if_missing(self, **kwargs):
                if (
                    kwargs["scientific_identity_sha256"] == current_identity
                    and not self.raced
                ):
                    self.raced = True
                    SolvedLeafStore.publish(
                        self,
                        scientific_identity_sha256=current_identity,
                        leaf_id=leaf.leaf_id,
                        record=competing.to_mapping(),
                        source_type="originating-campaign",
                    )
                return SolvedLeafStore.publish_if_missing(self, **kwargs)

        with tempfile.TemporaryDirectory() as temporary:
            store = RacingStore(Path(temporary) / "solved")
            store.publish(
                scientific_identity_sha256=legacy_identity,
                leaf_id=leaf.leaf_id,
                record=_legacy_primary_record(
                    legacy_plan, legacy_leaf, ComponentStatus.CONVERGED
                ).to_mapping(),
                source_type="originating-campaign",
            )

            lookup = _authenticated_solved_leaf_lookup(plan, leaf, store)

            self.assertTrue(store.raced)
            self.assertIs(lookup.status, SolvedLeafLookupStatus.HIT)
            self.assertEqual(lookup.receipt["record"], competing.to_mapping())
            self.assertEqual(
                store.lookup(current_identity, leaf.leaf_id).receipt["record"],
                competing.to_mapping(),
            )
            self.assertTrue((store.root / f"{legacy_identity}.json").is_file())

    def test_legacy_migration_waits_for_inflight_current_writer_and_authenticates_winner(self):
        """Catches aborting while the current receipt writer owns the lock."""

        plan, leaf, legacy_plan, legacy_leaf, legacy_identity, _ = (
            _primary_migration_context()
        )
        current_identity = scientific_computation_identity_sha256(plan, leaf)
        competing = CampaignLeafRecord(
            leaf_id=leaf.leaf_id,
            role="primary",
            state="PRODUCED",
            stages=(CampaignStageRecord(
                _production_outcome(
                    leaf,
                    baseline_omega=leaf.job.root.omega + complex(1.0e-13, 0.0),
                ),
                {
                    "precision_factory_identity": (
                        plan.precision_factory_identity.to_mapping()
                    ),
                    "available_precision_digits": [64, 80],
                },
            ),),
        )
        _validate_cacheable_leaf_record(plan, leaf, competing)
        writer_holds_lock = threading.Event()
        release_writer = threading.Event()
        writer_finished = threading.Event()
        migration_observed_lock = threading.Event()
        conditional_attempts = []
        writer_errors = []
        migration_errors = []
        migration_results = []

        class CoordinatedStore(SolvedLeafStore):
            def publish_if_missing(self, **kwargs):
                conditional_attempts.append(kwargs["scientific_identity_sha256"])
                try:
                    return super().publish_if_missing(**kwargs)
                except RuntimeError as error:
                    if str(error) == "solved-leaf cache publication is locked":
                        migration_observed_lock.set()
                        if not writer_finished.wait(5.0):
                            raise AssertionError(
                                "test current writer did not finish"
                            ) from error
                    raise

        with tempfile.TemporaryDirectory() as temporary:
            store = CoordinatedStore(Path(temporary) / "solved")
            store.publish(
                scientific_identity_sha256=legacy_identity,
                leaf_id=leaf.leaf_id,
                record=_legacy_primary_record(
                    legacy_plan, legacy_leaf, ComponentStatus.CONVERGED
                ).to_mapping(),
                source_type="originating-campaign",
            )
            current_path = store.root / f"{current_identity}.json"
            real_atomic_json = solved_leaf_cache_module._atomic_json

            def blocking_atomic_json(path, value):
                if path == current_path:
                    writer_holds_lock.set()
                    if not release_writer.wait(5.0):
                        raise AssertionError("test did not release the current writer")
                return real_atomic_json(path, value)

            def write_current():
                try:
                    store.publish(
                        scientific_identity_sha256=current_identity,
                        leaf_id=leaf.leaf_id,
                        record=competing.to_mapping(),
                        source_type="originating-campaign",
                    )
                except BaseException as error:
                    writer_errors.append(error)
                finally:
                    writer_finished.set()

            def migrate_legacy():
                try:
                    migration_results.append(
                        _authenticated_solved_leaf_lookup(plan, leaf, store)
                    )
                except BaseException as error:
                    migration_errors.append(error)

            with patch.object(
                solved_leaf_cache_module,
                "_atomic_json",
                side_effect=blocking_atomic_json,
            ):
                writer = threading.Thread(target=write_current)
                writer.start()
                self.assertTrue(writer_holds_lock.wait(5.0))
                migration = threading.Thread(target=migrate_legacy)
                migration.start()
                self.assertTrue(migration_observed_lock.wait(5.0))
                release_writer.set()
                writer.join(5.0)
                migration.join(5.0)

            self.assertFalse(writer.is_alive())
            self.assertFalse(migration.is_alive())
            self.assertEqual(writer_errors, [])
            self.assertEqual(migration_errors, [])
            self.assertEqual(
                conditional_attempts,
                [current_identity, current_identity],
            )
            self.assertEqual(len(migration_results), 1)
            lookup = migration_results[0]
            self.assertIs(lookup.status, SolvedLeafLookupStatus.HIT)
            self.assertEqual(lookup.receipt["record"], competing.to_mapping())
            self.assertEqual(
                store.lookup(current_identity, leaf.leaf_id).receipt["record"],
                competing.to_mapping(),
            )
            self.assertTrue((store.root / f"{legacy_identity}.json").is_file())

    def test_legacy_migration_lock_timeout_fails_closed_and_publish_stays_immediate(self):
        """Catches unbounded waiting and changes to originating publication."""

        plan, leaf, legacy_plan, legacy_leaf, legacy_identity, _ = (
            _primary_migration_context()
        )
        current_identity = scientific_computation_identity_sha256(plan, leaf)
        current = _legacy_primary_record(plan, leaf, ComponentStatus.CONVERGED)

        with tempfile.TemporaryDirectory() as temporary:
            store = SolvedLeafStore(Path(temporary) / "solved")
            store.publish(
                scientific_identity_sha256=legacy_identity,
                leaf_id=leaf.leaf_id,
                record=_legacy_primary_record(
                    legacy_plan, legacy_leaf, ComponentStatus.CONVERGED
                ).to_mapping(),
                source_type="originating-campaign",
            )
            lock = store.root / "locks" / f"{current_identity}.lock"
            lock.parent.mkdir(parents=True, exist_ok=True)
            lock.write_bytes(b"")

            with self.assertRaisesRegex(RuntimeError, "publication is locked"):
                store.publish(
                    scientific_identity_sha256=current_identity,
                    leaf_id=leaf.leaf_id,
                    record=current.to_mapping(),
                    source_type="originating-campaign",
                )
            with patch(
                "windows_solver.response_batches._LEGACY_MIGRATION_LOCK_TIMEOUT_SECONDS",
                0.0,
            ):
                with self.assertRaisesRegex(RuntimeError, "timed out"):
                    _authenticated_solved_leaf_lookup(plan, leaf, store)

            self.assertTrue(lock.is_file())
            self.assertFalse((store.root / f"{current_identity}.json").exists())
            self.assertTrue((store.root / f"{legacy_identity}.json").is_file())

    def test_late_corrupt_current_receipt_blocks_legacy_migration(self):
        """Catches replacing late current corruption with predecessor evidence."""

        plan, leaf, legacy_plan, legacy_leaf, legacy_identity, selection = (
            _primary_migration_context()
        )
        current_identity = scientific_computation_identity_sha256(plan, leaf)

        class LateCorruptStore(SolvedLeafStore):
            injected = False
            conditional_status = None

            def _inject_current_corruption(self, identity):
                if identity == current_identity and not self.injected:
                    self.injected = True
                    path = self.root / f"{current_identity}.json"
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(b"{")

            def publish(self, **kwargs):
                self._inject_current_corruption(
                    kwargs["scientific_identity_sha256"]
                )
                return SolvedLeafStore.publish(self, **kwargs)

            def publish_if_missing(self, **kwargs):
                self._inject_current_corruption(
                    kwargs["scientific_identity_sha256"]
                )
                result = SolvedLeafStore.publish_if_missing(self, **kwargs)
                self.conditional_status = result.status
                return result

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = LateCorruptStore(root / "solved")
            legacy = _legacy_primary_record(
                legacy_plan, legacy_leaf, ComponentStatus.CONVERGED
            )
            store.publish(
                scientific_identity_sha256=legacy_identity,
                leaf_id=leaf.leaf_id,
                record=legacy.to_mapping(),
                source_type="originating-campaign",
            )
            backend = _ConvergedProductionBackend(plan)

            summary = run_campaign_selection(
                plan,
                selection,
                backend,
                root / "recomputed.json",
                resume=False,
                solved_leaf_store=store,
            )

            current = store.lookup(current_identity, leaf.leaf_id)
            quarantined = tuple((store.root / "quarantine").glob("*.json"))
            self.assertTrue(store.injected)
            self.assertEqual(backend.calls, [(leaf.leaf_id, 64)])
            self.assertIs(
                store.conditional_status, SolvedLeafLookupStatus.CORRUPT
            )
            self.assertEqual(summary.executed_stage_count, 1)
            self.assertIs(current.status, SolvedLeafLookupStatus.HIT)
            self.assertEqual(
                current.receipt["record"], summary.records[0].to_mapping()
            )
            self.assertNotEqual(current.receipt["record"], legacy.to_mapping())
            self.assertEqual(len(quarantined), 1)
            self.assertTrue((store.root / f"{legacy_identity}.json").is_file())

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

    def test_scientific_execution_contract_changes_cache_identity(self):
        plan = _plan()
        leaf = next(item for item in plan.leaves if item.role == "primary")
        baseline = scientific_computation_identity_sha256(plan, leaf)
        first = {
            "schema": "windows-solver.m02-scientific-execution-contract/1",
            "ode_error_budgets_by_nominal_decimal_digits": {
                "80": {"calibration_identity": "calibration-a/v1"},
            },
        }
        changed = {
            "schema": "windows-solver.m02-scientific-execution-contract/1",
            "ode_error_budgets_by_nominal_decimal_digits": {
                "80": {"calibration_identity": "calibration-b/v1"},
            },
        }

        first_identity = scientific_computation_identity_sha256(
            plan, leaf, scientific_execution_contract=first
        )
        changed_identity = scientific_computation_identity_sha256(
            plan, leaf, scientific_execution_contract=changed
        )

        self.assertNotEqual(first_identity, baseline)
        self.assertNotEqual(first_identity, changed_identity)
        self.assertEqual(
            baseline, scientific_computation_identity_sha256(plan, leaf)
        )

    def test_campaign_cache_reuse_is_scoped_to_backend_execution_contract(self):
        plan = _plan()
        selection = _primary(plan, 1)

        class ContractBackend(_Backend):
            def __init__(self, selected_plan, calibration):
                super().__init__(selected_plan)
                self.contract = {
                    "schema": "synthetic-cache-execution-contract/1",
                    "calibration_identity": calibration,
                }

            def scientific_execution_contract_for(self, leaf):
                return self.contract

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = SolvedLeafStore(root / "solved")
            first = ContractBackend(plan, "calibration-a/v1")
            changed = ContractBackend(plan, "calibration-b/v1")
            repeated = ContractBackend(plan, "calibration-b/v1")
            with patch(
                "windows_solver.response_batches._validate_record_semantics",
                return_value=True,
            ):
                run_campaign_selection(
                    plan, selection, first, root / "first.json",
                    resume=False, solved_leaf_store=store,
                )
                run_campaign_selection(
                    plan, selection, changed, root / "changed.json",
                    resume=False, solved_leaf_store=store,
                )
                run_campaign_selection(
                    plan, selection, repeated, root / "repeated.json",
                    resume=False, solved_leaf_store=store,
                )
            stored_count = store.stored_count

        self.assertEqual(first.calls, [(selection.leaf_ids[0], 64)])
        self.assertEqual(changed.calls, [(selection.leaf_ids[0], 64)])
        self.assertEqual(repeated.calls, [])
        self.assertEqual(stored_count, 2)

    def test_promoted_record_budget_must_match_active_execution_contract(self):
        plan = build_campaign_plan(
            policy=NumericalPolicy(),
            backend_identity=VettedNativeDeterminantKernel.identity,
            precision_capabilities=PrecisionCapabilities((64, 80, 120)),
        )
        leaf = next(
            item for item in plan.leaves
            if item.role == "primary"
            and item.mechanism_id == "horizon-admittance"
        )
        expected_budget = synthetic_ode_error_budget(80).to_mapping()
        contract = {
            "schema": "windows-solver.m02-scientific-execution-contract/1",
            "ode_error_budgets_by_nominal_decimal_digits": {
                "80": expected_budget,
                "120": synthetic_ode_error_budget(120).to_mapping(),
            },
        }

        def record_for(runtime):
            component = {"scientific_runtime": runtime}
            outcome = StageOutcome(
                digits=80,
                numerical_state="NOT_CONVERGED",
                component_result=component,
                local_disk_radius_abs=1.0,
                signed_error_channels=synthetic_stage_signed_error_channels(
                    component, 1.0
                ),
            )
            return CampaignLeafRecord(
                leaf_id=leaf.leaf_id,
                role=leaf.role,
                state="IN_PROGRESS",
                stages=(CampaignStageRecord(
                    outcome,
                    {
                        "precision_factory_identity": (
                            plan.precision_factory_identity.to_mapping()
                        ),
                        "available_precision_digits": [64, 80, 120],
                    },
                ),),
            )

        runtime = {
            "precision_digits": 80,
            "ode_error_budget": expected_budget,
            "ode_error_budget_sha256": hashlib.sha256(
                canonical_json_bytes(expected_budget)
            ).hexdigest(),
        }
        _validate_record_scientific_execution_contract(
            leaf, record_for(runtime), contract
        )

        changed_budget = synthetic_ode_error_budget(120).to_mapping()
        changed_runtime = {
            **runtime,
            "ode_error_budget": changed_budget,
            "ode_error_budget_sha256": hashlib.sha256(
                canonical_json_bytes(changed_budget)
            ).hexdigest(),
        }
        with self.assertRaisesRegex(
            ValueError, "active scientific execution contract"
        ):
            _validate_record_scientific_execution_contract(
                leaf, record_for(changed_runtime), contract
            )
        with self.assertRaisesRegex(ValueError, "lacks its ODE budget"):
            _validate_record_scientific_execution_contract(
                leaf,
                record_for({"precision_digits": 80}),
                contract,
            )

    def test_promoted_record_empirical_receipt_must_match_active_contract(self):
        """Catches accepting a promoted stage after its receipt SHA changes."""

        plan = build_campaign_plan(
            policy=NumericalPolicy(),
            backend_identity=VettedNativeDeterminantKernel.identity,
            precision_capabilities=PrecisionCapabilities((64, 80, 120)),
        )
        leaf = next(
            item for item in plan.leaves
            if item.role == "primary"
            and item.mechanism_id == "horizon-admittance"
        )
        native = NativeCampaignStageBackend(
            object(),
            plan.precision_capabilities,
            object(),
            julia_adapter=object(),
        )
        receipt = native.calibration_receipt
        assert receipt is not None
        profile = receipt.budget_for("horizon-scattering/v1", 80)
        runtime = JuliaPrecisionRootBackend(
            leaf.job.backend_identity,
            SimpleNamespace(runtime_provenance={}),
            80,
            empirical_control_profile=profile,
            calibration_receipt=receipt,
        ).scientific_runtime_for(leaf.job)
        component = {"scientific_runtime": runtime}
        outcome = StageOutcome(
            digits=80,
            numerical_state="NOT_CONVERGED",
            component_result=component,
            local_disk_radius_abs=1.0,
            signed_error_channels=synthetic_stage_signed_error_channels(
                component, 1.0
            ),
        )
        record = CampaignLeafRecord(
            leaf_id=leaf.leaf_id,
            role=leaf.role,
            state="IN_PROGRESS",
            stages=(CampaignStageRecord(
                outcome,
                {
                    "precision_factory_identity": (
                        plan.precision_factory_identity.to_mapping()
                    ),
                    "available_precision_digits": [64, 80, 120],
                },
            ),),
        )
        contract = native.scientific_execution_contract_for(leaf)

        _validate_record_scientific_execution_contract(leaf, record, contract)

        changed = deepcopy(runtime)
        changed["promoted_control_calibration"]["receipt_sha256"] = "0" * 64
        changed_component = {"scientific_runtime": changed}
        changed_record = replace(
            record,
            stages=(CampaignStageRecord(
                replace(
                    outcome,
                    component_result=changed_component,
                    signed_error_channels=synthetic_stage_signed_error_channels(
                        changed_component, 1.0
                    ),
                ),
                record.stages[0].runner_provenance,
            ),),
        )
        with self.assertRaisesRegex(
            ValueError, "active scientific execution contract"
        ):
            _validate_record_scientific_execution_contract(
                leaf, changed_record, contract
            )

    def test_worker_source_change_keeps_promoted_horizon_record_compatible(self):
        """A plumbing-only worker change must not retire accepted horizon work."""

        capabilities = PrecisionCapabilities((64, 80))
        plan = build_campaign_plan(
            policy=NumericalPolicy(),
            backend_identity=VettedNativeDeterminantKernel.identity,
            precision_capabilities=capabilities,
        )
        leaf = next(
            item for item in plan.leaves
            if item.role == "primary"
            and item.mechanism_id == "horizon-admittance"
        )
        selection = build_campaign_selection(
            plan, role="primary", leaf_ids=(leaf.leaf_id,)
        )
        native = NativeCampaignStageBackend(
            object(),
            capabilities,
            object(),
            julia_adapter=object(),
        )
        receipt = native.calibration_receipt
        assert receipt is not None
        profile = receipt.budget_for("horizon-scattering/v1", 80)
        old_runtime = JuliaPrecisionRootBackend(
            leaf.job.backend_identity,
            SimpleNamespace(runtime_provenance={"worker_sha256": "a" * 64}),
            80,
            empirical_control_profile=profile,
            calibration_receipt=receipt,
        ).scientific_runtime_for(leaf.job)
        new_runtime = JuliaPrecisionRootBackend(
            leaf.job.backend_identity,
            SimpleNamespace(runtime_provenance={"worker_sha256": "b" * 64}),
            80,
            empirical_control_profile=profile,
            calibration_receipt=receipt,
        ).scientific_runtime_for(leaf.job)
        self.assertNotEqual(old_runtime["worker_sha256"], new_runtime["worker_sha256"])

        class Backend:
            identity = plan.backend_identity
            precision_capabilities = capabilities

            def __init__(self, runtime):
                self.runtime = runtime
                self.calls = []

            @staticmethod
            def scientific_execution_contract_for(selected):
                del selected
                return native.scientific_execution_contract_for(leaf)

            def execute_stage(self, selected, digits):
                self.calls.append(digits)
                return _production_outcome(
                    selected,
                    digits=digits,
                    status=ComponentStatus.NOT_CONVERGED,
                )

            def execute_promoted_stage(self, selected, digits, previous):
                del previous
                self.calls.append(digits)
                component = {
                    "leaf_id": selected.leaf_id,
                    "role": selected.role,
                    "mechanism_id": selected.mechanism_id,
                    "job_id": selected.job.job_id,
                    "root_identity_sha256": (
                        selected.job.root.identity_sha256
                    ),
                    "policy_sha256": selected.job.policy.identity_sha256,
                    "backend_identity_sha256": (
                        selected.job.backend_identity.identity_sha256
                    ),
                    "digits": digits,
                    "scientific_runtime": self.runtime,
                }
                return StageOutcome(
                    digits=digits,
                    numerical_state="CONVERGED",
                    component_result=component,
                    signed_error_channels=synthetic_stage_signed_error_channels(
                        component, 1.0
                    ),
                    local_disk_radius_abs=1.0,
                    self_refinement_enclosed=True,
                    discrepancy_from_previous_abs=0.0,
                    discrepancy_enclosed=True,
                )

        with tempfile.TemporaryDirectory() as temporary:
            checkpoint = Path(temporary) / "checkpoint.json"
            first = Backend(old_runtime)
            resumed = Backend(new_runtime)
            with patch(
                "windows_solver.response_batches._validate_component_result",
                return_value=True,
            ):
                run_campaign_selection(
                    plan, selection, first, checkpoint, resume=False
                )
                summary = run_campaign_selection(
                    plan, selection, resumed, checkpoint, resume=True
                )

            checkpoint_mapping = json.loads(checkpoint.read_text(encoding="utf-8"))

        self.assertEqual(first.calls, [64, 80])
        self.assertEqual(resumed.calls, [])
        self.assertEqual(summary.executed_stage_count, 0)
        self.assertEqual(summary.reused_stage_count, 2)
        self.assertEqual(
            tuple(stage.outcome.digits for stage in summary.records[0].stages),
            (64, 80),
        )
        self.assertEqual(
            checkpoint_mapping["records"][0]["stages"][1]
            ["component_result"]["scientific_runtime"]["worker_sha256"],
            "a" * 64,
        )

    def test_leaf42_type_repair_characterizes_full_checkpoint_resume(self):
        """The protocol failure has no receipt and cannot retire prior work."""

        capabilities = PrecisionCapabilities((64, 80, 120))
        plan = build_campaign_plan(
            policy=NumericalPolicy(),
            backend_identity=_FROZEN_MIGRATION_BACKEND_IDENTITY,
            precision_capabilities=capabilities,
        )
        all_selection = build_campaign_selection(plan, role="all")
        execution_ids = response_batches._campaign_execution_leaf_ids(
            plan, all_selection
        )
        leaf_42_id = (
            "b-prime-leaf-5a27a5fdc15f95de33d6773b16f89a9f594fe5ffd018f9ee94bbab91949fd653"
        )
        leaf_13_horizon_id = (
            "b-prime-leaf-28b8e2f139fae4ebbb839320057a127429f7a01a3cc2cac60b526815ad0e7252"
        )
        self.assertEqual(execution_ids[40], leaf_42_id)
        leaf_43_id = execution_ids[41]
        # These are the exact nine promoted-horizon leaves in the preserved
        # operator receipt inventory. The stage payloads below remain a safe
        # orchestration model; they do not claim to recreate archived numerics.
        promoted_horizon_ids = frozenset({
            leaf_13_horizon_id,
            "b-prime-leaf-9c8e2306e6b3deef2b45b7b7c4cfc7243e65d5c8a52d533c158b3d4d34b2bfde",
            "b-prime-leaf-5ba0cad4211e48b2bf283536e5e9478bf91fe70667a246db98785d7826b8da8d",
            "b-prime-leaf-c398b8a238c89e91bd0672fd032a211c0e39f43adb993102892017ae762bac05",
            "b-prime-leaf-e5ca7b9ca2a529549bc3aa5af4aead758fddc114757d1e5cc96ff139e924f1e0",
            "b-prime-leaf-10f14c3df33e2bac0e0c53b94018422df0f0e9b90a3af1f043ec960bcc584b23",
            "b-prime-leaf-53afb256f4d9a517f36c216ae6d12ad9d599950e34f1179fe0b7d05e69b70973",
            "b-prime-leaf-7fec2f65a174db68a3462684482dcd1f703c472d187b113a3f96e07f67f284e6",
            "b-prime-leaf-a141a222ab4ee5c308d9105805c8d04e7b5df552dee0d8bfdc56d3f388e9c7de",
        })
        self.assertEqual(len(promoted_horizon_ids), 9)
        self.assertTrue(all(
            next(
                leaf for leaf in plan.leaves if leaf.leaf_id == leaf_id
            ).mechanism_id
            == "horizon-admittance"
            for leaf_id in promoted_horizon_ids
        ))
        selection = all_selection
        leaf_by_id = {leaf.leaf_id: leaf for leaf in plan.leaves}
        leaf_42 = leaf_by_id[leaf_42_id]
        receipt = NativeCampaignStageBackend(
            object(), capabilities, object(), julia_adapter=object()
        ).calibration_receipt
        assert receipt is not None
        request_backend = JuliaPrecisionRootBackend(
            leaf_42.job.backend_identity,
            SimpleNamespace(runtime_provenance={}),
            80,
            empirical_control_profile=receipt.budget_for(
                "exterior-wronskian/v1", 80
            ),
            calibration_receipt=receipt,
            diagnostic_model_identity=(
                EXTERIOR_DETERMINANT_ABSOLUTE_ERROR_CERTIFICATE
            ),
        )
        corrected_request = request_backend._request(leaf_42.job, 0.0j)
        self.assertIs(
            type(
                corrected_request["policy"][
                    "determinant_error_safety_factor"
                ]
            ),
            int,
        )
        corrected_sha256 = hashlib.sha256(
            canonical_json_bytes(corrected_request)
        ).hexdigest()
        obsolete_request = deepcopy(corrected_request)
        obsolete_request["policy"]["determinant_error_safety_factor"] = "64"
        obsolete_sha256 = hashlib.sha256(
            canonical_json_bytes(obsolete_request)
        ).hexdigest()
        self.assertEqual(
            obsolete_sha256,
            "c31516bf16659f28de040da1ae9e8c1953b495c0a09415f327bf731e27a6cff5",
        )
        self.assertEqual(
            corrected_sha256,
            "d9f2376d3476298bb891426e2325f9b0c314d982161fdc8f70ce8139498a7905",
        )
        self.assertNotEqual(obsolete_sha256, corrected_sha256)

        class StopAfterLeaf42(RuntimeError):
            pass

        class Backend:
            identity = plan.backend_identity
            precision_capabilities = capabilities

            def __init__(self, *, fail_leaf_42, stop_leaf_id=None):
                self.fail_leaf_42 = fail_leaf_42
                self.stop_leaf_id = stop_leaf_id
                self.calls = []
                self.promoted_request_sha256s = []

            def execute_stage(self, leaf, digits):
                self.calls.append((leaf.leaf_id, digits))
                if leaf.leaf_id == self.stop_leaf_id:
                    raise StopAfterLeaf42(
                        "characterization stopped after repaired Leaf 42"
                    )
                status = (
                    ComponentStatus.NOT_CONVERGED
                    if leaf.leaf_id in promoted_horizon_ids | {leaf_42_id}
                    else ComponentStatus.CONVERGED
                )
                return _production_outcome(leaf, digits=digits, status=status)

            def execute_promoted_stage(self, leaf, digits, previous):
                del previous
                self.calls.append((leaf.leaf_id, digits))
                if leaf.leaf_id == leaf_42_id and self.fail_leaf_42:
                    raise JuliaResponseBackendError(
                        "regularised GSN mechanism policy "
                        "determinant_error_safety_factor is invalid"
                    )
                if leaf.leaf_id == leaf_42_id:
                    emitted_request = request_backend._request(leaf.job, 0.0j)
                    self.promoted_request_sha256s.append(hashlib.sha256(
                        canonical_json_bytes(emitted_request)
                    ).hexdigest())
                outcome = _production_outcome(
                    leaf, digits=digits, status=ComponentStatus.CONVERGED
                )
                outcome = replace(
                    outcome,
                    self_refinement_enclosed=True,
                    discrepancy_from_previous_abs=0.0,
                    discrepancy_enclosed=True,
                )
                return outcome

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            checkpoint = root / "leaf42-checkpoint.json"
            readout_store = RootReadoutStore(root / "root-readouts")
            runtime_identity = runtime_identity_sha256({
                "worker_sha256": "f" * 64,
            })
            obsolete_cache_path = readout_store.publish(
                request_sha256=obsolete_sha256,
                runtime_identity=runtime_identity,
                response={
                    "status": "ok",
                    "request_sha256": obsolete_sha256,
                    "fixture": "obsolete promoted-exterior wire identity",
                },
            )
            self.assertIs(
                readout_store.lookup(
                    request_sha256=corrected_sha256,
                    runtime_identity=runtime_identity,
                ).status,
                RootReadoutLookupStatus.MISSING,
            )
            initial = Backend(fail_leaf_42=True)
            reporter = CampaignProgressReporter(
                "normal", checkpoint, io.StringIO()
            )
            with patch(
                "windows_solver.response_batches._validate_component_result",
                return_value=True,
            ):
                with activate_progress(reporter):
                    with self.assertRaisesRegex(
                        JuliaResponseBackendError,
                        "determinant_error_safety_factor is invalid",
                    ):
                        run_campaign_selection(
                            plan, selection, initial, checkpoint, resume=False
                        )

            partial_bytes = checkpoint.read_bytes()
            partial = json.loads(partial_bytes)
            status = json.loads(
                Path(f"{checkpoint}.status.json").read_text(encoding="utf-8")
            )
            self.assertEqual(partial["state"], "PARTIAL")
            self.assertEqual(len(partial["records"]), 41)
            self.assertEqual(
                sum(record["computed"] for record in partial["records"]), 40
            )
            current = next(
                record
                for record in partial["records"]
                if record["leaf_id"] == leaf_42_id
            )
            self.assertEqual(current["leaf_id"], leaf_42_id)
            self.assertFalse(current["computed"])
            self.assertEqual([stage["digits"] for stage in current["stages"]], [64])
            self.assertEqual(partial["attempts"], [])
            self.assertNotIn(obsolete_sha256, partial_bytes.decode("utf-8"))
            self.assertEqual(
                status["persistence"]["current_leaf"],
                {
                    "leaf_id": leaf_42_id,
                    "terminal_computed": False,
                    "checkpoint_saved": True,
                    "receipt_published": False,
                    "publication_failed": False,
                },
            )
            completed_before = {
                record["leaf_id"]: deepcopy(record)
                for record in partial["records"]
                if record["computed"]
            }
            self.assertEqual(len(completed_before), 40)
            promoted_horizon_before = {
                leaf_id: completed_before[leaf_id]
                for leaf_id in promoted_horizon_ids
            }
            self.assertTrue(all(
                [stage["digits"] for stage in record["stages"]] == [64, 80]
                for record in promoted_horizon_before.values()
            ))

            resumed_backend = Backend(
                fail_leaf_42=False,
                stop_leaf_id=leaf_43_id,
            )
            with patch(
                "windows_solver.response_batches._validate_component_result",
                return_value=True,
            ):
                with self.assertRaisesRegex(
                    StopAfterLeaf42,
                    "stopped after repaired Leaf 42",
                ):
                    run_campaign_selection(
                        plan,
                        selection,
                        resumed_backend,
                        checkpoint,
                        resume=True,
                    )
            completed = json.loads(checkpoint.read_bytes())

            completed_after = {
                record["leaf_id"]: record
                for record in completed["records"]
                if record["leaf_id"] in completed_before
            }
            self.assertEqual(completed_after, completed_before)
            self.assertTrue(obsolete_cache_path.is_file())
            self.assertEqual(readout_store.stored_count, 1)
            self.assertIs(
                readout_store.lookup(
                    request_sha256=obsolete_sha256,
                    runtime_identity=runtime_identity,
                ).status,
                RootReadoutLookupStatus.HIT,
            )
            self.assertIs(
                readout_store.lookup(
                    request_sha256=corrected_sha256,
                    runtime_identity=runtime_identity,
                ).status,
                RootReadoutLookupStatus.MISSING,
            )

        self.assertEqual(
            resumed_backend.calls,
            [(leaf_42_id, 80), (leaf_43_id, 64)],
        )
        self.assertEqual(
            resumed_backend.promoted_request_sha256s,
            [corrected_sha256],
        )
        self.assertEqual(completed["state"], "PARTIAL")
        self.assertEqual(
            sum(record["computed"] for record in completed["records"]),
            41,
        )
        self.assertEqual(completed["attempts"], [])
        corrected = next(
            record
            for record in completed["records"]
            if record["leaf_id"] == leaf_42_id
        )
        self.assertTrue(corrected["computed"])
        self.assertEqual(
            [stage["digits"] for stage in corrected["stages"]], [64, 80]
        )

    def test_promoted_invalidation_preserves_binary64_and_resumes_first_tier(self):
        """Catches receipt invalidation discarding authenticated binary64 work."""

        plan = build_campaign_plan(
            policy=NumericalPolicy(),
            backend_identity=VettedNativeDeterminantKernel.identity,
            precision_capabilities=PrecisionCapabilities((64, 80, 120)),
        )
        leaf = next(item for item in plan.leaves if item.role == "primary")

        def stage(digits):
            component = {
                "leaf_id": leaf.leaf_id,
                "digits": digits,
            }
            return CampaignStageRecord(
                StageOutcome(
                    digits=digits,
                    numerical_state="NOT_CONVERGED",
                    component_result=component,
                    local_disk_radius_abs=1.0,
                    signed_error_channels=synthetic_stage_signed_error_channels(
                        component, 1.0
                    ),
                ),
                {
                    "precision_factory_identity": (
                        plan.precision_factory_identity.to_mapping()
                    ),
                    "available_precision_digits": [64, 80, 120],
                },
            )

        binary = stage(64)
        promoted = stage(80)
        record = CampaignLeafRecord(
            leaf_id=leaf.leaf_id,
            role=leaf.role,
            state="UNRESOLVED",
            stages=(binary, promoted),
            trigger_ids=("binary64-trigger",),
            sentinel=True,
            sentinel_comparison={"status": "old-promoted-comparison"},
        )

        invalidated = response_batches._invalidate_promoted_record(record)

        self.assertEqual(invalidated.stages, (binary,))
        self.assertEqual(invalidated.state, "IN_PROGRESS")
        self.assertEqual(invalidated.trigger_ids, record.trigger_ids)
        self.assertTrue(invalidated.sentinel)
        self.assertIsNone(invalidated.missing_precision_digits)
        self.assertIsNone(invalidated.sentinel_comparison)

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
