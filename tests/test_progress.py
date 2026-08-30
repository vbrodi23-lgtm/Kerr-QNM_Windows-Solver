from __future__ import annotations

import io
import json
import sys
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from contextvars import copy_context
from threading import Thread
import unittest
from unittest.mock import patch

from windows_solver.campaign_survey import (
    _attempted_endpoint_geometries_for_trace,
    _attempted_endpoint_orders_for_trace,
)
from windows_solver.campaign_reports import CampaignReportModel
from windows_solver.progress import (
    PROGRESS_SCHEMA,
    ProgressEventKind,
    ProgressMode,
    activate_progress,
    emit_progress,
    ingest_external_progress,
    progress_scope,
)
from windows_solver.progress_output import CampaignProgressReporter
from windows_solver.cli import build_parser


class RecordingObserver:
    def __init__(self) -> None:
        self.events = []

    def publish(self, event) -> None:
        self.events.append(event)


class ProgressBusTests(unittest.TestCase):

    def test_mixed_endpoint_receipts_project_valid_recovery_traces(self):
        horizon = {
            "schema": "windows-solver.exterior-endpoint-recovery-receipt/2",
            "attempts": [
                {"attempted_endpoint_order": 28, "rho": "-10"},
                {"attempted_endpoint_order": 56, "rho": "-25"},
            ],
        }
        infinity = {
            "schema": "windows-solver.exterior-endpoint-recovery-receipt/1",
            "attempted_endpoint_orders": [28],
            "attempts": [{
                "attempted_endpoint_order": 28,
                "attempted_geometry": "100",
            }],
        }

        attempted_orders = [
            _attempted_endpoint_orders_for_trace(receipt)
            for receipt in (horizon, infinity)
        ]
        attempted_geometries = [
            _attempted_endpoint_geometries_for_trace(receipt)
            for receipt in (horizon, infinity)
        ]
        with progress_scope(
            attempted_endpoint_orders=attempted_orders,
            attempted_endpoint_geometries=attempted_geometries,
        ):
            pass
        self.assertEqual(attempted_orders, [[28, 56], [28]])
        self.assertEqual(attempted_geometries, [["-10", "-25"], ["100"]])

    def test_campaign_run_and_resume_default_to_normal_progress(self):
        parser = build_parser()
        for command in ("campaign-run", "campaign-resume"):
            arguments = parser.parse_args(
                [command, "selection.json", "--checkpoint", "checkpoint.json"]
            )
            self.assertEqual(arguments.progress, "normal")
            traced = parser.parse_args(
                [
                    command,
                    "selection.json",
                    "--checkpoint",
                    "checkpoint.json",
                    "--progress",
                    "trace",
                ]
            )
            self.assertEqual(traced.progress, "trace")

    def test_progress_context_carries_unambiguous_omega_and_counter_fields(self):
        observer = RecordingObserver()
        omega = {"real": 0.5, "imaginary": -0.1}
        with activate_progress(observer), progress_scope(
            seed_omega=omega,
            current_omega=omega,
            candidate_omega=omega,
            determinant_index_leaf=137,
            determinant_index_phase=42,
            determinant_index_newton=3,
        ):
            emit_progress(ProgressEventKind.DETERMINANT_COMPLETED)

        context = observer.events[0].context
        self.assertEqual(context.seed_omega, omega)
        self.assertEqual(context.current_omega, omega)
        self.assertEqual(context.candidate_omega, omega)
        self.assertEqual(context.determinant_index_leaf, 137)
        self.assertEqual(context.determinant_index_phase, 42)
        self.assertEqual(context.determinant_index_newton, 3)

    def test_progress_context_carries_seed_strategy_without_entering_scientific_payloads(self):
        observer = RecordingObserver()
        with activate_progress(observer), progress_scope(
            seed_kind="EPSILON_CONTINUATION",
            fallback_used=False,
        ):
            emit_progress(ProgressEventKind.ROOT_SEED_SELECTED)

        context = observer.events[0].context
        self.assertEqual(context.seed_kind, "EPSILON_CONTINUATION")
        self.assertIs(context.fallback_used, False)

    def test_progress_scope_carries_the_complete_hierarchy_without_global_leakage(self):
        observer = RecordingObserver()
        with activate_progress(observer), progress_scope(
            leaf_index=1,
            leaf_count=1,
            leaf_id="leaf-1",
            role="primary",
            mode={"s": -2, "ell": 2, "m": 2, "n": 0},
            spin=0.95,
            mechanism_id="horizon-admittance",
            precision_digits=64,
        ):
            emit_progress(ProgressEventKind.ROOT_PHASE_STARTED, phase="PRIMARY")
        emit_progress(ProgressEventKind.ROOT_PHASE_STARTED, phase="OUTSIDE")

        self.assertEqual(len(observer.events), 1)
        event = observer.events[0]
        self.assertEqual(event.context.leaf_id, "leaf-1")
        self.assertEqual(event.context.mode["ell"], 2)
        self.assertEqual(event.payload["phase"], "PRIMARY")

    def test_progress_modes_are_exact(self):
        self.assertEqual(
            [item.value for item in ProgressMode], ["quiet", "normal", "trace"]
        )

    def test_progress_scope_restores_outer_context_after_nested_exception(self):
        observer = RecordingObserver()
        with activate_progress(observer), progress_scope(leaf_id="leaf-1"):
            with self.assertRaisesRegex(RuntimeError, "stop"):
                with progress_scope(phase="PRIMARY"):
                    raise RuntimeError("stop")
            emit_progress(ProgressEventKind.LEAF_COMPLETED)

        event = observer.events[0]
        self.assertEqual(event.context.leaf_id, "leaf-1")
        self.assertIsNone(event.context.phase)

    def test_event_context_and_payload_are_immutable_snapshots(self):
        observer = RecordingObserver()
        mode = {"ell": 2}
        payload = {"result": {"residual": 1.0}}
        with activate_progress(observer), progress_scope(mode=mode):
            emit_progress(ProgressEventKind.DETERMINANT_EVALUATED, **payload)
        mode["ell"] = 99
        payload["result"]["residual"] = 99.0

        event = observer.events[0]
        self.assertEqual(event.context.mode["ell"], 2)
        self.assertEqual(event.payload["result"]["residual"], 1.0)
        with self.assertRaises(TypeError):
            event.payload["new"] = "value"

    def test_external_event_rejects_unknown_schema_kind_or_context_key(self):
        valid = {
            "schema": PROGRESS_SCHEMA,
            "kind": ProgressEventKind.ROOT_PHASE_STARTED.value,
            "context": {"leaf_id": "leaf-1"},
            "payload": {"phase": "PRIMARY"},
        }
        observer = RecordingObserver()
        with activate_progress(observer):
            ingest_external_progress(valid)
            with self.assertRaises(ValueError):
                ingest_external_progress({**valid, "schema": "unknown/v1"})
            with self.assertRaises(ValueError):
                ingest_external_progress({**valid, "kind": "unknown_kind"})
            with self.assertRaises(ValueError):
                ingest_external_progress(
                    {**valid, "context": {"leaf_id": "leaf-1", "untrusted": 1}}
                )

        self.assertEqual([event.kind for event in observer.events], [
            ProgressEventKind.ROOT_PHASE_STARTED
        ])

    def test_external_progress_overlays_only_its_context_fragment(self):
        observer = RecordingObserver()
        with activate_progress(observer), progress_scope(
            leaf_index=4,
            leaf_id="leaf-4",
            readout_index=9,
            readout_role="positive",
        ):
            ingest_external_progress(
                {
                    "schema": PROGRESS_SCHEMA,
                    "kind": ProgressEventKind.ROOT_PHASE_STARTED.value,
                    "context": {"phase": "PRIMARY"},
                    "payload": {"source": "reader"},
                }
            )

        context = observer.events[0].context
        self.assertEqual(context.leaf_index, 4)
        self.assertEqual(context.leaf_id, "leaf-4")
        self.assertEqual(context.readout_index, 9)
        self.assertEqual(context.readout_role, "positive")
        self.assertEqual(context.phase, "PRIMARY")

    def test_external_progress_uses_explicitly_propagated_reader_context(self):
        observer = RecordingObserver()
        with activate_progress(observer), progress_scope(leaf_id="leaf-reader"):
            reader_context = copy_context()

            def read_one_event():
                ingest_external_progress(
                    {
                        "schema": PROGRESS_SCHEMA,
                        "kind": ProgressEventKind.ROOT_PHASE_STARTED.value,
                        "context": {"phase": "PRIMARY"},
                        "payload": {"source": "thread"},
                    }
                )

            thread = Thread(target=reader_context.run, args=(read_one_event,))
            thread.start()
            thread.join()

        self.assertEqual(len(observer.events), 1)
        self.assertEqual(observer.events[0].context.leaf_id, "leaf-reader")
        self.assertEqual(observer.events[0].context.phase, "PRIMARY")

    def test_external_ode_progress_rejects_malformed_solver_counters(self):
        valid = {
            "schema": PROGRESS_SCHEMA,
            "kind": "ode_solve_completed",
            "context": {"suboperation": "Xin"},
            "payload": {
                "ode_solve_id": 4,
                "ode_leg": "Xin_inner_to_match",
                "ode_stats_scope": "leg",
                "ode_t_start": "-5000.0",
                "ode_t_end": "0.0",
                "ode_t_current": "0.0",
                "ode_retcode": "Success",
                "ode_endpoint_reached": True,
                "ode_rhs_evaluations": 4096,
                "ode_accepted_steps": 1024,
                "ode_rejected_steps": 3,
                "ode_jacobian_evaluations": 0,
                "ode_linear_solves": 0,
                "ode_nonlinear_iterations": 0,
                "ode_nonlinear_convergence_failures": 0,
                "ode_last_accepted_step_abs": "0.25",
                "ode_min_accepted_step_abs": "1e-12",
                "ode_proposed_step_abs": None,
                "ode_algorithm_configured": "AutoVern9(Rosenbrock23(autodiff=false))",
                "elapsed_seconds": 3.0,
            },
        }
        observer = RecordingObserver()
        with activate_progress(observer):
            ingest_external_progress(valid)
            with self.assertRaises(ValueError):
                ingest_external_progress({
                    **valid,
                    "payload": {
                        **valid["payload"],
                        "ode_accepted_steps": "1024",
                    },
                })

        self.assertEqual(len(observer.events), 1)
        self.assertEqual(observer.events[0].payload["ode_accepted_steps"], 1024)

    def test_mutable_leaf_values_are_snapshotted_without_live_references(self):
        class MutableLeaf:
            def __init__(self, value):
                self.value = value

            def __repr__(self):
                return f"MutableLeaf({self.value!r})"

        observer = RecordingObserver()
        mode_leaf = bytearray(b"before")
        payload_leaf = MutableLeaf("before")
        with activate_progress(observer), progress_scope(
            leaf_index=1, mode={"blob": mode_leaf}
        ):
            emit_progress(
                ProgressEventKind.DETERMINANT_EVALUATED,
                diagnostic=payload_leaf,
            )
        mode_leaf[:] = b"after!"
        payload_leaf.value = "after"

        event = observer.events[0]
        self.assertEqual(event.context.mode["blob"], b"before")
        self.assertEqual(event.payload["diagnostic"], "MutableLeaf('before')")

        with TemporaryDirectory() as directory:
            checkpoint = Path(directory) / "checkpoint.json"
            reporter = CampaignProgressReporter("trace", checkpoint, io.StringIO())
            reporter.publish(event)
            record = json.loads(
                (Path(f"{checkpoint}.progress") / "leaf-000001.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()[1]
            )

        self.assertEqual(record["context"]["mode"]["blob"], "b'before'")
        self.assertEqual(record["payload"]["diagnostic"], "MutableLeaf('before')")


def _event(kind: ProgressEventKind, **context_values):
    observer = RecordingObserver()
    with activate_progress(observer), progress_scope(**context_values):
        emit_progress(kind, phase=context_values.get("phase", "PRIMARY"))
    return observer.events[0]


def _payload_event(kind: ProgressEventKind, payload, **context_values):
    observer = RecordingObserver()
    with activate_progress(observer), progress_scope(**context_values):
        emit_progress(kind, **payload)
    return observer.events[0]


class CampaignProgressReporterTests(unittest.TestCase):
    def setUp(self):
        self._reporter_directory = TemporaryDirectory()
        self.reporter_checkpoint = (
            Path(self._reporter_directory.name) / "checkpoint.json"
        )

    def tearDown(self):
        self._reporter_directory.cleanup()

    def _console_reporter(self, stream):
        # StringIO can model terminal output but can never supply a real Windows
        # console handle to SetConsoleMode.
        with patch.object(
            CampaignProgressReporter,
            "_enable_virtual_terminal",
            return_value=True,
        ):
            return CampaignProgressReporter(
                "normal", self.reporter_checkpoint, stream
            )

    def test_normal_defaults_to_the_main_stdout_console(self):
        class ConsoleStream(io.StringIO):
            def isatty(self):
                return True

        console = ConsoleStream()
        with patch("windows_solver.progress_output.sys.stdout", console):
            reporter = CampaignProgressReporter("normal", self.reporter_checkpoint)

        self.assertIs(reporter.stream, console)

    def test_normal_keeps_redirected_canonical_stdout_clean(self):
        redirected = io.StringIO()
        with patch("windows_solver.progress_output.sys.stdout", redirected):
            reporter = CampaignProgressReporter("normal", self.reporter_checkpoint)

        self.assertIs(reporter.stream, sys.stderr)

    def test_normal_non_terminal_preserves_lifecycle_and_detail_lines(self):
        stream = io.StringIO()
        reporter = CampaignProgressReporter("normal", self.reporter_checkpoint, stream)
        events = (
            _payload_event(
                ProgressEventKind.LEAF_REUSED,
                {"state": "PRODUCED"},
                leaf_id="leaf-1",
            ),
            _event(ProgressEventKind.CHECKPOINT_WRITING, leaf_id="leaf-2"),
            _event(ProgressEventKind.CHECKPOINT_WRITTEN, leaf_id="leaf-2"),
            _payload_event(
                ProgressEventKind.PRECISION_STAGE_COMPLETED,
                {"numerical_state": "CONVERGED", "leaf_state": "PRODUCED"},
                leaf_id="leaf-2",
            ),
            _event(ProgressEventKind.ROOT_PHASE_STARTED, leaf_id="leaf-2"),
            _event(ProgressEventKind.NEWTON_ITERATION_STARTED, leaf_id="leaf-2"),
            _payload_event(
                ProgressEventKind.DETERMINANT_COMPLETED,
                {"determinant_abs": 1.0e-12},
                leaf_id="leaf-2",
            ),
            _event(ProgressEventKind.SUBOPERATION_COMPLETED, leaf_id="leaf-2"),
        )
        for event in events:
            reporter.publish(event)

        output = stream.getvalue()
        for kind in (
            "leaf_reused",
            "checkpoint_writing",
            "checkpoint_written",
            "precision_stage_completed",
            "root_phase_started",
            "newton_iteration_started",
            "determinant_completed",
            "suboperation_completed",
        ):
            self.assertIn(kind, output)

    def test_promoted_stage_start_clears_prior_precision_live_solver_state(self):
        reporter = CampaignProgressReporter(
            "normal", self.reporter_checkpoint, io.StringIO()
        )
        base = {
            "leaf_id": "leaf-1",
            "leaf_index": 1,
            "leaf_count": 212,
            "role": "primary",
            "mode": {"s": -2, "ell": 2, "m": 2, "n": 0},
            "spin": 0.9999,
            "mechanism_id": "horizon-admittance",
        }
        reporter.publish(_event(
            ProgressEventKind.PRECISION_STAGE_STARTED,
            **base,
            precision_digits=64,
        ))
        reporter.publish(_payload_event(
            ProgressEventKind.ROOT_SEED_SELECTED,
            {"seed_kind": "AUTHENTICATED_BACKGROUND", "fallback_used": False},
            **base,
            precision_digits=64,
            phase="PRIMARY",
            seed_kind="AUTHENTICATED_BACKGROUND",
            fallback_used=False,
        ))
        reporter.publish(_payload_event(
            ProgressEventKind.NEWTON_ITERATION_STARTED,
            {"determinant_abs": "9.87654321e-7"},
            **base,
            precision_digits=64,
            phase="PRIMARY",
            newton_index=7,
            newton_limit=16,
            current_omega={"real": "0.7", "imaginary": "-0.1"},
        ))
        reporter.publish(_payload_event(
            ProgressEventKind.DETERMINANT_COMPLETED,
            {"determinant_abs": "9.87654321e-7"},
            **base,
            precision_digits=64,
            phase="PRIMARY",
            suboperation="Xin",
        ))
        reporter.publish(_payload_event(
            ProgressEventKind.SUBOPERATION_PROGRESS,
            {
                "suboperation": "Xin",
                "rhs_evaluations": 123456,
                "rho_span_fraction": 0.4,
                "elapsed_seconds": 99.0,
            },
            **base,
            precision_digits=64,
            phase="PRIMARY",
            suboperation="Xin",
        ))

        reporter.publish(_event(
            ProgressEventKind.PRECISION_STAGE_STARTED,
            **base,
            precision_digits=80,
        ))
        live = reporter._live_execution_mapping()

        self.assertEqual(live["precision_digits"], 80)
        self.assertEqual(live["worker"], "Julia")
        for name in (
            "phase",
            "seed_kind",
            "seed_authenticated",
            "current_omega",
            "newton_index",
            "newton_limit",
            "determinant_abs",
            "best_determinant_abs",
            "suboperation",
            "radial_suboperation",
            "radial_rhs_evaluations",
            "radial_rho_span_fraction",
            "radial_elapsed_seconds",
        ):
            self.assertIsNone(live[name], name)

    def test_live_dashboard_keeps_determinant_counter_scopes_separate_at_phase_boundary(self):
        reporter = CampaignProgressReporter(
            "normal", self.reporter_checkpoint, io.StringIO()
        )
        base = {
            "leaf_id": "leaf-1",
            "leaf_index": 1,
            "leaf_count": 212,
            "precision_digits": 64,
            "component_pass": "primary",
            "readout_index": 2,
        }
        reporter.publish(_event(
            ProgressEventKind.PRECISION_STAGE_STARTED,
            **{name: value for name, value in base.items() if name != "readout_index"},
        ))
        prior = {**base, "readout_index": 1, "phase": "PRIMARY"}
        for _ in range(296):
            reporter.publish(_event(ProgressEventKind.DETERMINANT_STARTED, **prior))

        current = {**base, "phase": "PRIMARY"}
        reporter.publish(_event(
            ProgressEventKind.NEWTON_ITERATION_STARTED,
            **current,
            newton_index=2,
            newton_limit=12,
        ))
        for _ in range(10):
            reporter.publish(_event(
                ProgressEventKind.DETERMINANT_STARTED,
                **current,
                newton_index=2,
                newton_limit=12,
            ))

        active = "\n".join(reporter._current_execution_lines(compact=True))
        self.assertIn(
            "Dets leaf 306 phase 10 Newton 10",
            active,
        )

        next_phase = {**base, "phase": "TRUNCATION"}
        reporter.publish(_event(ProgressEventKind.ROOT_PHASE_STARTED, **next_phase))
        boundary = "\n".join(reporter._current_execution_lines(compact=True))
        self.assertIn(
            "Dets leaf 306 phase - Newton -",
            boundary,
        )
        self.assertNotIn("Determinant 306", boundary)

        reporter.publish(_event(
            ProgressEventKind.NEWTON_ITERATION_STARTED,
            **next_phase,
            newton_index=1,
            newton_limit=12,
        ))
        reporter.publish(_event(
            ProgressEventKind.DETERMINANT_STARTED,
            **next_phase,
            newton_index=1,
            newton_limit=12,
        ))
        restarted = "\n".join(reporter._current_execution_lines(compact=True))
        self.assertIn(
            "Dets leaf 307 phase 1 Newton 1",
            restarted,
        )

    def test_worker_ode_segment_stats_reach_status_and_dashboard_state(self):
        reporter = CampaignProgressReporter(
            "normal", self.reporter_checkpoint, io.StringIO()
        )
        reporter.publish(_event(
            ProgressEventKind.PRECISION_STAGE_STARTED,
            leaf_id="leaf-1",
            leaf_index=1,
            leaf_count=212,
            precision_digits=80,
        ))
        payload = {
            "ode_solve_id": 4,
            "ode_leg": "Xin_inner_to_match",
            "ode_stats_scope": "leg",
            "ode_t_start": "-5000.0",
            "ode_t_end": "0.0",
            "ode_t_current": "0.0",
            "ode_retcode": "Success",
            "ode_endpoint_reached": True,
            "ode_rhs_evaluations": 4096,
            "ode_accepted_steps": 1024,
            "ode_rejected_steps": 3,
            "ode_jacobian_evaluations": 0,
            "ode_linear_solves": 0,
            "ode_nonlinear_iterations": 0,
            "ode_nonlinear_convergence_failures": 0,
            "ode_last_accepted_step_abs": "0.25",
            "ode_min_accepted_step_abs": "1e-12",
            "ode_proposed_step_abs": None,
            "ode_algorithm_configured": "AutoVern9(Rosenbrock23(autodiff=false))",
            "elapsed_seconds": 3.0,
        }
        reporter.publish(_payload_event(
            ProgressEventKind.ODE_SOLVE_COMPLETED,
            payload,
            leaf_id="leaf-1",
            leaf_index=1,
            leaf_count=212,
            precision_digits=80,
            phase="PRIMARY",
            suboperation="Xin",
        ))

        live = reporter._live_execution_mapping()
        self.assertEqual(live["ode_leg"], "Xin_inner_to_match")
        self.assertEqual(live["ode_retcode"], "Success")
        self.assertEqual(live["ode_rhs_evaluations"], 4096)
        self.assertEqual(live["ode_accepted_steps"], 1024)
        self.assertEqual(live["ode_rejected_steps"], 3)
        status = json.loads(
            Path(f"{self.reporter_checkpoint}.status.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(status["live_execution"]["ode_leg"], "Xin_inner_to_match")
        self.assertEqual(status["live_execution"]["ode_rhs_evaluations"], 4096)
        dashboard = "\n".join(reporter._current_execution_lines())
        compact = "\n".join(reporter._current_execution_lines(compact=True))
        for expected in (
            "#4 Xin_inner_to_match",
            "ret=Success",
            "nf=4096",
            "accept/reject=1024/3",
            "jac/linear=0/0",
            "nonlinear/fail=0/0",
            "dt last/min/proposed=0.25/1e-12/-",
            "AutoVern9(Rosenbrock23(autodiff=false))",
        ):
            self.assertIn(expected, dashboard)
        self.assertIn("dt last/min/proposed=0.25/1e-12/-", compact)

    def test_root_authentication_reaches_live_status_and_dashboard(self):
        reporter = CampaignProgressReporter(
            "normal", self.reporter_checkpoint, io.StringIO()
        )
        reporter.publish(_event(
            ProgressEventKind.PRECISION_STAGE_STARTED,
            leaf_id="leaf-13",
            leaf_index=13,
            leaf_count=212,
            mechanism_id="horizon-admittance",
            precision_digits=80,
        ))
        root_authentication = {
            "central_determinant_re": "1e-60",
            "central_determinant_im": "-2e-61",
            "determinant_error": {
                "endpoint_disagreement_abs": "2e-62",
                "control_disagreement_abs": "1e-62",
                "equivalence_disagreement_abs": "5e-63",
                "precision_disagreement_abs": None,
                "safety_factor": "64",
                "numerical_error_abs": "1.28e-60",
                "error_model_id": (
                    "verified-endpoint-control-equivalence-absolute-error/v2"
                ),
            },
            "residual_upper_bound_abs": "2.299803902718557e-60",
            "derivative_authentication": {
                "derivative_re": "2.5",
                "derivative_im": "-0.25",
                "propagated_error_abs": "1e-12",
                "step_disagreement_abs": "2e-12",
                "lower_bound_abs": "2.512468905277154",
                "selected_step": "5e-7",
                "axis": "real",
            },
            "correction_upper_bound": "9.15357579817089e-61",
            "root_correction_tolerance": "2e-11",
            "accepted": True,
        }
        reporter.publish(_payload_event(
            ProgressEventKind.DERIVATIVE_CONTROL_COMPLETED,
            {"root_authentication": root_authentication},
            leaf_id="leaf-13",
            leaf_index=13,
            leaf_count=212,
            mechanism_id="horizon-admittance",
            precision_digits=80,
            phase="PRIMARY",
        ))

        live = reporter._live_execution_mapping()
        expected = {
            "central_determinant_re": "1e-60",
            "central_determinant_im": "-2e-61",
            "determinant_error_abs": "1.28e-60",
            "determinant_error_safety_factor": "64",
            "endpoint_disagreement_abs": "2e-62",
            "control_disagreement_abs": "1e-62",
            "equivalence_disagreement_abs": "5e-63",
            "precision_disagreement_abs": None,
            "residual_upper_bound_abs": "2.299803902718557e-60",
            "derivative_re": "2.5",
            "derivative_im": "-0.25",
            "derivative_propagated_error_abs": "1e-12",
            "derivative_step_disagreement_abs": "2e-12",
            "derivative_lower_bound_abs": "2.512468905277154",
            "derivative_selected_step": "5e-7",
            "derivative_axis": "real",
            "correction_upper_bound": "9.15357579817089e-61",
            "root_correction_tolerance": "2e-11",
            "root_authentication_accepted": True,
        }
        for name, value in expected.items():
            self.assertEqual(live[name], value, name)
        self.assertEqual(
            live["determinant_error_model"],
            "verified-endpoint-control-equivalence-absolute-error/v2",
        )

        status = json.loads(
            Path(f"{self.reporter_checkpoint}.status.json").read_text(
                encoding="utf-8"
            )
        )
        for name, value in expected.items():
            self.assertEqual(status["live_execution"][name], value, name)
        dashboard = "\n".join(reporter._current_execution_lines(compact=True))
        self.assertIn("ROOT AUTHENTICATION", dashboard)
        self.assertIn("9.15357579817089e-61 / 2e-11", dashboard)
        self.assertIn("accepted=True", dashboard)

    def test_staged_authentication_workflow_fields_reach_live_telemetry(self):
        reporter = CampaignProgressReporter(
            "normal", self.reporter_checkpoint, io.StringIO()
        )
        reporter.publish(_payload_event(
            ProgressEventKind.PRIMARY_STAGED_AUTHENTICATION_COMPLETED,
            {
                "phase": "PRIMARY",
                "root_phase": "PRIMARY",
                "authentication_mode": "STAGED_FULL_AUTHENTICATION",
                "authoritative": True,
                "full_authentication_escalated": False,
                "escalation_reason": None,
                "determinant_count_phase": 8,
                "residual_upper_bound_abs": "2.8e-14",
                "derivative_lower_bound_abs": "2",
                "required_derivative_lower_bound_abs": "1.4e-3",
                "correction_upper_bound": "1.4e-14",
                "root_correction_tolerance": "2e-11",
                "raw_step_disagreement_abs": "1e-9",
                "guarded_step_disagreement_abs": "6.4e-8",
                "propagated_derivative_error_abs": "1e-12",
            },
            leaf_id="leaf-13",
            leaf_index=13,
            leaf_count=212,
            mechanism_id="horizon-admittance",
            precision_digits=80,
            phase="PRIMARY",
        ))

        live = reporter._live_execution_mapping()
        expected = {
            "root_phase": "PRIMARY",
            "authentication_mode": "STAGED_FULL_AUTHENTICATION",
            "authoritative": True,
            "full_authentication_escalated": False,
            "escalation_reason": None,
            "phase_determinant_count": 8,
            "phase_residual_upper_bound_abs": "2.8e-14",
            "phase_derivative_lower_bound_abs": "2",
            "phase_required_derivative_lower_bound_abs": "1.4e-3",
            "phase_correction_upper_bound": "1.4e-14",
            "phase_root_correction_tolerance": "2e-11",
            "phase_raw_step_disagreement_abs": "1e-9",
            "phase_guarded_step_disagreement_abs": "6.4e-8",
            "phase_propagated_derivative_error_abs": "1e-12",
        }
        for name, value in expected.items():
            self.assertEqual(live[name], value, name)

    def test_diagnostic_role_escalation_reuse_and_count_reach_live_telemetry(
        self,
    ):
        reporter = CampaignProgressReporter(
            "normal", self.reporter_checkpoint, io.StringIO()
        )
        context = {
            "leaf_id": "leaf-13",
            "leaf_index": 13,
            "leaf_count": 212,
            "mechanism_id": "horizon-admittance",
            "precision_digits": 80,
            "phase": "RESOLUTION",
        }
        reporter.publish(_payload_event(
            ProgressEventKind.ROOT_PHASE_STARTED,
            {
                "solve_role": "DIAGNOSTIC_CONSISTENCY",
                "full_authentication_escalated": False,
                "escalation_reason": None,
                "authenticated_evidence_reused": False,
                "control_identity": "resolution-controls/v1",
            },
            **context,
        ))
        reporter.publish(_payload_event(
            ProgressEventKind.ROOT_PHASE_AUTHENTICATION_ESCALATED,
            {
                "solve_role": "DIAGNOSTIC_CONSISTENCY",
                "full_authentication_escalated": True,
                "escalation_reason": "DERIVATIVE_ESTIMATE_UNRESOLVED",
                "authenticated_evidence_reused": True,
                "determinant_count": 2,
            },
            **context,
        ))
        live = reporter._live_execution_mapping()
        self.assertEqual(live["solve_role"], "DIAGNOSTIC_CONSISTENCY")
        self.assertIs(live["full_authentication_escalated"], True)
        self.assertEqual(
            live["escalation_reason"], "DERIVATIVE_ESTIMATE_UNRESOLVED"
        )
        self.assertIs(live["authenticated_evidence_reused"], True)
        self.assertEqual(live["phase_determinant_count"], 2)

        reporter.publish(_payload_event(
            ProgressEventKind.ROOT_PHASE_COMPLETED,
            {
                "resulting_omega": {"real": "0.5", "imaginary": "-0.1"},
                "resulting_determinant_abs": "1e-30",
                "converged": True,
                "solve_role": "DIAGNOSTIC_CONSISTENCY",
                "full_authentication_escalated": True,
                "escalation_reason": "DERIVATIVE_ESTIMATE_UNRESOLVED",
                "authenticated_evidence_reused": True,
                "determinant_count": 5,
                "control_identity": "resolution-controls/v1",
                "branch_authenticated": True,
                "correction_upper_bound": "1e-14",
                "elapsed_seconds": 1.0,
            },
            **context,
        ))
        live = reporter._live_execution_mapping()
        self.assertEqual(live["phase_determinant_count"], 5)
        self.assertEqual(
            live["phase_control_identity"], "resolution-controls/v1"
        )
        self.assertIs(live["phase_branch_authenticated"], True)
        self.assertEqual(live["phase_correction_upper_bound"], "1e-14")

    def test_operational_terminal_events_cannot_leave_live_solver_running(self):
        for terminal_kind in (
            ProgressEventKind.LEAF_FAILED,
            ProgressEventKind.CAMPAIGN_FAILED,
            ProgressEventKind.REQUEST_FAILED,
        ):
            with self.subTest(kind=terminal_kind.value):
                reporter = CampaignProgressReporter(
                    "normal", self.reporter_checkpoint, io.StringIO()
                )
                reporter.publish(_event(
                    ProgressEventKind.PRECISION_STAGE_STARTED,
                    leaf_id="leaf-failed",
                    leaf_index=1,
                    leaf_count=212,
                    precision_digits=80,
                ))
                reporter.publish(_event(
                    ProgressEventKind.ROOT_PHASE_STARTED,
                    leaf_id="leaf-failed",
                    leaf_index=1,
                    leaf_count=212,
                    precision_digits=80,
                    phase="PRIMARY",
                ))
                reporter.publish(_payload_event(
                    terminal_kind,
                    {"error_type": "JuliaWorkerTimeoutError", "message": "timeout"},
                    leaf_id="leaf-failed",
                    leaf_index=1,
                    leaf_count=212,
                    precision_digits=80,
                    phase="PRIMARY",
                ))

                live = reporter._live_execution_mapping()
                self.assertEqual(live["state"], "FAILED")
                self.assertEqual(reporter._dashboard_state["root_status"], "FAILED")
                status = json.loads(
                    Path(f"{self.reporter_checkpoint}.status.json").read_text(
                        encoding="utf-8"
                    )
                )
                self.assertEqual(status["live_execution"]["state"], "FAILED")

    def test_interruption_is_not_failure_and_checkpoint_is_bound_to_its_leaf(self):
        reporter = CampaignProgressReporter(
            "normal", self.reporter_checkpoint, io.StringIO()
        )
        first = {"leaf_id": "leaf-1", "leaf_index": 1, "leaf_count": 3}
        second = {"leaf_id": "leaf-2", "leaf_index": 2, "leaf_count": 3}
        reporter.publish(_event(ProgressEventKind.LEAF_STARTED, **first))
        reporter.publish(_event(ProgressEventKind.CHECKPOINT_WRITTEN, **first))
        reporter.publish(_payload_event(
            ProgressEventKind.LEAF_COMPLETED,
            {"state": "PRODUCED"},
            **first,
        ))
        reporter.publish(_event(ProgressEventKind.LEAF_STARTED, **second))
        reporter.publish(_payload_event(
            ProgressEventKind.LEAF_INTERRUPTED,
            {"message": "operator interrupt"},
            **second,
        ))

        persistence = reporter._current_leaf_persistence()
        self.assertEqual(reporter._dashboard_state["leaf_status"], "INTERRUPTED")
        self.assertEqual(reporter._dashboard_state["execution_state"], "INTERRUPTED")
        self.assertEqual(len(reporter._failed_leaf_ids), 0)
        self.assertFalse(persistence["terminal_computed"])
        self.assertFalse(persistence["checkpoint_saved"])
        status = json.loads(
            Path(f"{self.reporter_checkpoint}.status.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(status["kind"], "leaf_interrupted")
        self.assertEqual(status["live_execution"]["state"], "INTERRUPTED")

    def test_interrupted_promoted_leaf_reports_resumable_partial_checkpoint(self):
        reporter = CampaignProgressReporter(
            "normal", self.reporter_checkpoint, io.StringIO()
        )
        context = {"leaf_id": "leaf-2", "leaf_index": 2, "leaf_count": 3}
        reporter.publish(_event(ProgressEventKind.LEAF_STARTED, **context))
        reporter.publish(_event(ProgressEventKind.CHECKPOINT_WRITTEN, **context))
        reporter.publish(_payload_event(
            ProgressEventKind.LEAF_INTERRUPTED,
            {"message": "operator interrupt"},
            **context,
        ))

        self.assertEqual(
            reporter._current_leaf_persistence(),
            {
                "leaf_id": "leaf-2",
                "terminal_computed": False,
                "checkpoint_saved": True,
                "receipt_published": False,
                "publication_failed": False,
            },
        )

    def test_normal_writes_atomic_live_status_for_second_process_inspection(self):
        with TemporaryDirectory() as directory:
            checkpoint = Path(directory) / "checkpoint.json"
            reporter = CampaignProgressReporter("normal", checkpoint, io.StringIO())
            reporter.publish(
                _event(
                    ProgressEventKind.LEAF_STARTED,
                    leaf_id="leaf-1",
                    leaf_index=1,
                    leaf_count=553,
                    role="primary",
                    mode={"s": -2, "ell": 2, "m": 2, "n": 0},
                    spin=0.95,
                    sampling_coordinate={"coordinate_id": "a_over_M", "value": 0.95},
                    mechanism_id="horizon-admittance",
                )
            )
            status_path = Path(f"{checkpoint}.status.json")
            status = json.loads(status_path.read_text(encoding="utf-8"))

        self.assertEqual(status["kind"], "leaf_started")
        self.assertEqual(status["context"]["leaf_index"], 1)
        self.assertEqual(status["context"]["leaf_count"], 553)
        self.assertEqual(status["context"]["mode"]["ell"], 2)

    def test_primary_seed_telemetry_aggregates_calls_iterations_fallbacks_and_time(self):
        reporter = CampaignProgressReporter(
            "normal", self.reporter_checkpoint, io.StringIO()
        )

        def publish_primary(
            *, readout_index, seed_kind, fallback_used, determinants, newtons, elapsed
        ):
            context = {
                "leaf_id": "leaf-1",
                "leaf_index": 1,
                "leaf_count": 212,
                "readout_index": readout_index,
                "phase": "PRIMARY",
                "seed_kind": seed_kind,
                "fallback_used": fallback_used,
                "seed_omega": {"real": 0.5, "imaginary": -0.1},
            }
            reporter.publish(_event(ProgressEventKind.ROOT_PHASE_STARTED, **context))
            reporter.publish(
                _payload_event(
                    ProgressEventKind.ROOT_SEED_SELECTED,
                    {
                        "requested_seed_kind": (
                            "EPSILON_CONTINUATION"
                            if fallback_used
                            else seed_kind
                        ),
                        "seed_kind": seed_kind,
                        "fallback_used": fallback_used,
                        "fallback_reason": (
                            "PREDICTOR_NEWTON_FAILED" if fallback_used else None
                        ),
                        "seed_omega": {"real": 0.5, "imaginary": -0.1},
                    },
                    **context,
                )
            )
            for index in range(determinants):
                reporter.publish(
                    _payload_event(
                        ProgressEventKind.DETERMINANT_STARTED,
                        {"purpose": f"det-{index}"},
                        **context,
                    )
                )
                reporter.publish(
                    _payload_event(
                        ProgressEventKind.DETERMINANT_COMPLETED,
                        {"determinant_abs": 1.0e-3 / (index + 1)},
                        **context,
                    )
                )
            for index in range(newtons):
                reporter.publish(
                    _event(
                        ProgressEventKind.NEWTON_ITERATION_STARTED,
                        **context,
                        newton_index=index + 1,
                    )
                )
            reporter.publish(
                _payload_event(
                    ProgressEventKind.ROOT_PHASE_COMPLETED,
                    {
                        "resulting_omega": {"real": 0.49, "imaginary": -0.09},
                        "resulting_determinant_abs": 1.0e-12,
                        "converged": True,
                        "elapsed_seconds": elapsed,
                    },
                    **context,
                )
            )

        publish_primary(
            readout_index=1,
            seed_kind="AUTHENTICATED_BACKGROUND",
            fallback_used=False,
            determinants=10,
            newtons=3,
            elapsed=12.0,
        )
        publish_primary(
            readout_index=2,
            seed_kind="EPSILON_CONTINUATION",
            fallback_used=False,
            determinants=6,
            newtons=2,
            elapsed=7.0,
        )
        publish_primary(
            readout_index=3,
            seed_kind="FALLBACK_BACKGROUND",
            fallback_used=True,
            determinants=14,
            newtons=5,
            elapsed=18.0,
        )
        reporter.publish(
            _event(
                ProgressEventKind.LEAF_COMPLETED,
                leaf_id="leaf-1",
                leaf_index=1,
                leaf_count=212,
            )
        )
        status = json.loads(
            Path(f"{self.reporter_checkpoint}.status.json").read_text(
                encoding="utf-8"
            )
        )

        summary = status["momentum_summary"]
        self.assertEqual(summary["primary_solve_count"], 3)
        self.assertEqual(summary["epsilon_continuation_fallback_rate"], 0.5)
        self.assertEqual(
            summary["by_seed_kind"]["EPSILON_CONTINUATION"],
            {
                "solve_count": 1,
                "fallback_count": 0,
                "total_newton_iterations": 2,
                "average_newton_iterations": 2.0,
                "total_determinant_calls": 6,
                "average_determinant_calls": 6.0,
                "total_elapsed_seconds": 7.0,
                "mean_solve_seconds": 7.0,
            },
        )
        self.assertEqual(
            summary["observed_epsilon_determinant_call_delta_vs_background_mean"],
            4.0,
        )
        root_solve_path = (
            Path(f"{self.reporter_checkpoint}.progress") / "root-solves.jsonl"
        )
        root_solves = [
            json.loads(line)
            for line in root_solve_path.read_text(encoding="utf-8").splitlines()
        ]
        self.assertEqual(len(root_solves), 3)
        self.assertEqual(
            root_solves[1]["root_solve"],
            {
                "requested_seed_kind": "EPSILON_CONTINUATION",
                "seed_kind": "EPSILON_CONTINUATION",
                "seed_omega": {"real": 0.5, "imaginary": -0.1},
                "fallback_used": False,
                "fallback_reason": None,
                "fallback_error_type": None,
                "initial_determinant_abs": 0.001,
                "predictor_initial_determinant_abs": None,
                "newton_iterations": 2,
                "determinant_calls": 6,
                "resulting_omega": {"real": 0.49, "imaginary": -0.09},
                "resulting_determinant_abs": 1.0e-12,
                "converged": True,
                "elapsed_seconds": 7.0,
            },
        )

    def test_root_telemetry_separates_precision_and_component_pass(self):
        reporter = CampaignProgressReporter(
            "normal", self.reporter_checkpoint, io.StringIO()
        )

        def publish_root(*, digits, component_pass):
            context = {
                "leaf_id": "leaf-1",
                "leaf_index": 1,
                "leaf_count": 212,
                "precision_digits": digits,
                "component_pass": component_pass,
                "readout_index": 1,
                "phase": "PRIMARY",
            }
            reporter.publish(_event(ProgressEventKind.ROOT_PHASE_STARTED, **context))
            reporter.publish(
                _payload_event(
                    ProgressEventKind.ROOT_SEED_SELECTED,
                    {
                        "requested_seed_kind": "AUTHENTICATED_BACKGROUND",
                        "seed_kind": "AUTHENTICATED_BACKGROUND",
                        "seed_omega": {"real": 0.5, "imaginary": -0.1},
                        "fallback_used": False,
                        "fallback_reason": None,
                    },
                    **context,
                )
            )
            reporter.publish(
                _payload_event(
                    ProgressEventKind.DETERMINANT_STARTED,
                    {"purpose": "initial"},
                    **context,
                )
            )
            reporter.publish(
                _payload_event(
                    ProgressEventKind.DETERMINANT_COMPLETED,
                    {"determinant_abs": 1.0e-3},
                    **context,
                )
            )
            reporter.publish(
                _payload_event(
                    ProgressEventKind.ROOT_PHASE_COMPLETED,
                    {
                        "resulting_omega": {"real": 0.49, "imaginary": -0.09},
                        "resulting_determinant_abs": 1.0e-12,
                        "converged": True,
                        "elapsed_seconds": 1.0,
                    },
                    **context,
                )
            )

        publish_root(digits=64, component_pass="primary")
        publish_root(digits=80, component_pass="primary")
        publish_root(digits=80, component_pass="self-refinement")

        root_solve_path = (
            Path(f"{self.reporter_checkpoint}.progress") / "root-solves.jsonl"
        )
        root_solves = [
            json.loads(line)
            for line in root_solve_path.read_text(encoding="utf-8").splitlines()
        ]
        self.assertEqual(len(root_solves), 3)
        self.assertEqual(
            [record["root_solve"]["determinant_calls"] for record in root_solves],
            [1, 1, 1],
        )
        self.assertEqual(
            root_solves[-1]["momentum_summary"]["primary_solve_count"], 3
        )

    def test_normal_console_dashboard_is_completion_driven(self):
        class ConsoleStream(io.StringIO):
            def isatty(self):
                return True

        stream = ConsoleStream()
        reporter = self._console_reporter(stream)
        reporter.publish(
            _event(
                ProgressEventKind.CAMPAIGN_STARTED,
                leaf_count=553,
            )
        )
        initial_output = stream.getvalue()
        shared_context = {
            "leaf_id": "leaf-1",
            "leaf_index": 1,
            "leaf_count": 553,
            "role": "primary",
            "mechanism_id": "horizon-admittance",
            "spin": 0.95,
            "precision_digits": 64,
            "phase": "PRIMARY",
        }
        reporter.publish(
            _payload_event(
                ProgressEventKind.DETERMINANT_COMPLETED,
                {"determinant_abs": 3.2e-8},
                **shared_context,
            )
        )
        reporter.publish(
            _event(
                ProgressEventKind.SUBOPERATION_COMPLETED,
                **shared_context,
                suboperation="Xup",
            )
        )
        self.assertEqual(stream.getvalue(), initial_output)

        reporter.publish(
            _payload_event(
                ProgressEventKind.LEAF_COMPLETED,
                {"state": "PRODUCED"},
                **shared_context,
            )
        )

        output = stream.getvalue()
        self.assertIn("M02 | DASHBOARD", output)
        self.assertIn("LEAF", output)
        self.assertIn("MODE", output)
        # Human ordinal (1/553) replaces the SHA-form leaf id.
        row_starts = [
            line for line in output.splitlines() if line and line[0].isdigit()
        ]
        self.assertEqual(1, len(row_starts))
        self.assertTrue(row_starts[0].startswith("1/553"))
        self.assertIn("horizon", output)
        self.assertNotIn("horizon-~", output)
        self.assertNotIn("PRODUC~", output)
        self.assertNotIn("\x1b[", output)

    def test_published_receipts_increase_the_visible_cache_total(self):
        class ConsoleStream(io.StringIO):
            def isatty(self):
                return True

        stream = ConsoleStream()
        reporter = self._console_reporter(stream)
        reporter.publish(
            _payload_event(
                ProgressEventKind.SOLVED_LEAF_CACHE_SCANNED,
                {
                    "compatible_count": 10,
                    "stored_count": 11,
                    "reusing_count": 10,
                },
                leaf_count=212,
            )
        )
        reporter.publish(
            _payload_event(
                ProgressEventKind.LEAF_CACHE_PUBLISHED,
                {"store_path": "solved-leaves-v1"},
                leaf_id="leaf-1",
                leaf_index=1,
                leaf_count=212,
            )
        )
        reporter.publish(
            _payload_event(
                ProgressEventKind.LEAF_COMPLETED,
                {"state": "PRODUCED"},
                leaf_id="leaf-2",
                leaf_index=2,
                leaf_count=212,
            )
        )

        latest_panel = stream.getvalue()
        # Cache stats surface in the live counts suffix.
        self.assertIn("cache:12", latest_panel)
        self.assertNotIn("\x1b[", latest_panel)

    def test_live_dashboard_renders_latest_completed_scientific_result(self):
        class ConsoleStream(io.StringIO):
            def isatty(self):
                return True

        accepted_leaf = "leaf-accepted"
        stream = ConsoleStream()
        reporter = self._console_reporter(stream)
        reporter._campaign_report_model = CampaignReportModel(
            leaf_rows=(
                {
                    "leaf_id": accepted_leaf,
                    "terminal_state": "PRODUCED",
                    "precision_digits": 64,
                    "mode": "220",
                    "spin_or_Mkappa": "0.999",
                    "mechanism": "horizon-admittance",
                    "convergence_basis": "ORDER_RESOLVED",
                    "response_real": 1.25,
                    "response_imaginary": -0.5,
                    "response_magnitude": 1.346291201783626,
                    "local_disk_radius": 2.0e-8,
                    "relative_disk_radius": 1.4855627054164149e-8,
                    "relative_disk_state": "FINITE",
                    "baseline_omega_real": 0.9558544196294082,
                    "baseline_omega_imaginary": -0.010530589036141928,
                    "baseline_determinant_residual": 2.0e-13,
                    "baseline_newton_correction": 3.0e-14,
                    "signed_root_crosscheck_real": 1.25,
                    "signed_root_crosscheck_imaginary": -0.5,
                    "signed_root_crosscheck_magnitude": 1.346291201783626,
                    "signed_root_error": 2.0e-9,
                    "truncation_error": 3.0e-9,
                    "resolution_error": 4.0e-9,
                    "seed_path_error": 5.0e-9,
                    "axis_error": 6.0e-9,
                    "amplitude_error": 7.0e-9,
                },
            ),
            error_channel_rows=(),
            projective_rows=(
                {
                    "row_id": "projective-row-1",
                    "present_component_ids": json.dumps([accepted_leaf]),
                    "reducer_state": "COMPLETE",
                    "scientific_state": "BOUNDED",
                    "projective_outcome": "SEPARATED",
                    "nominal_angle": 0.21,
                    "angle_lower_bound": 0.20,
                    "angle_upper_bound": 0.22,
                    "separation_threshold": 0.15,
                    "equivalence_threshold": 0.05,
                    "reason": "bounded interval exceeds separation threshold",
                },
            ),
            checkpoint_source_receipt="sha256:" + "a" * 64,
        )

        reporter.publish(
            _payload_event(
                ProgressEventKind.LEAF_COMPLETED,
                {"state": "PRODUCED"},
                leaf_id=accepted_leaf,
                leaf_index=12,
                leaf_count=212,
                precision_digits=64,
            )
        )

        latest_panel = stream.getvalue()
        self.assertIn("M02 | DASHBOARD", latest_panel)
        # SHA-form leaf id belongs in logs, not the human dashboard row.
        self.assertNotIn("leaf-ac~", latest_panel)
        # Mechanism short name replaces the mutilated form.
        self.assertIn("horizon", latest_panel)
        self.assertNotIn("horizon-~", latest_panel)
        # Full evidence and state words replace ORDER_R~/PRODUC~ truncations.
        self.assertIn("ORDER_RESOLVED", latest_panel)
        self.assertIn("1.346", latest_panel)
        self.assertIn("1.486e-08", latest_panel)
        self.assertNotIn("PRODUC~", latest_panel)

        status = json.loads(
            Path(f"{self.reporter_checkpoint}.status.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(status["scientific"]["LatestResult"], accepted_leaf)
        self.assertEqual(status["scientific"]["ResultPrecision"], 64)
        self.assertEqual(
            status["scientific"]["ResultPrecisionTier"], "binary64"
        )
        self.assertEqual(
            status["scientific"]["ResultPrecisionDecimalDigitsNominal"], 15.95
        )
        self.assertEqual(
            status["scientific"]["ResultPrecisionLabel"],
            "binary64 (~15.95 dec)",
        )
        self.assertEqual(status["scientific"]["ResponseRe"], 1.25)
        self.assertEqual(
            status["scientific"]["ProjectiveOutcome"], "SEPARATED"
        )

    def test_live_status_exposes_active_precision_tier_without_rewriting_context(self):
        reporter = CampaignProgressReporter(
            "quiet", self.reporter_checkpoint, io.StringIO()
        )
        reporter.publish(
            _event(
                ProgressEventKind.LEAF_STARTED,
                leaf_id="leaf-1",
                precision_digits=64,
            )
        )

        status = json.loads(
            Path(f"{self.reporter_checkpoint}.status.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(status["context"]["precision_digits"], 64)
        self.assertEqual(
            status["precision"],
            {
                "arithmetic": "IEEE-754 binary64",
                "legacy_tier_value": 64,
                "nominal_decimal_digits": 15.95,
                "precision_tier": "binary64",
                "presentation_label": "binary64 (~15.95 dec)",
            },
        )

    def test_live_status_throttles_detail_events_but_forces_leaf_visibility(self):
        reporter = CampaignProgressReporter(
            "normal", self.reporter_checkpoint, io.StringIO()
        )
        with patch.object(reporter, "_write_status") as write_status:
            reporter.publish(
                _event(
                    ProgressEventKind.LEAF_STARTED,
                    leaf_id="leaf-1",
                    leaf_index=1,
                    leaf_count=553,
                )
            )
            reporter.publish(
                _event(
                    ProgressEventKind.DETERMINANT_STARTED,
                    leaf_id="leaf-1",
                    phase="PRIMARY",
                )
            )
            reporter.publish(
                _payload_event(
                    ProgressEventKind.DETERMINANT_COMPLETED,
                    {"determinant_abs": 1.0e-12},
                    leaf_id="leaf-1",
                    phase="PRIMARY",
                )
            )

        self.assertEqual(write_status.call_count, 1)

    def test_quiet_renders_only_leaf_and_terminal_events(self):
        stream = io.StringIO()
        reporter = CampaignProgressReporter("quiet", self.reporter_checkpoint, stream)
        reporter.publish(_event(ProgressEventKind.CAMPAIGN_STARTED))
        reporter.publish(
            _event(
                ProgressEventKind.LEAF_STARTED,
                leaf_id="leaf-1",
                precision_digits=64,
            )
        )
        reporter.publish(
            _event(
                ProgressEventKind.ROOT_PHASE_STARTED,
                leaf_id="leaf-1",
                phase="PRIMARY",
            )
        )
        reporter.publish(
            _event(
                ProgressEventKind.LEAF_COMPLETED,
                leaf_id="leaf-1",
                precision_digits=64,
            )
        )

        output = stream.getvalue()
        self.assertIn("leaf_started", output)
        self.assertIn("leaf_completed", output)
        self.assertIn("precision=binary64 (~15.95 dec)", output)
        self.assertNotIn("precision=64", output)
        self.assertNotIn("campaign_started", output)
        self.assertNotIn("root_phase_started", output)

    def test_normal_console_redraws_only_on_campaign_or_terminal_events(self):
        class ConsoleStream(io.StringIO):
            def isatty(self):
                return True

        stream = ConsoleStream()
        history = "[bootstrap] solver plan succeeded\nPS> .\\m02.ps1\n"
        stream.write(history)
        reporter = self._console_reporter(stream)
        reporter.publish(_event(ProgressEventKind.CAMPAIGN_STARTED, leaf_count=1))
        after_start = stream.getvalue()
        reporter.publish(
            _event(
                ProgressEventKind.LEAF_STARTED,
                leaf_id="leaf-1",
                leaf_index=1,
                leaf_count=1,
                role="primary",
            )
        )
        self.assertEqual(stream.getvalue(), after_start)
        reporter.publish(
            _payload_event(
                ProgressEventKind.LEAF_COMPLETED,
                {"state": "PRODUCED"},
                leaf_id="leaf-1",
                leaf_index=1,
                leaf_count=1,
                role="primary",
            )
        )

        output = stream.getvalue()
        self.assertTrue(output.startswith(history + "=" * 108))
        self.assertNotIn("\x1b[", output)
        row_starts = [
            line for line in output.splitlines() if line and line[0].isdigit()
        ]
        self.assertEqual(1, len(row_starts))
        self.assertTrue(row_starts[0].startswith("1/1"))
        self.assertIn("PRODUCED", output)
        self.assertNotIn("PRODUC~", output)

    def test_normal_console_compacts_without_active_solver_noise(self):
        class ConsoleStream(io.StringIO):
            def isatty(self):
                return True

        stream = ConsoleStream()
        history = "[bootstrap] solver plan succeeded\nPS> .\\m02.ps1\n"
        stream.write(history)
        reporter = self._console_reporter(stream)
        assert reporter._clean_tail is not None
        reporter._clean_tail.width = 80
        with patch.object(reporter, "_terminal_dimensions", return_value=(80, 24)):
            reporter.publish(
                _event(ProgressEventKind.CAMPAIGN_STARTED, leaf_count=553)
            )
            after_start = stream.getvalue()
            reporter.publish(
                _payload_event(
                    ProgressEventKind.DETERMINANT_COMPLETED,
                    {
                        "determinant_abs": 3.2e-8,
                        "best_determinant_abs": 2.1e-9,
                    },
                    leaf_id="leaf-1",
                    leaf_index=1,
                    leaf_count=553,
                    suboperation="Xup integration",
                )
            )
            self.assertEqual(stream.getvalue(), after_start)
            reporter.publish(
                _payload_event(
                    ProgressEventKind.LEAF_COMPLETED,
                    {"state": "UNRESOLVED"},
                    leaf_id="leaf-1",
                    leaf_index=1,
                    leaf_count=553,
                    mechanism_id="horizon-admittance",
                    spin=0.95,
                    precision_digits=64,
                )
            )

        output = stream.getvalue()
        # New banner uses the actual terminal width (80), no clip needed.
        self.assertTrue(output.startswith(history + "=" * 80))
        self.assertNotIn("\x1b[", output)
        self.assertIn("M02 | DASHBOARD", output)
        # Ordinal replaces the SHA leaf id in the row.
        self.assertIn("1/553", output)
        self.assertIn("UNRESOLVED", output)
        self.assertNotIn("UNRESO~", output)

    def test_partial_campaign_dashboard_keeps_outcome_counts_neutral(self):
        class ConsoleStream(io.StringIO):
            def isatty(self):
                return True

        stream = ConsoleStream()
        reporter = self._console_reporter(stream)
        leaf_context = {"leaf_id": "leaf-1", "leaf_index": 1, "leaf_count": 553}
        reporter.publish(_event(ProgressEventKind.LEAF_STARTED, **leaf_context))
        reporter.publish(
            _payload_event(
                ProgressEventKind.PRECISION_STAGE_COMPLETED,
                {
                    "numerical_state": "NOT_CONVERGED",
                    "leaf_state": "MISSING_PRECISION",
                },
                **leaf_context,
            )
        )
        reporter.publish(
            _payload_event(
                ProgressEventKind.CAMPAIGN_COMPLETED,
                {"state": "PARTIAL"},
            )
        )

        latest_panel = stream.getvalue()
        # New human-readable outcome-counts phrasing.
        self.assertIn("DONE 0", latest_panel)
        self.assertIn("REJECTED 0", latest_panel)
        self.assertIn("UNRESOLVED 0", latest_panel)
        self.assertIn("FAILED 0", latest_panel)

    def test_completed_leaf_status_retains_rolling_eta_telemetry(self):
        class ConsoleStream(io.StringIO):
            def isatty(self):
                return True

        stream = ConsoleStream()
        reporter = self._console_reporter(stream)
        reporter.publish(
            replace(
                _event(
                    ProgressEventKind.LEAF_STARTED,
                    leaf_id="leaf-1",
                    leaf_index=1,
                    leaf_count=553,
                ),
                monotonic_seconds=100.0,
            )
        )
        reporter.publish(
            replace(
                _payload_event(
                    ProgressEventKind.LEAF_COMPLETED,
                    {"state": "PRODUCED"},
                    leaf_id="leaf-1",
                    leaf_index=1,
                    leaf_count=553,
                ),
                monotonic_seconds=892.0,
            )
        )
        reporter.publish(
            replace(
                _event(
                    ProgressEventKind.LEAF_STARTED,
                    leaf_id="leaf-2",
                    leaf_index=2,
                    leaf_count=553,
                ),
                monotonic_seconds=900.0,
            )
        )

        status = json.loads(
            Path(f"{self.reporter_checkpoint}.status.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(status["leaf_timing_sample_size"], 1)
        self.assertEqual(status["average_leaf_seconds"], 792.0)
        self.assertEqual(status["median_leaf_seconds"], 792.0)
        self.assertGreater(status["eta_seconds"], 0.0)
        self.assertIn("estimated_finish", status)
        self.assertNotIn("ETA", stream.getvalue())

    def test_timing_window_excludes_old_and_reused_leaves(self):
        reporter = CampaignProgressReporter(
            "normal", self.reporter_checkpoint, io.StringIO()
        )
        current = 0.0
        for leaf_index in range(1, 12):
            reporter.publish(
                replace(
                    _event(
                        ProgressEventKind.LEAF_STARTED,
                        leaf_id=f"leaf-{leaf_index}",
                        leaf_index=leaf_index,
                        leaf_count=20,
                    ),
                    monotonic_seconds=current,
                )
            )
            current += 100.0 if leaf_index == 1 else 10.0
            reporter.publish(
                replace(
                    _payload_event(
                        ProgressEventKind.LEAF_COMPLETED,
                        {"state": "PRODUCED"},
                        leaf_id=f"leaf-{leaf_index}",
                        leaf_index=leaf_index,
                        leaf_count=20,
                    ),
                    monotonic_seconds=current,
                )
            )
        reporter.publish(
            replace(
                _payload_event(
                    ProgressEventKind.LEAF_REUSED,
                    {"state": "PRODUCED"},
                    leaf_id="leaf-12",
                    leaf_index=12,
                    leaf_count=20,
                ),
                monotonic_seconds=current + 1.0,
            )
        )

        status = json.loads(
            Path(f"{self.reporter_checkpoint}.status.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(status["leaf_timing_sample_size"], 10)
        self.assertEqual(status["average_leaf_seconds"], 10.0)
        self.assertEqual(status["median_leaf_seconds"], 10.0)

    def test_normal_console_reports_terminal_outcome_counts(self):
        class ConsoleStream(io.StringIO):
            def isatty(self):
                return True

        stream = ConsoleStream()
        reporter = self._console_reporter(stream)
        leaf_context = {
            "leaf_id": "leaf-1",
            "leaf_index": 1,
            "leaf_count": 553,
            "precision_digits": 64,
            "phase": "PRIMARY",
        }
        reporter.publish(_event(ProgressEventKind.LEAF_STARTED, **leaf_context))
        reporter.publish(_event(ProgressEventKind.CHECKPOINT_WRITTEN, **leaf_context))
        reporter.publish(
            _payload_event(
                ProgressEventKind.LEAF_COMPLETED,
                {"state": "PRODUCED", "stage_count": 1},
                **leaf_context,
            )
        )

        latest_panel = stream.getvalue()
        self.assertIn("1/553", latest_panel)
        self.assertIn("PRODUCED", latest_panel)
        self.assertNotIn("PRODUC~", latest_panel)
        self.assertNotIn("\x1b[", latest_panel)

        reporter.publish(
            _payload_event(
                ProgressEventKind.LEAF_REUSED,
                {"state": "UNRESOLVED", "stage_count": 1},
                leaf_id="leaf-2",
                leaf_index=2,
                leaf_count=553,
            )
        )
        reused_panel = stream.getvalue()
        self.assertIn("2/553", reused_panel)
        self.assertIn("UNRESOLVED", reused_panel)
        self.assertNotIn("UNRESO~", reused_panel)
        self.assertIn("done:2", reused_panel)
        self.assertIn("unres:1", reused_panel)

        reporter.publish(
            _payload_event(
                ProgressEventKind.LEAF_FAILED,
                {"error_type": "RuntimeError", "message": "backend stopped"},
                leaf_id="leaf-3",
                leaf_index=3,
                leaf_count=553,
            )
        )
        failed_panel = stream.getvalue()
        self.assertIn("3/553", failed_panel)
        self.assertIn("FAILED", failed_panel)
        self.assertIn("done:3", failed_panel)
        self.assertIn("fail:1", failed_panel)

    def test_trace_appends_session_marker_and_flushes_each_leaf_jsonl_event(self):
        with TemporaryDirectory() as directory:
            checkpoint = Path(directory) / "checkpoint.json"
            event = _event(
                ProgressEventKind.LEAF_STARTED, leaf_id="leaf-1", leaf_index=1
            )
            reporter = CampaignProgressReporter("trace", checkpoint, io.StringIO())
            reporter.publish(event)
            trace_path = Path(f"{checkpoint}.progress") / "leaf-000001.jsonl"
            first_records = [
                json.loads(line) for line in trace_path.read_text(encoding="utf-8").splitlines()
            ]

            second_reporter = CampaignProgressReporter("trace", checkpoint, io.StringIO())
            second_reporter.publish(event)
            records = [
                json.loads(line) for line in trace_path.read_text(encoding="utf-8").splitlines()
            ]

        self.assertEqual(len(first_records), 2)
        self.assertEqual(len(records), 4)
        self.assertEqual([record["kind"] for record in records[::2]], [
            "session_started", "session_started"
        ])
        event_record = records[1]
        self.assertEqual(event_record["schema"], PROGRESS_SCHEMA)
        self.assertEqual(event_record["kind"], "leaf_started")
        self.assertIn("session", event_record)
        self.assertEqual(event_record["sequence"], 2)
        self.assertIn("timestamp_utc", event_record)
        self.assertIn("elapsed_seconds", event_record)
        self.assertEqual(event_record["context"]["leaf_id"], "leaf-1")
        self.assertEqual(event_record["payload"]["phase"], "PRIMARY")

    def test_trace_flushes_the_writer_for_each_record(self):
        class Writer:
            def __init__(self):
                self.flush_count = 0

            def write(self, value):
                return len(value)

            def flush(self):
                self.flush_count += 1

            def __enter__(self):
                return self

            def __exit__(self, *unused):
                return False

        writer = Writer()
        event = _event(ProgressEventKind.LEAF_STARTED, leaf_id="leaf-1", leaf_index=1)
        with TemporaryDirectory() as directory, patch.object(Path, "open", return_value=writer):
            reporter = CampaignProgressReporter(
                "trace", Path(directory) / "checkpoint.json", io.StringIO()
            )
            reporter.publish(event)

        self.assertEqual(writer.flush_count, 2)

    def test_trace_skips_non_leaf_events_without_diagnostics_then_starts_leaf_file(self):
        with TemporaryDirectory() as directory:
            checkpoint = Path(directory) / "checkpoint.json"
            reporter = CampaignProgressReporter("trace", checkpoint, io.StringIO())
            reporter.publish(_event(ProgressEventKind.CAMPAIGN_STARTED))
            reporter.publish(_event(ProgressEventKind.CAMPAIGN_COMPLETED))

            trace_directory = Path(f"{checkpoint}.progress")
            self.assertFalse(trace_directory.exists())
            self.assertEqual(reporter.diagnostics, [])

            reporter.publish(
                _event(ProgressEventKind.LEAF_STARTED, leaf_id="leaf-1", leaf_index=1)
            )
            records = [
                json.loads(line)
                for line in (trace_directory / "leaf-000001.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()
            ]

        self.assertEqual([record["kind"] for record in records], [
            "session_started", "leaf_started"
        ])
        self.assertEqual(reporter.diagnostics, [])

    def test_trace_sequences_remain_monotonic_across_leaf_files(self):
        with TemporaryDirectory() as directory:
            checkpoint = Path(directory) / "checkpoint.json"
            reporter = CampaignProgressReporter("trace", checkpoint, io.StringIO())
            reporter.publish(
                _event(ProgressEventKind.LEAF_STARTED, leaf_id="leaf-1", leaf_index=1)
            )
            reporter.publish(
                _event(ProgressEventKind.LEAF_STARTED, leaf_id="leaf-2", leaf_index=2)
            )
            trace_directory = Path(f"{checkpoint}.progress")
            sequences = []
            for leaf_index in (1, 2):
                records = [
                    json.loads(line)
                    for line in (trace_directory / f"leaf-{leaf_index:06d}.jsonl")
                    .read_text(encoding="utf-8")
                    .splitlines()
                ]
                sequences.extend(record["sequence"] for record in records)

        self.assertEqual(sequences, [1, 2, 3, 4])

    def test_trace_human_identity_includes_suboperation_and_determinant_purpose(self):
        with TemporaryDirectory() as directory:
            stream = io.StringIO()
            reporter = CampaignProgressReporter(
                "trace", Path(directory) / "checkpoint.json", stream
            )
            reporter.publish(
                _event(
                    ProgressEventKind.SUBOPERATION_STARTED,
                    leaf_id="leaf-1",
                    leaf_index=1,
                    suboperation="angular",
                    determinant_purpose="candidate",
                )
            )

        output = stream.getvalue()
        self.assertIn("suboperation=angular", output)
        self.assertIn("determinant_purpose=candidate", output)

    def test_progress_event_kinds_include_stable_determinant_and_julia_lifecycle_names(self):
        self.assertEqual(ProgressEventKind.DETERMINANT_STARTED.value, "determinant_started")
        self.assertEqual(ProgressEventKind.DETERMINANT_COMPLETED.value, "determinant_completed")
        self.assertEqual(ProgressEventKind.REQUEST_STARTED.value, "request_started")
        self.assertEqual(ProgressEventKind.REQUEST_VALIDATED.value, "request_validated")
        self.assertEqual(ProgressEventKind.REQUEST_COMPLETED.value, "request_completed")
        self.assertEqual(ProgressEventKind.REQUEST_FAILED.value, "request_failed")
        for name in (
            "PRIMARY_STAGED_AUTHENTICATION_STARTED",
            "PRIMARY_STAGED_DERIVATIVE_ACCEPTED",
            "PRIMARY_STAGED_DERIVATIVE_REJECTED",
            "PRIMARY_STAGED_AUTHENTICATION_COMPLETED",
            "PRIMARY_FULL_AUTHENTICATION_ESCALATED",
            "PRIMARY_FULL_AUTHENTICATION_COMPLETED",
            "DIAGNOSTIC_CONSISTENCY_STARTED",
            "DIAGNOSTIC_CONSISTENCY_COMPLETED",
            "DIAGNOSTIC_FULL_AUTHENTICATION_ESCALATED",
            "DIAGNOSTIC_FULL_AUTHENTICATION_COMPLETED",
        ):
            event = getattr(ProgressEventKind, name)
            self.assertEqual(event.value, name.lower())
        self.assertEqual(ProgressEventKind.LEAF_INTERRUPTED.value, "leaf_interrupted")
        self.assertEqual(
            ProgressEventKind.CAMPAIGN_INTERRUPTED.value, "campaign_interrupted"
        )
        self.assertEqual(
            ProgressEventKind.REQUEST_INTERRUPTED.value, "request_interrupted"
        )

    def test_every_worker_emitted_event_is_registered_in_python(self):
        """Catches a Julia event name the Python registry cannot parse.

        The worker and the registry are edited in different languages by
        different changes, so a new emission can reach a campaign that has no
        name for it. Reading the emissions out of the worker source keeps the
        comparison honest rather than restating a hand-maintained list.
        """

        import re

        worker = (
            Path(__file__).resolve().parents[1]
            / "src/windows_solver/data/julia/m02_worker.jl"
        ).read_text(encoding="utf-8")
        emitted = set(
            re.findall(r'progress_emit\(\s*"([a-z_0-9]+)"', worker)
        )
        self.assertTrue(emitted, "worker must emit progress events")
        registered = {kind.value for kind in ProgressEventKind}
        self.assertEqual(sorted(emitted - registered), [])

    def test_terminal_control_failures_share_normal_mode_visibility(self):
        """Catches a terminal control failure that is silent outside trace.

        A coordinate stall ends a leg exactly as a resource limit does. If one
        is surfaced at normal verbosity and the other is not, the operator sees
        a run stop for no stated reason -- which is the condition the stall
        watchdog was added to eliminate.
        """

        from windows_solver import progress_output

        for peer_set in (
            progress_output._NORMAL_FALLBACK_KINDS,
            progress_output._FORCED_STATUS_KINDS,
            progress_output._DASHBOARD_FORCED_KINDS,
        ):
            if ProgressEventKind.ODE_RESOURCE_LIMIT in peer_set:
                self.assertIn(
                    ProgressEventKind.COORDINATE_INVERSION_STALLED, peer_set
                )

    def test_reporter_contains_stream_and_trace_failures(self):
        class BrokenStream:
            def write(self, value):
                raise OSError("broken progress stream")

            def flush(self):
                raise OSError("broken progress stream")

        event = _event(ProgressEventKind.LEAF_STARTED, leaf_id="leaf-1", leaf_index=1)
        reporter = CampaignProgressReporter(
            "trace", self.reporter_checkpoint, BrokenStream()
        )
        reporter.publish(event)

        self.assertEqual(len(reporter.diagnostics), 1)
        self.assertIn("OSError", reporter.diagnostics[0])

    def test_reporter_contains_trace_io_failure(self):
        event = _event(ProgressEventKind.LEAF_STARTED, leaf_id="leaf-1", leaf_index=1)
        stream = io.StringIO()
        with TemporaryDirectory() as directory:
            with patch.object(Path, "open", side_effect=OSError("trace unavailable")):
                reporter = CampaignProgressReporter(
                    "trace", Path(directory) / "checkpoint.json", stream
                )
                reporter.publish(event)

        self.assertEqual(len(reporter.diagnostics), 1)
        self.assertIn("trace unavailable", reporter.diagnostics[0])


if __name__ == "__main__":
    unittest.main()
