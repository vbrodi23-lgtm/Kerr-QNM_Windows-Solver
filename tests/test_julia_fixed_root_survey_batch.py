from __future__ import annotations

from dataclasses import replace
import hashlib
from pathlib import Path
from types import SimpleNamespace
import unittest

from windows_solver.contracts import canonical_json_bytes
from windows_solver.julia_response_backend import (
    FIXED_ROOT_SURVEY_BATCH_OPERATION,
    FIXED_ROOT_SURVEY_BATCH_SCHEMA,
    FIXED_ROOT_SURVEY_BATCH_RESPONSE_SCHEMA,
    FixedRootSurveyPlan,
    JuliaFixedRootSurveyBatch,
    JuliaPrecisionRootBackend,
    JuliaResponseBackendError,
    _worker_request_document,
)
from windows_solver.operation_control import execution_identity_from_request
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
        "schema": "windows-solver.fixed-root-survey-conditioning/2",
        "fixed_root_reliability_target_abs": request[
            "fixed_root_reliability_target_abs"
        ],
        "fixed_root_reliability_rule": request["fixed_root_reliability_rule"],
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
        execution_identity = execution_identity_from_request(
            request,
            request_sha256=request_sha256,
        )
        response = {
            "schema_version": 2,
            "schema": FIXED_ROOT_SURVEY_BATCH_RESPONSE_SCHEMA,
            "status": "ok",
            "operation": FIXED_ROOT_SURVEY_BATCH_OPERATION,
            "identity": BINARY64_FIXED_ROOT_SURVEY_IDENTITY,
            "plan": request["plan"],
            "execution_identity": execution_identity.to_mapping(),
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
                    "sample_index": sample["sample_index"],
                    "sample_role": sample["sample_role"],
                    "execution_identity": execution_identity.select_sample(
                        sample["sample_index"], sample["sample_role"]
                    ).to_mapping(),
                    "omega": sample["omega"],
                    "amplitude": sample["amplitude"],
                    "determinant": {
                        "real": str(index + 1),
                        "imaginary": str(-(index + 1)),
                    },
                    "numerical_conditioning": _conditioning(request),
                    "determinant_error_evidence": None,
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
    def test_reliability_projection_is_profile_bound_and_request_hashed(self):
        job = _job()
        receipt = load_default_calibration_receipt()
        profile = receipt.budget_for("exterior-wronskian/v1", 40)
        backend = _backend(_BatchAdapter())
        request = backend.preview_fixed_root_survey_request(
            job,
            fixed_root=job.root.omega,
            root_seal_sha256="0" * 64,
            branch_identity=job.root.branch_id,
            plan=FixedRootSurveyPlan.FULL_NINE,
        )
        self.assertEqual(
            request["fixed_root_reliability_target_abs"],
            profile.base_controls["root_correction_tolerance"],
        )
        _, _, original_sha256 = _worker_request_document(request)
        for field, value in (
            ("fixed_root_reliability_target_abs", "3e-11"),
            ("fixed_root_reliability_rule", "forged-rule/v1"),
        ):
            with self.subTest(field=field):
                changed = dict(request)
                changed[field] = value
                _, _, changed_sha256 = _worker_request_document(changed)
                self.assertNotEqual(original_sha256, changed_sha256)

        forged_controls = dict(profile.base_controls)
        forged_controls["root_correction_tolerance"] = "3e-11"
        forged_profile = replace(profile, base_controls=forged_controls)
        forged_backend = JuliaPrecisionRootBackend(
            VettedNativeDeterminantKernel.identity,
            _BatchAdapter(),
            40,
            empirical_control_profile=forged_profile,
            calibration_receipt=receipt,
        )
        with self.assertRaisesRegex(
            ValueError,
            "empirical control profile disagrees",
        ):
            forged_backend.preview_fixed_root_survey_request(
                job,
                fixed_root=job.root.omega,
                root_seal_sha256="0" * 64,
                branch_identity=job.root.branch_id,
                plan=FixedRootSurveyPlan.FULL_NINE,
            )

    def test_one_worker_request_returns_the_ordered_nine_sample_batch(self):
        job = _job()
        adapter = _BatchAdapter()
        backend = _backend(adapter)

        batch = backend.fixed_root_survey_batch(
            job,
            fixed_root=job.root.omega,
            root_seal_sha256="1" * 64,
            branch_identity=job.root.branch_id,
            plan=FixedRootSurveyPlan.FULL_NINE,
        )

        self.assertIsInstance(batch, JuliaFixedRootSurveyBatch)
        self.assertEqual(len(adapter.requests), 1)
        self.assertEqual(batch.sample_roles, BINARY64_FIXED_ROOT_SAMPLE_ROLES)
        self.assertEqual(batch.sample_count, 9)
        request = adapter.requests[0]
        self.assertEqual(request["operation"], FIXED_ROOT_SURVEY_BATCH_OPERATION)
        self.assertEqual(request["schema_version"], 2)
        self.assertEqual(request["schema"], FIXED_ROOT_SURVEY_BATCH_SCHEMA)
        self.assertEqual(request["plan"], FixedRootSurveyPlan.FULL_NINE.value)
        self.assertEqual(request["fixed_root_reliability_target_abs"], "2e-11")
        self.assertNotIn("root_correction_tolerance", request["policy"])
        self.assertEqual(
            [sample["sample_index"] for sample in request["samples"]],
            list(range(9)),
        )
        self.assertEqual(
            [sample["sample_role"] for sample in request["samples"]],
            list(BINARY64_FIXED_ROOT_SAMPLE_ROLES),
        )
        self.assertEqual(request["precision_digits"], 40)
        self.assertEqual(request["maximum_sample_count"], 9)
        for sample in request["samples"][:5]:
            self.assertNotIn("support", sample)
        for sample in request["samples"][5:]:
            self.assertEqual(set(sample["support"]), {
                "lower", "upper", "centre", "half_width"
            })
        still_forbidden = {
            "human_math_review_receipt_status",
            "independent_reference_fixture_receipt_status",
            "promoted_root_readout_policy",
        }
        self.assertTrue(still_forbidden.isdisjoint(request["policy"]))
        self.assertEqual(
            request["policy"]["determinant_error_model"],
            "exterior-determinant-additive-channels/provisional-v1",
        )
        self.assertEqual(
            request["policy"]["determinant_error_required_channels"],
            [
                "precision", "ode_controls", "endpoint_order",
                "match_readout", "angular_data", "arithmetic_rounding",
            ],
        )
        self.assertNotIn("determinant_error_safety_factor", request["policy"])
        self.assertEqual(
            request["policy"]["determinant_error_missing_evidence_outcome"],
            "BLOCKED_BY_REVIEWED_ERROR_EVIDENCE",
        )

    def test_canonical_five_and_reused_mechanism_four_are_valid_plans(self):
        job = _job()
        for requested_plan, operation_identity, roles in (
            (
                FixedRootSurveyPlan.CANONICAL_BACKGROUND_FIVE,
                CANONICAL_EXTERIOR_BACKGROUND_IDENTITY,
                BINARY64_FIXED_ROOT_SAMPLE_ROLES[:5],
            ),
            (
                FixedRootSurveyPlan.MECHANISM_COMPONENT_FOUR,
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
                    plan=requested_plan,
                )
                self.assertEqual(batch.sample_roles, roles)
                self.assertEqual(batch.plan, requested_plan)
                self.assertEqual(len(adapter.requests), 1)

    def test_invalid_roles_and_bf120_are_rejected_before_launch(self):
        job = _job()
        invalid_plans = ("UNKNOWN", "D0", "", None)
        for invalid_plan in invalid_plans:
            with self.subTest(plan=invalid_plan):
                adapter = _BatchAdapter()
                with self.assertRaises(ValueError):
                    _backend(adapter).preview_fixed_root_survey_request(
                        job,
                        fixed_root=job.root.omega,
                        root_seal_sha256="3" * 64,
                        branch_identity=job.root.branch_id,
                        plan=invalid_plan,
                    )
                self.assertEqual(adapter.requests, [])

        adapter = _BatchAdapter()
        with self.assertRaises(ValueError):
            _backend(adapter, 120).preview_fixed_root_survey_request(
                job,
                fixed_root=job.root.omega,
                root_seal_sha256="4" * 64,
                branch_identity=job.root.branch_id,
                plan=FixedRootSurveyPlan.FULL_NINE,
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
                plan=FixedRootSurveyPlan.FULL_NINE,
            )

    def test_response_conditioning_precision_verdict_is_recomputed(self):
        job = _job()

        class _ContradictoryConditioningAdapter(_BatchAdapter):
            def evaluate_for_validation(self, request):
                evaluation = super().evaluate_for_validation(request)
                evaluation.response["samples"][0]["numerical_conditioning"][
                    "precision_limited"
                ] = True
                return evaluation

        with self.assertRaisesRegex(
            JuliaResponseBackendError,
            "conditioning is invalid",
        ):
            _backend(_ContradictoryConditioningAdapter()).fixed_root_survey_batch(
                job,
                fixed_root=job.root.omega,
                root_seal_sha256="6" * 64,
                branch_identity=job.root.branch_id,
                plan=FixedRootSurveyPlan.FULL_NINE,
            )

    def test_worker_survey_function_has_no_root_solving_calls(self):
        """The survey batch computes its mandatory determinant-error
        certificate through the shared ``determinant_progress`` dispatcher
        (governing contract: promoted survey must produce a real bounded
        result), but it must never perform a root solve."""

        worker = (
            Path(__file__).parents[1]
            / "src/windows_solver/data/julia/m02_worker.jl"
        ).read_text(encoding="utf-8")
        start = worker.index("function fixed_root_survey_batch_fields")
        end = worker.index("\nfunction fixed_root_determinant_sample_fields", start)
        body = worker[start:end]
        for prohibited in (
            "select_worker_outer_endpoint_pair",
            "tight_control_request",
            "solve_phase",
            "bounded_newton",
        ):
            self.assertNotIn(prohibited, body)
        evaluator_start = worker.index(
            "function production_fixed_root_survey_sample_fields"
        )
        evaluator = worker[evaluator_start:start]
        self.assertIn("determinant_progress(", evaluator)
        self.assertIn("sample_evaluator(", body)

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
