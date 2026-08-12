from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from windows_solver.linear_response import (
    B_PRIME_RELEASE_DOMAIN,
    LINEAR_RESPONSE_DESCRIPTOR,
)
from windows_solver.response_engine import (
    BackendIdentity,
    ComponentStatus,
    DeterminantPartials,
    ExteriorPerturbation,
    HorizonPerturbation,
    NativeDeterminantAdapter,
    NumericalPolicy,
    ResponseComponentJob,
    RootReadout,
    build_response_plan,
    root_readout_preserves_authenticated_branch,
    run_component,
    run_response_plan,
    validate_response_checkpoint,
)
import windows_solver.response_engine as response_engine


HEAD_LEAF_ID = (
    "b-prime-leaf-9e5777728144433e089f9559b92b6e139e16115a5a53099f40403a45297aa3c3"
)
EXTERIOR_LEAF_ID = (
    "b-prime-leaf-7ef38d6f95c161d0b4c6650d470898c0742ad6ae8440e89956312344c0db6aac"
)
DEEP_LEAF_ID = (
    "b-prime-leaf-fc945cdbf25233004c8c36973c3ce1d1fd824c524b2e3cf36f7962dbe12c7e16"
)


IDENTITY = BackendIdentity(
    backend_id="test-native-determinant",
    implementation_version="1",
    source_commit="0c1e8a3d3bca6e608c34e111476a4f6dcb73e86e",
    source_blobs=(("determinant-kernel", "b65f2236f828204aa21dfa8d9bc79c8a1c66ca3b"),),
    runtime_fingerprint="cpython-test-runtime",
)


class AnalyticKernel:
    """Complete deterministic kernel double for the injected native boundary."""

    def __init__(
        self,
        *,
        response: complex = 0.125 - 0.375j,
        failure: str | None = None,
        fail_leaf_id: str | None = None,
    ) -> None:
        self.response = response
        self.failure = failure
        self.fail_leaf_id = fail_leaf_id
        self.calls: list[object] = []

    def evaluate_root(
        self,
        *,
        job,
        background_root,
        perturbation,
        policy,
        primary_predictor=None,
    ):
        self.calls.append(perturbation)
        if self.fail_leaf_id == job.leaf_id:
            raise RuntimeError("intentional interruption")
        amplitude = perturbation.amplitude
        response = self.response
        if self.failure == "axis" and amplitude.imag:
            response = -2.0 * response
        omega = background_root.omega + response * amplitude + (0.2 + 0.1j) * amplitude**3
        residual = 1.0e-12
        if self.failure == "noise":
            residual = 1.0
        return RootReadout(
            omega=omega,
            determinant_residual_abs=residual,
            determinant_derivative_abs=2.0,
            converged=self.failure != "not-converged",
            root_reference_id=background_root.root_reference_id,
            branch_id=(
                "wrong-branch"
                if self.failure == "branch"
                else background_root.branch_id
            ),
            equation_id=job.equation_id,
        )

    def horizon_partials(self, *, job, background_root, policy):
        return DeterminantPartials(
            frequency_derivative=2.0 + 0.0j,
            coordinate_derivative=-2.0 * self.response,
            simple_root_valid=True,
        )


class NewtonCorrectionGateTests(unittest.TestCase):
    def test_scaled_residual_converges_on_small_newton_correction_before_damping(self):
        """Catches treating determinant normalization as root-location error."""

        derivative = 36.1
        residual = 3.50e-11
        calls: list[complex] = []

        def determinant(omega: complex) -> complex:
            calls.append(complex(omega))
            return residual + derivative * complex(omega)

        root, observed_residual, observed_derivative, converged = (
            response_engine.VettedNativeDeterminantKernel._bounded_newton(
                determinant, 0.0j
            )
        )

        self.assertTrue(converged)
        self.assertEqual(root, 0.0j)
        self.assertAlmostEqual(observed_residual, residual, places=22)
        self.assertAlmostEqual(observed_derivative, derivative, places=9)
        self.assertLess(residual / derivative, 2.0e-11)
        self.assertEqual(len(calls), 4)

    def test_solve_once_reuses_derivative_that_accepted_the_same_root(self):
        """Catches recomputing the accepted phase derivative for its receipt."""

        derivative = 36.1
        residual = 3.50e-11

        class CountingKernel(response_engine.VettedNativeDeterminantKernel):
            def __init__(self):
                self.calls: list[complex] = []

            def _determinant(self, sn, omega, perturbation, policy):
                self.calls.append(complex(omega))
                return residual + derivative * complex(omega)

        kernel = CountingKernel()
        root, observed_residual, observed_derivative, converged = (
            kernel._solve_once(
                sn=object(),
                job=object(),
                perturbation=object(),
                policy=NumericalPolicy(),
                guess=0.0j,
            )
        )

        self.assertTrue(converged)
        self.assertEqual(root, 0.0j)
        self.assertAlmostEqual(observed_residual, residual, places=22)
        self.assertAlmostEqual(observed_derivative, derivative, places=9)
        self.assertEqual(len(kernel.calls), 4)

