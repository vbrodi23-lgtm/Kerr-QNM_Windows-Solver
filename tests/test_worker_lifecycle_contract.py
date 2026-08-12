from __future__ import annotations

from contextlib import redirect_stderr
import io
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

import windows_solver.julia_response_backend as julia_backend
from windows_solver.cli import main
from windows_solver.julia_response_backend import (
    JULIA_PROGRESS_PREFIX,
    JuliaODEResourceLimitError,
    JuliaProgressProtocolError,
    JuliaResponseAdapter,
    JuliaResponseBackendError,
    JuliaWorkerTimeoutError,
)
from windows_solver.progress import (
    PROGRESS_SCHEMA,
    ProgressEventKind,
    activate_progress,
)


class WorkerLifecycleContractTests(unittest.TestCase):
    @staticmethod
    def _adapter(root: Path, runner) -> JuliaResponseAdapter:
        for name in ("julia.exe", "Project.toml", "Manifest.toml", "worker.jl"):
            (root / name).write_text(name, encoding="ascii")
        depot = root / "depot"
        depot.mkdir()
        return JuliaResponseAdapter(
            root / "julia.exe", root, depot, root / "worker.jl", {}, runner
        )

    @staticmethod
    def _worker_failure() -> dict[str, object]:
        return {
            "worker_exit_code": 21,
            "worker_timed_out": False,
            "worker_stderr_tail": "synthetic Julia traceback",
            "worker_error_type": "ODEResourceLimit",
            "worker_error_message": "Xin reached MaxIters",
            "failure": {
                "failure_code": "ODE_RESOURCE_LIMIT",
                "failure_class": "CONTROL",
                "limit_kind": "ode_solver_iterations",
                "ode_snapshot": {
                    "ode_leg": "Xin_inner_to_match",
                    "ode_retcode": "MaxIters",
                },
            },
        }

    @staticmethod
    def _force_stop_process(pid_path: Path) -> None:
        if not pid_path.is_file():
            return
        pid = int(pid_path.read_text(encoding="ascii"))
        if os.name == "nt":
            subprocess.run(
                ("taskkill", "/PID", str(pid), "/T", "/F"),
                check=False,
                capture_output=True,
            )
        else:
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass

    def test_reserved_progress_protocol_error_has_a_dedicated_type(self):
        with self.assertRaises(JuliaProgressProtocolError):
            julia_backend._forward_julia_progress_line(
                JULIA_PROGRESS_PREFIX + "{"
            )

    def test_semantically_invalid_reserved_progress_emits_error_then_fails(self):
        class Observer:
            def __init__(self):
                self.events = []

            def publish(self, event):
                self.events.append(event)

        observer = Observer()
        with (
            activate_progress(observer),
            self.assertRaises(JuliaProgressProtocolError),
        ):
            julia_backend._forward_julia_progress_line(
                JULIA_PROGRESS_PREFIX + json.dumps({"schema": PROGRESS_SCHEMA})
            )

        self.assertEqual(len(observer.events), 1)
        self.assertIs(observer.events[0].kind, ProgressEventKind.ERROR)

    def test_injected_runner_timeout_is_normalized_to_worker_timeout(self):
        def runner(command, **kwargs):
            raise subprocess.TimeoutExpired(
                command,
                kwargs["timeout"],
                output="partial stdout",
                stderr="worker stopped responding",
            )

        with tempfile.TemporaryDirectory() as temporary:
            adapter = self._adapter(Path(temporary), runner)
            with self.assertRaises(JuliaWorkerTimeoutError) as raised:
                adapter.evaluate({"schema_version": 1})

        self.assertEqual(raised.exception.worker_failure["worker_exit_code"], None)
        self.assertIs(raised.exception.worker_failure["worker_timed_out"], True)
        self.assertIn(
            "worker stopped responding",
            raised.exception.worker_failure["worker_stderr_tail"],
        )

    def test_production_popen_uses_a_new_posix_session(self):
        sentinel = RuntimeError("stop after launch arguments")
        with (
            patch.object(julia_backend, "_IS_WINDOWS", False, create=True),
            patch.object(subprocess, "Popen", side_effect=sentinel) as popen,
            self.assertRaisesRegex(RuntimeError, "launch arguments"),
        ):
            julia_backend._run_streamed_julia(
                ("julia",), cwd=Path.cwd(), env=os.environ, timeout=60
            )

        options = popen.call_args.kwargs
        self.assertIn("start_new_session", options)
        self.assertIs(options["start_new_session"], True)
        self.assertNotIn("creationflags", options)

    def test_production_popen_uses_a_new_windows_process_group(self):
        sentinel = RuntimeError("stop after launch arguments")
        with (
            patch.object(julia_backend, "_IS_WINDOWS", True, create=True),
            patch.object(subprocess, "Popen", side_effect=sentinel) as popen,
            self.assertRaisesRegex(RuntimeError, "launch arguments"),
        ):
            julia_backend._run_streamed_julia(
                ("julia",), cwd=Path.cwd(), env=os.environ, timeout=60
            )

        options = popen.call_args.kwargs
        launch_command = popen.call_args.args[0]
        self.assertEqual(launch_command[:4], (sys.executable, "-I", "-S", "-c"))
        self.assertEqual(launch_command[-1:], ("julia",))
        self.assertIn("creationflags", options)
        self.assertEqual(options["creationflags"], 0x00000200)
        self.assertIs(options["stdin"], subprocess.PIPE)
        self.assertNotIn("start_new_session", options)

    @unittest.skipIf(os.name == "nt", "POSIX process-group contract")
    def test_posix_tree_termination_kills_group_and_reaps_parent(self):
        process = Mock(pid=4321)
        process.poll.return_value = None
        process.wait.return_value = -signal.SIGKILL
        with (
            patch.object(julia_backend, "_IS_WINDOWS", False, create=True),
            patch.object(os, "killpg") as killpg,
        ):
            self.assertTrue(hasattr(julia_backend, "_terminate_process_tree"))
            julia_backend._terminate_process_tree(process)

        killpg.assert_called_once_with(4321, signal.SIGKILL)
        process.wait.assert_called()

    def test_arbitrary_base_exception_terminates_and_reaps_worker(self):
        class FatalWorkerProgress(BaseException):
            pass

        event = JULIA_PROGRESS_PREFIX + json.dumps({
            "schema": PROGRESS_SCHEMA,
            "kind": "request_started",
            "context": {},
            "payload": {},
        })
        script = f"print({event!r}, flush=True); import time; time.sleep(60)"
        terminate = julia_backend._terminate_process_tree
        with (
            patch.object(
                julia_backend,
                "_forward_julia_progress_line",
                side_effect=FatalWorkerProgress,
            ),
            patch.object(
                julia_backend,
                "_terminate_process_tree",
                wraps=terminate,
            ) as terminate_spy,
            self.assertRaises(FatalWorkerProgress),
        ):
            julia_backend._run_streamed_julia(
                (sys.executable, "-c", script),
                cwd=Path.cwd(),
                env=os.environ,
                timeout=5,
            )

        terminate_spy.assert_called_once()

    def test_reader_startup_base_exception_terminates_and_reaps_worker(self):
        class FatalThreadStartup(BaseException):
            pass

        terminate = julia_backend._terminate_process_tree
        with (
            patch.object(
                julia_backend.Thread,
                "start",
                side_effect=FatalThreadStartup,
            ),
            patch.object(
                julia_backend,
                "_terminate_process_tree",
                wraps=terminate,
            ) as terminate_spy,
            self.assertRaises(FatalThreadStartup),
        ):
            julia_backend._run_streamed_julia(
                (sys.executable, "-c", "import time; time.sleep(60)"),
                cwd=Path.cwd(),
                env=os.environ,
                timeout=5,
            )

        terminate_spy.assert_called_once()

    def test_ode_resource_limit_has_a_dedicated_backend_type(self):
        with self.assertRaises(JuliaODEResourceLimitError) as raised:
            julia_backend._raise_worker_failure(self._worker_failure())

        self.assertEqual(
            raised.exception.worker_failure["failure"]["failure_code"],
            "ODE_RESOURCE_LIMIT",
        )

    def test_other_ode_failure_remains_a_generic_backend_failure(self):
        receipt = self._worker_failure()
        receipt["failure"] = {
            "failure_code": "ODE_SOLVER_FAILURE",
            "failure_class": "CONTROL",
            "ode_snapshot": {"ode_retcode": "Unstable"},
        }
        with self.assertRaises(JuliaResponseBackendError) as raised:
            julia_backend._raise_worker_failure(receipt)

        self.assertIs(type(raised.exception), JuliaResponseBackendError)

    def test_resource_code_without_control_class_is_not_resource_typed(self):
        receipt = self._worker_failure()
        receipt["failure"]["failure_class"] = "NUMERICAL"
        with self.assertRaises(JuliaResponseBackendError) as raised:
            julia_backend._raise_worker_failure(receipt)

        self.assertIs(type(raised.exception), JuliaResponseBackendError)

    def test_malformed_optional_failure_does_not_erase_legacy_receipt(self):
        failure = JuliaResponseBackendError("synthetic worker failure")
        failure.worker_failure = self._worker_failure()
        failure.worker_failure["failure"] = {
            "failure_code": "ODE_RESOURCE_LIMIT",
            "arbitrary": object(),
        }

        receipt = julia_backend.worker_failure_payload(failure)

        self.assertIsNotNone(receipt)
        self.assertNotIn("failure", receipt)
        self.assertEqual(receipt["worker_exit_code"], 21)

    def test_windows_tree_termination_uses_taskkill_and_reaps_parent(self):
        process = Mock(pid=4321)
        process.poll.return_value = None
        process.wait.return_value = 1
        with (
            patch.object(julia_backend, "_IS_WINDOWS", True, create=True),
            patch.object(subprocess, "run") as run,
        ):
            self.assertTrue(hasattr(julia_backend, "_terminate_process_tree"))
            julia_backend._terminate_process_tree(process)

        self.assertEqual(
            run.call_args.args[0],
            ("taskkill", "/PID", "4321", "/T", "/F"),
        )
        process.wait.assert_called()

    def test_windows_job_owns_worker_tree_and_closes_after_clean_drain(self):
        process = Mock(pid=4321, returncode=0, _handle=9876)
        process.stdin = Mock()
        process.stdout = io.StringIO("")
        process.stderr = io.StringIO("")
        process.poll.return_value = 0
        process.wait.return_value = 0
        job = Mock()
        launch_order = []
        job.assign.side_effect = lambda worker: launch_order.append("assigned")
        process.stdin.write.side_effect = lambda token: launch_order.append("released")
        with (
            patch.object(julia_backend, "_IS_WINDOWS", True),
            patch.object(subprocess, "Popen", return_value=process),
            patch.object(
                julia_backend._WindowsKillOnCloseJob,
                "create",
                return_value=job,
            ),
        ):
            completed = julia_backend._run_streamed_julia(
                ("julia",), cwd=Path.cwd(), env=os.environ, timeout=60
            )

        self.assertEqual(completed.returncode, 0)
        job.assign.assert_called_once_with(process)
        process.stdin.write.assert_called_once_with("G")
        self.assertEqual(launch_order, ["assigned", "released"])
        process.stdin.flush.assert_called_once()
        process.stdin.close.assert_called_once()
        job.close.assert_called_once()
        job.terminate.assert_not_called()

    def test_windows_job_assignment_failure_never_releases_worker_gate(self):
        process = Mock(pid=4321, returncode=None, _handle=9876)
        process.stdin = Mock()
        process.stdout = io.StringIO("")
        process.stderr = io.StringIO("")
        process.poll.return_value = None
        process.wait.return_value = 1
        job = Mock()
        job.assign.side_effect = OSError("synthetic assignment failure")
        with (
            patch.object(julia_backend, "_IS_WINDOWS", True),
            patch.object(subprocess, "Popen", return_value=process),
            patch.object(subprocess, "run") as taskkill,
            patch.object(
                julia_backend._WindowsKillOnCloseJob,
                "create",
                return_value=job,
            ),
            self.assertRaisesRegex(
                JuliaResponseBackendError, "kill-on-close Windows job"
            ),
        ):
            julia_backend._run_streamed_julia(
                ("julia",), cwd=Path.cwd(), env=os.environ, timeout=60
            )

        process.stdin.write.assert_not_called()
        job.close.assert_called_once()
        job.terminate.assert_not_called()
        self.assertEqual(
            taskkill.call_args.args[0],
            ("taskkill", "/PID", "4321", "/T", "/F"),
        )

    def test_windows_job_terminates_descendants_after_parent_exit(self):
        process = Mock(pid=4321, returncode=0)
        process.poll.return_value = 0
        process.wait.return_value = 0
        job = Mock()
        with (
            patch.object(julia_backend, "_IS_WINDOWS", True),
            patch.object(subprocess, "run") as taskkill,
        ):
            julia_backend._terminate_process_tree(process, job)

        job.terminate.assert_called_once()
        taskkill.assert_not_called()
        process.wait.assert_called()

    def test_deadline_cleans_descendant_that_holds_pipe_after_parent_exit(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            child_pid = root / "child.pid"
            marker = root / "child.marker"
            child = (
                "import os,sys,time; "
                "open(sys.argv[1],'w',encoding='ascii').write(str(os.getpid())); "
                "f=open(sys.argv[2],'a',encoding='ascii'); "
                "[(f.write('x'),f.flush(),time.sleep(.02)) for _ in range(3000)]"
            )
            parent = (
                "import subprocess,sys; "
                f"subprocess.Popen([sys.executable,'-c',{child!r},sys.argv[1],sys.argv[2]])"
            )
            try:
                completed = julia_backend._run_streamed_julia(
                    (
                        sys.executable,
                        "-c",
                        parent,
                        str(child_pid),
                        str(marker),
                    ),
                    cwd=root,
                    env=os.environ,
                    timeout=1,
                )
                self.assertTrue(completed.timed_out)
                deadline = time.monotonic() + 2
                while not marker.exists() and time.monotonic() < deadline:
                    time.sleep(0.01)
                before = marker.stat().st_size
                time.sleep(0.2)
                self.assertEqual(marker.stat().st_size, before)
            finally:
                self._force_stop_process(child_pid)

    def test_deadline_also_bounds_inherited_stderr_after_parent_exit(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            child_pid = root / "child.pid"
            marker = root / "child.marker"
            child = (
                "import os,sys,time; "
                "open(sys.argv[1],'w',encoding='ascii').write(str(os.getpid())); "
                "f=open(sys.argv[2],'a',encoding='ascii'); "
                "[(f.write('x'),f.flush(),time.sleep(.02)) for _ in range(3000)]"
            )
            parent = (
                "import subprocess,sys; "
                f"subprocess.Popen([sys.executable,'-c',{child!r},sys.argv[1],sys.argv[2]],"
                "stdout=subprocess.DEVNULL)"
            )
            try:
                completed = julia_backend._run_streamed_julia(
                    (
                        sys.executable,
                        "-c",
                        parent,
                        str(child_pid),
                        str(marker),
                    ),
                    cwd=root,
                    env=os.environ,
                    timeout=1,
                )
                self.assertTrue(completed.timed_out)
                deadline = time.monotonic() + 2
                while not marker.exists() and time.monotonic() < deadline:
                    time.sleep(0.01)
                before = marker.stat().st_size
                time.sleep(0.2)
                self.assertEqual(marker.stat().st_size, before)
            finally:
                self._force_stop_process(child_pid)

    def test_cli_request_failure_preserves_structured_worker_receipt(self):
        failure = JuliaResponseBackendError("M02 Julia worker failed with code 21")
        failure.worker_failure = self._worker_failure()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            checkpoint = root / "checkpoint.json"
            with (
                patch("windows_solver.cli.Path.cwd", return_value=root),
                patch(
                    "windows_solver.cli._campaign_selected", side_effect=failure
                ),
                redirect_stderr(io.StringIO()),
                self.assertRaises(JuliaResponseBackendError),
            ):
                main([
                    "campaign-run",
                    "selection.json",
                    "--checkpoint",
                    "checkpoint.json",
                    "--progress",
                    "normal",
                ])
            status = json.loads(
                Path(f"{checkpoint}.status.json").read_text(encoding="utf-8")
            )

        self.assertEqual(status["kind"], "request_failed")
        self.assertIn("worker_failure", status["payload"])
        self.assertEqual(
            status["payload"]["worker_failure"], failure.worker_failure
        )


if __name__ == "__main__":
    unittest.main()
