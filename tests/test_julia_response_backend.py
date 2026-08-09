from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

from windows_solver.contracts import canonical_json_bytes
from windows_solver.julia_response_backend import (
    JULIA_PROGRESS_PREFIX,
    JuliaPrecisionRootBackend,
    JuliaResponseAdapter,
    JuliaResponseBackendError,
    _forward_julia_progress_line,
)
from windows_solver.progress import PROGRESS_SCHEMA, ProgressEventKind, activate_progress
from windows_solver.response_batches import (
    PrecisionCapabilities,
    build_campaign_plan,
)
from windows_solver.response_engine import NumericalPolicy, VettedNativeDeterminantKernel


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
            "root_omega_re": "0.5",
            "root_omega_im": "-0.08",
            "root_residual_abs": "1e-60",
            "root_derivative_abs": "2.5",
            "root_converged": True,
            "truncation_radius_abs": "2e-55",
            "resolution_radius_abs": "3e-55",
            "seed_path_radius_abs": "4e-55",
        }


class JuliaResponseBackendTests(unittest.TestCase):
    def test_package_worker_declares_line_flushed_inner_progress_without_request_changes(self):
        worker = (
            Path(__file__).resolve().parents[1]
            / "src/windows_solver/data/julia/m02_worker.jl"
        ).read_text(encoding="utf-8")
        self.assertIn('const PROGRESS_PREFIX = "@@KERR_QNM_PROGRESS@@"', worker)
        self.assertIn("flush(stdout)", worker)
        for event in (
            "root_phase_started",
            "newton_iteration_started",
            "newton_iteration_completed",
            "determinant_started",
            "determinant_completed",
            "suboperation_started",
            "suboperation_completed",
        ):
            self.assertIn(f'progress_emit("{event}"', worker)
        self.assertIn('"acceptance_threshold" => string(tolerance)', worker)
        self.assertNotIn('document["progress', worker)

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
        self.assertEqual(readout.omega, complex(0.5, -0.08))
        self.assertEqual(readout.truncation_radius, 2.0e-55)
        self.assertTrue(readout.converged)
        self.assertEqual(backend.scientific_runtime["precision_digits"], 80)

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
