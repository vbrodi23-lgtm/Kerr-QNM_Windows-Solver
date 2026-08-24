from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from windows_solver.campaign_policy import (
    EvidenceLevel,
    add_numerical_record,
    empty_schema11_checkpoint,
    record_evidence,
)
from windows_solver.campaign_recovery import (
    RecoverySelection,
    recover_campaign,
    validate_recovery_checkpoint,
    validate_recovery_receipt,
)
from windows_solver.contracts import canonical_json_bytes


def _sha256(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _stage(index: int) -> dict[str, object]:
    content: dict[str, object] = {
        "digits": 40,
        "numerical_state": "BOUNDED",
        "centre": {"real": float(index), "imag": -float(index)},
    }
    return {**content, "stage_sha256": _sha256(content)}


def _record(index: int, *, state: str = "PRODUCED") -> dict[str, object]:
    content: dict[str, object] = {
        "leaf_id": f"leaf-{index:03d}",
        "role": "primary" if index % 2 else "control",
        "state": state,
        "stages": [_stage(index)],
        "computed": state in {"PRODUCED", "UNRESOLVED"},
    }
    return {**content, "record_sha256": _sha256(content)}


def _selection(count: int) -> RecoverySelection:
    leaf_ids = tuple(f"leaf-{index:03d}" for index in range(count))
    return RecoverySelection(
        campaign_id="campaign-1",
        selection_id="selection-1",
        ordered_leaf_ids=leaf_ids,
        roles={
            leaf_id: "primary" if index % 2 else "control"
            for index, leaf_id in enumerate(leaf_ids)
        },
        scientific_identities={
            leaf_id: hashlib.sha256(f"identity:{leaf_id}".encode()).hexdigest()
            for leaf_id in leaf_ids
        },
    )


def _solved_receipt(index: int, selection: RecoverySelection) -> dict[str, object]:
    record = _record(index)
    leaf_id = record["leaf_id"]
    sealed: dict[str, object] = {
        "schema_version": 1,
        "scientific_computation_identity_sha256": (
            selection.scientific_identities[leaf_id]
        ),
        "leaf_id": leaf_id,
        "record": record,
        "canonical_leaf_record_sha256": record["record_sha256"],
        "terminal_state": record["state"],
        "stage_count": 1,
        "created_utc": "2026-01-01T00:00:00Z",
        "source_type": "originating-campaign",
    }
    return {**sealed, "receipt_sha256": _sha256(sealed)}


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json_bytes(value))


