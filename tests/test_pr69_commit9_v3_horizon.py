"""PR69 Commit 9: v3 horizon mathematical-identity regressions."""

from __future__ import annotations

import copy
import hashlib
import unittest
from pathlib import Path
from types import SimpleNamespace

from windows_solver.campaign_runtime import (
    build_schema11_horizon_record,
    build_schema11_horizon_stage,
)
from windows_solver.campaign_record_intake import (
    assess_campaign_record_for_current_runtime,
)
from windows_solver.contracts import canonical_json_bytes
from windows_solver.response_engine import DeterminantPartials, NumericalPolicy
from windows_solver.native_response_kernel import VettedNativeDeterminantKernel
from windows_solver.response_batches import (
    NativeCampaignStageBackend,
    PrecisionCapabilities,
    build_campaign_plan,
    forensic_v2_scientific_computation_identity_sha256,
    validate_schema11_horizon_record,
)
from windows_solver.response_uncertainty import (
    ComplexDisk,
    ZeroContainingDiskError,
    horizon_chart_base_partials,
    horizon_frequency_disk,
    horizon_response_disk,
)
from windows_solver.root_evidence import AuthenticatedRootEvidence
from windows_solver.reviewed_determinant_error import ExteriorDeterminantErrorChannels


class Commit9V3HorizonTests(unittest.TestCase):
    @staticmethod
    def _horizon_leaf():
        plan = build_campaign_plan(
            policy=NumericalPolicy(),
            backend_identity=VettedNativeDeterminantKernel.identity,
            precision_capabilities=PrecisionCapabilities((64, 80)),
        )
        return next(
            leaf
            for leaf in plan.leaves
            if leaf.role == "primary" and leaf.mechanism_id == "horizon-admittance"
        )

    def test_approved_response_uses_negative_explicit_horizon_numerator(self) -> None:
        numerator = ComplexDisk(3.0 - 2.0j, 1.0e-8)
        horizon_frequency = ComplexDisk(0.4 + 0.1j, 2.0e-9)
        derivative = ComplexDisk(5.0 + 7.0j, 3.0e-8)

        response = horizon_response_disk(
            horizon_numerator=numerator,
            horizon_frequency=horizon_frequency,
            determinant_derivative=derivative,
        )

        self.assertEqual(
            response.centre,
            -numerator.centre
            / (2.0j * horizon_frequency.centre * derivative.centre),
        )
        self.assertGreater(response.radius, 0.0)

    def test_horizon_chart_has_zero_frequency_partial_at_delta_b_zero(self) -> None:
        root = ComplexDisk(0.8 + 0.3j, 2.0e-9)
        omega_h = ComplexDisk(0.2 + 0.0j, 1.0e-10)
        p_h = horizon_frequency_disk(
            root=root,
            azimuthal_index=2,
            background_omega_h=omega_h,
        )

        partials = horizon_chart_base_partials(p_h)

        self.assertEqual(partials.dR_domega_at_deltaB, 0.0j)
        self.assertEqual(
            partials.dR_ddeltaB.centre,
            1.0 / (2.0j * p_h.centre),
        )
        with self.assertRaises(ZeroContainingDiskError):
            horizon_chart_base_partials(ComplexDisk(0.0j, 1.0e-9))

    def test_orientation_and_common_rescaling_leave_v3_quotient_invariant(self) -> None:
        p_h = ComplexDisk(0.4 + 0.1j, 1.0e-9)
        d_h = ComplexDisk(3.0 - 2.0j, 2.0e-9)
        d_omega = ComplexDisk(5.0 + 7.0j, 3.0e-9)

        original = horizon_response_disk(
            horizon_numerator=d_h,
            horizon_frequency=p_h,
            determinant_derivative=d_omega,
        )
        reversed_orientation = horizon_response_disk(
            horizon_numerator=-d_h,
            horizon_frequency=p_h,
            determinant_derivative=-d_omega,
        )
        scale = ComplexDisk(2.0 - 1.0j, 0.0, exact_zero_radius=True)
        rescaled = horizon_response_disk(
            horizon_numerator=d_h * scale,
            horizon_frequency=p_h,
            determinant_derivative=d_omega * scale,
        )

        self.assertEqual(original.centre, reversed_orientation.centre)
        self.assertAlmostEqual(original.centre.real, rescaled.centre.real, places=14)
        self.assertAlmostEqual(original.centre.imag, rescaled.centre.imag, places=14)

    def test_v3_root_evidence_rejects_adapter_invented_zero_radius(self) -> None:
        leaf = self._horizon_leaf()

        with self.assertRaisesRegex(ValueError, "root uncertainty radius"):
            AuthenticatedRootEvidence.from_authenticated_disk(
                leaf,
                fixed_root=leaf.job.root.omega,
                root_uncertainty_radius=0.0,
                source_receipt_sha256="a" * 64,
                evidence_level="SCREENED",
            )

        evidence = AuthenticatedRootEvidence.from_authenticated_disk(
            leaf,
            fixed_root=leaf.job.root.omega,
            root_uncertainty_radius=1.0e-9,
            source_receipt_sha256="a" * 64,
            evidence_level="CERTIFIED",
        )

        self.assertEqual(evidence.evidence_level, "CERTIFIED")
        self.assertEqual(
            AuthenticatedRootEvidence.from_mapping(evidence.to_mapping()).evidence_level,
            "CERTIFIED",
        )
        self.assertEqual(evidence.root_disk.radius, 1.0e-9)

    def test_binary64_horizon_adapter_emits_authenticated_v3_record(self) -> None:
        plan = self._horizon_plan()
        leaf = self._horizon_leaf()
        root_evidence = AuthenticatedRootEvidence.from_authenticated_disk(
            leaf,
            fixed_root=leaf.job.root.omega,
            root_uncertainty_radius=1.0e-10,
            source_receipt_sha256="b" * 64,
            evidence_level="SCREENED",
        )
        horizon_radius = 1.0 + (1.0 - leaf.job.spin * leaf.job.spin) ** 0.5
        omega_h = leaf.job.spin / (2.0 * horizon_radius)
        p_h = leaf.job.root.omega - leaf.job.mode.m * omega_h
        d_h = 3.0 - 2.0j
        d_omega = 5.0 + 7.0j

        class Kernel:
            identity = VettedNativeDeterminantKernel.identity

            def horizon_partials(self, **_kwargs):
                return DeterminantPartials(
                    frequency_derivative=d_omega,
                    coordinate_derivative=d_h / (2.0j * p_h),
                    simple_root_valid=True,
                    frequency_derivative_error_abs=3.0e-10,
                    dD_dR=d_h,
                    dD_dR_error_abs=2.0e-10,
                    dD_ddeltaB=d_h / (2.0j * p_h),
                    dD_domega=d_omega,
                    dD_domega_error_abs=3.0e-10,
                )

        backend = NativeCampaignStageBackend(
            SimpleNamespace(identity=Kernel.identity, kernel=Kernel()),
            PrecisionCapabilities((64,)),
            SimpleNamespace(
                record_artifact_ids=(),
                path=Path("synthetic-gsn-cache"),
                sha256="a" * 64,
                parameter_pairs=(),
            ),
        )
        outcome = backend.execute_horizon_stage(leaf, root_evidence=root_evidence)
        stage, _stage_sha256 = build_schema11_horizon_stage(
            outcome,
            precision_tier="binary64",
            operation_identity="binary64-horizon-production/v3",
        )
        record = build_schema11_horizon_record(
            plan,
            leaf,
            stages=(stage,),
            retained_centre=stage["response_disk"]["centre"],
            state="PRODUCED",
        )

        result = outcome.component_result["result"]
        self.assertEqual(
            result["response"],
            {
                "real": (-d_h / (2.0j * p_h * d_omega)).real,
                "imaginary": (-d_h / (2.0j * p_h * d_omega)).imag,
            },
        )
        self.assertEqual(
            result["analytic_horizon_evidence"]["dD_dR"]["centre"],
            {"real": d_h.real, "imaginary": d_h.imag},
        )
        self.assertEqual(result["analytic_horizon_evidence"]["worker_launch_count"], 0)
        self.assertEqual(
            record["horizon_mathematics"]["operation_identity"],
            "binary64-horizon-production/v3",
        )
        mixed_normalisation = copy.deepcopy(record)
        mixed_stage = mixed_normalisation["stages"][0]
        mixed_stage["component_result"]["result"][
            "analytic_horizon_evidence"
        ]["mathematics"]["determinant_convention_identity"] = (
            "foreign-normalisation/v1"
        )
        mixed_stage["stage_sha256"] = hashlib.sha256(canonical_json_bytes({
            key: value for key, value in mixed_stage.items() if key != "stage_sha256"
        })).hexdigest()
        mixed_normalisation["record_sha256"] = hashlib.sha256(canonical_json_bytes({
            key: value for key, value in mixed_normalisation.items()
            if key != "record_sha256"
        })).hexdigest()
        with self.assertRaisesRegex(ValueError, "mathematical policy"):
            validate_schema11_horizon_record(plan, leaf, mixed_normalisation)
        stale = copy.deepcopy(record)
        stale.pop("horizon_mathematics")
        stale_stage = stale["stages"][0]
        stale_stage["operation_identity"] = "binary64-horizon-production/v2"
        stale_result = stale_stage["component_result"]["result"]
        stale_result["component_scientific_identity"] = (
            "binary64-horizon-analytic-component/v1"
        )
        stale_result["response_method"] = (
            "binary64-fixed-root-horizon-response/v1"
        )
        stale_stage["stage_sha256"] = hashlib.sha256(canonical_json_bytes({
            key: value for key, value in stale_stage.items() if key != "stage_sha256"
        })).hexdigest()
        stale["scientific_computation_identity"] = (
            forensic_v2_scientific_computation_identity_sha256(plan, leaf)
        )
        stale["record_sha256"] = hashlib.sha256(canonical_json_bytes({
            key: value for key, value in stale.items() if key != "record_sha256"
        })).hexdigest()
        intake = assess_campaign_record_for_current_runtime(
            plan, leaf.leaf_id, stale
        )
        self.assertTrue(intake.forensic_only)
        self.assertFalse(intake.response_admissible)

    def test_exterior_error_channels_are_additive_and_block_without_calibration(self) -> None:
        channels = ExteriorDeterminantErrorChannels(
            precision=1.0,
            ode_controls=2.0,
            endpoint_order=3.0,
            match_readout=4.0,
            angular_data=5.0,
            arithmetic_rounding=6.0,
        )

        self.assertEqual(channels.unscaled_additive_radius, 21.0)
        self.assertEqual(
            channels.screening_status(calibration_receipt=None),
            "BLOCKED_BY_REVIEWED_ERROR_EVIDENCE",
        )

    @staticmethod
    def _horizon_plan():
        return build_campaign_plan(
            policy=NumericalPolicy(),
            backend_identity=VettedNativeDeterminantKernel.identity,
            precision_capabilities=PrecisionCapabilities((64, 80)),
        )


if __name__ == "__main__":
    unittest.main()
