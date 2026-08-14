from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from fractions import Fraction
import hashlib
import io
import json
import math
from pathlib import Path
import tempfile
import unittest

import windows_solver.julia_response_backend as julia_backend
from windows_solver.contracts import canonical_json_bytes
from windows_solver.campaign_reports import refresh_campaign_reports
from windows_solver.progress import activate_progress
from windows_solver.progress_output import CampaignProgressReporter
from windows_solver.linear_response import B_PRIME_RELEASE_DOMAIN
from windows_solver.response_batches import (
    PrecisionCapabilities,
    StageOutcome,
    _checkpoint_precision_contract_sha256,
    _primary_recovery_precision_contract,
    _root_convergence_precision_contract,
    _produced_response,
    build_campaign_plan,
    build_campaign_selection,
    import_campaign_checkpoint_to_solved_leaf_store,
    merge_campaign_checkpoints,
    run_campaign_selection,
    synthetic_stage_signed_error_channels,
    validate_campaign_checkpoint,
)
from windows_solver.response_engine import (
    ComponentResult,
    ComponentStatus,
    DiagnosticRootReadout,
    LadderLevel,
    NumericalPolicy,
    NumericalConditioningEvidence,
    RootReadout,
    VettedNativeDeterminantKernel,
    regularised_gsn_precision_policy,
)
from windows_solver.solved_leaf_cache import SolvedLeafStore
from tests.fixtures import valid_numerical_conditioning


def leaf_id(role, mode_label, coordinate, mechanism_id):
    return next(
        leaf.leaf_id
        for leaf in B_PRIME_RELEASE_DOMAIN.production_leaves
        if (
            leaf.role,
            leaf.mode_label,
            leaf.coordinate,
            leaf.mechanism_id,
        ) == (role, mode_label, coordinate, mechanism_id)
    )


SENTINEL = leaf_id("deep", "220", Fraction(1, 100), "horizon-admittance")
PROMOTED_120 = leaf_id("deep", "222", Fraction(1, 500), "exterior-alpha-one")
MISSING_PRECISION = leaf_id(
    "deep", "210", Fraction(1, 1000), "exterior-throat-kappa"
)


def diagnostics(*, digits=12.0, step=0.0, repeat=0.0, angular=0.0,
                path=0.0, zero=False):
    return {
        "condition_amplifier_abs": 10.0,
        "predicted_reliable_decimal_digits": digits,
        "step_richardson_disagreement_abs": step,
        "repeat_polish_delta_abs": repeat,
        "angular_refinement_delta_abs": angular,
        "independent_path_delta_abs": path,
        "diagnostic_ceiling_abs": 1.0e-8,
        "denominator_or_calibration_disk_contains_zero": zero,
    }


def reseal(value):
    for record in value["records"]:
        for stage in record["stages"]:
            stage["stage_sha256"] = hashlib.sha256(canonical_json_bytes({
                key: item for key, item in stage.items() if key != "stage_sha256"
            })).hexdigest()
        record["record_sha256"] = hashlib.sha256(canonical_json_bytes({
            key: item for key, item in record.items() if key != "record_sha256"
        })).hexdigest()
    value["records_sha256"] = hashlib.sha256(
        canonical_json_bytes(value["records"])
    ).hexdigest()


def remove_promotion_decision_and_reseal(
    value, *, stage_index=1, remove_conditioning=False
):
    stage = value["records"][0]["stages"][stage_index]
    component = stage["component_result"]
    component.pop("promotion_decision")
    if remove_conditioning:
        component["result"]["baseline"].pop("numerical_conditioning")
    source_sha256 = hashlib.sha256(
        canonical_json_bytes(component)
    ).hexdigest()
    for channel in stage["signed_error_channels"]:
        channel["provenance"]["source_sha256"] = source_sha256
    reseal(value)


def _synthetic_stage_outcome(**values):
    component_result = values["component_result"]
    radius = values["local_disk_radius_abs"]
    return StageOutcome(
        **values,
        signed_error_channels=synthetic_stage_signed_error_channels(
            component_result, radius
        ),
    )


def _authenticated_primary_stage(
    leaf,
    digits,
    status,
    *,
    self_refinement_enclosed=None,
    discrepancy_from_previous_abs=None,
    discrepancy_enclosed=None,
    branch_loss_mismatch=True,
):
    """Build a canonical production-shaped stage without invoking a solver."""

    job = leaf.job
    status = ComponentStatus(status)
    levels = ()
    if status is ComponentStatus.CONVERGED:
        response = complex(1.0, -0.5)
        diagnostic_deltas = {
            "truncation": complex(3.0e-12, -1.0e-12),
            "resolution": complex(-2.0e-12, 2.0e-12),
            "seed-path": complex(1.0e-12, 3.0e-12),
        }

        def signed_readout(amplitude):
            return RootReadout(
                omega=job.root.omega + response * amplitude,
                determinant_residual_abs=1.0e-12,
                determinant_derivative_abs=2.0,
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
            for epsilon in job.policy.epsilons[-4:]
        )
    result = ComponentResult(
        job_id=job.job_id,
        leaf_id=job.leaf_id,
        mechanism_id=job.mechanism_id,
        status=status,
        convergence_basis=(
            "ORDER_RESOLVED" if status is ComponentStatus.CONVERGED else "UNRESOLVED"
        ),
        response=complex(1.0, -0.5) if status is ComponentStatus.CONVERGED else None,
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
        baseline=RootReadout(
            omega=job.root.omega,
            determinant_residual_abs=1.0e-12,
            determinant_derivative_abs=2.0,
            converged=status is not ComponentStatus.NOT_CONVERGED,
            root_reference_id=job.root.root_reference_id,
            branch_id=(
                f"{job.root.branch_id}-mismatch"
                if (
                    status is ComponentStatus.BRANCH_LOSS
                    and branch_loss_mismatch
                )
                else job.root.branch_id
            ),
            equation_id=job.equation_id,
            source_root_mapping=job.source_root_mapping,
        ),
        levels=levels,
        lineage={
            "leaf_id": job.leaf_id,
            "root_reference_id": job.root.root_reference_id,
            "root_identity_sha256": job.root.identity_sha256,
            "policy_sha256": job.policy.identity_sha256,
            "backend_identity_sha256": job.backend_identity.identity_sha256,
            "equation_id": job.equation_id,
            "sampling_coordinate": job.sampling_coordinate.to_mapping(),
            "source_root_mapping": job.source_root_mapping,
        },
    )
    component_result = {
        "evidence_kind": "authenticated-primary-precision-contract",
        "result": result.to_mapping(),
    }
    return _synthetic_stage_outcome(
        digits=digits,
        numerical_state=status.value,
        component_result=component_result,
        local_disk_radius_abs=1.0e-8,
        self_refinement_enclosed=self_refinement_enclosed,
        discrepancy_from_previous_abs=discrepancy_from_previous_abs,
        discrepancy_enclosed=discrepancy_enclosed,
    )


def _replace_component_result_fields(
    outcome,
    *,
    result_changes=None,
    raw_changes=None,
):
    """Reseal a synthetic stage around an independently chosen result body."""

    component = dict(outcome.component_result)
    result = replace(
        ComponentResult.from_mapping(component["result"]),
        **(result_changes or {}),
    )
    raw_result = result.to_mapping()
    raw_result.update(raw_changes or {})
    component["result"] = raw_result
    return replace(
        outcome,
        component_result=component,
        signed_error_channels=synthetic_stage_signed_error_channels(
            component, outcome.local_disk_radius_abs
        ),
    )


def _with_baseline_conditioning(
    outcome,
    *,
    predicted_reliable_digits,
    required_reliable_digits,
    precision_limited,
):
    result = ComponentResult.from_mapping(outcome.component_result["result"])
    mapping = valid_numerical_conditioning(result.mechanism_id)
    mapping.update({
        "predicted_reliable_digits": predicted_reliable_digits,
        "required_reliable_digits": required_reliable_digits,
        "precision_limited": precision_limited,
    })
    evidence = NumericalConditioningEvidence.from_mapping(mapping)
    horizon = evidence.scattering_diagnostics_applicable

    def conditioned(readout):
        return replace(
            readout,
            diagnostic_readouts=(readout.diagnostic_readouts or None),
            numerical_conditioning=evidence,
            normalised_determinant_abs=Decimal(
                str(readout.determinant_residual_abs)
            ),
            raw_determinant_abs=(
                Decimal(str(readout.determinant_residual_abs))
                if horizon
                else None
            ),
        )

    levels = tuple(
        replace(
            level,
            real_plus=conditioned(level.real_plus),
            real_minus=conditioned(level.real_minus),
            imaginary_plus=conditioned(level.imaginary_plus),
            imaginary_minus=conditioned(level.imaginary_minus),
        )
        for level in result.levels
    )
    conditioned_outcome = _replace_component_result_fields(
        outcome,
        result_changes={
            "baseline": conditioned(result.baseline),
            "levels": levels,
        },
    )
    component = dict(conditioned_outcome.component_result)
    component.update({
        "evidence_kind": "package-owned-julia-promoted-component-engine",
        "self_refinement_result": None,
        "scientific_runtime": {
            "precision_digits": outcome.digits,
            "working_precision_bits": (
                math.ceil(outcome.digits * math.log2(10)) + 32
            ),
            "refinement_level": 0,
            "regularised_gsn_precision_policy": dict(
                regularised_gsn_precision_policy(result.mechanism_id)
            ),
        },
    })
    if result.status is ComponentStatus.NOT_CONVERGED:
        component["self_refinement_skipped_reason"] = "PRIMARY_NOT_CONVERGED"
    return replace(
        conditioned_outcome,
        component_result=component,
        signed_error_channels=synthetic_stage_signed_error_channels(
            component, conditioned_outcome.local_disk_radius_abs
        ),
    )


def _authenticated_failed_preflight_recovery_stage(leaf, predecessor):
    """Build an independently checkable 120-base/120-refinement fixture."""

    outcome = _authenticated_primary_stage(
        leaf,
        120,
        ComponentStatus.CONVERGED,
        self_refinement_enclosed=True,
        discrepancy_from_previous_abs=None,
        discrepancy_enclosed=None,
    )
    outcome = _with_baseline_conditioning(
        outcome,
        predicted_reliable_digits="55",
        required_reliable_digits="24",
        precision_limited=False,
    )
    component = dict(outcome.component_result)
    component.update({
        "failed_preflight_predecessor": predecessor.to_mapping(),
        "comparison_kind": "same-precision-120-base-vs-refinement/v1",
        "precision_ladder_discrepancy_applicable": False,
        "same_precision_refinement_discrepancy_abs": 0.0,
        "self_refinement_result": component["result"],
        "self_refinement_scientific_runtime": {
            **dict(component["scientific_runtime"]),
            "refinement_level": 1,
        },
    })
    return replace(
        outcome,
        component_result=component,
        signed_error_channels=synthetic_stage_signed_error_channels(
            component,
            outcome.local_disk_radius_abs,
            precision_ladder_applicable=False,
        ),
    )


def _reseal_failed_preflight_recovery_stage(outcome, component, **changes):
    return replace(
        outcome,
        component_result=component,
        signed_error_channels=synthetic_stage_signed_error_channels(
            component,
            outcome.local_disk_radius_abs,
            precision_ladder_applicable=False,
        ),
        **changes,
    )


def _condition_failed_preflight_result(
    outcome,
    result_key,
    *,
    predicted_reliable_digits,
    required_reliable_digits="24",
    precision_limited,
):
    component = dict(outcome.component_result)
    temporary_component = {"result": component[result_key]}
    temporary = replace(
        outcome,
        component_result=temporary_component,
        signed_error_channels=synthetic_stage_signed_error_channels(
            temporary_component, outcome.local_disk_radius_abs
        ),
    )
    conditioned = _with_baseline_conditioning(
        temporary,
        predicted_reliable_digits=predicted_reliable_digits,
        required_reliable_digits=required_reliable_digits,
        precision_limited=precision_limited,
    )
    component[result_key] = conditioned.component_result["result"]
    return _reseal_failed_preflight_recovery_stage(outcome, component)


def _branch_safe_failed_preflight_recovery_stage(outcome, leaf):
    component = dict(outcome.component_result)

    def safe_result(raw):
        result = ComponentResult.from_mapping(raw)

        def safe(readout):
            return replace(readout, omega=leaf.job.root.omega)

        levels = tuple(
            replace(
                level,
                real_plus=safe(level.real_plus),
                real_minus=safe(level.real_minus),
                imaginary_plus=safe(level.imaginary_plus),
                imaginary_minus=safe(level.imaginary_minus),
            )
            for level in result.levels
        )
        return replace(result, levels=levels).to_mapping()

    component["result"] = safe_result(component["result"])
    component["self_refinement_result"] = safe_result(
        component["self_refinement_result"]
    )
    return _reseal_failed_preflight_recovery_stage(outcome, component)


