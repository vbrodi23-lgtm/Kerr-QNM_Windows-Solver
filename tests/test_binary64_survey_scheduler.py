from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from windows_solver.campaign_policy import (
    PromotionQueueKind,
    SurveyDisposition,
    empty_schema11_checkpoint,
)
from windows_solver.campaign_failures import CampaignSystemFailure
from windows_solver.campaign_recovery import RecoverySelection
from windows_solver.campaign_runtime import _typed_horizon_failure_code
from windows_solver.campaign_timing import CampaignTimingLog
from windows_solver.campaign_survey import (
    AuthenticatedRootSeal,
    Binary64PassOutcome,
    run_binary64_survey,
)
from windows_solver.contracts import canonical_json_bytes
from windows_solver.structural_diagnostics import (
    StructuralDiagnosticSession,
    read_structural_events,
)
from windows_solver.response_batches import (
    PrecisionCapabilities,
    build_campaign_plan,
    build_campaign_selection,
    scientific_computation_identity_sha256,
)
from windows_solver.response_engine import (
    BackgroundEquivalenceReceipt,
    ComponentStatus,
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

    def test_mass_response_promotion_never_trips_the_repetition_breaker(self) -> None:
        """Every exterior leaf legitimately needing RESPONSE promotion must
        queue normally; PROMOTION_PENDING_RESPONSE is scheduler state, not
        failure-monitor evidence, and must never arm the repetition breaker
        (governing contract §5, invariant: normal promotion is not failure).
        """

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

        exterior_leaf_ids = {
            leaf.leaf_id for leaf in self.plan.leaves
            if leaf.mechanism_id != "horizon-admittance"
        }
        self.assertGreater(len(exterior_leaf_ids), 2)

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

            durable = result.checkpoint
            self.assertEqual([], durable["system_failures"])
            queued = durable["promotion_queue"]["entries"]
            self.assertEqual(len(exterior_leaf_ids), len(queued))
            self.assertTrue(all(
                entry["queue_kind"] == "RESPONSE"
                and entry["reason_code"]
                == "DETERMINANT_ERROR_EVIDENCE_UNAVAILABLE"
                for entry in queued
            ))
            self.assertEqual(
                exterior_leaf_ids, {entry["leaf_id"] for entry in queued}
            )
            self.assertEqual(result.queued_count, len(exterior_leaf_ids))
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

    def test_repeated_horizon_derivative_outcomes_are_advisory(self) -> None:
        """Two repeated numerical outcomes must not block the third leaf."""

        horizon = tuple(
            leaf.leaf_id
            for leaf in self.plan.leaves
            if leaf.mechanism_id == "horizon-admittance"
        )[:3]
        self.assertEqual(3, len(horizon))
        selection = RecoverySelection(
            campaign_id=self.selection.campaign_id,
            selection_id="selection-repeated-horizon-outcome",
            ordered_leaf_ids=horizon,
            roles={leaf_id: self.selection.roles[leaf_id] for leaf_id in horizon},
            scientific_identities={
                leaf_id: self.selection.scientific_identities[leaf_id]
                for leaf_id in horizon
            },
        )
        started: list[str] = []

        def horizon_outcome(leaf) -> Binary64PassOutcome:
            started.append(leaf.leaf_id)
            if len(started) <= 2:
                return Binary64PassOutcome(
                    disposition=SurveyDisposition.PROMOTION_PENDING_RESPONSE,
                    operation_identity="binary64-horizon-production/v2",
                    reason_code="HORIZON_ARITHMETIC_INADEQUATE",
                    queue_kind=PromotionQueueKind.RESPONSE,
                    minimum_requested_tier="BF80",
                )
            record, stage_sha256 = _record(leaf.leaf_id)
            return Binary64PassOutcome(
                disposition=SurveyDisposition.COMPLETED,
                operation_identity="binary64-horizon-production/v2",
                reason_code="BOUNDED_HORIZON_RESPONSE",
                record=record,
                stage_sha256=stage_sha256,
            )

        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "checkpoint.json"
            session = StructuralDiagnosticSession.open(
                checkpoint_path=path,
                session_id="repeated-horizon-outcome",
                campaign_id=selection.campaign_id,
                selection_id=selection.selection_id,
            )
            result = run_binary64_survey(
                self.plan,
                selection,
                empty_schema11_checkpoint(selection.campaign_id, selection.selection_id),
                checkpoint_path=path,
                root_seal_lookup=lambda _leaf: self.fail(
                    "horizon survey must not request a root seal"
                ),
                native_backend_factory=lambda: self.fail(
                    "unresolved horizon must not construct an exterior backend"
                ),
                horizon_runner=horizon_outcome,
                produced_record_builder=lambda *args: self.fail(
                    "horizon survey must not build an exterior record"
                ),
                diagnostic_session=session,
            )
            session.close_completed()
            events = read_structural_events(session.paths.structural_events)

        self.assertEqual(list(horizon), started)
        self.assertEqual([], result.checkpoint["system_failures"])
        self.assertEqual(2, result.queued_count)
        self.assertEqual(1, result.completed_count)
        self.assertEqual(
            set(horizon),
            set(result.checkpoint["survey_pass_ledger"]["binary64"]),
        )
        queued = result.checkpoint["promotion_queue"]["entries"]
        self.assertEqual(2, len(queued))
        self.assertTrue(all(
            item["queue_kind"] == "RESPONSE"
            and item["reason_code"] == "HORIZON_ARITHMETIC_INADEQUATE"
            and item["minimum_requested_tier"] == "BF80"
            for item in queued
        ))
        repeated = [
            event for event in events
            if event["event_kind"] == "REPEATED_LEAF_OUTCOME_OBSERVED"
        ]
        self.assertEqual(1, len(repeated))
        self.assertEqual(2, repeated[0]["compact_diagnostics"]["observation_count"])
        self.assertEqual(list(horizon[:2]), repeated[0]["compact_diagnostics"]["all_observed_leaf_ids"])
        self.assertFalse(repeated[0]["compact_diagnostics"]["campaign_aborted"])

    def test_binary64_horizon_derivative_state_requests_bf80(self) -> None:
        unresolved = SimpleNamespace(
            analytic_horizon_evidence=None,
            derivative_evidence=None,
            resolved_window=None,
            status=ComponentStatus.DERIVATIVE_UNRESOLVED,
        )

        self.assertEqual(
            "HORIZON_ARITHMETIC_INADEQUATE",
            _typed_horizon_failure_code(unresolved, binary64=True),
        )
        self.assertEqual(
            "HORIZON_DERIVATIVE_UNRESOLVED",
            _typed_horizon_failure_code(unresolved, binary64=False),
        )

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
