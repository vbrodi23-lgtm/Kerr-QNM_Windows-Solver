from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import unittest

from windows_solver.campaign_policy import empty_schema11_checkpoint
from windows_solver.cli import _campaign_plan_and_selection
from windows_solver.contracts import canonical_json_bytes
from windows_solver.m03_handoff import (
    _m02_domega_bundle,
    build_handoff,
    validate_handoff,
)


SELECTION = Path(__file__).resolve().parents[1] / "examples" / "m02-campaign.json"


def _sha(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _record(leaf_id: str, root_identity: str | None = None) -> dict[str, object]:
    material: dict[str, object] = {
        "leaf_id": leaf_id,
        "state": "PRODUCED",
        "stages": [],
    }
    if root_identity is not None:
        material["lineage"] = {"root_identity_sha256": root_identity}
    return {**material, "record_sha256": _sha(material)}


def _binary64_entry(leaf_id: str, record_sha: str) -> dict[str, object]:
    material = {
        "leaf_id": leaf_id,
        "pass": "binary64",
        "source_record_sha256": None,
        "result_record_sha256": record_sha,
        "operation_identity": f"fixture:{leaf_id}",
        "precision_tiers": ["binary64"],
        "reason_code": "COMPLETED",
        "sample_count": 0,
        "sample_limit": 0,
        "root_read_count": 0,
        "root_read_limit": 0,
        "worker_launch_count": 0,
        "worker_launch_limit": 0,
        "tier_timing": [],
        "session_fragments": [],
        "disposition": "COMPLETED",
    }
    return {**material, "disposition_receipt_sha256": _sha(material)}


def _terminal_fixture():
    plan, selection, _ = _campaign_plan_and_selection(SELECTION)
    checkpoint = empty_schema11_checkpoint(plan.campaign_id, selection.selection_id)
    records = []
    binary64 = {}
    for leaf in plan.leaves:
        record = _record(leaf.leaf_id, leaf.job.root.identity_sha256)
        records.append(record)
        binary64[leaf.leaf_id] = _binary64_entry(
            leaf.leaf_id, record["record_sha256"]
        )
    checkpoint["records"] = records
    checkpoint["survey_pass_ledger"]["binary64"] = binary64
    checkpoint["state"] = "COMPLETE"
    return plan, selection, checkpoint


class M03HandoffTests(unittest.TestCase):
    def test_complete_exterior_stencil_is_reduced_from_raw_receipts(self) -> None:
        root_identity = "a" * 64
        leaf_id = "leaf-with-exterior-stencil"
        roles = (
            ("frequency-real-plus-h", "10.2", "3"),
            ("frequency-real-minus-h", "9.8", "-1"),
            ("frequency-real-plus-h2", "10.1", "2"),
            ("frequency-real-minus-h2", "9.9", "0"),
        )
        samples = []
        for role, omega_real, determinant_real in roles:
            response = {
                "status": "ok",
                "readout_role": role,
                "omega_re": omega_real,
                "omega_im": "-1",
                "determinant_re": determinant_real,
                "determinant_im": "0",
            }
            receipt = {
                "response_binding": response,
                "response_sha256": _sha(response),
            }
            samples.append(
                {
                    "readout_role": role,
                    "precision_tier": "bigfloat-40",
                    "working_precision_bits": 165,
                    "determinant_family": "exterior-wronskian/v1",
                    "determinant_normalisation": (
                        "unit-asymptotic-branch-wronskian/v1"
                    ),
                    "worker_response_receipt": receipt,
                    "worker_response_receipt_sha256": _sha(receipt),
                }
            )
        stage = {
            "stage_sha256": "b" * 64,
            "component_result": {
                "result": {
                    "leaf_id": leaf_id,
                    "baseline": {
                        "numerical_conditioning": {
                            "determinant_convention": (
                                "wronskian-perturbed-Xin-with-Xup/v1"
                            )
                        },
                        "primary_acceptance": {
                            "determinant_re": "1",
                            "determinant_im": "0",
                        },
                    },
                    "derivative_evidence": {
                        "fixed_root_samples": samples
                    },
                }
            },
        }
        background = {
            "reuse_key": {
                "root_identity": root_identity,
                "background_operation_identity": (
                    "canonical-exterior-background-wronskian/v1"
                ),
            }
        }
        checkpoint = {
            "promotion_queue": {
                "entries": [
                    {
                        "leaf_id": leaf_id,
                        "provisional_stage": {
                            "canonical_background": background
                        },
                    }
                ]
            }
        }

        background_sha, evidence = _m02_domega_bundle(
            checkpoint=checkpoint,
            records=[{"leaf_id": leaf_id, "stages": [stage]}],
            root_identity=root_identity,
            frozen_omega={"real": "10", "imaginary": "-1"},
        )

        self.assertEqual(background_sha, _sha(background))
        self.assertEqual(
            evidence["coarse_derivative"],
            {"real": "1E+1", "imaginary": "0E+1"},
        )
        self.assertEqual(
            evidence["fine_derivative"],
            {"real": "1E+1", "imaginary": "0E+1"},
        )
        self.assertEqual(evidence["disagreement_abs"], "0E+1")
        self.assertEqual(
            evidence["request_sha256"],
            _sha(
                {
                    key: value
                    for key, value in evidence.items()
                    if key != "request_sha256"
                }
            ),
        )

    def test_valid_handoff_collapses_212_leaves_to_48_roots(self) -> None:
        plan, selection, checkpoint = _terminal_fixture()

        handoff = build_handoff(
            plan=plan,
            selection=selection,
            checkpoint=checkpoint,
            checkpoint_path="m02-output/m02-campaign-checkpoint.json",
            created_utc="2026-08-31T00:00:00Z",
        )

        self.assertEqual(handoff["inventory"]["source_leaf_count"], 212)
        self.assertEqual(handoff["inventory"]["node_count"], 48)
        self.assertEqual(handoff["inventory"]["branch_count"], 11)
        self.assertEqual(len(handoff["nodes"]), 48)
        self.assertEqual(len(handoff["branches"]), 11)
        self.assertEqual(validate_handoff(handoff), handoff)
        self.assertNotIn("mechanism_id", json.dumps(handoff["nodes"][0]["spectral_seed"]))

    def test_conflicting_leaf_for_shared_root_fails_closed(self) -> None:
        plan, selection, checkpoint = _terminal_fixture()
        first_root = plan.leaves[0].job.root.identity_sha256
        same_root = [
            leaf for leaf in plan.leaves
            if leaf.job.root.identity_sha256 == first_root
        ]
        record = next(
            item for item in checkpoint["records"]
            if item["leaf_id"] == same_root[-1].leaf_id
        )
        record["lineage"]["root_identity_sha256"] = "0" * 64
        record["record_sha256"] = _sha(
            {key: value for key, value in record.items() if key != "record_sha256"}
        )
        checkpoint["survey_pass_ledger"]["binary64"][record["leaf_id"]] = (
            _binary64_entry(record["leaf_id"], record["record_sha256"])
        )

        with self.assertRaisesRegex(ValueError, "disagree.*common root identity"):
            build_handoff(
                plan=plan,
                selection=selection,
                checkpoint=checkpoint,
                checkpoint_path="checkpoint.json",
            )

    def test_incomplete_terminal_inventory_is_rejected(self) -> None:
        plan, selection, checkpoint = _terminal_fixture()
        removed = checkpoint["records"].pop()
        del checkpoint["survey_pass_ledger"]["binary64"][removed["leaf_id"]]

        with self.assertRaisesRegex(ValueError, "exactly 212 leaves"):
            build_handoff(
                plan=plan,
                selection=selection,
                checkpoint=checkpoint,
                checkpoint_path="checkpoint.json",
            )

    def test_corrupted_m02_record_is_rejected(self) -> None:
        plan, selection, checkpoint = _terminal_fixture()
        checkpoint["records"][0]["state"] = "UNRESOLVED"

        with self.assertRaisesRegex(ValueError, "record digest"):
            build_handoff(
                plan=plan,
                selection=selection,
                checkpoint=checkpoint,
                checkpoint_path="checkpoint.json",
            )

    def test_textually_different_numeric_identity_is_rejected(self) -> None:
        plan, selection, checkpoint = _terminal_fixture()
        handoff = build_handoff(
            plan=plan,
            selection=selection,
            checkpoint=checkpoint,
            checkpoint_path="checkpoint.json",
            created_utc="2026-08-31T00:00:00Z",
        )
        changed = copy.deepcopy(handoff)
        omega = changed["nodes"][0]["spectral_seed"]["frozen_eigenvalue"]["omega"]
        omega["real"] = omega["real"] + "0"
        material = {key: value for key, value in changed.items() if key != "handoff_sha256"}
        changed["handoff_sha256"] = _sha(material)

        with self.assertRaisesRegex(ValueError, "textually different"):
            validate_handoff(changed)

    def test_wrong_branch_count_is_rejected_even_when_resealed(self) -> None:
        plan, selection, checkpoint = _terminal_fixture()
        handoff = build_handoff(
            plan=plan,
            selection=selection,
            checkpoint=checkpoint,
            checkpoint_path="checkpoint.json",
            created_utc="2026-08-31T00:00:00Z",
        )
        changed = copy.deepcopy(handoff)
        changed["branches"].pop()
        changed["inventory"]["branch_count"] = 10
        material = {key: value for key, value in changed.items() if key != "handoff_sha256"}
        changed["handoff_sha256"] = _sha(material)

        with self.assertRaisesRegex(ValueError, "conservation"):
            validate_handoff(changed)


if __name__ == "__main__":
    unittest.main()
