from __future__ import annotations

import csv
from contextlib import nullcontext
import hashlib
import io
import json
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from windows_solver.campaign_reports import (
    CampaignReportModel,
    _derive_projective_triage_projection,
    _root_correction_tolerance_for_precision,
    refresh_campaign_reports,
)
from windows_solver.contracts import canonical_json_bytes
from windows_solver.progress import ProgressContext, ProgressEvent, ProgressEventKind
from windows_solver.progress_output import CampaignProgressReporter
from windows_solver.response_batches import (
    CampaignLeafRecord,
    CampaignStageRecord,
    PrecisionCapabilities,
    StageOutcome,
    _checkpoint_mapping,
    build_campaign_plan,
    build_campaign_selection,
    explicit_stage_signed_error_channels,
)
from windows_solver.response_engine import (
    ComponentResult,
    ComponentStatus,
    DiagnosticRootReadout,
    ERROR_CHANNELS,
    LadderLevel,
    NumericalPolicy,
    RootReadout,
    VettedNativeDeterminantKernel,
)


class CampaignReportTests(unittest.TestCase):
    def _plan(self):
        return build_campaign_plan(
            policy=NumericalPolicy(),
            backend_identity=VettedNativeDeterminantKernel.identity,
            precision_capabilities=PrecisionCapabilities((64,)),
        )

    @staticmethod
    def _produced_record(plan, leaf):
        job = leaf.job
        response = complex(1.25, -0.5)
        diagnostic_deltas = {
            "truncation": complex(3.0e-12, -1.0e-12),
            "resolution": complex(-2.0e-12, 2.0e-12),
            "seed-path": complex(1.0e-12, 3.0e-12),
        }

        def signed_readout(amplitude):
            return RootReadout(
                omega=job.root.omega + response * amplitude,
                determinant_residual_abs=1.0e-12,
                determinant_derivative_abs=2.0,
                converged=True,
                root_reference_id=job.root.root_reference_id,
                branch_id=job.root.branch_id,
                equation_id=job.equation_id,
                truncation_radius=abs(diagnostic_deltas["truncation"]),
                resolution_radius=abs(diagnostic_deltas["resolution"]),
                seed_path_radius=abs(diagnostic_deltas["seed-path"]),
                diagnostic_readouts={
                    family: DiagnosticRootReadout(
                        omega_delta_from_primary=delta,
                        determinant_residual_abs=1.0e-13,
                        determinant_derivative_abs=1.0,
                        converged=True,
                    )
                    for family, delta in diagnostic_deltas.items()
                },
                source_root_mapping=job.source_root_mapping,
            )

        levels = tuple(
            LadderLevel(
                epsilon=epsilon,
                real_plus=signed_readout(complex(epsilon, 0.0)),
                real_minus=signed_readout(complex(-epsilon, 0.0)),
                imaginary_plus=signed_readout(complex(0.0, epsilon)),
                imaginary_minus=signed_readout(complex(0.0, -epsilon)),
            )
            for epsilon in job.policy.epsilons[-4:]
        )
        result = ComponentResult(
            job_id=job.job_id,
            leaf_id=job.leaf_id,
            mechanism_id=job.mechanism_id,
            status=ComponentStatus.CONVERGED,
            convergence_basis="ORDER_RESOLVED",
            response=response,
            signed_root_crosscheck=response,
            closed_form_response=None,
            error_channels={
                "signed-root": 2.0e-9,
                "truncation": 3.0e-9,
                "resolution": 4.0e-9,
                "seed-path": 5.0e-9,
                "axis": 6.0e-9,
                "amplitude": 7.0e-9,
            },
            baseline=RootReadout(
                omega=job.root.omega,
                determinant_residual_abs=3.50e-11,
                determinant_derivative_abs=36.1,
                converged=True,
                root_reference_id=job.root.root_reference_id,
                branch_id=job.root.branch_id,
                equation_id=job.equation_id,
            ),
            levels=levels,
            lineage={
                "leaf_id": job.leaf_id,
                "root_reference_id": job.root.root_reference_id,
                "root_identity_sha256": job.root.identity_sha256,
                "policy_sha256": job.policy.identity_sha256,
                "backend_identity_sha256": job.backend_identity.identity_sha256,
                "equation_id": job.equation_id,
                "sampling_coordinate": job.sampling_coordinate.to_mapping(),
                "source_root_mapping": None,
            },
        )
        component_result = {
            "evidence_kind": "authenticated-test-component",
            "result": result.to_mapping(),
        }
        family_deltas = {
            "signed-root": complex(1.0e-8, -2.0e-8),
            "centred-step-amplitude": 0.0j,
            "refinement-holdout": 0.0j,
            "truncation": 0.0j,
            "resolution-angular-refinement": 0.0j,
            "continuation-seed-path": 0.0j,
            "repeat-polish": 0.0j,
            "precision-ladder-discrepancy": 0.0j,
        }
        stage = StageOutcome(
            digits=64,
            numerical_state="CONVERGED",
            component_result=component_result,
            local_disk_radius_abs=abs(family_deltas["signed-root"]),
            signed_error_channels=explicit_stage_signed_error_channels(
                component_result,
                family_deltas=family_deltas,
                source_kind="authenticated-test-component",
                source_id=job.job_id,
                units="M-delta-omega-per-native-coordinate",
            ),
        )
        return CampaignLeafRecord(
            leaf_id=leaf.leaf_id,
            role=leaf.role,
            state="PRODUCED",
            stages=(CampaignStageRecord(stage, {
                "precision_factory_identity": (
                    plan.precision_factory_identity.to_mapping()
                ),
                "available_precision_digits": [64],
            }),),
        )

    def test_dashboard_reports_radial_integration_progress_inside_one_suboperation(self):
        """Catches a long radial solve that shows no evidence of advancing."""

        with tempfile.TemporaryDirectory() as temporary:
            checkpoint = Path(temporary) / "checkpoint.json"
            reporter = CampaignProgressReporter("normal", checkpoint, io.StringIO())
            base_time = time.monotonic()
            base_context = {
                "leaf_index": 4,
                "leaf_count": 212,
                "leaf_id": "active-9999",
                "mechanism_id": "horizon-admittance",
                "precision_digits": 80,
                "phase": "PRIMARY",
            }

            def observe(kind, seconds, *, context=None, payload=None):
                event = ProgressEvent(
                    kind=kind,
                    context=ProgressContext.from_mapping({
                        **base_context,
                        **(context or {}),
                    }),
                    payload=payload or {},
                    monotonic_seconds=base_time + seconds,
                )
                record = reporter._record(event)
                reporter._update_dashboard_state(record)
                return record

            observe(ProgressEventKind.PRECISION_STAGE_STARTED, 0.0)
            observe(
                ProgressEventKind.SUBOPERATION_STARTED,
                0.1,
                context={"suboperation": "Xin"},
                payload={"suboperation": "Xin"},
            )
            advancing = observe(
                ProgressEventKind.SUBOPERATION_PROGRESS,
                900.0,
                context={"suboperation": "Xin"},
                payload={
                    "suboperation": "Xin",
                    "rhs_evaluations": 1048576,
                    "rho_current": -1200.0,
                    "rho_reached_min": -5000.0,
                    "rho_reached_max": -1200.0,
                    "rho_span": 10000.0,
                    "rho_span_fraction": 0.38,
                    "elapsed_seconds": 900.0,
                },
            )
            dashboard = "\n".join(reporter._dashboard_lines(advancing))
            reporter._terminal_dimensions = lambda: (120, 30)
            bounded = "\n".join(reporter._bounded_dashboard_lines(advancing))
            reporter._write_status(advancing)
            status = json.loads(
                Path(f"{checkpoint}.status.json").read_text(encoding="utf-8")
            )

            self.assertIn("Radial progress", dashboard)
            self.assertIn("1048576 evals", dashboard)
            self.assertIn("38.0% of ρ span", dashboard)
            self.assertIn("900s", dashboard)
            # The bounded panel must not spend an extra row on it.
            self.assertIn("1048576 evals", bounded)
            execution = status["live_execution"]
            self.assertEqual(execution["radial_suboperation"], "Xin")
            self.assertEqual(execution["radial_rhs_evaluations"], 1048576)
            self.assertEqual(execution["radial_rho_span_fraction"], 0.38)

            # A completed integration must stop reporting the interior progress
            # of the integration that has just finished.
            completed = observe(
                ProgressEventKind.SUBOPERATION_COMPLETED,
                901.0,
                context={"suboperation": "Xin"},
                payload={"suboperation": "Xin", "elapsed_seconds": 901.0},
            )
            self.assertNotIn(
                "1048576 evals", "\n".join(reporter._dashboard_lines(completed))
            )

    def test_dashboard_separates_completed_leaf_from_live_promoted_worker(self):
        """Catches a running BigFloat stage being hidden by completed science."""

        with tempfile.TemporaryDirectory() as temporary:
            checkpoint = Path(temporary) / "checkpoint.json"
            reporter = CampaignProgressReporter("normal", checkpoint, io.StringIO())
            reporter._campaign_report_model = CampaignReportModel(
                leaf_rows=({
                    "leaf_id": "completed-999",
                    "terminal_state": "PRODUCED",
                    "mechanism": "horizon-admittance",
                    "spin_or_Mkappa": 0.999,
                    "precision_digits": 64,
                    "mode": "220",
                },),
                error_channel_rows=(),
                projective_rows=(),
                checkpoint_source_receipt="fixture-receipt",
                precision_stage_rows=({
                    "leaf_id": "active-9999",
                    "root": "220 a/M=0.9999",
                    "precision_digits": 64,
                    "numerical_state": "NOT_CONVERGED",
                },),
            )
            reporter._last_terminal_leaf = "completed-999"
            reporter._last_terminal_state = "PRODUCED"
            base_time = time.monotonic()
            base_context = {
                "leaf_index": 16,
                "leaf_count": 212,
                "leaf_id": "active-9999",
                "role": "primary",
                "mode": {"s": -2, "ell": 2, "m": 2, "n": 0},
                "spin": 0.9999,
                "mechanism_id": "horizon-admittance",
                "precision_digits": 80,
                "component_pass": "promoted",
            }

            def observe(kind, seconds, *, context=None, payload=None):
                event = ProgressEvent(
                    kind=kind,
                    context=ProgressContext.from_mapping({
                        **base_context,
                        **(context or {}),
                    }),
                    payload=payload or {},
                    monotonic_seconds=base_time + seconds,
                )
                record = reporter._record(event)
                reporter._update_dashboard_state(record)
                return record

            observe(ProgressEventKind.PRECISION_STAGE_STARTED, 0.0)
            observe(
                ProgressEventKind.ROOT_PHASE_STARTED,
                0.1,
                context={"phase": "PRIMARY"},
            )
            observe(
                ProgressEventKind.ROOT_SEED_SELECTED,
                0.2,
                context={
                    "phase": "PRIMARY",
                    "seed_kind": "AUTHENTICATED_BACKGROUND",
                    "fallback_used": False,
                },
                payload={
                    "seed_kind": "AUTHENTICATED_BACKGROUND",
                    "fallback_used": False,
                },
            )
            observe(
                ProgressEventKind.NEWTON_ITERATION_STARTED,
                1.0,
                context={
                    "phase": "PRIMARY",
                    "newton_index": 7,
                    "newton_limit": 16,
                    "current_omega": {
                        "real": "0.98567354838270116",
                        "imaginary": "-0.0034686730676767082",
                    },
                },
                payload={
                    "determinant_abs": "2.40e-11",
                    "best_determinant_abs": "2.40e-11",
                },
            )
            observe(
                ProgressEventKind.SUBOPERATION_STARTED,
                2.0,
                context={
                    "phase": "PRIMARY",
                    "newton_index": 7,
                    "newton_limit": 16,
                    "determinant_index_phase": 146,
                    "suboperation": "r-from-rho",
                },
                payload={"suboperation": "r-from-rho"},
            )
            heartbeat = observe(
                ProgressEventKind.WORKER_HEARTBEAT,
                12.0,
                payload={
                    "worker": "Julia",
                    "worker_alive": True,
                    "heartbeat_interval_seconds": 2.0,
                },
            )

            dashboard = "\n".join(reporter._dashboard_lines(heartbeat))
            reporter._terminal_dimensions = lambda: (120, 30)
            bounded_dashboard = "\n".join(
                reporter._bounded_dashboard_lines(heartbeat)
            )
            reporter._write_status(heartbeat)
            status = json.loads(
                Path(f"{checkpoint}.status.json").read_text(encoding="utf-8")
            )

        self.assertIn("LATEST COMPLETED LEAF", dashboard)
        self.assertIn("CURRENTLY EXECUTING", dashboard)
        self.assertIn("Current leaf   16/212", dashboard)
        self.assertIn("LIVE ROOT SOLVE", dashboard)
        self.assertIn("220 a/M=0.9999", dashboard)
        self.assertIn("BigFloat 80 dec", dashboard)
        self.assertIn("PRIMARY", dashboard)
        self.assertIn("RUNNING", dashboard)
        self.assertIn("binary64 NOT_CONVERGED", dashboard)
        self.assertIn("AUTHENTICATED_BACKGROUND", dashboard)
        self.assertIn("Seed authenticated", dashboard)
        self.assertIn("YES", dashboard)
        self.assertIn("Branch valid", dashboard)
        self.assertIn("PENDING", dashboard)
        self.assertIn("Worker", dashboard)
        self.assertIn("Julia", dashboard)
        self.assertIn("Tier elapsed", dashboard)
        self.assertIn("12s", dashboard)
        self.assertIn("Last activity", dashboard)
        self.assertIn("r-from-rho started (10s ago)", dashboard)
        self.assertIn("Newton", dashboard)
        self.assertIn("7/16", dashboard)
        self.assertIn("Determinant", dashboard)
        self.assertIn("146", dashboard)
        self.assertIn("0.98567354838270116", dashboard)
        self.assertIn("2.400E-11", dashboard)
        self.assertIn("LATEST COMPLETED LEAF", bounded_dashboard)
        self.assertIn("CURRENTLY EXECUTING", bounded_dashboard)
        self.assertIn("Current leaf   16/212", bounded_dashboard)
        self.assertIn("LIVE ROOT SOLVE", bounded_dashboard)
        self.assertIn("PRECISION STAGE RESULTS", bounded_dashboard)
        self.assertIn("220 a/M=0.9999", bounded_dashboard)
        self.assertRegex(
            bounded_dashboard,
            r"220 a/M=0\.9999\s+binary64 \(~15\.95 dec\)",
        )
        self.assertTrue(reporter._should_render_dashboard(SimpleNamespace(
            kind=ProgressEventKind.WORKER_HEARTBEAT,
            monotonic_seconds=base_time + 14.0,
        )))
        self.assertEqual(status["live_execution"]["state"], "RUNNING")
        self.assertEqual(status["live_execution"]["leaf_index"], 16)
        self.assertEqual(status["live_execution"]["leaf_count"], 212)
        self.assertEqual(status["live_execution"]["precision_digits"], 80)
        self.assertEqual(status["live_execution"]["suboperation"], "r-from-rho")

    def test_precision_stage_table_uses_unit_aware_labels_and_real_thresholds(self):
        """Catches restoring the table with ambiguous 64/80/120 units."""

        reporter = CampaignProgressReporter(
            "normal", "checkpoint.json", io.StringIO()
        )
        reporter._campaign_report_model = CampaignReportModel(
            leaf_rows=(),
            error_channel_rows=(),
            projective_rows=(),
            checkpoint_source_receipt="fixture-receipt",
            precision_stage_rows=tuple(
                {
                    "root": f"220 a/M=0.{digits}",
                    "precision_digits": digits,
                    "numerical_state": "CONVERGED",
                    "converged": True,
                    "branch_ok": True,
                    "determinant_abs": 1.0e-18,
                    "newton_correction_over_tolerance": 1.0,
                    "newton_correction": 1.0e-19,
                    "root_displacement_abs": 1.0e-18,
                }
                for digits in (64, 80, 120)
            ),
        )

        table = "\n".join(reporter._precision_stage_table_lines())

        self.assertIn("binary64 (~15.95 dec)", table)
        self.assertIn("BigFloat 80 dec", table)
        self.assertIn("BigFloat 120 dec", table)
        self.assertNotIn("  64 CONVERGED", table)
        self.assertEqual(_root_correction_tolerance_for_precision(64), 2.0e-11)
        self.assertEqual(_root_correction_tolerance_for_precision(80), 2.0e-11)
        # The promoted target is the same at both storage tiers. It was
        # previously reconstructed from the digit count as 1e-102, which is a
        # threshold no promoted request has ever carried.
        self.assertEqual(_root_correction_tolerance_for_precision(120), 2.0e-11)

    def test_dashboard_throttles_fast_inner_events_but_forces_heartbeat(self):
        """Catches terminal redraw volume scaling with determinant operations."""

        reporter = CampaignProgressReporter(
            "normal", "checkpoint.json", io.StringIO()
        )

        def event(kind, seconds):
            return SimpleNamespace(kind=kind, monotonic_seconds=seconds)

        self.assertTrue(reporter._should_render_dashboard(event(
            ProgressEventKind.PRECISION_STAGE_STARTED, 1.0
        )))
        self.assertFalse(reporter._should_render_dashboard(event(
            ProgressEventKind.DETERMINANT_STARTED, 1.01
        )))
        self.assertFalse(reporter._should_render_dashboard(event(
            ProgressEventKind.SUBOPERATION_STARTED, 1.20
        )))
        self.assertFalse(reporter._should_render_dashboard(event(
            ProgressEventKind.DETERMINANT_COMPLETED, 1.30
        )))
        self.assertFalse(reporter._should_render_dashboard(event(
            ProgressEventKind.SUBOPERATION_COMPLETED, 1.305
        )))
        self.assertTrue(reporter._should_render_dashboard(event(
            ProgressEventKind.WORKER_HEARTBEAT, 1.31
        )))

    def test_refresh_projects_committed_checkpoint_without_mutating_it(self):
        """Catches absent or nondeterministic audit projections of committed science."""

        plan = self._plan()
        leaf = plan.leaves[0]
        record = self._produced_record(plan, leaf)
        selection = build_campaign_selection(
            plan, role="primary", leaf_ids=(leaf.leaf_id,)
        )

        with tempfile.TemporaryDirectory() as temporary:
            checkpoint = Path(temporary) / "m02-campaign-checkpoint.json"
            checkpoint.write_bytes(canonical_json_bytes(
                _checkpoint_mapping(plan, selection, (record,))
            ))
            original_checkpoint = checkpoint.read_bytes()

            model = refresh_campaign_reports(
                plan,
                checkpoint,
                run_provenance={leaf.leaf_id: "EXECUTED"},
            )

            report_directory = (
                Path(temporary) / "m02-campaign-checkpoint.reports"
            )
            leaves_path = report_directory / "m02-leaves.csv"
            channels_path = report_directory / "m02-error-channels.csv"
            projective_path = report_directory / "m02-projective.csv"
            self.assertTrue(leaves_path.is_file())
            self.assertTrue(channels_path.is_file())
            self.assertTrue(projective_path.is_file())
            self.assertEqual(checkpoint.read_bytes(), original_checkpoint)

            with leaves_path.open(newline="", encoding="utf-8") as handle:
                leaves = list(csv.DictReader(handle))
            self.assertEqual(len(leaves), 212)
            current = next(item for item in leaves if item["leaf_id"] == leaf.leaf_id)
            self.assertEqual(current["terminal_state"], "PRODUCED")
            self.assertEqual(current["component_status"], "CONVERGED")
            self.assertEqual(current["precision_digits"], "64")
            self.assertEqual(current["precision_tier"], "binary64")
            self.assertEqual(
                current["precision_decimal_digits_nominal"], "15.95"
            )
            self.assertEqual(current["convergence_basis"], "ORDER_RESOLVED")
            self.assertEqual(current["run_provenance"], "EXECUTED")
            self.assertEqual(float(current["response_real"]), 1.25)
            self.assertEqual(float(current["response_imaginary"]), -0.5)
            self.assertEqual(
                float(current["baseline_omega_real"]), leaf.job.root.omega.real
            )
            self.assertEqual(
                float(current["baseline_omega_imaginary"]),
                leaf.job.root.omega.imag,
            )
            self.assertEqual(
                float(current["baseline_determinant_residual"]), 3.50e-11
            )
            self.assertEqual(float(current["signed_root_crosscheck_real"]), 1.25)
            self.assertEqual(
                float(current["signed_root_crosscheck_imaginary"]), -0.5
            )
            self.assertEqual(len(model.precision_stage_rows), 1)
            stage_row = model.precision_stage_rows[0]
            self.assertEqual(stage_row["root"], "220 a/M=0.95")
            self.assertEqual(stage_row["precision_digits"], 64)
            self.assertEqual(stage_row["numerical_state"], "CONVERGED")
            self.assertIs(stage_row["converged"], True)
            self.assertIs(stage_row["branch_ok"], True)
            self.assertAlmostEqual(stage_row["determinant_abs"], 3.50e-11)
            self.assertAlmostEqual(
                stage_row["newton_correction_over_tolerance"],
                (3.50e-11 / 36.1) / 2.0e-11,
            )
            self.assertAlmostEqual(
                stage_row["newton_correction"], 3.50e-11 / 36.1
            )
            self.assertEqual(stage_row["root_displacement_abs"], 0.0)

    def test_report_tolerance_follows_policy_not_storage_precision(self):
        """Catches reports reconstructing the solve target from digit count.

        The promoted threshold is a property of the physics, so it is the same
        at both storage tiers. Deriving it from precision produced ``1e-102``
        for a 120-digit stage while the request actually carried the former uncalibrated ``1e-18``,
        making ``newton_correction_over_tolerance`` wrong by roughly eighty
        orders of magnitude -- a converged root reads as hopelessly
        under-converged.
        """

        from windows_solver.campaign_reports import (
            _root_correction_tolerance_for_precision as tolerance_for,
        )
        from windows_solver.julia_response_backend import (
            promoted_precision_numerical_controls,
        )

        controls = promoted_precision_numerical_controls()
        for digits in (80, 120):
            with self.subTest(digits=digits):
                self.assertEqual(
                    tolerance_for(digits),
                    float(
                        controls[str(digits)]["base"][
                            "root_correction_tolerance"
                        ]
                    ),
                )
        # Same physics target at both tiers, and emphatically not 1e-102.
        self.assertEqual(tolerance_for(120), tolerance_for(80))
        self.assertGreater(tolerance_for(120), 1.0e-30)
        # Binary64 is not a promoted tier and keeps its own threshold.
        self.assertEqual(tolerance_for(64), 2.0e-11)
        with self.assertRaises(ValueError):
            tolerance_for(96)

            reporter = CampaignProgressReporter("normal", checkpoint, io.StringIO())
            reporter._campaign_report_model = model
            table = "\n".join(reporter._precision_stage_table_lines())
            self.assertIn("ROOT", table)
            self.assertIn("CORR_OVER_TOL", table)
            self.assertNotIn("D_OVER_TOL", table.splitlines()[2].split())
            self.assertIn("NEWTON_DW", table)
            self.assertIn("DELTA_ROOT", table)
            self.assertIn("220 a/M=0.95", table)
            self.assertIn("CONVERGED", table)
            reporter._last_terminal_state = "CONVERGED"
            reporter._dashboard_state["mechanism_id"] = "horizon-admittance"
            compact = "\n".join(reporter._compact_dashboard_lines({
                "sequence": 1,
                "kind": ProgressEventKind.PRECISION_STAGE_COMPLETED.value,
                "elapsed_seconds": 0.0,
            }, 32))
            self.assertIn("LATEST COMPLETED LEAF", compact)
            self.assertIn("PRECISION STAGE RESULTS", compact)
            self.assertIn("220 a/M=0.95", compact)
            self.assertIn(" State          CONVERGED", compact)
            self.assertIn(" Mechanism      horizon-admittance", compact)
            self.assertTrue(reporter._should_render_dashboard(
                SimpleNamespace(
                    kind=ProgressEventKind.PRECISION_STAGE_COMPLETED,
                    monotonic_seconds=time.monotonic(),
                )
            ))
            legacy_fixture = CampaignReportModel(
                leaf_rows=(),
                error_channel_rows=(),
                projective_rows=(),
                checkpoint_source_receipt="fixture-receipt",
            )
            self.assertEqual(legacy_fixture.precision_stage_rows, ())
            pending = next(item for item in leaves if item["leaf_id"] != leaf.leaf_id)
            self.assertEqual(pending["terminal_state"], "PENDING")
            self.assertEqual(pending["response_real"], "")

            with channels_path.open(newline="", encoding="utf-8") as handle:
                channels = list(csv.DictReader(handle))
            self.assertEqual(len(channels), 8)
            self.assertTrue(
                all(item["precision_digits"] == "64" for item in channels)
            )
            self.assertTrue(
                all(item["precision_tier"] == "binary64" for item in channels)
            )
            self.assertTrue(
                all(
                    item["precision_decimal_digits_nominal"] == "15.95"
                    for item in channels
                )
            )
            self.assertEqual(
                tuple(item["family"] for item in channels),
                (
                    "signed-root",
                    "centred-step-amplitude",
                    "refinement-holdout",
                    "truncation",
                    "resolution-angular-refinement",
                    "continuation-seed-path",
                    "repeat-polish",
                    "precision-ladder-discrepancy",
                ),
            )
            self.assertTrue(all(
                item["source_receipt"]
                == "sha256:" + hashlib.sha256(original_checkpoint).hexdigest()
                for item in channels
            ))

            with projective_path.open(newline="", encoding="utf-8") as handle:
                projective = list(csv.DictReader(handle))
            self.assertEqual(len(projective), 57)
            self.assertEqual(projective[0]["reducer_state"], "INCOMPLETE")
            self.assertEqual(projective[0]["projective_outcome"], "")
            self.assertIn(leaf.leaf_id, projective[0]["present_component_ids"])
            self.assertTrue(projective[0]["missing_component_ids"])

            first_outputs = {
                path.name: path.read_bytes()
                for path in (leaves_path, channels_path, projective_path)
            }
            refresh_campaign_reports(
                plan,
                checkpoint,
                run_provenance={leaf.leaf_id: "EXECUTED"},
            )
            self.assertEqual(
                {
                    path.name: path.read_bytes()
                    for path in (leaves_path, channels_path, projective_path)
                },
                first_outputs,
            )

    def test_basic_reports_survive_projective_and_triage_failures(self):
        plan = self._plan()
        leaf = plan.leaves[0]
        record = self._produced_record(plan, leaf)
        selection = build_campaign_selection(
            plan, role="primary", leaf_ids=(leaf.leaf_id,)
        )

        for failure_kind in ("projective", "triage"):
            with (
                self.subTest(failure_kind=failure_kind),
                tempfile.TemporaryDirectory() as temporary,
            ):
                checkpoint = Path(temporary) / "checkpoint.json"
                checkpoint.write_bytes(
                    canonical_json_bytes(
                        _checkpoint_mapping(plan, selection, (record,))
                    )
                )
                triage = (
                    (lambda _model, _directory: (_ for _ in ()).throw(
                        RuntimeError("forced triage failure")
                    ))
                    if failure_kind == "triage"
                    else None
                )
                projective_patch = (
                    patch(
                        "windows_solver.campaign_reports.reduce_projective_rows",
                        side_effect=RuntimeError("forced projective failure"),
                    )
                    if failure_kind == "projective"
                    else nullcontext()
                )

                with projective_patch:
                    refresh_campaign_reports(
                        plan,
                        checkpoint,
                        advanced_triage=triage,
                    )

                directory = Path(temporary) / "checkpoint.reports"
                for name in (
                    "m02-leaves.csv",
                    "m02-precision-stages.csv",
                    "m02-error-channels.csv",
                    "m02-resource-failures.csv",
                ):
                    self.assertTrue((directory / name).is_file(), name)
                status = json.loads(
                    (directory / "m02-report-status.json").read_text()
                )
                self.assertEqual("COMPLETED", status["basic"]["status"])
                self.assertEqual(
                    "FAILED", status[failure_kind]["status"]
                )


