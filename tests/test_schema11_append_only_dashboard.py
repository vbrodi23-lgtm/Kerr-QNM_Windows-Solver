from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from windows_solver.campaign_policy import (
    PromotionQueueKind,
    SurveyDisposition,
    SurveyPass,
    append_promotion,
    empty_schema11_checkpoint,
    record_survey_disposition,
)
from windows_solver.contracts import canonical_json_bytes
from windows_solver.progress import (
    ProgressContext,
    ProgressEvent,
    ProgressEventKind,
)
from windows_solver.progress_output import Schema11ProgressReporter
from windows_solver.schema11_dashboard import project_schema11_dashboard


REFERENCE_PATH = Path(__file__).parents[1] / "tools" / (
    "M02_Operator_Dashboard_Append_Only_Reference.ps1"
)
REFERENCE_SHA256 = "f36dcf3b8269cac037b3d51ed2388aecb9d4e94fef1b99863a21082bf4c5a54a"


def _metadata(leaf_ids: list[str]) -> dict[str, dict[str, object]]:
    return {
        leaf_id: {
            "leaf_ordinal": ordinal,
            "leaf_count": len(leaf_ids),
            "mode": "s=-2,l=2,m=2,n=0",
            "spin_or_Mkappa": 0.9999,
            "mechanism": "horizon-admittance",
            "role": "primary",
        }
        for ordinal, leaf_id in enumerate(leaf_ids, start=1)
    }


def _checkpoint_for(
    leaf_ids: list[str], *, pending_routes: bool = True
) -> dict[str, object]:
    checkpoint = empty_schema11_checkpoint("campaign-test", "selection-test")
    for ordinal, leaf_id in enumerate(leaf_ids, start=1):
        checkpoint = record_survey_disposition(
            checkpoint,
            survey_pass=SurveyPass.BINARY64,
            leaf_id=leaf_id,
            disposition=(
                SurveyDisposition.PROMOTION_PENDING_RESPONSE
                if pending_routes
                else SurveyDisposition.COMPLETED
            ),
            operation_identity="test/dashboard/v1",
            precision_tiers=("binary64",),
            reason_code="test-disposition",
            sample_count=3,
            sample_limit=3,
            root_read_count=1,
            root_read_limit=1,
            worker_launch_count=1,
            worker_launch_limit=1,
            tier_timing=(),
            session_fragments=(),
        )
        if pending_routes:
            checkpoint = append_promotion(
                checkpoint,
                leaf_id=leaf_id,
                queue_kind=PromotionQueueKind.RESPONSE,
                reason_code="test-route",
                minimum_requested_tier="BF40" if ordinal <= 172 else "BF80",
                scientific_computation_identity=hashlib.sha256(
                    leaf_id.encode("utf-8")
                ).hexdigest(),
            )
    return checkpoint


def _write_checkpoint(path: Path, checkpoint: dict[str, object]) -> None:
    path.write_bytes(canonical_json_bytes(checkpoint))


def _event(
    kind: ProgressEventKind,
    *,
    leaf_id: str | None = None,
    leaf_index: int | None = None,
    leaf_count: int | None = None,
    suboperation: str | None = None,
) -> ProgressEvent:
    context_values: dict[str, object] = {
        "survey_pass": "binary64",
        "execution_profile": "SURVEY",
    }
    if leaf_id is not None:
        context_values["leaf_id"] = leaf_id
    if leaf_index is not None:
        context_values["leaf_index"] = leaf_index
    if leaf_count is not None:
        context_values["leaf_count"] = leaf_count
    if suboperation is not None:
        context_values["suboperation"] = suboperation
    return ProgressEvent(
        kind=kind,
        context=ProgressContext.from_mapping(context_values),
        payload={},
        monotonic_seconds=1.0,
    )