class PromotedConditioningDecisionTests(unittest.TestCase):
    @staticmethod
    def _run(*, evidence, status80=ComponentStatus.NOT_CONVERGED,
             self_refinement_enclosed=True, discrepancy_enclosed=True):
        capabilities = PrecisionCapabilities((64, 80, 120))
        plan = build_campaign_plan(
            policy=NumericalPolicy(),
            backend_identity=VettedNativeDeterminantKernel.identity,
            precision_capabilities=capabilities,
        )
        leaf = next(item for item in plan.leaves if item.role == "primary")
        selection = build_campaign_selection(
            plan, role="primary", leaf_ids=(leaf.leaf_id,)
        )

        class Backend:
            identity = plan.backend_identity
            precision_capabilities = capabilities

            def __init__(self):
                self.calls = []

            def execute_stage(self, selected, digits):
                self.calls.append(digits)
                if digits == 64:
                    return _authenticated_primary_stage(
                        selected, digits, ComponentStatus.NOT_CONVERGED
                    )
                if digits == 80:
                    outcome = _authenticated_primary_stage(
                        selected,
                        digits,
                        status80,
                        self_refinement_enclosed=self_refinement_enclosed,
                        discrepancy_from_previous_abs=1.0e-9,
                        discrepancy_enclosed=discrepancy_enclosed,
                    )
                    if evidence is not None:
                        outcome = _with_baseline_conditioning(
                            outcome, **evidence
                        )
                    return outcome
                return _authenticated_primary_stage(
                    selected,
                    digits,
                    ComponentStatus.CONVERGED,
                    discrepancy_from_previous_abs=1.0e-10,
                    discrepancy_enclosed=True,
                )

        temporary = tempfile.TemporaryDirectory()
        checkpoint = Path(temporary.name) / "conditioning.json"
        backend = Backend()
        summary = run_campaign_selection(
            plan, selection, backend, checkpoint, resume=False
        )
        reloaded = validate_campaign_checkpoint(plan, checkpoint)
        return temporary, backend, summary, reloaded

    def test_nonconverged_precision_limited_result_requests_120(self):
        temporary, backend, summary, reloaded = self._run(evidence={
            "predicted_reliable_digits": "11.2500",
            "required_reliable_digits": "24",
            "precision_limited": True,
        })
        self.addCleanup(temporary.cleanup)

        self.assertEqual(backend.calls, [64, 80, 120])
        decision = summary.records[0].stages[1].outcome.component_result[
            "promotion_decision"
        ]
        self.assertEqual(decision, {
            "schema": "windows-solver.precision-promotion-decision/1",
            "from_precision_digits": 80,
            "to_precision_digits": 120,
            "state": "REQUESTED",
            "reason": "INSUFFICIENT_RELIABLE_DIGITS",
            "predicted_reliable_digits": "11.2500",
            "required_reliable_digits": "24",
            "precision_limited": True,
            "asymptotic_preflight_avoided_ode": False,
        })
        self.assertEqual(
            reloaded.records[0].stages[1].outcome.component_result[
                "promotion_decision"
            ],
            decision,
        )

    def test_nonconverged_adequate_result_suppresses_120(self):
        temporary, backend, summary, _ = self._run(evidence={
            "predicted_reliable_digits": "55.12500000000000000001",
            "required_reliable_digits": "24",
            "precision_limited": False,
        })
        self.addCleanup(temporary.cleanup)

        self.assertEqual(backend.calls, [64, 80])
        self.assertEqual(summary.records[0].state, "UNRESOLVED")
        decision = summary.records[0].stages[1].outcome.component_result[
            "promotion_decision"
        ]
        self.assertEqual(decision["state"], "SUPPRESSED")
        self.assertEqual(
            decision["reason"], "PREDICTED_RELIABLE_DIGITS_ADEQUATE"
        )
        self.assertEqual(
            decision["predicted_reliable_digits"],
            "55.12500000000000000001",
        )

    def test_legacy_missing_conditioning_preserves_prior_promotion(self):
        temporary, backend, summary, _ = self._run(evidence=None)
        self.addCleanup(temporary.cleanup)

        self.assertEqual(backend.calls, [64, 80, 120])
        decision = summary.records[0].stages[1].outcome.component_result[
            "promotion_decision"
        ]
        self.assertEqual(decision["state"], "REQUESTED")
        self.assertEqual(
            decision["reason"], "LEGACY_CONDITIONING_EVIDENCE_ABSENT"
        )
        self.assertIsNone(decision["predicted_reliable_digits"])
        self.assertIsNone(decision["required_reliable_digits"])
        self.assertIsNone(decision["precision_limited"])

    def test_converged_refinement_gates_remain_authoritative(self):
        temporary, backend, summary, _ = self._run(
            evidence={
                "predicted_reliable_digits": "11.25",
                "required_reliable_digits": "24",
                "precision_limited": True,
            },
            status80=ComponentStatus.CONVERGED,
            self_refinement_enclosed=True,
            discrepancy_enclosed=True,
        )
        self.addCleanup(temporary.cleanup)

        self.assertEqual(backend.calls, [64, 80])
        decision = summary.records[0].stages[1].outcome.component_result[
            "promotion_decision"
        ]
        self.assertEqual(decision["state"], "SUPPRESSED")
        self.assertEqual(
            decision["reason"], "CONVERGED_PROMOTION_GATES_SATISFIED"
        )

    def test_deep_nonconverged_adequate_result_suppresses_120(self):
        capabilities = PrecisionCapabilities((64, 80, 120))
        plan = build_campaign_plan(
            policy=NumericalPolicy(),
            backend_identity=VettedNativeDeterminantKernel.identity,
            precision_capabilities=capabilities,
        )
        leaf = next(item for item in plan.leaves if item.role == "deep")
        selection = build_campaign_selection(
            plan, role="deep", leaf_ids=(leaf.leaf_id,)
        )

        class Backend:
            identity = plan.backend_identity
            precision_capabilities = capabilities

            def __init__(self):
                self.calls = []

            def execute_stage(self, selected, digits):
                self.calls.append(digits)
                if digits == 64:
                    return replace(
                        _authenticated_primary_stage(
                            selected, digits, ComponentStatus.CONVERGED
                        ),
                        deep_diagnostics=diagnostics(digits=8.0),
                    )
                outcome = _authenticated_primary_stage(
                    selected,
                    digits,
                    ComponentStatus.NOT_CONVERGED,
                    self_refinement_enclosed=False,
                    discrepancy_from_previous_abs=1.0e-9,
                    discrepancy_enclosed=True,
                )
                return _with_baseline_conditioning(
                    outcome,
                    predicted_reliable_digits="52.12500000000000000001",
                    required_reliable_digits="24",
                    precision_limited=False,
                )

        with tempfile.TemporaryDirectory() as temporary:
            backend = Backend()
            summary = run_campaign_selection(
                plan,
                selection,
                backend,
                Path(temporary) / "deep-conditioning.json",
                resume=False,
            )

        self.assertEqual(backend.calls, [64, 80])
        self.assertEqual(summary.records[0].state, "UNRESOLVED")
        decision = summary.records[0].stages[1].outcome.component_result[
            "promotion_decision"
        ]
        self.assertEqual(decision["state"], "SUPPRESSED")
        self.assertEqual(
            decision["reason"], "PREDICTED_RELIABLE_DIGITS_ADEQUATE"
        )

    def test_sentinel_false_negative_remains_mandatory_with_adequate_digits(self):
        capabilities = PrecisionCapabilities((64, 80, 120))
        plan = build_campaign_plan(
            policy=NumericalPolicy(),
            backend_identity=VettedNativeDeterminantKernel.identity,
            precision_capabilities=capabilities,
        )
        leaf = next(item for item in plan.leaves if item.leaf_id == SENTINEL)
        selection = build_campaign_selection(
            plan, role="deep", leaf_ids=(leaf.leaf_id,)
        )

        class Backend:
            identity = plan.backend_identity
            precision_capabilities = capabilities

            def __init__(self):
                self.calls = []

            def execute_stage(self, selected, digits):
                self.calls.append(digits)
                if digits == 64:
                    return replace(
                        _authenticated_primary_stage(
                            selected, digits, ComponentStatus.CONVERGED
                        ),
                        deep_diagnostics=diagnostics(digits=12.0),
                    )
                if digits == 80:
                    outcome = _authenticated_primary_stage(
                        selected,
                        digits,
                        ComponentStatus.NOT_CONVERGED,
                        self_refinement_enclosed=False,
                        discrepancy_from_previous_abs=1.0e-8,
                        discrepancy_enclosed=True,
                    )
                    return _with_baseline_conditioning(
                        outcome,
                        predicted_reliable_digits="55.125",
                        required_reliable_digits="24",
                        precision_limited=False,
                    )
                return _authenticated_primary_stage(
                    selected,
                    digits,
                    ComponentStatus.CONVERGED,
                    discrepancy_from_previous_abs=1.0e-9,
                    discrepancy_enclosed=True,
                )

        with tempfile.TemporaryDirectory() as temporary:
            backend = Backend()
            summary = run_campaign_selection(
                plan,
                selection,
                backend,
                Path(temporary) / "sentinel-conditioning.json",
                resume=False,
            )

        self.assertEqual(backend.calls, [64, 80, 120])
        self.assertEqual(
            summary.records[0].state, "INVALID_SENTINEL_FALSE_NEGATIVE"
        )
        decision = summary.records[0].stages[1].outcome.component_result[
            "promotion_decision"
        ]
        self.assertEqual(decision["state"], "REQUESTED")
        self.assertEqual(decision["reason"], "SENTINEL_TRIGGER_FALSE_NEGATIVE")

    def test_schema_five_cannot_strip_conditioning_and_promotion_decision(self):
        temporary, _, _, _ = self._run(evidence={
            "predicted_reliable_digits": "11.25",
            "required_reliable_digits": "24",
            "precision_limited": True,
        })
        self.addCleanup(temporary.cleanup)
        checkpoint = Path(temporary.name) / "conditioning.json"
        forged = json.loads(checkpoint.read_text(encoding="utf-8"))
        self.assertEqual(forged["schema_version"], 6)
        remove_promotion_decision_and_reseal(
            forged, remove_conditioning=True
        )
        checkpoint.write_bytes(canonical_json_bytes(forged))

        plan = build_campaign_plan(
            policy=NumericalPolicy(),
            backend_identity=VettedNativeDeterminantKernel.identity,
            precision_capabilities=PrecisionCapabilities((64, 80, 120)),
        )
        with self.assertRaisesRegex(
            ValueError, "scientific runtime lacks current conditioning"
        ):
            validate_campaign_checkpoint(plan, checkpoint)

    def test_schema_four_allows_historical_missing_decision_and_conditioning(self):
        temporary, _, _, _ = self._run(evidence=None)
        self.addCleanup(temporary.cleanup)
        checkpoint = Path(temporary.name) / "conditioning.json"
        historical = json.loads(checkpoint.read_text(encoding="utf-8"))
        remove_promotion_decision_and_reseal(historical)
        historical["schema_version"] = 4
        checkpoint.write_bytes(canonical_json_bytes(historical))

        plan = build_campaign_plan(
            policy=NumericalPolicy(),
            backend_identity=VettedNativeDeterminantKernel.identity,
            precision_capabilities=PrecisionCapabilities((64, 80, 120)),
        )
        restored = validate_campaign_checkpoint(plan, checkpoint)

        self.assertNotIn(
            "promotion_decision",
            restored.records[0].stages[1].outcome.component_result,
        )

    def test_schema_four_without_decision_is_not_resealed_on_resume(self):
        temporary, backend, _, _ = self._run(evidence=None)
        self.addCleanup(temporary.cleanup)
        checkpoint = Path(temporary.name) / "conditioning.json"
        historical = json.loads(checkpoint.read_text(encoding="utf-8"))
        remove_promotion_decision_and_reseal(historical)
        historical["schema_version"] = 4
        checkpoint.write_bytes(canonical_json_bytes(historical))
        original = checkpoint.read_bytes()

        plan = build_campaign_plan(
            policy=NumericalPolicy(),
            backend_identity=VettedNativeDeterminantKernel.identity,
            precision_capabilities=PrecisionCapabilities((64, 80, 120)),
        )
        leaf = next(item for item in plan.leaves if item.role == "primary")
        selection = build_campaign_selection(
            plan, role="primary", leaf_ids=(leaf.leaf_id,)
        )
        backend.calls.clear()

        with self.assertRaisesRegex(ValueError, "promotion decision is required"):
            run_campaign_selection(
                plan,
                selection,
                backend,
                checkpoint,
                resume=True,
            )

        self.assertEqual(backend.calls, [])
        self.assertEqual(checkpoint.read_bytes(), original)

    def test_schema_four_without_decision_is_not_merged_as_schema_five(self):
        temporary, _, _, _ = self._run(evidence=None)
        self.addCleanup(temporary.cleanup)
        checkpoint = Path(temporary.name) / "conditioning.json"
        historical = json.loads(checkpoint.read_text(encoding="utf-8"))
        remove_promotion_decision_and_reseal(historical)
        historical["schema_version"] = 4
        checkpoint.write_bytes(canonical_json_bytes(historical))
        output = Path(temporary.name) / "merged.json"

        plan = build_campaign_plan(
            policy=NumericalPolicy(),
            backend_identity=VettedNativeDeterminantKernel.identity,
            precision_capabilities=PrecisionCapabilities((64, 80, 120)),
        )
        with self.assertRaisesRegex(ValueError, "promotion decision is required"):
            merge_campaign_checkpoints(plan, (checkpoint,), output)

        self.assertFalse(output.exists())


