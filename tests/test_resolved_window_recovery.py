"""Recovery of a physically collapsed exterior response.

These cover the near-extremal exterior light-ring rows (220, 330 and 440 at
a/M = 0.9999), whose responses fall to roughly 1e-8 while the root error stays
near 1e-12.  The signed displacement is proportional to epsilon and the root
error is not, so the declared ladder sinks under its own noise floor at the
fine end even though the component is perfectly resolvable at a wider
amplitude.
"""

from __future__ import annotations

import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch
from dataclasses import replace

from windows_solver.response_engine import (
    AMPLITUDE_EXPANSION_RECOVERY_POLICY,
    BackendIdentity,
    ComponentResult,
    ComponentStatus,
    DiagnosticRootReadout,
    NumericalPolicy,
    ResponseComponentJob,
    RootReadout,
    _recover_resolved_window,
    _response_ladder_recovery,
    run_component,
)
from windows_solver.partial_component_checkpoint import PartialComponentJournal


EXTERIOR_LEAF_ID = (
    "b-prime-leaf-7ef38d6f95c161d0b4c6650d470898c0742ad6ae8440e89956312344c0db6aac"
)

IDENTITY = BackendIdentity(
    backend_id="test-native-determinant",
    implementation_version="1",
    source_commit="0c1e8a3d3bca6e608c34e111476a4f6dcb73e86e",
    source_blobs=(("determinant-kernel", "b65f2236f828204aa21dfa8d9bc79c8a1c66ca3b"),),
    runtime_fingerprint="cpython-test-runtime",
)

# The observed 220 row: response magnitude 3.46e-8 against a baseline Newton
# correction of 1.15e-12.
COLLAPSED_RESPONSE = complex(3.0e-8, 1.7e-8)
COLLAPSED_ROOT_NOISE = 1.15e-12
CUBIC_COEFFICIENT = complex(2.0e-4, 1.0e-4)


class CollapsedResponseBackend:
    """A component whose response is small enough to sink under root error."""

    identity = IDENTITY

    def __init__(
        self,
        response: complex = COLLAPSED_RESPONSE,
        root_noise: float = COLLAPSED_ROOT_NOISE,
        cubic: complex = CUBIC_COEFFICIENT,
    ) -> None:
        self.response = response
        self.root_noise = root_noise
        self.cubic = cubic
        self.amplitudes: list[complex] = []

    def read_root(self, job, amplitude, primary_predictor=None) -> RootReadout:
        value = complex(amplitude)
        self.amplitudes.append(value)
        return RootReadout(
            omega=job.root.omega + self.response * value + self.cubic * value**3,
            determinant_residual_abs=self.root_noise,
            determinant_derivative_abs=1.0,
            converged=True,
            root_reference_id=job.root.root_reference_id,
            branch_id=job.root.branch_id,
            equation_id=job.equation_id,
        )

    def closed_form_horizon_response(self, job) -> complex | None:
        return None

    @property
    def signed_epsilons(self) -> list[float]:
        return [abs(value) for value in self.amplitudes if value != 0.0j]


class ImaginaryAxisLimitedBackend(CollapsedResponseBackend):
    def read_root(self, job, amplitude, primary_predictor=None) -> RootReadout:
        value = complex(amplitude)
        self.amplitudes.append(value)
        response = self.response if value.real else complex(1.0e-10, 0.0)
        return RootReadout(
            omega=job.root.omega + response * value + self.cubic * value**3,
            determinant_residual_abs=self.root_noise,
            determinant_derivative_abs=1.0,
            converged=True,
            root_reference_id=job.root.root_reference_id,
            branch_id=job.root.branch_id,
            equation_id=job.equation_id,
        )


def _exterior_job() -> ResponseComponentJob:
    return ResponseComponentJob.from_leaf_id(
        EXTERIOR_LEAF_ID,
        policy=NumericalPolicy(),
        backend_identity=IDENTITY,
    )