class PredictorRecordingBackend:
    identity = IDENTITY

    def __init__(self) -> None:
        self.response = 0.125 - 0.375j
        self.calls: list[tuple[complex, complex | None]] = []
        self.predictor_kinds: list[str] = []

    def read_root(
        self,
        job: ResponseComponentJob,
        amplitude: complex,
        primary_predictor: complex | None = None,
    ) -> RootReadout:
        value = complex(amplitude)
        self.calls.append((value, primary_predictor))
        omega = (
            job.root.omega
            + self.response * value
            + (0.2 + 0.1j) * value**3
        )
        return RootReadout(
            omega=omega,
            determinant_residual_abs=1.0e-12,
            determinant_derivative_abs=2.0,
            converged=True,
            root_reference_id=job.root.root_reference_id,
            branch_id=job.root.branch_id,
            equation_id=job.equation_id,
        )

    def read_root_with_predictor_kind(
        self,
        job: ResponseComponentJob,
        amplitude: complex,
        primary_predictor: complex,
        primary_predictor_kind: str,
    ) -> RootReadout:
        self.predictor_kinds.append(primary_predictor_kind)
        return self.read_root(job, amplitude, primary_predictor)

    def closed_form_horizon_response(
        self, job: ResponseComponentJob
    ) -> complex | None:
        return None


