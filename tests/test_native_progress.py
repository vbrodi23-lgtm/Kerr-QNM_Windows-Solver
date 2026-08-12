from __future__ import annotations

import unittest
from unittest.mock import patch

import numpy as np

from windows_solver.contracts import canonical_json_bytes

from windows_solver.progress import ProgressEventKind, activate_progress
from windows_solver.response_engine import (
    BackendIdentity,
    NumericalPolicy,
    ResponseComponentJob,
    RootReadout,
    run_component,
)
from windows_solver.native_response_kernel import VettedNativeDeterminantKernel


LEAF_ID = (
    "b-prime-leaf-9e5777728144433e089f9559b92b6e139e16115a5a53099f40403a45297aa3c3"
)
IDENTITY = BackendIdentity(
    backend_id="progress-fixture",
    implementation_version="1",
    source_commit="0c1e8a3d3bca6e608c34e111476a4f6dcb73e86e",
    source_blobs=(("fixture", "b65f2236f828204aa21dfa8d9bc79c8a1c66ca3b"),),
    runtime_fingerprint="progress-fixture",
)


class Observer:
    def __init__(self) -> None:
        self.events = []

    def publish(self, event) -> None:
        self.events.append(event)


class LinearBackend:
    identity = IDENTITY

    def read_root(self, job, amplitude, primary_predictor=None):
        omega = job.root.omega + (0.125 - 0.375j) * amplitude
        return RootReadout(
            omega=omega,
            determinant_residual_abs=1.0e-12,
            determinant_derivative_abs=2.0,
            converged=True,
            root_reference_id=job.root.root_reference_id,
            branch_id=job.root.branch_id,
            equation_id=job.equation_id,
        )

    def closed_form_horizon_response(self, job):
        return 0.125 - 0.375j


