"""PR69 Commit 10: v3 recovery excludes authenticated stale v2 responses."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

from windows_solver.campaign_policy import (
    EvidenceLevel,
    add_numerical_record,
    empty_schema11_checkpoint,
    record_evidence,
)
from windows_solver.campaign_recovery import (
    SCIENTIFIC_COMPATIBILITY_SCHEMA,
    STALE_HORIZON_REASON,
    RecoverySelection,
    recover_campaign,
    validate_recovery_checkpoint,
)
from windows_solver.campaign_record_intake import (
    assess_campaign_record_for_current_runtime,
)
from windows_solver.campaign_runtime import (
    build_schema11_horizon_record,
    build_schema11_horizon_stage,
)
from windows_solver.contracts import canonical_json_bytes
from windows_solver.native_response_kernel import VettedNativeDeterminantKernel
from windows_solver.response_batches import (
    NativeCampaignStageBackend,
    PrecisionCapabilities,
    build_campaign_plan,
    forensic_v2_scientific_computation_identity_sha256,
    scientific_computation_identity_sha256,
    validate_campaign_recovery_record,
)
from windows_solver.response_engine import DeterminantPartials, NumericalPolicy
from windows_solver.root_evidence import AuthenticatedRootEvidence


def _sha256(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _rehashed_stage(stage: dict[str, object]) -> None:
    stage["stage_sha256"] = _sha256(
        {key: value for key, value in stage.items() if key != "stage_sha256"}
    )


def _rehashed_record(record: dict[str, object]) -> None:
    record["record_sha256"] = _sha256(
        {key: value for key, value in record.items() if key != "record_sha256"}
    )


class Commit10RecoveryTests(unittest.TestCase):
    def _plan_and_leaf(self):
        plan = build_campaign_plan(
            policy=NumericalPolicy(),
            backend_identity=VettedNativeDeterminantKernel.identity,
            precision_capabilities=PrecisionCapabilities((64, 80)),
        )
        leaf = next(
            item
            for item in plan.leaves
            if item.role == "primary" and item.mechanism_id == "horizon-admittance"
        )
        return plan, leaf

    def _authenticated_v2_horizon_record(self, plan, leaf) -> dict[str, object]:
        root_evidence = AuthenticatedRootEvidence.from_authenticated_disk(
            leaf,
            fixed_root=leaf.job.root.omega,
            root_uncertainty_radius=1.0e-10,
            source_receipt_sha256="c" * 64,
            evidence_level="SCREENED",
        )
        horizon_radius = 1.0 + (1.0 - leaf.job.spin * leaf.job.spin) ** 0.5
        omega_h = leaf.job.spin / (2.0 * horizon_radius)
        p_h = leaf.job.root.omega - leaf.job.mode.m * omega_h

        class Kernel:
            identity = VettedNativeDeterminantKernel.identity

            def horizon_partials(self, **_kwargs):
                d_h = 3.0 - 2.0j
                d_omega = 5.0 + 7.0j
                return DeterminantPartials(
                    frequency_derivative=d_omega,
                    coordinate_derivative=d_h / (2.0j * p_h),
                    simple_root_valid=True,
                    frequency_derivative_error_abs=3.0e-10,
                    dD_dR=d_h,
                    dD_dR_error_abs=2.0e-10,
                    dD_ddeltaB=d_h / (2.0j * p_h),
                    dD_domega=d_omega,
                    dD_domega_error_abs=3.0e-10,
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
        outcome = backend.execute_horizon_stage(leaf, root_evidence=root_evidence)
        stage, _ = build_schema11_horizon_stage(
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

        stale = copy.deepcopy(record)
        stale.pop("horizon_mathematics")
        stale_stage = stale["stages"][0]
        stale_stage["operation_identity"] = "binary64-horizon-production/v2"
        stale_result = stale_stage["component_result"]["result"]
        stale_result["component_scientific_identity"] = (
            "binary64-horizon-analytic-component/v1"
        )
        stale_result["response_method"] = "binary64-fixed-root-horizon-response/v1"
        _rehashed_stage(stale_stage)
        stale["scientific_computation_identity"] = (
            forensic_v2_scientific_computation_identity_sha256(plan, leaf)
        )
        _rehashed_record(stale)
        return stale

    def test_recovery_preserves_source_and_excludes_v2_as_forensic_only(self) -> None:
        plan, leaf = self._plan_and_leaf()
        stale = self._authenticated_v2_horizon_record(plan, leaf)
        selection = RecoverySelection(
            campaign_id=plan.campaign_id,
            selection_id="commit10-v2-recovery",
            ordered_leaf_ids=(leaf.leaf_id,),
            roles={leaf.leaf_id: leaf.role},
            scientific_identities={
                leaf.leaf_id: scientific_computation_identity_sha256(plan, leaf)
            },
        )
        source = empty_schema11_checkpoint(plan.campaign_id, selection.selection_id)
        source = add_numerical_record(source, stale)
        source = record_evidence(
            source,
            leaf_id=leaf.leaf_id,
            central_record_sha256=stale["record_sha256"],
            central_stage_sha256=stale["stages"][0]["stage_sha256"],
            evidence_level=EvidenceLevel.SCREENED,
            receipts=[{"schema": "historical-v2-screening/v1"}],
        )

        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            source_path = root / "failed-v2-source.json"
            output_path = root / "recovered.json"
            receipt_path = root / "recovery-receipt.json"
            source_path.write_bytes(canonical_json_bytes(source))
            source_bytes = source_path.read_bytes()
            source_sha256 = hashlib.sha256(source_bytes).hexdigest()

            summary = recover_campaign(
                selection,
                output_path=output_path,
                receipt_path=receipt_path,
                source_checkpoints=(source_path,),
                record_validator=lambda leaf_id, record: validate_campaign_recovery_record(
                    plan, leaf_id, record
                ),
                record_intake_assessor=lambda leaf_id, record: (
                    assess_campaign_record_for_current_runtime(plan, leaf_id, record)
                ),
            )

            self.assertEqual(source_bytes, source_path.read_bytes())
            self.assertEqual(0, summary.recovered_count)
            candidate = json.loads(output_path.read_text(encoding="utf-8"))
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            self.assertEqual([], candidate["records"])
            self.assertEqual({}, candidate["evidence_ledger"])
            self.assertEqual([], candidate["promotion_queue"]["entries"])
            compatibility = next(
                item
                for item in candidate["recovery_receipts"]
                if item.get("schema") == SCIENTIFIC_COMPATIBILITY_SCHEMA
            )
            self.assertEqual(STALE_HORIZON_REASON, compatibility["reason"])
            self.assertEqual(source_sha256, compatibility["source_sha256"])
            self.assertTrue(compatibility["source_evidence_was_present"])
            self.assertFalse(compatibility["imported_as_current_numerical_record"])
            self.assertFalse(compatibility["imported_as_current_evidence"])
            self.assertEqual(
                "REBUILT_FROM_CURRENT_SELECTION",
                compatibility["operational_queue_disposition"],
            )
            self.assertIn(
                "binary64-horizon-production/v2",
                compatibility["source_operation_identities"],
            )
            self.assertIn(
                STALE_HORIZON_REASON,
                {item["reason"] for item in receipt["ignored_inputs"]},
            )
            self.assertEqual(0, receipt["source_mutations"])
            validate_recovery_checkpoint(
                selection,
                output_path,
                record_validator=lambda leaf_id, record: validate_campaign_recovery_record(
                    plan, leaf_id, record
                ),
            )

    def test_stale_v2_must_authenticate_before_forensic_classification(self) -> None:
        plan, leaf = self._plan_and_leaf()
        stale = self._authenticated_v2_horizon_record(plan, leaf)
        stale["stages"][0]["stage_sha256"] = "0" * 64
        _rehashed_record(stale)
        selection = RecoverySelection(
            campaign_id=plan.campaign_id,
            selection_id="commit10-v2-corrupt-stage",
            ordered_leaf_ids=(leaf.leaf_id,),
            roles={leaf.leaf_id: leaf.role},
            scientific_identities={
                leaf.leaf_id: scientific_computation_identity_sha256(plan, leaf)
            },
        )
        source = add_numerical_record(
            empty_schema11_checkpoint(plan.campaign_id, selection.selection_id), stale
        )

        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            source_path = root / "corrupt-v2-source.json"
            output_path = root / "recovered.json"
            receipt_path = root / "recovery-receipt.json"
            source_path.write_bytes(canonical_json_bytes(source))

            with self.assertRaisesRegex(ValueError, "stage digest"):
                recover_campaign(
                    selection,
                    output_path=output_path,
                    receipt_path=receipt_path,
                    source_checkpoints=(source_path,),
                    record_validator=lambda leaf_id, record: validate_campaign_recovery_record(
                        plan, leaf_id, record
                    ),
                    record_intake_assessor=lambda leaf_id, record: (
                        assess_campaign_record_for_current_runtime(
                            plan, leaf_id, record
                        )
                    ),
                )
            self.assertFalse(output_path.exists())
            self.assertFalse(receipt_path.exists())


if __name__ == "__main__":
    unittest.main()