class PrimaryPrecisionTests(unittest.TestCase):
    def test_root_convergence_contract_names_estimate_and_safeguards(self):
        """Catches presenting a local Newton estimate as certified root error."""

        self.assertEqual(
            _root_convergence_precision_contract(),
            {
                "version": 1,
                "metric": "newton_correction_estimate_abs",
                "definition": "determinant_residual_abs_over_derivative_abs",
                "binary64_tolerance_abs": 2.0e-11,
                "derivative_requirement": "finite_strictly_positive",
                "required_phases": [
                    "PRIMARY",
                    "TRUNCATION",
                    "RESOLUTION",
                    "SEED-PATH",
                ],
                "branch_continuation_required": True,
                "evidence_ceiling": "local_estimate_not_root_enclosure",
            },
        )

    def test_primary_recovery_contract_binds_promoted_numerical_controls(self):
        """Catches changing promoted tolerances without changing policy identity."""

        contract = _primary_recovery_precision_contract()

        self.assertEqual(contract["recovery_digits"], [80, 120])
        self.assertEqual(
            contract["promoted_numerical_controls"],
            {
                "80": {
                    "base": {
                        "root_correction_tolerance": "1e-18",
                        "ode_relative_tolerance": "1e-18",
                        "ode_absolute_tolerance": "1e-20",
                        "frequency_step": "1e-6",
                    },
                    "refinement": {
                        "root_correction_tolerance": "1e-20",
                        "ode_relative_tolerance": "1e-20",
                        "ode_absolute_tolerance": "1e-20",
                        "frequency_step": "1e-7",
                    },
                },
                "120": {
                    "base": {
                        "root_correction_tolerance": "1e-102",
                        "ode_relative_tolerance": "1e-102",
                        "ode_absolute_tolerance": "1e-104",
                        "frequency_step": "1e-60",
                    },
                    "refinement": {
                        "root_correction_tolerance": "1e-106",
                        "ode_relative_tolerance": "1e-106",
                        "ode_absolute_tolerance": "1e-108",
                        "frequency_step": "1e-60",
                    },
                },
            },
        )
        alternate = contract["failed_preflight_alternate"]
        self.assertEqual(
            alternate["control_predecessor"],
            {
                "precision_digits": 80,
                "failure_code": "INSUFFICIENT_ASYMPTOTIC_PRECISION",
                "failure_class": "CONTROL",
                "retryable": True,
                "request_binding_required": True,
                "asymptotic_preflight_avoided_ode": True,
                "factored_homogeneous_rhs_evaluations": 0,
                "avoided_ode_scope": "factored-homogeneous-gsn/v1",
            },
        )
        self.assertEqual(alternate["terminal_precision_sequence"], [64, 120])
        self.assertEqual(
            alternate["comparison_kind"],
            "same-precision-120-base-vs-refinement/v1",
        )
        self.assertIs(
            alternate["precision_ladder_discrepancy_applicable"], False
        )
        self.assertEqual(
            alternate["terminal_state"]["fixed_precision_sentinel"],
            "UNRESOLVED",
        )

    def test_authenticated_primary_not_converged_recovers_at_80_or_each_120_gate(self) -> None:
        """Catches PRIMARY records terminalized at binary64 instead of recovered."""

        capabilities = PrecisionCapabilities((64, 80, 120))
        plan = build_campaign_plan(
            policy=NumericalPolicy(),
            backend_identity=VettedNativeDeterminantKernel.identity,
            precision_capabilities=capabilities,
        )
        leaf = next(item for item in plan.leaves if item.role == "primary")
        selection = build_campaign_selection(
            plan, role="primary", leaf_ids=(leaf.leaf_id,)
        )
        cases = {
            "80-terminal": (
                ComponentStatus.CONVERGED,
                True,
                True,
                ComponentStatus.CONVERGED,
                True,
                (64, 80),
                "PRODUCED",
            ),
            "80-not-converged": (
                ComponentStatus.NOT_CONVERGED,
                True,
                True,
                ComponentStatus.CONVERGED,
                True,
                (64, 80, 120),
                "PRODUCED",
            ),
            "80-branch-loss-is-terminal": (
                ComponentStatus.BRANCH_LOSS,
                True,
                True,
                ComponentStatus.CONVERGED,
                True,
                (64, 80),
                "UNRESOLVED",
            ),
            "80-self-refinement-unenclosed": (
                ComponentStatus.CONVERGED,
                False,
                True,
                ComponentStatus.CONVERGED,
                True,
                (64, 80, 120),
                "PRODUCED",
            ),
            "64-80-discrepancy-unenclosed": (
                ComponentStatus.CONVERGED,
                True,
                False,
                ComponentStatus.CONVERGED,
                True,
                (64, 80, 120),
                "PRODUCED",
            ),
            "120-nonconvergence-is-terminal-unresolved": (
                ComponentStatus.CONVERGED,
                False,
                True,
                ComponentStatus.NOT_CONVERGED,
                True,
                (64, 80, 120),
                "UNRESOLVED",
            ),
            "120-unenclosed-discrepancy-is-terminal-unresolved": (
                ComponentStatus.CONVERGED,
                False,
                True,
                ComponentStatus.CONVERGED,
                False,
                (64, 80, 120),
                "UNRESOLVED",
            ),
        }

        for name, (
            status80,
            self_enclosed,
            discrepancy_enclosed,
            status120,
            discrepancy120_enclosed,
            expected,
            terminal_state,
        ) in cases.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                class Backend:
                    identity = plan.backend_identity
                    precision_capabilities = capabilities

                    def __init__(self):
                        self.calls = []

                    def execute_stage(self, selected, digits):
                        self.calls.append(digits)
                        if digits == 64:
                            return _authenticated_primary_stage(
                                selected, digits, ComponentStatus.NOT_CONVERGED
                            )
                        if digits == 80:
                            return _authenticated_primary_stage(
                                selected,
                                digits,
                                status80,
                                self_refinement_enclosed=self_enclosed,
                                discrepancy_from_previous_abs=1.0e-9,
                                discrepancy_enclosed=discrepancy_enclosed,
                            )
                        return _authenticated_primary_stage(
                            selected,
                            digits,
                            status120,
                            discrepancy_from_previous_abs=1.0e-10,
                            discrepancy_enclosed=discrepancy120_enclosed,
                        )

                backend = Backend()
                root = Path(temporary)
                checkpoint = root / "primary.json"
                store = SolvedLeafStore(root / "solved")
                summary = run_campaign_selection(
                    plan,
                    selection,
                    backend,
                    checkpoint,
                    resume=False,
                    solved_leaf_store=store,
                )

                self.assertEqual(tuple(backend.calls), expected)
                self.assertEqual(summary.state, "COMPLETE")
                self.assertEqual(summary.records[0].state, terminal_state)
                self.assertEqual(
                    tuple(stage.outcome.digits for stage in summary.records[0].stages),
                    expected,
                )
                self.assertEqual(
                    validate_campaign_checkpoint(plan, checkpoint).records,
                    summary.records,
                )
                self.assertEqual(store.stored_count, 1)
                if terminal_state == "PRODUCED":
                    self.assertEqual(
                        _produced_response(summary.records[0]),
                        complex(1.0, -0.5),
                    )

        with self.subTest(name="missing-80-is-not-terminal-or-cacheable"):
            binary64 = PrecisionCapabilities((64,))
            plan64 = build_campaign_plan(
                policy=NumericalPolicy(),
                backend_identity=VettedNativeDeterminantKernel.identity,
                precision_capabilities=binary64,
            )
            leaf64 = next(item for item in plan64.leaves if item.role == "primary")
            selection64 = build_campaign_selection(
                plan64, role="primary", leaf_ids=(leaf64.leaf_id,)
            )

            class Binary64Backend:
                identity = plan64.backend_identity
                precision_capabilities = binary64

                def __init__(self):
                    self.calls = []

                def execute_stage(self, selected, digits):
                    self.calls.append(digits)
                    return _authenticated_primary_stage(
                        selected, digits, ComponentStatus.NOT_CONVERGED
                    )

            with tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                store = SolvedLeafStore(root / "solved")
                backend = Binary64Backend()
                summary = run_campaign_selection(
                    plan64,
                    selection64,
                    backend,
                    root / "primary.json",
                    resume=False,
                    solved_leaf_store=store,
                )

            self.assertEqual(backend.calls, [64])
            self.assertEqual(summary.state, "PARTIAL")
            self.assertEqual(summary.records[0].state, "MISSING_PRECISION")
            self.assertEqual(summary.records[0].missing_precision_digits, 80)
            self.assertEqual(store.stored_count, 0)


