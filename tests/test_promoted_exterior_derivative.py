from __future__ import annotations

import hashlib
import math
from dataclasses import replace
from decimal import Decimal, localcontext
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import windows_solver.response_batches as response_batches
import windows_solver.response_engine as response_engine
from tests.test_promoted_horizon_component import (
    _promoted_baseline,
    _with_worker_receipt,
)
from tests.fixtures import synthetic_ode_error_budget
from windows_solver.contracts import canonical_json_bytes
from windows_solver.precision_tiers import PrecisionTier, working_precision_bits
from windows_solver.response_batches import (
    PrecisionCapabilities,
    StageOutcome,
    _component_stage_signed_error_channels,
    _validate_component_result,
    build_campaign_plan,
    synthetic_stage_signed_error_channels,
)
from windows_solver.root_readout_cache import runtime_identity_sha256
from windows_solver.julia_response_backend import JuliaPrecisionRootBackend
from windows_solver.promoted_control_calibration import (
    load_default_calibration_receipt,
)
from windows_solver.response_engine import (
    ComponentResult,
    ComponentStatus,
    EXTERIOR_DERIVATIVE_COMPONENT_IDENTITY,
    EXTERIOR_DERIVATIVE_RESPONSE_DISK_IDENTITY,
    FIXED_ROOT_AXIS_VALIDATION_IDENTITY,
    FULL_COMPLEX_LADDER_VALIDATION_IDENTITY,
    DerivativeAuthenticationEvidence,
    FixedRootDeterminantSample,
    NumericalPolicy,
    PromotedRootSeal,
    VettedNativeDeterminantKernel,
    _fixed_root_coordinate_derivative,
    _JournaledComponentReads,
    _JournaledPromotedExteriorBackend,
    regularised_gsn_precision_policy,
    run_promoted_exterior_component,
    run_promoted_exterior_response_from_seal,
    run_promoted_full_ladder_validation,
    run_component,
    full_ladder_validation_policy,
)
from windows_solver.response_uncertainty import ComplexDisk, exterior_response_disk
from windows_solver.partial_component_checkpoint import (
    PartialComponentJournal,
    PartialComponentWorkUnit,
)


def _primary_exterior_leaf():
    plan = build_campaign_plan(
        policy=NumericalPolicy(),
        backend_identity=VettedNativeDeterminantKernel.identity,
        precision_capabilities=PrecisionCapabilities((64, 80, 120)),
    )
    return next(
        leaf
        for leaf in plan.leaves
        if leaf.role == "primary" and leaf.mechanism_id == "exterior-light-ring"
    )


def _deep_exterior_leaf():
    plan = build_campaign_plan(
        policy=NumericalPolicy(),
        backend_identity=VettedNativeDeterminantKernel.identity,
        precision_capabilities=PrecisionCapabilities((64, 80, 120)),
    )
    return next(
        leaf
        for leaf in plan.leaves
        if (
            leaf.role == "deep"
            and leaf.mechanism_id == "exterior-light-ring"
            and leaf.job.spin < 0.9999
        )
    )


class FixedRootOnlyBackend:
    def __init__(
        self,
        job,
        baseline,
        *,
        runtime_identity: str = "f" * 64,
        sample_tier: PrecisionTier = PrecisionTier.BIGFLOAT_80,
    ) -> None:
        self.identity = job.backend_identity
        self.baseline = baseline
        self.root_amplitudes: list[complex] = []
        self.sample_amplitudes: list[complex] = []
        self.runtime_identity = runtime_identity
        self.sample_tier = sample_tier

    def read_root(self, job, amplitude, primary_predictor=None):
        self.root_amplitudes.append(complex(amplitude))
        return self.baseline

    def sample_fixed_root_determinant(
        self, job, omega, amplitude, *, readout_role
    ) -> FixedRootDeterminantSample:
        converted = complex(amplitude)
        self.sample_amplitudes.append(converted)
        request = {
            "amplitude": {"imaginary": converted.imag, "real": converted.real},
            "job_id": job.job_id,
            "leaf_id": job.leaf_id,
            "omega": {"imaginary": omega.imag, "real": omega.real},
            "readout_role": readout_role,
        }
        request_sha256 = hashlib.sha256(canonical_json_bytes(request)).hexdigest()
        derivative = 2.0 + 3.0j
        determinant = 1.0e-12 + derivative * converted
        determinant_error_text = str(1.0e-9 * max(abs(converted), 1.0e-12))
        determinant_error_decimal = Decimal(determinant_error_text)
        determinant_error_abs = float(determinant_error_decimal)
        if Decimal.from_float(determinant_error_abs) < determinant_error_decimal:
            determinant_error_abs = math.nextafter(
                determinant_error_abs, math.inf
            )
        response = {
            "schema_version": 1,
            "status": "ok",
            "operation": "fixed-root-determinant-sample",
            "request_sha256": request_sha256,
            "omega_re": str(omega.real),
            "omega_im": str(omega.imag),
            "amplitude_re": str(converted.real),
            "amplitude_im": str(converted.imag),
            "determinant_re": str(determinant.real),
            "determinant_im": str(determinant.imag),
            "determinant_error_abs": determinant_error_text,
            "determinant_error_status": "available/v1",
            "determinant_error_model_id": "synthetic-absolute-bound/v1",
            "determinant_family": "exterior-wronskian/v1",
            "determinant_normalisation": "unit-asymptotic-branch-wronskian/v1",
            "branch_identity": "gsn-complex-rho/v1",
            "branch_authenticated": True,
            "semantic_precision_tier": self.sample_tier.value,
            "working_precision_bits": working_precision_bits(
                self.sample_tier
            ),
            "readout_role": readout_role,
        }
        receipt = {
            "schema": "windows-solver.fixed-root-determinant-sample-receipt/1",
            "request_binding": request,
            "request_sha256": request_sha256,
            "response_binding": response,
            "response_sha256": hashlib.sha256(
                canonical_json_bytes(response)
            ).hexdigest(),
            "runtime_identity_sha256": self.runtime_identity,
            "scientific_runtime_sha256": self.baseline.worker_response_receipt[
                "scientific_runtime_sha256"
            ],
        }
        receipt_sha256 = hashlib.sha256(canonical_json_bytes(receipt)).hexdigest()
        return FixedRootDeterminantSample(
            omega=omega,
            amplitude=converted,
            determinant=determinant,
            determinant_error_abs=determinant_error_abs,
            determinant_error_status="available/v1",
            determinant_error_model_id="synthetic-absolute-bound/v1",
            determinant_family="exterior-wronskian/v1",
            determinant_normalisation="unit-asymptotic-branch-wronskian/v1",
            branch_identity="gsn-complex-rho/v1",
            branch_authenticated=True,
            request_sha256=request_sha256,
            worker_response_receipt=receipt,
            worker_response_receipt_sha256=receipt_sha256,
            precision_tier=self.sample_tier,
            working_precision_bits=working_precision_bits(
                self.sample_tier
            ),
            readout_role=readout_role,
        )


