from __future__ import annotations

from decimal import Decimal
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from windows_solver.contracts import canonical_json_bytes
from windows_solver.julia_response_backend import (
    JULIA_PROGRESS_PREFIX,
    JuliaPrecisionRootBackend,
    JuliaResponseAdapter,
    JuliaResponseBackendError,
    _forward_julia_progress_line,
    _run_streamed_julia,
)
from windows_solver.progress import PROGRESS_SCHEMA, ProgressEventKind, activate_progress
from windows_solver.response_batches import (
    PrecisionCapabilities,
    build_campaign_selection,
    build_campaign_plan,
    run_campaign_selection,
)
from windows_solver.response_engine import NumericalPolicy, VettedNativeDeterminantKernel
from windows_solver.progress_output import CampaignProgressReporter


def _deep_job():
    plan = build_campaign_plan(
        policy=NumericalPolicy(),
        backend_identity=VettedNativeDeterminantKernel.identity,
        precision_capabilities=PrecisionCapabilities((64, 80, 120)),
    )
    return next(leaf.job for leaf in plan.leaves if leaf.role == "deep")


class FakeAdapter:
    runtime_provenance = {
        "julia_version": "1.10.11",
        "julia_executable_sha256": "a" * 64,
        "julia_manifest_sha256": "b" * 64,
        "worker_sha256": "c" * 64,
        "runtime_policy_sha256": "d" * 64,
        "scientific_sources": [],
    }

    def __init__(self):
        self.requests = []

    def evaluate(self, request):
        self.requests.append(request)
        return {
            "schema_version": 1,
            "status": "ok",
            "adapter": "package-owned-julia-gsn-root-readout",
            "request_sha256": "e" * 64,
            "precision_digits": request["precision_digits"],
            "working_precision_bits": request["working_precision_bits"],
            "root_omega_re": request["omega"]["real"],
            "root_omega_im": request["omega"]["imaginary"],
            "root_residual_abs": "1e-60",
            "root_derivative_abs": "2.5",
            "root_converged": True,
            "branch_authentication_contract_version": 2,
            "root_branch_continuation_valid": True,
            "branch_tolerance_abs": "0.005",
            "root_displacement_abs": "0",
            "truncation_radius_abs": "2e-55",
            "resolution_radius_abs": "3e-55",
            "seed_path_radius_abs": "4e-55",
        }


