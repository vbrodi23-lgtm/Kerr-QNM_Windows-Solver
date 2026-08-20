from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import unittest

from windows_solver.julia_response_backend import JuliaPrecisionRootBackend
from windows_solver.promoted_control_calibration import (
    load_default_calibration_receipt,
)
from windows_solver.response_batches import PrecisionCapabilities, build_campaign_plan
from windows_solver.response_engine import NumericalPolicy, VettedNativeDeterminantKernel


WORKER = (
    Path(__file__).resolve().parents[1]
    / "src/windows_solver/data/julia/m02_worker.jl"
)

EXTERIOR_CERTIFICATE_FIELDS = frozenset({
    "determinant_error_model",
    "determinant_error_required_term_classes",
    "determinant_error_missing_evidence_outcome",
    "determinant_error_certificate_statement",
    "determinant_error_preceding_precision_tier",
})

# These provenance hashes bind the nested Python request/receipt.  The worker
# does not consume them as flattened numerical controls.
DELIBERATELY_NESTED_EXTERIOR_POLICY_FIELDS = frozenset({
    "empirical_control_profile_sha256",
    "promoted_control_calibration_receipt_sha256",
})

EXTERIOR_FLATTENED_POLICY_FIELDS = frozenset({
    "angular_pad",
    "asymptotic_series_evaluation",
    "branch_convention",
    "branch_enclosure_radius_abs",
    "conditioning_diagnostics",
    "coordinate_ode_absolute_tolerance",
    "coordinate_ode_relative_tolerance",
    "determinant_convention",
    "determinant_error_certificate_statement",
    "determinant_error_missing_evidence_outcome",
    "determinant_error_model",
    "determinant_error_preceding_precision_tier",
    "determinant_error_required_term_classes",
    "determinant_error_safety_factor",
    "determinant_family",
    "determinant_normalisation",
    "endpoint_series_order",
    "factored_remainder_state_convention",
    "frequency_step",
    "frequency_step_maximum",
    "frequency_step_minimum",
    "homogeneous_ode_absolute_tolerance",
    "homogeneous_ode_relative_tolerance",
    "homogeneous_representation",
    "horizon_determinant_chart",
    "horizon_endpoint_rho_candidates",
    "horizon_endpoint_rho_floor",
    "horizon_maximum_endpoint_distance",
    "horizon_rho_inner_min",
    "human_math_review_receipt_sha256",
    "human_math_review_receipt_status",
    "independent_reference_fixture_receipt_sha256",
    "independent_reference_fixture_receipt_status",
    "max_newton_iterations",
    "ode_absolute_tolerance",
    "ode_relative_tolerance",
    "promoted_root_readout_policy",
    "radial_derivative_convention",
    "readout_radius",
    "regular_remainder_contract",
    "reliable_digit_safety_margin",
    "required_digit_guard",
    "rho_in",
    "rho_out",
    "rho_out_candidate_schedule",
    "root_correction_tolerance",
    "scattering_chart_safety_factor",
    "scattering_coefficient_extraction",
    "scattering_column_convention",
    "scattering_diagnostics_applicable",
    "support_subinterval_count",
})


class PromotedExteriorRequestFlatteningTests(unittest.TestCase):
    def test_every_generated_exterior_policy_field_is_flattened_or_nested(self):
        """Catches Python/Julia exterior policy drift before a promoted solve."""

        plan = build_campaign_plan(
            policy=NumericalPolicy(),
            backend_identity=VettedNativeDeterminantKernel.identity,
            precision_capabilities=PrecisionCapabilities((64, 80, 120)),
        )
        job = next(
            leaf.job
            for leaf in plan.leaves
            if leaf.mechanism_id == "exterior-light-ring"
        )
        receipt = load_default_calibration_receipt()
        backend = JuliaPrecisionRootBackend(
            job.backend_identity,
            SimpleNamespace(runtime_provenance={}),
            80,
            empirical_control_profile=receipt.budget_for(
                "exterior-wronskian/v1", 80
            ),
            calibration_receipt=receipt,
        )
        request = backend._request(job, 0.0j)
        policy_fields = frozenset(request["policy"])

        self.assertEqual(
            policy_fields,
            EXTERIOR_FLATTENED_POLICY_FIELDS
            | DELIBERATELY_NESTED_EXTERIOR_POLICY_FIELDS,
        )
        self.assertEqual(
            EXTERIOR_CERTIFICATE_FIELDS
            & DELIBERATELY_NESTED_EXTERIOR_POLICY_FIELDS,
            frozenset(),
        )

        worker = WORKER.read_text(encoding="utf-8")
        flatten_start = worker.index("function flatten_request(")
        flatten_end = worker.index(
            "function validate_regularised_gsn_policy(", flatten_start
        )
        flatten = worker[flatten_start:flatten_end]
        exterior_start = flatten.index('if mechanism != "horizon-admittance"')
        exterior_end = flatten.index("if haskey(document,", exterior_start)
        exterior = flatten[exterior_start:exterior_end]

        for field in EXTERIOR_FLATTENED_POLICY_FIELDS:
            source = exterior if field in EXTERIOR_CERTIFICATE_FIELDS else flatten
            with self.subTest(field=field):
                self.assertIn(f'"{field}"', source)
        for field in DELIBERATELY_NESTED_EXTERIOR_POLICY_FIELDS:
            with self.subTest(field=field):
                self.assertNotIn(f'"{field}"', flatten)
