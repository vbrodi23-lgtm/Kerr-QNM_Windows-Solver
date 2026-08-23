from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from windows_solver.campaign_recovery import RecoverySelection
from windows_solver.campaign_survey import dispatch_cache_first
from windows_solver.contracts import canonical_json_bytes
from windows_solver.solved_leaf_cache import (
    SolvedLeafLookupStatus,
    SolvedLeafStore,
)


def _sha256(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _record(leaf_id: str) -> dict[str, object]:
    stage_content: dict[str, object] = {
        "digits": 64,
        "numerical_state": "BOUNDED",
    }
    stage = {**stage_content, "stage_sha256": _sha256(stage_content)}
    content: dict[str, object] = {
        "leaf_id": leaf_id,
        "role": "primary",
        "state": "PRODUCED",
        "stages": [stage],
        "computed": True,
    }
    return {**content, "record_sha256": _sha256(content)}


def _selection(count: int) -> RecoverySelection:
    leaf_ids = tuple(f"leaf-{index}" for index in range(count))
    return RecoverySelection(
        campaign_id="campaign-1",
        selection_id="selection-1",
        ordered_leaf_ids=leaf_ids,
        roles={leaf_id: "primary" for leaf_id in leaf_ids},
        scientific_identities={
            leaf_id: hashlib.sha256(leaf_id.encode()).hexdigest()
            for leaf_id in leaf_ids
        },
    )


class CacheFirstSurveyTests(unittest.TestCase):
    def test_exact_hits_write_byte_identical_records_without_backend(self) -> None:
        selection = _selection(2)
        backend_factory = Mock(side_effect=AssertionError("backend constructed"))
        execute_misses = Mock(side_effect=AssertionError("numerics executed"))
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = SolvedLeafStore(root / "store")
            expected = []
            for leaf_id in selection.ordered_leaf_ids:
                record = _record(leaf_id)
                expected.append(record)
                store.publish(
                    scientific_identity_sha256=(
                        selection.scientific_identities[leaf_id]
                    ),
                    leaf_id=leaf_id,
                    record=record,
                    source_type="originating-campaign",
                )

            outcome = dispatch_cache_first(
                selection,
                store,
                checkpoint_path=root / "checkpoint.json",
                backend_factory=backend_factory,
                execute_misses=execute_misses,
            )

            checkpoint = json.loads((root / "checkpoint.json").read_text())
            self.assertTrue(outcome.cache_complete)
            self.assertEqual(expected, checkpoint["records"])
            self.assertEqual("COMPLETE", checkpoint["state"])
            self.assertEqual(
                {"leaf-0", "leaf-1"},
                set(checkpoint["survey_pass_ledger"]["binary64"]),
            )
            backend_factory.assert_not_called()
            execute_misses.assert_not_called()

    def test_cache_miss_constructs_backend_only_after_read_only_scan(self) -> None:
        selection = _selection(1)
        backend = object()
        backend_factory = Mock(return_value=backend)
        execute_misses = Mock(return_value="executed")
        with tempfile.TemporaryDirectory() as temporary:
            outcome = dispatch_cache_first(
                selection,
                SolvedLeafStore(Path(temporary) / "store"),
                checkpoint_path=Path(temporary) / "checkpoint.json",
                backend_factory=backend_factory,
                execute_misses=execute_misses,
            )

        self.assertFalse(outcome.cache_complete)
        self.assertEqual("executed", outcome.execution_result)
        backend_factory.assert_called_once_with()
        execute_misses.assert_called_once_with(backend)

    def test_read_only_corruption_check_does_not_quarantine_trusted_receipt(self) -> None:
        selection = _selection(1)
        leaf_id = selection.ordered_leaf_ids[0]
        identity = selection.scientific_identities[leaf_id]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = SolvedLeafStore(root)
            path = store.publish(
                scientific_identity_sha256=identity,
                leaf_id=leaf_id,
                record=_record(leaf_id),
                source_type="originating-campaign",
            )
            receipt = json.loads(path.read_text())
            receipt["receipt_sha256"] = "0" * 64
            path.write_bytes(canonical_json_bytes(receipt))

            lookup = store.lookup_readonly(identity, leaf_id)

            self.assertIs(SolvedLeafLookupStatus.CORRUPT, lookup.status)
            self.assertTrue(path.exists())
            self.assertFalse((root / "quarantine").exists())


if __name__ == "__main__":
    unittest.main()