class JuliaResponseBackendTests(unittest.TestCase):
    def test_streamed_worker_progress_and_heartbeat_are_serialized(self):
        """Catches a live Julia child becoming invisible between stdout events."""

        class Observer:
            def __init__(self):
                self.events = []
                self.thread_ids = []

            def publish(self, event):
                self.events.append(event)
                self.thread_ids.append(threading.get_ident())

        worker_event = JULIA_PROGRESS_PREFIX + json.dumps({
            "schema": PROGRESS_SCHEMA,
            "kind": "suboperation_started",
            "context": {"suboperation": "r-from-rho"},
            "payload": {"suboperation": "r-from-rho"},
        })
        script = (
            "import time; "
            f"print({worker_event!r}, flush=True); "
            "time.sleep(0.08)"
        )
        observer = Observer()
        caller_thread = threading.get_ident()

        with patch(
            "windows_solver.julia_response_backend._WORKER_HEARTBEAT_SECONDS",
            0.01,
            create=True,
        ):
            with activate_progress(observer):
                completed = _run_streamed_julia(
                    (sys.executable, "-c", script),
                    cwd=Path.cwd(),
                    env=os.environ,
                    timeout=5,
                )

        kinds = [event.kind.value for event in observer.events]
        self.assertEqual(completed.returncode, 0)
        self.assertIn("suboperation_started", kinds)
        self.assertIn("worker_heartbeat", kinds)
        self.assertTrue(observer.thread_ids)
        self.assertEqual(set(observer.thread_ids), {caller_thread})

    def test_package_worker_declares_line_flushed_inner_progress_without_request_changes(self):
        worker = (
            Path(__file__).resolve().parents[1]
            / "src/windows_solver/data/julia/m02_worker.jl"
        ).read_text(encoding="utf-8")
        self.assertIn('const PROGRESS_PREFIX = "@@KERR_QNM_PROGRESS@@"', worker)
        self.assertIn("flush(stdout)", worker)
        for event in (
            "root_phase_started",
            "root_seed_selected",
            "newton_iteration_started",
            "newton_iteration_completed",
            "determinant_started",
            "determinant_completed",
            "suboperation_started",
            "suboperation_completed",
        ):
            self.assertIn(f'progress_emit("{event}"', worker)
        self.assertIn('"acceptance_threshold" => string(tolerance)', worker)
        self.assertIn('haskey(document, "primary_predictor")', worker)
        self.assertIn('required(document, "primary_predictor_kind")', worker)
        self.assertIn('fallback_initial=fallback_initial', worker)
        self.assertIn('fallback_reason = "PREDICTOR_SOLVE_ERROR"', worker)
        self.assertIn("failure isa InterruptException && rethrow()", worker)
        self.assertIn('"INDEPENDENT_SEED_PATH"', worker)
        self.assertIn('"branch_authentication_contract_version" => 2', worker)
        self.assertIn('"root_branch_continuation_valid" => branch_valid', worker)
        self.assertIn('"branch_tolerance_abs" => numeric_text(branch_tolerance)', worker)
        self.assertIn('"root_displacement_abs" => numeric_text(abs(root - omega))', worker)
        self.assertNotIn('document["progress', worker)

    def test_package_worker_preserves_radial_tolerances_and_reports_r_from_rho(self):
        """Catches collapsing the promoted ODE tolerance pair or hiding its map."""

        worker = (
            Path(__file__).resolve().parents[1]
            / "src/windows_solver/data/julia/m02_worker.jl"
        ).read_text(encoding="utf-8")

        self.assertIn(
            'relative_tolerance = parse_real(T, request, "ode_relative_tolerance")',
            worker,
        )
        self.assertIn(
            'absolute_tolerance = parse_real(T, request, "ode_absolute_tolerance")',
            worker,
        )
        self.assertIn('radius_from_rho = progress_operation("r-from-rho") do', worker)
        self.assertIn("reltol=relative_tolerance", worker)
        self.assertIn("abstol=absolute_tolerance", worker)
        self.assertNotIn("tolerance = min(", worker)
        self.assertNotIn("reltol=tolerance", worker)
        self.assertNotIn("abstol=tolerance", worker)

    def test_reserved_julia_stdout_event_is_forwarded_to_active_reporter(self):
        class Observer:
            def __init__(self):
                self.events = []

            def publish(self, event):
                self.events.append(event)

        observer = Observer()
        line = JULIA_PROGRESS_PREFIX + json.dumps({
            "schema": PROGRESS_SCHEMA,
            "kind": "newton_iteration_started",
            "context": {
                "phase": "PRIMARY",
                "newton_index": 1,
                "newton_limit": 16,
                "current_omega": {"real": "0.5", "imaginary": "-0.1"},
            },
            "payload": {
                "current_omega": {"real": "0.5", "imaginary": "-0.1"},
                "determinant_abs": "1e-20",
                "best_determinant_abs": "1e-20",
            },
        })
        with activate_progress(observer):
            self.assertTrue(_forward_julia_progress_line(line))

        self.assertEqual(len(observer.events), 1)
        self.assertIs(observer.events[0].kind, ProgressEventKind.NEWTON_ITERATION_STARTED)
        self.assertEqual(observer.events[0].context.phase, "PRIMARY")

    def test_promoted_backend_uses_bigfloat_policy_without_binary64_tolerances(self):
        job = _deep_job()
        adapter = FakeAdapter()
        backend = JuliaPrecisionRootBackend(
            VettedNativeDeterminantKernel.identity, adapter, 80
        )

        readout = backend.read_root(job, complex(0.001, -0.002))

        request = adapter.requests[0]
        self.assertEqual(request["precision_digits"], 80)
        self.assertEqual(request["working_precision_bits"], 298)
        self.assertEqual(request["policy"]["ode_relative_tolerance"], "1e-62")
        self.assertEqual(request["policy"]["root_tolerance"], "1e-62")
        self.assertEqual(request["amplitude"], {
            "real": "0.001",
            "imaginary": "-0.002",
        })
        self.assertEqual(readout.omega, job.root.omega)
        self.assertEqual(readout.truncation_radius, 2.0e-55)
        self.assertTrue(readout.converged)
        self.assertEqual(backend.scientific_runtime["precision_digits"], 80)

    def test_promoted_nonconvergence_preserves_authenticated_branch(self):
        """Catches relabelling an in-radius Julia failure as branch loss."""

        class NonconvergedAdapter(FakeAdapter):
            def evaluate(self, request):
                response = super().evaluate(request)
                response.update({
                    "root_omega_re": request["omega"]["real"],
                    "root_omega_im": request["omega"]["imaginary"],
                    "root_displacement_abs": "0",
                    "root_residual_abs": "5e-11",
                    "root_converged": False,
                })
                return response

        job = _deep_job()
        backend = JuliaPrecisionRootBackend(
            VettedNativeDeterminantKernel.identity,
            NonconvergedAdapter(),
            80,
        )

        readout = backend.read_root(job, 0.0j)

        self.assertFalse(readout.converged)
        self.assertEqual(readout.branch_id, job.root.branch_id)

    def test_promoted_branch_radius_violation_marks_nonmatching_identity(self):
        """Catches authenticating a Julia root outside the continuation radius."""

        class OutsideBranchAdapter(FakeAdapter):
            def evaluate(self, request):
                response = super().evaluate(request)
                response.update({
                    "root_omega_re": request["omega"]["real"],
                    "root_omega_im": request["omega"]["imaginary"],
                    "root_displacement_abs": "0",
                    "truncation_radius_abs": "0.006",
                    "root_converged": False,
                    "root_branch_continuation_valid": False,
                })
                return response

        job = _deep_job()
        backend = JuliaPrecisionRootBackend(
            VettedNativeDeterminantKernel.identity,
            OutsideBranchAdapter(),
            80,
        )

        readout = backend.read_root(job, 0.0j)

        self.assertFalse(readout.converged)
        self.assertEqual(readout.branch_id, "nonmatching-julia-continuation")

    def test_promoted_branch_decision_preserves_high_precision_boundary(self):
        """Catches binary64 rounding authenticating a just-outside Julia root."""

        class BoundaryAdapter(FakeAdapter):
            def __init__(self, displacement, branch_valid):
                super().__init__()
                self.displacement = displacement
                self.branch_valid = branch_valid

            def evaluate(self, request):
                response = super().evaluate(request)
                response.update({
                    "root_omega_re": request["omega"]["real"],
                    "root_omega_im": request["omega"]["imaginary"],
                    "root_displacement_abs": "0",
                    "truncation_radius_abs": self.displacement,
                    "root_converged": False,
                    "root_branch_continuation_valid": self.branch_valid,
                })
                return response

        job = _deep_job()
        exact = JuliaPrecisionRootBackend(
            VettedNativeDeterminantKernel.identity,
            BoundaryAdapter("0.005", True),
            80,
        ).read_root(job, 0.0j)
        outside = JuliaPrecisionRootBackend(
            VettedNativeDeterminantKernel.identity,
            BoundaryAdapter("0.0050000000000000000000000001", False),
            80,
        ).read_root(job, 0.0j)

        class ComplexBoundaryAdapter(FakeAdapter):
            def evaluate(self, request):
                response = super().evaluate(request)
                response.update({
                    "root_omega_re": str(
                        Decimal(request["omega"]["real"]) + Decimal("0.003")
                    ),
                    "root_omega_im": str(
                        Decimal(request["omega"]["imaginary"]) + Decimal("0.004")
                    ),
                    "root_displacement_abs": "0.005",
                })
                return response

        complex_boundary = JuliaPrecisionRootBackend(
            VettedNativeDeterminantKernel.identity,
            ComplexBoundaryAdapter(),
            80,
        ).read_root(job, 0.0j)

        self.assertEqual(exact.branch_id, job.root.branch_id)
        self.assertEqual(complex_boundary.branch_id, job.root.branch_id)
        self.assertEqual(outside.branch_id, "nonmatching-julia-continuation")
        self.assertEqual(
            float("0.0050000000000000000000000001"),
            0.005,
        )

    def test_promoted_branch_decision_rejects_worker_metric_disagreement(self):
        """Catches trusting a forged Julia branch Boolean over clear radius evidence."""

        class DisagreeingAdapter(FakeAdapter):
            def evaluate(self, request):
                response = super().evaluate(request)
                response.update({
                    "root_omega_re": request["omega"]["real"],
                    "root_omega_im": request["omega"]["imaginary"],
                    "root_displacement_abs": "0",
                    "truncation_radius_abs": "0.006",
                    "root_converged": False,
                    "root_branch_continuation_valid": True,
                })
                return response

        job = _deep_job()
        backend = JuliaPrecisionRootBackend(
            VettedNativeDeterminantKernel.identity,
            DisagreeingAdapter(),
            80,
        )

        with self.assertRaisesRegex(
            JuliaResponseBackendError,
            "branch-continuation evidence is inconsistent",
        ):
            backend.read_root(job, 0.0j)

        class ForgedToleranceAdapter(DisagreeingAdapter):
            def evaluate(self, request):
                response = super().evaluate(request)
                response["branch_tolerance_abs"] = "0.006"
                return response

        forged_tolerance_backend = JuliaPrecisionRootBackend(
            VettedNativeDeterminantKernel.identity,
            ForgedToleranceAdapter(),
            80,
        )
        with self.assertRaisesRegex(
            JuliaResponseBackendError,
            "branch-continuation evidence is inconsistent",
        ):
            forged_tolerance_backend.read_root(job, 0.0j)

        class ImpossibleConvergenceAdapter(DisagreeingAdapter):
            def evaluate(self, request):
                response = super().evaluate(request)
                response.update({
                    "root_converged": True,
                    "root_branch_continuation_valid": False,
                })
                return response

        impossible_backend = JuliaPrecisionRootBackend(
            VettedNativeDeterminantKernel.identity,
            ImpossibleConvergenceAdapter(),
            80,
        )
        with self.assertRaisesRegex(
            JuliaResponseBackendError,
            "response contract is invalid",
        ):
            impossible_backend.read_root(job, 0.0j)

        class FalseInsideAdapter(FakeAdapter):
            def evaluate(self, request):
                response = super().evaluate(request)
                response.update({
                    "root_converged": False,
                    "root_branch_continuation_valid": False,
                })
                return response

        false_inside_backend = JuliaPrecisionRootBackend(
            VettedNativeDeterminantKernel.identity,
            FalseInsideAdapter(),
            80,
        )
        with self.assertRaisesRegex(
            JuliaResponseBackendError,
            "branch-continuation evidence is inconsistent",
        ):
            false_inside_backend.read_root(job, 0.0j)

    def test_promoted_backend_forwards_optional_primary_predictor(self):
        """Catches promoted precision reverting to background-only PRIMARY seeds."""

        job = _deep_job()
        adapter = FakeAdapter()
        backend = JuliaPrecisionRootBackend(
            VettedNativeDeterminantKernel.identity, adapter, 80
        )
        predictor = job.root.omega + complex(1.0e-5, -2.0e-5)

        backend.read_root(job, 0.001 + 0.0j, primary_predictor=predictor)

        self.assertEqual(adapter.requests[0]["primary_predictor"], {
            "real": format(predictor.real, ".17g"),
            "imaginary": format(predictor.imag, ".17g"),
        })

    def test_promoted_backend_labels_cross_spin_predictor(self):
        job = _deep_job()
        adapter = FakeAdapter()
        backend = JuliaPrecisionRootBackend(
            VettedNativeDeterminantKernel.identity, adapter, 80
        )
        predictor = job.root.omega + complex(1.0e-5, -2.0e-5)

        backend.read_root_with_predictor_kind(
            job,
            0.001 + 0.0j,
            predictor,
            "SPIN_CONTINUATION",
        )

        self.assertEqual(
            adapter.requests[0]["primary_predictor_kind"],
            "SPIN_CONTINUATION",
        )

    def test_refinement_tightens_every_resolution_control(self):
        job = _deep_job()
        adapter = FakeAdapter()
        backend = JuliaPrecisionRootBackend(
            VettedNativeDeterminantKernel.identity, adapter, 80, refinement=1
        )

        backend.read_root(job, 0.0j)

        policy = adapter.requests[0]["policy"]
        self.assertEqual(policy["ode_relative_tolerance"], "1e-66")
        self.assertEqual(policy["endpoint_series_order"], 36)
        self.assertEqual(policy["support_subinterval_count"], 512)
        self.assertEqual(policy["angular_pad"], 26)

    def test_runtime_adapter_authenticates_receipt_worker_and_manifest(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            runtime = root / ".runtime"
            project = runtime / "m02-julia-project"
            depot = runtime / "julia-depot"
            project.mkdir(parents=True)
            depot.mkdir()
            julia = runtime / "julia.exe"
            manifest = project / "Manifest.toml"
            project_file = project / "Project.toml"
            worker = root / "m02_worker.jl"
            for path, data in (
                (julia, b"julia"),
                (manifest, b"manifest"),
                (project_file, b"project"),
                (worker, b"worker"),
            ):
                path.write_bytes(data)
            receipt = {
                "policy_sha256": "f" * 64,
                "julia_runtime": {
                    "requested": True,
                    "version": "1.10.11",
                    "executable": str(julia),
                    "executable_sha256": hashlib.sha256(julia.read_bytes()).hexdigest(),
                    "archive": str(runtime / "julia.zip"),
                    "archive_sha256": "1" * 64,
                    "sources": [],
                    "depot": str(depot),
                    "project": str(project),
                    "manifest_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
                    "worker_sha256": hashlib.sha256(worker.read_bytes()).hexdigest(),
                },
            }
            (runtime / "python-runtime.json").write_bytes(canonical_json_bytes(receipt))

            module_worker = (
                Path(__file__).resolve().parents[1]
                / "src/windows_solver/data/julia/m02_worker.jl"
            )
            declared = receipt["julia_runtime"]
            declared["worker_sha256"] = hashlib.sha256(
                module_worker.read_bytes()
            ).hexdigest()
            (runtime / "python-runtime.json").write_bytes(canonical_json_bytes(receipt))

            adapter = JuliaResponseAdapter.from_runtime_receipt(
                runtime_root=runtime
            )
            self.assertEqual(adapter.julia_executable, julia.resolve())
            self.assertEqual(adapter.julia_project, project.resolve())

            manifest.write_bytes(b"changed")
            with self.assertRaisesRegex(
                JuliaResponseBackendError,
                "manifest receipt digest",
            ):
                JuliaResponseAdapter.from_runtime_receipt(runtime_root=runtime)

    def test_subprocess_response_is_bound_to_exact_request_digest(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name in ("julia.exe", "Project.toml", "Manifest.toml", "worker.jl"):
                (root / name).write_text(name, encoding="ascii")
            depot = root / "depot"
            depot.mkdir()
            provenance = {}

            def runner(command, **kwargs):
                request = json.loads(Path(command[-2]).read_text(encoding="utf-8"))
                Path(command[-1]).write_bytes(canonical_json_bytes({
                    "status": "ok",
                    "request_sha256": "0" * 64,
                }))
                return SimpleNamespace(returncode=0, stdout="", stderr="")

            adapter = JuliaResponseAdapter(
                root / "julia.exe",
                root,
                depot,
                root / "worker.jl",
                provenance,
                runner,
            )
            with self.assertRaisesRegex(JuliaResponseBackendError, "request digest"):
                adapter.evaluate({"schema_version": 1})

    def test_nonzero_worker_exit_exposes_structured_error_receipt(self):
        """Catches discarding the worker's own exit/error receipt on failure."""

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name in ("julia.exe", "Project.toml", "Manifest.toml", "worker.jl"):
                (root / name).write_text(name, encoding="ascii")
            depot = root / "depot"
            depot.mkdir()

            def runner(command, **kwargs):
                Path(command[-1]).write_bytes(canonical_json_bytes({
                    "schema_version": 1,
                    "status": "error",
                    "error_type": "ErrorException",
                    "message": "r-from-rho failed",
                }))
                return SimpleNamespace(
                    returncode=21,
                    stdout="",
                    stderr="synthetic Julia traceback",
                )

            adapter = JuliaResponseAdapter(
                root / "julia.exe",
                root,
                depot,
                root / "worker.jl",
                {},
                runner,
            )
            with self.assertRaisesRegex(JuliaResponseBackendError, "code 21") as raised:
                adapter.evaluate({"schema_version": 1})

        self.assertEqual(raised.exception.worker_failure, {
            "worker_exit_code": 21,
            "worker_timed_out": False,
            "worker_stderr_tail": "synthetic Julia traceback",
            "worker_error_type": "ErrorException",
            "worker_error_message": "r-from-rho failed",
        })

    def test_worker_timeout_is_explicit_in_failure_diagnostic(self):
        """Catches a killed worker being reported as an opaque nonzero exit."""

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name in ("julia.exe", "Project.toml", "Manifest.toml", "worker.jl"):
                (root / name).write_text(name, encoding="ascii")
            depot = root / "depot"
            depot.mkdir()

            def runner(command, **kwargs):
                return SimpleNamespace(
                    returncode=-9,
                    stdout="",
                    stderr="Julia worker timed out after 60 seconds\n",
                    timed_out=True,
                )

            adapter = JuliaResponseAdapter(
                root / "julia.exe",
                root,
                depot,
                root / "worker.jl",
                {},
                runner,
            )
            with self.assertRaisesRegex(JuliaResponseBackendError, "timed out") as raised:
                adapter.evaluate({"schema_version": 1})

        self.assertEqual(raised.exception.worker_failure, {
            "worker_exit_code": -9,
            "worker_timed_out": True,
            "worker_stderr_tail": "Julia worker timed out after 60 seconds\n",
            "worker_error_type": None,
            "worker_error_message": None,
        })

    def test_campaign_failure_status_persists_worker_diagnostic(self):
        """Catches final status overwriting the failed worker's exact diagnostic."""

        plan = build_campaign_plan(
            policy=NumericalPolicy(),
            backend_identity=VettedNativeDeterminantKernel.identity,
            precision_capabilities=PrecisionCapabilities((64, 80, 120)),
        )
        leaf = next(item for item in plan.leaves if item.role == "primary")
        selection = build_campaign_selection(
            plan,
            role="primary",
            leaf_ids=(leaf.leaf_id,),
        )
        failure = JuliaResponseBackendError("M02 Julia worker failed with code 21")
        failure.worker_failure = {
            "worker_exit_code": 21,
            "worker_timed_out": False,
            "worker_stderr_tail": "synthetic Julia traceback",
            "worker_error_type": "ErrorException",
            "worker_error_message": "r-from-rho failed",
        }

        class FailingBackend:
            identity = plan.backend_identity
            precision_capabilities = plan.precision_capabilities

            def execute_stage(self, selected_leaf, digits):
                raise failure

        with tempfile.TemporaryDirectory() as temporary:
            checkpoint = Path(temporary) / "checkpoint.json"
            reporter = CampaignProgressReporter("normal", checkpoint, io.StringIO())
            with activate_progress(reporter):
                with self.assertRaisesRegex(JuliaResponseBackendError, "code 21"):
                    run_campaign_selection(
                        plan,
                        selection,
                        FailingBackend(),
                        checkpoint,
                        resume=False,
                    )
            status = json.loads(
                Path(f"{checkpoint}.status.json").read_text(encoding="utf-8")
            )

        self.assertEqual(status["kind"], "campaign_failed")
        self.assertEqual(status["payload"]["worker_failure"], failure.worker_failure)

    def test_runtime_receipt_uses_persistent_worker_and_juliaup_channel(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            runtime = root / "runtime"
            project = runtime / "m02-environments" / "m02-contract" / "project"
            depot = runtime / "julia-depot" / "m02-contract"
            source_root = runtime / "scientific-sources" / "m02-contract"
            project.mkdir(parents=True)
            depot.mkdir(parents=True)
            source_root.mkdir(parents=True)
            julia = root / "julia.exe"
            worker = source_root / "m02_worker.jl"
            for path, data in (
                (julia, b"juliaup-shim"),
                (project / "Project.toml", b"project"),
                (project / "Manifest.toml", b"manifest"),
                (worker, b"persistent worker"),
            ):
                path.write_bytes(data)
            receipt = {
                "policy_sha256": "f" * 64,
                "julia_runtime": {
                    "requested": True,
                    "version": "1.10.11",
                    "executable": str(julia),
                    "executable_sha256": hashlib.sha256(julia.read_bytes()).hexdigest(),
                    "arguments": ["+1.10.11"],
                    "worker": str(worker),
                    "worker_sha256": hashlib.sha256(worker.read_bytes()).hexdigest(),
                    "depot": str(depot),
                    "project": str(project),
                    "manifest_sha256": hashlib.sha256(
                        (project / "Manifest.toml").read_bytes()
                    ).hexdigest(),
                    "sources": [],
                },
            }
            (runtime / "python-runtime.json").write_bytes(
                canonical_json_bytes(receipt)
            )
            commands: list[tuple[str, ...]] = []

            def runner(command, **kwargs):
                commands.append(tuple(command))
                request = json.loads(
                    Path(command[-2]).read_text(encoding="utf-8")
                )
                Path(command[-1]).write_bytes(
                    canonical_json_bytes(
                        {
                            "status": "ok",
                            "request_sha256": request["request_sha256"],
                        }
                    )
                )
                return SimpleNamespace(returncode=0, stdout="", stderr="")

            adapter = JuliaResponseAdapter.from_runtime_receipt(
                runtime_root=runtime,
                runner=runner,
            )
            adapter.evaluate({"schema_version": 1})
            self.assertTrue(Path(commands[0][0]).samefile(julia))
            self.assertEqual(commands[0][1:3], ("+1.10.11", "--startup-file=no"))
            self.assertTrue(Path(commands[0][-3]).samefile(worker))


if __name__ == "__main__":
    unittest.main()