class PromotedResourceContainmentTests(unittest.TestCase):
    @staticmethod
    def _plan_and_leaves():
        capabilities = PrecisionCapabilities((64, 80, 120))
        plan = build_campaign_plan(
            policy=NumericalPolicy(),
            backend_identity=VettedNativeDeterminantKernel.identity,
            precision_capabilities=capabilities,
        )
        incident = next(
            leaf
            for leaf in plan.leaves
            if (
                leaf.role == "primary"
                and leaf.leaf.mode_label == "221"
                and leaf.job.spin == 0.95
                and leaf.mechanism_id == "horizon-admittance"
            )
        )
        following = next(
            leaf
            for leaf in plan.leaves
            if (
                leaf.role == "primary"
                and leaf.leaf.mode_label == "221"
                and leaf.job.spin == 0.99
                and leaf.mechanism_id == "horizon-admittance"
            )
        )
        selection = build_campaign_selection(
            plan,
            role="primary",
            leaf_ids=(incident.leaf_id, following.leaf_id),
        )
        return plan, capabilities, selection, incident, following

    @staticmethod
    def _failure(
        error_class,
        failure_code,
        *,
        timed_out=False,
        leaf=None,
        precision_digits=80,
    ):
        error = (
            error_class(f"synthetic {failure_code}", failure_code)
            if error_class is julia_backend.JuliaNumericalControlError
            else error_class(f"synthetic {failure_code}")
        )
        error.worker_failure = {
            "worker_exit_code": None if timed_out else 1,
            "worker_timed_out": timed_out,
            "worker_stderr_tail": "bounded synthetic stderr",
            "worker_error_type": "SyntheticControlFailure",
            "worker_error_message": failure_code,
            "failure": {
                "failure_code": failure_code,
                "failure_class": "CONTROL",
                "retryable": (
                    failure_code == "INSUFFICIENT_ASYMPTOTIC_PRECISION"
                    if error_class is julia_backend.JuliaNumericalControlError
                    else True
                ),
                "precision_digits": precision_digits,
                "readout_index": 1,
                "readout_role": "baseline",
                "root_phase": "PRIMARY",
                "newton_index": 1,
                "determinant_index": 3,
                "phase_determinant_index": 3,
                "determinant_purpose": "residual",
                "elapsed_request_seconds": 5271.5,
                "elapsed_phase_seconds": 5271.5,
                "elapsed_leg_seconds": 1900.0,
                "ode_leg": "Xup_match_to_inner",
                "limiting_resource": (
                    "worker_request_wall_clock"
                    if timed_out
                    else "rhs_evaluations"
                ),
                "ode_snapshot": {
                    "accepted_steps": 982000,
                    "rejected_steps": 0,
                    "rhs_evaluations": 1960000,
                },
                "execution_resource_policy": {
                    "schema": "windows-solver.execution-resource-policy/1",
                    "version": 1,
                    "sha256": "a" * 64,
                },
            },
        }
        if leaf is not None:
            request_binding = julia_backend.JuliaPrecisionRootBackend(
                leaf.job.backend_identity,
                object(),
                precision_digits,
                refinement=0,
            )._request(leaf.job, 0.0j)
            request_sha256 = hashlib.sha256(
                canonical_json_bytes(request_binding)
            ).hexdigest()
            error.worker_failure["failure"].update({
                "request_sha256": request_sha256,
                "request_binding": request_binding,
                "job_id": leaf.job.job_id,
                "leaf_id": leaf.leaf_id,
                "role": leaf.role,
                "job_policy_sha256": leaf.job.policy.identity_sha256,
                "backend_identity_sha256": (
                    leaf.job.backend_identity.identity_sha256
                ),
                "refinement_level": 0,
                "execution_resource_policy": {
                    name: request_binding["execution_resource"][name]
                    for name in ("schema", "version", "sha256")
                },
            })
        if error_class is julia_backend.JuliaNumericalControlError:
            error.worker_failure["failure"]["diagnostics"] = {
                "predicted_reliable_digits": "11.25000000000000000001",
                "required_reliable_digits": "24",
                "asymptotic_preflight_avoided_ode": True,
                "asymptotic_preflight_reason": failure_code,
                "factored_homogeneous_rhs_evaluations": 0,
                "avoided_ode_scope": "factored-homogeneous-gsn/v1",
            }
        return error

    def _run_with_failure(self, error_class, failure_code, *, timed_out=False):
        plan, capabilities, selection, incident, following = self._plan_and_leaves()
        failure = self._failure(
            error_class, failure_code, timed_out=timed_out, leaf=incident
        )

        class Backend:
            identity = plan.backend_identity
            precision_capabilities = capabilities

            def __init__(self):
                self.calls = []

            def execute_stage(self, leaf, digits):
                self.calls.append((leaf.leaf_id, digits))
                if leaf.leaf_id == incident.leaf_id:
                    if digits == 64:
                        return _authenticated_primary_stage(
                            leaf, digits, ComponentStatus.NOT_CONVERGED
                        )
                    raise failure
                return _authenticated_primary_stage(
                    leaf, digits, ComponentStatus.CONVERGED
                )

            def execute_promoted_stage_after_failed_preflight(
                self, leaf, digits, predecessor
            ):
                self.calls.append((leaf.leaf_id, digits))
                return _authenticated_failed_preflight_recovery_stage(
                    leaf, predecessor
                )

        temporary = tempfile.TemporaryDirectory()
        root = Path(temporary.name)
        backend = Backend()
        store = SolvedLeafStore(root / "solved")
        checkpoint = root / "checkpoint.json"
        reporter = CampaignProgressReporter("normal", checkpoint, io.StringIO())
        reporter.bind_campaign_reports(plan)
        with activate_progress(reporter):
            summary = run_campaign_selection(
                plan,
                selection,
                backend,
                checkpoint,
                resume=False,
                solved_leaf_store=store,
            )
        return (
            temporary,
            root,
            plan,
            selection,
            incident,
            following,
            backend,
            store,
            summary,
        )

    def test_promoted_ode_resource_limit_is_durable_and_next_leaf_executes(self):
        run = self._run_with_failure(
            julia_backend.JuliaODEResourceLimitError,
            "ODE_RESOURCE_LIMIT",
        )
        temporary, root, plan, _, incident, following, backend, store, summary = run
        self.addCleanup(temporary.cleanup)

        records = {record.leaf_id: record for record in summary.records}
        self.assertEqual(summary.state, "PARTIAL")
        self.assertFalse(records[incident.leaf_id].to_mapping()["computed"])
        self.assertEqual(records[following.leaf_id].state, "PRODUCED")
        self.assertIn((following.leaf_id, 64), backend.calls)
        self.assertEqual(store.stored_count, 1)
        self.assertEqual(len(summary.attempts), 1)
        self.assertEqual(summary.attempts[0].failure_code, "ODE_RESOURCE_LIMIT")
        self.assertEqual(summary.attempts[0].state, "EXECUTION_RESOURCE_LIMITED")

        checkpoint = json.loads(
            (root / "checkpoint.json").read_text(encoding="utf-8")
        )
        self.assertEqual(checkpoint["schema_version"], 6)
        self.assertEqual(len(checkpoint["attempts"]), 1)
        self.assertEqual(
            checkpoint["attempts_sha256"],
            hashlib.sha256(canonical_json_bytes(checkpoint["attempts"])).hexdigest(),
        )
        reports = refresh_campaign_reports(plan, root / "checkpoint.json")
        self.assertEqual(len(reports.resource_failure_rows), 1)
        failure_row = reports.resource_failure_rows[0]
        self.assertEqual(failure_row["leaf_id"], incident.leaf_id)
        self.assertEqual(failure_row["mode"], "221")
        self.assertEqual(failure_row["precision_digits"], 80)
        self.assertEqual(failure_row["phase"], "PRIMARY")
        self.assertEqual(failure_row["determinant_count"], 3)
        self.assertEqual(failure_row["failure_code"], "ODE_RESOURCE_LIMIT")
        self.assertEqual(failure_row["limiting_resource"], "rhs_evaluations")
        self.assertEqual(failure_row["ode_rejected_steps"], 0)
        self.assertEqual(failure_row["rhs_evaluations"], 1960000)
        self.assertEqual(failure_row["retry_status"], "DEFERRED")
        self.assertTrue(
            (root / "checkpoint.reports" / "m02-resource-failures.csv").is_file()
        )
        status = json.loads(
            (root / "checkpoint.json.status.json").read_text(encoding="utf-8")
        )
        self.assertEqual(len(status["resource_failures"]), 1)
        self.assertEqual(
            status["resource_failures"][0]["failure_code"],
            "ODE_RESOURCE_LIMIT",
        )
        self.assertNotEqual(
            status["resource_failures"][0].get("terminal_state"),
            "PRODUCED",
        )

    def test_worker_timeout_is_durable_and_next_leaf_executes(self):
        run = self._run_with_failure(
            julia_backend.JuliaWorkerTimeoutError,
            "WORKER_TIMEOUT",
            timed_out=True,
        )
        temporary, _, _, _, incident, following, backend, store, summary = run
        self.addCleanup(temporary.cleanup)

        records = {record.leaf_id: record for record in summary.records}
        self.assertFalse(records[incident.leaf_id].to_mapping()["computed"])
        self.assertEqual(records[following.leaf_id].state, "PRODUCED")
        self.assertIn((following.leaf_id, 64), backend.calls)
        self.assertEqual(store.stored_count, 1)
        self.assertEqual(summary.attempts[0].failure_code, "WORKER_TIMEOUT")
        self.assertEqual(summary.attempts[0].state, "WORKER_TIMEOUT")

    def test_every_numerical_control_failure_is_durably_contained(self):
        for code in sorted(julia_backend.NUMERICAL_CONTROL_FAILURE_CODES):
            with self.subTest(code=code):
                run = self._run_with_failure(
                    julia_backend.JuliaNumericalControlError,
                    code,
                )
                (
                    temporary,
                    root,
                    plan,
                    _,
                    incident,
                    following,
                    backend,
                    store,
                    summary,
                ) = run
                self.addCleanup(temporary.cleanup)

                records = {item.leaf_id: item for item in summary.records}
                self.assertEqual(summary.attempts[0].failure_code, code)
                self.assertEqual(
                    summary.attempts[0].state, "NUMERICAL_CONTROL_FAILURE"
                )
                self.assertEqual(records[following.leaf_id].state, "PRODUCED")
                self.assertIn((following.leaf_id, 64), backend.calls)
                self.assertIs(
                    records[incident.leaf_id].to_mapping()["computed"],
                    code == "INSUFFICIENT_ASYMPTOTIC_PRECISION",
                )

                persisted = summary.attempts[0].failure_receipt["failure"]
                self.assertEqual(persisted["failure_code"], code)
                self.assertEqual(
                    persisted["execution_resource_policy"]["sha256"],
                    persisted["request_binding"]["execution_resource"][
                        "sha256"
                    ],
                )
                decision = persisted["promotion_decision"]
                self.assertEqual(
                    decision["state"],
                    (
                        "REQUESTED"
                        if code == "INSUFFICIENT_ASYMPTOTIC_PRECISION"
                        else "SUPPRESSED"
                    ),
                )
                self.assertEqual(decision["reason"], code)
                if code == "INSUFFICIENT_ASYMPTOTIC_PRECISION":
                    self.assertIn((incident.leaf_id, 120), backend.calls)
                    self.assertEqual(records[incident.leaf_id].state, "PRODUCED")
                    self.assertEqual(store.stored_count, 2)
                    imported_store = SolvedLeafStore(root / "imported-solved")
                    imported = import_campaign_checkpoint_to_solved_leaf_store(
                        plan,
                        root / "checkpoint.json",
                        imported_store,
                    )
                    self.assertEqual(imported.imported_count, 2)
                    self.assertEqual(imported_store.stored_count, 2)
                else:
                    self.assertNotIn((incident.leaf_id, 120), backend.calls)
                if code == "INSUFFICIENT_ASYMPTOTIC_PRECISION":
                    self.assertEqual(
                        decision["predicted_reliable_digits"],
                        "11.25000000000000000001",
                    )
                    self.assertEqual(
                        decision["required_reliable_digits"], "24"
                    )
                    self.assertIs(
                        decision["asymptotic_preflight_avoided_ode"], True
                    )
                reloaded = validate_campaign_checkpoint(
                    plan, root / "checkpoint.json"
                )
                self.assertEqual(
                    reloaded.attempts[0].to_mapping(),
                    summary.attempts[0].to_mapping(),
                )

    def test_insufficient_preflight_uses_authenticated_120_refinement_path(self):
        plan, capabilities, _, incident, _ = self._plan_and_leaves()
        selection = build_campaign_selection(
            plan, role="primary", leaf_ids=(incident.leaf_id,)
        )
        failure = self._failure(
            julia_backend.JuliaNumericalControlError,
            "INSUFFICIENT_ASYMPTOTIC_PRECISION",
            leaf=incident,
        )

        class Backend:
            identity = plan.backend_identity
            precision_capabilities = capabilities

            def __init__(self):
                self.calls = []

            def execute_stage(self, leaf, digits):
                self.calls.append(("ordinary", digits))
                if digits == 64:
                    return _authenticated_primary_stage(
                        leaf, digits, ComponentStatus.NOT_CONVERGED
                    )
                raise failure

            def execute_promoted_stage_after_failed_preflight(
                self, leaf, digits, predecessor
            ):
                self.calls.append(("failed-preflight", digits))
                return _authenticated_failed_preflight_recovery_stage(
                    leaf, predecessor
                )

        with tempfile.TemporaryDirectory() as temporary:
            checkpoint = Path(temporary) / "checkpoint.json"
            backend = Backend()
            summary = run_campaign_selection(
                plan,
                selection,
                backend,
                checkpoint,
                resume=False,
            )
            reloaded = validate_campaign_checkpoint(plan, checkpoint)

        self.assertEqual(
            backend.calls,
            [("ordinary", 64), ("ordinary", 80), ("failed-preflight", 120)],
        )
        self.assertEqual(summary.state, "COMPLETE")
        self.assertEqual(summary.records[0].state, "PRODUCED")
        self.assertEqual(
            tuple(stage.outcome.digits for stage in summary.records[0].stages),
            (64, 120),
        )
        recovered = summary.records[0].stages[-1].outcome
        self.assertIsNone(recovered.discrepancy_from_previous_abs)
        self.assertIsNone(recovered.discrepancy_enclosed)
        self.assertEqual(
            recovered.component_result["comparison_kind"],
            "same-precision-120-base-vs-refinement/v1",
        )
        self.assertIs(
            recovered.component_result[
                "precision_ladder_discrepancy_applicable"
            ],
            False,
        )
        precision_channel = next(
            channel
            for channel in recovered.signed_error_channels
            if channel["family"] == "precision-ladder-discrepancy"
        )
        self.assertEqual(
            precision_channel["provenance"]["derivation"],
            "not-applicable-precision-ladder-discrepancy",
        )
        self.assertEqual(
            precision_channel["signed_delta"],
            {"real": 0.0, "imaginary": 0.0},
        )
        self.assertEqual(
            recovered.component_result["failed_preflight_predecessor"],
            summary.attempts[0].to_mapping(),
        )
        self.assertEqual(
            reloaded.records[0].to_mapping(),
            summary.records[0].to_mapping(),
        )

    def test_failed_preflight_resume_requests_only_missing_120_precision(self):
        plan, _, _, incident, _ = self._plan_and_leaves()
        selection = build_campaign_selection(
            plan, role="primary", leaf_ids=(incident.leaf_id,)
        )
        failure = self._failure(
            julia_backend.JuliaNumericalControlError,
            "INSUFFICIENT_ASYMPTOTIC_PRECISION",
            leaf=incident,
        )

        class InitialBackend:
            identity = plan.backend_identity
            precision_capabilities = PrecisionCapabilities((64, 80))

            def __init__(self):
                self.calls = []

            def execute_stage(self, leaf, digits):
                self.calls.append(digits)
                if digits == 64:
                    return _authenticated_primary_stage(
                        leaf, digits, ComponentStatus.NOT_CONVERGED
                    )
                raise failure

        class ResumeBackend:
            identity = plan.backend_identity
            precision_capabilities = PrecisionCapabilities((64, 80, 120))

            def __init__(self):
                self.calls = []

            def execute_stage(self, _leaf, digits):
                self.calls.append(("unexpected-ordinary", digits))
                raise AssertionError("resume must not repeat the 80-digit stage")

            def execute_promoted_stage_after_failed_preflight(
                self, leaf, digits, predecessor
            ):
                self.calls.append(("failed-preflight", digits))
                return _authenticated_failed_preflight_recovery_stage(
                    leaf, predecessor
                )

        with tempfile.TemporaryDirectory() as temporary:
            checkpoint = Path(temporary) / "checkpoint.json"
            initial_backend = InitialBackend()
            first = run_campaign_selection(
                plan,
                selection,
                initial_backend,
                checkpoint,
                resume=False,
            )
            self.assertEqual(first.records[0].state, "MISSING_PRECISION")
            self.assertEqual(first.records[0].missing_precision_digits, 120)
            self.assertEqual(initial_backend.calls, [64, 80])

            resume_backend = ResumeBackend()
            resumed = run_campaign_selection(
                plan,
                selection,
                resume_backend,
                checkpoint,
                resume=True,
            )

        self.assertEqual(
            resume_backend.calls, [("failed-preflight", 120)]
        )
        self.assertEqual(resumed.state, "COMPLETE")
        self.assertEqual(resumed.records[0].state, "PRODUCED")
        self.assertEqual(
            tuple(stage.outcome.digits for stage in resumed.records[0].stages),
            (64, 120),
        )

    def test_failed_preflight_recovery_fails_closed_at_each_terminal_gate(self):
        def base_limited(outcome):
            return _condition_failed_preflight_result(
                outcome,
                "result",
                predicted_reliable_digits="11",
                precision_limited=True,
            )

        def refinement_limited(outcome):
            return _condition_failed_preflight_result(
                outcome,
                "self_refinement_result",
                predicted_reliable_digits="11",
                precision_limited=True,
            )

        def refinement_not_converged(outcome):
            component = dict(outcome.component_result)
            refinement = ComponentResult.from_mapping(
                component["self_refinement_result"]
            )
            component["self_refinement_result"] = replace(
                refinement,
                status=ComponentStatus.NOT_CONVERGED,
                convergence_basis="UNRESOLVED",
                response=None,
                signed_root_crosscheck=None,
                closed_form_response=None,
            ).to_mapping()
            component["same_precision_refinement_discrepancy_abs"] = 0.0
            return _reseal_failed_preflight_recovery_stage(
                outcome, component, self_refinement_enclosed=False
            )

        def refinement_unenclosed(outcome):
            component = dict(outcome.component_result)
            base = ComponentResult.from_mapping(component["result"])
            refinement = ComponentResult.from_mapping(
                component["self_refinement_result"]
            )
            shifted_response = base.response + complex(1.0, 0.0)
            component["self_refinement_result"] = replace(
                refinement,
                response=shifted_response,
                signed_root_crosscheck=shifted_response,
            ).to_mapping()
            component["same_precision_refinement_discrepancy_abs"] = 1.0
            return _reseal_failed_preflight_recovery_stage(
                outcome, component, self_refinement_enclosed=False
            )

        for label, mutate in (
            ("base-conditioning", base_limited),
            ("refinement-conditioning", refinement_limited),
            ("refinement-nonconverged", refinement_not_converged),
            ("delta-unenclosed", refinement_unenclosed),
        ):
            with self.subTest(label=label):
                plan, capabilities, _, incident, _ = self._plan_and_leaves()
                selection = build_campaign_selection(
                    plan, role="primary", leaf_ids=(incident.leaf_id,)
                )
                failure = self._failure(
                    julia_backend.JuliaNumericalControlError,
                    "INSUFFICIENT_ASYMPTOTIC_PRECISION",
                    leaf=incident,
                )

                class Backend:
                    identity = plan.backend_identity
                    precision_capabilities = capabilities

                    def execute_stage(self, leaf, digits):
                        if digits == 64:
                            return _authenticated_primary_stage(
                                leaf, digits, ComponentStatus.NOT_CONVERGED
                            )
                        raise failure

                    def execute_promoted_stage_after_failed_preflight(
                        self, leaf, digits, predecessor
                    ):
                        outcome = _authenticated_failed_preflight_recovery_stage(
                            leaf, predecessor
                        )
                        return mutate(outcome)

                with tempfile.TemporaryDirectory() as temporary:
                    checkpoint = Path(temporary) / f"{label}.json"
                    summary = run_campaign_selection(
                        plan,
                        selection,
                        Backend(),
                        checkpoint,
                        resume=False,
                    )
                    reloaded = validate_campaign_checkpoint(plan, checkpoint)

                self.assertEqual(summary.records[0].state, "UNRESOLVED")
                self.assertEqual(reloaded.records[0].state, "UNRESOLVED")
                self.assertIsNone(_produced_response(summary.records[0]))

    def test_failed_preflight_recovery_rejects_forged_refinement_runtime(self):
        plan, capabilities, _, incident, _ = self._plan_and_leaves()
        selection = build_campaign_selection(
            plan, role="primary", leaf_ids=(incident.leaf_id,)
        )
        failure = self._failure(
            julia_backend.JuliaNumericalControlError,
            "INSUFFICIENT_ASYMPTOTIC_PRECISION",
            leaf=incident,
        )

        class Backend:
            identity = plan.backend_identity
            precision_capabilities = capabilities

            def execute_stage(self, leaf, digits):
                if digits == 64:
                    return _authenticated_primary_stage(
                        leaf, digits, ComponentStatus.NOT_CONVERGED
                    )
                raise failure

            def execute_promoted_stage_after_failed_preflight(
                self, leaf, digits, predecessor
            ):
                outcome = _authenticated_failed_preflight_recovery_stage(
                    leaf, predecessor
                )
                component = dict(outcome.component_result)
                runtime = dict(
                    component["self_refinement_scientific_runtime"]
                )
                runtime["worker_sha256"] = "f" * 64
                component["self_refinement_scientific_runtime"] = runtime
                return _reseal_failed_preflight_recovery_stage(
                    outcome, component
                )

        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(ValueError, "paired runtime identity"):
                run_campaign_selection(
                    plan,
                    selection,
                    Backend(),
                    Path(temporary) / "forged-runtime.json",
                    resume=False,
                )

    def test_failed_preflight_recovery_authenticates_embedded_and_refinement_evidence(self):
        def missing_predecessor(component):
            component.pop("failed_preflight_predecessor")

        def forged_refinement_readout(component):
            component["self_refinement_result"]["baseline"]["branch_id"] = (
                "forged-branch"
            )

        def forged_predecessor_code(component):
            predecessor = component["failed_preflight_predecessor"]
            predecessor["failure_code"] = "SCATTERING_BASIS_ILL_CONDITIONED"
            predecessor["failure_receipt"]["failure"]["failure_code"] = (
                "SCATTERING_BASIS_ILL_CONDITIONED"
            )
            predecessor["attempt_sha256"] = hashlib.sha256(
                canonical_json_bytes({
                    key: value
                    for key, value in predecessor.items()
                    if key != "attempt_sha256"
                })
            ).hexdigest()

        def fake_cross_precision_evidence(component):
            component["precision80_result"] = component["result"]
            component["cross_precision_discrepancy_abs"] = 0.0

        for label, mutate, message in (
            (
                "missing-predecessor",
                missing_predecessor,
                "recovery component fields",
            ),
            (
                "forged-predecessor-code",
                forged_predecessor_code,
                "receipt numerical-control diagnostics|predecessor identity",
            ),
            (
                "fake-cross-precision-evidence",
                fake_cross_precision_evidence,
                "recovery component fields",
            ),
            (
                "forged-refinement-readout",
                forged_refinement_readout,
                "readout lineage",
            ),
        ):
            with self.subTest(label=label):
                plan, capabilities, _, incident, _ = self._plan_and_leaves()
                selection = build_campaign_selection(
                    plan, role="primary", leaf_ids=(incident.leaf_id,)
                )
                failure = self._failure(
                    julia_backend.JuliaNumericalControlError,
                    "INSUFFICIENT_ASYMPTOTIC_PRECISION",
                    leaf=incident,
                )

                class Backend:
                    identity = plan.backend_identity
                    precision_capabilities = capabilities

                    def execute_stage(self, leaf, digits):
                        if digits == 64:
                            return _authenticated_primary_stage(
                                leaf, digits, ComponentStatus.NOT_CONVERGED
                            )
                        raise failure

                    def execute_promoted_stage_after_failed_preflight(
                        self, leaf, digits, predecessor
                    ):
                        outcome = _authenticated_failed_preflight_recovery_stage(
                            leaf, predecessor
                        )
                        component = json.loads(json.dumps(
                            outcome.component_result
                        ))
                        mutate(component)
                        return _reseal_failed_preflight_recovery_stage(
                            outcome, component
                        )

                with tempfile.TemporaryDirectory() as temporary:
                    with self.assertRaisesRegex(ValueError, message):
                        run_campaign_selection(
                            plan,
                            selection,
                            Backend(),
                            Path(temporary) / f"{label}.json",
                            resume=False,
                        )

    def test_failed_preflight_120_control_failure_remains_partial(self):
        plan, capabilities, _, incident, _ = self._plan_and_leaves()
        selection = build_campaign_selection(
            plan, role="primary", leaf_ids=(incident.leaf_id,)
        )
        failure80 = self._failure(
            julia_backend.JuliaNumericalControlError,
            "INSUFFICIENT_ASYMPTOTIC_PRECISION",
            leaf=incident,
        )
        failure120 = self._failure(
            julia_backend.JuliaODEResourceLimitError,
            "ODE_RESOURCE_LIMIT",
            leaf=incident,
            precision_digits=120,
        )

        class Backend:
            identity = plan.backend_identity
            precision_capabilities = capabilities

            def execute_stage(self, leaf, digits):
                if digits == 64:
                    return _authenticated_primary_stage(
                        leaf, digits, ComponentStatus.NOT_CONVERGED
                    )
                raise failure80

            def execute_promoted_stage_after_failed_preflight(
                self, leaf, digits, predecessor
            ):
                raise failure120

        with tempfile.TemporaryDirectory() as temporary:
            checkpoint = Path(temporary) / "failed-120.json"
            summary = run_campaign_selection(
                plan,
                selection,
                Backend(),
                checkpoint,
                resume=False,
            )
            reloaded = validate_campaign_checkpoint(plan, checkpoint)

        self.assertEqual(summary.state, "PARTIAL")
        self.assertEqual(summary.records[0].state, "IN_PROGRESS")
        self.assertEqual(
            tuple(stage.outcome.digits for stage in summary.records[0].stages),
            (64,),
        )
        self.assertEqual(
            [attempt.precision_digits for attempt in summary.attempts],
            [80, 120],
        )
        self.assertEqual(
            [attempt.attempt_sha256 for attempt in reloaded.attempts],
            [attempt.attempt_sha256 for attempt in summary.attempts],
        )

    def test_deep_failed_preflight_recovery_preserves_sentinel_audit_boundary(self):
        capabilities = PrecisionCapabilities((64, 80, 120))
        plan = build_campaign_plan(
            policy=NumericalPolicy(),
            backend_identity=VettedNativeDeterminantKernel.identity,
            precision_capabilities=capabilities,
        )
        sentinel_ids = set(
            B_PRIME_RELEASE_DOMAIN.fixed_precision_sentinel_leaf_ids
        )
        leaves = (
            next(
                leaf for leaf in plan.leaves
                if leaf.role == "deep" and leaf.leaf_id not in sentinel_ids
            ),
            next(leaf for leaf in plan.leaves if leaf.leaf_id in sentinel_ids),
        )
        for leaf in leaves:
            with self.subTest(leaf_id=leaf.leaf_id):
                selection = build_campaign_selection(
                    plan, role="deep", leaf_ids=(leaf.leaf_id,)
                )
                failure = self._failure(
                    julia_backend.JuliaNumericalControlError,
                    "INSUFFICIENT_ASYMPTOTIC_PRECISION",
                    leaf=leaf,
                )

                class Backend:
                    identity = plan.backend_identity
                    precision_capabilities = capabilities

                    def execute_stage(self, selected, digits):
                        if digits == 64:
                            return replace(
                                _authenticated_primary_stage(
                                    selected,
                                    digits,
                                    ComponentStatus.NOT_CONVERGED,
                                ),
                                deep_diagnostics=diagnostics(digits=8.0),
                            )
                        raise failure

                    def execute_promoted_stage_after_failed_preflight(
                        self, selected, digits, predecessor
                    ):
                        return _branch_safe_failed_preflight_recovery_stage(
                            _authenticated_failed_preflight_recovery_stage(
                                selected, predecessor
                            ),
                            selected,
                        )

                with tempfile.TemporaryDirectory() as temporary:
                    checkpoint = Path(temporary) / "deep-recovery.json"
                    summary = run_campaign_selection(
                        plan,
                        selection,
                        Backend(),
                        checkpoint,
                        resume=False,
                    )
                    reloaded = validate_campaign_checkpoint(plan, checkpoint)

                is_sentinel = leaf.leaf_id in sentinel_ids
                expected_state = "UNRESOLVED" if is_sentinel else "PRODUCED"
                self.assertEqual(summary.records[0].state, expected_state)
                self.assertEqual(reloaded.records[0].state, expected_state)
                self.assertIs(summary.records[0].sentinel, is_sentinel)
                self.assertIsNone(summary.records[0].sentinel_comparison)

    def test_invalid_asymptotic_failure_diagnostics_are_not_contained(self):
        cases = {
            "false_avoided": lambda failure: failure["diagnostics"].update(
                {"asymptotic_preflight_avoided_ode": False}
            ),
            "wrong_reason": lambda failure: failure["diagnostics"].update(
                {"asymptotic_preflight_reason": "ADEQUATE"}
            ),
            "inconsistent_digits": lambda failure: failure["diagnostics"].update(
                {
                    "predicted_reliable_digits": "24",
                    "required_reliable_digits": "24",
                }
            ),
            "wrong_retryability": lambda failure: failure.update(
                {"retryable": False}
            ),
            "wrong_source_precision": lambda failure: failure.update(
                {"precision_digits": 64}
            ),
            "wrong_job": lambda failure: failure.update(
                {"job_id": "forged-job"}
            ),
            "wrong_policy": lambda failure: failure.update(
                {"job_policy_sha256": "f" * 64}
            ),
            "wrong_refinement": lambda failure: failure.update(
                {"refinement_level": 1}
            ),
            "rhs_already_evaluated": lambda failure: failure[
                "diagnostics"
            ].update({"factored_homogeneous_rhs_evaluations": 1}),
        }
        for label, mutate in cases.items():
            with self.subTest(label=label):
                plan, capabilities, selection, incident, _ = (
                    self._plan_and_leaves()
                )
                failure = self._failure(
                    julia_backend.JuliaNumericalControlError,
                    "INSUFFICIENT_ASYMPTOTIC_PRECISION",
                    leaf=incident,
                )
                mutate(failure.worker_failure["failure"])

                class Backend:
                    identity = plan.backend_identity
                    precision_capabilities = capabilities

                    def execute_stage(self, leaf, digits):
                        if leaf.leaf_id == incident.leaf_id and digits == 64:
                            return _authenticated_primary_stage(
                                leaf, digits, ComponentStatus.NOT_CONVERGED
                            )
                        raise failure

                with tempfile.TemporaryDirectory() as temporary:
                    with self.assertRaises((
                        julia_backend.JuliaNumericalControlError,
                        ValueError,
                    )):
                        run_campaign_selection(
                            plan,
                            selection,
                            Backend(),
                            Path(temporary) / "invalid-control.json",
                            resume=False,
                        )

    def test_nonretryable_control_cannot_claim_retryability(self):
        plan, capabilities, selection, incident, _ = self._plan_and_leaves()
        failure = self._failure(
            julia_backend.JuliaNumericalControlError,
            "SCATTERING_BASIS_ILL_CONDITIONED",
        )
        failure.worker_failure["failure"]["retryable"] = True

        class Backend:
            identity = plan.backend_identity
            precision_capabilities = capabilities

            def execute_stage(self, leaf, digits):
                if leaf.leaf_id == incident.leaf_id and digits == 64:
                    return _authenticated_primary_stage(
                        leaf, digits, ComponentStatus.NOT_CONVERGED
                    )
                raise failure

        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaises(julia_backend.JuliaNumericalControlError):
                run_campaign_selection(
                    plan,
                    selection,
                    Backend(),
                    Path(temporary) / "invalid-retryability.json",
                    resume=False,
                )

    def test_reloaded_asymptotic_attempt_revalidates_diagnostics(self):
        run = self._run_with_failure(
            julia_backend.JuliaNumericalControlError,
            "INSUFFICIENT_ASYMPTOTIC_PRECISION",
        )
        temporary, root, plan, _, _, _, _, _, _ = run
        self.addCleanup(temporary.cleanup)
        checkpoint = root / "checkpoint.json"
        forged = json.loads(checkpoint.read_text(encoding="utf-8"))
        attempt = forged["attempts"][0]
        attempt["failure_receipt"]["failure"]["diagnostics"][
            "asymptotic_preflight_reason"
        ] = "ADEQUATE"
        attempt["attempt_sha256"] = hashlib.sha256(
            canonical_json_bytes({
                key: value
                for key, value in attempt.items()
                if key != "attempt_sha256"
            })
        ).hexdigest()
        forged["attempts_sha256"] = hashlib.sha256(
            canonical_json_bytes(forged["attempts"])
        ).hexdigest()
        checkpoint.write_bytes(canonical_json_bytes(forged))

        with self.assertRaisesRegex(ValueError, "attempt receipt"):
            validate_campaign_checkpoint(plan, checkpoint)

    def test_reloaded_preflight_attempt_rejects_valid_but_wrong_request_sha(self):
        plan, _, _, incident, _ = self._plan_and_leaves()
        selection = build_campaign_selection(
            plan, role="primary", leaf_ids=(incident.leaf_id,)
        )
        failure = self._failure(
            julia_backend.JuliaNumericalControlError,
            "INSUFFICIENT_ASYMPTOTIC_PRECISION",
            leaf=incident,
        )

        class Backend:
            identity = plan.backend_identity
            precision_capabilities = PrecisionCapabilities((64, 80))

            def execute_stage(self, leaf, digits):
                if digits == 64:
                    return _authenticated_primary_stage(
                        leaf, digits, ComponentStatus.NOT_CONVERGED
                    )
                raise failure

        with tempfile.TemporaryDirectory() as temporary:
            checkpoint = Path(temporary) / "checkpoint.json"
            run_campaign_selection(
                plan, selection, Backend(), checkpoint, resume=False
            )
            forged = json.loads(checkpoint.read_text(encoding="utf-8"))
            attempt = forged["attempts"][0]
            attempt["failure_receipt"]["failure"]["request_sha256"] = (
                "0" * 64
            )
            attempt["attempt_sha256"] = hashlib.sha256(
                canonical_json_bytes({
                    key: value
                    for key, value in attempt.items()
                    if key != "attempt_sha256"
                })
            ).hexdigest()
            forged["attempts_sha256"] = hashlib.sha256(
                canonical_json_bytes(forged["attempts"])
            ).hexdigest()
            checkpoint.write_bytes(canonical_json_bytes(forged))

            with self.assertRaisesRegex(
                ValueError, "digest disagrees with canonical binding"
            ):
                validate_campaign_checkpoint(plan, checkpoint)

    def test_reloaded_preflight_attempt_rejects_resealed_nested_request_policy(self):
        plan, _, _, incident, _ = self._plan_and_leaves()
        selection = build_campaign_selection(
            plan, role="primary", leaf_ids=(incident.leaf_id,)
        )
        failure = self._failure(
            julia_backend.JuliaNumericalControlError,
            "INSUFFICIENT_ASYMPTOTIC_PRECISION",
            leaf=incident,
        )

        class Backend:
            identity = plan.backend_identity
            precision_capabilities = PrecisionCapabilities((64, 80))

            def execute_stage(self, leaf, digits):
                if digits == 64:
                    return _authenticated_primary_stage(
                        leaf, digits, ComponentStatus.NOT_CONVERGED
                    )
                raise failure

        with tempfile.TemporaryDirectory() as temporary:
            checkpoint = Path(temporary) / "checkpoint.json"
            run_campaign_selection(
                plan, selection, Backend(), checkpoint, resume=False
            )
            forged = json.loads(checkpoint.read_text(encoding="utf-8"))
            attempt = forged["attempts"][0]
            receipt = attempt["failure_receipt"]["failure"]
            receipt["request_binding"]["policy"][
                "root_correction_tolerance"
            ] = "9e-18"
            receipt["request_sha256"] = hashlib.sha256(
                canonical_json_bytes(receipt["request_binding"])
            ).hexdigest()
            attempt["attempt_sha256"] = hashlib.sha256(
                canonical_json_bytes({
                    key: value
                    for key, value in attempt.items()
                    if key != "attempt_sha256"
                })
            ).hexdigest()
            forged["attempts_sha256"] = hashlib.sha256(
                canonical_json_bytes(forged["attempts"])
            ).hexdigest()
            checkpoint.write_bytes(canonical_json_bytes(forged))

            with self.assertRaisesRegex(
                ValueError, "canonical request contract"
            ):
                validate_campaign_checkpoint(plan, checkpoint)

    def test_reloaded_preflight_attempt_rejects_resealed_exterior_support(self):
        plan, _, _, _, _ = self._plan_and_leaves()
        leaf = next(
            item for item in plan.leaves
            if item.role == "primary"
            and item.mechanism_id != "horizon-admittance"
        )
        selection = build_campaign_selection(
            plan, role="primary", leaf_ids=(leaf.leaf_id,)
        )
        failure = self._failure(
            julia_backend.JuliaNumericalControlError,
            "INSUFFICIENT_ASYMPTOTIC_PRECISION",
            leaf=leaf,
        )

        class Backend:
            identity = plan.backend_identity
            precision_capabilities = PrecisionCapabilities((64, 80))

            def execute_stage(self, selected, digits):
                if digits == 64:
                    return _authenticated_primary_stage(
                        selected, digits, ComponentStatus.NOT_CONVERGED
                    )
                raise failure

        with tempfile.TemporaryDirectory() as temporary:
            checkpoint = Path(temporary) / "checkpoint.json"
            run_campaign_selection(
                plan, selection, Backend(), checkpoint, resume=False
            )
            forged = json.loads(checkpoint.read_text(encoding="utf-8"))
            attempt = forged["attempts"][0]
            receipt = attempt["failure_receipt"]["failure"]
            support = receipt["request_binding"]["support"]
            first_name = next(iter(support))
            support[first_name] = "9"
            receipt["request_sha256"] = hashlib.sha256(
                canonical_json_bytes(receipt["request_binding"])
            ).hexdigest()
            attempt["attempt_sha256"] = hashlib.sha256(
                canonical_json_bytes({
                    key: value
                    for key, value in attempt.items()
                    if key != "attempt_sha256"
                })
            ).hexdigest()
            forged["attempts_sha256"] = hashlib.sha256(
                canonical_json_bytes(forged["attempts"])
            ).hexdigest()
            checkpoint.write_bytes(canonical_json_bytes(forged))

            with self.assertRaisesRegex(
                ValueError, "canonical request contract"
            ):
                validate_campaign_checkpoint(plan, checkpoint)

    def test_reloaded_recovery_rejects_one_ulp_discrepancy_tamper(self):
        run = self._run_with_failure(
            julia_backend.JuliaNumericalControlError,
            "INSUFFICIENT_ASYMPTOTIC_PRECISION",
        )
        temporary, root, plan, _, incident, _, _, _, _ = run
        self.addCleanup(temporary.cleanup)
        checkpoint = root / "checkpoint.json"
        forged = json.loads(checkpoint.read_text(encoding="utf-8"))
        record = next(
            item for item in forged["records"]
            if item["leaf_id"] == incident.leaf_id
        )
        stage = record["stages"][-1]
        component = stage["component_result"]
        recorded = component["same_precision_refinement_discrepancy_abs"]
        component["same_precision_refinement_discrepancy_abs"] = math.nextafter(
            recorded, math.inf
        )
        source_sha256 = hashlib.sha256(
            canonical_json_bytes(component)
        ).hexdigest()
        for channel in stage["signed_error_channels"]:
            channel["provenance"]["source_sha256"] = source_sha256
        reseal(forged)
        checkpoint.write_bytes(canonical_json_bytes(forged))

        with self.assertRaisesRegex(
            ValueError, "same-precision discrepancy disagrees"
        ):
            validate_campaign_checkpoint(plan, checkpoint)

    def test_malformed_typed_or_unknown_worker_failure_remains_fail_closed(self):
        plan, capabilities, selection, incident, _ = self._plan_and_leaves()
        malformed = julia_backend.JuliaODEResourceLimitError("malformed")
        malformed.worker_failure = {
            "worker_exit_code": 1,
            "worker_timed_out": False,
            "worker_stderr_tail": "bad receipt",
            "worker_error_type": "Synthetic",
            "worker_error_message": "missing structured failure",
        }

        class Backend:
            identity = plan.backend_identity
            precision_capabilities = capabilities

            def execute_stage(self, leaf, digits):
                if leaf.leaf_id == incident.leaf_id and digits == 64:
                    return _authenticated_primary_stage(
                        leaf, digits, ComponentStatus.NOT_CONVERGED
                    )
                raise malformed

        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaises(julia_backend.JuliaODEResourceLimitError):
                run_campaign_selection(
                    plan,
                    selection,
                    Backend(),
                    Path(temporary) / "checkpoint.json",
                    resume=False,
                )

        unknown = julia_backend.JuliaResponseBackendError("unknown worker failure")

        class UnknownBackend(Backend):
            def execute_stage(self, leaf, digits):
                if leaf.leaf_id == incident.leaf_id and digits == 64:
                    return _authenticated_primary_stage(
                        leaf, digits, ComponentStatus.NOT_CONVERGED
                    )
                raise unknown

        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaises(julia_backend.JuliaResponseBackendError):
                run_campaign_selection(
                    plan,
                    selection,
                    UnknownBackend(),
                    Path(temporary) / "checkpoint.json",
                    resume=False,
                )

    def test_resume_retries_deferred_leaf_without_recomputing_completed_leaf(self):
        run = self._run_with_failure(
            julia_backend.JuliaRootReadoutResourceLimitError,
            "ROOT_READOUT_RESOURCE_INFEASIBLE",
        )
        temporary, root, plan, selection, incident, following, _, store, first = run
        self.addCleanup(temporary.cleanup)

        class RetryBackend:
            identity = plan.backend_identity
            precision_capabilities = plan.precision_capabilities

            def __init__(self):
                self.calls = []

            def execute_stage(self, leaf, digits):
                self.calls.append((leaf.leaf_id, digits))
                return _authenticated_primary_stage(
                    leaf,
                    digits,
                    ComponentStatus.CONVERGED,
                    self_refinement_enclosed=True,
                    discrepancy_from_previous_abs=1.0e-9,
                    discrepancy_enclosed=True,
                )

        retry = RetryBackend()
        resumed = run_campaign_selection(
            plan,
            selection,
            retry,
            root / "checkpoint.json",
            resume=True,
            solved_leaf_store=store,
        )

        self.assertEqual(first.state, "PARTIAL")
        self.assertEqual(resumed.state, "COMPLETE")
        self.assertEqual(retry.calls, [(incident.leaf_id, 80)])
        self.assertNotIn((following.leaf_id, 64), retry.calls)
        self.assertEqual(store.stored_count, 2)
        self.assertEqual(len(resumed.attempts), 1)

    def test_failed_retry_appends_without_overwriting_first_attempt(self):
        run = self._run_with_failure(
            julia_backend.JuliaRootReadoutResourceLimitError,
            "ROOT_READOUT_RESOURCE_INFEASIBLE",
        )
        temporary, root, plan, selection, incident, following, _, store, first = run
        self.addCleanup(temporary.cleanup)
        second_failure = self._failure(
            julia_backend.JuliaODEResourceLimitError,
            "ODE_RESOURCE_LIMIT",
        )

        class RetryBackend:
            identity = plan.backend_identity
            precision_capabilities = plan.precision_capabilities

            def __init__(self):
                self.calls = []

            def execute_stage(self, leaf, digits):
                self.calls.append((leaf.leaf_id, digits))
                raise second_failure

        backend = RetryBackend()
        retried = run_campaign_selection(
            plan,
            selection,
            backend,
            root / "checkpoint.json",
            resume=True,
            solved_leaf_store=store,
        )

        self.assertEqual(backend.calls, [(incident.leaf_id, 80)])
        self.assertNotIn((following.leaf_id, 64), backend.calls)
        self.assertEqual(len(retried.attempts), 2)
        self.assertEqual(
            retried.attempts[0].to_mapping(), first.attempts[0].to_mapping()
        )
        self.assertNotEqual(
            retried.attempts[0].attempt_sha256,
            retried.attempts[1].attempt_sha256,
        )

    def test_recovered_80_failure_can_be_followed_by_deferred_120_attempt(self):
        run = self._run_with_failure(
            julia_backend.JuliaRootReadoutResourceLimitError,
            "ROOT_READOUT_RESOURCE_INFEASIBLE",
        )
        temporary, root, plan, selection, incident, _, _, store, _ = run
        self.addCleanup(temporary.cleanup)
        failure120 = self._failure(
            julia_backend.JuliaODEResourceLimitError,
            "ODE_RESOURCE_LIMIT",
        )
        failure120.worker_failure["failure"]["precision_digits"] = 120

        class RetryBackend:
            identity = plan.backend_identity
            precision_capabilities = plan.precision_capabilities

            def execute_stage(self, leaf, digits):
                if digits == 80:
                    return _authenticated_primary_stage(
                        leaf,
                        digits,
                        ComponentStatus.CONVERGED,
                        self_refinement_enclosed=False,
                        discrepancy_from_previous_abs=1.0e-9,
                        discrepancy_enclosed=True,
                    )
                raise failure120

        retried = run_campaign_selection(
            plan,
            selection,
            RetryBackend(),
            root / "checkpoint.json",
            resume=True,
            solved_leaf_store=store,
        )
        reloaded = validate_campaign_checkpoint(
            plan,
            root / "checkpoint.json",
        )

        self.assertEqual(retried.state, "PARTIAL")
        self.assertEqual(retried.records[0].stages[-1].outcome.digits, 80)
        self.assertEqual(
            [attempt.precision_digits for attempt in retried.attempts],
            [80, 120],
        )
        self.assertEqual(
            [attempt.attempt_sha256 for attempt in reloaded.attempts],
            [attempt.attempt_sha256 for attempt in retried.attempts],
        )

    def test_attempt_content_digest_detects_tampering(self):
        run = self._run_with_failure(
            julia_backend.JuliaODEResourceLimitError,
            "ODE_RESOURCE_LIMIT",
        )
        temporary, root, plan, _, _, _, _, _, _ = run
        self.addCleanup(temporary.cleanup)
        checkpoint = root / "checkpoint.json"
        forged = json.loads(checkpoint.read_text(encoding="utf-8"))
        forged["attempts"][0]["failure_receipt"]["failure"][
            "limiting_resource"
        ] = "forged-limit"
        forged["attempts_sha256"] = hashlib.sha256(
            canonical_json_bytes(forged["attempts"])
        ).hexdigest()
        checkpoint.write_bytes(canonical_json_bytes(forged))

        with self.assertRaisesRegex(ValueError, "attempt digest"):
            validate_campaign_checkpoint(plan, checkpoint)

    def test_schema_version_3_checkpoint_remains_compatible(self):
        plan, capabilities, _, incident, _ = self._plan_and_leaves()
        selection = build_campaign_selection(
            plan, role="primary", leaf_ids=(incident.leaf_id,)
        )

        class Backend:
            identity = plan.backend_identity
            precision_capabilities = capabilities

            def execute_stage(self, leaf, digits):
                return _authenticated_primary_stage(
                    leaf, digits, ComponentStatus.CONVERGED
                )

        with tempfile.TemporaryDirectory() as temporary:
            checkpoint = Path(temporary) / "checkpoint.json"
            run_campaign_selection(
                plan, selection, Backend(), checkpoint, resume=False
            )
            legacy = json.loads(checkpoint.read_text(encoding="utf-8"))
            legacy["schema_version"] = 3
            legacy["bindings"]["precision_contract_sha256"] = (
                _checkpoint_precision_contract_sha256(3)
            )
            legacy.pop("attempts")
            legacy.pop("attempts_sha256")
            checkpoint.write_bytes(canonical_json_bytes(legacy))

            loaded = validate_campaign_checkpoint(plan, checkpoint)

        self.assertEqual(loaded.state, "COMPLETE")
        self.assertEqual(loaded.attempts, ())

    def test_incomplete_schema_five_checkpoint_cannot_resume_as_schema_six(self):
        plan, _, _, incident, _ = self._plan_and_leaves()
        selection = build_campaign_selection(
            plan, role="primary", leaf_ids=(incident.leaf_id,)
        )

        class InitialBackend:
            identity = plan.backend_identity
            precision_capabilities = PrecisionCapabilities((64,))

            def execute_stage(self, leaf, digits):
                self.assert_digits = digits
                return _authenticated_primary_stage(
                    leaf, digits, ComponentStatus.NOT_CONVERGED
                )

        class ResumeBackend:
            identity = plan.backend_identity
            precision_capabilities = PrecisionCapabilities((64, 80, 120))

            def execute_stage(self, _leaf, _digits):
                raise AssertionError("historical partial resume must not execute")

        with tempfile.TemporaryDirectory() as temporary:
            checkpoint = Path(temporary) / "checkpoint.json"
            run_campaign_selection(
                plan,
                selection,
                InitialBackend(),
                checkpoint,
                resume=False,
            )
            historical = json.loads(checkpoint.read_text(encoding="utf-8"))
            historical["schema_version"] = 5
            historical["bindings"]["precision_contract_sha256"] = (
                _checkpoint_precision_contract_sha256(5)
            )
            checkpoint.write_bytes(canonical_json_bytes(historical))

            readable = validate_campaign_checkpoint(plan, checkpoint)
            self.assertEqual(readable.state, "PARTIAL")
            with self.assertRaisesRegex(
                ValueError,
                "incomplete historical campaign checkpoint.*fresh checkpoint",
            ):
                run_campaign_selection(
                    plan,
                    selection,
                    ResumeBackend(),
                    checkpoint,
                    resume=True,
                )
            with self.assertRaisesRegex(
                ValueError, "incomplete historical campaign checkpoint.*merged"
            ):
                merge_campaign_checkpoints(
                    plan,
                    (checkpoint,),
                    Path(temporary) / "merged.json",
                )
            with self.assertRaisesRegex(
                ValueError,
                "incomplete historical campaign checkpoint.*publish",
            ):
                import_campaign_checkpoint_to_solved_leaf_store(
                    plan,
                    checkpoint,
                    SolvedLeafStore(Path(temporary) / "solved"),
                )

    def test_component_status_body_contract_is_enforced_at_every_primary_tier(self) -> None:
        """Catches sealed status/body contradictions accepted as production."""

        capabilities = PrecisionCapabilities((64, 80, 120))
        plan = build_campaign_plan(
            policy=NumericalPolicy(),
            backend_identity=VettedNativeDeterminantKernel.identity,
            precision_capabilities=capabilities,
        )
        leaf = next(item for item in plan.leaves if item.role == "primary")
        selection = build_campaign_selection(
            plan, role="primary", leaf_ids=(leaf.leaf_id,)
        )
        contradictions = (
            (
                "converged-response-null",
                ComponentStatus.CONVERGED,
                {"response": None},
                {},
            ),
            (
                "converged-signed-root-null",
                ComponentStatus.CONVERGED,
                {"signed_root_crosscheck": None},
                {},
            ),
            (
                "converged-basis-unresolved",
                ComponentStatus.CONVERGED,
                {"convergence_basis": "UNRESOLVED"},
                {},
            ),
            (
                "converged-claims-unusable",
                ComponentStatus.CONVERGED,
                {},
                {"usable": False},
            ),
            (
                "unresolved-response-present",
                ComponentStatus.NOT_CONVERGED,
                {"response": complex(1.0, -0.5)},
                {},
            ),
            (
                "unresolved-signed-root-present",
                ComponentStatus.NOT_CONVERGED,
                {"signed_root_crosscheck": complex(1.0, -0.5)},
                {},
            ),
            (
                "unresolved-closed-form-present",
                ComponentStatus.NOT_CONVERGED,
                {"closed_form_response": complex(1.0, -0.5)},
                {},
            ),
            (
                "unresolved-basis-resolved",
                ComponentStatus.NOT_CONVERGED,
                {"convergence_basis": "ORDER_RESOLVED"},
                {},
            ),
            (
                "unresolved-claims-usable",
                ComponentStatus.NOT_CONVERGED,
                {},
                {"usable": True},
            ),
        )

        for digits in (64, 80, 120):
            for name, status, result_changes, raw_changes in contradictions:
                with self.subTest(digits=digits, contradiction=name), tempfile.TemporaryDirectory() as temporary:
                    class Backend:
                        identity = plan.backend_identity
                        precision_capabilities = capabilities

                        def execute_stage(self, selected, current_digits):
                            if current_digits == digits:
                                target = _authenticated_primary_stage(
                                    selected,
                                    current_digits,
                                    status,
                                    self_refinement_enclosed=(
                                        False if current_digits == 80 else None
                                    ),
                                    discrepancy_from_previous_abs=(
                                        1.0e-9 if current_digits > 64 else None
                                    ),
                                    discrepancy_enclosed=(
                                        True if current_digits > 64 else None
                                    ),
                                )
                                return _replace_component_result_fields(
                                    target,
                                    result_changes=result_changes,
                                    raw_changes=raw_changes,
                                )
                            if current_digits == 64:
                                return _authenticated_primary_stage(
                                    selected,
                                    current_digits,
                                    ComponentStatus.NOT_CONVERGED,
                                )
                            if current_digits == 80:
                                return _authenticated_primary_stage(
                                    selected,
                                    current_digits,
                                    ComponentStatus.CONVERGED,
                                    self_refinement_enclosed=False,
                                    discrepancy_from_previous_abs=1.0e-9,
                                    discrepancy_enclosed=True,
                                )
                            return _authenticated_primary_stage(
                                selected,
                                current_digits,
                                ComponentStatus.CONVERGED,
                                discrepancy_from_previous_abs=1.0e-10,
                                discrepancy_enclosed=True,
                            )

                    with self.assertRaisesRegex(
                        ValueError,
                        "component result.*status|component result.*canonical",
                    ):
                        run_campaign_selection(
                            plan,
                            selection,
                            Backend(),
                            Path(temporary) / "contradiction.json",
                            resume=False,
                        )

    def test_primary_terminal_component_statuses_and_control_never_promote(self) -> None:
        """Catches the PRIMARY ladder promoting scientific terminal statuses."""

        capabilities = PrecisionCapabilities((64, 80, 120))
        plan = build_campaign_plan(
            policy=NumericalPolicy(),
            backend_identity=VettedNativeDeterminantKernel.identity,
            precision_capabilities=capabilities,
        )
        for role, status, terminal_state in (
            ("primary", ComponentStatus.CONVERGED, "PRODUCED"),
            ("primary", ComponentStatus.BRANCH_LOSS, "UNRESOLVED"),
            ("primary", ComponentStatus.NOISE_FLOOR, "UNRESOLVED"),
            ("primary", ComponentStatus.AXIS_MISMATCH, "UNRESOLVED"),
            ("control", ComponentStatus.NOT_CONVERGED, "UNRESOLVED"),
        ):
            leaf = next(item for item in plan.leaves if item.role == role)
            selection = build_campaign_selection(
                plan, role=role, leaf_ids=(leaf.leaf_id,)
            )

            class Backend:
                identity = plan.backend_identity
                precision_capabilities = capabilities

                def __init__(self):
                    self.calls = []

                def execute_stage(self, selected, digits):
                    self.calls.append(digits)
                    return _authenticated_primary_stage(selected, digits, status)

            with self.subTest(role=role, status=status.value), tempfile.TemporaryDirectory() as temporary:
                backend = Backend()
                root = Path(temporary)
                checkpoint = root / "terminal.json"
                store = (
                    SolvedLeafStore(root / "solved")
                    if status is ComponentStatus.BRANCH_LOSS
                    else None
                )
                summary = run_campaign_selection(
                    plan,
                    selection,
                    backend,
                    checkpoint,
                    resume=False,
                    solved_leaf_store=store,
                )
                self.assertEqual(backend.calls, [64])
                self.assertEqual(summary.records[0].state, terminal_state)
                self.assertEqual(
                    validate_campaign_checkpoint(plan, checkpoint).records,
                    summary.records,
                )
                if terminal_state == "PRODUCED":
                    self.assertEqual(
                        _produced_response(summary.records[0]),
                        complex(1.0, -0.5),
                    )
                if store is not None:
                    self.assertEqual(store.stored_count, 1)

        mislabeled_leaf = next(
            item for item in plan.leaves if item.role == "primary"
        )
        mislabeled_selection = build_campaign_selection(
            plan, role="primary", leaf_ids=(mislabeled_leaf.leaf_id,)
        )

        class MislabeledBranchLossBackend:
            identity = plan.backend_identity
            precision_capabilities = capabilities

            def execute_stage(self, selected, digits):
                return _authenticated_primary_stage(
                    selected,
                    digits,
                    ComponentStatus.BRANCH_LOSS,
                    branch_loss_mismatch=False,
                )

        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(ValueError, "lacks an identity mismatch"):
                run_campaign_selection(
                    plan,
                    mislabeled_selection,
                    MislabeledBranchLossBackend(),
                    Path(temporary) / "mislabeled-branch-loss.json",
                    resume=False,
                )