class LinearResponseEngineTests(unittest.TestCase):
    def test_coarse_signed_readouts_predict_from_previous_spin_response(
        self,
    ) -> None:
        """Catches seeding a new spin from its predecessor's absolute root."""

        job = ResponseComponentJob.from_leaf_id(
            EXTERIOR_LEAF_ID,
            policy=NumericalPolicy(),
            backend_identity=IDENTITY,
        )
        backend = PredictorRecordingBackend()
        previous_response = complex(-0.75, 0.25)

        result = run_component(
            job,
            backend,
            response_predictor=previous_response,
        )

        self.assertEqual(result.status, ComponentStatus.CONVERGED)
        self.assertEqual(backend.calls[0], (0.0j, None))
        for amplitude, predictor in backend.calls[1:5]:
            self.assertEqual(
                predictor,
                job.root.omega + amplitude * previous_response,
            )
        self.assertEqual(
            backend.predictor_kinds,
            ["SPIN_CONTINUATION"] * 4 + ["EPSILON_CONTINUATION"] * 12,
        )

    def test_finer_epsilon_readouts_continue_independently_along_each_signed_ray(
        self,
    ) -> None:
        """Catches restarting every signed PRIMARY solve from the background."""

        job = ResponseComponentJob.from_leaf_id(
            EXTERIOR_LEAF_ID,
            policy=NumericalPolicy(),
            backend_identity=IDENTITY,
        )
        original_job_id = job.job_id
        backend = PredictorRecordingBackend()

        result = run_component(job, backend)

        self.assertEqual(result.status, ComponentStatus.CONVERGED)
        self.assertEqual(job.job_id, original_job_id)
        self.assertEqual(len(backend.calls), 17)
        self.assertEqual(backend.calls[0], (0.0j, None))
        rays = (1.0 + 0.0j, -1.0 + 0.0j, 0.0 + 1.0j, 0.0 - 1.0j)
        previous_roots: dict[complex, tuple[float, complex]] = {}
        call_index = 1
        for level_index, epsilon in enumerate(job.policy.epsilons[:4]):
            for ray in rays:
                amplitude, predictor = backend.calls[call_index]
                self.assertEqual(amplitude, ray * epsilon)
                if level_index == 0:
                    self.assertIsNone(predictor)
                else:
                    prior_epsilon, prior_root = previous_roots[ray]
                    expected = job.root.omega + (epsilon / prior_epsilon) * (
                        prior_root - job.root.omega
                    )
                    self.assertEqual(predictor, expected)
                previous_roots[ray] = (epsilon, result.levels[level_index].__getattribute__(
                    {
                        1.0 + 0.0j: "real_plus",
                        -1.0 + 0.0j: "real_minus",
                        0.0 + 1.0j: "imaginary_plus",
                        0.0 - 1.0j: "imaginary_minus",
                    }[ray]
                ).omega)
                call_index += 1

    def test_native_kernel_requires_variant_radii_and_branch_continuation(self) -> None:
        """Catches a tiny local correction overriding independent-path disagreement."""

        kernel_type = response_engine.VettedNativeDeterminantKernel

        class ScriptedKernel(kernel_type):
            def __init__(self, roots):
                self.roots = iter(roots)
                self.calls = []

            def _standard_sn(self, job, policy):
                return object()

            def _solve_once(self, *, sn, job, perturbation, policy, guess):
                self.calls.append((policy, guess))
                return next(self.roots)

        job = ResponseComponentJob.from_leaf_id(
            EXTERIOR_LEAF_ID,
            policy=NumericalPolicy(),
            backend_identity=kernel_type.identity,
        )
        perturbation = ExteriorPerturbation(
            0.001 + 0.0j,
            "fixed-r3",
            response_engine._exterior_support(job.spin, job.mechanism_id),
        )
        base = job.root.omega
        matching = ScriptedKernel((
            (base + 1.0e-4, 1.0e-12, 2.0, True),
            (base + 1.0e-4 + 1.0e-9, 1.0e-12, 2.0, True),
            (base + 1.0e-4 + 2.0e-9, 1.0e-12, 2.0, True),
            (base + 1.0e-4 + 3.0e-9, 1.0e-12, 2.0, True),
        ))
        readout = matching.evaluate_root(
            job=job,
            background_root=job.root,
            perturbation=perturbation,
            policy=job.policy,
        )
        self.assertTrue(readout.converged)
        self.assertAlmostEqual(readout.truncation_radius, 1.0e-9, places=15)
        self.assertAlmostEqual(readout.resolution_radius, 2.0e-9, places=15)
        self.assertAlmostEqual(readout.seed_path_radius, 3.0e-9, places=15)
        self.assertEqual(len(matching.calls), 4)
        self.assertGreater(
            matching.calls[1][0].endpoint_series_order,
            matching.calls[0][0].endpoint_series_order,
        )
        self.assertLess(
            matching.calls[2][0].ode_relative_tolerance,
            matching.calls[0][0].ode_relative_tolerance,
        )
        self.assertNotEqual(matching.calls[3][1], matching.calls[0][1])

        nonmatching = ScriptedKernel((
            (base + 1.0e-4, 1.0e-12, 2.0, True),
            (base + 1.0e-4 + 1.0e-9, 1.0e-12, 2.0, True),
            (base + 1.0e-4 + 2.0e-9, 1.0e-12, 2.0, True),
            (base + 0.1, 1.0e-12, 2.0, True),
        ))
        rejected = nonmatching.evaluate_root(
            job=job,
            background_root=job.root,
            perturbation=perturbation,
            policy=job.policy,
        )
        self.assertFalse(rejected.converged)
        self.assertLess(1.0e-12 / 2.0, 2.0e-11)
        self.assertEqual(rejected.branch_id, "nonmatching-native-continuation")

    def test_native_nonconvergence_preserves_authenticated_branch(self) -> None:
        """Catches relabelling an in-radius numerical failure as branch loss."""

        kernel_type = response_engine.VettedNativeDeterminantKernel

        class ScriptedKernel(kernel_type):
            def __init__(self, roots):
                self.roots = iter(roots)

            def _standard_sn(self, job, policy):
                return object()

            def _solve_once(self, *, sn, job, perturbation, policy, guess):
                return next(self.roots)

        job = ResponseComponentJob.from_leaf_id(
            EXTERIOR_LEAF_ID,
            policy=NumericalPolicy(),
            backend_identity=kernel_type.identity,
        )
        perturbation = ExteriorPerturbation(
            0.0j,
            "fixed-r3",
            response_engine._exterior_support(job.spin, job.mechanism_id),
        )
        base = job.root.omega
        root = base + 1.0e-4
        kernel = ScriptedKernel((
            (root, 5.0e-11, 2.0, False),
            (root + 1.0e-9, 1.0e-12, 2.0, True),
            (root + 2.0e-9, 1.0e-12, 2.0, True),
            (root + 3.0e-9, 1.0e-12, 2.0, True),
        ))

        readout = kernel.evaluate_root(
            job=job,
            background_root=job.root,
            perturbation=perturbation,
            policy=job.policy,
        )

        self.assertFalse(readout.converged)
        self.assertEqual(readout.branch_id, job.root.branch_id)
        self.assertTrue(
            root_readout_preserves_authenticated_branch(
                readout,
                job.root,
                equation_id=job.equation_id,
                source_root_mapping=job.source_root_mapping,
            )
        )

        large_correction = replace(
            readout,
            determinant_residual_abs=6.0e-3,
            determinant_derivative_abs=1.0,
        )
        self.assertEqual(large_correction.branch_id, job.root.branch_id)
        self.assertFalse(
            root_readout_preserves_authenticated_branch(
                large_correction,
                job.root,
                equation_id=job.equation_id,
                source_root_mapping=job.source_root_mapping,
            )
        )

    def test_native_primary_uses_in_branch_predictor_without_preflight_and_keeps_seed_path_independent(
        self,
    ) -> None:
        """Catches predictor preflight determinants or predictor-fed SEED-PATH."""

        kernel_type = response_engine.VettedNativeDeterminantKernel

        class ScriptedKernel(kernel_type):
            def __init__(self, roots):
                self.roots = iter(roots)
                self.calls = []

            def _standard_sn(self, job, policy):
                return object()

            def _determinant(self, *args, **kwargs):
                raise AssertionError("predictor admission must not preflight determinants")

            def _solve_once(self, *, sn, job, perturbation, policy, guess):
                self.calls.append((policy, guess))
                return next(self.roots)

        job = ResponseComponentJob.from_leaf_id(
            EXTERIOR_LEAF_ID,
            policy=NumericalPolicy(),
            backend_identity=kernel_type.identity,
        )
        base = job.root.omega
        predictor = base + complex(5.0e-5, -2.0e-5)
        primary = base + complex(1.0e-4, -4.0e-5)
        kernel = ScriptedKernel((
            (primary, 1.0e-12, 2.0, True),
            (primary + 1.0e-9, 1.0e-12, 2.0, True),
            (primary + 2.0e-9, 1.0e-12, 2.0, True),
            (primary + 3.0e-9, 1.0e-12, 2.0, True),
        ))
        perturbation = ExteriorPerturbation(
            0.001 + 0.0j,
            "fixed-r3",
            response_engine._exterior_support(job.spin, job.mechanism_id),
        )

        readout = kernel.evaluate_root(
            job=job,
            background_root=job.root,
            perturbation=perturbation,
            policy=job.policy,
            primary_predictor=predictor,
        )

        self.assertTrue(readout.converged)
        self.assertEqual(kernel.calls[0][1], predictor)
        self.assertEqual(kernel.calls[1][1], primary)
        self.assertEqual(kernel.calls[2][1], primary)
        expected_seed_path = base + complex(2.5e-4, 1.25e-4) * (1.0 + abs(base))
        self.assertEqual(kernel.calls[3][1], expected_seed_path)

    def test_native_primary_falls_back_before_work_or_after_failed_predictor(self) -> None:
        """Catches losing the authenticated-background recovery path."""

        kernel_type = response_engine.VettedNativeDeterminantKernel

        class ScriptedKernel(kernel_type):
            def __init__(self, roots):
                self.roots = iter(roots)
                self.guesses = []

            def _standard_sn(self, job, policy):
                return object()

            def _solve_once(self, *, sn, job, perturbation, policy, guess):
                self.guesses.append(guess)
                result = next(self.roots)
                if isinstance(result, Exception):
                    raise result
                return result

        job = ResponseComponentJob.from_leaf_id(
            EXTERIOR_LEAF_ID,
            policy=NumericalPolicy(),
            backend_identity=kernel_type.identity,
        )
        base = job.root.omega
        primary = base + 1.0e-4
        perturbation = ExteriorPerturbation(
            0.001 + 0.0j,
            "fixed-r3",
            response_engine._exterior_support(job.spin, job.mechanism_id),
        )
        outside = ScriptedKernel(tuple(
            (primary + index * 1.0e-9, 1.0e-12, 2.0, True)
            for index in range(4)
        ))
        outside.evaluate_root(
            job=job,
            background_root=job.root,
            perturbation=perturbation,
            policy=job.policy,
            primary_predictor=base + 0.1,
        )
        self.assertEqual(outside.guesses[0], base)

        predictor = base + 5.0e-5
        failed = ScriptedKernel((
            (predictor, 1.0, 2.0, False),
            (primary, 1.0e-12, 2.0, True),
            (primary + 1.0e-9, 1.0e-12, 2.0, True),
            (primary + 2.0e-9, 1.0e-12, 2.0, True),
            (primary + 3.0e-9, 1.0e-12, 2.0, True),
        ))
        recovered = failed.evaluate_root(
            job=job,
            background_root=job.root,
            perturbation=perturbation,
            policy=job.policy,
            primary_predictor=predictor,
        )
        self.assertTrue(recovered.converged)
        self.assertEqual(failed.guesses[:2], [predictor, base])

        errored = ScriptedKernel((
            RuntimeError("predictor-local determinant failure"),
            (primary, 1.0e-12, 2.0, True),
            (primary + 1.0e-9, 1.0e-12, 2.0, True),
            (primary + 2.0e-9, 1.0e-12, 2.0, True),
            (primary + 3.0e-9, 1.0e-12, 2.0, True),
        ))
        recovered_after_error = errored.evaluate_root(
            job=job,
            background_root=job.root,
            perturbation=perturbation,
            policy=job.policy,
            primary_predictor=predictor,
        )
        self.assertTrue(recovered_after_error.converged)
        self.assertEqual(errored.guesses[:2], [predictor, base])

    def test_vetted_native_kernel_profiles_and_missing_cache_fail_before_work(self) -> None:
        """Catches shipping only a Protocol or six support labels without kernels."""

        kernel_type = getattr(response_engine, "VettedNativeDeterminantKernel", None)
        unavailable_type = getattr(response_engine, "NativeResourceUnavailableError", None)
        self.assertIsNotNone(kernel_type)
        self.assertIsNotNone(unavailable_type)
        self.assertEqual(
            kernel_type.identity.source_commit,
            "0c1e8a3d3bca6e608c34e111476a4f6dcb73e86e",
        )
        self.assertEqual(kernel_type.identity.implementation_version, "3")
        self.assertIn(
            "adapted-source-native-gsn-adapter-contract-2",
            kernel_type.identity.runtime_fingerprint,
        )
        self.assertIn("python-64bit", kernel_type.identity.runtime_fingerprint)
        self.assertIn(
            "gsn-input-julia-exact-f-u-cache-contract-1",
            kernel_type.identity.runtime_fingerprint,
        )
        for mechanism_id in (
            "exterior-fixed-r3",
            "exterior-light-ring",
            "exterior-throat-kappa",
            "exterior-alpha-zero",
            "exterior-alpha-half",
            "exterior-alpha-one",
        ):
            perturbation = ExteriorPerturbation(
                1.0 + 0.0j,
                mechanism_id.removeprefix("exterior-"),
                response_engine._exterior_support(0.95, mechanism_id),
            )
            self.assertEqual(perturbation.profile_value(perturbation.support.centre), 1.0)
            self.assertEqual(perturbation.profile_value(perturbation.support.lower), 0.0)
        with tempfile.TemporaryDirectory() as temporary:
            missing = Path(temporary) / "gsn-infinity-series.fixture"
            with self.assertRaisesRegex(
                unavailable_type, "authenticated GSN infinity-series resource is absent"
            ):
                kernel_type.from_generated_resource(missing, "0" * 64)

    def test_native_equation_source_identity_is_structural_not_sha_gated(self) -> None:
        """A readable contract-compatible source edit must remain executable."""

        from windows_solver import _native_gsn_equations as equations

        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "Potentials.jl"
            source.write_bytes(equations.POTENTIALS_SOURCE.read_bytes() + b"\n")
            with patch.object(equations, "POTENTIALS_SOURCE", source):
                expression = equations._julia_branch_expression("sF", "sU")

        self.assertIn("omega", expression)

    def test_job_resolves_direct_and_source_coordinate_roots_through_owner(self) -> None:
        """Catches jobs substituting a caller-provided root or losing M-kappa lineage."""

        direct = ResponseComponentJob.from_leaf_id(
            HEAD_LEAF_ID, policy=NumericalPolicy(), backend_identity=IDENTITY
        )
        deep = ResponseComponentJob.from_leaf_id(
            DEEP_LEAF_ID, policy=NumericalPolicy(), backend_identity=IDENTITY
        )
        self.assertEqual(direct.sampling_coordinate.coordinate_id, "a_over_M")
        self.assertEqual(direct.sampling_coordinate.exact, (19, 20))
        self.assertEqual(deep.sampling_coordinate.coordinate_id, "M-kappa")
        self.assertEqual(deep.sampling_coordinate.exact, (1, 1000))
        self.assertEqual(direct.root.spin_binary64_hex, float(19 / 20).hex())
        self.assertEqual(deep.root.spin_binary64_hex, deep.spin.hex())
        self.assertEqual(direct.root.branch_id, "schwarzschild-overtone-continuation")
        self.assertEqual(len(direct.root.identity_sha256), 64)

    def test_native_horizon_and_exterior_use_one_refinement_boundary(self) -> None:
        """Catches a path bypassing complex axes, Richardson, or raw readout capture."""

        for leaf_id, perturbation_type in (
            (HEAD_LEAF_ID, HorizonPerturbation),
            (EXTERIOR_LEAF_ID, ExteriorPerturbation),
        ):
            with self.subTest(leaf_id=leaf_id):
                kernel = AnalyticKernel()
                job = ResponseComponentJob.from_leaf_id(
                    leaf_id, policy=NumericalPolicy(), backend_identity=IDENTITY
                )
                result = run_component(job, NativeDeterminantAdapter(IDENTITY, kernel))
                self.assertEqual(result.status, ComponentStatus.CONVERGED)
                self.assertAlmostEqual(result.response.real, kernel.response.real, places=11)
                self.assertAlmostEqual(result.response.imag, kernel.response.imag, places=11)
                self.assertEqual(len(result.levels), 4)
                self.assertEqual(len(result.raw_readouts), 17)
                self.assertTrue(all(isinstance(item, perturbation_type) for item in kernel.calls))
                self.assertEqual(
                    set(result.error_channels),
                    {"signed-root", "truncation", "resolution", "seed-path", "axis", "amplitude"},
                )
                if leaf_id == HEAD_LEAF_ID:
                    self.assertEqual(result.closed_form_response, kernel.response)
                    self.assertIsNotNone(result.signed_root_crosscheck)

    def test_all_six_exterior_profiles_dispatch_native_unit_complex_amplitude(self) -> None:
        """Catches a declared exterior mechanism falling through to a stub or alias."""

        expected = {
            "exterior-fixed-r3": "fixed-r3",
            "exterior-light-ring": "light-ring",
            "exterior-throat-kappa": "throat-kappa",
            "exterior-alpha-zero": "alpha-zero",
            "exterior-alpha-half": "alpha-half",
            "exterior-alpha-one": "alpha-one",
        }
        template_leaf = next(
            leaf
            for leaf in B_PRIME_RELEASE_DOMAIN.production_leaves
            if (
                leaf.role == "primary"
                and leaf.mode_label == "220"
                and leaf.spin == 0.95
                and leaf.mechanism_id == "exterior-fixed-r3"
            )
        )
        template = ResponseComponentJob.from_leaf_id(
            template_leaf.leaf_id,
            policy=NumericalPolicy(),
            backend_identity=IDENTITY,
        )
        for mechanism_id, profile_id in expected.items():
            with self.subTest(mechanism_id=mechanism_id):
                kernel = AnalyticKernel()
                job = replace(template, mechanism_id=mechanism_id)
                adapter = NativeDeterminantAdapter(IDENTITY, kernel)
                adapter.read_root(job, 1.0j)
                perturbation = kernel.calls[-1]
                self.assertIsInstance(perturbation, ExteriorPerturbation)
                self.assertEqual(perturbation.profile_id, profile_id)
                self.assertEqual(perturbation.amplitude, 1.0j)
                self.assertGreater(perturbation.support.lower, 1.0)
                self.assertLess(perturbation.support.lower, perturbation.support.centre)
                self.assertLess(perturbation.support.centre, perturbation.support.upper)

    def test_unresolved_gates_never_fabricate_a_response(self) -> None:
        """Catches noise, axis, branch, or solve failures being serialized as centres."""

        expected = {
            "noise": ComponentStatus.NOISE_FLOOR,
            "axis": ComponentStatus.AXIS_MISMATCH,
            "branch": ComponentStatus.BRANCH_LOSS,
            "not-converged": ComponentStatus.NOT_CONVERGED,
        }
        for failure, status in expected.items():
            with self.subTest(failure=failure):
                kernel = AnalyticKernel(failure=failure)
                job = ResponseComponentJob.from_leaf_id(
                    EXTERIOR_LEAF_ID,
                    policy=NumericalPolicy(),
                    backend_identity=IDENTITY,
                )
                result = run_component(job, NativeDeterminantAdapter(IDENTITY, kernel))
                self.assertEqual(result.status, status)
                self.assertIsNone(result.response)
                self.assertFalse(result.usable)

    def test_policy_requires_four_levels_and_positive_fit_dof(self) -> None:
        """Catches regression to an exactly determined three-point quartic ladder."""

        with self.assertRaisesRegex(ValueError, "at least four"):
            NumericalPolicy(epsilons=(0.004, 0.002, 0.001))
        policy = NumericalPolicy()
        self.assertGreaterEqual(len(policy.epsilons), 4)
        self.assertGreaterEqual(len(policy.epsilons) - 2, 2)

    def test_checkpoint_cold_resume_zero_work_and_tamper_are_strict(self) -> None:
        """Catches stale/tampered results or a complete cache invoking backend work."""

        policy = NumericalPolicy()
        plan = build_response_plan(
            (HEAD_LEAF_ID, EXTERIOR_LEAF_ID),
            policy=policy,
            backend_identity=IDENTITY,
        )
        with tempfile.TemporaryDirectory() as temporary:
            checkpoint = Path(temporary) / "cohort.json"
            first_kernel = AnalyticKernel()
            cold = run_response_plan(
                plan,
                NativeDeterminantAdapter(IDENTITY, first_kernel),
                checkpoint,
                resume=False,
            )
            self.assertEqual((cold.executed_count, cold.reused_count), (2, 0))

            warm_kernel = AnalyticKernel()
            warm = run_response_plan(
                plan,
                NativeDeterminantAdapter(IDENTITY, warm_kernel),
                checkpoint,
                resume=True,
            )
            self.assertEqual((warm.executed_count, warm.reused_count), (0, 2))
            self.assertEqual(warm_kernel.calls, [])
            validated = validate_response_checkpoint(plan, checkpoint)
            self.assertEqual(validated.reused_count, 2)

            tampered = json.loads(checkpoint.read_text(encoding="utf-8"))
            tampered["results"][0]["response"]["real"] += 1.0e-6
            checkpoint.write_text(json.dumps(tampered), encoding="utf-8")
            rejecting_kernel = AnalyticKernel()
            with self.assertRaisesRegex(ValueError, "results digest"):
                run_response_plan(
                    plan,
                    NativeDeterminantAdapter(IDENTITY, rejecting_kernel),
                    checkpoint,
                    resume=True,
                )
            self.assertEqual(rejecting_kernel.calls, [])

    def test_partial_checkpoint_resumes_only_missing_component(self) -> None:
        """Catches resume discarding a committed component or repeating it."""

        plan = build_response_plan(
            (HEAD_LEAF_ID, EXTERIOR_LEAF_ID),
            policy=NumericalPolicy(),
            backend_identity=IDENTITY,
        )
        second_id = plan.jobs[1].leaf_id
        with tempfile.TemporaryDirectory() as temporary:
            checkpoint = Path(temporary) / "cohort.json"
            interrupted = AnalyticKernel(fail_leaf_id=second_id)
            with self.assertRaisesRegex(RuntimeError, "intentional interruption"):
                run_response_plan(
                    plan,
                    NativeDeterminantAdapter(IDENTITY, interrupted),
                    checkpoint,
                    resume=False,
                )
            partial = json.loads(checkpoint.read_text(encoding="utf-8"))
            self.assertEqual(len(partial["results"]), 1)

            resumed_kernel = AnalyticKernel()
            resumed = run_response_plan(
                plan,
                NativeDeterminantAdapter(IDENTITY, resumed_kernel),
                checkpoint,
                resume=True,
            )
            self.assertEqual((resumed.executed_count, resumed.reused_count), (1, 1))

    def test_provider_admission_remains_closed(self) -> None:
        """Catches engine availability being confused with release admission."""

        self.assertFalse(LINEAR_RESPONSE_DESCRIPTOR.available)
        self.assertEqual(LINEAR_RESPONSE_DESCRIPTOR.evidence_level, "contract-only-not-admitted")


if __name__ == "__main__":
    unittest.main()
