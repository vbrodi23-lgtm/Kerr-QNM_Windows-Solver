from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace
import unittest

from windows_solver.contracts import canonical_json_bytes
from windows_solver.julia_response_backend import (
    FIXED_ROOT_SURVEY_BATCH_OPERATION,
    JuliaFixedRootSurveyBatch,
    JuliaPrecisionRootBackend,
    JuliaResponseBackendError,
)
from windows_solver.promoted_control_calibration import (
    load_default_calibration_receipt,
)
from windows_solver.response_batches import (
    PrecisionCapabilities,
    build_campaign_plan,
)
from windows_solver.response_engine import (
    BINARY64_FIXED_ROOT_SAMPLE_ROLES,
    BINARY64_FIXED_ROOT_SURVEY_IDENTITY,
    CANONICAL_EXTERIOR_BACKGROUND_IDENTITY,
    NumericalPolicy,
    VettedNativeDeterminantKernel,
)


def _job():
    plan = build_campaign_plan(
        policy=NumericalPolicy(),
        backend_identity=VettedNativeDeterminantKernel.identity,
        precision_capabilities=PrecisionCapabilities((64, 80, 120)),
    )
    return next(
        leaf.job
        for leaf in plan.leaves
        if leaf.job.mechanism_id == "exterior-light-ring"
    )


def _conditioning(request) -> dict[str, object]:
    policy = request["policy"]
    return {
        "schema": "windows-solver.fixed-root-survey-conditioning/1",
        "determinant_family": "exterior-wronskian/v1",
        "homogeneous_representation": policy["homogeneous_representation"],
        "branch_convention": policy["branch_convention"],
        "determinant_convention": policy["determinant_convention"],
        "determinant_normalisation": policy["determinant_normalisation"],
        "maximum_series_digits_lost": "1",
        "maximum_recurrence_digits_lost": "1",
        "minimum_asymptotic_predicted_reliable_digits": "35",
        "endpoint_remainders_regular": True,
        "maximum_endpoint_reconstruction_error": "1e-30",
        "maximum_contour_angle_deformation": "0",
        "predicted_reliable_digits": "34",
        "required_reliable_digits": "20",
        "precision_limited": False,
        "determinant_count": 1,
    }


class _BatchAdapter:
    runtime_provenance = {
        "julia_version": "1.10.11",
        "julia_executable_sha256": "a" * 64,
        "julia_manifest_sha256": "b" * 64,
        "worker_sha256": "c" * 64,
        "runtime_policy_sha256": "d" * 64,
        "scientific_sources": [],
    }

    def __init__(self) -> None:
        self.requests: list[dict[str, object]] = []

    def evaluate_for_validation(self, request):
        self.requests.append(request)
        request_sha256 = hashlib.sha256(canonical_json_bytes(request)).hexdigest()
        response = {
            "schema_version": 1,
            "status": "ok",
            "operation": FIXED_ROOT_SURVEY_BATCH_OPERATION,
            "identity": BINARY64_FIXED_ROOT_SURVEY_IDENTITY,
            "scientific_operation_identity": request[
                "scientific_operation_identity"
            ],
            "request_sha256": request_sha256,
            "leaf_id": request["leaf_id"],
            "job_id": request["job_id"],
            "root_reference_id": request["root_reference_id"],
            "root_seal_sha256": request["root_seal_sha256"],
            "branch_identity": request["branch_identity"],
            "semantic_precision_tier": request["semantic_precision_tier"],
            "working_precision_bits": request["working_precision_bits"],
            "sample_roles": request["sample_roles"],
            "maximum_sample_count": request["maximum_sample_count"],
            "sample_count": len(request["samples"]),
            "samples": [
                {
                    "role": sample["role"],
                    "omega": sample["omega"],
                    "amplitude": sample["amplitude"],
                    "determinant": {
                        "real": str(index + 1),
                        "imaginary": str(-(index + 1)),
                    },
                    "numerical_conditioning": _conditioning(request),
                }
                for index, sample in enumerate(request["samples"])
            ],
        }
        return SimpleNamespace(
            response=response,
            request_binding=dict(request),
            request_sha256=request_sha256,
            runtime_identity_sha256="e" * 64,
            reused=False,
            cached_worker_response_receipt=None,
        )


def _backend(adapter: _BatchAdapter, digits: int = 40):
    receipt = load_default_calibration_receipt()
    return JuliaPrecisionRootBackend(
        VettedNativeDeterminantKernel.identity,
        adapter,
        digits,
        empirical_control_profile=receipt.budget_for(
            "exterior-wronskian/v1", digits
        ),
        calibration_receipt=receipt,
    )


