from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from windows_solver.campaign_policy import (
    EvidenceLevel,
    SurveyDisposition,
    SurveyPass,
    add_numerical_record,
    empty_schema11_checkpoint,
    record_evidence,
    record_survey_disposition,
)
from windows_solver.campaign_reports import (
    refresh_schema11_reports,
    report_directory_for_checkpoint,
)
from windows_solver.contracts import canonical_json_bytes


def _sha256(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _fixture():
    stage_content = {
        "schema": "windows-solver.fixed-root-screening-stage/1",
        "precision_tier": "binary64",
        "response_disk": {
            "centre": {"real": 2.0, "imaginary": -1.0},
            "radius": 0.25,
        },
    }
    stage = {**stage_content, "stage_sha256": _sha256(stage_content)}
    content = {
        "schema": "windows-solver.schema11-numerical-record/1",
        "leaf_id": "leaf-1",
        "role": "primary",
        "state": "PRODUCED",
        "retained_centre": {"real": 2.0, "imaginary": -1.0},
        "stages": [stage],
    }
    record = {**content, "record_sha256": _sha256(content)}
    checkpoint = add_numerical_record(
        empty_schema11_checkpoint("campaign-1", "selection-1"), record
    )
    checkpoint = record_evidence(
        checkpoint,
        leaf_id="leaf-1",
        central_record_sha256=record["record_sha256"],
        central_stage_sha256=stage["stage_sha256"],
        evidence_level=EvidenceLevel.SCREENED,
    )
    checkpoint = record_survey_disposition(
        checkpoint,
        survey_pass=SurveyPass.BINARY64,
        leaf_id="leaf-1",
        disposition=SurveyDisposition.COMPLETED,
        result_record_sha256=record["record_sha256"],
        operation_identity="fixed-root/v1",
        precision_tiers=("binary64",),
        reason_code="BOUNDED_RESPONSE",
        sample_count=9,
        sample_limit=9,
        root_read_count=0,
        root_read_limit=0,
        worker_launch_count=0,
        worker_launch_limit=0,
        tier_timing=(),
        session_fragments=(),
    )
    leaf = SimpleNamespace(
        leaf_id="leaf-1",
        role="primary",
        mechanism_id="exterior-light-ring",
        leaf=SimpleNamespace(mode_label="220"),
        job=SimpleNamespace(spin=0.9),
    )
    plan = SimpleNamespace(leaves=(leaf,))
    selection = SimpleNamespace(leaf_ids=("leaf-1",))
    return plan, selection, checkpoint


class Schema11ReportTests(unittest.TestCase):
    def test_basic_csvs_survive_advanced_projection_failure(self):
        plan, selection, checkpoint = _fixture()
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "checkpoint.json"
            path.write_bytes(canonical_json_bytes(checkpoint))

            updated = refresh_schema11_reports(
                plan,
                selection,
                checkpoint,
                path,
                advanced_projective=lambda *_: (_ for _ in ()).throw(
                    RuntimeError("forced projective failure")
                ),
                advanced_triage=lambda *_: self.fail(
                    "triage must not run after projective failure"
                ),
            )

            directory = report_directory_for_checkpoint(path)
            for name in (
                "m02-leaves.csv",
                "m02-precision-stages.csv",
                "m02-error-channels.csv",
                "m02-resource-failures.csv",
            ):
                self.assertTrue((directory / name).is_file(), name)
            with (directory / "m02-leaves.csv").open(
                encoding="utf-8", newline=""
            ) as handle:
                rows = list(csv.DictReader(handle))
            status = json.loads(
                (directory / "m02-report-status.json").read_text(
                    encoding="utf-8"
                )
            )
            durable = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(1, len(rows))
        self.assertEqual("SCREENED", rows[0]["evidence_level"])
        self.assertEqual("COMPLETED", status["basic"]["status"])
        self.assertEqual("FAILED", status["projective"]["status"])
        self.assertEqual("NOT_RUN", status["triage"]["status"])
        self.assertEqual(status, updated["report_status_receipt"])
        self.assertEqual(updated, durable)

    def test_basic_report_failure_is_durable_and_raises(self):
        plan, selection, checkpoint = _fixture()
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "checkpoint.json"
            path.write_bytes(canonical_json_bytes(checkpoint))
            with self.assertRaisesRegex(RuntimeError, "forced basic failure"):
                refresh_schema11_reports(
                    plan,
                    selection,
                    checkpoint,
                    path,
                    basic_writer=lambda *_: (_ for _ in ()).throw(
                        RuntimeError("forced basic failure")
                    ),
                )
            durable = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(
            "FAILED",
            durable["report_status_receipt"]["basic"]["status"],
        )


if __name__ == "__main__":
    unittest.main()