class CountAgnosticRecoveryTests(unittest.TestCase):
    def test_zero_sources_creates_empty_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            summary = recover_campaign(
                _selection(50),
                output_path=root / "candidate.json",
                receipt_path=root / "receipt.json",
            )

            self.assertEqual(0, summary.recovered_count)
            candidate = json.loads((root / "candidate.json").read_text())
            self.assertEqual(11, candidate["schema_version"])
            self.assertEqual([], candidate["records"])
            self.assertEqual(0, summary.backend_constructions)
            self.assertEqual(0, summary.julia_launches)
            self.assertEqual(0, summary.determinant_evaluations)
            self.assertEqual(0, summary.root_solves)

    def test_recovers_exactly_one_seven_forty_two_and_arbitrary_n(self) -> None:
        for count in (1, 7, 42, 13):
            with self.subTest(count=count), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                store = root / "store"
                selection = _selection(50)
                expected_records = []
                for index in range(count):
                    receipt = _solved_receipt(index, selection)
                    expected_records.append(receipt["record"])
                    identity = receipt["scientific_computation_identity_sha256"]
                    _write(store / f"{identity}.json", receipt)

                source_hashes = {
                    path: hashlib.sha256(path.read_bytes()).hexdigest()
                    for path in store.glob("*.json")
                }
                summary = recover_campaign(
                    selection,
                    output_path=root / "candidate.json",
                    receipt_path=root / "receipt.json",
                    solved_leaf_stores=(store,),
                )

                candidate = json.loads((root / "candidate.json").read_text())
                self.assertEqual(count, summary.discovered_valid_unique_count)
                self.assertEqual(count, summary.recovered_count)
                self.assertEqual(0, summary.lost_valid_count)
                self.assertEqual(0, summary.fabricated_count)
                self.assertEqual(expected_records, candidate["records"])
                self.assertEqual("PARTIAL", candidate["state"])
                self.assertEqual(
                    source_hashes,
                    {
                        path: hashlib.sha256(path.read_bytes()).hexdigest()
                        for path in store.glob("*.json")
                    },
                )

    def test_source_order_cannot_change_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            selection = _selection(7)
            left = root / "left"
            right = root / "right"
            for index in reversed(range(7)):
                receipt = _solved_receipt(index, selection)
                identity = receipt["scientific_computation_identity_sha256"]
                _write(left / f"{identity}.json", receipt)
            for index in range(7):
                receipt = _solved_receipt(index, selection)
                identity = receipt["scientific_computation_identity_sha256"]
                _write(right / f"{identity}.json", receipt)

            recover_campaign(
                selection,
                output_path=root / "a.json",
                receipt_path=root / "a-receipt.json",
                solved_leaf_stores=(left, right),
            )
            recover_campaign(
                selection,
                output_path=root / "b.json",
                receipt_path=root / "b-receipt.json",
                solved_leaf_stores=(right, left),
            )

            a = json.loads((root / "a.json").read_text())
            b = json.loads((root / "b.json").read_text())
            a["recovery_receipts"] = []
            b["recovery_receipts"] = []
            self.assertEqual(a, b)

    def test_identical_records_union_authenticated_screening_without_rewriting_record(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            selection = _selection(1)
            record = _record(0)
            checkpoint_a = add_numerical_record(
                empty_schema11_checkpoint("campaign-1", "selection-1"), record
            )
            checkpoint_a = record_evidence(
                checkpoint_a,
                leaf_id=record["leaf_id"],
                central_record_sha256=record["record_sha256"],
                central_stage_sha256=record["stages"][0]["stage_sha256"],
                evidence_level=EvidenceLevel.SCREENED,
                receipts=[{"schema": "screening/v1", "source": "a"}],
            )
            checkpoint_b = record_evidence(
                add_numerical_record(
                    empty_schema11_checkpoint("campaign-1", "selection-1"), record
                ),
                leaf_id=record["leaf_id"],
                central_record_sha256=record["record_sha256"],
                central_stage_sha256=record["stages"][0]["stage_sha256"],
                evidence_level=EvidenceLevel.SCREENED,
                receipts=[{"schema": "screening/v1", "source": "b"}],
            )
            _write(root / "a.json", checkpoint_a)
            _write(root / "b.json", checkpoint_b)

            recover_campaign(
                selection,
                output_path=root / "candidate.json",
                receipt_path=root / "receipt.json",
                source_checkpoints=(root / "b.json", root / "a.json"),
            )

            candidate = json.loads((root / "candidate.json").read_text())
            self.assertEqual(record, candidate["records"][0])
            self.assertEqual("COMPLETE", candidate["state"])
            evidence = candidate["evidence_ledger"][record["leaf_id"]]
            self.assertEqual("SCREENED", evidence["evidence_level"])
            self.assertEqual(2, len(evidence["receipts"]))

    def test_conflicting_terminal_records_abort_without_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            selection = _selection(1)
            a = _solved_receipt(0, selection)
            b = _solved_receipt(0, selection)
            changed = dict(b["record"])
            changed["state"] = "UNRESOLVED"
            changed["computed"] = True
            changed["record_sha256"] = _sha256(
                {key: value for key, value in changed.items() if key != "record_sha256"}
            )
            b["record"] = changed
            b["canonical_leaf_record_sha256"] = changed["record_sha256"]
            b["terminal_state"] = "UNRESOLVED"
            b["receipt_sha256"] = _sha256(
                {key: value for key, value in b.items() if key != "receipt_sha256"}
            )
            _write(root / "a" / "a.json", a)
            _write(root / "b" / "b.json", b)

            with self.assertRaisesRegex(ValueError, "conflicting terminal"):
                recover_campaign(
                    selection,
                    output_path=root / "candidate.json",
                    receipt_path=root / "receipt.json",
                    solved_leaf_stores=(root / "a", root / "b"),
                )
            self.assertFalse((root / "candidate.json").exists())
            self.assertFalse((root / "receipt.json").exists())

    def test_corrupt_trusted_receipt_aborts_but_junk_is_reported_and_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            selection = _selection(1)
            store = root / "store"
            _write(store / "notes.json", {"hello": "world"})
            receipt = _solved_receipt(0, selection)
            receipt["receipt_sha256"] = "0" * 64
            identity = receipt["scientific_computation_identity_sha256"]
            _write(store / f"{identity}.json", receipt)

            with self.assertRaisesRegex(ValueError, "outer receipt digest"):
                recover_campaign(
                    selection,
                    output_path=root / "candidate.json",
                    receipt_path=root / "receipt.json",
                    solved_leaf_stores=(store,),
                )

    def test_corrupt_explicit_checkpoint_aborts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.json"
            source.write_text("{broken", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "explicit source checkpoint"):
                recover_campaign(
                    _selection(0),
                    output_path=root / "candidate.json",
                    receipt_path=root / "receipt.json",
                    source_checkpoints=(source,),
                )

    def test_off_selection_and_incompatible_receipts_are_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            selection = _selection(1)
            wider_selection = _selection(2)
            off_selection = _solved_receipt(1, wider_selection)
            incompatible = _solved_receipt(0, selection)
            incompatible["scientific_computation_identity_sha256"] = "d" * 64
            incompatible["receipt_sha256"] = _sha256(
                {
                    key: value
                    for key, value in incompatible.items()
                    if key != "receipt_sha256"
                }
            )
            _write(root / "store" / "off.json", off_selection)
            _write(root / "store" / "incompatible.json", incompatible)

            summary = recover_campaign(
                selection,
                output_path=root / "candidate.json",
                receipt_path=root / "receipt.json",
                solved_leaf_stores=(root / "store",),
            )

            self.assertEqual(0, summary.recovered_count)
            self.assertEqual(2, summary.ignored_count)

    def test_cli_recovery_builds_no_backend(self) -> None:
        from windows_solver.cli import _campaign_recover
        from windows_solver.campaign_reports import report_directory_for_checkpoint

        leaf = SimpleNamespace(
            leaf_id="leaf-000",
            role="control",
            mechanism_id="exterior-light-ring",
            leaf=SimpleNamespace(mode_label="220"),
            job=SimpleNamespace(spin=0.9),
        )
        plan = SimpleNamespace(campaign_id="campaign-1", leaves=(leaf,))
        selection = SimpleNamespace(
            selection_id="selection-1", leaf_ids=("leaf-000",)
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with (
                patch(
                    "windows_solver.cli._campaign_plan_and_selection",
                    return_value=(plan, selection, None),
                ),
                patch(
                    "windows_solver.cli.scientific_computation_identity_sha256",
                    return_value="c" * 64,
                ),
                patch("windows_solver.cli._load_campaign_backend") as backend,
                patch("windows_solver.cli.Path.cwd", return_value=root),
            ):
                status, output = _campaign_recover(
                    Path("selection.json"),
                    Path("candidate.json"),
                    Path("receipt.json"),
                    source_checkpoints=(),
                    solved_leaf_stores=(),
                    root_readout_stores=(),
                    oracle_path=None,
                )
                candidate = root / "candidate.json"
                reports = report_directory_for_checkpoint(candidate)
                report_names = (
                    "m02-leaves.csv",
                    "m02-precision-stages.csv",
                    "m02-error-channels.csv",
                    "m02-resource-failures.csv",
                )
                self.assertTrue(
                    all((reports / name).is_file() for name in report_names)
                )
                recovered = validate_recovery_checkpoint(_selection(1), candidate)
                validate_recovery_receipt(
                    _selection(1), candidate, root / "receipt.json"
                )

        self.assertEqual(0, status)
        self.assertEqual(0, output["backend_constructions"])
        self.assertEqual(
            "COMPLETED",
            recovered["report_status_receipt"]["basic"]["status"],
        )
        backend.assert_not_called()

    def test_recovered_candidate_validates_from_disk(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            selection = _selection(1)
            store = root / "store"
            solved = _solved_receipt(0, selection)
            identity = solved["scientific_computation_identity_sha256"]
            _write(store / f"{identity}.json", solved)
            recover_campaign(
                selection,
                output_path=root / "candidate.json",
                receipt_path=root / "receipt.json",
                solved_leaf_stores=(store,),
            )

            validated = validate_recovery_checkpoint(
                selection, root / "candidate.json"
            )
            receipt = validate_recovery_receipt(
                selection, root / "candidate.json", root / "receipt.json"
            )

            self.assertEqual(1, len(validated["records"]))
            self.assertEqual(
                hashlib.sha256((root / "candidate.json").read_bytes()).hexdigest(),
                receipt["output_sha256"],
            )


if __name__ == "__main__":
    unittest.main()
