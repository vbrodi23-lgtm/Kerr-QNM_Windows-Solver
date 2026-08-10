from __future__ import annotations

import csv
import hashlib
from pathlib import Path
import tempfile
import unittest

from windows_solver.campaign_reports import refresh_campaign_reports
from windows_solver.contracts import canonical_json_bytes
from windows_solver.response_batches import (
    CampaignLeafRecord,
    CampaignStageRecord,
    PrecisionCapabilities,
    StageOutcome,
    _checkpoint_mapping,
    build_campaign_plan,
    build_campaign_selection,
    explicit_stage_signed_error_channels,
)
from windows_solver.response_engine import (
    ComponentResult,
    ComponentStatus,
    ERROR_CHANNELS,
    NumericalPolicy,
    RootReadout,
    VettedNativeDeterminantKernel,
)


class CampaignReportTests(unittest.TestCase):
    def _plan(self):
        return build_campaign_plan(
            policy=NumericalPolicy(),
            backend_identity=VettedNativeDeterminantKernel.identity,
            precision_capabilities=PrecisionCapabilities((64,)),
        )

    @staticmethod
    def _produced_record(plan, leaf):
        job = leaf.job
        response = complex(1.25, -0.5)
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
                "signed-root": 2.0e-9,
                "truncation": 3.0e-9,
                "resolution": 4.0e-9,
                "seed-path": 5.0e-9,
                "axis": 6.0e-9,
                "amplitude": 7.0e-9,
            },
            baseline=RootReadout(
                omega=job.root.omega,
                determinant_residual_abs=1.42e-11,
                determinant_derivative_abs=1.0,
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
        family_deltas = {
            "signed-root": complex(1.0e-8, -2.0e-8),
            "centred-step-amplitude": 0.0j,
            "refinement-holdout": 0.0j,
            "truncation": 0.0j,
            "resolution-angular-refinement": 0.0j,
            "continuation-seed-path": 0.0j,
            "repeat-polish": 0.0j,
            "precision-ladder-discrepancy": 0.0j,
        }
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
        return CampaignLeafRecord(
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

    def test_refresh_projects_committed_checkpoint_without_mutating_it(self):
        """Catches absent or nondeterministic audit projections of committed science."""

        plan = self._plan()
        leaf = plan.leaves[0]
        record = self._produced_record(plan, leaf)
        selection = build_campaign_selection(
            plan, role="primary", leaf_ids=(leaf.leaf_id,)
        )

        with tempfile.TemporaryDirectory() as temporary:
            checkpoint = Path(temporary) / "m02-campaign-checkpoint.json"
            checkpoint.write_bytes(canonical_json_bytes(
                _checkpoint_mapping(plan, selection, (record,))
            ))
            original_checkpoint = checkpoint.read_bytes()

            refresh_campaign_reports(
                plan,
                checkpoint,
                run_provenance={leaf.leaf_id: "EXECUTED"},
            )

            report_directory = (
                Path(temporary) / "m02-campaign-checkpoint.reports"
            )
            leaves_path = report_directory / "m02-leaves.csv"
            channels_path = report_directory / "m02-error-channels.csv"
            projective_path = report_directory / "m02-projective.csv"
            self.assertTrue(leaves_path.is_file())
            self.assertTrue(channels_path.is_file())
            self.assertTrue(projective_path.is_file())
            self.assertEqual(checkpoint.read_bytes(), original_checkpoint)

            with leaves_path.open(newline="", encoding="utf-8") as handle:
                leaves = list(csv.DictReader(handle))
            self.assertEqual(len(leaves), 212)
            current = next(item for item in leaves if item["leaf_id"] == leaf.leaf_id)
            self.assertEqual(current["terminal_state"], "PRODUCED")
            self.assertEqual(current["component_status"], "CONVERGED")
            self.assertEqual(current["convergence_basis"], "ORDER_RESOLVED")
            self.assertEqual(current["run_provenance"], "EXECUTED")
            self.assertEqual(float(current["response_real"]), 1.25)
            self.assertEqual(float(current["response_imaginary"]), -0.5)
            self.assertEqual(
                float(current["baseline_omega_real"]), leaf.job.root.omega.real
            )
            self.assertEqual(
                float(current["baseline_omega_imaginary"]),
                leaf.job.root.omega.imag,
            )
            self.assertEqual(
                float(current["baseline_determinant_residual"]), 1.42e-11
            )
            self.assertEqual(float(current["signed_root_crosscheck_real"]), 1.25)
            self.assertEqual(
                float(current["signed_root_crosscheck_imaginary"]), -0.5
            )
            pending = next(item for item in leaves if item["leaf_id"] != leaf.leaf_id)
            self.assertEqual(pending["terminal_state"], "PENDING")
            self.assertEqual(pending["response_real"], "")

            with channels_path.open(newline="", encoding="utf-8") as handle:
                channels = list(csv.DictReader(handle))
            self.assertEqual(len(channels), 8)
            self.assertEqual(
                tuple(item["family"] for item in channels),
                (
                    "signed-root",
                    "centred-step-amplitude",
                    "refinement-holdout",
                    "truncation",
                    "resolution-angular-refinement",
                    "continuation-seed-path",
                    "repeat-polish",
                    "precision-ladder-discrepancy",
                ),
            )
            self.assertTrue(all(
                item["source_receipt"]
                == "sha256:" + hashlib.sha256(original_checkpoint).hexdigest()
                for item in channels
            ))

            with projective_path.open(newline="", encoding="utf-8") as handle:
                projective = list(csv.DictReader(handle))
            self.assertEqual(len(projective), 57)
            self.assertEqual(projective[0]["reducer_state"], "INCOMPLETE")
            self.assertEqual(projective[0]["projective_outcome"], "")
            self.assertIn(leaf.leaf_id, projective[0]["present_component_ids"])
            self.assertTrue(projective[0]["missing_component_ids"])

            first_outputs = {
                path.name: path.read_bytes()
                for path in (leaves_path, channels_path, projective_path)
            }
            refresh_campaign_reports(
                plan,
                checkpoint,
                run_provenance={leaf.leaf_id: "EXECUTED"},
            )
            self.assertEqual(
                {
                    path.name: path.read_bytes()
                    for path in (leaves_path, channels_path, projective_path)
                },
                first_outputs,
            )


if __name__ == "__main__":
    unittest.main()