class ProjectiveTriageProjectionTests(unittest.TestCase):
    """No hand-authored glue file: triage derives row-to-leaf projection
    automatically from the authenticated projective reduction."""

    @staticmethod
    def _row(row_id, left, right):
        return SimpleNamespace(
            row_id=row_id, left_component_ids=left, right_component_ids=right
        )

    @staticmethod
    def _result(row_id, *, interval, outcome):
        return SimpleNamespace(
            row_id=row_id,
            bounded_angle_interval_radians=interval,
            projective_outcome=outcome,
        )

    def test_leaf_lower_bound_is_the_minimum_across_its_complete_rows(self):
        reduction = SimpleNamespace(
            plans=(
                self._row("row-a", ("leaf-1",), ("leaf-2",)),
                self._row("row-b", ("leaf-1",), ("leaf-3",)),
            ),
            results=(
                self._result(
                    "row-a", interval=(0.5, 0.6), outcome="SEPARATED"
                ),
                self._result(
                    "row-b",
                    interval=(0.1, 0.2),
                    outcome="EQUIVALENT_WITHIN_TOLERANCE",
                ),
            ),
        )

        projections = _derive_projective_triage_projection(
            reduction, selected_leaf_ids=("leaf-1", "leaf-2", "leaf-3")
        )

        self.assertEqual((0.1, True), projections["leaf-1"])
        self.assertEqual((0.5, True), projections["leaf-2"])
        self.assertEqual((0.1, False), projections["leaf-3"])

    def test_incomplete_row_is_excluded_never_zero_never_safe(self):
        reduction = SimpleNamespace(
            plans=(
                self._row("row-a", ("leaf-1",), ("leaf-2",)),
                self._row("row-b", ("leaf-1",), ("leaf-3",)),
            ),
            results=(
                self._result("row-a", interval=None, outcome=None),
                self._result(
                    "row-b", interval=None, outcome="UNRESOLVED"
                ),
            ),
        )

        projections = _derive_projective_triage_projection(
            reduction, selected_leaf_ids=("leaf-1", "leaf-2", "leaf-3")
        )

        lower, controls = projections["leaf-1"]
        self.assertIsNone(lower)
        self.assertIs(controls, False)

    def test_mixed_complete_and_incomplete_rows_ignore_the_incomplete_one(self):
        reduction = SimpleNamespace(
            plans=(
                self._row("row-a", ("leaf-1",), ("leaf-2",)),
                self._row("row-b", ("leaf-1",), ("leaf-3",)),
            ),
            results=(
                self._result("row-a", interval=None, outcome="UNRESOLVED"),
                self._result(
                    "row-b",
                    interval=(0.3, 0.4),
                    outcome="EQUIVALENT_WITHIN_TOLERANCE",
                ),
            ),
        )

        projections = _derive_projective_triage_projection(
            reduction, selected_leaf_ids=("leaf-1", "leaf-2", "leaf-3")
        )

        self.assertEqual((0.3, False), projections["leaf-1"])

    def test_unselected_leaves_are_omitted(self):
        reduction = SimpleNamespace(
            plans=(self._row("row-a", ("leaf-1",), ("leaf-2",)),),
            results=(
                self._result(
                    "row-a",
                    interval=(0.1, 0.2),
                    outcome="EQUIVALENT_WITHIN_TOLERANCE",
                ),
            ),
        )

        projections = _derive_projective_triage_projection(
            reduction, selected_leaf_ids=("leaf-1",)
        )

        self.assertEqual({"leaf-1"}, set(projections))