class DeepPrecisionTests(unittest.TestCase):
    def test_missing_precision_is_partial_and_resumes_with_superset_backend(self) -> None:
        plan = build_campaign_plan(
            policy=NumericalPolicy(),
            backend_identity=VettedNativeDeterminantKernel.identity,
            precision_capabilities=PrecisionCapabilities((64, 80)),
        )
        selection = build_campaign_selection(
            plan, role="deep", leaf_ids=(SENTINEL,)
        )

        class Backend:
            identity = plan.backend_identity

            def __init__(self, available):
                self.precision_capabilities = PrecisionCapabilities(available)
                self.calls = []

            def execute_stage(self, leaf, digits):
                self.calls.append((leaf.leaf_id, digits))
                if digits == 64:
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
                        local_disk_radius_abs=1.0e-6,
                        deep_diagnostics=diagnostics(),
                    )
                return _synthetic_stage_outcome(
                    digits=80,
                    numerical_state="CONVERGED",
                    component_result={
                        "evidence_kind": "synthetic-orchestration-contract",
                        "leaf_id": leaf.leaf_id,
                        "role": leaf.role,
                        "mechanism_id": leaf.mechanism_id,
                        "digits": 80,
                    },
                    local_disk_radius_abs=1.0e-6,
                    self_refinement_enclosed=True,
                    discrepancy_from_previous_abs=1.0e-8,
                    discrepancy_enclosed=True,
                )

        with tempfile.TemporaryDirectory() as temporary:
            checkpoint = Path(temporary) / "resume.json"
            binary64 = Backend((64,))
            partial = run_campaign_selection(
                plan, selection, binary64, checkpoint, resume=False
            )
            self.assertEqual(partial.state, "PARTIAL")
            self.assertEqual(partial.records[0].state, "MISSING_PRECISION")
            self.assertEqual(binary64.calls, [(SENTINEL, 64)])

            promoted = Backend((64, 80))
            complete = run_campaign_selection(
                plan, selection, promoted, checkpoint, resume=True
            )
            self.assertEqual(complete.state, "COMPLETE")
            self.assertEqual(complete.records[0].state, "PRODUCED")
            self.assertEqual(promoted.calls, [(SENTINEL, 80)])

    def test_resealed_sentinel64_and_inconsistent_state_are_rejected(self) -> None:
        capabilities = PrecisionCapabilities((64,))
        plan = build_campaign_plan(
            policy=NumericalPolicy(),
            backend_identity=VettedNativeDeterminantKernel.identity,
            precision_capabilities=capabilities,
        )
        selection = build_campaign_selection(
            plan, role="deep", leaf_ids=(SENTINEL,)
        )

        class Backend:
            identity = plan.backend_identity
            precision_capabilities = capabilities

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
                    local_disk_radius_abs=1.0e-6,
                    deep_diagnostics=diagnostics(),
                )

        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            checkpoint = directory / "checkpoint.json"
            run_campaign_selection(
                plan, selection, Backend(), checkpoint, resume=False
            )
            original = json.loads(checkpoint.read_text(encoding="utf-8"))
            for name, state in (
                ("sentinel64", "PRODUCED"),
                ("inconsistent", "UNRESOLVED"),
            ):
                forged = json.loads(json.dumps(original))
                forged["records"][0]["state"] = state
                forged["records"][0]["computed"] = True
                forged["state"] = "COMPLETE"
                forged["records"][0]["missing_precision_digits"] = None
                reseal(forged)
                path = directory / f"{name}.json"
                path.write_bytes(canonical_json_bytes(forged))
                with self.subTest(name=name), self.assertRaises(ValueError):
                    validate_campaign_checkpoint(plan, path)

    def test_sentinel_and_triggered_120_ladders_are_exact(self) -> None:
        capabilities = PrecisionCapabilities((64, 80, 120))
        plan = build_campaign_plan(
            policy=NumericalPolicy(),
            backend_identity=VettedNativeDeterminantKernel.identity,
            precision_capabilities=capabilities,
        )
        selected = tuple(
            leaf.leaf_id
            for leaf in plan.leaves
            if leaf.leaf_id in {SENTINEL, PROMOTED_120}
        )
        selection = build_campaign_selection(plan, role="deep", leaf_ids=selected)

        class Backend:
            identity = plan.backend_identity
            precision_capabilities = capabilities

            def __init__(self):
                self.calls = []

            def execute_stage(self, leaf, digits):
                self.calls.append((leaf.leaf_id, digits))
                common = {
                    "digits": digits,
                    "numerical_state": "CONVERGED",
                    "component_result": {
                        "kind": "deterministic-contract",
                        "leaf_id": leaf.leaf_id,
                        "digits": digits,
                    },
                    "local_disk_radius_abs": 1.0e-6,
                }
                if digits == 64:
                    return _synthetic_stage_outcome(
                        **common,
                        deep_diagnostics=diagnostics(
                            digits=8.0 if leaf.leaf_id == PROMOTED_120 else 12.0
                        ),
                    )
                if digits == 80:
                    return _synthetic_stage_outcome(
                        **common,
                        self_refinement_enclosed=leaf.leaf_id == SENTINEL,
                        discrepancy_from_previous_abs=1.0e-8,
                        discrepancy_enclosed=leaf.leaf_id == SENTINEL,
                    )
                return _synthetic_stage_outcome(
                    **common,
                    discrepancy_from_previous_abs=1.0e-9,
                    discrepancy_enclosed=True,
                )

        with tempfile.TemporaryDirectory() as temporary:
            backend = Backend()
            summary = run_campaign_selection(
                plan,
                selection,
                backend,
                Path(temporary) / "deep.json",
                resume=False,
            )
        by_id = {record.leaf_id: record for record in summary.records}
        self.assertEqual(
            tuple(stage.outcome.digits for stage in by_id[SENTINEL].stages),
            (64, 80),
        )
        self.assertTrue(by_id[SENTINEL].sentinel)
        self.assertEqual(
            tuple(stage.outcome.digits for stage in by_id[PROMOTED_120].stages),
            (64, 80, 120),
        )
        self.assertEqual(
            by_id[PROMOTED_120].trigger_ids,
            (B_PRIME_RELEASE_DOMAIN.precision_promotion_gates[0],),
        )
        self.assertTrue(all(record.state == "PRODUCED" for record in summary.records))

    def test_missing_precision_and_diagnostics_fail_closed(self) -> None:
        capabilities = PrecisionCapabilities((64,))
        plan = build_campaign_plan(
            policy=NumericalPolicy(),
            backend_identity=VettedNativeDeterminantKernel.identity,
            precision_capabilities=capabilities,
        )
        selection = build_campaign_selection(
            plan, role="deep", leaf_ids=(MISSING_PRECISION,)
        )

        class Backend:
            identity = plan.backend_identity
            precision_capabilities = capabilities

            def __init__(self, with_diagnostics):
                self.with_diagnostics = with_diagnostics

            def execute_stage(self, leaf, digits):
                return _synthetic_stage_outcome(
                    digits=digits,
                    numerical_state="NOT_CONVERGED",
                    component_result={"leaf_id": leaf.leaf_id},
                    local_disk_radius_abs=1.0e-6,
                    deep_diagnostics=(
                        diagnostics(digits=8.0) if self.with_diagnostics else None
                    ),
                )

        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            missing = run_campaign_selection(
                plan, selection, Backend(True), directory / "missing.json", resume=False
            )
            self.assertEqual(missing.records[0].state, "MISSING_PRECISION")
            self.assertEqual(missing.records[0].missing_precision_digits, 80)
            self.assertFalse(missing.records[0].to_mapping()["computed"])
            with self.assertRaisesRegex(ValueError, "deep diagnostics"):
                run_campaign_selection(
                    plan,
                    selection,
                    Backend(False),
                    directory / "diagnostics.json",
                    resume=False,
                )


if __name__ == "__main__":
    unittest.main()
