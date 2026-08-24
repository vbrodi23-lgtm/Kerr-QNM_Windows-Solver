"""PR66 R1: historical schema-9 recovery is honest and cardinality-agnostic."""

from __future__ import annotations

import copy
import hashlib
import json
import lzma
from pathlib import Path
import subprocess
import tempfile
import unittest

from windows_solver.campaign_recovery import RecoverySelection, recover_campaign
from windows_solver.contracts import canonical_json_bytes
from windows_solver.native_response_kernel import VettedNativeDeterminantKernel
from windows_solver.response_batches import (
    CampaignLeafRecord,
    CampaignStageRecord,
    PrecisionCapabilities,
    StageOutcome,
    build_campaign_plan,
    build_campaign_selection,
    synthetic_stage_signed_error_channels,
    validate_campaign_recovery_record,
)
from windows_solver.response_engine import NumericalPolicy


FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "m02_schema9_production_checkpoint.json.xz"
)
HISTORICAL_FIXTURE_COMMIT = "1fce3d893c1ac375967e7f7b03f0f675930f1dcc"
FIXTURE_SHA256 = "b0f87521f9b9a1223fadca2eca519f6bc9a2aeb5e18bf8f590d5f8cc87979b01"
TERMINAL_STATES = {"PRODUCED", "UNRESOLVED", "REJECTED"}


