"""PR68 regression tests for the schema-11 horizon lifecycle."""

from __future__ import annotations

import copy
from decimal import Decimal
import hashlib
from dataclasses import replace
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import windows_solver.campaign_runtime as campaign_runtime
import windows_solver.campaign_survey as campaign_survey
import windows_solver.response_batches as response_batches
from windows_solver.campaign_failures import CampaignSystemFailure
from windows_solver.campaign_policy import (
    PromotionQueueKind,
    SurveyDisposition,
    SurveyPass,
    add_numerical_record,
    append_promotion,
    empty_schema11_checkpoint,
    record_survey_disposition,
)
from windows_solver.campaign_recovery import RecoverySelection
from windows_solver.campaign_runtime import (
    _promoted_horizon_outcome,
    build_schema11_horizon_record,
    build_schema11_horizon_stage,
)
from windows_solver.campaign_survey import (
    Binary64PassOutcome,
    PromotedPassOutcome,
    _record_pass_outcome,
    run_promoted_survey,
)
from windows_solver.contracts import canonical_json_bytes
from windows_solver.native_response_kernel import VettedNativeDeterminantKernel
from windows_solver.response_batches import (
    B_PRIME_RELEASE_DOMAIN,
    NativeCampaignStageBackend,
    PrecisionCapabilities,
    StageOutcome,
    build_horizon_promotion_trigger_receipt,
    build_campaign_plan,
    build_campaign_selection,
    synthetic_stage_signed_error_channels,
)
from windows_solver.response_engine import DeterminantPartials, NumericalPolicy
from tests.test_native_campaign_backend import _result as native_component_result
from tests.test_promoted_horizon_component import (
    FakePromotedBackend,
    _promoted_baseline,
)
from windows_solver.response_engine import (
    ComponentResult,
    DecimalComplex,
    run_promoted_horizon_component,
)
from windows_solver.promoted_control_calibration import PromotedExecutionMode
from windows_solver.reviewed_determinant_error_issuance import (
    PromotedExecutionPreflight,
)
from windows_solver.root_evidence import AuthenticatedRootEvidence


