from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from windows_solver.progress import activate_progress
from windows_solver.progress_output import CampaignProgressReporter
from windows_solver.response_batches import (
    PrecisionCapabilities,
    StageOutcome,
    build_campaign_plan,
    build_campaign_selection,
    run_campaign_selection,
    synthetic_stage_signed_error_channels,
)
from windows_solver.response_engine import NumericalPolicy, VettedNativeDeterminantKernel


class CampaignProgressLifecycleTests(unittest.TestCase):
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
            backend = Backend(Path(f"{checkpoint}.status.json"))
            with activate_progress(reporter):
                summary = run_campaign_selection(
                    plan, selection, backend, checkpoint, resume=False
                )
            status = json.loads(
                Path(f"{checkpoint}.status.json").read_text(encoding="utf-8")
            )

        self.assertEqual(summary.executed_stage_count, 1)
        self.assertEqual(status["kind"], "campaign_completed")
        self.assertEqual(status["payload"]["executed_stage_count"], 1)

