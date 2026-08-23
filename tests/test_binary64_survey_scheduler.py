from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from windows_solver.campaign_policy import empty_schema11_checkpoint
from windows_solver.campaign_failures import CampaignSystemFailure
from windows_solver.campaign_recovery import RecoverySelection
from windows_solver.campaign_timing import CampaignTimingLog
from windows_solver.campaign_survey import (
    AuthenticatedRootSeal,
    Binary64PassOutcome,
    run_binary64_survey,
)
from windows_solver.contracts import canonical_json_bytes
from windows_solver.response_batches import (
    PrecisionCapabilities,
    build_campaign_plan,
    build_campaign_selection,
    scientific_computation_identity_sha256,
)
from windows_solver.response_engine import (
    BackgroundEquivalenceReceipt,
    Binary64SurveyDisposition,
    NumericalPolicy,
    VettedNativeDeterminantKernel,
)


def _sha256(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _record(leaf_id: str, response: complex = 1.0j):
    stage_content = {
        "schema": "windows-solver.test-binary64-stage/1",
        "response": {"real": response.real, "imaginary": response.imag},
    }
    stage = {**stage_content, "stage_sha256": _sha256(stage_content)}
    content = {
        "leaf_id": leaf_id,
        "state": "PRODUCED",
        "stages": [stage],
    }
    return {**content, "record_sha256": _sha256(content)}, stage["stage_sha256"]


class _AnalyticBackend(VettedNativeDeterminantKernel):
    def __init__(self, *, flat_frequency: bool = False) -> None:
        self.flat_frequency = flat_frequency
        self.current_root = 0.0j
        self.determinant_calls = 0
        self.root_reads = 0
        self.julia_launches = 0

    def _standard_sn(self, job, policy):
        self.current_root = job.root.omega
        return object()

    def _determinant(self, sn, omega, perturbation, policy):
        self.determinant_calls += 1
        amplitude = getattr(perturbation, "amplitude", 0.0j)
        frequency = 0.0j if self.flat_frequency else 3.0 * (omega - self.current_root)
        return frequency + 2.0 * amplitude

    def read_root(self, *args, **kwargs):
        self.root_reads += 1
        raise AssertionError("binary64 scheduler attempted a root read")


class Binary64SurveySchedulerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.plan = build_campaign_plan(
            policy=NumericalPolicy(),
            backend_identity=VettedNativeDeterminantKernel.identity,
            precision_capabilities=PrecisionCapabilities((64,)),
        )
        selected = build_campaign_selection(cls.plan, role="all")
        leaf_by_id = {leaf.leaf_id: leaf for leaf in cls.plan.leaves}
        cls.selection = RecoverySelection(
            campaign_id=cls.plan.campaign_id,
            selection_id=selected.selection_id,
            ordered_leaf_ids=tuple(selected.leaf_ids),
            roles={leaf_id: leaf_by_id[leaf_id].role for leaf_id in selected.leaf_ids},
            scientific_identities={
                leaf_id: scientific_computation_identity_sha256(
                    cls.plan, leaf_by_id[leaf_id]
                )
                for leaf_id in selected.leaf_ids
            },
        )

    @staticmethod
    def _horizon_outcome(leaf) -> Binary64PassOutcome:
        record, stage_sha256 = _record(leaf.leaf_id)
        return Binary64PassOutcome.produced(
            record=record,
            stage_sha256=stage_sha256,
            operation_identity="existing-binary64-horizon-production/v1",
            reason_code="BOUNDED_HORIZON_RESPONSE",
        )

    def test_full_mocked_plan_has_zero_julia_and_no_inline_promotion(self) -> None:
        backend = _AnalyticBackend()
        backend_constructions = 0

        def backend_factory():
            nonlocal backend_constructions
            backend_constructions += 1
            return backend

        def equivalence(leaf, background):
            return BackgroundEquivalenceReceipt.issue(
                reuse_key=background.reuse_key,
                job=leaf.job,
                canonical_background_sha256=background.sha256,
            )

        with tempfile.TemporaryDirectory() as temporary:
            checkpoint_path = Path(temporary) / "checkpoint.json"
            result = run_binary64_survey(
                self.plan,
                self.selection,
                empty_schema11_checkpoint(
                    self.selection.campaign_id, self.selection.selection_id
                ),
                checkpoint_path=checkpoint_path,
                root_seal_lookup=lambda leaf: AuthenticatedRootSeal(
                    fixed_root=leaf.job.root.omega,
                    branch_identity=leaf.job.root.branch_id,
                    root_seal_sha256=_sha256(
                        {"root_identity": leaf.job.root.identity_sha256}
                    ),
                ),
                native_backend_factory=backend_factory,
                horizon_runner=self._horizon_outcome,
                produced_record_builder=lambda leaf, batch, screening: _record(
                    leaf.leaf_id, screening.response_disk.centre
                ),
                equivalence_receipt_lookup=equivalence,
            )

            self.assertEqual(len(self.selection.ordered_leaf_ids), result.completed_count)
            self.assertEqual(1, backend_constructions)
            self.assertEqual(0, backend.julia_launches)
            self.assertEqual(0, backend.root_reads)
            self.assertEqual([], result.checkpoint["promotion_queue"]["entries"])
            ledger = result.checkpoint["survey_pass_ledger"]["binary64"]
            self.assertEqual(set(self.selection.ordered_leaf_ids), set(ledger))
            self.assertTrue(
                all(entry["worker_launch_count"] == 0 for entry in ledger.values())
            )
            exterior_counts = {
                entry["sample_count"]
                for leaf_id, entry in ledger.items()
                if next(
                    leaf for leaf in self.plan.leaves if leaf.leaf_id == leaf_id
                ).mechanism_id != "horizon-admittance"
            }
            self.assertEqual({4, 9}, exterior_counts)
            exterior_timing = [
                entry["tier_timing"]
                for leaf_id, entry in ledger.items()
                if next(
                    leaf for leaf in self.plan.leaves if leaf.leaf_id == leaf_id
                ).mechanism_id != "horizon-admittance"
            ]
            self.assertTrue(all(
                timing and timing[0]["tier"] == "binary64"
                and timing[0]["source"] == "direct"
                for timing in exterior_timing
            ))
            self.assertTrue(checkpoint_path.is_file())

    def test_typed_response_insufficiency_queues_and_advances_without_promotion(self) -> None:
        exterior = tuple(
            leaf.leaf_id for leaf in self.plan.leaves
            if leaf.mechanism_id != "horizon-admittance"
        )[:2]
        selection = RecoverySelection(
            campaign_id=self.selection.campaign_id,
            selection_id="selection-two-exterior",
            ordered_leaf_ids=exterior,
            roles={leaf_id: self.selection.roles[leaf_id] for leaf_id in exterior},
            scientific_identities={
                leaf_id: self.selection.scientific_identities[leaf_id]
                for leaf_id in exterior
            },
        )
        backend = _AnalyticBackend(flat_frequency=True)
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "checkpoint.json"
            result = run_binary64_survey(
                self.plan,
                selection,
                empty_schema11_checkpoint(selection.campaign_id, selection.selection_id),
                checkpoint_path=path,
                root_seal_lookup=lambda leaf: AuthenticatedRootSeal(
                    leaf.job.root.omega, leaf.job.root.branch_id, "d" * 64
                ),
                native_backend_factory=lambda: backend,
                horizon_runner=lambda leaf: (_ for _ in ()).throw(
                    AssertionError("unexpected horizon leaf")
                ),
                produced_record_builder=lambda *args: (_ for _ in ()).throw(
                    AssertionError("unbounded response produced a record")
                ),
            )

            entries = result.checkpoint["promotion_queue"]["entries"]
            self.assertEqual(2, len(entries))
            self.assertTrue(all(item["queue_kind"] == "RESPONSE" for item in entries))
            self.assertEqual(18, backend.determinant_calls)
            self.assertEqual(0, result.completed_count)
            self.assertEqual(2, result.queued_count)

    def test_missing_root_queues_once_and_resume_is_zero_work(self) -> None:
        leaf_id = next(
            leaf.leaf_id for leaf in self.plan.leaves
            if leaf.mechanism_id != "horizon-admittance"
        )
        selection = RecoverySelection(
            campaign_id=self.selection.campaign_id,
            selection_id="selection-one-exterior",
            ordered_leaf_ids=(leaf_id,),
            roles={leaf_id: self.selection.roles[leaf_id]},
            scientific_identities={
                leaf_id: self.selection.scientific_identities[leaf_id]
            },
        )
        constructions = 0

        def forbidden_backend():
            nonlocal constructions
            constructions += 1
            raise AssertionError("missing root constructed a backend")

        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "checkpoint.json"
            first = run_binary64_survey(
                self.plan,
                selection,
                empty_schema11_checkpoint(selection.campaign_id, selection.selection_id),
                checkpoint_path=path,
                root_seal_lookup=lambda leaf: None,
                native_backend_factory=forbidden_backend,
                horizon_runner=lambda leaf: None,
                produced_record_builder=lambda *args: None,
            )
            second = run_binary64_survey(
                self.plan,
                selection,
                first.checkpoint,
                checkpoint_path=path,
                root_seal_lookup=lambda leaf: (_ for _ in ()).throw(
                    AssertionError("resume repeated root lookup")
                ),
                native_backend_factory=forbidden_backend,
                horizon_runner=lambda leaf: None,
                produced_record_builder=lambda *args: None,
            )

            self.assertEqual(0, constructions)
            self.assertEqual(1, len(second.checkpoint["promotion_queue"]["entries"]))
            self.assertEqual(1, second.skipped_count)

    def test_unexpected_backend_error_is_durable_and_stops_before_next_leaf(self) -> None:
        exterior = tuple(
            leaf.leaf_id for leaf in self.plan.leaves
            if leaf.mechanism_id != "horizon-admittance"
        )[:2]
        selection = RecoverySelection(
            campaign_id=self.selection.campaign_id,
            selection_id="selection-system-failure",
            ordered_leaf_ids=exterior,
            roles={leaf_id: self.selection.roles[leaf_id] for leaf_id in exterior},
            scientific_identities={
                leaf_id: self.selection.scientific_identities[leaf_id]
                for leaf_id in exterior
            },
        )

        class MethodError(RuntimeError):
            pass

        class BrokenBackend:
            def __init__(self):
                self.started = 0

            def fixed_root_survey_with_optional_background(self, **kwargs):
                self.started += 1
                raise MethodError("synthetic precision dispatch defect")

        backend = BrokenBackend()
        root_lookups = []
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "checkpoint.json"
            with self.assertRaises(CampaignSystemFailure):
                run_binary64_survey(
                    self.plan,
                    selection,
                    empty_schema11_checkpoint(
                        selection.campaign_id, selection.selection_id
                    ),
                    checkpoint_path=path,
                    root_seal_lookup=lambda leaf: (
                        root_lookups.append(leaf.leaf_id)
                        or AuthenticatedRootSeal(
                            leaf.job.root.omega,
                            leaf.job.root.branch_id,
                            "e" * 64,
                        )
                    ),
                    native_backend_factory=lambda: backend,
                    horizon_runner=lambda leaf: None,
                    produced_record_builder=lambda *args: None,
                )

            durable = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(1, backend.started)
            self.assertEqual([exterior[0]], root_lookups)
            self.assertEqual([], durable["records"])
            self.assertEqual(1, len(durable["system_failures"]))
            self.assertEqual(
                "MethodError", durable["system_failures"][0]["cause_type"]
            )
            self.assertNotIn("FAILED", str(durable))
            timing = CampaignTimingLog(
                path.with_name(f"{path.name}.timing.jsonl")
            ).read()
            self.assertEqual("INTERRUPTED", timing[-1].state)


if __name__ == "__main__":
    unittest.main()