class ReferenceScriptTests(unittest.TestCase):
    def test_reference_script_is_exact_and_static_safe(self) -> None:
        source = REFERENCE_PATH.read_bytes()
        self.assertEqual(REFERENCE_SHA256, hashlib.sha256(source).hexdigest())
        text = source.decode("utf-8")
        first_code_line = next(
            line.strip()
            for line in text.splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        )
        self.assertEqual("& {", first_code_line)
        self.assertEqual(
            1, sum(line.strip() == "Clear-Host" for line in text.splitlines())
        )
        self.assertNotIn("\r", text)
        self.assertNotIn("[Console]::", text)
        self.assertNotIn("SetCursorPosition", text)
        self.assertNotIn("\x1b", text)
        for required in (
            "M02 | OPERATOR DASHBOARD",
            "BINARY64 PROCESSED",
            "PROMOTION ROUTES",
            "RETAINED BINARY64 SAMPLES",
            "LAST SETTLED LEAVES",
            "BINARY64 SURVEY COMPLETE",
            "NEXT PASS: SURVEY / PROMOTED",
        ):
            self.assertIn(required, text)

    def test_reference_script_parses_when_powershell_is_available(self) -> None:
        executable = shutil.which("pwsh") or shutil.which("powershell")
        if executable is None:
            self.skipTest("PowerShell is not installed in this environment")
        command = (
            "$Tokens=$null; $Errors=$null; "
            "[System.Management.Automation.Language.Parser]::ParseFile("
            "[Environment]::GetEnvironmentVariable('DASHBOARD_SCRIPT'),"
            "[ref]$Tokens,[ref]$Errors) > $null; "
            "if ($Errors.Count -ne 0) { exit 1 }"
        )
        result = subprocess.run(
            [executable, "-NoProfile", "-NonInteractive", "-Command", command],
            env={**os.environ, "DASHBOARD_SCRIPT": str(REFERENCE_PATH)},
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(0, result.returncode, result.stderr)

    def test_reference_script_runs_as_an_interactive_paste_on_windows(self) -> None:
        if os.name != "nt":
            self.skipTest("PowerShell 5.1 interactive-paste proof is Windows-only")
        executable = shutil.which("powershell.exe")
        if executable is None:
            self.skipTest("Windows PowerShell 5.1 is not installed")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repo = root / "Downloads" / "Kerr-QNM_Windows-Solver-main" / "Kerr-QNM_Windows-Solver-main"
            output = repo / "m02-output"
            reports = output / "m02-campaign-checkpoint.reports"
            reports.mkdir(parents=True)
            checkpoint = {
                "schema_version": 11,
                "records": [],
                "system_failures": [],
                "evidence_ledger": {},
                "survey_pass_ledger": {
                    "binary64": {
                        "leaf-1": {
                            "leaf_id": "leaf-1",
                            "disposition": "COMPLETED",
                            "sample_count": 1,
                            "tier_timing": [],
                        }
                    },
                    "promoted": {},
                },
                "promotion_queue": {"entries": []},
            }
            status = {
                "survey_pass": "binary64",
                "live_execution": {"leaf": "1/1", "mode": "s=-2"},
                "terminal_event": {"kind": "campaign_pass_completed"},
            }
            (output / "m02-campaign-checkpoint.json").write_text(
                json.dumps(checkpoint), encoding="utf-8"
            )
            (output / "m02-campaign-checkpoint.json.status.json").write_text(
                json.dumps(status), encoding="utf-8"
            )
            (reports / "m02-leaves.csv").write_text(
                "leaf_id,leaf_ordinal,mode,spin_or_Mkappa,mechanism,role\n"
                "leaf-1,1,s=-2,0.9999,horizon-admittance,primary\n",
                encoding="utf-8",
            )
            environment = dict(os.environ)
            environment["HOME"] = str(root)
            environment["USERPROFILE"] = str(root)
            result = subprocess.run(
                [
                    executable,
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-Command",
                    REFERENCE_PATH.read_text(encoding="utf-8"),
                ],
                text=True,
                capture_output=True,
                timeout=30,
                env=environment,
                check=False,
            )
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertNotIn("elseif : The term 'elseif' is not recognized", result.stderr)
        self.assertNotIn("else : The term 'else' is not recognized", result.stderr)
        self.assertIn("M02 | OPERATOR DASHBOARD", result.stdout)


class LedgerProjectionTests(unittest.TestCase):
    def test_binary64_ledger_is_truth_when_records_are_empty(self) -> None:
        leaf_ids = [f"leaf-{index:03d}" for index in range(1, 213)]
        checkpoint = _checkpoint_for(leaf_ids)
        self.assertEqual([], checkpoint["records"])
        snapshot = project_schema11_dashboard(
            checkpoint,
            selected_leaf_ids=leaf_ids,
            leaf_metadata=_metadata(leaf_ids),
        )

        self.assertEqual(212, snapshot.selected_leaf_count)
        self.assertEqual(212, snapshot.binary64_processed_count)
        self.assertEqual(0, snapshot.promoted_processed_count)
        self.assertEqual(0, snapshot.produced_count)
        self.assertEqual(212, snapshot.pending_count)
        self.assertEqual({"BF40": 172, "BF80": 40}, snapshot.pending_by_minimum_tier)
        self.assertEqual(636, snapshot.retained_binary64_sample_count)
        self.assertEqual(212, len(snapshot.binary64_rows))
        self.assertEqual(0, len(snapshot.promoted_rows))
        self.assertEqual(tuple(leaf_ids), snapshot.settled_leaf_ids)
        self.assertEqual("QUEUED->BF40", snapshot.binary64_rows[0].state)
        self.assertEqual("BF80", snapshot.binary64_rows[-1].next_tier)

    def test_projection_keeps_processed_and_produced_distinct(self) -> None:
        leaf_ids = ["leaf-001", "leaf-002"]
        checkpoint = _checkpoint_for(leaf_ids)
        snapshot = project_schema11_dashboard(
            checkpoint,
            selected_leaf_ids=leaf_ids,
            leaf_metadata=_metadata(leaf_ids),
        )
        self.assertEqual(2, snapshot.binary64_processed_count)
        self.assertEqual(0, snapshot.produced_count)


class AppendOnlyRendererTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.checkpoint_path = self.root / "m02-campaign-checkpoint.json"
        self.leaf_ids = [f"leaf-{index:03d}" for index in range(1, 4)]
        self.metadata = _metadata(self.leaf_ids)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_default_stream_is_stderr_for_cli_stream_separation(self) -> None:
        checkpoint = _checkpoint_for(self.leaf_ids[:1], pending_routes=False)
        _write_checkpoint(self.checkpoint_path, checkpoint)
        reporter = Schema11ProgressReporter(
            self.checkpoint_path,
            leaf_metadata=self.metadata,
            profile="survey",
            pass_name="binary64",
        )
        try:
            self.assertIs(sys.stderr, reporter.stream)
        finally:
            reporter.close()

    def test_constructor_is_silent_and_rows_are_append_only(self) -> None:
        first = _checkpoint_for(self.leaf_ids[:1], pending_routes=False)
        _write_checkpoint(self.checkpoint_path, first)
        stream = io.StringIO()
        reporter = Schema11ProgressReporter(
            self.checkpoint_path,
            leaf_metadata=self.metadata,
            profile="survey",
            pass_name="binary64",
            stream=stream,
            width=118,
        )
        self.assertEqual("", stream.getvalue())

        reporter.publish(_event(ProgressEventKind.WORKER_HEARTBEAT))
        self.assertEqual("", stream.getvalue())

        reporter.publish(
            _event(
                ProgressEventKind.LEAF_PASS_STARTED,
                leaf_id=self.leaf_ids[0],
                leaf_index=1,
                leaf_count=3,
            )
        )
        opened = stream.getvalue()
        self.assertIn("M02 | OPERATOR DASHBOARD", opened)
        self.assertEqual(1, opened.count("M02 | OPERATOR DASHBOARD"))
        self.assertNotIn("\r", opened)
        self.assertNotIn("\x1b", opened)

        prefix = stream.getvalue()
        reporter.publish(
            _event(
                ProgressEventKind.SUBOPERATION_PROGRESS,
                leaf_id=self.leaf_ids[0],
                leaf_index=1,
                leaf_count=3,
                suboperation="determinant",
            )
        )
        self.assertEqual(prefix, stream.getvalue())

        reporter.publish(
            _event(
                ProgressEventKind.LEAF_PASS_DISPOSITION_RECORDED,
                leaf_id=self.leaf_ids[1],
                leaf_index=2,
                leaf_count=3,
            )
        )
        self.assertEqual(prefix, stream.getvalue())

        second = _checkpoint_for(self.leaf_ids[:2], pending_routes=False)
        _write_checkpoint(self.checkpoint_path, second)
        before_row = stream.getvalue()
        reporter.publish(
            _event(
                ProgressEventKind.CHECKPOINT_WRITTEN,
                leaf_id=self.leaf_ids[1],
                leaf_index=2,
                leaf_count=3,
            )
        )
        appended = stream.getvalue()[len(before_row) :]
        self.assertEqual(1, len(appended.splitlines()))
        self.assertIn("2/3", appended)

        after_second = stream.getvalue()
        third = _checkpoint_for(self.leaf_ids, pending_routes=False)
        _write_checkpoint(self.checkpoint_path, third)
        reporter.publish(
            _event(
                ProgressEventKind.CAMPAIGN_PASS_COMPLETED,
                leaf_id=self.leaf_ids[2],
                leaf_index=3,
                leaf_count=3,
            )
        )
        terminal_append = stream.getvalue()[len(after_second) :]
        self.assertIn("3/3", terminal_append)
        self.assertIn("BINARY64 SURVEY COMPLETE", terminal_append)
        self.assertEqual(1, stream.getvalue().count("BINARY64 SURVEY COMPLETE"))
        self.assertEqual(1, stream.getvalue().count("NEXT PASS: SURVEY / PROMOTED"))
        self.assertTrue(stream.getvalue().startswith(opened))
        finished = stream.getvalue()
        reporter.close()
        reporter.close()
        self.assertEqual(finished, stream.getvalue())

        status = json.loads(self.checkpoint_path.with_name(
            self.checkpoint_path.name + ".status.json"
        ).read_text(encoding="utf-8"))
        self.assertEqual("windows-solver.schema11-progress-status/2", status["schema"])
        self.assertEqual(["leaf-001", "leaf-002", "leaf-003"], status["settled_leaf_ids"])
        self.assertIn("printed_leaf_ids", status)


if __name__ == "__main__":
    unittest.main()
