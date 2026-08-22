from __future__ import annotations

from fractions import Fraction
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from windows_solver.contracts import canonical_json_bytes
from windows_solver.linear_response import B_PRIME_RELEASE_DOMAIN
from windows_solver.response_batches import (
    CampaignLeafRecord,
    CampaignStageRecord,
    PrecisionCapabilities,
    StageOutcome,
    _checkpoint_mapping,
    build_campaign_plan,
    build_campaign_selection,
    explicit_stage_signed_error_channels,
    _with_inferred_legacy_evidence,
)
from windows_solver.response_engine import (
    ComponentResult,
    ComponentStatus,
    DiagnosticRootReadout,
    ERROR_CHANNELS,
    LadderLevel,
    NumericalPolicy,
    RootReadout,
    VettedNativeDeterminantKernel,
)
from windows_solver.response_reduction import (
    CampaignReductionSummary,
    EMPIRICAL_GRAM_KIND,
    ComputedUnresolvedComponentEvidence,
    ResolvedComponentEvidence,
    SignedErrorContribution,
    build_projective_row_plans,
    reduce_projective_row,
    reduce_projective_rows,
)


class ProjectiveRowPlanTests(unittest.TestCase):
    @staticmethod
    def resolved_components(
        plan: object,
        left: tuple[complex, complex, complex],
        right: tuple[complex, complex, complex],
        *,
        family: str,
        shared_group: str,
        scale: float = 1.0e-7,
    ) -> dict[str, ResolvedComponentEvidence]:
        component_ids = (*plan.left_component_ids, *plan.right_component_ids)
        centres = (*left, *right)
        receipt = "sha256:" + "5" * 64
        return {
            component_id: ResolvedComponentEvidence(
                component_id=component_id,
                centre=centre,
                units="synthetic-dimensionless-response",
                contributions=(SignedErrorContribution(
                    channel_id=f"shared:{family}:{shared_group}",
                    family=family,
                    shared_group=shared_group,
                    delta=complex(scale * (index + 1), -0.5 * scale * (index + 1)),
                    units="synthetic-dimensionless-response",
                    source_receipt=receipt,
                    scope="shared",
                ),),
            )
            for index, (component_id, centre) in enumerate(zip(component_ids, centres))
        }

    def test_exact_frozen_48_primary_and_9_deep_rows_are_enumerated_only(self) -> None:
        plans = build_projective_row_plans()

        self.assertEqual(len(plans), 57)
        self.assertEqual(tuple(plan.row_id for plan in plans), B_PRIME_RELEASE_DOMAIN.projective_row_ids)
        self.assertEqual(sum(plan.role == "primary" for plan in plans), 48)
        self.assertEqual(sum(plan.role == "deep" for plan in plans), 9)
        self.assertFalse(any(plan.role == "control" for plan in plans))

        head = plans[0]
        self.assertEqual(head.row_id, "primary-K0-19-20-exterior-fixed-r3")
        self.assertEqual(head.mode_labels, ("220", "330", "440"))
        self.assertEqual(head.coordinate, Fraction(19, 20))
        self.assertEqual(head.left_mechanism_id, "horizon-admittance")
        self.assertEqual(head.right_mechanism_id, "exterior-fixed-r3")
        self.assertEqual(head.calibration_mode_label, "220")
        self.assertEqual(head.calibration_component_ids, (head.left_component_ids[0], head.right_component_ids[0]))
        self.assertEqual(head.empirical_gram_kind, EMPIRICAL_GRAM_KIND)
        self.assertEqual(head.separation_lower_radians, 1.0e-2)
        self.assertEqual(head.equivalence_upper_radians, 1.0e-3)

        deep = next(
            plan
            for plan in plans
            if plan.row_id == "deep-K22-1-1000-exterior-throat-kappa"
        )
        self.assertEqual(deep.mode_labels, ("220", "221", "222"))
        self.assertEqual(deep.coordinate_role, "M-kappa")
        self.assertEqual(deep.evidence_ceiling, "exploratory-near-extremal")
        self.assertEqual(len(set((*deep.left_component_ids, *deep.right_component_ids))), 6)

    def test_deep_tail_missing_promoted_precision_is_explicitly_incomplete(self) -> None:
        plan = next(
            plan
            for plan in build_projective_row_plans()
            if plan.row_id == "deep-K22-1-1000-exterior-throat-kappa"
        )

        result = reduce_projective_row(plan, {}, source_hashes=("sha256:" + "4" * 64,))

        self.assertEqual(result.reducer_state, "INCOMPLETE")
        self.assertEqual(result.present_component_ids, ())
        self.assertEqual(
            result.missing_component_ids,
            (*plan.left_component_ids, *plan.right_component_ids),
        )
        self.assertIsNone(result.projective_outcome)
        self.assertIsNone(result.scientific_state)
        self.assertIsNone(result.nominal_angle_radians)
        self.assertIsNone(result.bounded_angle_interval_radians)

    def test_primary_head_shared_continuation_reduces_to_separated(self) -> None:
        plan = build_projective_row_plans()[0]
        components = self.resolved_components(
            plan,
            (1.0 + 0.0j, 0.0 + 0.0j, 0.0 + 0.0j),
            (1.0 + 0.0j, 1.0 + 0.0j, 0.0 + 0.0j),
            family="continuation-seed-path",
            shared_group="synthetic-head-root",
        )

        result = reduce_projective_row(
            plan, components, source_hashes=("sha256:" + "6" * 64,)
        )

        self.assertEqual(result.reducer_state, "COMPLETE")
        self.assertEqual(result.projective_outcome, "SEPARATED")
        self.assertEqual(result.scientific_state, "CONTRADICTED")
        self.assertGreater(result.bounded_angle_interval_radians[0], 1.0e-2)
        self.assertIsNotNone(result.empirical_gram_id)

    def test_summary_owns_complete_recomputable_empirical_gram(self) -> None:
        """Catches omitted Gram evidence and resealed numeric/metadata tamper."""

        plan = build_projective_row_plans()[0]
        components = self.resolved_components(
            plan,
            (1.0 + 0.0j, 2.0 + 0.0j, 3.0 + 0.0j),
            (1.0 + 0.0j, 2.5 + 0.0j, 4.0 + 0.0j),
            family="continuation-seed-path",
            shared_group="summary-gram-root",
        )
        summary = reduce_projective_rows(
            "campaign-summary-gram",
            (plan.row_id,),
            components,
            source_hashes=("sha256:" + "6" * 64,),
        )
        mapping = summary.to_mapping()
        gram = mapping["empirical_grams"][0]
        self.assertEqual(gram["construction_id"], summary.results[0].empirical_gram_id)
        self.assertEqual(
            set(gram),
            {
                "kind", "basis", "channel_ids", "channel_families", "columns",
                "matrix", "units", "local_marginals", "local_disks",
                "construction_id", "source_hashes",
            },
        )
        self.assertEqual(len(gram["local_marginals"]), 6)
        self.assertEqual(CampaignReductionSummary.from_mapping(mapping), summary)

        for name, mutate in (
            ("column", lambda item: item["columns"][0].__setitem__(0, 9.0)),
            ("matrix", lambda item: item["matrix"][0].__setitem__(0, 9.0)),
            (
                "marginal",
                lambda item: item["local_marginals"][
                    plan.left_component_ids[0]
                ][0].__setitem__(0, 9.0),
            ),
        ):
            forged = json.loads(json.dumps(mapping))
            forged_gram = forged["empirical_grams"][0]
            mutate(forged_gram)
            gram_material = {
                key: value
                for key, value in forged_gram.items()
                if key != "construction_id"
            }
            forged_gram["construction_id"] = "empirical-error-gram-" + hashlib.sha256(
                canonical_json_bytes(gram_material)
            ).hexdigest()
            summary_material = {
                key: value
                for key, value in forged.items()
                if key not in {"reduction_id", "release_admissible"}
            }
            forged["reduction_id"] = "b-prime-reduction-" + hashlib.sha256(
                canonical_json_bytes(summary_material)
            ).hexdigest()
            with self.subTest(name=name), self.assertRaisesRegex(
                ValueError, "Gram|gram|marginal|recomput"
            ):
                CampaignReductionSummary.from_mapping(forged)

    def test_primary_middle_correlated_refinement_reduces_to_equivalent(self) -> None:
        plan = next(
            plan
            for plan in build_projective_row_plans()
            if plan.row_id == "primary-K1-999-1000-exterior-alpha-half"
        )
        components = self.resolved_components(
            plan,
            (1.0 + 0.0j, 2.0 + 0.0j, 3.0 + 0.0j),
            (1.0 + 0.0j, 2.0 + 0.0j, 3.0001 + 0.0j),
            family="refinement-holdout",
            shared_group="synthetic-middle-refinement",
            scale=1.0e-9,
        )

        result = reduce_projective_row(
            plan, components, source_hashes=("sha256:" + "7" * 64,)
        )

        self.assertEqual(result.reducer_state, "COMPLETE")
        self.assertEqual(result.projective_outcome, "EQUIVALENT_WITHIN_TOLERANCE")
        self.assertEqual(result.scientific_state, "SUPPORTED")
        self.assertLess(result.bounded_angle_interval_radians[1], 1.0e-3)
        self.assertGreaterEqual(result.linearized_angle_gram, 0.0)

    def test_zero_containing_calibration_disk_forces_unbounded_unresolved(self) -> None:
        plan = build_projective_row_plans()[0]
        components = self.resolved_components(
            plan,
            (1.0 + 0.0j, 0.0 + 0.0j, 0.0 + 0.0j),
            (1.0 + 0.0j, 1.0 + 0.0j, 0.0 + 0.0j),
            family="centred-step-amplitude",
            shared_group="synthetic-zero-calibration",
            scale=1.0e-3,
        )
        denominator_id = plan.right_component_ids[0]
        components[denominator_id] = replace(
            components[denominator_id], centre=0.0 + 0.0j
        )

        result = reduce_projective_row(
            plan, components, source_hashes=("sha256:" + "8" * 64,)
        )

        self.assertEqual(result.reducer_state, "COMPLETE")
        self.assertTrue(result.calibration_disk_contains_zero)
        self.assertEqual(result.projective_outcome, "UNRESOLVED")
        self.assertEqual(result.scientific_state, "UNRESOLVED")
        self.assertIsNone(result.nominal_angle_radians)
        self.assertIsNone(result.bounded_angle_interval_radians)

    def test_computed_unresolved_component_remains_produced_and_propagates(self) -> None:
        plan = build_projective_row_plans()[0]
        components = self.resolved_components(
            plan,
            (1.0 + 0.0j, 0.0 + 0.0j, 0.0 + 0.0j),
            (1.0 + 0.0j, 1.0 + 0.0j, 0.0 + 0.0j),
            family="repeat-polish",
            shared_group="synthetic-unresolved-ledger",
        )
        unresolved_id = plan.left_component_ids[-1]
        resolved = components[unresolved_id]
        components[unresolved_id] = ComputedUnresolvedComponentEvidence(
            component_id=unresolved_id,
            units=resolved.units,
            contributions=resolved.contributions,
            reason="synthetic repeat-polish ceiling exceeded",
            source_receipt="sha256:" + "9" * 64,
        )

        result = reduce_projective_row(
            plan, components, source_hashes=("sha256:" + "a" * 64,)
        )

        self.assertEqual(result.reducer_state, "COMPLETE")
        self.assertEqual(result.produced_unresolved_component_ids, (unresolved_id,))
        self.assertEqual(result.projective_outcome, "UNRESOLVED")
        self.assertEqual(result.scientific_state, "UNRESOLVED")
        self.assertEqual(result.missing_component_ids, ())
        self.assertIsNone(result.empirical_gram_id)

    def test_campaign_reduce_cli_validates_checkpoint_and_is_partial_honest(self) -> None:
        plan = build_campaign_plan(
            policy=NumericalPolicy(),
            backend_identity=VettedNativeDeterminantKernel.identity,
            precision_capabilities=PrecisionCapabilities((64,)),
        )
        row = next(
            item
            for item in build_projective_row_plans()
            if item.row_id == "deep-K22-1-1000-exterior-throat-kappa"
        )
        selected_set = set((*row.left_component_ids, *row.right_component_ids))
        selected_ids = tuple(
            leaf.leaf_id for leaf in plan.leaves if leaf.leaf_id in selected_set
        )
        selection = build_campaign_selection(plan, role="deep", leaf_ids=selected_ids)
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            checkpoint = directory / "deep-tail-partial.json"
            checkpoint.write_bytes(
                canonical_json_bytes(_checkpoint_mapping(plan, selection, ()))
            )
            source_hash = "sha256:" + hashlib.sha256(checkpoint.read_bytes()).hexdigest()
            material = {
                "schema_version": 1,
                "campaign_id": plan.campaign_id,
                "backend_id": plan.backend_identity.backend_id,
                "precision_digits": [64],
                "precision_backend": None,
                "checkpoint_paths": [checkpoint.name],
                "selected_row_ids": [row.row_id],
                "component_evidence": [],
                "source_hashes": [source_hash],
            }
            bundle = {
                **material,
                "bundle_sha256": hashlib.sha256(canonical_json_bytes(material)).hexdigest(),
            }
            bundle_path = directory / "reduction-bundle.json"
            bundle_path.write_bytes(canonical_json_bytes(bundle))

            def invoke(*arguments: str) -> subprocess.CompletedProcess[str]:
                return subprocess.run(
                    [sys.executable, "-m", "windows_solver", *arguments],
                    cwd=directory,
                    env={"PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src")},
                    text=True,
                    capture_output=True,
                )

            reduced = invoke(
                "campaign-reduce", bundle_path.name, "--output", "partial-reduction.json"
            )
            self.assertEqual(reduced.returncode, 0, reduced.stderr)
            self.assertEqual(len(reduced.stdout.splitlines()), 1)
            output = json.loads(reduced.stdout)
            self.assertEqual(output["reducer_state"], "INCOMPLETE")
            self.assertEqual(output["selected_row_ids"], [row.row_id])
            self.assertEqual(output["results"][0]["projective_outcome"], None)
            self.assertFalse(output["release_admissible"])
            self.assertEqual(
                (directory / "partial-reduction.json").read_bytes(),
                canonical_json_bytes({key: value for key, value in output.items() if key != "command"}),
            )

            overwrite = invoke(
                "campaign-reduce", bundle_path.name, "--output", "partial-reduction.json"
            )
            self.assertEqual(overwrite.returncode, 2)
            unsafe = invoke(
                "campaign-reduce", bundle_path.name, "--output", "C:relative.json"
            )
            self.assertEqual(unsafe.returncode, 2)

            stale_material = {**material, "campaign_id": "b-prime-campaign-" + "0" * 64}
            stale = {
                **stale_material,
                "bundle_sha256": hashlib.sha256(
                    canonical_json_bytes(stale_material)
                ).hexdigest(),
            }
            bundle_path.write_bytes(canonical_json_bytes(stale))
            rejected = invoke(
                "campaign-reduce", bundle_path.name, "--output", "stale.json"
            )
            self.assertEqual(rejected.returncode, 2)
            self.assertFalse((directory / "stale.json").exists())

            bundle_path.write_text(
                '{"schema_version":1,"schema_version":1}', encoding="utf-8"
            )
            duplicate = invoke(
                "campaign-reduce", bundle_path.name, "--output", "duplicate.json"
            )
            self.assertEqual(duplicate.returncode, 2)

    def test_campaign_reduce_binds_centres_and_signed_channels_to_checkpoint(self) -> None:
        plan = build_campaign_plan(
            policy=NumericalPolicy(),
            backend_identity=VettedNativeDeterminantKernel.identity,
            precision_capabilities=PrecisionCapabilities((64,)),
        )
        row = build_projective_row_plans()[0]
        leaf = next(
            item for item in plan.leaves
            if item.leaf_id == row.left_component_ids[0]
        )
        job = leaf.job
        response = complex(1.25, -0.5)
        diagnostic_deltas = {
            "truncation": 0.0j,
            "resolution": 0.0j,
            "seed-path": 0.0j,
        }

        def signed_readout(amplitude):
            return RootReadout(
                omega=job.root.omega + response * amplitude,
                determinant_residual_abs=0.0,
                determinant_derivative_abs=1.0,
                converged=True,
                root_reference_id=job.root.root_reference_id,
                branch_id=job.root.branch_id,
                equation_id=job.equation_id,
                diagnostic_readouts={
                    family: DiagnosticRootReadout(
                        omega_delta_from_primary=delta,
                        determinant_residual_abs=0.0,
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
            status=ComponentStatus.CONVERGED,
            convergence_basis="ORDER_RESOLVED",
            response=response,
            signed_root_crosscheck=response,
            closed_form_response=None,
            error_channels={name: 0.0 for name in ERROR_CHANNELS},
            baseline=RootReadout(
                omega=job.root.omega,
                determinant_residual_abs=0.0,
                determinant_derivative_abs=1.0,
                converged=True,
                root_reference_id=job.root.root_reference_id,
                branch_id=job.root.branch_id,
                equation_id=job.equation_id,
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
                "source_root_mapping": None,
            },
        )
        component_result = {
            "evidence_kind": "authenticated-test-component",
            "result": result.to_mapping(),
        }
        family_deltas = {family: 0.0j for family in (
            "signed-root", "centred-step-amplitude", "refinement-holdout",
            "truncation", "resolution-angular-refinement",
            "continuation-seed-path", "repeat-polish",
            "precision-ladder-discrepancy",
        )}
        family_deltas["signed-root"] = complex(1.0e-8, -2.0e-8)
        stage = StageOutcome(
            digits=64,
            numerical_state="CONVERGED",
            component_result=component_result,
            local_disk_radius_abs=abs(family_deltas["signed-root"]),
            signed_error_channels=explicit_stage_signed_error_channels(
                component_result,
                family_deltas=family_deltas,
                source_kind="authenticated-test-component",
                source_id=job.job_id,
                units="M-delta-omega-per-native-coordinate",
            ),
        )
        record = CampaignLeafRecord(
            leaf_id=leaf.leaf_id,
            role=leaf.role,
            state="PRODUCED",
            stages=(CampaignStageRecord(stage, {
                "precision_factory_identity": (
                    plan.precision_factory_identity.to_mapping()
                ),
                "available_precision_digits": [64],
            }),),
        )
        record = _with_inferred_legacy_evidence(
            record,
            source_checkpoint_schema_version=9,
        )
        selection = build_campaign_selection(
            plan, role="primary", leaf_ids=(leaf.leaf_id,)
        )

        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            checkpoint = directory / "one-component.json"
            checkpoint.write_bytes(canonical_json_bytes(
                _checkpoint_mapping(plan, selection, (record,))
            ))
            source_receipt = (
                "sha256:" + hashlib.sha256(checkpoint.read_bytes()).hexdigest()
            )
            contributions = []
            for channel in stage.signed_error_channels:
                contributions.append({
                    "channel_id": f"local:{leaf.leaf_id}:{channel['family']}",
                    "family": channel["family"],
                    "shared_group": leaf.leaf_id,
                    "signed_delta": channel["signed_delta"],
                    "units": channel["units"],
                    "source_receipt": source_receipt,
                    "scope": channel["scope"],
                })
            component = {
                "evidence_state": "RESOLVED",
                "evidence_kind": "authenticated-campaign",
                "component_id": leaf.leaf_id,
                "centre": {"real": response.real, "imaginary": response.imag},
                "units": "M-delta-omega-per-native-coordinate",
                "contributions": contributions,
                "required_families": [item["family"] for item in contributions],
                "recorded_discrepancies": [],
            }

            def write_bundle(component_mapping: dict[str, object]) -> Path:
                material = {
                    "schema_version": 1,
                    "campaign_id": plan.campaign_id,
                    "backend_id": plan.backend_identity.backend_id,
                    "precision_digits": [64],
                    "precision_backend": None,
                    "checkpoint_paths": [checkpoint.name],
                    "selected_row_ids": [row.row_id],
                    "component_evidence": [component_mapping],
                    "source_hashes": [source_receipt],
                }
                bundle = {
                    **material,
                    "bundle_sha256": hashlib.sha256(
                        canonical_json_bytes(material)
                    ).hexdigest(),
                }
                path = directory / "reduction-bundle.json"
                path.write_bytes(canonical_json_bytes(bundle))
                return path

            def invoke(output: str) -> subprocess.CompletedProcess[str]:
                return subprocess.run(
                    [
                        sys.executable, "-m", "windows_solver",
                        "campaign-reduce", write_bundle(component).name,
                        "--output", output,
                    ],
                    cwd=directory,
                    env={
                        "PYTHONPATH": str(
                            Path(__file__).resolve().parents[1] / "src"
                        )
                    },
                    text=True,
                    capture_output=True,
                )

            accepted = invoke("accepted.json")
            self.assertEqual(accepted.returncode, 0, accepted.stderr)

            component["centre"]["real"] = 99.0
            corrupted_centre = invoke("corrupted-centre.json")
            self.assertEqual(corrupted_centre.returncode, 2)
            self.assertIn("checkpoint", corrupted_centre.stderr)
            component["centre"]["real"] = response.real

            component["contributions"][0]["signed_delta"]["real"] = 99.0
            corrupted_delta = invoke("corrupted-delta.json")
            self.assertEqual(corrupted_delta.returncode, 2)
            self.assertIn("checkpoint", corrupted_delta.stderr)


if __name__ == "__main__":
    unittest.main()