class RootForbiddenFrequencyFallbackBackend(FixedRootOnlyBackend):
    """Synthetic fixed-root boundary that makes accidental root work fatal."""

    def __init__(self, job, baseline) -> None:
        super().__init__(job, baseline)
        self.sample_calls: list[tuple[complex, complex, str]] = []

    def read_root(self, *args, **kwargs):
        raise AssertionError("sealed response repair must not call read_root")

    def sample_fixed_root_determinant(
        self, job, omega, amplitude, *, readout_role
    ) -> FixedRootDeterminantSample:
        sample = super().sample_fixed_root_determinant(
            job, omega, amplitude, readout_role=readout_role
        )
        self.sample_calls.append((complex(omega), complex(amplitude), readout_role))
        # D(omega, c) = 5 omega + (2 + 3i)c.  The response runner must use
        # omega differences for D_omega and amplitude differences for D_c.
        determinant = 5.0 * complex(omega) + (2.0 + 3.0j) * complex(amplitude)
        receipt = dict(sample.worker_response_receipt)
        response = dict(receipt["response_binding"])
        response.update({
            "omega_re": str(omega.real),
            "omega_im": str(omega.imag),
            "determinant_re": str(determinant.real),
            "determinant_im": str(determinant.imag),
            "determinant_error_abs": "1e-18",
        })
        receipt["response_binding"] = response
        receipt["response_sha256"] = hashlib.sha256(
            canonical_json_bytes(response)
        ).hexdigest()
        return replace(
            sample,
            determinant=determinant,
            determinant_error_abs=1.0e-18,
            worker_response_receipt=receipt,
            worker_response_receipt_sha256=hashlib.sha256(
                canonical_json_bytes(receipt)
            ).hexdigest(),
        )


