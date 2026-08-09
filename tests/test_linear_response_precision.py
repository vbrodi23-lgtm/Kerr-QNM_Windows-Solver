from __future__ import annotations

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
    build_campaign_plan,
    build_campaign_selection,
    run_campaign_selection,
    synthetic_stage_signed_error_channels,
    validate_campaign_checkpoint,
)
from windows_solver.response_engine import NumericalPolicy, VettedNativeDeterminantKernel


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

    def test_resume_passes_authenticated_prior_outcomes_to_promoted_backend(self) -> None:
        binary64_capabilities = PrecisionCapabilities((64,))
        promoted_capabilities = PrecisionCapabilities((64, 80))
        plan = build_campaign_plan(
            policy=NumericalPolicy(),
            backend_identity=VettedNativeDeterminantKernel.identity,
            precision_capabilities=binary64_capabilities,
        )
        selection = build_campaign_selection(
            plan, role="deep", leaf_ids=(SENTINEL,)
        )

        class Binary64Backend:
            identity = plan.backend_identity
            precision_capabilities = binary64_capabilities

            def execute_stage(self, leaf, digits):
                return _synthetic_stage_outcome(
                    digits=digits,
                    numerical_state="CONVERGED",
                    component_result={"leaf_id": leaf.leaf_id, "digits": digits},
                    local_disk_radius_abs=1.0e-6,
                    deep_diagnostics=diagnostics(digits=12.0),
                )

        class PromotedBackend:
            identity = plan.backend_identity
            precision_capabilities = promoted_capabilities

            def __init__(self):
                self.previous = None

            def execute_stage(self, leaf, digits):
                raise AssertionError("promoted resume lost its prior-stage boundary")

            def execute_promoted_stage(self, leaf, digits, previous_outcomes):
                self.previous = previous_outcomes
                return _synthetic_stage_outcome(
                    digits=digits,
                    numerical_state="CONVERGED",
                    component_result={"leaf_id": leaf.leaf_id, "digits": digits},
                    local_disk_radius_abs=1.0e-8,
                    self_refinement_enclosed=True,
                    discrepancy_from_previous_abs=2.0e-8,
                    discrepancy_enclosed=True,
                )

        with tempfile.TemporaryDirectory() as temporary:
            checkpoint = Path(temporary) / "promoted-resume.json"
            run_campaign_selection(
                plan, selection, Binary64Backend(), checkpoint, resume=False
            )
            promoted = PromotedBackend()
            completed = run_campaign_selection(
                plan, selection, promoted, checkpoint, resume=True
            )

        self.assertEqual(completed.state, "COMPLETE")
        self.assertIsNotNone(promoted.previous)
        self.assertEqual(tuple(stage.digits for stage in promoted.previous), (64,))
        self.assertEqual(
            promoted.previous[0].component_result["leaf_id"], SENTINEL
        )

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
