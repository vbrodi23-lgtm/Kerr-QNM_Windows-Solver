from __future__ import annotations

from decimal import Decimal, localcontext
import hashlib
import io
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import threading
import time
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
    _mode_specific_branch_enclosure_radius,
    _run_streamed_julia,
)
from windows_solver.progress import PROGRESS_SCHEMA, ProgressEventKind, activate_progress
from windows_solver.root_readout_cache import (
    ROOT_READOUT_STORE_DIRECTORY_NAME,
    RootReadoutStore,
    runtime_identity_sha256,
)
from windows_solver.response_batches import (
    PrecisionCapabilities,
    build_campaign_selection,
    build_campaign_plan,
    run_campaign_selection,
    scientific_computation_identity_sha256,
)
from windows_solver.response_engine import (
    LadderLevel,
    NumericalPolicy,
    VettedNativeDeterminantKernel,
    _diagnostic_response_channel,
)
from windows_solver.progress_output import CampaignProgressReporter
from tests.fixtures import valid_schema_three_julia_root_response


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

    @staticmethod
    def shifted(value, delta):
        with localcontext() as context:
            context.prec = 180
            return str(Decimal(value) + Decimal(delta))

    def evaluate(self, request):
        self.requests.append(request)
        return valid_schema_three_julia_root_response(request)

    def evaluate_for_validation(self, request):
        return SimpleNamespace(
            response=self.evaluate(request),
            request_binding=dict(request),
            request_sha256=hashlib.sha256(
                canonical_json_bytes(request)
            ).hexdigest(),
            runtime_identity_sha256=hashlib.sha256(
                canonical_json_bytes(
                    JuliaPrecisionRootBackend(
                        VettedNativeDeterminantKernel.identity,
                        self,
                        request["precision_digits"],
                        refinement=request["refinement_level"],
                    ).scientific_runtime_for(_deep_job())
                )
            ).hexdigest(),
            reused=False,
            cached_worker_response_receipt=None,
        )

    def retain_validated_readout(self, evaluation, receipt):
        return None

    def invalidate_validated_readout(self, evaluation):
        return None