if __name__ == "__main__":
    unittest.main()


class AuthenticationReportColumnTests(unittest.TestCase):
    """The acceptance comparison must survive into the report a human reads."""

    def _fields(self, readout):
        from windows_solver.campaign_reports import (
            _authentication_report_fields,
        )

        return _authentication_report_fields(readout)

    def test_authentication_columns_stay_a_sibling_of_conditioning(self):
        """Catches acceptance terms leaking into the solve-health surface.

        ``CONDITIONING_REPORT_COLUMNS`` is pinned by contract and mirrored into
        the live progress mapping, which reports how healthy a solve's
        arithmetic is. Acceptance evidence answers a different question and is
        present or absent independently, so it rides beside conditioning in the
        leaf row rather than inside it.
        """

        from windows_solver.campaign_reports import (
            AUTHENTICATION_REPORT_COLUMNS,
            CONDITIONING_REPORT_COLUMNS,
            LEAF_COLUMNS,
        )

        self.assertEqual(
            set(AUTHENTICATION_REPORT_COLUMNS)
            & set(CONDITIONING_REPORT_COLUMNS),
            set(),
        )
        self.assertTrue(set(AUTHENTICATION_REPORT_COLUMNS) <= set(LEAF_COLUMNS))
        # No column is silently dropped by a name collision in the leaf row.
        self.assertEqual(len(LEAF_COLUMNS), len(set(LEAF_COLUMNS)))

    def test_report_row_carries_every_term_of_the_acceptance_comparison(self):
        """Catches a report that shows ``converged`` and nothing behind it.

        A row saying a root converged, without the residual bound, derivative
        bound and error components the decision came from, cannot be audited --
        only believed. These columns exist so the comparison can be re-derived
        from the row itself.
        """

        from windows_solver.campaign_reports import (
            AUTHENTICATION_REPORT_COLUMNS,
        )
        from windows_solver.response_engine import RootAuthenticationEvidence
        from tests.fixtures import valid_root_authentication

        authentication = RootAuthenticationEvidence.from_mapping(
            valid_root_authentication("horizon-admittance")
        )
        fields = self._fields(
            SimpleNamespace(root_authentication=authentication)
        )

        self.assertEqual(
            set(AUTHENTICATION_REPORT_COLUMNS) - set(fields), set()
        )
        # Exact decimal text, not a binary64 rendering: at 1e-60 and below the
        # float round trip collapses distinct components onto one another.
        self.assertEqual(fields["determinant_error_abs"], "1.4E-60")
        self.assertEqual(fields["endpoint_disagreement_abs"], "2.1875E-62")
        self.assertEqual(fields["control_disagreement_abs"], "1E-62")
        self.assertEqual(fields["equivalence_disagreement_abs"], "5E-63")
        self.assertEqual(fields["precision_disagreement_abs"], "3E-63")
        self.assertEqual(fields["determinant_error_safety_factor"], "64")
        self.assertEqual(fields["central_determinant_re"], "1E-60")
        self.assertEqual(fields["central_determinant_im"], "0")
        self.assertEqual(fields["residual_upper_bound_abs"], "2.4E-60")
        self.assertEqual(
            fields["derivative_re"],
            "2.400000000000000000000000000000000000000000000000000003",
        )
        self.assertEqual(fields["derivative_im"], "0")
        self.assertEqual(fields["derivative_lower_bound_abs"], "2.4")
        self.assertEqual(fields["correction_upper_bound"], "1E-60")
        self.assertEqual(fields["root_correction_tolerance"], "2E-11")
        self.assertIs(fields["root_authentication_accepted"], True)
        self.assertEqual(fields["derivative_axis"], "real")
        self.assertEqual(
            fields["determinant_error_model"],
            "verified-endpoint-control-equivalence-absolute-error/v2",
        )

        # The decision re-derives from the row alone.
        from decimal import Decimal

        self.assertEqual(
            Decimal(fields["residual_upper_bound_abs"])
            / Decimal(fields["derivative_lower_bound_abs"]),
            Decimal(fields["correction_upper_bound"]),
        )

    def test_a_family_without_an_error_model_leaves_the_columns_empty(self):
        """Absent evidence must read as absent, never as a defaulted zero.

        A zero in these columns would claim a measured, perfect agreement. The
        exterior Wronskian path publishes no error model in this revision, so
        its columns have to stay null.
        """

        from windows_solver.campaign_reports import (
            AUTHENTICATION_REPORT_COLUMNS,
        )
        from windows_solver.response_engine import RootAuthenticationEvidence
        from tests.fixtures import valid_root_authentication

        authentication = RootAuthenticationEvidence.from_mapping(
            valid_root_authentication("exterior-fixed-r3")
        )
        fields = self._fields(
            SimpleNamespace(root_authentication=authentication)
        )

        self.assertIsNone(fields["determinant_error_abs"])
        self.assertIsNone(fields["determinant_error_model"])
        self.assertIsNone(fields["precision_disagreement_abs"])
        # The comparison's own terms are still present; only the error model is
        # missing.
        self.assertEqual(fields["residual_upper_bound_abs"], "2.4E-60")

        # A readout that predates the record leaves every column null rather
        # than failing, so historical checkpoints stay projectable.
        historical = self._fields(SimpleNamespace())
        for column in AUTHENTICATION_REPORT_COLUMNS:
            self.assertIsNone(historical[column])
