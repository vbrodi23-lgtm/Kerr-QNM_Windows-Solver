from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from windows_solver.contracts import canonical_json_bytes
from windows_solver.julia_response_backend import (
    JuliaResponseAdapter,
    JuliaResponseBackendError,
)
from windows_solver.root_readout_cache import (
    ROOT_READOUT_STORE_DIRECTORY_NAME,
    RootReadoutLookupStatus,
    RootReadoutStore,
    root_readout_identity_sha256,
    runtime_identity_sha256,
)


def _runtime_receipt(root: Path) -> Path:
    """Provision one minimal runtime the adapter is willing to authenticate."""

    julia = root / "julia.exe"
    worker = root / "m02_worker.jl"
    project = root / "project"
    project.mkdir(exist_ok=True)
    depot = root / "depot"
    depot.mkdir(exist_ok=True)
    julia.write_text("julia", encoding="ascii")
    worker.write_text("worker", encoding="ascii")
    (project / "Project.toml").write_text("project", encoding="ascii")
    (project / "Manifest.toml").write_text("manifest", encoding="ascii")
    runtime = root / "runtime"
    runtime.mkdir(exist_ok=True)
    (runtime / "python-runtime.json").write_bytes(canonical_json_bytes({
        "julia_runtime": {
            "requested": True,
            "version": "1.10.11",
            "executable": str(julia),
            "executable_sha256": hashlib.sha256(julia.read_bytes()).hexdigest(),
            "arguments": [],
            "worker": str(worker),
            "worker_sha256": hashlib.sha256(worker.read_bytes()).hexdigest(),
            "depot": str(depot),
            "project": str(project),
            "manifest_sha256": hashlib.sha256(
                (project / "Manifest.toml").read_bytes()
            ).hexdigest(),
            "sources": [],
        },
    }))
    return runtime


class _RecordingRunner:
    """Answer a readout while counting how often the worker actually ran."""

    def __init__(self) -> None:
        self.commands: list[tuple[str, ...]] = []

    def __call__(self, command, **kwargs):
        self.commands.append(tuple(command))
        request = json.loads(Path(command[-2]).read_text(encoding="utf-8"))
        Path(command[-1]).write_bytes(canonical_json_bytes({
            "status": "ok",
            "request_sha256": request["request_sha256"],
            "root": {"real": "0.5", "imaginary": "-0.1"},
        }))
        return SimpleNamespace(returncode=0, stdout="", stderr="")


class RootReadoutStoreTests(unittest.TestCase):
    def _store(self, root: Path) -> RootReadoutStore:
        return RootReadoutStore(root / ROOT_READOUT_STORE_DIRECTORY_NAME)

    def test_retained_readout_round_trips_under_its_own_identity(self):
        """Catches losing a finished readout that an interrupted stage must reuse."""

        with tempfile.TemporaryDirectory() as temporary:
            store = self._store(Path(temporary))
            request_sha256 = "a" * 64
            runtime = "b" * 64
            response = {"status": "ok", "request_sha256": request_sha256}
            store.publish(
                request_sha256=request_sha256,
                runtime_identity=runtime,
                response=response,
            )
            self.assertEqual(store.stored_count, 1)
            lookup = store.lookup(
                request_sha256=request_sha256, runtime_identity=runtime
            )
            self.assertIs(lookup.status, RootReadoutLookupStatus.HIT)
            self.assertEqual(lookup.response, response)

    def test_other_request_or_runtime_is_a_miss_rather_than_a_reuse(self):
        """Catches reusing numerics across a different request or worker build."""

        with tempfile.TemporaryDirectory() as temporary:
            store = self._store(Path(temporary))
            request_sha256 = "a" * 64
            runtime = "b" * 64
            store.publish(
                request_sha256=request_sha256,
                runtime_identity=runtime,
                response={"status": "ok", "request_sha256": request_sha256},
            )
            other_request = store.lookup(
                request_sha256="c" * 64, runtime_identity=runtime
            )
            other_runtime = store.lookup(
                request_sha256=request_sha256, runtime_identity="d" * 64
            )
            self.assertIs(other_request.status, RootReadoutLookupStatus.MISSING)
            self.assertIs(other_runtime.status, RootReadoutLookupStatus.MISSING)

    def test_unsuccessful_readout_is_never_retained(self):
        """Catches caching a worker failure as though it were a completed solve."""

        with tempfile.TemporaryDirectory() as temporary:
            store = self._store(Path(temporary))
            for response in (
                {"status": "error", "request_sha256": "a" * 64},
                {"status": "ok", "request_sha256": "e" * 64},
            ):
                with self.assertRaises(ValueError):
                    store.publish(
                        request_sha256="a" * 64,
                        runtime_identity="b" * 64,
                        response=response,
                    )
            self.assertEqual(store.stored_count, 0)

    def test_rewritten_entry_is_reported_corrupt_instead_of_trusted(self):
        """Catches trusting a cache file whose contents no longer match its name."""

        with tempfile.TemporaryDirectory() as temporary:
            store = self._store(Path(temporary))
            request_sha256 = "a" * 64
            runtime = "b" * 64
            path = store.publish(
                request_sha256=request_sha256,
                runtime_identity=runtime,
                response={"status": "ok", "request_sha256": request_sha256},
            )
            entry = json.loads(path.read_text(encoding="utf-8"))
            entry["response"] = {"status": "ok", "request_sha256": "f" * 64}
            path.write_bytes(canonical_json_bytes(entry))
            lookup = store.lookup(
                request_sha256=request_sha256, runtime_identity=runtime
            )
            self.assertIs(lookup.status, RootReadoutLookupStatus.CORRUPT)
            self.assertIsNone(lookup.response)

    def test_identity_binds_request_and_runtime_together(self):
        """Catches an address that ignores which runtime answered the readout."""

        first = root_readout_identity_sha256(
            request_sha256="a" * 64, runtime_identity="b" * 64
        )
        second = root_readout_identity_sha256(
            request_sha256="a" * 64, runtime_identity="c" * 64
        )
        self.assertNotEqual(first, second)
        self.assertNotEqual(
            runtime_identity_sha256({"worker_sha256": "a"}),
            runtime_identity_sha256({"worker_sha256": "b"}),
        )


