from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

import windows_solver.response_engine as response_engine
from windows_solver import julia_response_backend
from windows_solver.contracts import canonical_json_bytes
from windows_solver.julia_response_backend import JuliaPrecisionRootBackend
from windows_solver.partial_component_checkpoint import PartialComponentJournal
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
    def test_leaf_42_request_preserves_receipt_safety_factor_json_type(self):
        plan = build_campaign_plan(
            policy=NumericalPolicy(),
            backend_identity=VettedNativeDeterminantKernel.identity,
            precision_capabilities=PrecisionCapabilities((64, 80, 120)),
        )
        receipt = load_default_calibration_receipt()
        leaf_42 = next(
            leaf
            for leaf in plan.leaves
            if leaf.leaf_id
            == "b-prime-leaf-5a27a5fdc15f95de33d6773b16f89a9f594fe5ffd018f9ee94bbab91949fd653"
        )
        self.assertEqual(leaf_42.mechanism_id, "exterior-light-ring")
        self.assertEqual(
            (leaf_42.job.mode.ell, leaf_42.job.mode.m, leaf_42.job.mode.n),
            (2, 2, 1),
        )
        self.assertEqual(leaf_42.job.spin, 0.95)

        exterior_backend = JuliaPrecisionRootBackend(
            leaf_42.job.backend_identity,
            SimpleNamespace(runtime_provenance={}),
            80,
            empirical_control_profile=receipt.budget_for(
                "exterior-wronskian/v1", 80
            ),
            calibration_receipt=receipt,
        )
        exterior_request = json.loads(
            canonical_json_bytes(exterior_backend._request(leaf_42.job, 0.0j))
        )
        exterior_value = exterior_request["policy"][
            "determinant_error_safety_factor"
        ]

        self.assertIs(type(exterior_value), int)
        self.assertEqual(exterior_value, 64)
        self.assertEqual(exterior_value, receipt.certificate_safety_factor)
        self.assertEqual(
            hashlib.sha256(
                canonical_json_bytes(exterior_request)
            ).hexdigest(),
            "95934bdfb8cb9ccc070ba1a601b8c41a8cedecec7113b3228fc2d1c82ee11637",
        )

        horizon_leaf = next(
            leaf
            for leaf in plan.leaves
            if leaf.mechanism_id == "horizon-admittance"
            and leaf.job.mode == leaf_42.job.mode
            and leaf.job.spin == leaf_42.job.spin
        )
        horizon_backend = JuliaPrecisionRootBackend(
            horizon_leaf.job.backend_identity,
            SimpleNamespace(runtime_provenance={}),
            80,
            empirical_control_profile=receipt.budget_for(
                "horizon-scattering/v1", 80
            ),
            calibration_receipt=receipt,
        )
        horizon_request = json.loads(
            canonical_json_bytes(horizon_backend._request(horizon_leaf.job, 0.0j))
        )
        horizon_value = horizon_request["policy"][
            "determinant_error_safety_factor"
        ]

        self.assertIs(type(horizon_value), str)
        self.assertEqual(horizon_value, "64")
        self.assertEqual(
            hashlib.sha256(
                canonical_json_bytes(horizon_request)
            ).hexdigest(),
            "da7c91c801e13c8d91afdf6a8d2ed235a1d7363917b7ed5dd7916623e118532d",
        )

    def test_policy_fragment_merger_rejects_duplicate_fields(self):
        with self.assertRaisesRegex(
            ValueError, "duplicate promoted policy field: shared"
        ):
            julia_response_backend._merge_policy_fragments(
                {"shared": 64}, {"shared": "64"}
            )

    def test_exterior_receipt_safety_factor_is_exactly_integer_64(self):
        plan = build_campaign_plan(
            policy=NumericalPolicy(),
            backend_identity=VettedNativeDeterminantKernel.identity,
            precision_capabilities=PrecisionCapabilities((64, 80, 120)),
        )
        job = next(
            leaf.job
            for leaf in plan.leaves
            if leaf.leaf_id
            == "b-prime-leaf-5a27a5fdc15f95de33d6773b16f89a9f594fe5ffd018f9ee94bbab91949fd653"
        )
        receipt = load_default_calibration_receipt()

        class ReceiptProxy:
            def __init__(self, safety_factor):
                self.certificate_safety_factor = safety_factor

            def __getattr__(self, name):
                return getattr(receipt, name)

        for invalid in ("64", 64.0, True, 63):
            with self.subTest(invalid=invalid):
                forged = ReceiptProxy(invalid)
                backend = JuliaPrecisionRootBackend(
                    job.backend_identity,
                    SimpleNamespace(runtime_provenance={}),
                    80,
                    empirical_control_profile=receipt.budget_for(
                        "exterior-wronskian/v1", 80
                    ),
                    calibration_receipt=forged,
                )
                with self.assertRaisesRegex(
                    ValueError,
                    "exterior determinant certificate safety factor is invalid",
                ):
                    backend._request(job, 0.0j)

    def test_horizon_geometry_cannot_own_certificate_safety_factor(self):
        self.assertNotIn(
            "determinant_error_safety_factor",
            julia_response_backend.horizon_geometry_controls(),
        )

    def test_leaf42_partial_journal_rolls_forward_without_deleting_old_plan(self):
        """Request-SHA ownership isolates old and corrected journal plans."""

        plan = build_campaign_plan(
            policy=NumericalPolicy(),
            backend_identity=VettedNativeDeterminantKernel.identity,
            precision_capabilities=PrecisionCapabilities((64, 80, 120)),
        )
        leaf_42 = next(
            leaf
            for leaf in plan.leaves
            if leaf.leaf_id
            == "b-prime-leaf-5a27a5fdc15f95de33d6773b16f89a9f594fe5ffd018f9ee94bbab91949fd653"
        )
        receipt = load_default_calibration_receipt()
        corrected = JuliaPrecisionRootBackend(
            leaf_42.job.backend_identity,
            SimpleNamespace(runtime_provenance={}),
            80,
            empirical_control_profile=receipt.budget_for(
                "exterior-wronskian/v1", 80
            ),
            calibration_receipt=receipt,
        )

        class ObsoleteStringPolicyPreview:
            identity = corrected.identity
            digits = corrected.digits
            refinement = corrected.refinement

            @staticmethod
            def _obsolete(request):
                value = deepcopy(request)
                value["policy"]["determinant_error_safety_factor"] = "64"
                return value

            def preview_root_request(self, *args, **kwargs):
                return self._obsolete(
                    corrected.preview_root_request(*args, **kwargs)
                )

            def preview_fixed_root_request(self, *args, **kwargs):
                return self._obsolete(
                    corrected.preview_fixed_root_request(*args, **kwargs)
                )

        with tempfile.TemporaryDirectory() as temporary, patch.dict(
            "os.environ",
            {"KERR_QNM_PARTIAL_COMPONENT_JOURNAL_ROOT": temporary},
        ):
            obsolete = response_engine._journaled_promoted_exterior_backend(
                leaf_42.job,
                ObsoleteStringPolicyPreview(),
                predictor=leaf_42.job.root.omega,
                derivative_step=leaf_42.job.policy.epsilons[0],
                validation_reason=None,
            )
            obsolete_path = obsolete._journal.path
            obsolete_bytes = obsolete_path.read_bytes()
            obsolete_ids = obsolete._journal.expected_work_unit_ids

            current = response_engine._journaled_promoted_exterior_backend(
                leaf_42.job,
                corrected,
                predictor=leaf_42.job.root.omega,
                derivative_step=leaf_42.job.policy.epsilons[0],
                validation_reason=None,
            )
            current_path = current._journal.path
            current_ids = current._journal.expected_work_unit_ids

            self.assertNotEqual(current_path, obsolete_path)
            self.assertTrue(current_path.is_file())
            self.assertTrue(obsolete_path.is_file())
            self.assertEqual(obsolete_path.read_bytes(), obsolete_bytes)
            self.assertTrue(set(current_ids).isdisjoint(obsolete_ids))
            self.assertEqual(
                PartialComponentJournal.load(obsolete_path)
                .expected_work_unit_ids,
                obsolete_ids,
            )
            self.assertEqual(
                PartialComponentJournal.load(current_path)
                .expected_work_unit_ids,
                current_ids,
            )

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