class PromotedExteriorDerivativeTests(unittest.TestCase):
    def test_sealed_root_recovers_frequency_stencil_without_a_root_call(self) -> None:
        leaf = _primary_exterior_leaf()
        baseline = _promoted_baseline(
            leaf.job,
            conditioning_mechanism=leaf.mechanism_id,
        )
        baseline = replace(baseline, omega=leaf.job.root.omega)
        baseline = _with_worker_receipt(
            leaf.job, baseline, 80, baseline.omega
        )
        self.assertEqual(
            baseline.primary_acceptance.derivative_authentication
            .determinant_error_status,
            "unavailable/v1",
        )
        seal = PromotedRootSeal.derive(leaf.job, baseline)
        backend = RootForbiddenFrequencyFallbackBackend(leaf.job, baseline)

        result = run_promoted_exterior_response_from_seal(
            leaf.job,
            backend,
            seal,
            derivative_step=0.004,
        )

        self.assertEqual(result.status.value, "CONVERGED")
        self.assertEqual(
            [role for _, _, role in backend.sample_calls],
            [
                "frequency-real-plus-h",
                "frequency-real-minus-h",
                "frequency-real-plus-h2",
                "frequency-real-minus-h2",
                "coordinate-real-plus-h",
                "coordinate-real-minus-h",
                "coordinate-real-plus-h2",
                "coordinate-real-minus-h2",
            ],
        )
        evidence = result.derivative_evidence
        self.assertEqual(
            evidence["frequency_derivative_source"],
            "fixed-root-frequency-h-h2-stencil/v1",
        )
        self.assertEqual(evidence["root_seal_sha256"], seal.sha256)

    def test_frequency_only_repair_reuses_coordinate_stencil_at_the_sealed_root(
        self,
    ) -> None:
        """A response-tier retry promotes only the Dω h/h2 family."""

        leaf = _primary_exterior_leaf()
        baseline = _promoted_baseline(
            leaf.job,
            conditioning_mechanism=leaf.mechanism_id,
        )
        baseline = replace(baseline, omega=leaf.job.root.omega)
        baseline = _with_worker_receipt(
            leaf.job, baseline, 80, baseline.omega
        )
        seal = PromotedRootSeal.derive(leaf.job, baseline)
        original_backend = RootForbiddenFrequencyFallbackBackend(
            leaf.job, baseline
        )
        original = run_promoted_exterior_response_from_seal(
            leaf.job,
            original_backend,
            seal,
            derivative_step=0.004,
        )
        self.assertEqual(len(original_backend.sample_calls), 8)

        repaired_backend = RootForbiddenFrequencyFallbackBackend(
            leaf.job, baseline
        )
        repaired_backend.sample_tier = PrecisionTier.BIGFLOAT_120
        repaired = run_promoted_exterior_response_from_seal(
            leaf.job,
            repaired_backend,
            seal,
            derivative_step=0.004,
            repair_families=frozenset({"frequency"}),
            reusable_result=original,
        )

        self.assertEqual(
            [role for _, _, role in repaired_backend.sample_calls],
            [
                "frequency-real-plus-h",
                "frequency-real-minus-h",
                "frequency-real-plus-h2",
                "frequency-real-minus-h2",
            ],
        )
        evidence = repaired.derivative_evidence
        self.assertEqual(
            evidence["response_repair_scope"]["recomputed_families"],
            ["frequency"],
        )
        self.assertEqual(
            evidence["response_repair_scope"]["reused_families"],
            ["coordinate"],
        )
        samples = evidence["fixed_root_samples"]
        frequency_tiers = {
            sample["precision_tier"]
            for sample in samples
            if sample["readout_role"].startswith("frequency-")
        }
        coordinate_tiers = {
            sample["precision_tier"]
            for sample in samples
            if sample["readout_role"].startswith("coordinate-")
        }
        self.assertEqual(frequency_tiers, {"bigfloat-120"})
        self.assertEqual(coordinate_tiers, {"bigfloat-80"})
        self.assertEqual(
            ComponentResult.from_mapping(repaired.to_mapping()).to_mapping(),
            repaired.to_mapping(),
        )

    def test_reused_stencil_must_match_the_immediate_sealed_predecessor(
        self,
    ) -> None:
        """A repair cannot relabel independently sampled D_c as a reuse."""

        leaf = _primary_exterior_leaf()
        baseline = _promoted_baseline(
            leaf.job,
            conditioning_mechanism=leaf.mechanism_id,
        )
        baseline = replace(baseline, omega=leaf.job.root.omega)
        baseline = _with_worker_receipt(
            leaf.job, baseline, 80, baseline.omega
        )
        seal = PromotedRootSeal.derive(leaf.job, baseline)
        predecessor = run_promoted_exterior_response_from_seal(
            leaf.job,
            RootForbiddenFrequencyFallbackBackend(leaf.job, baseline),
            seal,
            derivative_step=0.004,
        )

        class DifferentCoordinateBackend(RootForbiddenFrequencyFallbackBackend):
            def sample_fixed_root_determinant(self, *args, **kwargs):
                sample = super().sample_fixed_root_determinant(*args, **kwargs)
                if not sample.readout_role.startswith("coordinate-"):
                    return sample
                determinant = sample.determinant + complex(1.0e-9, -2.0e-9)
                receipt = dict(sample.worker_response_receipt)
                response = dict(receipt["response_binding"])
                response.update({
                    "determinant_re": str(determinant.real),
                    "determinant_im": str(determinant.imag),
                })
                receipt["response_binding"] = response
                receipt["response_sha256"] = hashlib.sha256(
                    canonical_json_bytes(response)
                ).hexdigest()
                return replace(
                    sample,
                    determinant=determinant,
                    worker_response_receipt=receipt,
                    worker_response_receipt_sha256=hashlib.sha256(
                        canonical_json_bytes(receipt)
                    ).hexdigest(),
                )

        independently_sampled = run_promoted_exterior_response_from_seal(
            leaf.job,
            DifferentCoordinateBackend(leaf.job, baseline),
            seal,
            derivative_step=0.004,
        )
        forged = independently_sampled.to_mapping()
        forged["derivative_evidence"]["response_repair_scope"] = {
            "schema": "windows-solver.fixed-root-response-repair-scope/1",
            "requested_families": ["coordinate", "frequency"],
            "recomputed_families": ["frequency"],
            "reused_families": ["coordinate"],
        }
        forged_repair = ComponentResult.from_mapping(forged)

        with self.assertRaisesRegex(
            ValueError, "reused samples do not match their predecessor"
        ):
            response_batches._validate_root_sealed_response_reuse_binding(
                predecessor,
                forged_repair,
            )

    def _resume_sealed_response_journal(self, *, interrupt_after: int):
        leaf = _primary_exterior_leaf()
        baseline = _promoted_baseline(
            leaf.job,
            conditioning_mechanism=leaf.mechanism_id,
        )
        baseline = replace(baseline, omega=leaf.job.root.omega)
        baseline = _with_worker_receipt(
            leaf.job, baseline, 80, baseline.omega
        )
        seal = PromotedRootSeal.derive(leaf.job, baseline)

        class InterruptingBackend(RootForbiddenFrequencyFallbackBackend):
            def sample_fixed_root_determinant(self, *args, **kwargs):
                if len(self.sample_calls) >= interrupt_after:
                    raise KeyboardInterrupt("synthetic response-journal interrupt")
                return super().sample_fixed_root_determinant(*args, **kwargs)

        with tempfile.TemporaryDirectory() as temporary, patch.dict(
            "os.environ",
            {"KERR_QNM_PARTIAL_COMPONENT_JOURNAL_ROOT": temporary},
        ):
            interrupted_backend = InterruptingBackend(leaf.job, baseline)
            interrupted_journal_backend = (
                response_engine._journaled_promoted_exterior_response_backend(
                    leaf.job,
                    interrupted_backend,
                    seal=seal,
                    derivative_step=0.004,
                    validation_reason=None,
                )
            )
            with self.assertRaises(KeyboardInterrupt):
                run_promoted_exterior_response_from_seal(
                    leaf.job,
                    interrupted_journal_backend,
                    seal,
                    derivative_step=0.004,
                )

            journals = tuple(Path(temporary).glob("*.json"))
            self.assertEqual(len(journals), 1)
            stopped = PartialComponentJournal.load(journals[0])
            self.assertEqual(len(stopped.entries), interrupt_after)
            self.assertTrue(
                all(
                    entry.root_seal_sha256 == seal.sha256
                    for entry in stopped.entries.values()
                )
            )

            resumed_backend = RootForbiddenFrequencyFallbackBackend(
                leaf.job, baseline
            )
            resumed_journal_backend = (
                response_engine._journaled_promoted_exterior_response_backend(
                    leaf.job,
                    resumed_backend,
                    seal=seal,
                    derivative_step=0.004,
                    validation_reason=None,
                )
            )
            result = run_promoted_exterior_response_from_seal(
                leaf.job,
                resumed_journal_backend,
                seal,
                derivative_step=0.004,
            )
            return result, resumed_backend, PartialComponentJournal.load(journals[0])

    def test_sealed_response_journal_resumes_after_frequency_interrupt(self) -> None:
        """I: no root read and completed Dω samples survive an interruption."""

        result, resumed_backend, journal = self._resume_sealed_response_journal(
            interrupt_after=2
        )
        self.assertEqual(result.status, ComponentStatus.CONVERGED)
        self.assertEqual(len(resumed_backend.sample_calls), 6)
        self.assertEqual(
            [role for _, _, role in resumed_backend.sample_calls[:2]],
            ["frequency-real-plus-h2", "frequency-real-minus-h2"],
        )
        self.assertTrue(journal.complete)
        self.assertEqual(len(journal.entries), 8)

    def test_sealed_response_journal_resumes_after_coordinate_interrupt(self) -> None:
        """J: completed Dω and completed D_c samples are never recomputed."""

        result, resumed_backend, journal = self._resume_sealed_response_journal(
            interrupt_after=6
        )
        self.assertEqual(result.status, ComponentStatus.CONVERGED)
        self.assertEqual(
            [role for _, _, role in resumed_backend.sample_calls],
            ["coordinate-real-plus-h2", "coordinate-real-minus-h2"],
        )
        self.assertTrue(journal.complete)
        self.assertEqual(len(journal.entries), 8)

    def test_fixed_root_derivative_uses_exact_worker_decimal_text(self) -> None:
        leaf = _primary_exterior_leaf()
        baseline = self._baseline_with_derivative_evidence(leaf)
        backend = FixedRootOnlyBackend(leaf.job, baseline)

        def exact_sample(amplitude, role, determinant_text):
            sample = backend.sample_fixed_root_determinant(
                leaf.job,
                baseline.omega,
                amplitude,
                readout_role=role,
            )
            receipt = dict(sample.worker_response_receipt)
            response = dict(receipt["response_binding"])
            response.update({
                "determinant_re": determinant_text,
                "determinant_im": "0",
                "determinant_error_abs": "1e-40",
            })
            receipt["response_binding"] = response
            receipt["response_sha256"] = hashlib.sha256(
                canonical_json_bytes(response)
            ).hexdigest()
            receipt_sha256 = hashlib.sha256(
                canonical_json_bytes(receipt)
            ).hexdigest()
            exact_error = Decimal("1e-40")
            bounded_error = float(exact_error)
            if Decimal.from_float(bounded_error) < exact_error:
                bounded_error = math.nextafter(bounded_error, math.inf)
            return replace(
                sample,
                determinant=complex(float(Decimal(determinant_text)), 0.0),
                determinant_error_abs=bounded_error,
                worker_response_receipt=receipt,
                worker_response_receipt_sha256=receipt_sha256,
            )

        step = 0.004
        samples = (
            exact_sample(
                complex(step, 0.0),
                "coordinate-real-plus-h",
                "1.000000000000000000000000000004",
            ),
            exact_sample(
                complex(-step, 0.0),
                "coordinate-real-minus-h",
                "0.999999999999999999999999999996",
            ),
            exact_sample(
                complex(step / 2.0, 0.0),
                "coordinate-real-plus-h2",
                "1.000000000000000000000000000001",
            ),
            exact_sample(
                complex(-step / 2.0, 0.0),
                "coordinate-real-minus-h2",
                "0.999999999999999999999999999999",
            ),
        )

        disk, coarse, fine, propagated, disagreement = (
            _fixed_root_coordinate_derivative(samples, step)
        )

        self.assertNotEqual(fine, 0.0j)
        self.assertAlmostEqual(fine.real, 5.0e-28, delta=1.0e-42)
        self.assertAlmostEqual(coarse.real, 1.0e-27, delta=1.0e-42)
        self.assertGreater(disk.radius, propagated)
        self.assertGreater(disagreement, 0.0)

    @staticmethod
    def _baseline_with_derivative_evidence(leaf):
        baseline = _promoted_baseline(
            leaf.job,
            conditioning_mechanism=leaf.mechanism_id,
        )
        baseline = replace(baseline, omega=leaf.job.root.omega)
        derivative = baseline.primary_acceptance.derivative
        with localcontext() as context:
            context.prec = 180
            derivative_radius = Decimal("4e-7") + Decimal("6e-7")
            derivative_lower_bound = derivative.magnitude() - derivative_radius
        derivative_authentication = DerivativeAuthenticationEvidence(
            derivative_re=derivative.real,
            derivative_im=derivative.imaginary,
            propagated_error_abs=Decimal("4e-7"),
            step_disagreement_abs=Decimal("6e-7"),
            lower_bound_abs=derivative_lower_bound,
            selected_step=Decimal("1e-5"),
            axis="real",
            determinant_error_status="available/v1",
            determinant_error_model_id="synthetic-absolute-bound/v1",
        )
        admitted = replace(
            baseline,
            primary_acceptance=replace(
                baseline.primary_acceptance,
                determinant_error_abs=Decimal("1e-20"),
                error_model_id="synthetic-absolute-bound/v1",
                derivative_authentication=derivative_authentication,
            ),
        )
        return _with_worker_receipt(
            leaf.job,
            admitted,
            80,
            admitted.omega,
        )

    def test_ordinary_route_uses_fixed_root_samples_and_no_perturbed_roots(self) -> None:
        leaf = _primary_exterior_leaf()
        baseline = self._baseline_with_derivative_evidence(leaf)
        backend = FixedRootOnlyBackend(leaf.job, baseline)

        result = run_promoted_exterior_component(
            leaf.job,
            backend,
            primary_predictor=baseline.omega,
            derivative_step=0.004,
        )
        mapping = result.to_mapping()

        self.assertEqual(backend.root_amplitudes, [0.0j])
        self.assertEqual(
            backend.sample_amplitudes,
            [0.004 + 0.0j, -0.004 + 0.0j, 0.002 + 0.0j, -0.002 + 0.0j],
        )

        self.assertEqual(
            mapping["component_scientific_identity"],
            EXTERIOR_DERIVATIVE_COMPONENT_IDENTITY,
        )
        evidence = mapping["derivative_evidence"]
        self.assertEqual(evidence["response_disk_identity"], EXTERIOR_DERIVATIVE_RESPONSE_DISK_IDENTITY)
        self.assertEqual(evidence["determinant_count"], 4)
        self.assertEqual(len(evidence["fixed_root_samples"]), 4)
        self.assertEqual(evidence["selected_step"], 0.002)
        self.assertGreater(evidence["coordinate_derivative_disk"]["radius"], 0.0)
        self.assertGreater(evidence["response_disk"]["radius"], 0.0)
        self.assertEqual(
            evidence["conditioning_decision"],
            {
                "accepted": True,
                "identity": "fixed-root-h-h2-conditioning/v1",
                "rejection_reason": None,
                "selected_candidate": "h/2",
            },
        )
        self.assertEqual(
            evidence["frequency_derivative_radius_provenance"],
            {
                "axis": "real",
                "propagated_error_abs": "4E-7",
                "selected_step": "0.00001",
                "step_disagreement_abs": "6E-7",
            },
        )
        self.assertFalse(mapping["finite_amplitude_ladder_executed"])
        self.assertEqual(mapping["finite_amplitude_readout_count"], 0)

    def test_reused_fixed_sample_must_bind_nested_request_to_work_unit(self) -> None:
        leaf = _primary_exterior_leaf()
        baseline = self._baseline_with_derivative_evidence(leaf)
        backend = FixedRootOnlyBackend(leaf.job, baseline)
        role = "coordinate-real-plus-h"
        sample = backend.sample_fixed_root_determinant(
            leaf.job, baseline.omega, 0.004 + 0.0j, readout_role=role
        )
        unit = PartialComponentWorkUnit(
            component_scientific_identity=EXTERIOR_DERIVATIVE_COMPONENT_IDENTITY,
            leaf_id=leaf.job.leaf_id,
            job_id=leaf.job.job_id,
            policy_sha256=leaf.job.policy.identity_sha256,
            backend_identity=leaf.job.backend_identity.identity_sha256,
            determinant_family=sample.determinant_family,
            determinant_normalisation=sample.determinant_normalisation,
            precision_tier=sample.precision_tier,
            mpfr_bits=sample.working_precision_bits,
            amplitude=sample.amplitude,
            epsilon=abs(sample.amplitude),
            readout_role=role,
            refinement_level=0,
            request_sha256="0" * 64,
        )
        with tempfile.TemporaryDirectory() as temporary:
            journal = PartialComponentJournal.create(
                Path(temporary) / "fixed.json",
                expected_work_unit_ids=(unit.work_unit_id,),
            )
            journal.record(unit.to_entry({
                "schema": "windows-solver.promoted-component-journal-receipt/1",
                "kind": "fixed-root-determinant-sample",
                "output": sample.to_mapping(),
            }))
            guarded = _JournaledPromotedExteriorBackend(
                backend,
                journal,
                {role: unit},
                exact_request_binding=True,
            )
            with self.assertRaisesRegex(ValueError, "reused output request"):
                guarded._reuse(role, "fixed-root-determinant-sample")

    def test_reused_root_must_bind_nested_request_to_work_unit(self) -> None:
        leaf = _primary_exterior_leaf()
        baseline = self._baseline_with_derivative_evidence(leaf)
        backend = FixedRootOnlyBackend(leaf.job, baseline)
        unit = PartialComponentWorkUnit(
            component_scientific_identity=(
                "same-equation-signed-root-component-journal/v1"
            ),
            leaf_id=leaf.job.leaf_id,
            job_id=leaf.job.job_id,
            policy_sha256=leaf.job.policy.identity_sha256,
            backend_identity=leaf.job.backend_identity.identity_sha256,
            determinant_family="exterior-wronskian/v1",
            determinant_normalisation=(
                "unit-asymptotic-branch-wronskian/v1"
            ),
            precision_tier=PrecisionTier.BINARY64,
            mpfr_bits=working_precision_bits(PrecisionTier.BINARY64),
            amplitude=0.0j,
            epsilon=0.0,
            readout_role="baseline",
            refinement_level=0,
            request_sha256="0" * 64,
        )
        with tempfile.TemporaryDirectory() as temporary:
            journal = PartialComponentJournal.create(
                Path(temporary) / "root.json",
                expected_work_unit_ids=(unit.work_unit_id,),
            )
            journal.record(unit.to_entry({
                "schema": "windows-solver.promoted-component-journal-receipt/1",
                "kind": "root-readout",
                "output": baseline.to_mapping(),
            }))
            guarded = _JournaledComponentReads(
                backend,
                journal,
                {("baseline", 0.0j): unit},
            )
            with self.assertRaisesRegex(ValueError, "reused output request"):
                guarded.read_root(
                    leaf.job, "baseline", 0.0j, None, None
                )

    def test_production_partial_journal_resumes_baseline_without_backend_recompute(self) -> None:
        leaf = _primary_exterior_leaf()
        baseline = self._baseline_with_derivative_evidence(leaf)

        class InterruptAfterBaseline(FixedRootOnlyBackend):
            def sample_fixed_root_determinant(self, *args, **kwargs):
                raise KeyboardInterrupt("synthetic interruption")

        with tempfile.TemporaryDirectory() as temporary, patch.dict(
            "os.environ",
            {"KERR_QNM_PARTIAL_COMPONENT_JOURNAL_ROOT": temporary},
        ):
            interrupted = InterruptAfterBaseline(leaf.job, baseline)
            with self.assertRaises(KeyboardInterrupt):
                run_promoted_exterior_component(
                    leaf.job,
                    interrupted,
                    primary_predictor=baseline.omega,
                    derivative_step=0.004,
                )
            journals = tuple(Path(temporary).glob("*.json"))
            self.assertEqual(len(journals), 2)
            stopped = tuple(PartialComponentJournal.load(path) for path in journals)
            root_journal = next(
                journal for journal in stopped if len(journal.entries) == 1
            )
            response_journal = next(
                journal for journal in stopped if len(journal.entries) == 0
            )
            baseline_entry = next(iter(root_journal.entries.values()))
            self.assertEqual(baseline_entry.readout_role, "baseline-root")
            self.assertIn(
                "diagnostic_readouts",
                baseline_entry.worker_response_receipt["output"],
            )

            resumed = FixedRootOnlyBackend(leaf.job, baseline)
            result = run_promoted_exterior_component(
                leaf.job,
                resumed,
                primary_predictor=baseline.omega,
                derivative_step=0.004,
            )
            self.assertEqual(resumed.root_amplitudes, [])
            self.assertEqual(len(resumed.sample_amplitudes), 4)
            self.assertIsNotNone(result.response)
            self.assertTrue(PartialComponentJournal.load(root_journal.path).complete)
            final_response = PartialComponentJournal.load(response_journal.path)
            self.assertTrue(final_response.complete)
            self.assertEqual(len(final_response.entries), 4)

    def test_completed_production_partial_journal_reuses_all_reads_byte_stably(self) -> None:
        """An identical full assembly is a byte-stable, zero-worker replay."""

        leaf = _primary_exterior_leaf()
        baseline = self._baseline_with_derivative_evidence(leaf)
        scientific_runtime = {
            "julia_version": "1.11.7",
            "worker_sha256": "a" * 64,
        }
        scientific_runtime_sha256 = hashlib.sha256(
            canonical_json_bytes(scientific_runtime)
        ).hexdigest()
        runtime_identity = "b" * 64
        receipt = response_engine._journal_json_value(
            baseline.worker_response_receipt
        )
        receipt["scientific_runtime_sha256"] = (
            scientific_runtime_sha256
        )
        material = {
            key: value
            for key, value in receipt.items()
            if key != "receipt_sha256"
        }
        receipt["receipt_sha256"] = hashlib.sha256(
            canonical_json_bytes(material)
        ).hexdigest()
        baseline = replace(baseline, worker_response_receipt=receipt)

        class ExactPreviewBackend(FixedRootOnlyBackend):
            def __init__(self):
                super().__init__(
                    leaf.job,
                    baseline,
                    runtime_identity=runtime_identity,
                )

            def scientific_runtime_for(self, job):
                return dict(scientific_runtime)

            def preview_root_request(
                self,
                job,
                amplitude,
                primary_predictor,
                primary_predictor_kind,
                readout_role,
            ):
                return dict(
                    self.baseline.worker_response_receipt[
                        "request_binding"
                    ]
                )

            def preview_fixed_root_request(
                self, job, omega, amplitude, readout_role
            ):
                converted = complex(amplitude)
                return {
                    "amplitude": {
                        "imaginary": converted.imag,
                        "real": converted.real,
                    },
                    "job_id": job.job_id,
                    "leaf_id": job.leaf_id,
                    "omega": {
                        "imaginary": omega.imag,
                        "real": omega.real,
                    },
                    "readout_role": readout_role,
                }

        with tempfile.TemporaryDirectory() as temporary, patch.dict(
            "os.environ",
            {"KERR_QNM_PARTIAL_COMPONENT_JOURNAL_ROOT": temporary},
        ):
            first_backend = ExactPreviewBackend()
            first_result = run_promoted_exterior_component(
                leaf.job,
                first_backend,
                primary_predictor=baseline.omega,
                derivative_step=0.004,
            )
            self.assertEqual(first_backend.root_amplitudes, [0.0j])
            self.assertEqual(len(first_backend.sample_amplitudes), 4)

            journals = tuple(Path(temporary).glob("*.json"))
            self.assertEqual(len(journals), 2)
            journal_paths = tuple(sorted(journals))
            original_bytes = {
                path: path.read_bytes() for path in journal_paths
            }
            original = {
                path: PartialComponentJournal.load(path) for path in journal_paths
            }
            self.assertEqual(
                sorted(len(journal.entries) for journal in original.values()),
                [1, 4],
            )
            self.assertTrue(all(journal.complete for journal in original.values()))

            for journal in original.values():
                for entry in journal.entries.values():
                    output = entry.worker_response_receipt["output"]
                    output_receipt = output["worker_response_receipt"]
                    self.assertEqual(
                        output_receipt["scientific_runtime_sha256"],
                        scientific_runtime_sha256,
                    )
                    self.assertEqual(
                        entry.request_sha256,
                        (
                            output_receipt["request_sha256"]
                            if entry.readout_role == "baseline-root"
                            else output["request_sha256"]
                        ),
                    )
                    if entry.readout_role != "baseline-root":
                        self.assertEqual(
                            output_receipt["runtime_identity_sha256"],
                            runtime_identity,
                        )

            second_backend = ExactPreviewBackend()
            second_result = run_promoted_exterior_component(
                leaf.job,
                second_backend,
                primary_predictor=baseline.omega,
                derivative_step=0.004,
            )

            self.assertEqual(second_backend.root_amplitudes, [])
            self.assertEqual(second_backend.sample_amplitudes, [])
            self.assertEqual(
                second_result.to_mapping(), first_result.to_mapping()
            )
            self.assertEqual(
                tuple(sorted(Path(temporary).glob("*.json"))), journal_paths
            )
            for path in journal_paths:
                self.assertEqual(path.read_bytes(), original_bytes[path])
                reloaded = PartialComponentJournal.load(path)
                self.assertEqual(reloaded.to_mapping(), original[path].to_mapping())

    def test_production_partial_journal_worker_change_reruns_baseline(self) -> None:
        """A changed worker rolls forward without deleting the old journal."""

        leaf = _primary_exterior_leaf()
        baseline = self._baseline_with_derivative_evidence(leaf)

        def runtime_bound_baseline(worker_sha256: str):
            runtime = {"worker_sha256": worker_sha256}
            receipt = response_engine._journal_json_value(
                baseline.worker_response_receipt
            )
            receipt["scientific_runtime_sha256"] = hashlib.sha256(
                canonical_json_bytes(runtime)
            ).hexdigest()
            material = {
                key: value
                for key, value in receipt.items()
                if key != "receipt_sha256"
            }
            receipt["receipt_sha256"] = hashlib.sha256(
                canonical_json_bytes(material)
            ).hexdigest()
            return runtime, replace(
                baseline, worker_response_receipt=receipt
            )

        class ExactPreviewBackend(FixedRootOnlyBackend):
            def __init__(self, job, baseline, runtime):
                super().__init__(job, baseline)
                self._runtime = runtime

            def scientific_runtime_for(self, job):
                return dict(self._runtime)

            def preview_root_request(
                self,
                job,
                amplitude,
                primary_predictor,
                primary_predictor_kind,
                readout_role,
            ):
                return dict(
                    self.baseline.worker_response_receipt[
                        "request_binding"
                    ]
                )

            def preview_fixed_root_request(
                self, job, omega, amplitude, readout_role
            ):
                converted = complex(amplitude)
                return {
                    "amplitude": {
                        "imaginary": converted.imag,
                        "real": converted.real,
                    },
                    "job_id": job.job_id,
                    "leaf_id": job.leaf_id,
                    "omega": {
                        "imaginary": omega.imag,
                        "real": omega.real,
                    },
                    "readout_role": readout_role,
                }

        class InterruptAfterBaseline(ExactPreviewBackend):
            def sample_fixed_root_determinant(self, *args, **kwargs):
                raise KeyboardInterrupt("synthetic interruption")

        runtime_a, baseline_a = runtime_bound_baseline("a" * 64)
        runtime_b, baseline_b = runtime_bound_baseline("b" * 64)
        with tempfile.TemporaryDirectory() as temporary, patch.dict(
            "os.environ",
            {"KERR_QNM_PARTIAL_COMPONENT_JOURNAL_ROOT": temporary},
        ):
            interrupted = InterruptAfterBaseline(
                leaf.job, baseline_a, runtime_a
            )
            with self.assertRaises(KeyboardInterrupt):
                run_promoted_exterior_component(
                    leaf.job,
                    interrupted,
                    primary_predictor=baseline.omega,
                    derivative_step=0.004,
                )
            old_paths = tuple(sorted(Path(temporary).glob("*.json")))
            self.assertEqual(len(old_paths), 2)
            old_bytes = {path: path.read_bytes() for path in old_paths}

            resumed = ExactPreviewBackend(leaf.job, baseline_b, runtime_b)
            result = run_promoted_exterior_component(
                leaf.job,
                resumed,
                primary_predictor=baseline.omega,
                derivative_step=0.004,
            )

            self.assertEqual(resumed.root_amplitudes, [0.0j])
            self.assertIsNotNone(result.response)
            journals = tuple(Path(temporary).glob("*.json"))
            self.assertEqual(len(journals), 4)
            for path in old_paths:
                self.assertTrue(path.is_file())
                self.assertEqual(path.read_bytes(), old_bytes[path])

    def test_non_primary_exterior_uses_the_same_fixed_root_contract(self) -> None:
        leaf = _deep_exterior_leaf()
        baseline = self._baseline_with_derivative_evidence(leaf)
        backend = FixedRootOnlyBackend(leaf.job, baseline)

        result = run_promoted_exterior_component(
            leaf.job,
            backend,
            primary_predictor=baseline.omega,
            derivative_step=0.004,
        )

        self.assertEqual(result.status.value, "CONVERGED")
        self.assertEqual(backend.root_amplitudes, [0.0j])
        self.assertEqual(len(backend.sample_amplitudes), 4)

    def test_validation_reasons_are_restricted_and_do_not_trigger_root_ladder(self) -> None:
        leaf = _primary_exterior_leaf()
        baseline = self._baseline_with_derivative_evidence(leaf)
        rejected_backend = FixedRootOnlyBackend(leaf.job, baseline)
        with self.assertRaisesRegex(ValueError, "validation reason"):
            run_promoted_exterior_component(
                leaf.job,
                rejected_backend,
                primary_predictor=baseline.omega,
                derivative_step=0.004,
                validation_reason="AUTOMATIC_DERIVATIVE_FAILURE_FALLBACK",
            )
        self.assertEqual(rejected_backend.root_amplitudes, [])

        backend = FixedRootOnlyBackend(leaf.job, baseline)
        result = run_promoted_exterior_component(
            leaf.job,
            backend,
            primary_predictor=baseline.omega,
            derivative_step=0.004,
            validation_reason="PUBLICATION_VALIDATION",
        )
        evidence = result.to_mapping()["derivative_evidence"]
        self.assertEqual(backend.root_amplitudes, [0.0j])
        self.assertEqual(len(backend.sample_amplitudes), 6)
        self.assertEqual(evidence["determinant_count"], 6)
        self.assertEqual(
            evidence["validation_policy_identity"],
            FIXED_ROOT_AXIS_VALIDATION_IDENTITY,
        )
        self.assertEqual(evidence["validation_reason"], "PUBLICATION_VALIDATION")
        self.assertTrue(evidence["imaginary_axis_validation"]["agrees"])
        self.assertEqual(
            full_ladder_validation_policy("RISK_SELECTED_SENTINEL"),
            {
                "identity": FULL_COMPLEX_LADDER_VALIDATION_IDENTITY,
                "reason": "RISK_SELECTED_SENTINEL",
            },
        )

    def test_full_ladder_execution_requires_identity_bound_reason(self) -> None:
        leaf = _primary_exterior_leaf()
        baseline = self._baseline_with_derivative_evidence(leaf)
        backend = FixedRootOnlyBackend(leaf.job, baseline)

        with patch("windows_solver.response_engine.run_component") as generic:
            with self.assertRaisesRegex(ValueError, "validation reason"):
                run_promoted_full_ladder_validation(
                    leaf.job,
                    backend,
                    primary_predictor=baseline.omega,
                    reason="AUTOMATIC_DERIVATIVE_FAILURE_FALLBACK",
                )
            generic.assert_not_called()

        generic_result = object()
        with patch(
            "windows_solver.response_engine.run_component",
            return_value=generic_result,
        ) as generic:
            validation = run_promoted_full_ladder_validation(
                leaf.job,
                backend,
                primary_predictor=baseline.omega,
                reason="PUBLICATION_VALIDATION",
            )
        generic.assert_called_once()
        self.assertIs(validation["result"], generic_result)
        self.assertEqual(
            validation["validation_policy"],
            {
                "identity": FULL_COMPLEX_LADDER_VALIDATION_IDENTITY,
                "reason": "PUBLICATION_VALIDATION",
            },
        )

        class MarkedBackend(FixedRootOnlyBackend):
            promoted_precision_backend = True

            def read_root(self, *args, **kwargs):
                raise AssertionError("promoted backend work started")

        with self.assertRaisesRegex(ValueError, "full-ladder validation"):
            run_component(
                leaf.job,
                MarkedBackend(leaf.job, baseline),
                response_predictor=baseline.omega,
            )

    def test_missing_or_inadmissible_derivative_evidence_is_typed_unusable(self) -> None:
        leaf = _primary_exterior_leaf()
        missing = _promoted_baseline(
            leaf.job,
            conditioning_mechanism=leaf.mechanism_id,
        )
        missing = replace(missing, omega=leaf.job.root.omega)
        missing = replace(
            missing,
            primary_acceptance=replace(
                missing.primary_acceptance,
                derivative_authentication=None,
            ),
        )
        missing = _with_worker_receipt(
            leaf.job, missing, 80, missing.omega
        )
        missing_backend = FixedRootOnlyBackend(leaf.job, missing)
        missing_result = run_promoted_exterior_component(
            leaf.job,
            missing_backend,
            primary_predictor=missing.omega,
            derivative_step=0.004,
        ).to_mapping()
        self.assertEqual(missing_result["status"], "DERIVATIVE_UNRESOLVED")
        self.assertFalse(missing_result["usable"])
        self.assertEqual(
            missing_result["derivative_evidence"]["failure_code"],
            "FREQUENCY_DERIVATIVE_DISK_CONTAINS_ZERO",
        )
        self.assertEqual(len(missing_backend.sample_amplitudes), 8)

        class NoisyBackend(FixedRootOnlyBackend):
            def sample_fixed_root_determinant(self, *args, **kwargs):
                sample = super().sample_fixed_root_determinant(*args, **kwargs)
                error_abs = 10.0 * abs(sample.amplitude)
                receipt = dict(sample.worker_response_receipt)
                response = dict(receipt["response_binding"])
                response["determinant_error_abs"] = str(error_abs)
                receipt["response_binding"] = response
                receipt["response_sha256"] = hashlib.sha256(
                    canonical_json_bytes(response)
                ).hexdigest()
                return replace(
                    sample,
                    determinant_error_abs=error_abs,
                    worker_response_receipt=receipt,
                    worker_response_receipt_sha256=hashlib.sha256(
                        canonical_json_bytes(receipt)
                    ).hexdigest(),
                )

        baseline = self._baseline_with_derivative_evidence(leaf)
        noisy_result = run_promoted_exterior_component(
            leaf.job,
            NoisyBackend(leaf.job, baseline),
            primary_predictor=baseline.omega,
            derivative_step=0.004,
        ).to_mapping()
        self.assertEqual(noisy_result["status"], "DERIVATIVE_UNRESOLVED")
        self.assertIsNone(noisy_result["response"])
        self.assertEqual(
            noisy_result["derivative_evidence"]["failure_code"],
            "NO_ADMISSIBLE_FIXED_ROOT_DERIVATIVE_STEP",
        )
        self.assertFalse(
            noisy_result["derivative_evidence"]["conditioning_decision"]["accepted"]
        )

    def test_unavailable_determinant_error_model_is_typed_math_review_blocker(self) -> None:
        leaf = _primary_exterior_leaf()
        baseline = _promoted_baseline(
            leaf.job,
            conditioning_mechanism=leaf.mechanism_id,
        )
        baseline = replace(baseline, omega=leaf.job.root.omega)
        baseline = _with_worker_receipt(leaf.job, baseline, 80, baseline.omega)
        backend = FixedRootOnlyBackend(leaf.job, baseline)

        result = run_promoted_exterior_component(
            leaf.job,
            backend,
            primary_predictor=baseline.omega,
            derivative_step=0.004,
        ).to_mapping()

        self.assertEqual(result["status"], "DERIVATIVE_UNRESOLVED")
        self.assertEqual(len(backend.sample_amplitudes), 8)
        self.assertEqual(
            result["derivative_evidence"]["failure_code"],
            "FREQUENCY_DERIVATIVE_DISK_CONTAINS_ZERO",
        )
        self.assertEqual(
            result["derivative_evidence"]["frequency_derivative_source"],
            "fixed-root-frequency-h-h2-stencil/v1",
        )

    def test_component_result_rejects_coherently_resealed_sample_ladder(self) -> None:
        leaf = _primary_exterior_leaf()
        baseline = self._baseline_with_derivative_evidence(leaf)
        result = run_promoted_exterior_component(
            leaf.job,
            FixedRootOnlyBackend(leaf.job, baseline),
            primary_predictor=baseline.omega,
            derivative_step=0.004,
        ).to_mapping()
        evidence = result["derivative_evidence"]
        moved_omega = baseline.omega + complex(0.001, -0.001)
        for sample in evidence["fixed_root_samples"]:
            amplitude = complex(
                sample["amplitude"]["real"],
                sample["amplitude"]["imaginary"],
            )
            determinant = 1.0e-12 + (4.0 + 6.0j) * amplitude
            sample["omega"] = {
                "real": moved_omega.real,
                "imaginary": moved_omega.imag,
            }
            sample["determinant"] = {
                "real": determinant.real,
                "imaginary": determinant.imag,
            }
            receipt = sample["worker_response_receipt"]
            request = receipt["request_binding"]
            request["omega"] = sample["omega"]
            request_sha = hashlib.sha256(canonical_json_bytes(request)).hexdigest()
            sample["request_sha256"] = request_sha
            receipt["request_sha256"] = request_sha
            response = receipt["response_binding"]
            response.update({
                "request_sha256": request_sha,
                "omega_re": str(moved_omega.real),
                "omega_im": str(moved_omega.imag),
                "determinant_re": str(determinant.real),
                "determinant_im": str(determinant.imag),
            })
            receipt["response_sha256"] = hashlib.sha256(
                canonical_json_bytes(response)
            ).hexdigest()
            sample["worker_response_receipt_sha256"] = hashlib.sha256(
                canonical_json_bytes(receipt)
            ).hexdigest()

        samples = evidence["fixed_root_samples"]
        h = 0.004
        determinants = [
            complex(item["determinant"]["real"], item["determinant"]["imaginary"])
            for item in samples
        ]
        coarse = (determinants[0] - determinants[1]) / (2.0 * h)
        fine = (determinants[2] - determinants[3]) / h
        propagated = (
            samples[2]["determinant_error_abs"]
            + samples[3]["determinant_error_abs"]
        ) / h
        disagreement = abs(fine - coarse)
        coordinate = ComplexDisk(fine, propagated + disagreement)
        frequency_raw = evidence["frequency_derivative_disk"]
        frequency = ComplexDisk(
            complex(
                frequency_raw["centre"]["real"],
                frequency_raw["centre"]["imaginary"],
            ),
            frequency_raw["radius"],
        )
        response = exterior_response_disk(
            coordinate_derivative=coordinate,
            frequency_derivative=frequency,
        )
        evidence.update({
            "coordinate_derivative_disk": coordinate.to_mapping(),
            "fine_derivative": {"real": fine.real, "imaginary": fine.imag},
            "propagated_determinant_error_abs": propagated,
            "raw_step_disagreement_abs": disagreement,
            "real_h_derivative": {"real": coarse.real, "imaginary": coarse.imag},
            "response_disk": response.to_mapping(),
        })
        result["response"] = response.to_mapping()["centre"]
        result["error_channels"]["resolution"] = response.radius

        with self.assertRaisesRegex(ValueError, "baseline omega"):
            ComponentResult.from_mapping(result)

    def test_checkpoint_rejects_sample_from_a_different_runtime(self) -> None:
        leaf = _primary_exterior_leaf()
        baseline = replace(
            self._baseline_with_derivative_evidence(leaf),
            omega=leaf.job.root.omega,
        )
        runtime_provenance = {}
        calibration_receipt = load_default_calibration_receipt()
        runtime_backend = JuliaPrecisionRootBackend(
            leaf.job.backend_identity,
            SimpleNamespace(runtime_provenance=runtime_provenance),
            80,
            empirical_control_profile=calibration_receipt.budget_for(
                "exterior-wronskian/v1", 80
            ),
            calibration_receipt=calibration_receipt,
        )
        runtime = runtime_backend.scientific_runtime_for(leaf.job)
        result = run_promoted_exterior_component(
            leaf.job,
            FixedRootOnlyBackend(
                leaf.job,
                baseline,
                runtime_identity=runtime_identity_sha256(
                    runtime_provenance
                ),
            ),
            primary_predictor=baseline.omega,
            derivative_step=0.004,
        )
        payload = {
            "evidence_kind": (
                "package-owned-julia-fixed-root-exterior-derivative-component"
            ),
            "result": result.to_mapping(),
            "self_refinement_result": None,
            "self_refinement_skipped_reason": (
                "NOT_REQUIRED_BY_FIXED_ROOT_DERIVATIVE_POLICY"
            ),
            "scientific_runtime": runtime,
            "primary_root_predictor_source": (
                "PREVIOUS_STAGE_BASELINE_OMEGA"
            ),
            "precision_ladder_discrepancy_applicable": False,
            "precision_ladder_discrepancy_reason": (
                "BINARY64_COMPONENT_RESPONSE_UNAVAILABLE"
            ),
        }
        outcome = StageOutcome(
            digits=80,
            numerical_state="CONVERGED",
            component_result=payload,
            local_disk_radius_abs=sum(result.error_channels.values()),
            signed_error_channels=_component_stage_signed_error_channels(
                payload,
                result,
                repeat_applicable=False,
                precision_ladder_applicable=False,
            ),
            self_refinement_enclosed=None,
            discrepancy_from_previous_abs=None,
            discrepancy_enclosed=None,
        )
        self.assertTrue(_validate_component_result(leaf, outcome))

        tampered_payload = dict(payload)
        tampered_payload["scientific_runtime"] = {
            **runtime,
            "worker_sha256": "a" * 64,
        }
        tampered = replace(
            outcome,
            component_result=tampered_payload,
            signed_error_channels=_component_stage_signed_error_channels(
                tampered_payload,
                result,
                repeat_applicable=False,
                precision_ladder_applicable=False,
            ),
        )
        with self.assertRaisesRegex(ValueError, "sample runtime identity"):
            _validate_component_result(leaf, tampered)

    def test_component_result_rejects_sample_request_without_leaf_binding(self) -> None:
        leaf = _primary_exterior_leaf()
        baseline = self._baseline_with_derivative_evidence(leaf)
        mapping = run_promoted_exterior_component(
            leaf.job,
            FixedRootOnlyBackend(leaf.job, baseline),
            primary_predictor=baseline.omega,
            derivative_step=0.004,
        ).to_mapping()
        sample = mapping["derivative_evidence"]["fixed_root_samples"][0]
        receipt = sample["worker_response_receipt"]
        del receipt["request_binding"]["leaf_id"]
        request_sha = hashlib.sha256(
            canonical_json_bytes(receipt["request_binding"])
        ).hexdigest()
        sample["request_sha256"] = request_sha
        receipt["request_sha256"] = request_sha
        receipt["response_binding"]["request_sha256"] = request_sha
        receipt["response_sha256"] = hashlib.sha256(
            canonical_json_bytes(receipt["response_binding"])
        ).hexdigest()
        sample["worker_response_receipt_sha256"] = hashlib.sha256(
            canonical_json_bytes(receipt)
        ).hexdigest()

        with self.assertRaisesRegex(ValueError, "job, or runtime binding"):
            ComponentResult.from_mapping(mapping)

    def test_component_result_rejects_unauthenticated_sample_branch(self) -> None:
        leaf = _primary_exterior_leaf()
        baseline = self._baseline_with_derivative_evidence(leaf)
        mapping = run_promoted_exterior_component(
            leaf.job,
            FixedRootOnlyBackend(leaf.job, baseline),
            primary_predictor=baseline.omega,
            derivative_step=0.004,
        ).to_mapping()
        sample = mapping["derivative_evidence"]["fixed_root_samples"][0]
        sample["branch_authenticated"] = False
        receipt = sample["worker_response_receipt"]
        receipt["response_binding"]["branch_authenticated"] = False
        receipt["response_sha256"] = hashlib.sha256(
            canonical_json_bytes(receipt["response_binding"])
        ).hexdigest()
        sample["worker_response_receipt_sha256"] = hashlib.sha256(
            canonical_json_bytes(receipt)
        ).hexdigest()

        with self.assertRaisesRegex(ValueError, "baseline omega"):
            ComponentResult.from_mapping(mapping)

    def test_campaign_rejects_sample_precision_not_bound_to_stage_runtime(self) -> None:
        leaf = _primary_exterior_leaf()
        baseline = replace(
            self._baseline_with_derivative_evidence(leaf),
            omega=leaf.job.root.omega,
        )
        budget = synthetic_ode_error_budget(80).to_mapping()
        runtime = {
            "precision_digits": 80,
            "working_precision_bits": 298,
            "semantic_precision_tier": "bigfloat-80",
            "refinement_level": 0,
            "regularised_gsn_precision_policy": dict(
                regularised_gsn_precision_policy(leaf.mechanism_id)
            ),
            "ode_error_budget": budget,
            "ode_error_budget_sha256": hashlib.sha256(
                canonical_json_bytes(budget)
            ).hexdigest(),
        }
        result = run_promoted_exterior_component(
            leaf.job,
            FixedRootOnlyBackend(
                leaf.job,
                baseline,
                runtime_identity=runtime_identity_sha256({}),
                sample_tier=PrecisionTier.BIGFLOAT_120,
            ),
            primary_predictor=baseline.omega,
            derivative_step=0.004,
        )
        payload = {
            "evidence_kind": (
                "package-owned-julia-fixed-root-exterior-derivative-component"
            ),
            "result": result.to_mapping(),
            "self_refinement_result": None,
            "self_refinement_skipped_reason": (
                "NOT_REQUIRED_BY_FIXED_ROOT_DERIVATIVE_POLICY"
            ),
            "scientific_runtime": runtime,
            "primary_root_predictor_source": (
                "PREVIOUS_STAGE_BASELINE_OMEGA"
            ),
            "precision_ladder_discrepancy_applicable": False,
            "precision_ladder_discrepancy_reason": (
                "BINARY64_COMPONENT_RESPONSE_UNAVAILABLE"
            ),
        }
        outcome = StageOutcome(
            digits=80,
            numerical_state="CONVERGED",
            component_result=payload,
            local_disk_radius_abs=sum(result.error_channels.values()),
            signed_error_channels=_component_stage_signed_error_channels(
                payload,
                result,
                repeat_applicable=False,
                precision_ladder_applicable=False,
            ),
            self_refinement_enclosed=None,
            discrepancy_from_previous_abs=None,
            discrepancy_enclosed=None,
        )

        with self.assertRaisesRegex(ValueError, "sample precision"):
            _validate_component_result(leaf, outcome)


if __name__ == "__main__":
    unittest.main()