def _sha256(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _fixture() -> dict[str, object]:
    return json.loads(lzma.decompress(FIXTURE.read_bytes()))


def _write(path: Path, value: object) -> None:
    path.write_bytes(canonical_json_bytes(value))


def _selection_for_schema9(
    fixture: dict[str, object], leaf_ids: tuple[str, ...]
) -> RecoverySelection:
    bindings = fixture["bindings"]
    assert isinstance(bindings, dict)
    source_selection = bindings["selection"]
    assert isinstance(source_selection, dict)
    records_by_id = {record["leaf_id"]: record for record in fixture["records"]}
    return RecoverySelection(
        campaign_id=str(bindings["campaign_id"]),
        selection_id=str(source_selection["selection_id"]),
        ordered_leaf_ids=leaf_ids,
        roles={leaf_id: str(records_by_id[leaf_id]["role"]) for leaf_id in leaf_ids},
        scientific_identities={
            leaf_id: hashlib.sha256(f"current:{leaf_id}".encode()).hexdigest()
            for leaf_id in leaf_ids
        },
    )


def _synthetic_schema9(fixture: dict[str, object], count: int) -> dict[str, object]:
    """Make a deterministic schema-9-shaped count test from real record shape."""

    source = copy.deepcopy(fixture)
    bindings = source["bindings"]
    assert isinstance(bindings, dict)
    source_selection = bindings["selection"]
    assert isinstance(source_selection, dict)
    all_leaf_ids = tuple(source_selection["leaf_ids"])
    assert count <= len(all_leaf_ids)
    template = next(record for record in source["records"] if record["state"] == "PRODUCED")
    runner_provenance = template["stages"][0]["runner_provenance"]
    records: list[dict[str, object]] = []
    for leaf_id in all_leaf_ids[:count]:
        component_result = {
            "leaf_id": leaf_id,
            "kind": "synthetic-schema9-cardinality-regression",
        }
        outcome = StageOutcome(
            digits=64,
            numerical_state="SYNTHETIC",
            component_result=component_result,
            local_disk_radius_abs=0.0,
            signed_error_channels=synthetic_stage_signed_error_channels(
                component_result, 0.0
            ),
        )
        stage = CampaignStageRecord(
            outcome,
            copy.deepcopy(runner_provenance),
        )
        record = CampaignLeafRecord(
            leaf_id=leaf_id,
            role="primary",
            state="PRODUCED",
            stages=(stage,),
        )
        records.append(record.to_mapping())
    source["records"] = records
    source["records_sha256"] = _sha256(records)
    source["attempts"] = []
    source["attempts_sha256"] = _sha256([])
    source["state"] = "PARTIAL" if count < len(all_leaf_ids) else "COMPLETE"
    return source


class LegacySchema9RecoveryTests(unittest.TestCase):
    def test_real_historical_fixture_is_authenticated_but_not_relabelled(self) -> None:
        """The real artifact has 40 terminal records, none current-compatible."""

        self.assertEqual(
            FIXTURE_SHA256, hashlib.sha256(FIXTURE.read_bytes()).hexdigest()
        )
        historical = subprocess.run(
            [
                "git",
                "show",
                f"{HISTORICAL_FIXTURE_COMMIT}:"
                "tests/fixtures/m02_schema9_production_checkpoint.json.xz",
            ],
            cwd=Path(__file__).resolve().parents[1],
            check=True,
            capture_output=True,
        ).stdout
        self.assertEqual(historical, FIXTURE.read_bytes())

        source_fixture = _fixture()
        states = [record["state"] for record in source_fixture["records"]]
        self.assertEqual(41, len(states))
        self.assertEqual(39, states.count("PRODUCED"))
        self.assertEqual(1, states.count("UNRESOLVED"))
        self.assertEqual(1, states.count("IN_PROGRESS"))
        self.assertEqual(40, sum(state in TERMINAL_STATES for state in states))

        plan = build_campaign_plan(
            policy=NumericalPolicy(),
            backend_identity=VettedNativeDeterminantKernel.identity,
            precision_capabilities=PrecisionCapabilities((64, 80, 120)),
        )
        selection = build_campaign_selection(plan, role="all")
        recovery = RecoverySelection(
            campaign_id=plan.campaign_id,
            selection_id=selection.selection_id,
            ordered_leaf_ids=tuple(selection.leaf_ids),
            roles={leaf.leaf_id: leaf.role for leaf in plan.leaves},
            scientific_identities={
                leaf.leaf_id: hashlib.sha256(
                    leaf.leaf_id.encode("utf-8")
                ).hexdigest()
                for leaf in plan.leaves
            },
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "schema9.json"
            _write(source, source_fixture)
            summary = recover_campaign(
                recovery,
                output_path=root / "candidate.json",
                receipt_path=root / "receipt.json",
                source_checkpoints=(source,),
                record_validator=lambda leaf_id, record: validate_campaign_recovery_record(
                    plan, leaf_id, record
                ),
            )
            candidate = json.loads((root / "candidate.json").read_text())
            receipt = json.loads((root / "receipt.json").read_text())

        compatibility = [
            item
            for item in candidate["recovery_receipts"]
            if item.get("schema") == "legacy-compatibility/v1"
        ]
        self.assertEqual(40, summary.legacy_authenticated_terminal_count)
        self.assertEqual(0, summary.legacy_imported_count)
        self.assertEqual(0, summary.legacy_unreconstructable_count)
        self.assertEqual([], candidate["records"])
        self.assertEqual({}, candidate["evidence_ledger"])
        self.assertEqual(40, len(compatibility))
        self.assertTrue(all(
            item["original_record_status"] == "AUTHENTICATED"
            and item["imported_as_current_numerical_record"] is False
            and item["schema11_evidence_level"] is None
            and item["reason"] == "CURRENT_SCIENTIFIC_IDENTITY_INCOMPATIBLE"
            for item in compatibility
        ))
        self.assertEqual("NOT_SUPPLIED", receipt["oracle_status"])
        self.assertEqual("NOT_SUPPLIED", receipt["canary_x9_status"])
        self.assertEqual(
            {
                "legacy_authenticated_terminal_records": 40,
                "legacy_current_compatible_records": 0,
                "legacy_reused_records": 0,
                "legacy_rejected_records": 40,
            },
            {
                key: receipt["discovery_counts"][key]
                for key in (
                    "legacy_authenticated_terminal_records",
                    "legacy_current_compatible_records",
                    "legacy_reused_records",
                    "legacy_rejected_records",
                )
            },
        )
        self.assertEqual(
            (0, 0, 0, 0),
            tuple(
                receipt[name]
                for name in (
                    "backend_constructions",
                    "julia_launches",
                    "determinant_evaluations",
                    "root_solves",
                )
            ),
        )

    def test_schema9_recovery_is_cardinality_agnostic(self) -> None:
        """EMPTY, one, mixed-scale, and atlas-scale sources use one adapter."""

        original = _fixture()
        source_leaf_ids = tuple(original["bindings"]["selection"]["leaf_ids"])
        for count in (0, 1, 7, 20, 42, 212):
            with self.subTest(count=count), tempfile.TemporaryDirectory() as temporary:
                fixture = _synthetic_schema9(original, count)
                selected = source_leaf_ids[:count]
                recovery = _selection_for_schema9(fixture, selected)
                root = Path(temporary)
                source = root / "schema9.json"
                _write(source, fixture)
                summary = recover_campaign(
                    recovery,
                    output_path=root / "candidate.json",
                    receipt_path=root / "receipt.json",
                    source_checkpoints=(source,),
                    record_validator=lambda _leaf_id, _record: None,
                )
                candidate = json.loads((root / "candidate.json").read_text())
                receipt = json.loads((root / "receipt.json").read_text())

                compatibility = [
                    item
                    for item in candidate["recovery_receipts"]
                    if item.get("schema") == "legacy-compatibility/v1"
                ]
                self.assertEqual(count, summary.legacy_authenticated_terminal_count)
                self.assertEqual(count, summary.legacy_imported_count)
                self.assertEqual(0, summary.legacy_unreconstructable_count)
                self.assertEqual(count, len(candidate["records"]))
                self.assertEqual(count, len(compatibility))
                self.assertEqual(count, receipt["discovery_counts"]["legacy_current_compatible_records"])
                self.assertEqual(count, receipt["discovery_counts"]["legacy_reused_records"])
                self.assertEqual(0, receipt["discovery_counts"]["legacy_rejected_records"])
                self.assertTrue(all(
                    item["imported_as_current_numerical_record"] is True
                    and item["schema11_evidence_level"] is None
                    for item in compatibility
                ))

    def test_wrong_selection_ambiguous_source_and_trusted_corruption_are_distinct(self) -> None:
        """Nonmatches are counted; trusted corruption remains a hard failure."""

        original = _fixture()
        source_leaf_ids = tuple(original["bindings"]["selection"]["leaf_ids"])
        base = _synthetic_schema9(original, 1)
        selected = source_leaf_ids[:1]
        recovery = _selection_for_schema9(base, selected)

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            wrong_selection = copy.deepcopy(base)
            wrong_selection["bindings"]["selection"]["selection_id"] = "wrong"
            source = root / "wrong-selection.json"
            _write(source, wrong_selection)
            summary = recover_campaign(
                recovery,
                output_path=root / "candidate.json",
                receipt_path=root / "receipt.json",
                source_checkpoints=(source,),
                record_validator=lambda _leaf_id, _record: None,
            )
            candidate = json.loads((root / "candidate.json").read_text())
            compatibility = next(
                item
                for item in candidate["recovery_receipts"]
                if item.get("schema") == "legacy-compatibility/v1"
            )
            self.assertEqual(1, summary.recovered_count)
            self.assertIsNone(compatibility["reason"])
            self.assertFalse(compatibility["source_selection_matches_current"])
            self.assertTrue(compatibility["imported_as_current_numerical_record"])

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            ambiguous = copy.deepcopy(base)
            ambiguous["records"].append(copy.deepcopy(ambiguous["records"][0]))
            ambiguous["records_sha256"] = _sha256(ambiguous["records"])
            source = root / "ambiguous.json"
            _write(source, ambiguous)
            summary = recover_campaign(
                recovery,
                output_path=root / "candidate.json",
                receipt_path=root / "receipt.json",
                source_checkpoints=(source,),
                record_validator=lambda _leaf_id, _record: None,
            )
            candidate = json.loads((root / "candidate.json").read_text())
            compatibility = [
                item
                for item in candidate["recovery_receipts"]
                if item.get("schema") == "legacy-compatibility/v1"
            ]
            self.assertEqual(0, summary.recovered_count)
            self.assertEqual(2, summary.legacy_authenticated_terminal_count)
            self.assertEqual(2, summary.legacy_unreconstructable_count)
            self.assertEqual(
                {"AMBIGUOUS_LEGACY_RECONSTRUCTION"},
                {item["reason"] for item in compatibility},
            )

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            corrupt = copy.deepcopy(base)
            corrupt["records"][0]["record_sha256"] = "0" * 64
            corrupt["records_sha256"] = _sha256(corrupt["records"])
            source = root / "corrupt.json"
            _write(source, corrupt)
            with self.assertRaisesRegex(ValueError, "explicit source checkpoint is corrupt"):
                recover_campaign(
                    recovery,
                    output_path=root / "candidate.json",
                    receipt_path=root / "receipt.json",
                    source_checkpoints=(source,),
                    record_validator=lambda _leaf_id, _record: None,
                )
            self.assertFalse((root / "candidate.json").exists())
            self.assertFalse((root / "receipt.json").exists())


if __name__ == "__main__":
    unittest.main()
