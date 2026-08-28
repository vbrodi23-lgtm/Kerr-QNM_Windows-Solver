from __future__ import annotations

import copy
import hashlib
import json
import lzma
from pathlib import Path
from types import SimpleNamespace
import unittest

from windows_solver.campaign_failures import (
    require_system_failures_resolved_for_promoted_resume,
    resolve_system_failure_for_resume,
)
from windows_solver.campaign_policy import validate_schema11_checkpoint
from windows_solver.contracts import canonical_json_bytes
from windows_solver.julia_response_backend import (
    FIXED_ROOT_SURVEY_BATCH_SCHEMA,
    FixedRootSurveyPlan,
    JuliaPrecisionRootBackend,
    _worker_request_document,
)
from windows_solver.promoted_control_calibration import (
    load_default_calibration_receipt,
)
from windows_solver.response_batches import (
    PrecisionCapabilities,
    build_campaign_plan,
)
from windows_solver.response_engine import (
    NumericalPolicy,
    VettedNativeDeterminantKernel,
)


FIXTURE = (
    Path(__file__).with_name("fixtures")
    / "m02_pr74_failed_promoted_checkpoint.json.xz"
)
MANIFEST = FIXTURE.with_suffix("").with_suffix(".manifest.json")


def _sha256(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _load_fixture() -> tuple[dict[str, object], dict[str, object]]:
    compressed = FIXTURE.read_bytes()
    manifest = json.loads(MANIFEST.read_bytes())
    if hashlib.sha256(compressed).hexdigest() != manifest[
        "compressed_fixture_sha256"
    ]:
        raise ValueError("PR74 fixture compressed digest is invalid")
    raw = lzma.decompress(compressed)
    if hashlib.sha256(raw).hexdigest() != manifest[
        "redacted_checkpoint_sha256"
    ]:
        raise ValueError("PR74 fixture redacted digest is invalid")
    checkpoint = validate_schema11_checkpoint(json.loads(raw))
    return checkpoint, manifest


def _preview_backend(digits: int) -> JuliaPrecisionRootBackend:
    calibration = load_default_calibration_receipt()
    adapter = SimpleNamespace(runtime_provenance={
        "julia_version": "fixture-no-worker",
        "julia_executable_sha256": "a" * 64,
        "julia_manifest_sha256": "b" * 64,
        "worker_sha256": "c" * 64,
        "runtime_policy_sha256": "d" * 64,
        "scientific_sources": [],
    })
    return JuliaPrecisionRootBackend(
        VettedNativeDeterminantKernel.identity,
        adapter,
        digits,
        empirical_control_profile=calibration.budget_for(
            "exterior-wronskian/v1", digits
        ),
        calibration_receipt=calibration,
    )


class PR74CheckpointHandoverTests(unittest.TestCase):
    def test_exact_failed_checkpoint_hands_ordinal_one_to_fresh_request_v2(self):
        checkpoint, manifest = _load_fixture()
        self.assertEqual(
            manifest["source_checkpoint_sha256"],
            "35dab16bd0f29a6bb05509f5bda4dac73996c6afd67205b609d4dc44fc5063f2",
        )
        self.assertEqual(
            manifest["redaction_method"],
            "token-replace-private-roots-and-reauthenticate/v1",
        )
        self.assertEqual(len(checkpoint["survey_pass_ledger"]["binary64"]), 212)
        self.assertEqual(len(checkpoint["promotion_queue"]["entries"]), 212)

        entries = checkpoint["promotion_queue"]["entries"]
        ordinal_zero = entries[0]
        ordinal_one = entries[1]
        retained_zero = checkpoint["promoted_stage_ledger"]["0"][
            ordinal_zero["leaf_id"]
        ]
        self.assertEqual(ordinal_zero["disposition"], "AWAITING_ADMISSION")
        self.assertEqual(retained_zero["route"], "HORIZON_BF80")
        self.assertEqual(retained_zero["precision_tiers"], ["BF80"])
        self.assertEqual(retained_zero["admission_state"], "AWAITING_ADMISSION")
        self.assertEqual(ordinal_one["disposition"], "PENDING")
        self.assertIsNone(ordinal_one["retained_promoted_stage_sha256"])
        self.assertNotIn("1", checkpoint["promoted_stage_ledger"])

        preserved = {
            "binary64": _sha256(checkpoint["survey_pass_ledger"]["binary64"]),
            "queue_sources": _sha256([
                {
                    "leaf_id": entry["leaf_id"],
                    "source_stage_sha256": entry["source_stage_sha256"],
                    "source_root_seal_sha256": entry[
                        "source_root_seal_sha256"
                    ],
                    "provisional_stage": entry["provisional_stage"],
                }
                for entry in entries
            ]),
            "root_ledger": _sha256(checkpoint["promoted_root_ledger"]),
            "background_ledger": _sha256(
                checkpoint["promoted_background_ledger"]
            ),
            "ordinal_zero_stage": retained_zero["stage_sha256"],
        }
        forensic = manifest["forensic_history"]
        failure = checkpoint["system_failures"][0]
        self.assertEqual(
            forensic["request_schema"],
            "windows-solver.fixed-root-survey-batch/1",
        )
        self.assertEqual(forensic["authority"], "FORENSIC_ONLY")
        self.assertEqual(
            forensic["redacted_system_failure_receipt_sha256"],
            failure["receipt_sha256"],
        )
        self.assertIn("fixed-root survey policy fields are invalid", failure["message"])

        calibration = load_default_calibration_receipt()
        layer1_lock = retained_zero["layer1_lock_receipt_sha256"]
        authority = calibration.independent_review_authority_sha256
        with self.assertRaisesRegex(ValueError, "active SYSTEM_FAILURE"):
            require_system_failures_resolved_for_promoted_resume(
                checkpoint,
                expected_authority_sha256=authority,
                calibration_receipt_sha256=calibration.sha256,
                binary64_lock_receipt_sha256=layer1_lock,
            )
        resolved, resolution = resolve_system_failure_for_resume(
            checkpoint,
            system_failure_receipt_sha256=failure["receipt_sha256"],
            expected_authority_sha256=authority,
            calibration_receipt_sha256=calibration.sha256,
            binary64_lock_receipt_sha256=layer1_lock,
            repair_commit_sha="d" * 40,
            reason="PR75 replaces PR74 fixed-root execution authority",
            resolved_at_utc="2026-08-28T00:00:00Z",
        )
        authorised = require_system_failures_resolved_for_promoted_resume(
            resolved,
            expected_authority_sha256=authority,
            calibration_receipt_sha256=calibration.sha256,
            binary64_lock_receipt_sha256=layer1_lock,
        )
        self.assertEqual(authorised, (resolution,))
        self.assertEqual(
            resolution["resolution_scope"],
            "RESUME_UNRETAINED_LAYER2_WORK_ONLY",
        )
        self.assertEqual(resolved["system_failures"], checkpoint["system_failures"])
        self.assertEqual(len(resolved["recovery_receipts"]), 1)

        resolved_entries = resolved["promotion_queue"]["entries"]
        resolved_zero = resolved["promoted_stage_ledger"]["0"][
            ordinal_zero["leaf_id"]
        ]
        self.assertEqual(
            {
                "binary64": _sha256(resolved["survey_pass_ledger"]["binary64"]),
                "queue_sources": _sha256([
                    {
                        "leaf_id": entry["leaf_id"],
                        "source_stage_sha256": entry["source_stage_sha256"],
                        "source_root_seal_sha256": entry[
                            "source_root_seal_sha256"
                        ],
                        "provisional_stage": entry["provisional_stage"],
                    }
                    for entry in resolved_entries
                ]),
                "root_ledger": _sha256(resolved["promoted_root_ledger"]),
                "background_ledger": _sha256(
                    resolved["promoted_background_ledger"]
                ),
                "ordinal_zero_stage": resolved_zero["stage_sha256"],
            },
            preserved,
        )

        plan = build_campaign_plan(
            policy=NumericalPolicy(),
            backend_identity=VettedNativeDeterminantKernel.identity,
            precision_capabilities=PrecisionCapabilities((64, 80, 120)),
        )
        leaf = next(
            item for item in plan.leaves if item.leaf_id == ordinal_one["leaf_id"]
        )
        request_binding = _preview_backend(40).preview_fixed_root_survey_request(
            leaf.job,
            fixed_root=leaf.job.root.omega,
            root_seal_sha256=ordinal_one["source_root_seal_sha256"],
            branch_identity=leaf.job.root.branch_id,
            plan=FixedRootSurveyPlan.CANONICAL_BACKGROUND_FIVE,
        )
        canonical_request, wire_request, request_sha256 = _worker_request_document(
            request_binding
        )
        self.assertEqual(canonical_request["schema"], FIXED_ROOT_SURVEY_BATCH_SCHEMA)
        self.assertEqual(canonical_request["schema_version"], 2)
        self.assertEqual(wire_request["request_sha256"], request_sha256)
        self.assertEqual(wire_request["execution_identity"]["scope"], "REQUEST")
        self.assertNotIn("sample_index", wire_request["execution_identity"])
        self.assertNotIn("sample_role", wire_request["execution_identity"])
        self.assertEqual(
            [sample["sample_index"] for sample in wire_request["samples"]],
            list(range(5)),
        )
        self.assertEqual(resolved_entries[0], entries[0])
        self.assertEqual(resolved_entries[1], entries[1])


if __name__ == "__main__":
    unittest.main()
