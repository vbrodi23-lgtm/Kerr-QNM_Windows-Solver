from __future__ import annotations

from dataclasses import replace
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from windows_solver.contracts import canonical_json_bytes
from windows_solver.linear_response import B_PRIME_RELEASE_DOMAIN
from windows_solver.response_batches import (
    PrecisionCapabilities,
    StageOutcome,
    _primary_recovery_precision_contract,
    _root_convergence_precision_contract,
    _produced_response,
    build_campaign_plan,
    build_campaign_selection,
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
    RootReadout,
    VettedNativeDeterminantKernel,
)
from windows_solver.solved_leaf_cache import SolvedLeafStore


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
