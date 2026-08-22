from __future__ import annotations

from dataclasses import replace
import hashlib
import json
import lzma
from pathlib import Path
import tempfile
import unittest

from windows_solver.campaign_policy import (
    CampaignEvidenceRecord,
    EvidenceLevel,
    EvidenceReceipt,
    ExecutionProfile,
)
from windows_solver.cli import _validate_reduction_component_checkpoint_binding
from windows_solver.response_batches import (
    CAMPAIGN_CHECKPOINT_SCHEMA_VERSION,
    CampaignLeafRecord,
    PrecisionCapabilities,
    StageOutcome,
    _atomic_json,
    _campaign_stage_record,
    _checkpoint_mapping,
    build_campaign_plan,
    build_campaign_selection,
    run_campaign_selection,
    synthetic_stage_signed_error_channels,
    validate_campaign_checkpoint,
)
from windows_solver.response_engine import (
    FULL_COMPLEX_LADDER_VALIDATION_IDENTITY,
    NumericalPolicy,
    VettedNativeDeterminantKernel,
)
from tests.test_linear_response_batches import _produced_stage_outcome


class NoNumericalWorkBackend:
    identity = VettedNativeDeterminantKernel.identity
    precision_capabilities = PrecisionCapabilities((64, 80, 120))

    def __init__(self) -> None:
        self.calls = 0

    def scientific_execution_contract_for(self, leaf):
        return None

    def execute_profile_stage(self, leaf, digits, policy, survey_cache):
        self.calls += 1
        raise AssertionError("checkpoint migration scheduled numerical work")


class MigrationValidationBackend:
    identity = VettedNativeDeterminantKernel.identity
    precision_capabilities = PrecisionCapabilities((64, 80, 120))

    def __init__(self) -> None:
        self.calls = 0

    def scientific_execution_contract_for(self, leaf):
        return None

    def execute_evidence_stage(self, leaf, retained_record, policy):
        self.calls += 1
        self.assert_validate_policy(policy)
        central = retained_record.stages[-1].outcome
        result = central.component_result["result"]
        payload = {
            "evidence_kind": "independent-publication-validation/v1",
            "execution_profile": ExecutionProfile.VALIDATE.value,
            "result": result,
            "heavy_local_stage_chain": [],
            "validation_policy": {
                "identity": FULL_COMPLEX_LADDER_VALIDATION_IDENTITY,
                "reason": "PUBLICATION_VALIDATION",
            },
        }
        radius = central.local_disk_radius_abs
        return StageOutcome(
            digits=80,
            numerical_state="CONVERGED",
            component_result=payload,
            local_disk_radius_abs=radius,
            signed_error_channels=synthetic_stage_signed_error_channels(
                payload,
                radius,
                precision_ladder_applicable=False,
            ),
        )

    @staticmethod
    def assert_validate_policy(policy) -> None:
        if (
            policy.profile is not ExecutionProfile.VALIDATE
            or not policy.allow_full_complex_root_ladder
            or not policy.allow_independent_validation
        ):
            raise AssertionError("migrated evidence used the wrong validation policy")


class StopAtFirstMissingSurveyBackend:
    precision_capabilities = PrecisionCapabilities((64, 80, 120))

    def __init__(self, identity) -> None:
        self.identity = identity
        self.calls: list[tuple[str, int]] = []

    def scientific_execution_contract_for(self, leaf):
        return None

    def execute_profile_stage(self, leaf, digits, policy, survey_cache):
        self.calls.append((leaf.leaf_id, digits))
        raise AssertionError("stopped at first genuinely missing survey result")

    def execute_profile_promoted_stage(
        self, leaf, digits, previous_outcomes, policy, survey_cache
    ):
        self.calls.append((leaf.leaf_id, digits))
        raise AssertionError("stopped at first genuinely missing survey result")


