from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import unittest

from windows_solver.contracts import canonical_json_bytes
from windows_solver.fixed_root_reliability import (
    FixedRootReliabilityAuthorityError,
    _parse_fixed_root_reliability_projection_authority,
    load_fixed_root_reliability_projection_authority,
)
from windows_solver.julia_response_backend import (
    ENDPOINT_ARITHMETIC_LIMITED,
    ENDPOINT_SERIES_ORDER_LIMITED,
    FIXED_ROOT_SURVEY_BATCH_OPERATION,
    FIXED_ROOT_SURVEY_BATCH_SCHEMA,
    FIXED_ROOT_SURVEY_BATCH_RESPONSE_SCHEMA,
    FixedRootSurveyPlan,
    JuliaFixedRootSurveyBatch,
    JuliaPrecisionRootBackend,
    JuliaResponseBackendError,
    _validated_exterior_endpoint_recovery_evidence,
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
    projection = request["fixed_root_reliability_projection"]
    recovery = request["fixed_root_endpoint_recovery_policy"]
    receipts = []
    for branch, schedule_name in (
        ("horizon-ingoing", "horizon_geometry_schedule"),
        ("infinity-outgoing", "infinity_geometry_schedule"),
    ):
        geometry = recovery[schedule_name][0]
        order = recovery["endpoint_order_schedule"][0]
        attempt = {
            "endpoint_branch": branch,
            "attempted_endpoint_order": order,
            "attempted_geometry": geometry,
            "maximum_last_term_ratio": "1e-20",
            "maximum_truncation_digits_lost": "0",
            "maximum_recurrence_digits_lost": "1",
            "maximum_series_evaluation_digits_lost": "1",
            "predicted_reliable_digits": "35",
            "required_reliable_digits": (
                "16.698970004336018804786261105275506973231810118538"
            ),
            "candidate_limitation": "adequate/v1",
            "selected_intervention": "ENTER_HOMOGENEOUS_ODE",
            "result": "ADEQUATE",
        }
        receipts.append({
            "schema": "windows-solver.exterior-endpoint-recovery-receipt/1",
            "endpoint_branch": branch,
            "recovery_policy_identity": recovery["identity"],
            "recovery_policy_sha256": recovery["policy_sha256"],
            "base_endpoint_order": recovery["base_endpoint_order"],
            "generated_maximum_order": recovery["generated_maximum_order"],
            "attempted_endpoint_orders": [order],
            "terminal_endpoint_order": order,
            "candidate_geometry_schedule": recovery[schedule_name],
            "terminal_geometry": geometry,
            "maximum_last_term_ratio": "1e-20",
            "maximum_truncation_digits_lost": "0",
            "maximum_recurrence_digits_lost": "1",
            "maximum_series_evaluation_digits_lost": "1",
            "predicted_reliable_digits": "35",
            "required_reliable_digits": attempt["required_reliable_digits"],
            "candidate_limitation": "adequate/v1",
            "aggregate_limitation": "adequate/v1",
            "factored_homogeneous_rhs_evaluations": 0,
            "attempts": [attempt],
        })
    return {
        "schema": "windows-solver.fixed-root-survey-conditioning/3",
        "fixed_root_reliability_target_abs": projection[
            "fixed_root_reliability_target_abs"
        ],
        "fixed_root_reliability_rule": projection[
            "fixed_root_reliability_rule"
        ],
        "required_digit_guard": projection["required_digit_guard"],
        "fixed_root_reliability_projection_sha256": projection[
            "projection_sha256"
        ],
        "determinant_family": "exterior-wronskian/v1",
        "homogeneous_representation": policy["homogeneous_representation"],
        "branch_convention": policy["branch_convention"],
        "determinant_convention": policy["determinant_convention"],
        "determinant_normalisation": policy["determinant_normalisation"],
        "maximum_series_digits_lost": "1",
        "maximum_recurrence_digits_lost": "1",
        "maximum_series_evaluation_digits_lost": "1",
        "maximum_last_term_ratio": "1e-20",
        "maximum_truncation_digits_lost": "0",
        "minimum_asymptotic_predicted_reliable_digits": "35",
        "endpoint_remainders_regular": True,
        "maximum_endpoint_reconstruction_error": "1e-30",
        "maximum_contour_angle_deformation": "0",
        "predicted_reliable_digits": "34",
        "required_reliable_digits": (
            "16.698970004336018804786261105275506973231810118538"
        ),
        "precision_limited": False,
        "endpoint_recovery_policy_identity": recovery["identity"],
        "endpoint_recovery_policy_sha256": recovery["policy_sha256"],
        "endpoint_receipts": receipts,
        "aggregate_limitation": "adequate/v1",
        "factored_homogeneous_rhs_evaluations_before_recovery_decision": 0,
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
            "schema_version": 3,
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


def _backend(
    adapter: _BatchAdapter, digits: int = 40, refinement: int = 0
):
    receipt = load_default_calibration_receipt()
    return JuliaPrecisionRootBackend(
        VettedNativeDeterminantKernel.identity,
        adapter,
        digits,
        refinement=refinement,
        empirical_control_profile=receipt.budget_for(
            "exterior-wronskian/v1", digits
        ),
        calibration_receipt=receipt,
    )


class JuliaFixedRootSurveyBatchTests(unittest.TestCase):
    def test_mixed_arithmetic_and_order_blockers_cannot_claim_arithmetic(self):
        job = _job()
        request = _backend(_BatchAdapter()).preview_fixed_root_survey_request(
            job,
            fixed_root=job.root.omega,
            root_seal_sha256="0" * 64,
            branch_identity=job.root.branch_id,
            plan=FixedRootSurveyPlan.FULL_NINE,
        )
        policy = request["fixed_root_endpoint_recovery_policy"]
        required = "16.698970004336018804786261105275506973231810118538"
        horizon_geometry = policy["horizon_geometry_schedule"][0]
        base_order = policy["endpoint_order_schedule"][0]
        arithmetic_attempt = {
            "endpoint_branch": "horizon-ingoing",
            "attempted_endpoint_order": base_order,
            "attempted_geometry": horizon_geometry,
            "maximum_last_term_ratio": "0.1",
            "maximum_truncation_digits_lost": "2",
            "maximum_recurrence_digits_lost": "1",
            "maximum_series_evaluation_digits_lost": "1",
            "predicted_reliable_digits": "10",
            "required_reliable_digits": required,
            "candidate_limitation": ENDPOINT_ARITHMETIC_LIMITED,
            "selected_intervention": (
                "PROMOTE_ARITHMETIC_TIER_IF_AGGREGATE_ALLOWS"
            ),
            "result": "ARITHMETIC_INADEQUATE",
        }
        horizon = {
            "schema": "windows-solver.exterior-endpoint-recovery-receipt/1",
            "endpoint_branch": "horizon-ingoing",
            "recovery_policy_identity": policy["identity"],
            "recovery_policy_sha256": policy["policy_sha256"],
            "base_endpoint_order": policy["base_endpoint_order"],
            "generated_maximum_order": policy["generated_maximum_order"],
            "attempted_endpoint_orders": [base_order],
            "terminal_endpoint_order": base_order,
            "candidate_geometry_schedule": policy["horizon_geometry_schedule"],
            "terminal_geometry": horizon_geometry,
            "maximum_last_term_ratio": "0.1",
            "maximum_truncation_digits_lost": "2",
            "maximum_recurrence_digits_lost": "1",
            "maximum_series_evaluation_digits_lost": "1",
            "predicted_reliable_digits": "10",
            "required_reliable_digits": required,
            "candidate_limitation": ENDPOINT_ARITHMETIC_LIMITED,
            "aggregate_limitation": ENDPOINT_ARITHMETIC_LIMITED,
            "factored_homogeneous_rhs_evaluations": 0,
            "attempts": [arithmetic_attempt],
        }
        infinity_attempts = []
        for index, order in enumerate(policy["endpoint_order_schedule"]):
            terminal = index == len(policy["endpoint_order_schedule"]) - 1
            infinity_attempts.append({
                "endpoint_branch": "infinity-outgoing",
                "attempted_endpoint_order": order,
                "attempted_geometry": policy["infinity_geometry_schedule"][0],
                "maximum_last_term_ratio": "0.1",
                "maximum_truncation_digits_lost": "5",
                "maximum_recurrence_digits_lost": "1",
                "maximum_series_evaluation_digits_lost": "1",
                "predicted_reliable_digits": "10",
                "required_reliable_digits": required,
                "candidate_limitation": ENDPOINT_SERIES_ORDER_LIMITED,
                "selected_intervention": (
                    "NONE" if terminal else "INCREASE_ENDPOINT_ORDER"
                ),
                "result": "ORDER_EXHAUSTED" if terminal else "RETRY",
            })
        infinity = {
            "schema": "windows-solver.exterior-endpoint-recovery-receipt/1",
            "endpoint_branch": "infinity-outgoing",
            "recovery_policy_identity": policy["identity"],
            "recovery_policy_sha256": policy["policy_sha256"],
            "base_endpoint_order": policy["base_endpoint_order"],
            "generated_maximum_order": policy["generated_maximum_order"],
            "attempted_endpoint_orders": policy["endpoint_order_schedule"],
            "terminal_endpoint_order": policy["endpoint_order_schedule"][-1],
            "candidate_geometry_schedule": policy["infinity_geometry_schedule"],
            "terminal_geometry": policy["infinity_geometry_schedule"][0],
            "maximum_last_term_ratio": "0.1",
            "maximum_truncation_digits_lost": "5",
            "maximum_recurrence_digits_lost": "1",
            "maximum_series_evaluation_digits_lost": "1",
            "predicted_reliable_digits": "10",
            "required_reliable_digits": required,
            "candidate_limitation": ENDPOINT_SERIES_ORDER_LIMITED,
            "aggregate_limitation": ENDPOINT_ARITHMETIC_LIMITED,
            "factored_homogeneous_rhs_evaluations": 0,
            "attempts": infinity_attempts,
        }

        with self.assertRaisesRegex(ValueError, "aggregate limitation"):
            _validated_exterior_endpoint_recovery_evidence(
                [horizon, infinity],
                policy,
                expected_aggregate=ENDPOINT_ARITHMETIC_LIMITED,
            )

    def test_committed_reliability_authority_is_canonical_and_contract_bound(self):
        root = Path(__file__).resolve().parents[1]
        authority_path = root / (
            "src/windows_solver/data/"
            "fixed_root_reliability_projection_authority_v1.json"
        )
        raw = authority_path.read_bytes()
        authority = load_fixed_root_reliability_projection_authority()
        self.assertEqual(raw, canonical_json_bytes(authority.to_mapping()) + b"\n")

        for field, replacement in (
            (
                "schema",
                "windows-solver.fixed-root-reliability-projection-authority/2",
            ),
            ("identity", "forged-fixed-root-reliability-authority/v1"),
            (
                "calibration_receipt_schema",
                "windows-solver.promoted-control-empirical-calibration-receipt/2",
            ),
            (
                "calibration_receipt_identity",
                "forged-promoted-control-calibration/v1",
            ),
            (
                "fixed_root_policy_control_fields",
                [
                    "coordinate_ode_absolute_tolerance",
                    "coordinate_ode_relative_tolerance",
                    "frequency_step",
                    "homogeneous_ode_absolute_tolerance",
                    "homogeneous_ode_relative_tolerance",
                    "ode_absolute_tolerance",
                    "ode_relative_tolerance",
                ],
            ),
            (
                "fixed_root_reliability_target_control_field",
                "frequency_step",
            ),
        ):
            with self.subTest(field=field):
                changed = json.loads(raw)
                changed[field] = replacement
                binding = {
                    key: value
                    for key, value in changed.items()
                    if key != "authority_sha256"
                }
                changed["authority_sha256"] = hashlib.sha256(
                    canonical_json_bytes(binding)
                ).hexdigest()
                with self.assertRaises(FixedRootReliabilityAuthorityError):
                    _parse_fixed_root_reliability_projection_authority(
                        canonical_json_bytes(changed) + b"\n"
                    )

        with self.assertRaisesRegex(
            FixedRootReliabilityAuthorityError,
            "not canonical JSON",
        ):
            _parse_fixed_root_reliability_projection_authority(
                json.dumps(json.loads(raw), indent=2).encode("utf-8")
            )

        digest_mismatch = json.loads(raw)
        digest_mismatch["fixed_root_reliability_rule"] = "forged-rule/v1"
        with self.assertRaisesRegex(
            FixedRootReliabilityAuthorityError,
            "digest does not match",
        ):
            _parse_fixed_root_reliability_projection_authority(
                canonical_json_bytes(digest_mismatch) + b"\n"
            )

    def test_julia_fixed_root_reliability_has_one_committed_authority(self):
        root = Path(__file__).resolve().parents[1]
        worker = (
            root / "src/windows_solver/data/julia/m02_worker.jl"
        ).read_text(encoding="utf-8")
        response_engine = (
            root / "src/windows_solver/response_engine.py"
        ).read_text(encoding="utf-8")
        self.assertIn(
            '"windows-solver.fixed-root-reliability-projection/2"', worker
        )
        self.assertIn(
            '"fixed_root_reliability_projection_authority_v1.json"', worker
        )
        self.assertIn(
            "function fixed_root_reliability_projection_authority()", worker
        )
        projection_start = worker.index(
            "function fixed_root_reliability_projection(request)"
        )
        projection_end = worker.index(
            "function required_reliable_digits", projection_start
        )
        projection_source = worker[projection_start:projection_end]
        self.assertIn("for field in policy_control_fields", projection_source)
        self.assertNotIn("for (key, value) in controls", projection_source)
        self.assertIn(
            "target = string(required(controls, target_control_field))",
            projection_source,
        )
        self.assertNotIn("FIXED_ROOT_RELIABILITY_RULE", worker)
        self.assertNotIn(
            "load_fixed_root_reliability_projection_authority", response_engine
        )

        harness = (
            root / "tests/julia/test_pr75_fixed_root_lifecycle.jl"
        ).read_text(encoding="utf-8")
        negative_start = harness.index(
            "function validate_reliability_negative_matrix(document)"
        )
        negative_end = harness.index("function main()", negative_start)
        negative_source = harness[negative_start:negative_end]
        self.assertLess(
            negative_source.index("PR75 fixed-root reliability baseline was rejected"),
            negative_source.index("for (field, replacement"),
        )

    def test_reliability_authority_accepts_the_fixed_root_baseline_shape(self):
        job = _job()
        receipt = load_default_calibration_receipt()
        authority = load_fixed_root_reliability_projection_authority()
        self.assertEqual(
            authority.fixed_root_policy_control_fields,
            (
                "coordinate_ode_absolute_tolerance",
                "coordinate_ode_relative_tolerance",
                "homogeneous_ode_absolute_tolerance",
                "homogeneous_ode_relative_tolerance",
                "ode_absolute_tolerance",
                "ode_relative_tolerance",
            ),
        )
        for digits in (40, 80):
            profile = receipt.budget_for("exterior-wronskian/v1", digits)
            for refinement in (0, 1):
                controls = (
                    profile.base_controls
                    if refinement == 0
                    else profile.refinement_controls
                )
                request = _backend(
                    _BatchAdapter(), digits, refinement
                ).preview_fixed_root_survey_request(
                    job,
                    fixed_root=job.root.omega,
                    root_seal_sha256="0" * 64,
                    branch_identity=job.root.branch_id,
                    plan=FixedRootSurveyPlan.FULL_NINE,
                )
                for field in authority.fixed_root_policy_control_fields:
                    with self.subTest(
                        digits=digits, refinement=refinement, field=field
                    ):
                        self.assertEqual(request["policy"][field], controls[field])
                self.assertEqual(
                    request["fixed_root_reliability_projection"][
                        "fixed_root_reliability_target_abs"
                    ],
                    controls[
                        authority.fixed_root_reliability_target_control_field
                    ],
                )
                self.assertNotEqual(
                    request["frequency_step"], controls["frequency_step"]
                )
                self.assertNotIn("root_correction_tolerance", request["policy"])
                _worker_request_document(request)
        self.assertNotIn(
            "frequency_step", authority.fixed_root_policy_control_fields
        )
        self.assertEqual(
            authority.fixed_root_reliability_target_control_field,
            "root_correction_tolerance",
        )

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
        projection = request["fixed_root_reliability_projection"]
        self.assertEqual(
            projection["schema"],
            "windows-solver.fixed-root-reliability-projection/2",
        )
        self.assertEqual(
            projection["source_reliability_projection_authority_schema"],
            "windows-solver.fixed-root-reliability-projection-authority/1",
        )
        self.assertEqual(
            projection["source_reliability_projection_authority_identity"],
            "fixed-root-reliability-projection-authority/v1",
        )
        self.assertEqual(
            projection["source_reliability_projection_authority_sha256"],
            "3e2b617990b25221aa0e6ed11d45c0fab93a1c1abc928f7fbddad4bd2725277c",
        )
        self.assertEqual(
            projection["source_calibration_receipt_sha256"], receipt.sha256
        )
        self.assertEqual(
            projection["source_empirical_control_profile_sha256"],
            hashlib.sha256(canonical_json_bytes(profile.to_mapping())).hexdigest(),
        )
        self.assertEqual(projection["source_refinement_level"], 0)
        self.assertEqual(
            projection["fixed_root_reliability_target_abs"],
            profile.base_controls["root_correction_tolerance"],
        )
        self.assertEqual(projection["required_digit_guard"], 6)
        projection_binding = {
            key: value
            for key, value in projection.items()
            if key != "projection_sha256"
        }
        self.assertEqual(
            projection["projection_sha256"],
            hashlib.sha256(
                canonical_json_bytes(projection_binding)
            ).hexdigest(),
        )
        self.assertNotIn("root_correction_tolerance", request)
        self.assertNotIn("root_correction_tolerance", request["policy"])
        self.assertNotIn("fixed_root_reliability_target_abs", request)
        self.assertNotIn("fixed_root_reliability_rule", request)
        _, _, original_sha256 = _worker_request_document(request)
        for field, value in (
            ("schema", "windows-solver.fixed-root-reliability-projection/1"),
            (
                "source_reliability_projection_authority_schema",
                "windows-solver.fixed-root-reliability-projection-authority/2",
            ),
            (
                "source_reliability_projection_authority_identity",
                "forged-fixed-root-reliability-authority/v1",
            ),
            ("source_reliability_projection_authority_sha256", "0" * 64),
            ("fixed_root_reliability_target_abs", "3e-11"),
            ("fixed_root_reliability_rule", "forged-rule/v1"),
            ("required_digit_guard", 7),
        ):
            with self.subTest(field=field):
                changed = deepcopy(request)
                changed["fixed_root_reliability_projection"][field] = value
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
        self.assertEqual(request["schema_version"], 3)
        self.assertEqual(request["schema"], FIXED_ROOT_SURVEY_BATCH_SCHEMA)
        self.assertEqual(request["plan"], FixedRootSurveyPlan.FULL_NINE.value)
        self.assertEqual(
            request["fixed_root_reliability_projection"][
                "fixed_root_reliability_target_abs"
            ],
            "2e-11",
        )
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

    def test_response_conditioning_required_digits_are_request_derived(self):
        job = _job()

        class _ForgedRequiredDigitsAdapter(_BatchAdapter):
            def evaluate_for_validation(self, request):
                evaluation = super().evaluate_for_validation(request)
                evaluation.response["samples"][0]["numerical_conditioning"][
                    "required_reliable_digits"
                ] = "17"
                return evaluation

        with self.assertRaisesRegex(
            JuliaResponseBackendError,
            "conditioning is invalid",
        ):
            _backend(_ForgedRequiredDigitsAdapter()).fixed_root_survey_batch(
                job,
                fixed_root=job.root.omega,
                root_seal_sha256="7" * 64,
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