def _sha256(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _plan():
    return build_campaign_plan(
        policy=NumericalPolicy(),
        backend_identity=VettedNativeDeterminantKernel.identity,
        precision_capabilities=PrecisionCapabilities((64, 80)),
    )


def _root_evidence(leaf):
    return AuthenticatedRootEvidence.from_authenticated_disk(
        leaf,
        fixed_root=leaf.job.root.omega,
        root_uncertainty_radius=1.0e-9,
        source_receipt_sha256="b" * 64,
        evidence_level="SCREENED",
    )


def _deep_horizon_stage(*, diagnostics: dict[str, object] | None):
    payload = {
        "evidence_kind": "synthetic-pr68-horizon-stage",
        "result": {"status": "CONVERGED"},
    }
    return StageOutcome(
        digits=64,
        numerical_state="CONVERGED",
        component_result=payload,
        local_disk_radius_abs=1.0e-6,
        signed_error_channels=synthetic_stage_signed_error_channels(
            payload, 1.0e-6
        ),
        deep_diagnostics=diagnostics,
    )


def _triggering_diagnostics() -> dict[str, object]:
    return {
        "condition_amplifier_abs": 1.0,
        "predicted_reliable_decimal_digits": 8.0,
        "step_richardson_disagreement_abs": 0.0,
        "repeat_polish_delta_abs": 0.0,
        "angular_refinement_delta_abs": 0.0,
        "independent_path_delta_abs": 0.0,
        "diagnostic_ceiling_abs": 1.0,
        "denominator_or_calibration_disk_contains_zero": False,
    }


def _binary64_horizon_outcome(plan, leaf) -> StageOutcome:
    class Kernel:
        identity = VettedNativeDeterminantKernel.identity

        def horizon_partials(self, **kwargs):
            job = kwargs["job"]
            omega_h = job.spin / (2.0 * (1.0 + (1.0 - job.spin * job.spin) ** 0.5))
            p_h = job.root.omega - job.mode.m * omega_h
            coordinate = -0.5 + 0.1j
            d_h = coordinate * (2.0j * p_h)
            return DeterminantPartials(
                frequency_derivative=1.0 + 0.25j,
                coordinate_derivative=coordinate,
                simple_root_valid=True,
                frequency_derivative_error_abs=1.0e-12,
                dD_dR=d_h,
                dD_dR_error_abs=1.0e-12,
                dR_ddeltaB=1.0 / (2.0j * p_h),
                dD_ddeltaB=coordinate,
                dD_domega=1.0 + 0.25j,
                dD_domega_error_abs=1.0e-12,
            )

        def evaluate_root(self, **_kwargs):
            raise AssertionError("binary64 horizon entered root/ladders")

    kernel = Kernel()
    backend = NativeCampaignStageBackend(
        SimpleNamespace(identity=kernel.identity, kernel=kernel),
        PrecisionCapabilities((64,)),
        SimpleNamespace(
            record_artifact_ids=(),
            path=Path("synthetic-gsn-cache"),
            sha256="a" * 64,
            parameter_pairs=(),
        ),
    )
    return backend.execute_horizon_stage(leaf, root_evidence=_root_evidence(leaf))


class HorizonRecordConstructionTests(unittest.TestCase):
    def test_authoritative_decision_derives_deep_trigger_and_sentinel(self) -> None:
        plan = _plan()
        leaf = next(
            item
            for item in plan.leaves
            if item.role == "deep"
            and item.mechanism_id == "horizon-admittance"
            and item.leaf_id
            in set(B_PRIME_RELEASE_DOMAIN.fixed_precision_sentinel_leaf_ids)
        )
        decision_builder = getattr(
            response_batches, "derive_horizon_promotion_decision", None
        )
        self.assertTrue(callable(decision_builder))

        stage = _deep_horizon_stage(diagnostics=_triggering_diagnostics())
        decision = decision_builder(leaf, stage)

        self.assertEqual(
            decision.trigger_ids,
            response_batches._deep_trigger_ids(stage),
        )
        self.assertTrue(decision.sentinel)
        self.assertTrue(decision.promotion_required)
        self.assertEqual(decision.reason_code, "DEEP_TRIGGER_AND_FIXED_SENTINEL")

    def test_deep_horizon_without_diagnostics_fails_closed(self) -> None:
        plan = _plan()
        leaf = next(
            item
            for item in plan.leaves
            if item.role == "deep" and item.mechanism_id == "horizon-admittance"
        )
        decision_builder = getattr(
            response_batches, "derive_horizon_promotion_decision", None
        )
        self.assertTrue(callable(decision_builder))

        with self.assertRaisesRegex(ValueError, "deep diagnostics"):
            decision_builder(leaf, _deep_horizon_stage(diagnostics=None))

    def test_schema11_horizon_builder_is_not_legacy_record(self) -> None:
        self.assertFalse(hasattr(campaign_runtime, "_produced_horizon_record"))
        self.assertTrue(
            callable(getattr(campaign_runtime, "build_schema11_horizon_record", None))
        )
        self.assertTrue(
            callable(getattr(response_batches, "validate_schema11_horizon_record", None))
        )

    def test_horizon_validator_rejects_foreign_policy_and_backend_lineage(self) -> None:
        plan = _plan()
        leaf = next(
            item
            for item in plan.leaves
            if item.role == "primary"
            and item.mechanism_id == "horizon-admittance"
        )
        outcome = _binary64_horizon_outcome(plan, leaf)
        stage, _stage_sha256 = build_schema11_horizon_stage(
            outcome,
            precision_tier="binary64",
            operation_identity="binary64-horizon-production/v3",
        )
        record = build_schema11_horizon_record(
            plan,
            leaf,
            stages=(stage,),
            retained_centre=stage["response_disk"]["centre"],
            state="PRODUCED",
        )

        for lineage_field in ("policy_sha256", "backend_identity_sha256"):
            tampered = copy.deepcopy(record)
            tampered_stage = tampered["stages"][0]
            tampered_stage["component_result"]["result"]["lineage"][
                lineage_field
            ] = "f" * 64
            stage_content = {
                key: value
                for key, value in tampered_stage.items()
                if key != "stage_sha256"
            }
            tampered_stage["stage_sha256"] = _sha256(stage_content)
            record_content = {
                key: value
                for key, value in tampered.items()
                if key != "record_sha256"
            }
            tampered["record_sha256"] = _sha256(record_content)

            with self.subTest(lineage_field=lineage_field):
                with self.assertRaisesRegex(ValueError, "lineage"):
                    response_batches.validate_schema11_horizon_record(
                        plan, leaf, tampered
                    )

    def test_horizon_validator_rejects_foreign_root_readout_identity(self) -> None:
        plan = _plan()
        leaf = next(
            item
            for item in plan.leaves
            if item.role == "primary"
            and item.mechanism_id == "horizon-admittance"
        )
        outcome = _binary64_horizon_outcome(plan, leaf)
        stage, _stage_sha256 = build_schema11_horizon_stage(
            outcome,
            precision_tier="binary64",
            operation_identity="binary64-horizon-production/v3",
        )
        record = build_schema11_horizon_record(
            plan,
            leaf,
            stages=(stage,),
            retained_centre=stage["response_disk"]["centre"],
            state="PRODUCED",
        )

        for readout_field in ("root_reference_id", "branch_id", "equation_id"):
            tampered = copy.deepcopy(record)
            tampered_stage = tampered["stages"][0]
            tampered_stage["component_result"]["result"]["baseline"][
                readout_field
            ] = f"foreign-{readout_field}"
            stage_content = {
                key: value
                for key, value in tampered_stage.items()
                if key != "stage_sha256"
            }
            tampered_stage["stage_sha256"] = _sha256(stage_content)
            record_content = {
                key: value
                for key, value in tampered.items()
                if key != "record_sha256"
            }
            tampered["record_sha256"] = _sha256(record_content)

            with self.subTest(readout_field=readout_field):
                with self.assertRaisesRegex(ValueError, "readout"):
                    response_batches.validate_schema11_horizon_record(
                        plan, leaf, tampered
                    )

    def test_horizon_validator_rejects_generic_component_labeled_bf80(self) -> None:
        plan = _plan()
        leaf = next(
            item
            for item in plan.leaves
            if item.role == "primary"
            and item.mechanism_id == "horizon-admittance"
        )
        component = native_component_result(leaf.job, 0.25 + 0.1j)
        payload = {
            "evidence_kind": "generic-native-component",
            "result": component.to_mapping(),
        }
        outcome = StageOutcome(
            digits=80,
            numerical_state="CONVERGED",
            component_result=payload,
            local_disk_radius_abs=1.0e-6,
            signed_error_channels=synthetic_stage_signed_error_channels(
                payload, 1.0e-6
            ),
        )
        stage, _stage_sha256 = build_schema11_horizon_stage(
            outcome,
            precision_tier="BF80",
            operation_identity="test-promoted-horizon/v1",
        )

        with self.assertRaisesRegex(ValueError, "precision tier"):
            build_schema11_horizon_record(
                plan,
                leaf,
                stages=(stage,),
                retained_centre=stage["response_disk"]["centre"],
                state="PRODUCED",
            )

    def test_horizon_validator_accepts_package_owned_typed_bf80_failure(self) -> None:
        plan = _plan()
        leaf = next(
            item
            for item in plan.leaves
            if item.role == "primary"
            and item.mechanism_id == "horizon-admittance"
        )
        branch_lost = replace(
            _promoted_baseline(leaf.job, omega=leaf.job.root.omega),
            branch_id="foreign-promoted-branch",
        )
        component = run_promoted_horizon_component(
            leaf.job,
            FakePromotedBackend(leaf.job, branch_lost),
            leaf.job.root.omega,
        )
        payload = {
            "evidence_kind": "package-owned-julia-promoted-horizon-survey",
            "result": component.to_mapping(),
            "scientific_runtime": {"runtime": "synthetic-bf80"},
        }
        outcome = StageOutcome(
            digits=80,
            numerical_state="BRANCH_LOSS",
            component_result=payload,
            local_disk_radius_abs=0.0,
            signed_error_channels=synthetic_stage_signed_error_channels(
                payload,
                0.0,
                precision_ladder_applicable=False,
            ),
        )
        stage, _stage_sha256 = build_schema11_horizon_stage(
            outcome,
            precision_tier="BF80",
            operation_identity="promoted-horizon-component/v2",
        )

        record = build_schema11_horizon_record(
            plan,
            leaf,
            stages=(stage,),
            retained_centre=None,
            state="UNRESOLVED",
        )

        self.assertEqual("UNRESOLVED", record["state"])
        self.assertIsNotNone(component.component_scientific_identity)
        malformed = component.to_mapping()
        malformed["finite_amplitude_ladder_required"] = True
        with self.assertRaisesRegex(ValueError, "typed failure"):
            ComponentResult.from_mapping(malformed)

    def test_typed_not_converged_requires_baseline_failure_evidence(self) -> None:
        plan = _plan()
        leaf = next(
            item
            for item in plan.leaves
            if item.role == "primary"
            and item.mechanism_id == "horizon-admittance"
        )
        failed_baseline = replace(
            _promoted_baseline(leaf.job, omega=leaf.job.root.omega),
            converged=False,
        )
        component = run_promoted_horizon_component(
            leaf.job,
            FakePromotedBackend(leaf.job, failed_baseline),
            leaf.job.root.omega,
        )
        self.assertEqual("NOT_CONVERGED", component.status.value)

        malformed = component.to_mapping()
        malformed["baseline"]["converged"] = True
        with self.assertRaisesRegex(ValueError, "typed failure"):
            ComponentResult.from_mapping(malformed)

    def test_unsuccessful_promotions_keep_source_records_out_of_cache(self) -> None:
        source = "a" * 64
        forged_completed = "b" * 64
        entries = [
            {
                "source_record_sha256": source,
                "disposition": disposition,
            }
            for disposition in (
                "PENDING",
                "UNRESOLVED",
                "DEFERRED",
                "REJECTED",
                "SUPERSEDED_BY_CACHE",
            )
        ]
        entries.append({
            "source_record_sha256": forged_completed,
            "source_stage_sha256": "c" * 64,
            "leaf_id": "forged-leaf",
            "queue_ordinal": len(entries),
            "disposition_receipt_sha256": "d" * 64,
            "disposition": "COMPLETED",
        })

        self.assertEqual(
            {source, forged_completed},
            campaign_runtime._promotion_bound_source_record_sha256({
                "promotion_queue": {"entries": entries},
                "survey_pass_ledger": {"promoted": {}},
                "evidence_ledger": {},
                "records": [],
            }),
        )

    def test_horizon_stage_radius_is_bound_to_component_evidence(self) -> None:
        plan = _plan()
        leaf = next(
            item
            for item in plan.leaves
            if item.role == "primary"
            and item.mechanism_id == "horizon-admittance"
        )
        outcome = _binary64_horizon_outcome(plan, leaf)
        stage, _stage_sha256 = build_schema11_horizon_stage(
            outcome,
            precision_tier="binary64",
            operation_identity="binary64-horizon-production/v3",
        )
        record = build_schema11_horizon_record(
            plan,
            leaf,
            stages=(stage,),
            retained_centre=stage["response_disk"]["centre"],
            state="PRODUCED",
        )

        tampered = copy.deepcopy(record)
        tampered_stage = tampered["stages"][0]
        self.assertGreater(tampered_stage["response_disk"]["radius"], 0.0)
        tampered_stage["response_disk"]["radius"] = 0.0
        tampered_stage["response_disk"]["exact_zero_radius"] = True
        tampered_stage["stage_sha256"] = _sha256({
            key: value
            for key, value in tampered_stage.items()
            if key != "stage_sha256"
        })
        tampered["record_sha256"] = _sha256({
            key: value
            for key, value in tampered.items()
            if key != "record_sha256"
        })

        with self.assertRaisesRegex(ValueError, "component evidence"):
            response_batches.validate_schema11_horizon_record(
                plan, leaf, tampered
            )

    def test_completed_comparison_remains_cache_bound_without_admission(self) -> None:
        plan = _plan()
        leaf = next(
            item for item in plan.leaves
            if item.role == "deep"
            and item.mechanism_id == "horizon-admittance"
            and item.leaf_id
            in set(B_PRIME_RELEASE_DOMAIN.fixed_precision_sentinel_leaf_ids)
        )
        promoted_result = run_promoted_horizon_component(
            leaf.job,
            FakePromotedBackend(
                leaf.job,
                _promoted_baseline(leaf.job, omega=leaf.job.root.omega),
            ),
            leaf.job.root.omega,
        )
        assert promoted_result.response is not None
        horizon_radius = 1.0 + (
            max(0.0, 1.0 - leaf.job.spin * leaf.job.spin) ** 0.5
        )
        horizon_frequency = leaf.job.root.omega - leaf.job.mode.m * (
            leaf.job.spin / (2.0 * horizon_radius)
        )

        class Kernel:
            identity = VettedNativeDeterminantKernel.identity

            def horizon_partials(self, **_kwargs):
                d_omega = 1.0 / (
                    2.0j * horizon_frequency * promoted_result.response
                )
                d_h = -1.0 + 0.0j
                return DeterminantPartials(
                    frequency_derivative=d_omega,
                    coordinate_derivative=d_h / (2.0j * horizon_frequency),
                    simple_root_valid=True,
                    frequency_derivative_error_abs=1.0e-12,
                    dD_dR=d_h,
                    dD_dR_error_abs=1.0e-12,
                    dR_ddeltaB=1.0 / (2.0j * horizon_frequency),
                    dD_ddeltaB=d_h / (2.0j * horizon_frequency),
                    dD_domega=d_omega,
                    dD_domega_error_abs=1.0e-12,
                )

        backend = NativeCampaignStageBackend(
            SimpleNamespace(identity=Kernel.identity, kernel=Kernel()),
            PrecisionCapabilities((64,)),
            SimpleNamespace(
                record_artifact_ids=(),
                path=Path("synthetic-gsn-cache"),
                sha256="a" * 64,
                parameter_pairs=(),
            ),
        )
        binary_outcome = replace(
            backend.execute_horizon_stage(leaf, root_evidence=_root_evidence(leaf)),
            deep_diagnostics=_triggering_diagnostics(),
        )
        source_stage, source_stage_sha256 = build_schema11_horizon_stage(
            binary_outcome,
            precision_tier="binary64",
            operation_identity="binary64-horizon-production/v3",
        )
        source_record = build_schema11_horizon_record(
            plan,
            leaf,
            stages=(source_stage,),
            retained_centre=source_stage["response_disk"]["centre"],
            state="PRODUCED",
        )
        source_record_sha256 = source_record["record_sha256"]
        trigger = build_horizon_promotion_trigger_receipt(
            plan, leaf, binary_outcome, source_stage
        )
        scientific_runtime = {"runtime": "test-bf80"}
        bf80_payload = {
            "evidence_kind": "package-owned-julia-promoted-horizon-survey",
            "result": promoted_result.to_mapping(),
            "scientific_runtime": scientific_runtime,
        }
        bf80_outcome = StageOutcome(
            digits=80,
            numerical_state=promoted_result.status.value,
            component_result=bf80_payload,
            local_disk_radius_abs=promoted_result.error_channels["resolution"],
            signed_error_channels=synthetic_stage_signed_error_channels(
                bf80_payload,
                promoted_result.error_channels["resolution"],
                precision_ladder_applicable=False,
            ),
        )
        bf80_stage, _bf80_stage_sha256 = build_schema11_horizon_stage(
            bf80_outcome,
            precision_tier="BF80",
            operation_identity="test-bf80-operation/v1",
        )
        source_disk = source_stage["response_disk"]
        bf80_disk = bf80_stage["response_disk"]
        source_centre = source_disk["centre"]
        bf80_centre = bf80_disk["centre"]
        source_radius = source_disk["radius"]
        bf80_radius = bf80_disk["radius"]
        discrepancy = abs(
            complex(source_centre["real"], source_centre["imaginary"])
            - complex(bf80_centre["real"], bf80_centre["imaginary"])
        )
        threshold = source_radius + bf80_radius
        self.assertLessEqual(discrepancy, threshold)
        comparison_content = {
            "schema": response_batches.HORIZON_PROMOTED_COMPARISON_RECEIPT_SCHEMA,
            "leaf_id": leaf.leaf_id,
            "source_record_sha256": source_record_sha256,
            "source_stage_sha256": source_stage_sha256,
            "source_centre": source_centre,
            "source_disk_radius": source_radius,
            "promotion_trigger_receipt_sha256": trigger["receipt_sha256"],
            "bf80_operation_identity": "test-bf80-operation/v1",
            "bf80_result_sha256": _sha256(promoted_result.to_mapping()),
            "bf80_stage": bf80_stage,
            "bf80_centre": bf80_centre,
            "bf80_disk_radius": bf80_radius,
            "centre_discrepancy": discrepancy,
            "reviewed_comparison_threshold": threshold,
            "agrees": True,
            "outcome_code": "AGREES",
            "runtime_identity": scientific_runtime,
            "backend_identity": leaf.job.backend_identity.identity_sha256,
        }
        comparison = {
            **comparison_content,
            "receipt_sha256": _sha256(comparison_content),
        }
        promoted = {
            "disposition": "COMPLETED",
            "operation_identity": "promoted-horizon-comparison/v2",
            "reason_code": "PROMOTED_HORIZON_COMPARISON_AGREES",
            "precision_tiers": ["BF80"],
            "source_record_sha256": source_record_sha256,
            "result_record_sha256": source_record_sha256,
        }
        queue_receipt = {
            "schema": "windows-solver.promoted-queue-disposition/1",
            "leaf_id": leaf.leaf_id,
            "queue_ordinal": 0,
            "disposition": "COMPLETED",
            "reason_code": promoted["reason_code"],
            "precision_tiers": promoted["precision_tiers"],
            "result_record_sha256": source_record_sha256,
            "source_record_sha256": source_record_sha256,
        }
        checkpoint = {
            "promotion_queue": {"entries": [{
                "leaf_id": leaf.leaf_id,
                "queue_ordinal": 0,
                "source_record_sha256": source_record_sha256,
                "source_stage_sha256": source_stage_sha256,
                "disposition": "COMPLETED",
                "disposition_receipt_sha256": _sha256(queue_receipt),
            }]},
            "survey_pass_ledger": {"promoted": {leaf.leaf_id: promoted}},
            "evidence_ledger": {leaf.leaf_id: {
                "central_record_sha256": source_record_sha256,
                "central_stage_sha256": source_stage_sha256,
                "receipts": [trigger, comparison],
            }},
            "records": [source_record],
        }

        self.assertEqual(
            {source_record_sha256},
            campaign_runtime._promotion_bound_source_record_sha256(
                checkpoint, plan
            ),
        )
        tampered = copy.deepcopy(checkpoint)
        tampered_comparison = tampered["evidence_ledger"][leaf.leaf_id][
            "receipts"
        ][1]
        tampered_comparison["bf80_result_sha256"] = "f" * 64
        tampered_comparison["receipt_sha256"] = _sha256({
            key: value
            for key, value in tampered_comparison.items()
            if key != "receipt_sha256"
        })
        self.assertEqual(
            {source_record_sha256},
            campaign_runtime._promotion_bound_source_record_sha256(
                tampered, plan
            ),
        )
        substituted = copy.deepcopy(checkpoint)
        substituted_comparison = substituted["evidence_ledger"][leaf.leaf_id][
            "receipts"
        ][1]
        substituted_comparison["bf80_stage"] = source_stage
        substituted_comparison["bf80_operation_identity"] = source_stage[
            "operation_identity"
        ]
        substituted_comparison["bf80_result_sha256"] = _sha256(
            source_stage["component_result"]["result"]
        )
        substituted_comparison["bf80_centre"] = source_centre
        substituted_comparison["bf80_disk_radius"] = source_radius
        substituted_comparison["centre_discrepancy"] = 0.0
        substituted_comparison["reviewed_comparison_threshold"] = (
            2.0 * source_radius
        )
        substituted_comparison["runtime_identity"] = source_stage[
            "component_result"
        ]["scientific_runtime"]
        substituted_comparison["receipt_sha256"] = _sha256({
            key: value
            for key, value in substituted_comparison.items()
            if key != "receipt_sha256"
        })
        self.assertEqual(
            {source_record_sha256},
            campaign_runtime._promotion_bound_source_record_sha256(
                substituted, plan
            ),
        )

    def test_trigger_receipt_rejects_stage_outcome_payload_mismatch(self) -> None:
        plan = _plan()
        leaf = next(
            item
            for item in plan.leaves
            if item.role == "primary"
            and item.mechanism_id == "horizon-admittance"
        )
        component = native_component_result(leaf.job, 0.25 + 0.1j)
        payload = {
            "evidence_kind": "synthetic-pr68-horizon-stage",
            "result": component.to_mapping(),
        }
        outcome = StageOutcome(
            digits=64,
            numerical_state="CONVERGED",
            component_result=payload,
            local_disk_radius_abs=1.0e-6,
            signed_error_channels=synthetic_stage_signed_error_channels(
                payload, 1.0e-6
            ),
        )
        stage, _stage_sha256 = build_schema11_horizon_stage(
            outcome,
            precision_tier="binary64",
            operation_identity="binary64-horizon-production/v3",
        )
        mismatched_payload = {
            **payload,
            "evidence_kind": "tampered-after-stage-authentication",
        }
        mismatched_outcome = replace(
            outcome,
            component_result=mismatched_payload,
            signed_error_channels=synthetic_stage_signed_error_channels(
                mismatched_payload, 1.0e-6
            ),
        )

        with self.assertRaisesRegex(ValueError, "stage payload"):
            build_horizon_promotion_trigger_receipt(
                plan,
                leaf,
                mismatched_outcome,
                stage,
            )

    def test_binary64_horizon_stage_is_fixed_root_analytic_and_ladder_free(self) -> None:
        plan = _plan()
        leaf = next(
            item
            for item in plan.leaves
            if item.role == "primary"
            and item.mechanism_id == "horizon-admittance"
        )

        class Kernel:
            identity = VettedNativeDeterminantKernel.identity

            def __init__(self):
                self.partial_calls = 0
                self.root_calls = 0

            def horizon_partials(self, **_kwargs):
                self.partial_calls += 1
                return DeterminantPartials(
                    frequency_derivative=1.0 + 0.25j,
                    coordinate_derivative=-0.5 + 0.1j,
                    simple_root_valid=True,
                    frequency_derivative_error_abs=1.0e-12,
                )

            def evaluate_root(self, **_kwargs):
                self.root_calls += 1
                raise AssertionError("binary64 horizon entered root/ladders")

        kernel = Kernel()
        adapter = SimpleNamespace(identity=kernel.identity, kernel=kernel)
        generated = SimpleNamespace(
            record_artifact_ids=(),
            path=Path("synthetic-gsn-cache"),
            sha256="a" * 64,
            parameter_pairs=(),
        )
        backend = NativeCampaignStageBackend(
            adapter,
            PrecisionCapabilities((64,)),
            generated,
        )

        outcome = backend.execute_horizon_stage(leaf, root_evidence=_root_evidence(leaf))
        raw = outcome.component_result["result"]
        self.assertEqual(64, outcome.digits)
        self.assertEqual(1, kernel.partial_calls)
        self.assertEqual(0, kernel.root_calls)
        self.assertEqual([], raw["levels"])
        self.assertFalse(raw["finite_amplitude_ladder_required"])
        self.assertFalse(raw["finite_amplitude_ladder_executed"])
        self.assertEqual(0, raw["finite_amplitude_readout_count"])
        self.assertEqual(0, raw["analytic_horizon_evidence"]["worker_launch_count"])
        self.assertEqual([], raw["analytic_horizon_evidence"]["levels"])

    def test_binary64_horizon_without_stencil_error_bound_is_unbounded(self) -> None:
        plan = _plan()
        leaf = next(
            item for item in plan.leaves
            if item.role == "primary"
            and item.mechanism_id == "horizon-admittance"
        )

        class Kernel:
            identity = VettedNativeDeterminantKernel.identity

            def horizon_partials(self, **_kwargs):
                return DeterminantPartials(
                    frequency_derivative=1.0 + 0.25j,
                    coordinate_derivative=-0.5 + 0.1j,
                    simple_root_valid=True,
                )

        backend = NativeCampaignStageBackend(
            SimpleNamespace(identity=Kernel.identity, kernel=Kernel()),
            PrecisionCapabilities((64,)),
            SimpleNamespace(
                record_artifact_ids=(),
                path=Path("synthetic-gsn-cache"),
                sha256="a" * 64,
                parameter_pairs=(),
            ),
        )
        outcome = backend.execute_horizon_stage(leaf, root_evidence=_root_evidence(leaf))

        self.assertEqual("DERIVATIVE_UNRESOLVED", outcome.numerical_state)
        self.assertIsNone(outcome.component_result["result"]["response"])

    def test_binary64_outcome_commits_record_and_promotion_queue(self) -> None:
        record_content = {
            "schema": "windows-solver.schema11-numerical-record/1",
            "leaf_id": "leaf-1",
            "role": "deep",
            "state": "PRODUCED",
            "scientific_computation_identity": "b" * 64,
            "retained_centre": {"real": 1.0, "imaginary": -0.25},
            "stages": [{"stage_sha256": "a" * 64}],
        }
        record = {**record_content, "record_sha256": _sha256(record_content)}
        selection = RecoverySelection(
            campaign_id="campaign-1",
            selection_id="selection-1",
            ordered_leaf_ids=("leaf-1",),
            roles={"leaf-1": "deep"},
            scientific_identities={"leaf-1": "b" * 64},
        )
        outcome = Binary64PassOutcome(
            disposition=SurveyDisposition.PROMOTION_PENDING_RESPONSE,
            operation_identity="binary64-horizon-production/v2",
            reason_code="DEEP_DIAGNOSTIC_PROMOTION",
            record=record,
            stage_sha256="a" * 64,
            queue_kind=PromotionQueueKind.RESPONSE,
        )

        checkpoint = _record_pass_outcome(
            empty_schema11_checkpoint("campaign-1", "selection-1"),
            selection=selection,
            leaf_id="leaf-1",
            outcome=outcome,
            root_seal_sha256=None,
        )

        self.assertEqual([record], checkpoint["records"])
        queue = checkpoint["promotion_queue"]["entries"]
        self.assertEqual(1, len(queue))
        self.assertEqual(record["record_sha256"], queue[0]["source_record_sha256"])
        self.assertEqual("a" * 64, queue[0]["source_stage_sha256"])

    def test_promoted_horizon_uses_source_record_comparison_callback(self) -> None:
        plan = _plan()
        leaf = next(
            item
            for item in plan.leaves
            if item.role == "primary"
            and item.mechanism_id == "horizon-admittance"
        )
        selected = build_campaign_selection(
            plan, role=leaf.role, leaf_ids=(leaf.leaf_id,)
        )
        selection = RecoverySelection(
            campaign_id=plan.campaign_id,
            selection_id=selected.selection_id,
            ordered_leaf_ids=(leaf.leaf_id,),
            roles={leaf.leaf_id: leaf.role},
            scientific_identities={
                leaf.leaf_id: response_batches.scientific_computation_identity_sha256(
                    plan, leaf
                )
            },
        )
        stage_outcome = _binary64_horizon_outcome(plan, leaf)
        stage, stage_sha256 = build_schema11_horizon_stage(
            stage_outcome,
            precision_tier="binary64",
            operation_identity="binary64-horizon-production/v3",
        )
        response_disk = stage["response_disk"]
        assert isinstance(response_disk, dict)
        record = build_schema11_horizon_record(
            plan,
            leaf,
            stages=(stage,),
            retained_centre=response_disk["centre"],
            state="PRODUCED",
        )
        checkpoint = add_numerical_record(
            empty_schema11_checkpoint(plan.campaign_id, selected.selection_id),
            record,
        )
        checkpoint = append_promotion(
            checkpoint,
            leaf_id=leaf.leaf_id,
            queue_kind=PromotionQueueKind.RESPONSE,
            reason_code="FIXED_PRECISION_SENTINEL_PROMOTION",
            minimum_requested_tier="BF80",
            scientific_computation_identity=selection.scientific_identities[
                leaf.leaf_id
            ],
            source_record_sha256=record["record_sha256"],
            source_stage_sha256=stage_sha256,
        )
        observed: dict[str, object] = {}

        def compare(source_leaf, entry, source_record, receipts):
            observed.update({
                "leaf_id": source_leaf.leaf_id,
                "entry": entry,
                "source_record": source_record,
                "receipts": receipts,
            })
            return PromotedPassOutcome(
                disposition=SurveyDisposition.COMPLETED,
                reason_code="PROMOTED_HORIZON_COMPARISON_AGREES",
                precision_tiers=("BF80",),
                operation_identity="promoted-horizon-comparison/v2",
                source_record_sha256=record["record_sha256"],
                source_stage_sha256=stage_sha256,
                root_read_count=1,
                root_read_limit=1,
            )

        with tempfile.TemporaryDirectory() as temporary:
            result = run_promoted_survey(
                plan,
                selection,
                checkpoint,
                checkpoint_path=Path(temporary) / "checkpoint.json",
                root_seal_lookup=lambda _leaf, _entry: None,
                provisional_stage_lookup=lambda _leaf, entry: entry[
                    "provisional_stage"
                ],
                root_seal_publish=lambda *_args: self.fail(
                    "horizon promotion must not publish a root"
                ),
                backend_factory=lambda _leaf, _digits: None,
                primary_root_runner=lambda *_args: self.fail(
                    "unexpected promoted root"
                ),
                horizon_runner=lambda _leaf: self.fail(
                    "legacy promoted horizon runner was used"
                ),
                promoted_horizon_runner=compare,
            )

        self.assertEqual(leaf.leaf_id, observed["leaf_id"])
        self.assertEqual(result.checkpoint["records"][0], observed["source_record"])
        self.assertEqual(
            "COMPLETED",
            result.checkpoint["promotion_queue"]["entries"][0]["disposition"],
        )

    def test_promoted_survey_rejects_tampered_binary64_disposition_binding(self) -> None:
        plan = _plan()
        leaf = next(
            item
            for item in plan.leaves
            if item.role == "primary"
            and item.mechanism_id == "horizon-admittance"
        )
        selected = build_campaign_selection(
            plan, role=leaf.role, leaf_ids=(leaf.leaf_id,)
        )
        selection = RecoverySelection(
            campaign_id=plan.campaign_id,
            selection_id=selected.selection_id,
            ordered_leaf_ids=(leaf.leaf_id,),
            roles={leaf.leaf_id: leaf.role},
            scientific_identities={
                leaf.leaf_id: response_batches.scientific_computation_identity_sha256(
                    plan, leaf
                )
            },
        )
        stage_outcome = _binary64_horizon_outcome(plan, leaf)
        stage, stage_sha256 = build_schema11_horizon_stage(
            stage_outcome,
            precision_tier="binary64",
            operation_identity="binary64-horizon-production/v3",
        )
        response_disk = stage["response_disk"]
        assert isinstance(response_disk, dict)
        record = build_schema11_horizon_record(
            plan,
            leaf,
            stages=(stage,),
            retained_centre=response_disk["centre"],
            state="PRODUCED",
        )
        checkpoint = add_numerical_record(
            empty_schema11_checkpoint(plan.campaign_id, selected.selection_id),
            record,
        )
        checkpoint = record_survey_disposition(
            checkpoint,
            survey_pass=SurveyPass.BINARY64,
            leaf_id=leaf.leaf_id,
            disposition=SurveyDisposition.PROMOTION_PENDING_RESPONSE,
            operation_identity="binary64-horizon-production/v3",
            precision_tiers=("binary64",),
            reason_code="FIXED_PRECISION_SENTINEL_PROMOTION",
            sample_count=0,
            sample_limit=0,
            root_read_count=0,
            root_read_limit=0,
            worker_launch_count=0,
            worker_launch_limit=0,
            tier_timing=(),
            session_fragments=(),
            result_record_sha256=record["record_sha256"],
        )
        binary64_receipt = checkpoint["survey_pass_ledger"]["binary64"][
            leaf.leaf_id
        ]["disposition_receipt_sha256"]
        checkpoint = append_promotion(
            checkpoint,
            leaf_id=leaf.leaf_id,
            queue_kind=PromotionQueueKind.RESPONSE,
            reason_code="FIXED_PRECISION_SENTINEL_PROMOTION",
            minimum_requested_tier="BF80",
            scientific_computation_identity=selection.scientific_identities[
                leaf.leaf_id
            ],
            source_record_sha256=record["record_sha256"],
            source_stage_sha256=stage_sha256,
            source_binary64_disposition_receipt_sha256=binary64_receipt,
        )
        checkpoint["promotion_queue"]["entries"][0][
            "source_binary64_disposition_receipt_sha256"
        ] = "b" * 64
        called = False

        def promoted_runner(*_args):
            nonlocal called
            called = True
            raise AssertionError("BF80 runner must not start")

        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaises(CampaignSystemFailure):
                run_promoted_survey(
                    plan,
                    selection,
                    checkpoint,
                    checkpoint_path=Path(temporary) / "checkpoint.json",
                    root_seal_lookup=lambda _leaf, _entry: None,
                    provisional_stage_lookup=lambda _leaf, entry: entry[
                        "provisional_stage"
                    ],
                    root_seal_publish=lambda *_args: self.fail(
                        "horizon promotion must not publish a root"
                    ),
                    backend_factory=lambda _leaf, _digits: None,
                    primary_root_runner=lambda *_args: self.fail(
                        "unexpected promoted root"
                    ),
                    horizon_runner=lambda _leaf: self.fail(
                        "legacy promoted horizon runner was used"
                    ),
                    promoted_horizon_runner=promoted_runner,
                )
        self.assertFalse(called)

    def test_promoted_horizon_rejects_nonpromoting_source_receipt(self) -> None:
        plan = _plan()
        leaf = next(
            item
            for item in plan.leaves
            if item.role == "primary"
            and item.mechanism_id == "horizon-admittance"
        )
        stage_outcome = _binary64_horizon_outcome(plan, leaf)
        stage, stage_sha256 = build_schema11_horizon_stage(
            stage_outcome,
            precision_tier="binary64",
            operation_identity="binary64-horizon-production/v3",
        )
        response_disk = stage["response_disk"]
        assert isinstance(response_disk, dict)
        record = build_schema11_horizon_record(
            plan,
            leaf,
            stages=(stage,),
            retained_centre=response_disk["centre"],
            state="PRODUCED",
        )
        trigger_receipt = build_horizon_promotion_trigger_receipt(
            plan, leaf, stage_outcome, stage
        )
        self.assertFalse(trigger_receipt["promotion_required"])
        called = False

        class Backend:
            def _julia_precision_backend_for(self, *_args):
                nonlocal called
                called = True
                raise AssertionError("BF80 runner must not start")

        with self.assertRaisesRegex(ValueError, "does not require"):
            _promoted_horizon_outcome(
                plan,
                Backend(),
                leaf,
                queue_entry={
                    "source_record_sha256": record["record_sha256"],
                    "source_stage_sha256": stage_sha256,
                    "source_binary64_disposition_receipt_sha256": "c" * 64,
                },
                source_record=record,
                trigger_receipts=(trigger_receipt,),
            )
        self.assertFalse(called)

    def test_source_less_bf80_keeps_binary64_lineage_out_of_record_stages(self) -> None:
        """A locked v3 predecessor is provenance, not a BF80 record stage."""

        plan = _plan()
        leaf = next(
            item
            for item in plan.leaves
            if item.role == "primary"
            and item.mechanism_id == "horizon-admittance"
        )
        selected = build_campaign_selection(
            plan, role=leaf.role, leaf_ids=(leaf.leaf_id,)
        )
        scientific_identity = response_batches.scientific_computation_identity_sha256(
            plan, leaf
        )
        provisional_outcome = _binary64_horizon_outcome(plan, leaf)
        provisional, provisional_sha256 = build_schema11_horizon_stage(
            provisional_outcome,
            precision_tier="binary64",
            operation_identity="binary64-horizon-production/v3",
        )
        checkpoint = record_survey_disposition(
            empty_schema11_checkpoint(plan.campaign_id, selected.selection_id),
            survey_pass=SurveyPass.BINARY64,
            leaf_id=leaf.leaf_id,
            disposition=SurveyDisposition.PROMOTION_PENDING_RESPONSE,
            operation_identity="binary64-horizon-production/v3",
            precision_tiers=("binary64",),
            reason_code="ROOT_UNCERTAINTY_EVIDENCE_UNAVAILABLE",
            sample_count=0,
            sample_limit=0,
            root_read_count=0,
            root_read_limit=0,
            worker_launch_count=0,
            worker_launch_limit=0,
            tier_timing=(),
            session_fragments=(),
        )
        binary64_receipt_sha256 = checkpoint["survey_pass_ledger"]["binary64"][
            leaf.leaf_id
        ]["disposition_receipt_sha256"]
        checkpoint = append_promotion(
            checkpoint,
            leaf_id=leaf.leaf_id,
            queue_kind=PromotionQueueKind.RESPONSE,
            reason_code="ROOT_UNCERTAINTY_EVIDENCE_UNAVAILABLE",
            minimum_requested_tier="BF80",
            scientific_computation_identity=scientific_identity,
            source_stage_sha256=provisional_sha256,
            source_root_seal_sha256="d" * 64,
            provisional_stage=provisional,
            provisional_stage_sha256=provisional_sha256,
            provisional_operation_identity="binary64-horizon-production/v3",
            source_binary64_disposition_receipt_sha256=binary64_receipt_sha256,
        )
        queue_entry = checkpoint["promotion_queue"]["entries"][0]
        bf80_component = run_promoted_horizon_component(
            leaf.job,
            FakePromotedBackend(
                leaf.job,
                _promoted_baseline(
                    leaf.job,
                    omega=leaf.job.root.omega,
                    derivative=DecimalComplex(Decimal("1"), Decimal("0.25")),
                ),
            ),
            leaf.job.root.omega,
        )
        self.assertEqual("CONVERGED", bf80_component.status.value)

        class Backend:
            def _julia_precision_backend_for(self, *_args):
                return SimpleNamespace(
                    scientific_runtime_for=lambda _job: {"runtime": "synthetic-bf80"}
                )

        with patch(
            "windows_solver.campaign_runtime.run_promoted_horizon_component",
            return_value=bf80_component,
        ):
            outcome = _promoted_horizon_outcome(
                plan,
                Backend(),
                leaf,
                queue_entry=queue_entry,
            )

        self.assertIsNotNone(outcome.record)
        record = outcome.record
        assert isinstance(record, dict)
        response_batches.validate_schema11_horizon_record(plan, leaf, record)
        self.assertEqual(1, len(record["stages"]))
        self.assertEqual("BF80", record["stages"][0]["precision_tier"])
        self.assertEqual(
            "promoted-horizon-component/v2",
            record["stages"][0]["operation_identity"],
        )
        self.assertEqual(provisional, queue_entry["provisional_stage"])

        retained = campaign_survey._commit_promoted_outcome(
            checkpoint,
            leaf=leaf,
            leaf_id=leaf.leaf_id,
            queue_ordinal=0,
            queue_kind=PromotionQueueKind.RESPONSE,
            outcome=outcome,
            route="HORIZON_BF80",
            execution_preflight=PromotedExecutionPreflight(
                mode=PromotedExecutionMode.CALCULATE_ONLY,
                route="HORIZON_BF80",
                calibration_receipt_sha256="e" * 64,
                calculation_permitted=True,
                checkpointing_permitted=True,
                admission_permitted=False,
                publication_permitted=False,
                result_code="REVIEW_PENDING",
            ),
            layer1_lock_receipt_sha256="f" * 64,
            scientific_computation_identity=scientific_identity,
        )
        retained_stage = retained["promoted_stage_ledger"]["0"][leaf.leaf_id]
        self.assertEqual(provisional_sha256, retained_stage["predecessor_stage_sha256"])
        self.assertEqual(
            queue_entry["source_fingerprint_sha256"],
            retained_stage["source_fingerprint_sha256"],
        )
        self.assertEqual("f" * 64, retained_stage["layer1_lock_receipt_sha256"])
        self.assertEqual(
            "AWAITING_ADMISSION",
            retained["promotion_queue"]["entries"][0]["disposition"],
        )
        self.assertEqual([], retained["records"])
        self.assertEqual({}, retained["evidence_ledger"])

    def test_promoted_horizon_source_record_path_runs_and_retains_source(self) -> None:
        plan = _plan()
        leaf = next(
            item
            for item in plan.leaves
            if item.role == "deep"
            and item.mechanism_id == "horizon-admittance"
            and item.leaf_id
            in set(B_PRIME_RELEASE_DOMAIN.fixed_precision_sentinel_leaf_ids)
        )
        stage_outcome = replace(
            _binary64_horizon_outcome(plan, leaf),
            deep_diagnostics=_triggering_diagnostics(),
        )
        stage, stage_sha256 = build_schema11_horizon_stage(
            stage_outcome,
            precision_tier="binary64",
            operation_identity="binary64-horizon-production/v3",
        )
        response_disk = stage["response_disk"]
        assert isinstance(response_disk, dict)
        record = build_schema11_horizon_record(
            plan,
            leaf,
            stages=(stage,),
            retained_centre=response_disk["centre"],
            state="PRODUCED",
        )
        trigger_receipt = build_horizon_promotion_trigger_receipt(
            plan, leaf, stage_outcome, stage
        )
        self.assertTrue(trigger_receipt["promotion_required"])
        bf80_component = run_promoted_horizon_component(
            leaf.job,
            FakePromotedBackend(
                leaf.job,
                _promoted_baseline(
                    leaf.job,
                    omega=leaf.job.root.omega,
                    derivative=DecimalComplex(Decimal("1"), Decimal("0.25")),
                ),
            ),
            leaf.job.root.omega,
        )

        class Backend:
            def _julia_precision_backend_for(self, *_args):
                return SimpleNamespace(
                    scientific_runtime_for=lambda _job: {
                        "runtime": "synthetic-bf80"
                    }
                )

        with patch(
            "windows_solver.campaign_runtime.run_promoted_horizon_component",
            return_value=bf80_component,
        ):
            outcome = _promoted_horizon_outcome(
                plan,
                Backend(),
                leaf,
                queue_entry={
                    "source_record_sha256": record["record_sha256"],
                    "source_stage_sha256": stage_sha256,
                    "source_binary64_disposition_receipt_sha256": "c" * 64,
                },
                source_record=record,
                trigger_receipts=(trigger_receipt,),
            )

        self.assertIsNone(outcome.record)
        self.assertEqual(record["record_sha256"], outcome.source_record_sha256)
        self.assertEqual("UNRESOLVED", outcome.disposition.value)
        self.assertEqual(1, len(outcome.evidence_receipts))
        self.assertEqual(
            record["record_sha256"],
            outcome.evidence_receipts[0]["source_record_sha256"],
        )


if __name__ == "__main__":
    unittest.main()