class RecoverLegacyPartialThenStopBackend(StopAtFirstMissingSurveyBackend):
    def __init__(self, identity, legacy_partial_leaf_id: str) -> None:
        super().__init__(identity)
        self.legacy_partial_leaf_id = legacy_partial_leaf_id
        self.recovered_legacy_partial = False

    def execute_profile_stage(self, leaf, digits, policy, survey_cache):
        if self.recovered_legacy_partial:
            raise AssertionError("stopped after recovering the legacy partial leaf")
        self.calls.append((leaf.leaf_id, digits))
        if leaf.leaf_id == self.legacy_partial_leaf_id:
            self.recovered_legacy_partial = True
        payload = {
            "evidence_kind": "synthetic-survey-orchestration-contract",
            "leaf_id": leaf.leaf_id,
            "mechanism_id": leaf.mechanism_id,
            "digits": digits,
            "root_seal_accepted": True,
            "branch_identity_preserved": True,
            "domega_excludes_zero": True,
            "cheap_derivative_refinement_agrees": True,
            "bounded_response_disk": True,
            "response": {"real": 1.0e-3, "imaginary": -2.0e-3},
            "survey_promotion_required": False,
            "survey_required_precision_digits": None,
            "survey_failure_code": None,
        }
        radius = 1.0e-7
        return StageOutcome(
            digits=digits,
            numerical_state="CONVERGED",
            component_result=payload,
            local_disk_radius_abs=radius,
            signed_error_channels=synthetic_stage_signed_error_channels(
                payload,
                radius,
                precision_ladder_applicable=False,
            ),
        )


def _plan_and_produced_record():
    plan = build_campaign_plan(
        policy=NumericalPolicy(),
        backend_identity=VettedNativeDeterminantKernel.identity,
        precision_capabilities=PrecisionCapabilities((64, 80, 120)),
    )
    leaf = next(
        item
        for item in plan.leaves
        if item.role == "control"
        and item.mechanism_id == "exterior-fixed-r3"
    )
    selection = build_campaign_selection(
        plan, role="control", leaf_ids=(leaf.leaf_id,)
    )
    stage = _campaign_stage_record(
        plan,
        plan.precision_capabilities,
        _produced_stage_outcome(leaf, complex(0.01, -0.02)),
    )
    record = CampaignLeafRecord(
        leaf_id=leaf.leaf_id,
        role=leaf.role,
        state="PRODUCED",
        stages=(stage,),
    )
    return plan, selection, record