class JuliaAdapterReadoutReuseTests(unittest.TestCase):
    def test_completed_readout_is_reused_without_reinvoking_the_worker(self):
        """Catches discarding finished readouts when a promoted stage restarts."""

        with tempfile.TemporaryDirectory() as temporary:
            runtime = _runtime_receipt(Path(temporary))
            first = _RecordingRunner()
            adapter = JuliaResponseAdapter.from_runtime_receipt(
                runtime_root=runtime, runner=first
            )
            original = adapter.evaluate({"schema_version": 1, "operation": "x"})
            self.assertEqual(len(first.commands), 1)

            # A later campaign process rebuilds the adapter from the same runtime.
            second = _RecordingRunner()
            resumed = JuliaResponseAdapter.from_runtime_receipt(
                runtime_root=runtime, runner=second
            )
            reused = resumed.evaluate({"schema_version": 1, "operation": "x"})
            self.assertEqual(second.commands, [])
            self.assertEqual(reused, original)

    def test_distinct_request_still_reaches_the_worker(self):
        """Catches a cache that answers a readout it was never given."""

        with tempfile.TemporaryDirectory() as temporary:
            runtime = _runtime_receipt(Path(temporary))
            runner = _RecordingRunner()
            adapter = JuliaResponseAdapter.from_runtime_receipt(
                runtime_root=runtime, runner=runner
            )
            adapter.evaluate({"schema_version": 1, "operation": "x"})
            adapter.evaluate({"schema_version": 1, "operation": "y"})
            self.assertEqual(len(runner.commands), 2)

    def test_failed_readout_leaves_no_reusable_entry(self):
        """Catches a failed solve being replayed as a completed one."""

        with tempfile.TemporaryDirectory() as temporary:
            runtime = _runtime_receipt(Path(temporary))

            def failing(command, **kwargs):
                Path(command[-1]).write_bytes(canonical_json_bytes({
                    "schema_version": 1,
                    "status": "error",
                    "error_type": "ErrorException",
                    "message": "Xin failed",
                }))
                return SimpleNamespace(returncode=9, stdout="", stderr="")

            adapter = JuliaResponseAdapter.from_runtime_receipt(
                runtime_root=runtime, runner=failing
            )
            with self.assertRaises(JuliaResponseBackendError):
                adapter.evaluate({"schema_version": 1})
            store = RootReadoutStore(runtime / ROOT_READOUT_STORE_DIRECTORY_NAME)
            self.assertEqual(store.stored_count, 0)

    def test_corrupt_entry_recomputes_instead_of_failing_the_readout(self):
        """Catches letting a damaged work cache break an otherwise valid solve."""

        with tempfile.TemporaryDirectory() as temporary:
            runtime = _runtime_receipt(Path(temporary))
            runner = _RecordingRunner()
            adapter = JuliaResponseAdapter.from_runtime_receipt(
                runtime_root=runtime, runner=runner
            )
            expected = adapter.evaluate({"schema_version": 1})
            store = RootReadoutStore(runtime / ROOT_READOUT_STORE_DIRECTORY_NAME)
            for path in store.root.glob("*.json"):
                path.write_text("{ not json", encoding="utf-8")
            recovered = adapter.evaluate({"schema_version": 1})
            self.assertEqual(len(runner.commands), 2)
            self.assertEqual(recovered, expected)

    def test_cache_can_be_switched_off(self):
        """Catches removing the operator's ability to force a clean recompute."""

        with tempfile.TemporaryDirectory() as temporary:
            runtime = _runtime_receipt(Path(temporary))
            runner = _RecordingRunner()
            with patch.dict(
                "os.environ", {"KERR_QNM_ROOT_READOUT_CACHE": "0"}, clear=False
            ):
                adapter = JuliaResponseAdapter.from_runtime_receipt(
                    runtime_root=runtime, runner=runner
                )
                self.assertIsNone(adapter.readout_cache)
                adapter.evaluate({"schema_version": 1})
                adapter.evaluate({"schema_version": 1})
            self.assertEqual(len(runner.commands), 2)


if __name__ == "__main__":
    unittest.main()
