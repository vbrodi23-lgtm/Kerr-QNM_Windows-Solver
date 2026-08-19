from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from windows_solver.contracts import canonical_json_bytes
from windows_solver.partial_component_checkpoint import (
    PartialComponentEntry,
    PartialComponentJournal,
    PartialComponentWorkUnit,
    run_partial_component_work,
)
from windows_solver.precision_tiers import PrecisionTier


def entry(
    *,
    receipt_status: str = "accepted",
    receipt: dict[str, object] | None = None,
    readout_role: str = "baseline-root",
) -> PartialComponentEntry:
    if receipt is None:
        receipt = {"determinant": {"imaginary": -2.0, "real": 1.0}, "status": receipt_status}
    return PartialComponentEntry(
        component_scientific_identity="component/v2",
        leaf_id="leaf-222",
        job_id="job-horizon",
        policy_sha256="1" * 64,
        backend_identity="julia-gsn/v1",
        determinant_family="gsn-factored",
        determinant_normalisation="cinc-over-cref-minus-r/v1",
        precision_tier=PrecisionTier.BIGFLOAT_40,
        mpfr_bits=165,
        amplitude=0.0j,
        epsilon=0.0,
        readout_role=readout_role,
        refinement_level=0,
        request_sha256="2" * 64,
        worker_response_receipt=receipt,
        worker_response_receipt_sha256=hashlib.sha256(canonical_json_bytes(receipt)).hexdigest(),
    )


class PartialComponentCheckpointTests(unittest.TestCase):
    def test_interruption_resume_reuses_every_exact_expensive_work_unit(self) -> None:
        roles = (
            "baseline-root",
            "fixed-root-determinant-sample",
            "variational-derivative-solve",
            "direct-derivative-stencil-sample",
            "signed-validation-root",
            "diagnostic-readout",
        )
        units = tuple(
            PartialComponentWorkUnit.from_entry(entry(readout_role=role))
            for role in roles
        )
        calls: list[str] = []

        def execute(unit: PartialComponentWorkUnit) -> dict[str, object]:
            calls.append(unit.readout_role)
            if len(calls) == 3:
                raise KeyboardInterrupt("deliberate stop")
            return {"readout_role": unit.readout_role, "status": "accepted"}

        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "partial.json"
            journal = PartialComponentJournal.create(
                path,
                expected_work_unit_ids=tuple(unit.work_unit_id for unit in units),
            )
            with self.assertRaisesRegex(KeyboardInterrupt, "deliberate stop"):
                run_partial_component_work(journal, units, execute)
            self.assertEqual(calls, list(roles[:3]))

            resumed_calls: list[str] = []
            completed, evidence = run_partial_component_work(
                PartialComponentJournal.load(path),
                units,
                lambda unit: (
                    resumed_calls.append(unit.readout_role)
                    or {"readout_role": unit.readout_role, "status": "accepted"}
                ),
            )
            self.assertEqual(resumed_calls, list(roles[2:]))
            self.assertEqual(evidence.reused_work_unit_ids, tuple(unit.work_unit_id for unit in units[:2]))
            self.assertEqual(evidence.executed_work_unit_ids, tuple(unit.work_unit_id for unit in units[2:]))
            self.assertEqual(tuple(item.readout_role for item in completed), roles)
            self.assertTrue(PartialComponentJournal.load(path).complete)

    def test_atomic_resume_reuses_exact_entry_and_serializes_canonically(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "partial.json"
            first = entry()
            journal = PartialComponentJournal.create(path, expected_work_unit_ids=(first.work_unit_id, "f" * 64))
            journal.record(first)

            resumed = PartialComponentJournal.load(path)
            resumed.record(first)
            self.assertEqual(resumed.missing_work_unit_ids(), ("f" * 64,))
            stored_entry = json.loads(path.read_bytes())["entries"][first.work_unit_id]
            self.assertEqual(stored_entry["precision_tier"], "bigfloat-40")
            self.assertEqual(stored_entry["nominal_decimal_digits"], 40)
            self.assertEqual(stored_entry["mpfr_bits"], 165)
            self.assertEqual(path.read_bytes(), canonical_json_bytes(json.loads(path.read_bytes())))
            self.assertEqual(list(path.parent.glob(f".{path.name}.*.tmp")), [])

    def test_conflicting_receipt_for_same_work_unit_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "partial.json"
            first = entry()
            journal = PartialComponentJournal.create(path, expected_work_unit_ids=(first.work_unit_id,))
            journal.record(first)
            conflicting = entry(receipt_status="rejected")
            self.assertEqual(conflicting.work_unit_id, first.work_unit_id)
            with self.assertRaisesRegex(ValueError, "conflicts with durable evidence"):
                journal.record(conflicting)

    def test_failed_atomic_replace_does_not_advance_in_memory_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "partial.json"
            first = entry()
            journal = PartialComponentJournal.create(path, expected_work_unit_ids=(first.work_unit_id,))
            with patch("windows_solver.partial_component_checkpoint.os.replace", side_effect=OSError("blocked")):
                with self.assertRaisesRegex(OSError, "blocked"):
                    journal.record(first)
            self.assertEqual(journal.missing_work_unit_ids(), (first.work_unit_id,))
            self.assertEqual(PartialComponentJournal.load(path).missing_work_unit_ids(), (first.work_unit_id,))

    def test_nested_caller_mutation_cannot_corrupt_a_later_journal_write(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "partial.json"
            source = {
                "determinant": {"imaginary": -2.0, "real": 1.0},
                "samples": [{"radius": 1.0e-12}],
                "status": "accepted",
            }
            first = entry(receipt=source)
            second = entry(readout_role="diagnostic-readout")
            journal = PartialComponentJournal.create(
                path,
                expected_work_unit_ids=(first.work_unit_id, second.work_unit_id),
            )
            journal.record(first)
            source["determinant"]["real"] = 99.0
            source["samples"].append({"radius": 1.0})
            journal.record(second)

            resumed = PartialComponentJournal.load(path)
            stored = resumed.entries[first.work_unit_id].to_mapping()["worker_response_receipt"]
            self.assertEqual(stored["determinant"]["real"], 1.0)
            self.assertEqual(stored["samples"], [{"radius": 1.0e-12}])

    def test_entry_receipt_is_deeply_immutable(self) -> None:
        first = entry()
        with self.assertRaises(TypeError):
            first.worker_response_receipt["determinant"]["real"] = 99.0


if __name__ == "__main__":
    unittest.main()
