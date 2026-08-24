from __future__ import annotations

import hashlib
from pathlib import Path
import tempfile
import unittest

from windows_solver.campaign_evidence import (
    EvidencePassOutcome,
    EvidenceStrengtheningPolicy,
    build_evidence_pass_request,
    require_release_evidence,
    run_evidence_pass,
)
from windows_solver.campaign_failures import CampaignSystemFailure
from windows_solver.campaign_policy import (
    EvidenceLevel,
    ExecutionProfile,
    add_numerical_record,
    empty_schema11_checkpoint,
    record_evidence,
)
from windows_solver.contracts import canonical_json_bytes
from windows_solver.evidence_authentication import evidence_policy_identity


def _sha256(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _native_receipt(
    profile: ExecutionProfile,
    record_sha256: str,
    stage_sha256: str,
    leaf_id: str = "leaf-1",
):
    independent_result = {"centre": {"real": 1.25, "imaginary": -0.5}}
    content = {
        "schema": "windows-solver.native-evidence-result/1",
        "profile": profile.value,
        "evidence_policy_identity": evidence_policy_identity(profile.value),
        "leaf_id": leaf_id,
        "central_record_sha256": record_sha256,
        "central_stage_sha256": stage_sha256,
        "precision_tier": "BF80",
        "refinement": 0 if profile is ExecutionProfile.CERTIFY else 1,
        "operation_identity": (
            "production-certification-comparator/v1"
            if profile is ExecutionProfile.CERTIFY
            else "independent-validation-comparator/v1"
        ),
        "backend_identity": "b" * 64,
        "runtime_identity": "c" * 64,
        "calculation_route_identity": "same-backend-refinement/v1",
        "calculation_route_family": "EXTERIOR",
        "route_output_sha256": _sha256(independent_result),
        "human_mathematics_review_receipt": None,
        "centre_agrees": True,
        "discrepancy_code": None,
        "independent_result": independent_result,
    }
    return {**content, "receipt_sha256": _sha256(content)}


def _certification_disposition(record_sha256: str, stage_sha256: str):
    source = _native_receipt(
        ExecutionProfile.CERTIFY, record_sha256, stage_sha256
    )
    content = {
        "schema": "windows-solver.evidence-pass-disposition/1",
        "profile": "CERTIFY",
        "request_sha256": "a" * 64,
        "evidence_policy_identity": evidence_policy_identity("CERTIFY"),
        "engine_identity": "b" * 64,
        "leaf_id": "leaf-1",
        "central_record_sha256": record_sha256,
        "central_stage_sha256": stage_sha256,
        "centre_agrees": True,
        "discrepancy_code": None,
        "precision_tiers": ["BF80"],
        "validation_admission_status": "NOT_APPLICABLE",
        "source_receipt": source,
    }
    return {**content, "receipt_sha256": _sha256(content)}


def _checkpoint(level: EvidenceLevel = EvidenceLevel.SCREENED):
    stage_content = {"schema": "windows-solver.test-stage/1", "value": 7}
    stage_sha256 = _sha256(stage_content)
    stage = {**stage_content, "stage_sha256": stage_sha256}
    content = {
        "leaf_id": "leaf-1",
        "state": "PRODUCED",
        "response": {"real": 1.25, "imaginary": -0.5},
        "stages": [stage],
    }
    record = {**content, "record_sha256": _sha256(content)}
    checkpoint = empty_schema11_checkpoint("campaign-1", "selection-1")
    checkpoint = add_numerical_record(checkpoint, record)
    checkpoint = record_evidence(
        checkpoint,
        leaf_id="leaf-1",
        central_record_sha256=record["record_sha256"],
        central_stage_sha256=stage_sha256,
        evidence_level=EvidenceLevel.SCREENED,
        receipts=({"schema": "windows-solver.screening/1"},),
    )
    if level is EvidenceLevel.CERTIFIED:
        checkpoint = record_evidence(
            checkpoint,
            leaf_id="leaf-1",
            central_record_sha256=record["record_sha256"],
            central_stage_sha256=stage_sha256,
            evidence_level=EvidenceLevel.CERTIFIED,
            receipts=(
                _certification_disposition(record["record_sha256"], stage_sha256),
            ),
        )
    return checkpoint, record, stage_sha256


class CampaignEvidencePassTests(unittest.TestCase):
    def _run(self, checkpoint, policy, outcome):
        request = build_evidence_pass_request(
            checkpoint,
            policy=policy,
            ordered_leaf_ids=("leaf-1",),
            engine_identity="b" * 64,
        )
        with tempfile.TemporaryDirectory() as temporary:
            return run_evidence_pass(
                checkpoint,
                request,
                policy,
                checkpoint_path=Path(temporary) / "checkpoint.json",
                execute_leaf=lambda leaf_id, active_policy: outcome,
            )

    def test_certification_upgrades_evidence_without_changing_record(self):
        checkpoint, record, stage_sha256 = _checkpoint()
        policy = EvidenceStrengtheningPolicy.certification()
        outcome = EvidencePassOutcome(
            leaf_id="leaf-1",
            profile=ExecutionProfile.CERTIFY,
            central_record_sha256=record["record_sha256"],
            central_stage_sha256=stage_sha256,
            centre_agrees=True,
            discrepancy_code=None,
            receipt=_native_receipt(
                ExecutionProfile.CERTIFY,
                record["record_sha256"],
                stage_sha256,
            ),
        )

        result = self._run(checkpoint, policy, outcome)

        self.assertEqual([record], result["records"])
        self.assertEqual(
            "CERTIFIED", result["evidence_ledger"]["leaf-1"]["evidence_level"]
        )

    def test_validation_requires_certified_input(self):
        checkpoint, record, stage_sha256 = _checkpoint()
        policy = EvidenceStrengtheningPolicy.validation()
        outcome = EvidencePassOutcome(
            leaf_id="leaf-1",
            profile=ExecutionProfile.VALIDATE,
            central_record_sha256=record["record_sha256"],
            central_stage_sha256=stage_sha256,
            centre_agrees=True,
            discrepancy_code=None,
            receipt=_native_receipt(
                ExecutionProfile.VALIDATE,
                record["record_sha256"],
                stage_sha256,
            ),
        )
        called = []
        request = build_evidence_pass_request(
            checkpoint,
            policy=policy,
            ordered_leaf_ids=("leaf-1",),
            engine_identity="b" * 64,
        )
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(ValueError, "requires CERTIFIED"):
                run_evidence_pass(
                    checkpoint,
                    request,
                    policy,
                    checkpoint_path=Path(temporary) / "checkpoint.json",
                    execute_leaf=lambda *args: called.append(args),
                )
        self.assertEqual([], called)

    def test_disagreement_records_discrepancy_and_keeps_screened_centre(self):
        checkpoint, record, stage_sha256 = _checkpoint()
        outcome = EvidencePassOutcome(
            leaf_id="leaf-1",
            profile=ExecutionProfile.CERTIFY,
            central_record_sha256=record["record_sha256"],
            central_stage_sha256=stage_sha256,
            centre_agrees=False,
            discrepancy_code="CERTIFIED_CENTRE_OUTSIDE_SCREENED_DISK",
            receipt=_native_receipt(
                ExecutionProfile.CERTIFY,
                record["record_sha256"],
                stage_sha256,
            ),
        )

        result = self._run(
            checkpoint, EvidenceStrengtheningPolicy.certification(), outcome
        )

        self.assertEqual([record], result["records"])
        evidence = result["evidence_ledger"]["leaf-1"]
        self.assertEqual("SCREENED", evidence["evidence_level"])
        self.assertEqual(
            ["CERTIFIED_CENTRE_OUTSIDE_SCREENED_DISK"],
            evidence["discrepancy_codes"],
        )

    def test_same_backend_validation_receipt_cannot_award_validated(self):
        checkpoint, record, stage_sha256 = _checkpoint(EvidenceLevel.CERTIFIED)
        outcome = EvidencePassOutcome(
            leaf_id="leaf-1",
            profile=ExecutionProfile.VALIDATE,
            central_record_sha256=record["record_sha256"],
            central_stage_sha256=stage_sha256,
            centre_agrees=True,
            discrepancy_code=None,
            receipt=_native_receipt(
                ExecutionProfile.VALIDATE,
                record["record_sha256"],
                stage_sha256,
            ),
        )

        result = self._run(
            checkpoint, EvidenceStrengtheningPolicy.validation(), outcome
        )

        self.assertEqual([record], result["records"])
        self.assertEqual(
            "CERTIFIED", result["evidence_ledger"]["leaf-1"]["evidence_level"]
        )
        self.assertEqual(
            "ROUTE_NOT_INDEPENDENT",
            result["evidence_ledger"]["leaf-1"]["receipts"][-1][
                "validation_admission_status"
            ],
        )

    def test_heavy_paths_are_exposed_only_by_the_explicit_profile(self):
        certification = EvidenceStrengtheningPolicy.certification()
        validation = EvidenceStrengtheningPolicy.validation()
        self.assertTrue(certification.certificate_path_allowed)
        self.assertFalse(certification.independent_validation_allowed)
        self.assertFalse(validation.certificate_path_allowed)
        self.assertTrue(validation.independent_validation_allowed)
        with self.assertRaisesRegex(ValueError, "not an evidence-strengthening"):
            EvidenceStrengtheningPolicy(profile=ExecutionProfile.SURVEY)

    def test_bf120_requires_an_explicit_review_receipt(self):
        with self.assertRaisesRegex(ValueError, "BF120 requires"):
            EvidenceStrengtheningPolicy(
                profile=ExecutionProfile.CERTIFY,
                precision_tiers=("BF80", "BF120"),
            )
        policy = EvidenceStrengtheningPolicy(
            profile=ExecutionProfile.CERTIFY,
            precision_tiers=("BF80", "BF120"),
            bf120_review_receipt_sha256="c" * 64,
        )
        self.assertEqual(("BF80", "BF120"), policy.precision_tiers)

    def test_screened_evidence_is_not_release_admissible(self):
        checkpoint, _, _ = _checkpoint()
        with self.assertRaisesRegex(ValueError, "requires CERTIFIED"):
            require_release_evidence(
                checkpoint, {"leaf-1": EvidenceLevel.CERTIFIED}
            )
        with self.assertRaisesRegex(ValueError, "CERTIFIED or VALIDATED"):
            require_release_evidence(
                checkpoint, {"leaf-1": EvidenceLevel.SCREENED}
            )

    def test_stale_request_aborts_before_executor(self):
        checkpoint, record, stage_sha256 = _checkpoint()
        policy = EvidenceStrengtheningPolicy.certification()
        request = build_evidence_pass_request(
            checkpoint,
            policy=policy,
            ordered_leaf_ids=("leaf-1",),
            engine_identity="b" * 64,
        )
        changed = record_evidence(
            checkpoint,
            leaf_id="leaf-1",
            central_record_sha256=record["record_sha256"],
            central_stage_sha256=stage_sha256,
            evidence_level=EvidenceLevel.SCREENED,
            receipts=({"schema": "new-screening/v1"},),
        )
        called = []
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(ValueError, "checkpoint binding"):
                run_evidence_pass(
                    changed,
                    request,
                    policy,
                    checkpoint_path=Path(temporary) / "checkpoint.json",
                    execute_leaf=lambda *args: called.append(args),
                )
        self.assertEqual([], called)

    def test_unexpected_executor_error_is_durable_system_failure(self):
        checkpoint, _, _ = _checkpoint()
        policy = EvidenceStrengtheningPolicy.certification()
        request = build_evidence_pass_request(
            checkpoint,
            policy=policy,
            ordered_leaf_ids=("leaf-1",),
            engine_identity="b" * 64,
        )
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "checkpoint.json"
            with self.assertRaises(CampaignSystemFailure):
                run_evidence_pass(
                    checkpoint,
                    request,
                    policy,
                    checkpoint_path=path,
                    execute_leaf=lambda *args: (_ for _ in ()).throw(
                        TypeError("unexpected certification defect")
                    ),
                )
            self.assertTrue(path.is_file())


if __name__ == "__main__":
    unittest.main()