class JuliaResponseBackendTests(unittest.TestCase):
    @staticmethod
    def _cache_adapter(root, runner):
        depot = root / "depot"
        depot.mkdir()
        for name in ("julia.exe", "Project.toml", "Manifest.toml", "worker.jl"):
            (root / name).write_text(name, encoding="ascii")
        store = RootReadoutStore(root / ROOT_READOUT_STORE_DIRECTORY_NAME)
        adapter = JuliaResponseAdapter(
            root / "julia.exe",
            root,
            depot,
            root / "worker.jl",
            dict(FakeAdapter.runtime_provenance),
            runner,
            readout_cache=store,
        )
        return adapter, store

    def test_invalid_fresh_success_is_rejected_before_cache_publication(self):
        """Catches adapter-only checks retaining a mechanism-swapped success."""

        def runner(command, **kwargs):
            request = json.loads(Path(command[-2]).read_text(encoding="utf-8"))
            response = valid_schema_three_julia_root_response(request)
            response["numerical_conditioning"]["determinant_family"] = (
                "cinc-over-cref-minus-R/v1"
            )
            response["numerical_conditioning"][
                "scattering_diagnostics_applicable"
            ] = True
            response["request_sha256"] = request["request_sha256"]
            Path(command[-1]).write_bytes(canonical_json_bytes(response))
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        with tempfile.TemporaryDirectory() as temporary:
            adapter, store = self._cache_adapter(Path(temporary), runner)
            backend = JuliaPrecisionRootBackend(
                VettedNativeDeterminantKernel.identity, adapter, 80
            )
            with self.assertRaises(JuliaResponseBackendError):
                backend.read_root(_deep_job(), 0.0j)
            self.assertEqual(store.stored_count, 0)

    def test_invalid_cached_success_is_evicted_then_valid_retry_is_reused(self):
        """Catches one poisoned entry permanently blocking exact recomputation."""

        calls = []

        def runner(command, **kwargs):
            calls.append(tuple(command))
            request = json.loads(Path(command[-2]).read_text(encoding="utf-8"))
            response = valid_schema_three_julia_root_response(request)
            response["request_sha256"] = request["request_sha256"]
            Path(command[-1]).write_bytes(canonical_json_bytes(response))
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        with tempfile.TemporaryDirectory() as temporary:
            adapter, store = self._cache_adapter(Path(temporary), runner)
            job = _deep_job()
            backend = JuliaPrecisionRootBackend(
                VettedNativeDeterminantKernel.identity, adapter, 80
            )
            request = backend._request(job, 0.0j)
            request_sha256 = hashlib.sha256(
                canonical_json_bytes(request)
            ).hexdigest()
            poisoned = valid_schema_three_julia_root_response(request)
            poisoned["schema_version"] = 2
            poisoned["request_sha256"] = request_sha256
            store.publish(
                request_sha256=request_sha256,
                runtime_identity=runtime_identity_sha256(
                    adapter.runtime_provenance
                ),
                response=poisoned,
            )

            with self.assertRaisesRegex(
                JuliaResponseBackendError, "response contract is invalid"
            ):
                backend.read_root(job, 0.0j)
            self.assertEqual(store.stored_count, 0)
            self.assertEqual(calls, [])

            first = backend.read_root(job, 0.0j)
            second = backend.read_root(job, 0.0j)
            self.assertEqual(len(calls), 1)
            self.assertEqual(second.to_mapping(), first.to_mapping())
            self.assertEqual(store.stored_count, 1)

    def test_worker_response_receipt_preserves_exact_determinant_text(self):
        """Catches reducing exact worker decimal evidence to one binary64 bin."""

        readout = JuliaPrecisionRootBackend(
            VettedNativeDeterminantKernel.identity, FakeAdapter(), 80
        ).read_root(_deep_job(), 0.0j)

        receipt = readout.worker_response_receipt
        self.assertEqual(
            receipt["root_residual_abs_text"],
            str(readout.normalised_determinant_abs),
        )
        self.assertEqual(len(receipt["receipt_sha256"]), 64)

    def test_success_wire_schema_is_three_and_worker_errors_remain_schema_one(self):
        """Catches changing the successful wire without preserving error parsing."""

        request = JuliaPrecisionRootBackend(
            VettedNativeDeterminantKernel.identity,
            FakeAdapter(),
            80,
        )._request(_deep_job(), 0.0j)
        self.assertEqual(
            valid_schema_three_julia_root_response(request)["schema_version"],
            3,
        )
        root = Path(__file__).resolve().parents[1]
        worker = (
            root / "src/windows_solver/data/julia/m02_worker.jl"
        ).read_text(encoding="utf-8")
        result_fields = worker[
            worker.index("function result_fields(") :
            worker.index("function evaluate_request(")
        ]
        self.assertEqual(result_fields.count('"schema_version" => 3'), 2)
        error_path = worker[
            worker.rindex("catch failure") : worker.index(
                "if abspath(PROGRAM_FILE)"
            )
        ]
        self.assertGreaterEqual(error_path.count('"schema_version" => 1'), 2)

    def test_worker_control_failure_binds_request_job_and_refinement(self):
        root = Path(__file__).resolve().parents[1]
        worker = (
            root / "src/windows_solver/data/julia/m02_worker.jl"
        ).read_text(encoding="utf-8")
        flatten = worker[
            worker.index("function flatten_request(") :
            worker.index("function parse_real(")
        ]
        context = worker[
            worker.index("function control_failure_context(") :
            worker.index("function throw_ode_resource_limit(")
        ]
        for field in (
            "job_id",
            "leaf_id",
            "role",
            "job_policy_sha256",
            "backend_identity_sha256",
            "refinement_level",
            "request_sha256",
        ):
            self.assertIn(f'"{field}" =>', flatten)
            self.assertIn(f'required(document, "{field}")', flatten)
            self.assertIn(f'"{field}" =>', context)
            self.assertIn(f'required(request, "{field}")', context)

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

    @staticmethod
    def _process_tree_command(
        directory: Path, *, emit_reserved_progress: bool = False
    ) -> tuple[str, ...]:
        parent_pid = directory / "parent.pid"
        child_pid = directory / "child.pid"
        marker = directory / "child.marker"
        child = (
            "import os,sys,time; "
            "open(sys.argv[1],'w',encoding='ascii').write(str(os.getpid())); "
            "f=open(sys.argv[2],'a',encoding='ascii'); "
            "[(f.write('x'),f.flush(),time.sleep(.02)) for _ in range(3000)]"
        )
        progress = ""
        if emit_reserved_progress:
            progress = (
                f"print({(JULIA_PROGRESS_PREFIX + json.dumps({'schema': PROGRESS_SCHEMA, 'kind': 'request_started', 'context': {}, 'payload': {}}))!r}, flush=True); "
            )
        parent = (
            "import os,subprocess,sys,time; "
            "open(sys.argv[1],'w',encoding='ascii').write(str(os.getpid())); "
            f"subprocess.Popen([sys.executable,'-c',{child!r},sys.argv[2],sys.argv[3]],"
            "stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL); "
            "deadline=time.time()+5; "
            "exec(\"while not os.path.exists(sys.argv[3]) and time.time() < deadline:\\n time.sleep(.01)\"); "
            + progress
            + "time.sleep(60)"
        )
        return (
            sys.executable,
            "-c",
            parent,
            str(parent_pid),
            str(child_pid),
            str(marker),
        )

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
        self.assertIn('"branch_authentication_contract_version" => 3', worker)
        self.assertIn('"root_branch_continuation_valid" => branch_valid', worker)
        self.assertIn('"branch_tolerance_abs" => numeric_text(branch_tolerance)', worker)
        self.assertIn('"root_displacement_abs" => numeric_text(abs(root - omega))', worker)
        self.assertNotIn('document["progress', worker)

    def test_package_worker_carries_the_initial_determinant_into_the_first_iteration(self):
        """Catches re-solving the determinant already computed at the seed."""

        worker = (
            Path(__file__).resolve().parents[1]
            / "src/windows_solver/data/julia/m02_worker.jl"
        ).read_text(encoding="utf-8")

        self.assertIn("initial_determinant = determinant_progress(", worker)
        self.assertIn("best_residual = abs(initial_determinant.value)", worker)
        self.assertIn("carried_residual = initial_determinant", worker)
        self.assertIn("carried_available = true", worker)
        self.assertIn("carried_available = false", worker)
        self.assertIn("carried_residual = candidate_residual", worker)
        self.assertIn("carried_available = true", worker)
        self.assertIn(
            "return value, magnitude, derivative, true, residual", worker
        )
        self.assertIn(
            "root, residual, accepted_derivative, newton_converged, "
            "root_evaluation =",
            worker,
        )
        self.assertIn("isnothing(accepted_derivative) ?", worker)
        # The seed determinant is carried, not recomputed, but every later
        # iteration still evaluates its own residual at its own frequency.
        bounded_newton = worker[
            worker.index("function bounded_newton(") :
            worker.index("numeric_text(value)")
        ]
        self.assertEqual(
            bounded_newton.count('"residual",'),
            1,
        )
        self.assertIn("magnitude = abs(residual.value)", bounded_newton)

    def test_package_worker_reports_radial_integration_interior_progress(self):
        """Catches a radial integration that cannot be told from a stalled one."""

        worker = (
            Path(__file__).resolve().parents[1]
            / "src/windows_solver/data/julia/m02_worker.jl"
        ).read_text(encoding="utf-8")

        self.assertIn("function observed_radial_map(", worker)
        self.assertIn('progress_emit("suboperation_progress"', worker)
        for field in (
            "rhs_evaluations",
            "rho_current",
            "rho_reached_min",
            "rho_reached_max",
            "rho_span_fraction",
        ):
            self.assertIn(f'"{field}"', worker)
        # Every package-owned contour map reports through the observed wrapper,
        # and the map itself still returns the unmodified radius.
        self.assertIn(
            "observed_radial_map(\n"
            "        raw_radius_from_rho, label, rho_in, rho_out\n"
            "    )",
            worker,
        )
        self.assertIn('lower, "Xin"', worker)
        self.assertIn('readout, "Xup"', worker)
        self.assertIn("return radial_map(rho)", worker)
        self.assertIn("progress_active() || return radial_map", worker)

    def test_package_worker_preserves_radial_tolerances_and_reports_r_from_rho(self):
        """Catches collapsing the promoted ODE tolerance pair or hiding its map."""

        worker = (
            Path(__file__).resolve().parents[1]
            / "src/windows_solver/data/julia/m02_worker.jl"
        ).read_text(encoding="utf-8")

        self.assertIn(
            'progress_operation("r-from-rho"; payload=Dict(', worker
        )
        self.assertIn(
            'reltol=parse_real(T, request, "ode_relative_tolerance")', worker
        )
        self.assertIn(
            'abstol=parse_real(T, request, "ode_absolute_tolerance")', worker
        )
        self.assertNotIn("tolerance = min(", worker)
        self.assertNotIn("reltol=tolerance", worker)
        self.assertNotIn("abstol=tolerance", worker)

    def test_package_worker_observes_every_promoted_ode_leg_before_use(self):
        root = Path(__file__).resolve().parents[1]
        worker = (root / "src/windows_solver/data/julia/m02_worker.jl").read_text(
            encoding="utf-8"
        )
        complex_frequencies = (
            root
            / "src/windows_solver/data/julia/GeneralizedSasakiNakamura.jl/src/Homogeneous/ComplexFrequencies.jl"
        ).read_text(encoding="utf-8")

        for leg in (
            "r_from_rho_positive",
            "r_from_rho_negative",
            "Xin_inner_to_match",
            "Xin_match_to_outer",
            "Xup_outer_to_match",
            "Xup_match_to_inner",
        ):
            self.assertIn(f'"{leg}"', complex_frequencies)
        self.assertIn("ode_observation_factory=nothing", complex_frequencies)
        self.assertIn("ode_solution_observer=nothing", complex_frequencies)
        self.assertIn("ode_solution_observer(", complex_frequencies)
        self.assertIn("function ode_observation_factory(", worker)
        self.assertIn("function observe_ode_solution(", worker)
        self.assertIn("DiscreteCallback(", worker)
        self.assertIn("save_positions=(false, false)", worker)
        self.assertIn("SciMLBase.u_modified!(integrator, false)", worker)
        self.assertIn("stats = solution.stats", worker)

    def test_package_worker_serializes_ode_control_failures_without_policy_drift(self):
        root = Path(__file__).resolve().parents[1]
        worker = (root / "src/windows_solver/data/julia/m02_worker.jl").read_text(
            encoding="utf-8"
        )
        complex_frequencies = (
            root
            / "src/windows_solver/data/julia/GeneralizedSasakiNakamura.jl/src/Homogeneous/ComplexFrequencies.jl"
        ).read_text(encoding="utf-8")

        self.assertIn("abstract type ODEControlFailure", worker)
        self.assertIn("SciMLBase.ReturnCode.MaxIters", worker)
        self.assertIn('"ODE_RESOURCE_LIMIT"', worker)
        self.assertIn('"ODE_SOLVER_FAILURE"', worker)
        self.assertIn("failure isa ODEControlFailure && rethrow()", worker)
        self.assertIn('"failure" => failure_details(failure)', worker)
        self.assertIn("homogeneous_ode_maxiters", worker)
        self.assertNotIn("maxiters=Inf", worker)
        self.assertNotIn("maxiters=Inf", complex_frequencies)
        self.assertIn("maxiters=ode_maxiters", worker)
        self.assertIn("maxiters=ode_maxiters", complex_frequencies)
        for resource in (
            "max_accepted_steps_per_homogeneous_leg",
            "max_rhs_evaluations_per_homogeneous_leg",
            "homogeneous_leg_wall_clock_seconds",
            "cooperative_request_deadline_seconds",
        ):
            self.assertIn(resource, worker)

    def test_package_worker_short_circuits_infeasible_and_unsuccessful_primary(self):
        worker = (
            Path(__file__).resolve().parents[1]
            / "src/windows_solver/data/julia/m02_worker.jl"
        ).read_text(encoding="utf-8")

        self.assertIn('progress_emit("root_readout_resource_infeasible"', worker)
        self.assertIn('"ROOT_READOUT_RESOURCE_INFEASIBLE"', worker)
        self.assertIn('"minimum_remaining_determinant_count" => 8', worker)
        self.assertIn('"estimator" => "first-determinant-linear-lower-bound/v1"', worker)
        self.assertIn('"diagnostics_skipped_reason" => "PRIMARY_NOT_CONVERGED"', worker)
        primary_guard = worker.index("if !primary_converged")
        truncation = worker.index('"TRUNCATION"', primary_guard)
        self.assertLess(primary_guard, truncation)

    def test_package_worker_gates_roots_on_newton_correction(self):
        """Catches restoring the normalization-dependent bare residual gate."""

        root = Path(__file__).resolve().parents[1]
        worker = (root / "src/windows_solver/data/julia/m02_worker.jl").read_text(
            encoding="utf-8"
        )

        self.assertIn('"root_correction_tolerance"', worker)
        self.assertIn('"newton_correction_estimate_abs"', worker)
        self.assertIn("correction_abs = magnitude / derivative_abs", worker)
        self.assertIn("correction_abs <= tolerance", worker)
        self.assertNotIn("best_residual <= tolerance", worker)

    def test_package_worker_uses_stable_two_ended_determinants(self):
        """Catches singular horizon reconstruction and common-flow exterior roots."""

        worker = (
            Path(__file__).resolve().parents[1]
            / "src/windows_solver/data/julia/m02_worker.jl"
        ).read_text(encoding="utf-8")

        self.assertIn("Solutions.solve_scaled_factored_scattering(", worker)
        self.assertIn("Solutions.evaluate_normalised_horizon_determinant(", worker)
        self.assertIn(
            "reflectivity = amplitude / "
            "(T(2) * im * spectral.p_horizon - amplitude)",
            worker,
        )
        self.assertNotIn("xout_match =", worker)
        self.assertIn(
            "xup_match = CF.reconstruct_factored_match_state(",
            worker,
        )
        self.assertIn(
            "Complex{T}[xup_match.X, xup_match.dX_drstar]",
            worker,
        )
        self.assertNotIn("perturbed_Xup_real_radius", worker)
        self.assertNotIn("chart_ratio < one(T)", worker)
        self.assertIn("chart_relative_margin > sqrt(eps(T))", worker)
        self.assertIn(
            '"Cinc" => progress_complex(coefficients.Cinc)', worker
        )
        self.assertIn(
            '"Cref" => progress_complex(coefficients.Cref)', worker
        )
        self.assertIn(
            '"matching_reconstruction_residual" => string(', worker
        )

    def test_package_worker_rejects_invalid_mechanism_and_support_contracts(self):
        worker = (
            Path(__file__).resolve().parents[1]
            / "src/windows_solver/data/julia/m02_worker.jl"
        ).read_text(encoding="utf-8")

        for mechanism in (
            "horizon-admittance",
            "exterior-fixed-r3",
            "exterior-light-ring",
            "exterior-throat-kappa",
            "exterior-alpha-zero",
            "exterior-alpha-half",
            "exterior-alpha-one",
        ):
            self.assertIn(f'"{mechanism}"', worker)
        self.assertIn("ALLOWED_MECHANISMS", worker)
        self.assertIn("unsupported mechanism_id", worker)
        self.assertIn("half_width > zero(T)", worker)
        self.assertIn("support lower bound is inconsistent", worker)
        self.assertIn("support upper bound is inconsistent", worker)

    def test_package_worker_rejects_an_unaccepted_newton_step(self):
        worker = (
            Path(__file__).resolve().parents[1]
            / "src/windows_solver/data/julia/m02_worker.jl"
        ).read_text(encoding="utf-8")

        self.assertNotIn('value -= parse(T, "0.125") * step', worker)
        self.assertIn("!accepted && break", worker)
        self.assertIn("best_value, best_residual = candidate, candidate_abs", worker)

    def test_package_worker_cross_checks_frequency_derivatives(self):
        worker = (
            Path(__file__).resolve().parents[1]
            / "src/windows_solver/data/julia/m02_worker.jl"
        ).read_text(encoding="utf-8")

        for evidence in (
            "derivative_real_half",
            "derivative_real_base",
            "derivative_real_double",
            "derivative_imaginary",
            "derivative_uncertainty_abs",
            "derivative_lower_bound_abs",
        ):
            self.assertIn(evidence, worker)
        self.assertIn("correction_upper_bound", worker)
        self.assertIn("real_step_convergent", worker)
        self.assertIn("complex_axis_consistent", worker)
        self.assertIn(
            "return root, residual, derivative_lower_bound_abs, converged",
            worker,
        )
        self.assertIn("derivative_control_completed", worker)

    def test_package_worker_confines_fine_steps_and_stores_only_endpoints(self):
        worker = (
            Path(__file__).resolve().parents[1]
            / "src/windows_solver/data/julia/m02_worker.jl"
        ).read_text(encoding="utf-8")

        self.assertIn("function radial_rhs!(du, state, parameters, radius)", worker)
        self.assertIn("vacuum_tail_dtmax = T(0.2)", worker)
        self.assertIn("fine_dtmax = min(", worker)
        self.assertIn("tstops=[stop_radius]", worker)
        self.assertIn("save_everystep=false", worker)
        self.assertIn("save_start=false", worker)
        self.assertIn("save_end=true", worker)
        self.assertIn("dense=false", worker)
        self.assertIn("solution.u[end]", worker)
        self.assertIn('ode_leg="$(ode_leg)_compact_support"', worker)
        self.assertIn('ode_leg="$(ode_leg)_vacuum_tail"', worker)
        self.assertIn('ode_leg="perturbed_Xin"', worker)

    def test_package_worker_avoids_unused_exterior_homogeneous_half_solutions(self):
        worker = (
            Path(__file__).resolve().parents[1]
            / "src/windows_solver/data/julia/m02_worker.jl"
        ).read_text(encoding="utf-8")

        for retired in (
            "solve_xin_at_match",
            "solve_xup_at_match",
            "homogeneous_rho_rhs!",
            "solve_homogeneous_endpoint",
            "xup_outer_to_match_raw",
            "solve_xup_scattering_coefficients",
        ):
            self.assertNotIn(f"function {retired}(", worker)
        self.assertIn("CF.prepare_factored_horizon_ingoing(", worker)
        self.assertIn("CF.prepare_factored_infinity_outgoing(", worker)
        self.assertIn("CF.solve_factored_xin_to_match(", worker)
        self.assertIn("CF.solve_factored_xup_to_match(", worker)

    def test_promoted_branch_authentication_uses_a_mode_specific_enclosure(self):
        root = Path(__file__).resolve().parents[1]
        worker = (root / "src/windows_solver/data/julia/m02_worker.jl").read_text(
            encoding="utf-8"
        )
        backend = (
            root / "src/windows_solver/julia_response_backend.py"
        ).read_text(encoding="utf-8")

        self.assertIn('"branch_enclosure_radius_abs"', worker)
        self.assertIn('"branch_enclosure_radius_abs"', backend)
        self.assertIn("_mode_specific_branch_enclosure_radius", backend)
        self.assertIn('"branch_authentication_contract_version" => 3', worker)

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

    def test_reserved_horizon_chart_event_is_forwarded_to_active_reporter(self):
        class Observer:
            def __init__(self):
                self.events = []

            def publish(self, event):
                self.events.append(event)

        observer = Observer()
        line = JULIA_PROGRESS_PREFIX + json.dumps({
            "schema": PROGRESS_SCHEMA,
            "kind": "horizon_chart_evaluated",
            "context": {},
            "payload": {
                "Cinc": {"real": "1.0", "imaginary": "-0.5"},
                "Cref": {"real": "0.25", "imaginary": "0.125"},
                "horizon_frequency": {"real": "0.01", "imaginary": "-0.02"},
                "reflectivity": {"real": "0.03", "imaginary": "0.04"},
                "chart_denominator": {"real": "0.05", "imaginary": "0.06"},
                "Cinc_abs": "1.118033988749895",
                "Cref_abs": "0.2795084971874737",
                "horizon_frequency_abs": "0.0223606797749979",
                "reflectivity_abs": "0.05",
                "chart_denominator_abs": "0.07810249675906655",
                "chart_scale_abs": "0.04",
                "chart_condition_abs": "1.9525624189766637",
                "chart_condition_threshold": "1e-40",
                "chart_ratio": "0.1",
            },
        })
        with activate_progress(observer):
            self.assertTrue(_forward_julia_progress_line(line))

        self.assertEqual(len(observer.events), 1)
        self.assertIs(
            observer.events[0].kind,
            ProgressEventKind.HORIZON_CHART_EVALUATED,
        )
        self.assertEqual(observer.events[0].payload["chart_ratio"], "0.1")

    def test_reserved_derivative_control_event_is_forwarded_to_active_reporter(self):
        class Observer:
            def __init__(self):
                self.events = []

            def publish(self, event):
                self.events.append(event)

        observer = Observer()
        line = JULIA_PROGRESS_PREFIX + json.dumps({
            "schema": PROGRESS_SCHEMA,
            "kind": "derivative_control_completed",
            "context": {},
            "payload": {
                "derivative_real_half": {"real": "2.0", "imaginary": "0.1"},
                "derivative_real_base": {"real": "2.1", "imaginary": "0.1"},
                "derivative_real_double": {"real": "2.2", "imaginary": "0.1"},
                "derivative_imaginary": {"real": "2.0", "imaginary": "0.2"},
                "fine_step_difference_abs": "0.1",
                "coarse_step_difference_abs": "0.2",
                "complex_axis_difference_abs": "0.1",
                "real_step_convergent": True,
                "complex_axis_consistent": True,
                "derivative_uncertainty_abs": "0.2",
                "derivative_lower_bound_abs": "1.8024984394500787",
                "correction_upper_bound": "1e-18",
                "accepted": True,
            },
        })
        with activate_progress(observer):
            self.assertTrue(_forward_julia_progress_line(line))

        self.assertEqual(len(observer.events), 1)
        self.assertIs(
            observer.events[0].kind,
            ProgressEventKind.DERIVATIVE_CONTROL_COMPLETED,
        )
        self.assertIs(observer.events[0].payload["accepted"], True)

    def test_every_literal_worker_progress_event_is_registered_in_python(self):
        worker = (
            Path(__file__).resolve().parents[1]
            / "src/windows_solver/data/julia/m02_worker.jl"
        ).read_text(encoding="utf-8")
        worker_kinds = set(re.findall(r'progress_emit\("([^"]+)"', worker))
        python_kinds = {kind.value for kind in ProgressEventKind}

        self.assertEqual(worker_kinds - python_kinds, set())

    def test_unknown_reserved_julia_progress_kind_is_fail_closed(self):
        line = JULIA_PROGRESS_PREFIX + json.dumps({
            "schema": PROGRESS_SCHEMA,
            "kind": "unregistered_worker_event",
            "context": {},
            "payload": {},
        })

        with self.assertRaises(JuliaResponseBackendError):
            _forward_julia_progress_line(line)

    def test_malformed_reserved_julia_progress_is_fail_closed(self):
        with self.assertRaises(JuliaResponseBackendError):
            _forward_julia_progress_line(JULIA_PROGRESS_PREFIX + "{")

    def test_streamed_worker_timeout_terminates_descendant_process_tree(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            command = self._process_tree_command(directory)
            try:
                completed = _run_streamed_julia(
                    command, cwd=directory, env=os.environ, timeout=1
                )
                self.assertTrue(completed.timed_out)
                marker = directory / "child.marker"
                before = marker.stat().st_size
                time.sleep(0.2)
                self.assertEqual(marker.stat().st_size, before)
            finally:
                self._force_stop_process(directory / "child.pid")
                self._force_stop_process(directory / "parent.pid")

    def test_streamed_worker_keyboard_interrupt_terminates_descendant_tree(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            command = self._process_tree_command(
                directory, emit_reserved_progress=True
            )
            try:
                with patch(
                    "windows_solver.julia_response_backend._forward_julia_progress_line",
                    side_effect=KeyboardInterrupt,
                ):
                    with self.assertRaises(KeyboardInterrupt):
                        _run_streamed_julia(
                            command, cwd=directory, env=os.environ, timeout=5
                        )
                marker = directory / "child.marker"
                before = marker.stat().st_size
                time.sleep(0.2)
                self.assertEqual(marker.stat().st_size, before)
            finally:
                self._force_stop_process(directory / "child.pid")
                self._force_stop_process(directory / "parent.pid")

    def test_promoted_backend_uses_practical_80_digit_policy(self):
        job = _deep_job()
        adapter = FakeAdapter()
        backend = JuliaPrecisionRootBackend(
            VettedNativeDeterminantKernel.identity, adapter, 80
        )

        readout = backend.read_root(job, complex(0.001, -0.002))

        request = adapter.requests[0]
        self.assertEqual(request["precision_digits"], 80)
        self.assertEqual(request["working_precision_bits"], 298)
        self.assertEqual(
            request["policy"]["root_correction_tolerance"], "1e-18"
        )
        self.assertEqual(request["policy"]["ode_relative_tolerance"], "1e-18")
        self.assertEqual(request["policy"]["ode_absolute_tolerance"], "1e-20")
        self.assertEqual(request["policy"]["frequency_step"], "1e-6")
        self.assertEqual(request["amplitude"], {
            "real": "0.001",
            "imaginary": "-0.002",
        })
        self.assertEqual(readout.omega, job.root.omega)
        self.assertEqual(readout.truncation_radius, 2.0e-55)
        self.assertEqual(
            set(readout.diagnostic_readouts),
            {"truncation", "resolution", "seed-path"},
        )
        self.assertTrue(readout.converged)
        self.assertEqual(backend.scientific_runtime["precision_digits"], 80)

    def test_promoted_request_binds_job_policy_and_refinement_identity(self):
        job = _deep_job()
        request = JuliaPrecisionRootBackend(
            VettedNativeDeterminantKernel.identity,
            FakeAdapter(),
            120,
            refinement=1,
        )._request(job, 0.0j)

        self.assertEqual(request["job_id"], job.job_id)
        self.assertEqual(request["leaf_id"], job.leaf_id)
        self.assertEqual(request["role"], job.role)
        self.assertEqual(
            request["job_policy_sha256"], job.policy.identity_sha256
        )
        self.assertEqual(
            request["backend_identity_sha256"],
            job.backend_identity.identity_sha256,
        )
        self.assertEqual(request["refinement_level"], 1)

    def test_promoted_policy_refines_80_without_changing_120_contract(self):
        """Catches coupling scientific solve targets to BigFloat storage digits."""

        job = _deep_job()
        adapter = FakeAdapter()
        policy80_refined = JuliaPrecisionRootBackend(
            VettedNativeDeterminantKernel.identity, adapter, 80, refinement=1
        )._request(job, 0.0j)["policy"]
        policy120 = JuliaPrecisionRootBackend(
            VettedNativeDeterminantKernel.identity, adapter, 120
        )._request(job, 0.0j)["policy"]
        policy120_refined = JuliaPrecisionRootBackend(
            VettedNativeDeterminantKernel.identity, adapter, 120, refinement=1
        )._request(job, 0.0j)["policy"]

        self.assertEqual(
            policy80_refined["root_correction_tolerance"], "1e-20"
        )
        self.assertEqual(policy80_refined["ode_relative_tolerance"], "1e-20")
        self.assertEqual(policy80_refined["ode_absolute_tolerance"], "1e-20")
        self.assertEqual(policy80_refined["frequency_step"], "1e-7")
        self.assertEqual(policy120["root_correction_tolerance"], "1e-102")
        self.assertEqual(policy120["ode_relative_tolerance"], "1e-102")
        self.assertEqual(policy120["ode_absolute_tolerance"], "1e-104")
        self.assertEqual(policy120["frequency_step"], "1e-60")
        self.assertEqual(
            policy120_refined["root_correction_tolerance"], "1e-106"
        )
        self.assertEqual(policy120_refined["ode_relative_tolerance"], "1e-106")
        self.assertEqual(policy120_refined["ode_absolute_tolerance"], "1e-108")
        self.assertEqual(policy120_refined["frequency_step"], "1e-60")

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
                response["diagnostic_roots"]["truncation"]["root_omega_re"] = self.shifted(
                    request["omega"]["real"], "0.006"
                )
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
                response["diagnostic_roots"]["truncation"]["root_omega_re"] = self.shifted(
                    request["omega"]["real"], self.displacement
                )
                return response

        job = _deep_job()
        exact_radius = Decimal(
            format(_mode_specific_branch_enclosure_radius(job), ".17g")
        )
        outside_radius = exact_radius + Decimal("1e-28")
        exact = JuliaPrecisionRootBackend(
            VettedNativeDeterminantKernel.identity,
            BoundaryAdapter(str(exact_radius), True),
            80,
        ).read_root(job, 0.0j)
        outside = JuliaPrecisionRootBackend(
            VettedNativeDeterminantKernel.identity,
            BoundaryAdapter(str(outside_radius), False),
            80,
        ).read_root(job, 0.0j)

        class ComplexBoundaryAdapter(FakeAdapter):
            def evaluate(self, request):
                response = super().evaluate(request)
                radius = Decimal(request["policy"]["branch_enclosure_radius_abs"])
                real_delta = Decimal("0.6") * radius
                imaginary_delta = Decimal("0.8") * radius
                response.update({
                    "root_omega_re": str(
                        Decimal(request["omega"]["real"]) + real_delta
                    ),
                    "root_omega_im": str(
                        Decimal(request["omega"]["imaginary"]) + imaginary_delta
                    ),
                    "root_displacement_abs": str(radius),
                })
                for raw in response["diagnostic_roots"].values():
                    raw["root_omega_re"] = response["root_omega_re"]
                    raw["root_omega_im"] = response["root_omega_im"]
                response["truncation_radius_abs"] = "0"
                response["resolution_radius_abs"] = "0"
                response["seed_path_radius_abs"] = "0"
                return response

        complex_boundary = JuliaPrecisionRootBackend(
            VettedNativeDeterminantKernel.identity,
            ComplexBoundaryAdapter(),
            80,
        ).read_root(job, 0.0j)

        self.assertEqual(exact.branch_id, job.root.branch_id)
        self.assertEqual(complex_boundary.branch_id, job.root.branch_id)
        self.assertEqual(outside.branch_id, "nonmatching-julia-continuation")
        self.assertEqual(float(outside_radius), float(exact_radius))

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

    def test_promoted_backend_rejects_diagnostic_root_displacement_forgery(self):
        class ForgedDiagnosticAdapter(FakeAdapter):
            def evaluate(self, request):
                response = super().evaluate(request)
                response["diagnostic_roots"]["resolution"]["root_omega_re"] = (
                    self.shifted(request["omega"]["real"], "0.001")
                )
                return response

        job = _deep_job()
        backend = JuliaPrecisionRootBackend(
            VettedNativeDeterminantKernel.identity,
            ForgedDiagnosticAdapter(),
            80,
        )

        with self.assertRaisesRegex(
            JuliaResponseBackendError,
            "diagnostic root evidence is inconsistent",
        ):
            backend.read_root(job, 0.0j)

    def test_promoted_sub_ulp_diagnostic_shifts_survive_response_reduction(self):
        """Catches rounding signed BigFloat control deltas into absolute roots."""

        class SubUlpDiagnosticAdapter(FakeAdapter):
            coefficient = Decimal("1e-18")

            def evaluate(self, request):
                response = super().evaluate(request)
                amplitude_real = Decimal(request["amplitude"]["real"])
                amplitude_imaginary = Decimal(request["amplitude"]["imaginary"])
                delta_real = self.coefficient * amplitude_real
                delta_imaginary = self.coefficient * amplitude_imaginary
                with localcontext() as context:
                    context.prec = 180
                    radius = (
                        delta_real * delta_real
                        + delta_imaginary * delta_imaginary
                    ).sqrt()
                response["truncation_radius_abs"] = str(radius)
                response["resolution_radius_abs"] = "0"
                response["seed_path_radius_abs"] = "0"
                for family, real_delta, imaginary_delta in (
                    ("truncation", delta_real, delta_imaginary),
                    ("resolution", Decimal(0), Decimal(0)),
                    ("seed-path", Decimal(0), Decimal(0)),
                ):
                    raw = response["diagnostic_roots"][family]
                    raw["root_omega_re"] = self.shifted(
                        request["omega"]["real"], real_delta
                    )
                    raw["root_omega_im"] = self.shifted(
                        request["omega"]["imaginary"], imaginary_delta
                    )
                return response

        job = _deep_job()
        backend = JuliaPrecisionRootBackend(
            VettedNativeDeterminantKernel.identity,
            SubUlpDiagnosticAdapter(),
            80,
        )

        def level(epsilon):
            return LadderLevel(
                epsilon=epsilon,
                real_plus=backend.read_root(job, complex(epsilon, 0.0)),
                real_minus=backend.read_root(job, complex(-epsilon, 0.0)),
                imaginary_plus=backend.read_root(job, complex(0.0, epsilon)),
                imaginary_minus=backend.read_root(job, complex(0.0, -epsilon)),
            )

        channel = _diagnostic_response_channel(
            (level(2.0e-3), level(1.0e-3)),
            "truncation",
            primary_center=0.0j,
            primary_radius=0.0,
        )

        self.assertAlmostEqual(channel, 1.0e-18, places=32)

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
        self.assertEqual(policy["ode_relative_tolerance"], "1e-20")
        self.assertEqual(policy["endpoint_series_order"], 36)
        self.assertEqual(policy["support_subinterval_count"], 512)
        self.assertEqual(policy["angular_pad"], 26)

    def test_unsuccessful_primary_omits_diagnostic_science(self):
        class PrimaryNotConvergedAdapter(FakeAdapter):
            def evaluate(self, request):
                response = super().evaluate(request)
                response.update({
                    "root_converged": False,
                    "truncation_radius_abs": None,
                    "resolution_radius_abs": None,
                    "seed_path_radius_abs": None,
                    "diagnostic_roots": {},
                    "diagnostics_skipped_reason": "PRIMARY_NOT_CONVERGED",
                })
                return response

        job = _deep_job()
        backend = JuliaPrecisionRootBackend(
            VettedNativeDeterminantKernel.identity,
            PrimaryNotConvergedAdapter(),
            80,
        )

        readout = backend.read_root(job, 0.0j)

        self.assertFalse(readout.converged)
        self.assertEqual(readout.diagnostic_readouts, {})
        self.assertIsNone(readout.truncation_radius)
        self.assertIsNone(readout.resolution_radius)
        self.assertIsNone(readout.seed_path_radius)
        self.assertEqual(
            readout.diagnostics_skipped_reason, "PRIMARY_NOT_CONVERGED"
        )

    def test_execution_resource_policy_changes_request_digest_not_scientific_identity(self):
        plan = build_campaign_plan(
            policy=NumericalPolicy(),
            backend_identity=VettedNativeDeterminantKernel.identity,
            precision_capabilities=PrecisionCapabilities((64, 80, 120)),
        )
        leaf = next(
            item
            for item in plan.leaves
            if (
                item.role == "primary"
                and item.leaf.mode_label == "221"
                and item.job.spin == 0.95
                and item.mechanism_id == "horizon-admittance"
            )
        )
        job = leaf.job
        solved_leaf_identity = scientific_computation_identity_sha256(plan, leaf)
        backend = JuliaPrecisionRootBackend(
            VettedNativeDeterminantKernel.identity, FakeAdapter(), 80
        )
        scientific_identity = (
            job.root.identity_sha256,
            job.policy.identity_sha256,
            job.backend_identity.identity_sha256,
            job.job_id,
        )

        with patch.dict(
            os.environ,
            {"KERR_QNM_JULIA_ODE_MAX_RHS_EVALUATIONS": "2000000"},
            clear=False,
        ):
            first = backend._request(job, 0.0j)
        with patch.dict(
            os.environ,
            {"KERR_QNM_JULIA_ODE_MAX_RHS_EVALUATIONS": "3000000"},
            clear=False,
        ):
            second = backend._request(job, 0.0j)

        policy = first["execution_resource"]
        self.assertEqual(
            set(policy),
            {
                "schema",
                "version",
                "worker_request_wall_clock_seconds",
                "cooperative_request_deadline_seconds",
                "homogeneous_ode_maxiters",
                "max_accepted_steps_per_homogeneous_leg",
                "max_rhs_evaluations_per_homogeneous_leg",
                "homogeneous_leg_wall_clock_seconds",
                "sha256",
            },
        )
        self.assertEqual(policy["worker_request_wall_clock_seconds"], 7200)
        self.assertLess(
            policy["cooperative_request_deadline_seconds"],
            policy["worker_request_wall_clock_seconds"],
        )
        material = {key: value for key, value in policy.items() if key != "sha256"}
        self.assertEqual(
            policy["sha256"], hashlib.sha256(canonical_json_bytes(material)).hexdigest()
        )
        self.assertNotEqual(
            hashlib.sha256(canonical_json_bytes(first)).hexdigest(),
            hashlib.sha256(canonical_json_bytes(second)).hexdigest(),
        )
        self.assertEqual(
            scientific_identity,
            (
                job.root.identity_sha256,
                job.policy.identity_sha256,
                job.backend_identity.identity_sha256,
                job.job_id,
            ),
        )
        self.assertEqual(
            solved_leaf_identity,
            scientific_computation_identity_sha256(plan, leaf),
        )
        # The backend identity already includes the Python runtime fingerprint,
        # so its exact digest legitimately differs between supported Python
        # patch releases.  The operational policy must remain absent from the
        # runtime-bound scientific identity on every platform.
        self.assertNotIn(
            b"execution_resource",
            canonical_json_bytes({
                "leaf_id": leaf.leaf_id,
                "response_job": leaf.job.to_mapping(),
                "precision_factory_identity": (
                    plan.precision_factory_identity.to_mapping()
                ),
            }),
        )
        self.assertEqual(
            leaf.leaf_id,
            "b-prime-leaf-28b8e2f139fae4ebbb839320057a127429f7a01a3cc2cac60b526815ad0e7252",
        )
        self.assertEqual(
            job.policy.identity_sha256,
            "2d7cee336c6126a11bccd652ee35e73de60837e9418476849b9026cd27bf6171",
        )

    def test_outer_timeout_override_keeps_an_inner_cooperative_deadline(self):
        backend = JuliaPrecisionRootBackend(
            VettedNativeDeterminantKernel.identity, FakeAdapter(), 80
        )
        environment = {"KERR_QNM_JULIA_REQUEST_TIMEOUT_SECONDS": "60"}

        with patch.dict(os.environ, environment, clear=True):
            policy = backend._request(_deep_job(), 0.0j)["execution_resource"]

        self.assertEqual(policy["worker_request_wall_clock_seconds"], 60)
        self.assertEqual(policy["cooperative_request_deadline_seconds"], 57)

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

    def test_failed_preflight_receipt_is_bound_to_canonical_request(self):
        job = _deep_job()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name in ("julia.exe", "Project.toml", "Manifest.toml", "worker.jl"):
                (root / name).write_text(name, encoding="ascii")
            depot = root / "depot"
            depot.mkdir()

            def runner(command, **kwargs):
                request = json.loads(
                    Path(command[-2]).read_text(encoding="utf-8")
                )
                Path(command[-1]).write_bytes(canonical_json_bytes({
                    "schema_version": 1,
                    "status": "error",
                    "error_type": "AsymptoticPrecisionError",
                    "message": "preflight rejected 80 digits",
                    "failure": {
                        "failure_code": "INSUFFICIENT_ASYMPTOTIC_PRECISION",
                        "failure_class": "CONTROL",
                        "retryable": True,
                        "precision_digits": request["precision_digits"],
                        "request_sha256": request["request_sha256"],
                        "job_id": request["job_id"],
                        "leaf_id": request["leaf_id"],
                        "role": request["role"],
                        "job_policy_sha256": request["job_policy_sha256"],
                        "backend_identity_sha256": request[
                            "backend_identity_sha256"
                        ],
                        "refinement_level": request["refinement_level"],
                        "execution_resource_policy": {
                            name: request["execution_resource"][name]
                            for name in ("schema", "version", "sha256")
                        },
                        "diagnostics": {
                            "predicted_reliable_digits": "11",
                            "required_reliable_digits": "24",
                            "asymptotic_preflight_avoided_ode": True,
                            "asymptotic_preflight_reason": (
                                "INSUFFICIENT_ASYMPTOTIC_PRECISION"
                            ),
                            "factored_homogeneous_rhs_evaluations": 0,
                            "avoided_ode_scope": (
                                "factored-homogeneous-gsn/v1"
                            ),
                        },
                    },
                }))
                return SimpleNamespace(returncode=21, stdout="", stderr="")

            adapter = JuliaResponseAdapter(
                root / "julia.exe", root, depot, root / "worker.jl", {}, runner
            )
            request = JuliaPrecisionRootBackend(
                job.backend_identity, adapter, 80
            )._request(job, 0.0j)
            with self.assertRaises(JuliaResponseBackendError) as raised:
                adapter.evaluate(request)

        failure = raised.exception.worker_failure["failure"]
        self.assertEqual(failure["request_binding"], request)
        self.assertEqual(
            failure["request_sha256"],
            hashlib.sha256(canonical_json_bytes(request)).hexdigest(),
        )

    def test_failed_preflight_worker_cannot_substitute_valid_request_digest(self):
        job = _deep_job()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name in ("julia.exe", "Project.toml", "Manifest.toml", "worker.jl"):
                (root / name).write_text(name, encoding="ascii")
            depot = root / "depot"
            depot.mkdir()

            def runner(command, **kwargs):
                request = json.loads(
                    Path(command[-2]).read_text(encoding="utf-8")
                )
                Path(command[-1]).write_bytes(canonical_json_bytes({
                    "schema_version": 1,
                    "status": "error",
                    "error_type": "AsymptoticPrecisionError",
                    "message": "forged request digest",
                    "failure": {
                        "failure_code": "INSUFFICIENT_ASYMPTOTIC_PRECISION",
                        "failure_class": "CONTROL",
                        "retryable": True,
                        "precision_digits": request["precision_digits"],
                        "request_sha256": "0" * 64,
                        "job_id": request["job_id"],
                        "leaf_id": request["leaf_id"],
                        "role": request["role"],
                        "job_policy_sha256": request["job_policy_sha256"],
                        "backend_identity_sha256": request[
                            "backend_identity_sha256"
                        ],
                        "refinement_level": request["refinement_level"],
                        "execution_resource_policy": {
                            name: request["execution_resource"][name]
                            for name in ("schema", "version", "sha256")
                        },
                        "diagnostics": {
                            "predicted_reliable_digits": "11",
                            "required_reliable_digits": "24",
                            "asymptotic_preflight_avoided_ode": True,
                            "asymptotic_preflight_reason": (
                                "INSUFFICIENT_ASYMPTOTIC_PRECISION"
                            ),
                            "factored_homogeneous_rhs_evaluations": 0,
                            "avoided_ode_scope": (
                                "factored-homogeneous-gsn/v1"
                            ),
                        },
                    },
                }))
                return SimpleNamespace(returncode=21, stdout="", stderr="")

            adapter = JuliaResponseAdapter(
                root / "julia.exe", root, depot, root / "worker.jl", {}, runner
            )
            request = JuliaPrecisionRootBackend(
                job.backend_identity, adapter, 80
            )._request(job, 0.0j)
            with self.assertRaisesRegex(
                JuliaResponseBackendError, "request identity mismatch"
            ) as raised:
                adapter.evaluate(request)

        self.assertNotIn("failure", raised.exception.worker_failure)

    def test_ode_resource_limit_receipt_is_a_typed_worker_failure(self):
        ode_snapshot = {
            "ode_solve_id": 17,
            "ode_leg": "Xup_outer_to_match",
            "ode_stats_scope": "leg",
            "ode_retcode": "MaxIters",
            "ode_rhs_evaluations": 9000001,
            "ode_accepted_steps": 120,
            "ode_rejected_steps": 9999880,
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name in ("julia.exe", "Project.toml", "Manifest.toml", "worker.jl"):
                (root / name).write_text(name, encoding="ascii")
            depot = root / "depot"
            depot.mkdir()

            def runner(command, **kwargs):
                request = json.loads(
                    Path(command[-2]).read_text(encoding="utf-8")
                )
                Path(command[-1]).write_bytes(canonical_json_bytes({
                    "schema_version": 1,
                    "status": "error",
                    "error_type": "ODEResourceLimit",
                    "message": "Xup exceeded the existing solver iteration limit",
                    "failure": {
                        "failure_code": "ODE_RESOURCE_LIMIT",
                        "failure_class": "CONTROL",
                        "limit_kind": "ode_solver_iterations",
                        "ode_snapshot": ode_snapshot,
                        "execution_resource_policy": request[
                            "execution_resource"
                        ],
                    },
                }))
                return SimpleNamespace(returncode=21, stdout="", stderr="")

            adapter = JuliaResponseAdapter(
                root / "julia.exe", root, depot, root / "worker.jl", {}, runner
            )
            with self.assertRaises(JuliaResponseBackendError) as raised:
                adapter.evaluate({"schema_version": 1})

        self.assertEqual(type(raised.exception).__name__, "JuliaODEResourceLimitError")
        self.assertEqual(
            raised.exception.worker_failure["failure"]["failure_code"],
            "ODE_RESOURCE_LIMIT",
        )
        self.assertEqual(
            raised.exception.worker_failure["failure"]["ode_snapshot"],
            ode_snapshot,
        )

    def test_root_readout_feasibility_receipt_is_a_typed_worker_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name in ("julia.exe", "Project.toml", "Manifest.toml", "worker.jl"):
                (root / name).write_text(name, encoding="ascii")
            depot = root / "depot"
            depot.mkdir()

            def runner(command, **kwargs):
                request = json.loads(
                    Path(command[-2]).read_text(encoding="utf-8")
                )
                Path(command[-1]).write_bytes(canonical_json_bytes({
                    "schema_version": 1,
                    "status": "error",
                    "error_type": "RootReadoutResourceLimit",
                    "message": "mandatory determinant work cannot fit",
                    "failure": {
                        "failure_code": "ROOT_READOUT_RESOURCE_INFEASIBLE",
                        "failure_class": "CONTROL",
                        "retryable": True,
                        "precision_digits": 80,
                        "root_phase": "PRIMARY",
                        "newton_index": 1,
                        "determinant_index": 1,
                        "measured_determinant_seconds": 1800.0,
                        "minimum_remaining_determinant_count": 8,
                        "remaining_wall_time_seconds": 5000.0,
                        "estimator": "first-determinant-linear-lower-bound/v1",
                        "execution_resource_policy": request["execution_resource"],
                    },
                }))
                return SimpleNamespace(returncode=21, stdout="", stderr="")

            adapter = JuliaResponseAdapter(
                root / "julia.exe", root, depot, root / "worker.jl", {}, runner
            )
            with self.assertRaises(JuliaResponseBackendError) as raised:
                adapter.evaluate({"schema_version": 1})

        self.assertEqual(
            type(raised.exception).__name__,
            "JuliaRootReadoutResourceLimitError",
        )
        self.assertEqual(
            raised.exception.worker_failure["failure"]["failure_code"],
            "ROOT_READOUT_RESOURCE_INFEASIBLE",
        )

    def test_control_receipt_resource_policy_mismatch_is_fatal(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name in ("julia.exe", "Project.toml", "Manifest.toml", "worker.jl"):
                (root / name).write_text(name, encoding="ascii")
            depot = root / "depot"
            depot.mkdir()

            def runner(command, **kwargs):
                request = json.loads(
                    Path(command[-2]).read_text(encoding="utf-8")
                )
                forged_identity = {
                    "schema": request["execution_resource"]["schema"],
                    "version": request["execution_resource"]["version"],
                    "sha256": "0" * 64,
                }
                Path(command[-1]).write_bytes(canonical_json_bytes({
                    "schema_version": 1,
                    "status": "error",
                    "error_type": "ODEResourceLimit",
                    "message": "forged resource identity",
                    "failure": {
                        "failure_code": "ODE_RESOURCE_LIMIT",
                        "failure_class": "CONTROL",
                        "retryable": True,
                        "precision_digits": 80,
                        "execution_resource_policy": forged_identity,
                    },
                }))
                return SimpleNamespace(returncode=21, stdout="", stderr="bounded")

            adapter = JuliaResponseAdapter(
                root / "julia.exe", root, depot, root / "worker.jl", {}, runner
            )
            with self.assertRaisesRegex(
                JuliaResponseBackendError,
                "execution-resource policy identity mismatch",
            ) as raised:
                adapter.evaluate({"schema_version": 1})

        self.assertIs(type(raised.exception), JuliaResponseBackendError)
        self.assertNotIn("failure", raised.exception.worker_failure)
        self.assertEqual(
            raised.exception.worker_failure["worker_error_type"],
            "ExecutionResourcePolicyIdentityError",
        )

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
                    last_progress_event_validated=True,
                    last_progress_event={
                        "schema": PROGRESS_SCHEMA,
                        "kind": "ode_solve_progress",
                        "context": {
                            "readout_index": 1,
                            "readout_role": "baseline",
                            "phase": "PRIMARY",
                            "newton_index": 1,
                            "determinant_index_leaf": 3,
                            "determinant_index_phase": 3,
                            "determinant_purpose": "derivative -h",
                        },
                        "payload": {
                            "ode_leg": "Xup_match_to_inner",
                            "elapsed_seconds": 1900.0,
                            "request_elapsed_seconds": 5271.5,
                            "ode_accepted_steps": 982000,
                            "ode_rejected_steps": 0,
                            "ode_rhs_evaluations": 1960000,
                        },
                    },
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

        receipt = raised.exception.worker_failure
        self.assertEqual(receipt["worker_exit_code"], -9)
        self.assertIs(receipt["worker_timed_out"], True)
        self.assertEqual(
            receipt["worker_stderr_tail"],
            "Julia worker timed out after 60 seconds\n",
        )
        self.assertEqual(receipt["failure"]["failure_code"], "WORKER_TIMEOUT")
        self.assertEqual(receipt["failure"]["failure_class"], "CONTROL")
        self.assertIs(receipt["failure"]["retryable"], True)
        self.assertEqual(receipt["failure"]["root_phase"], "PRIMARY")
        self.assertEqual(receipt["failure"]["determinant_index"], 3)
        self.assertEqual(receipt["failure"]["elapsed_request_seconds"], 5271.5)
        self.assertEqual(
            receipt["failure"]["ode_leg"], "Xup_match_to_inner"
        )
        self.assertEqual(
            receipt["failure"]["ode_snapshot"]["ode_rhs_evaluations"],
            1960000,
        )
        policy = receipt["failure"]["execution_resource_policy"]
        self.assertEqual(
            policy["schema"], "windows-solver.execution-resource-policy/1"
        )
        self.assertEqual(len(policy["sha256"]), 64)

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