class NativeProgressTests(unittest.TestCase):
    def test_component_emits_baseline_and_signed_readout_roles_without_reordering(self):
        job = ResponseComponentJob.from_leaf_id(
            LEAF_ID, policy=NumericalPolicy(), backend_identity=IDENTITY
        )
        observer = Observer()
        with activate_progress(observer):
            result = run_component(job, LinearBackend())

        starts = [
            event
            for event in observer.events
            if event.kind is ProgressEventKind.AMPLITUDE_READOUT_STARTED
        ]
        completions = [
            event
            for event in observer.events
            if event.kind is ProgressEventKind.AMPLITUDE_READOUT_COMPLETED
        ]
        self.assertEqual(len(starts), 17)
        self.assertEqual(len(completions), 17)
        self.assertEqual(starts[0].context.readout_role, "baseline")
        self.assertEqual(
            [event.context.readout_role for event in starts[1:5]],
            ["real-plus", "real-minus", "imaginary-plus", "imaginary-minus"],
        )
        self.assertEqual(completions[-1].payload["current_omega"], {
            "real": result.raw_readouts[-1].omega.real,
            "imaginary": result.raw_readouts[-1].omega.imag,
        })

    def test_root_evaluation_emits_four_named_phases_with_seed_and_result(self):
        class ScriptedKernel(VettedNativeDeterminantKernel):
            def __init__(self, roots):
                self.roots = iter(roots)

            def _standard_sn(self, job, policy):
                return object()

            def _solve_once(self, *, sn, job, perturbation, policy, guess):
                return next(self.roots)

        job = ResponseComponentJob.from_leaf_id(
            LEAF_ID,
            policy=NumericalPolicy(),
            backend_identity=VettedNativeDeterminantKernel.identity,
        )
        base = job.root.omega
        kernel = ScriptedKernel(tuple(
            (base + index * 1.0e-10, 1.0e-12, 2.0, True)
            for index in range(1, 5)
        ))
        observer = Observer()
        from windows_solver.response_engine import HorizonPerturbation

        with activate_progress(observer):
            kernel.evaluate_root_with_predictor_kind(
                job=job,
                background_root=job.root,
                perturbation=HorizonPerturbation(0.0j, job.spin, job.mode.m),
                policy=job.policy,
                primary_predictor=base + complex(5.0e-5, -2.0e-5),
                primary_predictor_kind="SPIN_CONTINUATION",
            )

        starts = [event for event in observer.events if event.kind is ProgressEventKind.ROOT_PHASE_STARTED]
        seeds = [event for event in observer.events if event.kind is ProgressEventKind.ROOT_SEED_SELECTED]
        completions = [event for event in observer.events if event.kind is ProgressEventKind.ROOT_PHASE_COMPLETED]
        self.assertEqual([event.context.phase for event in starts], [
            "PRIMARY", "TRUNCATION", "RESOLUTION", "SEED-PATH"
        ])
        self.assertEqual(len(seeds), 4)
        self.assertEqual(
            [event.payload["seed_kind"] for event in seeds],
            [
                "SPIN_CONTINUATION",
                "ACCEPTED_PRIMARY",
                "ACCEPTED_PRIMARY",
                "INDEPENDENT_SEED_PATH",
            ],
        )
        self.assertEqual(seeds[0].payload["requested_seed_kind"], "SPIN_CONTINUATION")
        self.assertIs(seeds[0].payload["fallback_used"], False)
        self.assertEqual(
            seeds[-1].payload["seed_omega"],
            starts[-1].context.seed_omega,
        )
        self.assertEqual(len(completions), 4)
        self.assertIsNotNone(starts[0].context.seed_omega)
        self.assertIn("resulting_omega", completions[0].payload)

    def test_failed_predictor_reports_one_primary_fallback_without_new_phase(self):
        class ScriptedKernel(VettedNativeDeterminantKernel):
            def __init__(self, roots):
                self.roots = iter(roots)

            def _standard_sn(self, job, policy):
                return object()

            def _solve_once(self, *, sn, job, perturbation, policy, guess):
                return next(self.roots)

        job = ResponseComponentJob.from_leaf_id(
            LEAF_ID,
            policy=NumericalPolicy(),
            backend_identity=VettedNativeDeterminantKernel.identity,
        )
        base = job.root.omega
        predictor = base + complex(5.0e-5, -2.0e-5)
        accepted = base + complex(1.0e-4, -4.0e-5)
        kernel = ScriptedKernel((
            (predictor, 1.0, 2.0, False),
            (accepted, 1.0e-12, 2.0, True),
            (accepted + 1.0e-10, 1.0e-12, 2.0, True),
            (accepted + 2.0e-10, 1.0e-12, 2.0, True),
            (accepted + 3.0e-10, 1.0e-12, 2.0, True),
        ))
        observer = Observer()
        from windows_solver.response_engine import HorizonPerturbation

        with activate_progress(observer):
            kernel.evaluate_root(
                job=job,
                background_root=job.root,
                perturbation=HorizonPerturbation(0.0j, job.spin, job.mode.m),
                policy=job.policy,
                primary_predictor=predictor,
            )

        starts = [
            event
            for event in observer.events
            if event.kind is ProgressEventKind.ROOT_PHASE_STARTED
        ]
        primary_seeds = [
            event
            for event in observer.events
            if event.kind is ProgressEventKind.ROOT_SEED_SELECTED
            and event.context.phase == "PRIMARY"
        ]
        primary_completion = next(
            event
            for event in observer.events
            if event.kind is ProgressEventKind.ROOT_PHASE_COMPLETED
            and event.context.phase == "PRIMARY"
        )
        self.assertEqual(len(starts), 4)
        self.assertEqual(
            [event.payload["seed_kind"] for event in primary_seeds],
            ["EPSILON_CONTINUATION", "FALLBACK_BACKGROUND"],
        )
        self.assertEqual(
            primary_seeds[-1].payload["fallback_reason"],
            "PREDICTOR_NEWTON_FAILED",
        )
        self.assertEqual(primary_completion.context.seed_kind, "FALLBACK_BACKGROUND")
        self.assertIs(primary_completion.context.fallback_used, True)

    def test_newton_payloads_reuse_exact_determinant_calls_and_report_steps(self):
        calls = []

        def determinant(omega):
            calls.append(complex(omega))
            return complex(omega) - (0.5 - 0.1j)

        observer = Observer()
        with activate_progress(observer):
            root, residual, derivative, converged = (
                VettedNativeDeterminantKernel._bounded_newton(
                    determinant, 0.5002 - 0.1j
                )
            )

        determinant_events = [
            event for event in observer.events
            if event.kind is ProgressEventKind.DETERMINANT_COMPLETED
        ]
        completed = [
            event for event in observer.events
            if event.kind is ProgressEventKind.NEWTON_ITERATION_COMPLETED
        ]
        started = [
            event for event in observer.events
            if event.kind is ProgressEventKind.NEWTON_ITERATION_STARTED
        ]
        self.assertEqual(len(determinant_events), len(calls))
        self.assertTrue(converged)
        self.assertLess(residual, 2.0e-11)
        self.assertAlmostEqual(derivative, 1.0)
        self.assertAlmostEqual(root.real, 0.5)
        self.assertTrue(started)
        self.assertEqual(started[0].payload["acceptance_threshold"], 2.0e-11)
        self.assertTrue(completed)
        payload = completed[0].payload
        for field in (
            "derivative_abs", "raw_step", "applied_step", "step_abs",
            "clipped", "damping", "accepted", "resulting_omega",
            "resulting_determinant_abs", "elapsed_seconds",
        ):
            self.assertIn(field, payload)


    def test_solve_once_emits_a_json_serializable_builtin_convergence_boolean(self):
        kernel = object.__new__(VettedNativeDeterminantKernel)
        with patch.object(
            VettedNativeDeterminantKernel,
            "_bounded_newton",
            return_value=(
                0.5 - 0.1j,
                np.float64(1.0e-15),
                np.float64(2.0),
                True,
            ),
        ):
            _, _, _, converged = kernel._solve_once(
                sn=object(),
                job=object(),
                perturbation=object(),
                policy=object(),
                guess=0.5 - 0.1j,
            )

        self.assertIs(type(converged), bool)
        self.assertEqual(
            canonical_json_bytes({"converged": converged}),
            b'{"converged":true}',
        )


if __name__ == "__main__":
    unittest.main()
