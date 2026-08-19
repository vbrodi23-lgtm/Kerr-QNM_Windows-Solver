from __future__ import annotations

import hashlib
from dataclasses import replace
from decimal import Decimal, localcontext
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tests.test_promoted_horizon_component import (
    _promoted_baseline,
    _with_worker_receipt,
)
from windows_solver.contracts import canonical_json_bytes
from windows_solver.precision_tiers import PrecisionTier, working_precision_bits
from windows_solver.response_batches import (
    PrecisionCapabilities,
    StageOutcome,
    _validate_component_result,
    build_campaign_plan,
    synthetic_stage_signed_error_channels,
)
from windows_solver.root_readout_cache import runtime_identity_sha256
from windows_solver.response_engine import (
    ComponentResult,
    EXTERIOR_DERIVATIVE_COMPONENT_IDENTITY,
    EXTERIOR_DERIVATIVE_RESPONSE_DISK_IDENTITY,
    FIXED_ROOT_AXIS_VALIDATION_IDENTITY,
    FULL_COMPLEX_LADDER_VALIDATION_IDENTITY,
    DerivativeAuthenticationEvidence,
    FixedRootDeterminantSample,
    NumericalPolicy,
    VettedNativeDeterminantKernel,
    regularised_gsn_precision_policy,
    run_promoted_exterior_component,
    run_promoted_full_ladder_validation,
    run_component,
    full_ladder_validation_policy,
)
from windows_solver.response_uncertainty import ComplexDisk, exterior_response_disk
from windows_solver.partial_component_checkpoint import PartialComponentJournal


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
            "determinant_error_abs": str(1.0e-9 * abs(converted)),
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
            determinant_error_abs=1.0e-9 * abs(converted),
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


class PromotedExteriorDerivativeTests(unittest.TestCase):
    @staticmethod
    def _baseline_with_derivative_evidence(leaf):
        baseline = _promoted_baseline(
            leaf.job,
            conditioning_mechanism=leaf.mechanism_id,
        )
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
            self.assertEqual(len(journals), 1)
            stopped = PartialComponentJournal.load(journals[0])
            self.assertEqual(len(stopped.entries), 1)
            baseline_entry = next(iter(stopped.entries.values()))
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
            final = PartialComponentJournal.load(journals[0])
            self.assertTrue(final.complete)
            self.assertEqual(len(final.entries), 5)

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
        missing = replace(
            missing,
            primary_acceptance=replace(
                missing.primary_acceptance,
                derivative_authentication=None,
            ),
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
            "MISSING_FREQUENCY_DERIVATIVE_AUTHENTICATION",
        )
        self.assertEqual(missing_backend.sample_amplitudes, [])

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
        backend = FixedRootOnlyBackend(leaf.job, baseline)

        result = run_promoted_exterior_component(
            leaf.job,
            backend,
            primary_predictor=baseline.omega,
            derivative_step=0.004,
        ).to_mapping()

        self.assertEqual(result["status"], "DERIVATIVE_UNRESOLVED")
        self.assertEqual(backend.sample_amplitudes, [])
        self.assertEqual(
            result["derivative_evidence"]["failure_code"],
            "DETERMINANT_ERROR_MODEL_UNAVAILABLE",
        )
        self.assertEqual(
            result["derivative_evidence"]["math_review_blocker"],
            "TODO: [HUMAN MATH REVIEW REQUIRED - fixed-root exterior "
            "determinant error model is unavailable]",
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
        runtime = {
            "precision_digits": 80,
            "working_precision_bits": 298,
            "semantic_precision_tier": "bigfloat-80",
            "refinement_level": 0,
            "regularised_gsn_precision_policy": dict(
                regularised_gsn_precision_policy(leaf.mechanism_id)
            ),
        }
        result = run_promoted_exterior_component(
            leaf.job,
            FixedRootOnlyBackend(
                leaf.job,
                baseline,
                runtime_identity=runtime_identity_sha256({}),
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
        }
        outcome = StageOutcome(
            digits=80,
            numerical_state="CONVERGED",
            component_result=payload,
            local_disk_radius_abs=sum(result.error_channels.values()),
            signed_error_channels=synthetic_stage_signed_error_channels(
                payload,
                sum(result.error_channels.values()),
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
            signed_error_channels=synthetic_stage_signed_error_channels(
                tampered_payload,
                sum(result.error_channels.values()),
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
        runtime = {
            "precision_digits": 80,
            "working_precision_bits": 298,
            "semantic_precision_tier": "bigfloat-80",
            "refinement_level": 0,
            "regularised_gsn_precision_policy": dict(
                regularised_gsn_precision_policy(leaf.mechanism_id)
            ),
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
        }
        outcome = StageOutcome(
            digits=80,
            numerical_state="CONVERGED",
            component_result=payload,
            local_disk_radius_abs=sum(result.error_channels.values()),
            signed_error_channels=synthetic_stage_signed_error_channels(
                payload,
                sum(result.error_channels.values()),
            ),
            self_refinement_enclosed=None,
            discrepancy_from_previous_abs=None,
            discrepancy_enclosed=None,
        )

        with self.assertRaisesRegex(ValueError, "sample precision"):
            _validate_component_result(leaf, outcome)


if __name__ == "__main__":
    unittest.main()
