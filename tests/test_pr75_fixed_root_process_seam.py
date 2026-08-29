from __future__ import annotations

import copy
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tests.pr75_fixed_root_contract_fixture import (
    ROOT_SEAL_SHA256,
    RUNTIME_PROVENANCE,
    _backend,
    _job,
)
from windows_solver.julia_response_backend import (
    FixedRootSurveyPlan,
    JULIA_PROGRESS_PREFIX,
    JuliaNumericalControlError,
    JuliaResponseAdapter,
    _worker_request_document,
)
from windows_solver.contracts import canonical_json_bytes
from windows_solver.operation_control import JULIA_WORKER_ORIGIN
from windows_solver.progress import (
    ProgressEventKind,
    activate_progress,
)


class _RecordingObserver:
    def __init__(self) -> None:
        self.events = []

    def publish(self, event) -> None:
        self.events.append(event)


@unittest.skipUnless(
    os.environ.get("PR75_REAL_WORKER_PROCESS") == "1",
    "hosted real-Julia worker process seam is not enabled",
)
class PR75FixedRootProcessSeamTests(unittest.TestCase):
    def _real_adapter(self) -> JuliaResponseAdapter:
        executable = shutil.which("julia")
        self.assertIsNotNone(executable, "hosted Julia executable is unavailable")
        project = os.environ.get("M02_PROJECT")
        self.assertIsNotNone(project, "hosted M02 Julia project is unavailable")
        depot_text = os.environ.get(
            "JULIA_DEPOT_PATH", str(Path.home() / ".julia")
        )
        depot = Path(depot_text.split(os.pathsep)[0]).resolve()
        self.assertTrue(depot.is_dir(), "hosted Julia depot is unavailable")
        root = Path(__file__).resolve().parents[1]
        return JuliaResponseAdapter(
            julia_executable=Path(str(executable)).resolve(),
            julia_project=Path(str(project)).resolve(),
            julia_depot=depot,
            worker_script=(
                root / "tests/julia/pr75_fixed_root_process_worker.jl"
            ).resolve(),
            runtime_provenance=RUNTIME_PROVENANCE,
        )

    def test_real_worker_main_success_is_loaded_by_production_adapter(self):
        adapter = self._real_adapter()
        job = _job()
        backend = _backend(adapter, 40)
        prepared = backend.prepare_fixed_root_survey_request(
            job,
            fixed_root=job.root.omega,
            root_seal_sha256=ROOT_SEAL_SHA256,
            branch_identity=job.root.branch_id,
            plan=FixedRootSurveyPlan.MECHANISM_COMPONENT_FOUR,
        )
        observer = _RecordingObserver()

        with patch.dict(
            os.environ,
            {"PR75_PROCESS_FIXTURE_OUTCOME": "success"},
        ), activate_progress(observer):
            batch = backend.fixed_root_survey_batch(
                job,
                fixed_root=job.root.omega,
                root_seal_sha256=ROOT_SEAL_SHA256,
                branch_identity=job.root.branch_id,
                plan=FixedRootSurveyPlan.MECHANISM_COMPONENT_FOUR,
                prepared_request=prepared,
            )

        self.assertEqual(batch.request_sha256, prepared.request_sha256)
        self.assertEqual(
            hashlib.sha256(
                canonical_json_bytes(dict(batch.execution_identity))
            ).hexdigest(),
            prepared.execution_identity_sha256,
        )
        self.assertEqual(batch.sample_count, 4)
        self.assertEqual(
            batch.sample_roles,
            (
                "DC_PLUS_EPSILON",
                "DC_MINUS_EPSILON",
                "DC_PLUS_HALF_EPSILON",
                "DC_MINUS_HALF_EPSILON",
            ),
        )
        self.assertEqual(batch.samples[0].determinant.real, Decimal("1.0"))
        self.assertEqual(
            batch.samples[0].determinant.imaginary, Decimal("-1.0")
        )
        event_kinds = [event.kind for event in observer.events]
        self.assertIn(ProgressEventKind.REQUEST_STARTED, event_kinds)
        self.assertIn(ProgressEventKind.REQUEST_VALIDATED, event_kinds)
        self.assertIn(ProgressEventKind.REQUEST_COMPLETED, event_kinds)
        self.assertNotIn(ProgressEventKind.REQUEST_FAILED, event_kinds)
        self.assertLess(
            event_kinds.index(ProgressEventKind.REQUEST_STARTED),
            event_kinds.index(ProgressEventKind.REQUEST_VALIDATED),
        )
        self.assertLess(
            event_kinds.index(ProgressEventKind.REQUEST_VALIDATED),
            event_kinds.index(ProgressEventKind.REQUEST_COMPLETED),
        )

    def test_real_worker_main_exit_21_is_bound_by_production_adapter(self):
        adapter = self._real_adapter()
        job = _job()
        backend = _backend(adapter, 40)
        request = backend.preview_fixed_root_survey_request(
            job,
            fixed_root=job.root.omega,
            root_seal_sha256=ROOT_SEAL_SHA256,
            branch_identity=job.root.branch_id,
            plan=FixedRootSurveyPlan.MECHANISM_COMPONENT_FOUR,
        )
        expected_binding, _wire, expected_sha256 = _worker_request_document(request)
        observer = _RecordingObserver()

        with activate_progress(observer), self.assertRaises(
            JuliaNumericalControlError
        ) as raised:
            backend.fixed_root_survey_batch(
                job,
                fixed_root=job.root.omega,
                root_seal_sha256=ROOT_SEAL_SHA256,
                branch_identity=job.root.branch_id,
                plan=FixedRootSurveyPlan.MECHANISM_COMPONENT_FOUR,
            )

        error = raised.exception
        worker_failure = error.worker_failure
        self.assertEqual(worker_failure["worker_exit_code"], 21)
        self.assertIs(worker_failure["worker_timed_out"], False)
        self.assertTrue(worker_failure["worker_stderr_tail"])
        self.assertEqual(
            worker_failure["worker_error_type"], "NumericalControlFailure"
        )
        receipt = error.control_receipt
        self.assertEqual(receipt.origin, JULIA_WORKER_ORIGIN)
        self.assertEqual(
            receipt.failure_code, "INSUFFICIENT_ASYMPTOTIC_PRECISION"
        )
        self.assertEqual(receipt.identity.operation, "fixed-root-survey-batch")
        self.assertEqual(receipt.identity.mapping["scope"], "SAMPLE")
        self.assertEqual(
            receipt.identity.mapping["plan"],
            FixedRootSurveyPlan.MECHANISM_COMPONENT_FOUR.value,
        )
        self.assertEqual(receipt.identity.mapping["sample_index"], 0)
        self.assertEqual(receipt.identity.mapping["sample_role"], "DC_PLUS_EPSILON")
        self.assertEqual(receipt.identity.request_sha256, expected_sha256)
        self.assertEqual(dict(receipt.canonical_request or {}), expected_binding)
        event_kinds = [event.kind for event in observer.events]
        self.assertIn(ProgressEventKind.REQUEST_STARTED, event_kinds)
        self.assertIn(ProgressEventKind.REQUEST_VALIDATED, event_kinds)
        self.assertIn(ProgressEventKind.REQUEST_FAILED, event_kinds)
        self.assertLess(
            event_kinds.index(ProgressEventKind.REQUEST_STARTED),
            event_kinds.index(ProgressEventKind.REQUEST_VALIDATED),
        )
        self.assertLess(
            event_kinds.index(ProgressEventKind.REQUEST_VALIDATED),
            event_kinds.index(ProgressEventKind.REQUEST_FAILED),
        )
        failed = next(
            event
            for event in reversed(observer.events)
            if event.kind is ProgressEventKind.REQUEST_FAILED
        )
        self.assertNotIn("failure", failed.payload)
        self.assertNotIn("message", failed.payload)
        self.assertNotIn("diagnostics", failed.payload)
        self.assertEqual(
            failed.payload["control_receipt_sha256"], receipt.sha256
        )
        self.assertEqual(failed.payload["request_sha256"], expected_sha256)
        self.assertEqual(
            failed.payload["execution_identity_sha256"],
            receipt.identity.sha256,
        )
        self.assertEqual(
            failed.payload["failure_code"], receipt.failure_code
        )
        self.assertEqual(failed.payload["scope"], "SAMPLE")
        self.assertEqual(
            failed.payload["plan"],
            FixedRootSurveyPlan.MECHANISM_COMPONENT_FOUR.value,
        )
        self.assertEqual(failed.payload["sample_index"], 0)
        self.assertEqual(failed.payload["sample_role"], "DC_PLUS_EPSILON")

    def test_main_catches_parse_and_semantic_failures_before_validation_event(self):
        executable = shutil.which("julia")
        self.assertIsNotNone(executable, "hosted Julia executable is unavailable")
        project = os.environ.get("M02_PROJECT")
        self.assertIsNotNone(project, "hosted M02 Julia project is unavailable")
        depot_text = os.environ.get(
            "JULIA_DEPOT_PATH", str(Path.home() / ".julia")
        )
        depot = Path(depot_text.split(os.pathsep)[0]).resolve()
        self.assertTrue(depot.is_dir(), "hosted Julia depot is unavailable")

        job = _job()
        request = _backend(SimpleNamespace(
            runtime_provenance=RUNTIME_PROVENANCE
        ), 40).preview_fixed_root_survey_request(
            job,
            fixed_root=job.root.omega,
            root_seal_sha256=ROOT_SEAL_SHA256,
            branch_identity=job.root.branch_id,
            plan=FixedRootSurveyPlan.MECHANISM_COMPONENT_FOUR,
        )
        _binding, valid_wire, _request_sha256 = _worker_request_document(
            request
        )
        semantic_wire = copy.deepcopy(valid_wire)
        semantic_wire["maximum_sample_count"] = 8
        semantic_binding = {
            key: value
            for key, value in semantic_wire.items()
            if key not in {"request_sha256", "execution_identity"}
        }
        semantic_sha256 = hashlib.sha256(
            canonical_json_bytes(semantic_binding)
        ).hexdigest()
        semantic_wire["request_sha256"] = semantic_sha256
        semantic_wire["execution_identity"]["request_sha256"] = (
            semantic_sha256
        )

        root = Path(__file__).resolve().parents[1]
        worker = (
            root / "tests/julia/pr75_fixed_root_process_worker.jl"
        ).resolve()
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            malformed_request = directory / "malformed-request.json"
            malformed_response = directory / "malformed-response.json"
            semantic_request = directory / "semantic-request.json"
            semantic_response = directory / "semantic-response.json"
            malformed_request.write_text("{", encoding="utf-8")
            semantic_request.write_bytes(canonical_json_bytes(semantic_wire))
            environment = dict(os.environ)
            environment["JULIA_DEPOT_PATH"] = str(depot)
            environment["KERR_QNM_PROGRESS"] = "1"
            completed = subprocess.run(
                [
                    str(Path(str(executable)).resolve()),
                    f"--project={Path(str(project)).resolve()}",
                    "--startup-file=no",
                    "--history-file=no",
                    str(worker),
                    "--no-solver-contract-cases",
                    str(malformed_request),
                    str(malformed_response),
                    str(semantic_request),
                    str(semantic_response),
                ],
                check=False,
                capture_output=True,
                text=True,
                env=environment,
                # A cold hosted Julia process compiles the package-owned
                # worker before these two no-solver error cases execute.  The
                # same compilation can take about fifteen minutes on the CI
                # runner; subsequent worker launches reuse the warmed cache.
                timeout=20 * 60,
            )
            malformed_result = json.loads(malformed_response.read_bytes())
            semantic_result = json.loads(semantic_response.read_bytes())

        self.assertEqual(completed.returncode, 21)
        self.assertEqual(malformed_result["status"], "error")
        self.assertNotIn("failure", malformed_result)
        self.assertEqual(semantic_result["status"], "error")
        self.assertNotIn("failure", semantic_result)
        self.assertIn(
            "fixed-root survey sample budget is invalid",
            semantic_result["message"],
        )
        progress = [
            json.loads(line[len(JULIA_PROGRESS_PREFIX):])
            for line in completed.stdout.splitlines()
            if line.startswith(JULIA_PROGRESS_PREFIX)
        ]
        semantic_kinds = [
            event["kind"]
            for event in progress
            if event["context"].get("request_sha256") == semantic_sha256
        ]
        self.assertIn(ProgressEventKind.REQUEST_STARTED.value, semantic_kinds)
        self.assertIn(ProgressEventKind.REQUEST_FAILED.value, semantic_kinds)
        self.assertNotIn(
            ProgressEventKind.REQUEST_VALIDATED.value, semantic_kinds
        )


if __name__ == "__main__":
    unittest.main()