class JuliaFixedRootSurveyBatchTests(unittest.TestCase):
    def test_one_worker_request_returns_the_ordered_nine_sample_batch(self):
        job = _job()
        adapter = _BatchAdapter()
        backend = _backend(adapter)

        batch = backend.fixed_root_survey_batch(
            job,
            fixed_root=job.root.omega,
            root_seal_sha256="1" * 64,
            branch_identity=job.root.branch_id,
            sample_roles=BINARY64_FIXED_ROOT_SAMPLE_ROLES,
        )

        self.assertIsInstance(batch, JuliaFixedRootSurveyBatch)
        self.assertEqual(len(adapter.requests), 1)
        self.assertEqual(batch.sample_roles, BINARY64_FIXED_ROOT_SAMPLE_ROLES)
        self.assertEqual(batch.sample_count, 9)
        request = adapter.requests[0]
        self.assertEqual(request["operation"], FIXED_ROOT_SURVEY_BATCH_OPERATION)
        self.assertEqual(request["precision_digits"], 40)
        self.assertEqual(request["maximum_sample_count"], 9)
        for sample in request["samples"][:5]:
            self.assertNotIn("support", sample)
        for sample in request["samples"][5:]:
            self.assertEqual(set(sample["support"]), {
                "lower", "upper", "centre", "half_width"
            })
        forbidden = {
            "determinant_error_model",
            "determinant_error_required_term_classes",
            "determinant_error_certificate_statement",
            "human_math_review_receipt_status",
            "independent_reference_fixture_receipt_status",
            "promoted_root_readout_policy",
        }
        self.assertTrue(forbidden.isdisjoint(request["policy"]))

    def test_canonical_five_and_reused_mechanism_four_are_valid_plans(self):
        job = _job()
        for operation_identity, roles in (
            (
                CANONICAL_EXTERIOR_BACKGROUND_IDENTITY,
                BINARY64_FIXED_ROOT_SAMPLE_ROLES[:5],
            ),
            (
                BINARY64_FIXED_ROOT_SURVEY_IDENTITY,
                BINARY64_FIXED_ROOT_SAMPLE_ROLES[5:],
            ),
        ):
            with self.subTest(operation_identity=operation_identity):
                adapter = _BatchAdapter()
                batch = _backend(adapter).fixed_root_survey_batch(
                    job,
                    fixed_root=job.root.omega,
                    root_seal_sha256="2" * 64,
                    branch_identity=job.root.branch_id,
                    scientific_operation_identity=operation_identity,
                    sample_roles=roles,
                )
                self.assertEqual(batch.sample_roles, roles)
                self.assertEqual(len(adapter.requests), 1)

    def test_invalid_roles_and_bf120_are_rejected_before_launch(self):
        job = _job()
        invalid_plans = (
            ("D0", "D0"),
            ("UNKNOWN",),
            tuple(reversed(BINARY64_FIXED_ROOT_SAMPLE_ROLES)),
            BINARY64_FIXED_ROOT_SAMPLE_ROLES + ("D0",),
        )
        for roles in invalid_plans:
            with self.subTest(roles=roles):
                adapter = _BatchAdapter()
                with self.assertRaises(ValueError):
                    _backend(adapter).preview_fixed_root_survey_request(
                        job,
                        fixed_root=job.root.omega,
                        root_seal_sha256="3" * 64,
                        branch_identity=job.root.branch_id,
                        sample_roles=roles,
                    )
                self.assertEqual(adapter.requests, [])

        adapter = _BatchAdapter()
        with self.assertRaises(ValueError):
            _backend(adapter, 120).preview_fixed_root_survey_request(
                job,
                fixed_root=job.root.omega,
                root_seal_sha256="4" * 64,
                branch_identity=job.root.branch_id,
                sample_roles=BINARY64_FIXED_ROOT_SAMPLE_ROLES,
            )
        self.assertEqual(adapter.requests, [])

    def test_response_request_binding_and_order_are_fail_closed(self):
        job = _job()

        class _BadAdapter(_BatchAdapter):
            def evaluate_for_validation(self, request):
                evaluation = super().evaluate_for_validation(request)
                evaluation.response["samples"] = list(
                    reversed(evaluation.response["samples"])
                )
                return evaluation

        with self.assertRaises(JuliaResponseBackendError):
            _backend(_BadAdapter()).fixed_root_survey_batch(
                job,
                fixed_root=job.root.omega,
                root_seal_sha256="5" * 64,
                branch_identity=job.root.branch_id,
                sample_roles=BINARY64_FIXED_ROOT_SAMPLE_ROLES,
            )

    def test_worker_survey_function_has_no_root_or_certificate_calls(self):
        worker = (
            Path(__file__).parents[1]
            / "src/windows_solver/data/julia/m02_worker.jl"
        ).read_text(encoding="utf-8")
        start = worker.index("function fixed_root_survey_batch_fields")
        end = worker.index("\nfunction fixed_root_determinant_sample_fields", start)
        body = worker[start:end]
        for prohibited in (
            "select_worker_outer_endpoint_pair",
            "authenticated_determinant_progress",
            "exterior_cross_precision_disagreement",
            "tight_control_request",
            "solve_phase",
            "bounded_newton",
        ):
            self.assertNotIn(prohibited, body)
        self.assertIn("raw_determinant_progress", body)

    def test_fixed_root_policy_shape_is_checked_only_by_fixed_root_parser(self):
        worker = (
            Path(__file__).parents[1]
            / "src/windows_solver/data/julia/m02_worker.jl"
        ).read_text(encoding="utf-8")
        promoted_start = worker.index("function flatten_request(document)")
        promoted_end = worker.index(
            "\nfunction flatten_fixed_root_survey_request", promoted_start
        )
        fixed_start = promoted_end
        fixed_end = worker.index(
            "\nfunction validate_fixed_root_survey_policy", fixed_start
        )

        self.assertNotIn(
            "FIXED_ROOT_SURVEY_POLICY_FIELDS",
            worker[promoted_start:promoted_end],
        )
        self.assertIn(
            "FIXED_ROOT_SURVEY_POLICY_FIELDS",
            worker[fixed_start:fixed_end],
        )


if __name__ == "__main__":
    unittest.main()