class CampaignEvidenceMigrationTests(unittest.TestCase):
    def test_copied_schema9_production_checkpoint_migrates_before_new_work(self):
        fixture = (
            Path(__file__).parent
            / "fixtures"
            / "m02_schema9_production_checkpoint.json.xz"
        )
        original_bytes = lzma.decompress(fixture.read_bytes())
        self.assertEqual(
            hashlib.sha256(original_bytes).hexdigest(),
            "b62f9e6c1c901cd7eee907b99d387bdc1e86be5019b5d4efd11fa28997015d35",
        )
        original = json.loads(original_bytes)
        self.assertEqual(original["schema_version"], 9)
        self.assertEqual(original["state"], "PARTIAL")
        self.assertEqual(len(original["records"]), 41)

        windows_identity = replace(
            VettedNativeDeterminantKernel.identity,
            runtime_fingerprint=(
                "cpython-3.12.13-windows-python-64bit-"
                "gsn-input-julia-exact-f-u-cache-contract-1-"
                "adapted-source-native-gsn-adapter-contract-2"
            ),
        )
        self.assertEqual(
            windows_identity.identity_sha256,
            "a35815c047fae2cb0880666d1ce8c1add236c8597e68d6a914709307d1e2afc1",
        )
        plan = build_campaign_plan(
            policy=NumericalPolicy(),
            backend_identity=windows_identity,
            precision_capabilities=PrecisionCapabilities((64, 80, 120)),
        )
        selection = build_campaign_selection(plan, role="all")
        backend = StopAtFirstMissingSurveyBackend(windows_identity)
        original_stage_sha256s = {
            record["leaf_id"]: tuple(
                stage["stage_sha256"] for stage in record["stages"]
            )
            for record in original["records"]
        }

        with tempfile.TemporaryDirectory() as temporary:
            checkpoint = Path(temporary) / "checkpoint.json"
            checkpoint.write_bytes(original_bytes)
            with self.assertRaisesRegex(
                AssertionError, "first genuinely missing survey result"
            ):
                run_campaign_selection(
                    plan,
                    selection,
                    backend,
                    checkpoint,
                    resume=True,
                    execution_profile=ExecutionProfile.SURVEY,
                )
            migrated = json.loads(checkpoint.read_text(encoding="utf-8"))

        self.assertEqual(migrated["schema_version"], 10)
        self.assertEqual(migrated["state"], "PARTIAL")
        self.assertEqual(len(migrated["records"]), 41)
        self.assertEqual(migrated["attempts"], original["attempts"])
        self.assertEqual(
            {
                record["leaf_id"]: tuple(
                    stage["stage_sha256"] for stage in record["stages"]
                )
                for record in migrated["records"]
            },
            original_stage_sha256s,
        )
        produced = [
            record for record in migrated["records"]
            if record["state"] == "PRODUCED"
        ]
        self.assertEqual(len(produced), 39)
        self.assertTrue(all(
            record["evidence"]["evidence_level"]
            in {"CERTIFIED", "VALIDATED"}
            for record in produced
        ))
        self.assertEqual(len(backend.calls), 1)
        self.assertNotIn(
            backend.calls[0][0],
            {
                record["leaf_id"]
                for record in original["records"]
                if record["state"] in {"PRODUCED", "UNRESOLVED"}
            },
        )

    def test_schema9_nonterminal_stage_restarts_as_one_valid_survey_sequence(self):
        fixture = (
            Path(__file__).parent
            / "fixtures"
            / "m02_schema9_production_checkpoint.json.xz"
        )
        original_bytes = lzma.decompress(fixture.read_bytes())
        original = json.loads(original_bytes)
        legacy_partial = next(
            record
            for record in original["records"]
            if record["state"] not in {"PRODUCED", "UNRESOLVED", "FAILED"}
        )
        completed_stage_sha256s = {
            record["leaf_id"]: tuple(
                stage["stage_sha256"] for stage in record["stages"]
            )
            for record in original["records"]
            if record["state"] in {"PRODUCED", "UNRESOLVED", "FAILED"}
        }
        windows_identity = replace(
            VettedNativeDeterminantKernel.identity,
            runtime_fingerprint=(
                "cpython-3.12.13-windows-python-64bit-"
                "gsn-input-julia-exact-f-u-cache-contract-1-"
                "adapted-source-native-gsn-adapter-contract-2"
            ),
        )
        plan = build_campaign_plan(
            policy=NumericalPolicy(),
            backend_identity=windows_identity,
            precision_capabilities=PrecisionCapabilities((64, 80, 120)),
        )
        selection = build_campaign_selection(plan, role="all")
        backend = RecoverLegacyPartialThenStopBackend(
            windows_identity,
            legacy_partial["leaf_id"],
        )

        with tempfile.TemporaryDirectory() as temporary:
            checkpoint = Path(temporary) / "checkpoint.json"
            checkpoint.write_bytes(original_bytes)
            with self.assertRaisesRegex(
                AssertionError,
                "stopped after recovering the legacy partial leaf",
            ):
                run_campaign_selection(
                    plan,
                    selection,
                    backend,
                    checkpoint,
                    resume=True,
                    execution_profile=ExecutionProfile.SURVEY,
                )
            migrated = json.loads(checkpoint.read_text(encoding="utf-8"))

        migrated_by_id = {
            record["leaf_id"]: record for record in migrated["records"]
        }
        recovered = migrated_by_id[legacy_partial["leaf_id"]]
        self.assertIn((legacy_partial["leaf_id"], 64), backend.calls)
        self.assertEqual(recovered["state"], "PRODUCED")
        self.assertEqual(
            [stage["digits"] for stage in recovered["stages"]],
            [64],
        )
        self.assertEqual(recovered["evidence"]["evidence_level"], "SCREENED")
        self.assertNotEqual(
            recovered["stages"][0]["stage_sha256"],
            legacy_partial["stages"][0]["stage_sha256"],
        )
        self.assertEqual(
            {
                leaf_id: tuple(
                    stage["stage_sha256"]
                    for stage in migrated_by_id[leaf_id]["stages"]
                )
                for leaf_id in completed_stage_sha256s
            },
            completed_stage_sha256s,
        )

    def test_schema9_completed_record_migrates_without_numerical_work(self):
        self.assertEqual(CAMPAIGN_CHECKPOINT_SCHEMA_VERSION, 10)
        plan, selection, record = _plan_and_produced_record()
        old_stage_sha256 = record.stages[0].stage_sha256
        backend = NoNumericalWorkBackend()

        with tempfile.TemporaryDirectory() as temporary:
            checkpoint = Path(temporary) / "checkpoint.json"
            legacy = _checkpoint_mapping(plan, selection, (record,))
            legacy["schema_version"] = 9
            _atomic_json(checkpoint, legacy)

            summary = run_campaign_selection(
                plan,
                selection,
                backend,
                checkpoint,
                resume=True,
                execution_profile=ExecutionProfile.SURVEY,
            )
            persisted = json.loads(checkpoint.read_text(encoding="utf-8"))

        self.assertEqual(backend.calls, 0)
        self.assertEqual(summary.executed_stage_count, 0)
        self.assertEqual(summary.records[0].stages[0].stage_sha256, old_stage_sha256)
        self.assertEqual(
            summary.records[0].evidence.evidence_level,
            EvidenceLevel.CERTIFIED,
        )
        self.assertEqual(persisted["schema_version"], 10)
        self.assertEqual(
            persisted["records"][0]["evidence"]["evidence_level"],
            "CERTIFIED",
        )

    def test_stronger_existing_evidence_is_never_downgraded(self):
        plan, selection, record = _plan_and_produced_record()
        original = record.stages[0].outcome
        payload = dict(original.component_result)
        payload["validation_policy"] = {
            "identity": FULL_COMPLEX_LADDER_VALIDATION_IDENTITY,
            "reason": "PUBLICATION_VALIDATION",
        }
        outcome = StageOutcome(
            digits=original.digits,
            numerical_state=original.numerical_state,
            component_result=payload,
            local_disk_radius_abs=original.local_disk_radius_abs,
            signed_error_channels=synthetic_stage_signed_error_channels(
                payload, original.local_disk_radius_abs
            ),
        )
        stage = _campaign_stage_record(
            plan, plan.precision_capabilities, outcome
        )
        record = CampaignLeafRecord(
            leaf_id=record.leaf_id,
            role=record.role,
            state=record.state,
            stages=(stage,),
        )
        backend = NoNumericalWorkBackend()

        with tempfile.TemporaryDirectory() as temporary:
            checkpoint = Path(temporary) / "checkpoint.json"
            legacy = _checkpoint_mapping(plan, selection, (record,))
            legacy["schema_version"] = 9
            _atomic_json(checkpoint, legacy)
            migrated = run_campaign_selection(
                plan,
                selection,
                backend,
                checkpoint,
                resume=True,
                execution_profile=ExecutionProfile.SURVEY,
            )
            evidence_before = migrated.records[0].evidence
            summary = run_campaign_selection(
                plan,
                selection,
                backend,
                checkpoint,
                resume=True,
                execution_profile=ExecutionProfile.SURVEY,
            )

        self.assertEqual(backend.calls, 0)
        self.assertEqual(summary.records[0].evidence, evidence_before)
        self.assertEqual(
            summary.records[0].evidence.evidence_level,
            EvidenceLevel.VALIDATED,
        )

    def test_schema9_explicit_independent_validation_migrates_as_validated(self):
        plan, selection, record = _plan_and_produced_record()
        original = record.stages[0].outcome
        payload = dict(original.component_result)
        payload["validation_policy"] = {
            "identity": FULL_COMPLEX_LADDER_VALIDATION_IDENTITY,
            "reason": "PUBLICATION_VALIDATION",
        }
        outcome = StageOutcome(
            digits=original.digits,
            numerical_state=original.numerical_state,
            component_result=payload,
            local_disk_radius_abs=original.local_disk_radius_abs,
            signed_error_channels=synthetic_stage_signed_error_channels(
                payload, original.local_disk_radius_abs
            ),
        )
        stage = _campaign_stage_record(
            plan, plan.precision_capabilities, outcome
        )
        record = CampaignLeafRecord(
            leaf_id=record.leaf_id,
            role=record.role,
            state=record.state,
            stages=(stage,),
        )
        backend = NoNumericalWorkBackend()

        with tempfile.TemporaryDirectory() as temporary:
            checkpoint = Path(temporary) / "checkpoint.json"
            legacy = _checkpoint_mapping(plan, selection, (record,))
            legacy["schema_version"] = 9
            _atomic_json(checkpoint, legacy)

            summary = run_campaign_selection(
                plan,
                selection,
                backend,
                checkpoint,
                resume=True,
                execution_profile=ExecutionProfile.SURVEY,
            )

        self.assertEqual(backend.calls, 0)
        self.assertEqual(summary.records[0].stages[0], stage)
        self.assertEqual(
            summary.records[0].evidence.evidence_level,
            EvidenceLevel.VALIDATED,
        )

    def test_migrated_certified_leaf_cannot_claim_validation_without_a_stage(self):
        plan, selection, record = _plan_and_produced_record()
        backend = NoNumericalWorkBackend()

        with tempfile.TemporaryDirectory() as temporary:
            checkpoint = Path(temporary) / "checkpoint.json"
            legacy = _checkpoint_mapping(plan, selection, (record,))
            legacy["schema_version"] = 9
            _atomic_json(checkpoint, legacy)
            migrated = run_campaign_selection(
                plan,
                selection,
                backend,
                checkpoint,
                resume=True,
                execution_profile=ExecutionProfile.SURVEY,
            ).records[0]
            assert migrated.evidence is not None
            forged = replace(
                migrated,
                evidence=migrated.evidence.with_receipt(EvidenceReceipt(
                    execution_profile=ExecutionProfile.VALIDATE,
                    evidence_level=EvidenceLevel.VALIDATED,
                    receipt_sha256="f" * 64,
                )),
            )
            _atomic_json(
                checkpoint,
                _checkpoint_mapping(plan, selection, (forged,)),
            )

            with self.assertRaisesRegex(
                ValueError,
                "legacy.*receipt|upgrade.*receipt|upgrade.*level",
            ):
                validate_campaign_checkpoint(plan, checkpoint)

    def test_migrated_certified_leaf_accepts_additive_validation_evidence(self):
        plan, selection, record = _plan_and_produced_record()
        migration_backend = NoNumericalWorkBackend()

        with tempfile.TemporaryDirectory() as temporary:
            checkpoint = Path(temporary) / "checkpoint.json"
            legacy = _checkpoint_mapping(plan, selection, (record,))
            legacy["schema_version"] = 9
            _atomic_json(checkpoint, legacy)
            migrated = run_campaign_selection(
                plan,
                selection,
                migration_backend,
                checkpoint,
                resume=True,
                execution_profile=ExecutionProfile.SURVEY,
            ).records[0]
            validation_backend = MigrationValidationBackend()
            upgraded = run_campaign_selection(
                plan,
                selection,
                validation_backend,
                checkpoint,
                resume=True,
                execution_profile=ExecutionProfile.VALIDATE,
            ).records[0]
            restored = validate_campaign_checkpoint(plan, checkpoint).records[0]

        self.assertEqual(migration_backend.calls, 0)
        self.assertEqual(validation_backend.calls, 1)
        self.assertEqual(upgraded.stages, migrated.stages)
        self.assertEqual(len(upgraded.evidence_stages), 1)
        self.assertEqual(upgraded.evidence.evidence_level, EvidenceLevel.VALIDATED)
        self.assertEqual(restored, upgraded)

    def test_screened_record_is_rejected_at_release_reduction_boundary(self):
        plan, _, record = _plan_and_produced_record()
        screened = CampaignEvidenceRecord.create(
            leaf_id=record.leaf_id,
            central_stage_sha256=record.stages[0].stage_sha256,
            receipt=EvidenceReceipt(
                execution_profile=ExecutionProfile.SURVEY,
                evidence_level=EvidenceLevel.SCREENED,
                receipt_sha256="b" * 64,
            ),
        )
        record = CampaignLeafRecord(
            leaf_id=record.leaf_id,
            role=record.role,
            state=record.state,
            stages=record.stages,
            evidence=screened,
        )

        with self.assertRaisesRegex(ValueError, "SCREENED-only"):
            _validate_reduction_component_checkpoint_binding(
                object(), record, frozenset()
            )


if __name__ == "__main__":
    unittest.main()