class ResolvedWindowRecoveryTests(unittest.TestCase):
    def test_serialized_windows_use_runtime_absolute_axis_floor(self):
        base = _exterior_job()
        job = replace(
            base,
            policy=replace(base.policy, absolute_axis_floor=1.0e-9),
        )

        class SmallAxisOffset(CollapsedResponseBackend):
            def read_root(self, job, amplitude, primary_predictor=None):
                value = complex(amplitude)
                self.amplitudes.append(value)
                response = self.response + (
                    0.0j if value.real else complex(1.0e-10, 0.0)
                )
                return RootReadout(
                    omega=job.root.omega + response * value,
                    determinant_residual_abs=self.root_noise,
                    determinant_derivative_abs=1.0,
                    converged=True,
                    root_reference_id=job.root.root_reference_id,
                    branch_id=job.root.branch_id,
                    equation_id=job.equation_id,
                )

        result = run_component(
            job,
            SmallAxisOffset(
                response=complex(0.125, -0.375),
                root_noise=1.0e-16,
                cubic=0.0j,
            ),
        )
        runtime = _recover_resolved_window(job, result.levels)
        serialized = _response_ladder_recovery(job, result.levels)

        self.assertIsNotNone(runtime)
        self.assertEqual(
            serialized.selected_epsilons,
            tuple(level.epsilon for level in runtime[0]),
        )

    def test_serialized_windows_share_runtime_even_order_alternative(self):
        job = _exterior_job()

        class EvenOrderBackend(CollapsedResponseBackend):
            def read_root(self, job, amplitude, primary_predictor=None):
                value = complex(amplitude)
                self.amplitudes.append(value)
                return RootReadout(
                    omega=(
                        job.root.omega
                        + self.response * value
                        + complex(1.0e-4, -2.0e-4) * value**2
                    ),
                    determinant_residual_abs=self.root_noise,
                    determinant_derivative_abs=1.0,
                    converged=True,
                    root_reference_id=job.root.root_reference_id,
                    branch_id=job.root.branch_id,
                    equation_id=job.equation_id,
                )

        result = run_component(
            job,
            EvenOrderBackend(
                response=complex(0.125, -0.375),
                root_noise=1.0e-16,
                cubic=0.0j,
            ),
        )
        runtime = _recover_resolved_window(job, result.levels)
        serialized = _response_ladder_recovery(job, result.levels)

        self.assertIsNotNone(runtime)
        self.assertEqual(
            serialized.selected_epsilons,
            tuple(level.epsilon for level in runtime[0]),
        )
    def test_generic_component_journal_resumes_signed_and_expanded_readouts(self):
        job = _exterior_job()

        class DiagnosticBackend(CollapsedResponseBackend):
            def read_root(self, job, amplitude, primary_predictor=None):
                output = super().read_root(job, amplitude, primary_predictor)
                diagnostic = DiagnosticRootReadout(
                    omega_delta_from_primary=0.0j,
                    determinant_residual_abs=self.root_noise,
                    determinant_derivative_abs=1.0,
                    converged=True,
                )
                return replace(output, diagnostic_readouts={
                    family: diagnostic
                    for family in ("truncation", "resolution", "seed-path")
                })

        class InterruptAfterFirstSigned(DiagnosticBackend):
            def read_root(self, job, amplitude, primary_predictor=None):
                if len(self.amplitudes) == 2:
                    raise KeyboardInterrupt("synthetic interruption")
                return super().read_root(job, amplitude, primary_predictor)

        with tempfile.TemporaryDirectory() as temporary, patch.dict(
            "os.environ",
            {"KERR_QNM_PARTIAL_COMPONENT_JOURNAL_ROOT": temporary},
        ):
            interrupted = InterruptAfterFirstSigned()
            with self.assertRaises(KeyboardInterrupt):
                run_component(job, interrupted)

            journals = tuple(Path(temporary).glob("*.json"))
            self.assertEqual(len(journals), 1)
            stopped = PartialComponentJournal.load(journals[0])
            self.assertEqual(
                {entry.readout_role for entry in stopped.entries.values()},
                {"baseline", "real-plus@0.004"},
            )

            resumed = DiagnosticBackend()
            result = run_component(job, resumed)

            self.assertEqual(result.status, ComponentStatus.CONVERGED)
            self.assertNotIn(0.0j, resumed.amplitudes)
            self.assertNotIn(complex(0.004, 0.0), resumed.amplitudes)
            self.assertIn(complex(0.008, 0.0), resumed.amplitudes)
            final = PartialComponentJournal.load(journals[0])
            roles = {entry.readout_role for entry in final.entries.values()}
            self.assertIn("real-plus@0.008", roles)
            self.assertIn("imaginary-minus@0.008", roles)
            first_signed = next(
                entry for entry in final.entries.values()
                if entry.readout_role == "real-plus@0.004"
            )
            self.assertEqual(
                first_signed.worker_response_receipt["kind"], "root-readout"
            )
            self.assertIn(
                "diagnostic_readouts",
                first_signed.worker_response_receipt["output"],
            )

    def test_production_recovery_serializes_only_failing_axis_pair_promotion(self):
        job = _exterior_job()
        backend = ImaginaryAxisLimitedBackend(
            response=complex(0.125, -0.375), cubic=0.0j
        )

        result = run_component(job, backend)

        self.assertEqual(result.status, ComponentStatus.AXIS_MISMATCH)
        recovery = result.resolved_window
        self.assertIsNotNone(recovery)
        self.assertEqual(recovery["recovery_disposition"], "PROMOTE_READOUTS")
        self.assertEqual(recovery["next_precision_tier"], "bigfloat-40")
        self.assertEqual(recovery["exact_added_epsilons"], [0.008, 0.016])
        self.assertTrue(recovery["candidate_windows"])
        self.assertTrue(recovery["signal_noise_ratios"])
        self.assertTrue(recovery["window_diagnostics"])
        self.assertTrue(recovery["branch_margins"])
        plan = recovery["readout_specific_promotion_plan"]
        self.assertTrue(plan)
        self.assertEqual(
            {item["readout_role"] for item in plan},
            {"imaginary_plus", "imaginary_minus"},
        )
        self.assertNotIn("real_plus", {item["readout_role"] for item in plan})

    def test_collapsed_response_recovers_by_widening_the_amplitude(self):
        """The 0.9999 light-ring rows must resolve instead of returning noise."""

        job = _exterior_job()
        backend = CollapsedResponseBackend()

        result = run_component(job, backend)

        self.assertEqual(result.status, ComponentStatus.CONVERGED)
        self.assertIsNotNone(result.response)
        self.assertAlmostEqual(
            result.response.real, COLLAPSED_RESPONSE.real, delta=1.0e-10
        )
        self.assertAlmostEqual(
            result.response.imag, COLLAPSED_RESPONSE.imag, delta=1.0e-10
        )

        window = result.resolved_window
        self.assertIsNotNone(window)
        self.assertEqual(window["policy"], AMPLITUDE_EXPANSION_RECOVERY_POLICY)
        # The widened amplitude carries the estimate and the level that sank
        # under the noise floor is named as excluded rather than silently kept.
        self.assertIn(0.008, window["included_epsilons"])
        self.assertIn(0.0005, window["excluded_epsilons"])
        self.assertNotIn(0.0005, window["included_epsilons"])

    def test_widened_amplitudes_are_actually_read_from_the_backend(self):
        """Guards against recording an expansion that never ran."""

        job = _exterior_job()
        backend = CollapsedResponseBackend()

        run_component(job, backend)

        self.assertIn(0.008, backend.signed_epsilons)
        self.assertGreater(max(backend.signed_epsilons), max(job.policy.epsilons))

    def test_healthy_component_keeps_the_declared_ladder_untouched(self):
        """A component with real signal must not pay for the recovery path."""

        job = _exterior_job()
        backend = CollapsedResponseBackend(response=complex(0.125, -0.375))

        result = run_component(job, backend)

        self.assertEqual(result.status, ComponentStatus.CONVERGED)
        self.assertIsNone(result.resolved_window)
        self.assertEqual(len(backend.amplitudes), 17)
        self.assertLessEqual(max(backend.signed_epsilons), max(job.policy.epsilons))

    def test_response_under_every_amplitude_stays_fail_closed(self):
        """Recovery must not manufacture a result the evidence cannot support."""

        job = _exterior_job()
        backend = CollapsedResponseBackend(response=complex(1.0e-10, 0.0))

        result = run_component(job, backend)

        self.assertEqual(result.status, ComponentStatus.NOISE_FLOOR)
        self.assertIsNone(result.response)
        self.assertFalse(result.usable)
        self.assertEqual(result.convergence_basis, "UNRESOLVED")

    def test_resolved_window_survives_the_component_mapping_round_trip(self):
        """The exclusion record has to reach the campaign checkpoint intact."""

        job = _exterior_job()
        result = run_component(job, CollapsedResponseBackend())

        restored = ComponentResult.from_mapping(result.to_mapping())

        self.assertEqual(
            dict(restored.resolved_window), dict(result.resolved_window)
        )

    def test_every_readout_stays_in_the_evidence_record(self):
        """Excluding a level from the estimate must not delete its evidence."""

        job = _exterior_job()
        backend = CollapsedResponseBackend()

        result = run_component(job, backend)

        recorded = [level.epsilon for level in result.levels]
        self.assertIn(0.0005, recorded)
        self.assertIn(0.008, recorded)
        self.assertEqual(result.finite_amplitude_readout_count, 4 * len(recorded))


if __name__ == "__main__":
    unittest.main()
