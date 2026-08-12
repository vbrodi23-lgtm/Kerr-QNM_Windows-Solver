from __future__ import annotations

import csv
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from windows_solver.progress import ProgressEventKind, activate_progress
from windows_solver.progress_output import CampaignProgressReporter
from windows_solver.response_batches import (
    PrecisionCapabilities,
    StageOutcome,
    build_campaign_plan,
    build_campaign_selection,
    run_campaign_selection,
    synthetic_stage_signed_error_channels,
    validate_campaign_checkpoint,
)
from windows_solver.response_engine import NumericalPolicy, VettedNativeDeterminantKernel
from windows_solver.native_response_kernel import _progress_suboperation


class CampaignProgressLifecycleTests(unittest.TestCase):
    def test_keyboard_interrupt_emits_interrupted_not_failed_events(self):
        plan, selection, _, _ = self._plan_selection_backend()

        class InterruptingBackend:
            identity = plan.backend_identity
            precision_capabilities = plan.precision_capabilities

            def execute_stage(self, leaf, digits):
                with _progress_suboperation("synthetic native integration"):
                    raise KeyboardInterrupt

        class Observer:
            def __init__(self):
                self.events = []

            def publish(self, event):
                self.events.append(event)

        observer = Observer()
        with tempfile.TemporaryDirectory() as temporary, activate_progress(observer):
            with self.assertRaises(KeyboardInterrupt):
                run_campaign_selection(
                    plan,
                    selection,
                    InterruptingBackend(),
                    Path(temporary) / "checkpoint.json",
                    resume=False,
                )

        kinds = [event.kind for event in observer.events]
        self.assertIn(ProgressEventKind.LEAF_INTERRUPTED, kinds)
        self.assertIn(ProgressEventKind.CAMPAIGN_INTERRUPTED, kinds)
        self.assertNotIn(ProgressEventKind.LEAF_FAILED, kinds)
        self.assertNotIn(ProgressEventKind.CAMPAIGN_FAILED, kinds)
        self.assertNotIn(ProgressEventKind.ERROR, kinds)

    @staticmethod
    def _plan_selection_backend():
        plan = build_campaign_plan(
            policy=NumericalPolicy(),
            backend_identity=VettedNativeDeterminantKernel.identity,
            precision_capabilities=PrecisionCapabilities((64,)),
        )
        leaf_id = next(leaf.leaf_id for leaf in plan.leaves if leaf.role == "primary")
        selection = build_campaign_selection(
            plan, role="primary", leaf_ids=(leaf_id,)
        )

        class Backend:
            identity = plan.backend_identity
            precision_capabilities = plan.precision_capabilities

            def execute_stage(self, leaf, digits):
                component = {"leaf_id": leaf.leaf_id, "digits": digits}
                return StageOutcome(
                    digits=digits,
                    numerical_state="CONVERGED",
                    component_result=component,
                    local_disk_radius_abs=1.0e-8,
                    signed_error_channels=synthetic_stage_signed_error_channels(
                        component, 1.0e-8
                    ),
                )

        return plan, selection, leaf_id, Backend()

    def test_first_leaf_is_visible_before_backend_stage_completes(self):
        plan = build_campaign_plan(
            policy=NumericalPolicy(),
            backend_identity=VettedNativeDeterminantKernel.identity,
            precision_capabilities=PrecisionCapabilities((64,)),
        )
        leaf_id = next(leaf.leaf_id for leaf in plan.leaves if leaf.role == "primary")
        selection = build_campaign_selection(
            plan, role="primary", leaf_ids=(leaf_id,)
        )

        class Backend:
            identity = plan.backend_identity
            precision_capabilities = plan.precision_capabilities

            def __init__(self, status_path: Path) -> None:
                self.status_path = status_path

            def execute_stage(self, leaf, digits):
                status = json.loads(self.status_path.read_text(encoding="utf-8"))
                if status["kind"] != "precision_stage_started":
                    raise AssertionError("first leaf was not visible before stage work")
                component = {"leaf_id": leaf.leaf_id, "digits": digits}
                return StageOutcome(
                    digits=digits,
                    numerical_state="CONVERGED",
                    component_result=component,
                    local_disk_radius_abs=1.0e-8,
                    signed_error_channels=synthetic_stage_signed_error_channels(
                        component, 1.0e-8
                    ),
                )

        with tempfile.TemporaryDirectory() as temporary:
            checkpoint = Path(temporary) / "checkpoint.json"
            reporter = CampaignProgressReporter("normal", checkpoint)
            reporter.bind_campaign_reports(plan)
            backend = Backend(Path(f"{checkpoint}.status.json"))
            with activate_progress(reporter):
                summary = run_campaign_selection(
                    plan, selection, backend, checkpoint, resume=False
                )
            status = json.loads(
                Path(f"{checkpoint}.status.json").read_text(encoding="utf-8")
            )
            reports = checkpoint.with_name(f"{checkpoint.stem}.reports")
            with (reports / "m02-leaves.csv").open(
                newline="", encoding="utf-8"
            ) as handle:
                rows = list(csv.DictReader(handle))

        self.assertEqual(summary.executed_stage_count, 1)
        self.assertEqual(status["kind"], "campaign_completed")
        self.assertEqual(status["payload"]["executed_stage_count"], 1)
        completed = next(item for item in rows if item["leaf_id"] == leaf_id)
        self.assertEqual(completed["terminal_state"], "PRODUCED")
        self.assertEqual(completed["run_provenance"], "EXECUTED")

    def test_binding_an_existing_checkpoint_regenerates_reused_reports(self):
        plan, selection, leaf_id, backend = self._plan_selection_backend()
        with tempfile.TemporaryDirectory() as temporary:
            checkpoint = Path(temporary) / "checkpoint.json"
            run_campaign_selection(
                plan, selection, backend, checkpoint, resume=False
            )
            reports = checkpoint.with_name(f"{checkpoint.stem}.reports")
            self.assertFalse(reports.exists())

            reporter = CampaignProgressReporter(
                "normal", checkpoint, io.StringIO()
            )
            reporter.bind_campaign_reports(plan)
            with (reports / "m02-leaves.csv").open(
                newline="", encoding="utf-8"
            ) as handle:
                rows = list(csv.DictReader(handle))

        completed = next(item for item in rows if item["leaf_id"] == leaf_id)
        self.assertEqual(completed["terminal_state"], "PRODUCED")
        self.assertEqual(completed["run_provenance"], "REUSED")

    def test_report_failure_cannot_roll_back_a_committed_checkpoint(self):
        plan, selection, _, backend = self._plan_selection_backend()
        with tempfile.TemporaryDirectory() as temporary:
            checkpoint = Path(temporary) / "checkpoint.json"
            reporter = CampaignProgressReporter(
                "normal", checkpoint, io.StringIO()
            )
            reporter.bind_campaign_reports(plan)
            with patch(
                "windows_solver.progress_output.refresh_campaign_reports",
                side_effect=OSError("report directory is unavailable"),
            ), activate_progress(reporter):
                summary = run_campaign_selection(
                    plan, selection, backend, checkpoint, resume=False
                )

            authenticated = validate_campaign_checkpoint(plan, checkpoint)

        self.assertEqual(summary.state, "COMPLETE")
        self.assertEqual(authenticated.state, "COMPLETE")
        self.assertTrue(any(
            "report directory is unavailable" in item
            for item in reporter.diagnostics
        ))
