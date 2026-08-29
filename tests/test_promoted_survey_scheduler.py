from __future__ import annotations

import copy
from dataclasses import replace
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from windows_solver.campaign_failures import CampaignSystemFailure
from windows_solver.campaign_policy import (
    PROMOTED_CONTROL_CONTINUATION_PROOF_SCHEMA,
    PROMOTED_CONTROL_CONTINUATION_STAGE_SCHEMA,
    PROMOTED_CONTROL_DECISION_SCHEMA,
    PROMOTED_CONTROL_DECISION_STAGE_SCHEMA,
    PROMOTED_POLICY_TERMINAL_STAGE_SCHEMA,
    PromotionQueueDisposition,
    PromotionQueueKind,
    SurveyDisposition,
    SurveyPass,
    append_promotion,
    empty_schema11_checkpoint,
    record_survey_disposition,
    retain_promoted_control_decision,
    validate_schema11_checkpoint,
)
from windows_solver.campaign_recovery import RecoverySelection
from windows_solver.campaign_timing import CampaignTimingLog
from windows_solver.campaign_survey import (
    AuthenticatedRootSeal,
    PromotedRootSolveResult,
    run_promoted_survey,
)
from windows_solver.contracts import canonical_json_bytes
from windows_solver.julia_response_backend import (
    FixedRootSurveyConditioning,
    FixedRootSurveyPlan,
    JuliaFixedRootSurveyBatch,
    JuliaFixedRootSurveySample,
    JuliaNumericalControlError,
    JuliaODEResourceLimitError,
    JuliaPrecisionRootBackend,
    PreparedFixedRootSurveyRequest,
    _execution_resource_policy,
    fixed_root_survey_request_contract,
)
from windows_solver.operation_control import (
    JULIA_PRODUCER_RETRYABILITY_BASIS,
    JULIA_WORKER_ORIGIN,
    OPERATION_EXECUTION_IDENTITY_SCHEMA,
    OperationExecutionIdentity,
    build_operation_control_receipt,
    execution_identity_from_request,
    operation_execution_identity,
    validate_operation_control_receipt,
)
from windows_solver.precision_tiers import PrecisionTier, working_precision_bits
from windows_solver.root_evidence import AuthenticatedRootEvidence, RootDependencyKey
from windows_solver.reviewed_determinant_error_issuance import (
    PromotedExecutionPreflight,
    require_locked_bf40_determinant_error_issuance_authority,
)
from windows_solver.schema11_dashboard import project_schema11_dashboard
from windows_solver.promoted_control_calibration import PromotedExecutionMode
from windows_solver.promoted_control_authority import (
    authenticate_persisted_control_decision,
    authenticate_persisted_control_return,
    resolve_persisted_control_return,
)
from windows_solver.structural_diagnostics import StructuralDiagnosticSession
from windows_solver.response_batches import (
    PrecisionCapabilities,
    build_campaign_plan,
    build_campaign_selection,
    scientific_computation_identity_sha256,
)
from windows_solver.response_engine import (
    BINARY64_FIXED_ROOT_SAMPLE_ROLES,
    BackgroundEquivalenceReceipt,
    Binary64FixedRootBatch,
    Binary64FixedRootSample,
    DecimalComplex,
    NumericalPolicy,
    VettedNativeDeterminantKernel,
    _exterior_support,
    build_exterior_background_reuse_key,
    build_exterior_provisional_stage,
    canonical_background_from_binary64_batch,
)
from tests.test_julia_response_backend import (
    FakeAdapter,
    valid_control_failure_diagnostics,
)


def _sha256(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _durable_root_result(leaf, digits: int) -> PromotedRootSolveResult:
    """Supply the no-numeric scheduler with typed, leaf-bound root authority."""

    evidence = AuthenticatedRootEvidence.from_bound_leaf(leaf)
    return PromotedRootSolveResult(
        AuthenticatedRootSeal(
            evidence.fixed_root,
            evidence.branch_identity,
            evidence.root_seal_sha256,
            root_success_evidence=evidence.to_mapping(),
        ),
        precision_tier=f"BF{digits}",
        root_success_evidence=evidence.to_mapping(),
    )


def _requested_contract(kwargs):
    """Resolve fake-worker identity and roles through the production contract."""

    return fixed_root_survey_request_contract(kwargs["plan"])


def _fixture_fixed_root_request(job, digits: int, kwargs):
    contract = _requested_contract(kwargs)
    recovery_binding = {
        "schema": "windows-solver.fixed-root-endpoint-recovery-policy/1",
        "identity": "cause-aware-fixed-root-exterior-endpoint-recovery/v1",
        "endpoint_order_rule": "bounded-doubling-prefix/v1",
        "base_endpoint_order": 28,
        "generated_maximum_order": 112,
        "endpoint_order_schedule": [28, 56, 112],
        "horizon_geometry_rule": "bounded-negative-rho-depth/v1",
        "horizon_geometry_schedule": ["-5000", "-10000", "-20000"],
        "infinity_geometry_rule": "bounded-positive-rho-depth/v1",
        "infinity_geometry_schedule": [
            "100", "250", "500", "1000", "2000", "5000", "10000", "20000"
        ],
        "fixed_root_reliability_target_abs": "2e-11",
        "fixed_root_reliability_rule": (
            "minus-log10-target-plus-required-digit-guard/v1"
        ),
        "required_digit_guard": 6,
        "precision_digits": digits,
        "semantic_precision_tier": f"bigfloat-{digits}",
    }
    recovery = {
        **recovery_binding,
        "policy_sha256": _sha256(recovery_binding),
    }
    return {
        "schema_version": 3,
        "schema": "windows-solver.fixed-root-survey-batch/3",
        "operation": "fixed-root-survey-batch",
        "control_profile": "fixed-root-deep-v1",
        "leaf_id": job.leaf_id,
        "job_id": job.job_id,
        "backend_identity_sha256": job.backend_identity.identity_sha256,
        "precision_digits": digits,
        "working_precision_bits": working_precision_bits(
            PrecisionTier.BIGFLOAT_40
            if digits == 40
            else PrecisionTier.BIGFLOAT_80
        ),
        "semantic_precision_tier": f"bigfloat-{digits}",
        "policy": {
            "job_policy_sha256": job.policy.identity_sha256,
            "endpoint_series_order": 28,
            "rho_in": "-20000",
            "rho_out": "20000",
        },
        "fixed_root_endpoint_recovery_policy": recovery,
        "execution_resource": _execution_resource_policy(),
        "plan": contract.plan.value,
        "scientific_operation_identity": contract.scientific_operation_identity,
        "root_reference_id": job.root.root_reference_id,
        "root_seal_sha256": kwargs["root_seal_sha256"],
        "branch_identity": kwargs["branch_identity"],
        "sample_roles": list(contract.sample_roles),
    }


def _endpoint_control_diagnostics(request, failure_code: str):
    policy = request["fixed_root_endpoint_recovery_policy"]
    limitation, intervention, outcome = {
        "EXTERIOR_ENDPOINT_MAXIMUM_ORDER_INADEQUATE": (
            "insufficient-series-order/v1",
            "ENDPOINT_ORDER_RECOVERY_EXHAUSTED",
            "UNRESOLVED",
        ),
        "EXTERIOR_ENDPOINT_GEOMETRY_EXHAUSTED": (
            "insufficient-geometric-depth/v1",
            "ENDPOINT_GEOMETRY_RECOVERY_EXHAUSTED",
            "UNRESOLVED",
        ),
        "EXTERIOR_ENDPOINT_ARITHMETIC_INADEQUATE": (
            "insufficient-arithmetic-precision/v1",
            "ARITHMETIC_PRECISION_PROMOTION",
            "ARITHMETIC_INADEQUATE",
        ),
    }[failure_code]
    receipts = []
    for branch, geometry_field in (
        ("horizon-ingoing", "horizon_geometry_schedule"),
        ("infinity-outgoing", "infinity_geometry_schedule"),
    ):
        geometries = policy[geometry_field]
        orders = policy["endpoint_order_schedule"]
        coordinates = (
            [(order, geometries[0]) for order in orders]
            if limitation == "insufficient-series-order/v1"
            else [(orders[0], geometry) for geometry in geometries]
            if limitation == "insufficient-geometric-depth/v1"
            else [(orders[0], geometries[0])]
        )
        attempts = []
        for index, (order, geometry) in enumerate(coordinates):
            terminal = index == len(coordinates) - 1
            last_ratio = (
                "1" if limitation == "insufficient-geometric-depth/v1" else "0.1"
            )
            truncation = (
                "2" if limitation == "insufficient-arithmetic-precision/v1" else "10"
            )
            selected = (
                "PROMOTE_ARITHMETIC_TIER_IF_AGGREGATE_ALLOWS"
                if limitation == "insufficient-arithmetic-precision/v1"
                else "NONE" if terminal
                else "INCREASE_ENDPOINT_ORDER"
                if limitation == "insufficient-series-order/v1"
                else "DEEPEN_ENDPOINT_GEOMETRY"
            )
            result = (
                "ARITHMETIC_INADEQUATE"
                if limitation == "insufficient-arithmetic-precision/v1"
                else "ORDER_EXHAUSTED"
                if terminal and limitation == "insufficient-series-order/v1"
                else "GEOMETRY_EXHAUSTED"
                if terminal else "RETRY"
            )
            attempts.append({
                "endpoint_branch": branch,
                "attempted_endpoint_order": order,
                "attempted_geometry": geometry,
                "maximum_last_term_ratio": last_ratio,
                "maximum_truncation_digits_lost": truncation,
                "maximum_recurrence_digits_lost": "1",
                "maximum_series_evaluation_digits_lost": "1",
                "predicted_reliable_digits": "10",
                "required_reliable_digits": "20",
                "candidate_limitation": limitation,
                "selected_intervention": selected,
                "result": result,
            })
        terminal_attempt = attempts[-1]
        receipts.append({
            "schema": "windows-solver.exterior-endpoint-recovery-receipt/1",
            "endpoint_branch": branch,
            "recovery_policy_identity": policy["identity"],
            "recovery_policy_sha256": policy["policy_sha256"],
            "base_endpoint_order": policy["base_endpoint_order"],
            "generated_maximum_order": policy["generated_maximum_order"],
            "attempted_endpoint_orders": [
                attempt["attempted_endpoint_order"] for attempt in attempts
            ],
            "terminal_endpoint_order": terminal_attempt[
                "attempted_endpoint_order"
            ],
            "candidate_geometry_schedule": geometries,
            "terminal_geometry": terminal_attempt["attempted_geometry"],
            "maximum_last_term_ratio": terminal_attempt[
                "maximum_last_term_ratio"
            ],
            "maximum_truncation_digits_lost": terminal_attempt[
                "maximum_truncation_digits_lost"
            ],
            "maximum_recurrence_digits_lost": "1",
            "maximum_series_evaluation_digits_lost": "1",
            "predicted_reliable_digits": "10",
            "required_reliable_digits": "20",
            "candidate_limitation": limitation,
            "aggregate_limitation": limitation,
            "factored_homogeneous_rhs_evaluations": 0,
            "attempts": attempts,
        })
    return {
        "reason": failure_code,
        "aggregate_limitation": limitation,
        "endpoint_recovery_policy_identity": policy["identity"],
        "endpoint_recovery_policy_sha256": policy["policy_sha256"],
        "endpoint_receipts": receipts,
        "selected_intervention": intervention,
        "result": outcome,
        "factored_homogeneous_rhs_evaluations": 0,
    }


class _TestLayer1Guard:
    """Minimal guard seam for scheduler unit tests; routes remain explicit."""

    def assert_unchanged(self, checkpoint):
        return checkpoint

    def pre_write(self, checkpoint):
        return checkpoint

    def post_write(self, checkpoint):
        return checkpoint

    def post_callback(self, checkpoint):
        return checkpoint


def _locked_routes(checkpoint, leaves) -> dict[int, object]:
    leaf_by_id = {leaf.leaf_id: leaf for leaf in leaves}
    routes = {}
    for entry in checkpoint["promotion_queue"]["entries"]:
        leaf = leaf_by_id[entry["leaf_id"]]
        routes[int(entry["queue_ordinal"])] = SimpleNamespace(
            queue_ordinal=int(entry["queue_ordinal"]),
            leaf_id=entry["leaf_id"],
            route=(
                "HORIZON_BF80"
                if leaf.mechanism_id == "horizon-admittance"
                else "EXTERIOR_BF40"
            ),
            minimum_requested_tier=entry["minimum_requested_tier"],
            source_stage_sha256=entry["source_stage_sha256"],
            source_root_seal_sha256=entry["source_root_seal_sha256"],
            source_fingerprint_sha256=entry.get("source_fingerprint_sha256"),
            provisional_stage=entry.get("provisional_stage"),
        )
    return routes


def _strict_run(plan, selection, checkpoint, **kwargs):
    """Invoke the scheduler with the same typed seams as production wiring."""

    kwargs.pop("provisional_stage_lookup", None)
    kwargs.pop("terminal_record_committed", None)
    leaves = {leaf.leaf_id: leaf for leaf in plan.leaves}
    routes = _locked_routes(
        checkpoint,
        tuple(leaves[leaf_id] for leaf_id in selection.ordered_leaf_ids),
    )
    kwargs.setdefault("layer1_guard", _TestLayer1Guard())
    kwargs.setdefault("locked_routes_by_ordinal", routes)
    kwargs.setdefault(
        "promoted_preflights_by_ordinal",
        {
            ordinal: require_locked_bf40_determinant_error_issuance_authority(
                route=route.route
            )
            for ordinal, route in routes.items()
        },
    )
    kwargs.setdefault("layer1_lock_receipt_sha256", "f" * 64)
    return run_promoted_survey(plan, selection, checkpoint, **kwargs)


def _record(leaf_id: str, digits: int):
    stage_content = {
        "schema": "windows-solver.test-promoted-stage/1",
        "digits": digits,
    }
    stage = {**stage_content, "stage_sha256": _sha256(stage_content)}
    content = {"leaf_id": leaf_id, "state": "PRODUCED", "stages": [stage]}
    return {**content, "record_sha256": _sha256(content)}, stage["stage_sha256"]


def _conditioning(
    digits: int,
    *,
    precision_limited: bool = False,
) -> FixedRootSurveyConditioning:
    del precision_limited
    required = "16.698970004336018804786261105275506973231810118538"
    receipts = []
    for branch, geometry, schedule in (
        ("horizon-ingoing", "-5000", ["-5000", "-10000", "-20000"]),
        (
            "infinity-outgoing", "100",
            ["100", "250", "500", "1000", "2000", "5000", "10000", "20000"],
        ),
    ):
        attempt = {
            "endpoint_branch": branch,
            "attempted_endpoint_order": 28,
            "attempted_geometry": geometry,
            "maximum_last_term_ratio": "1e-20",
            "maximum_truncation_digits_lost": "0",
            "maximum_recurrence_digits_lost": "1",
            "maximum_series_evaluation_digits_lost": "1",
            "predicted_reliable_digits": str(digits - 5),
            "required_reliable_digits": required,
            "candidate_limitation": "adequate/v1",
            "selected_intervention": "ENTER_HOMOGENEOUS_ODE",
            "result": "ADEQUATE",
        }
        receipts.append({
            "schema": "windows-solver.exterior-endpoint-recovery-receipt/1",
            "endpoint_branch": branch,
            "recovery_policy_identity": (
                "cause-aware-fixed-root-exterior-endpoint-recovery/v1"
            ),
            "recovery_policy_sha256": "f" * 64,
            "base_endpoint_order": 28,
            "generated_maximum_order": 112,
            "attempted_endpoint_orders": [28],
            "terminal_endpoint_order": 28,
            "candidate_geometry_schedule": schedule,
            "terminal_geometry": geometry,
            "maximum_last_term_ratio": "1e-20",
            "maximum_truncation_digits_lost": "0",
            "maximum_recurrence_digits_lost": "1",
            "maximum_series_evaluation_digits_lost": "1",
            "predicted_reliable_digits": str(digits - 5),
            "required_reliable_digits": required,
            "candidate_limitation": "adequate/v1",
            "aggregate_limitation": "adequate/v1",
            "factored_homogeneous_rhs_evaluations": 0,
            "attempts": [attempt],
        })
    return FixedRootSurveyConditioning({
        "schema": "windows-solver.fixed-root-survey-conditioning/3",
        "fixed_root_reliability_target_abs": "2e-11",
        "fixed_root_reliability_rule": (
            "minus-log10-target-plus-required-digit-guard/v1"
        ),
        "required_digit_guard": 6,
        "fixed_root_reliability_projection_sha256": "a" * 64,
        "determinant_family": "exterior-wronskian/v1",
        "homogeneous_representation": "factored-plane-wave-gsn/v1",
        "branch_convention": "gsn-complex-rho/v1",
        "determinant_convention": "wronskian-perturbed-Xin-with-Xup/v1",
        "determinant_normalisation": "unit-asymptotic-branch-wronskian/v1",
        "maximum_series_digits_lost": "1",
        "maximum_recurrence_digits_lost": "1",
        "maximum_series_evaluation_digits_lost": "1",
        "maximum_last_term_ratio": "1e-20",
        "maximum_truncation_digits_lost": "0",
        "minimum_asymptotic_predicted_reliable_digits": (
            str(digits - 5)
        ),
        "endpoint_remainders_regular": True,
        "maximum_endpoint_reconstruction_error": f"1e-{digits - 5}",
        "maximum_contour_angle_deformation": "0",
        "predicted_reliable_digits": (
            str(digits - 6)
        ),
        "required_reliable_digits": (
            "16.698970004336018804786261105275506973231810118538"
        ),
        "precision_limited": False,
        "endpoint_recovery_policy_identity": (
            "cause-aware-fixed-root-exterior-endpoint-recovery/v1"
        ),
        "endpoint_recovery_policy_sha256": "f" * 64,
        "endpoint_receipts": receipts,
        "aggregate_limitation": "adequate/v1",
        "factored_homogeneous_rhs_evaluations_before_recovery_decision": 0,
        "determinant_count": 1,
    })


def _batch(
    leaf,
    seal: AuthenticatedRootSeal,
    digits: int,
    *,
    flat=False,
    plan: FixedRootSurveyPlan = FixedRootSurveyPlan.FULL_NINE,
    prepared_request: PreparedFixedRootSurveyRequest | None = None,
):
    root = seal.fixed_root
    h = 1.0e-5 * (1.0 + abs(root))
    epsilon = float(leaf.job.policy.epsilons[0])
    points = (
        (root, 0.0),
        (root + h, 0.0),
        (root - h, 0.0),
        (root + h / 2.0, 0.0),
        (root - h / 2.0, 0.0),
        (root, epsilon),
        (root, -epsilon),
        (root, epsilon / 2.0),
        (root, -epsilon / 2.0),
    )
    contract = fixed_root_survey_request_contract(plan)
    point_by_role = dict(zip(BINARY64_FIXED_ROOT_SAMPLE_ROLES, points))
    if prepared_request is None:
        request_sha256 = _sha256({
            "leaf_id": leaf.leaf_id,
            "digits": digits,
            "plan": contract.plan.value,
        })
        identity = OperationExecutionIdentity({
            "schema": OPERATION_EXECUTION_IDENTITY_SCHEMA,
            "scope": "REQUEST",
            "operation": "fixed-root-survey-batch",
            "control_profile": "fixed-root-deep-v1",
            "request_schema": "windows-solver.fixed-root-survey-batch/3",
            "request_sha256": request_sha256,
            "leaf_id": leaf.leaf_id,
            "job_id": leaf.job.job_id,
            "backend_identity_sha256": leaf.job.backend_identity.identity_sha256,
            "precision_digits": digits,
            "working_precision_bits": working_precision_bits(
                PrecisionTier.BIGFLOAT_40
                if digits == 40 else PrecisionTier.BIGFLOAT_80
            ),
            "semantic_precision_tier": f"bigfloat-{digits}",
            "effective_policy_identity": leaf.job.policy.identity_sha256,
            "execution_resource_policy_identity": {"sha256": "3" * 64},
            "plan": contract.plan.value,
            "scientific_operation_identity": contract.scientific_operation_identity,
            "root_reference_id": leaf.job.root.root_reference_id,
            "root_seal_sha256": seal.root_seal_sha256,
            "branch_identity": seal.branch_identity,
            "sample_roles": list(contract.sample_roles),
        })
    else:
        request_sha256 = prepared_request.request_sha256
        identity = operation_execution_identity(
            prepared_request.document["execution_identity"]
        )
    samples = []
    for index, role in enumerate(contract.sample_roles):
        omega, amplitude = point_by_role[role]
        frequency = 0.0 if flat else 3.0 * (omega.real - root.real)
        determinant = DecimalComplex(
            Decimal(str(frequency + 2.0 * amplitude)), Decimal(0)
        )
        samples.append(JuliaFixedRootSurveySample(
            index,
            role,
            complex(omega),
            complex(amplitude),
            determinant,
            _conditioning(digits, precision_limited=flat),
            identity.select_sample(index, role).to_mapping(),
        ))
    tier = (
        PrecisionTier.BIGFLOAT_40
        if digits == 40 else PrecisionTier.BIGFLOAT_80
    )
    return JuliaFixedRootSurveyBatch(
        leaf_id=leaf.leaf_id,
        job_id=leaf.job.job_id,
        mechanism_id=leaf.mechanism_id,
        root_reference_id=leaf.job.root.root_reference_id,
        root_seal_sha256=seal.root_seal_sha256,
        branch_identity=seal.branch_identity,
        fixed_root=root,
        frequency_step=Decimal(format(h, ".17g")),
        coordinate_step=Decimal(str(epsilon)),
        scientific_operation_identity=contract.scientific_operation_identity,
        plan=contract.plan,
        execution_identity=identity.to_mapping(),
        request_sha256=request_sha256,
        precision_tier=tier,
        working_precision_bits=working_precision_bits(tier),
        samples=tuple(samples),
    )


def _provisional_stage(leaf, scientific_identity: str, root_seal_sha256: str):
    root = leaf.job.root.omega
    frequency_step = 1.0e-5 * (1.0 + abs(root))
    coordinate_step = float(leaf.job.policy.epsilons[0])
    points = (
        (root, 0.0),
        (root + frequency_step, 0.0),
        (root - frequency_step, 0.0),
        (root + frequency_step / 2.0, 0.0),
        (root - frequency_step / 2.0, 0.0),
        (root, coordinate_step),
        (root, -coordinate_step),
        (root, coordinate_step / 2.0),
        (root, -coordinate_step / 2.0),
    )
    batch = Binary64FixedRootBatch(
        leaf_id=leaf.leaf_id,
        job_id=leaf.job.job_id,
        mechanism_id=leaf.mechanism_id,
        fixed_root=root,
        branch_identity=leaf.job.root.branch_id,
        frequency_step=frequency_step,
        coordinate_step=coordinate_step,
        support=_exterior_support(leaf.job.spin, leaf.mechanism_id),
        samples=tuple(
            Binary64FixedRootSample(
                role=role,
                omega=omega,
                amplitude=complex(amplitude, 0.0),
                determinant=complex(index + 1.0, 0.0),
            )
            for index, (role, (omega, amplitude)) in enumerate(
                zip(BINARY64_FIXED_ROOT_SAMPLE_ROLES, points)
            )
        ),
    )
    reuse_key = build_exterior_background_reuse_key(
        leaf.job,
        root_seal_sha256=root_seal_sha256,
        fixed_root=root,
    )
    background = canonical_background_from_binary64_batch(batch, reuse_key)
    receipt = BackgroundEquivalenceReceipt.issue(
        reuse_key=reuse_key,
        job=leaf.job,
        canonical_background_sha256=background.sha256,
        fixed_root=root,
    )
    return build_exterior_provisional_stage(
        job=leaf.job,
        scientific_computation_identity=scientific_identity,
        root_seal_sha256=root_seal_sha256,
        raw_batch=batch,
        combined_batch=batch,
        background=background,
        background_receipt=receipt,
        reason_code="DETERMINANT_ERROR_EVIDENCE_UNAVAILABLE",
    )


class _Backend:
    def __init__(
        self,
        leaf,
        digits: int,
        flat: bool,
        calls: list[int],
        failure_code: str | None = None,
    ) -> None:
        self.leaf = leaf
        self.digits = digits
        self.flat = flat
        self.calls = calls
        self.failure_code = failure_code

    def prepare_fixed_root_survey_request(self, job, **kwargs):
        return PreparedFixedRootSurveyRequest.from_request(
            _fixture_fixed_root_request(job, self.digits, kwargs)
        )

    def fixed_root_survey_batch(self, job, **kwargs):
        self.calls.append(self.digits)
        prepared_request = kwargs.get("prepared_request")
        if prepared_request is not None:
            expected = self.prepare_fixed_root_survey_request(job, **kwargs)
            if prepared_request != expected:
                raise AssertionError("scheduler changed its prepared request")
        if self.failure_code is not None:
            contract = _requested_contract(kwargs)
            if prepared_request is None:
                canonical_request = _fixture_fixed_root_request(
                    job, self.digits, kwargs
                )
                request_sha256 = _sha256(canonical_request)
            else:
                canonical_request = dict(prepared_request.request_binding)
                request_sha256 = prepared_request.request_sha256
            identity = execution_identity_from_request(
                canonical_request,
                request_sha256=request_sha256,
                sample_index=0,
                sample_role=contract.sample_roles[0],
            )
            if self.failure_code == "ODE_RESOURCE_LIMIT":
                stage = "homogeneous-propagation"
                diagnostics = {
                    "limit_kind": "accepted_steps",
                    "limiting_resource": "accepted_steps",
                    "ode_leg": "infinity",
                    "elapsed_leg_seconds": "1.25",
                    "ode_snapshot": {
                        "ode_leg": "infinity",
                        "ode_endpoint_reached": False,
                        "ode_retcode": "ResourceLimit",
                        "elapsed_seconds": "1.25",
                    },
                }
            elif self.failure_code.startswith("EXTERIOR_ENDPOINT_"):
                stage = "asymptotic-preflight"
                diagnostics = _endpoint_control_diagnostics(
                    canonical_request, self.failure_code
                )
            else:
                stage = "asymptotic-preflight"
                diagnostics = {
                    "reason": "INSUFFICIENT_ASYMPTOTIC_PRECISION",
                    "precision_bits": canonical_request[
                        "working_precision_bits"
                    ],
                    "factored_homogeneous_rhs_evaluations": 0,
                    "avoided_ode_scope": "factored-homogeneous-gsn/v1",
                    "predicted_reliable_digits": "10",
                    "required_reliable_digits": "20",
                    "asymptotic_preflight_avoided_ode": True,
                    "asymptotic_preflight_reason": (
                        "INSUFFICIENT_ASYMPTOTIC_PRECISION"
                    ),
                    "maximum_series_digits_lost": "30",
                    "maximum_recurrence_digits_lost": "5",
                }
            receipt = validate_operation_control_receipt(
                build_operation_control_receipt(
                    origin=JULIA_WORKER_ORIGIN,
                    failure_code=self.failure_code,
                    stage=stage,
                    identity=identity,
                    diagnostics=diagnostics,
                ),
                request=canonical_request,
                request_sha256=request_sha256,
                diagnostics_validator=lambda _receipt: True,
            )
            if self.failure_code == "ODE_RESOURCE_LIMIT":
                error = JuliaODEResourceLimitError(
                    "reviewed ODE resource limit"
                )
                error.control_receipt = receipt
                raise error
            raise JuliaNumericalControlError(
                "reviewed numerical insufficiency",
                self.failure_code,
                control_receipt=receipt,
            )
        seal = AuthenticatedRootSeal(
            kwargs["fixed_root"], kwargs["branch_identity"],
            kwargs["root_seal_sha256"],
        )
        return _batch(
            self.leaf,
            seal,
            self.digits,
            flat=self.flat,
            plan=_requested_contract(kwargs).plan,
            prepared_request=prepared_request,
        )


class PromotedSurveySchedulerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.plan = build_campaign_plan(
            policy=NumericalPolicy(),
            backend_identity=VettedNativeDeterminantKernel.identity,
            precision_capabilities=PrecisionCapabilities((64, 80)),
        )
        exterior = tuple(
            leaf for leaf in cls.plan.leaves
            if leaf.mechanism_id != "horizon-admittance"
        )[:2]
        cls.leaves = exterior
        selected = build_campaign_selection(
            cls.plan, role="primary",
            leaf_ids=tuple(leaf.leaf_id for leaf in exterior),
        )
        cls.selection = RecoverySelection(
            campaign_id=cls.plan.campaign_id,
            selection_id=selected.selection_id,
            ordered_leaf_ids=tuple(selected.leaf_ids),
            roles={leaf.leaf_id: leaf.role for leaf in exterior},
            scientific_identities={
                leaf.leaf_id: scientific_computation_identity_sha256(
                    cls.plan, leaf
                ) for leaf in exterior
            },
        )

    def _checkpoint(self, kind=PromotionQueueKind.RESPONSE, count=1):
        checkpoint = empty_schema11_checkpoint(
            self.selection.campaign_id, self.selection.selection_id
        )
        for leaf in self.leaves[:count]:
            scientific_identity = self.selection.scientific_identities[leaf.leaf_id]
            provisional_stage = None
            provisional_stage_sha256 = None
            provisional_operation_identity = None
            binary64_disposition_receipt_sha256 = None
            if kind is PromotionQueueKind.RESPONSE:
                provisional_stage, provisional_stage_sha256 = _provisional_stage(
                    leaf, scientific_identity, "a" * 64
                )
                provisional_operation_identity = str(
                    provisional_stage["operation_identity"]
                )
                checkpoint = record_survey_disposition(
                    checkpoint,
                    survey_pass=SurveyPass.BINARY64,
                    leaf_id=leaf.leaf_id,
                    disposition=SurveyDisposition.PROMOTION_PENDING_RESPONSE,
                    operation_identity="binary64-fixed-root-survey/v1",
                    precision_tiers=("binary64",),
                    reason_code="FINITE_DIFFERENCE_NOISE_LIMIT",
                    sample_count=9,
                    sample_limit=9,
                    root_read_count=0,
                    root_read_limit=0,
                    worker_launch_count=0,
                    worker_launch_limit=0,
                    tier_timing=(),
                    session_fragments=(),
                )
                binary64_disposition_receipt_sha256 = checkpoint[
                    "survey_pass_ledger"
                ]["binary64"][leaf.leaf_id]["disposition_receipt_sha256"]
            checkpoint = append_promotion(
                checkpoint,
                leaf_id=leaf.leaf_id,
                queue_kind=kind,
                reason_code=(
                    "FINITE_DIFFERENCE_NOISE_LIMIT"
                    if kind is PromotionQueueKind.RESPONSE
                    else "DETERMINANT_UNCERTAINTY_TOO_LARGE"
                ),
                minimum_requested_tier="BF40",
                scientific_computation_identity=scientific_identity,
                source_root_seal_sha256=(
                    "a" * 64 if kind is PromotionQueueKind.RESPONSE else None
                ),
                source_stage_sha256=provisional_stage_sha256,
                provisional_stage=provisional_stage,
                provisional_stage_sha256=provisional_stage_sha256,
                provisional_operation_identity=provisional_operation_identity,
                source_binary64_disposition_receipt_sha256=(
                    binary64_disposition_receipt_sha256
                ),
            )
        return checkpoint

    def _run(
        self,
        checkpoint,
        *,
        flat40=False,
        flat80=False,
        failure40: str | None = None,
        failure80: str | None = None,
        root_runner=None,
        diagnostic_session=None,
        calculate_only=False,
        block_all=False,
        checkpoint_committed=None,
        backend_factory=None,
    ):
        calls: list[int] = []
        published: dict[str, AuthenticatedRootSeal] = {}

        def root_seal_lookup(leaf, entry):
            source_sha256 = entry["source_root_seal_sha256"]
            if source_sha256 is not None:
                return AuthenticatedRootSeal(
                    leaf.job.root.omega,
                    leaf.job.root.branch_id,
                    source_sha256,
                )
            return published.get(leaf.leaf_id)

        with tempfile.TemporaryDirectory() as temporary:
            routes = _locked_routes(checkpoint, self.leaves)
            preflights = {
                ordinal: (
                    PromotedExecutionPreflight(
                        mode=PromotedExecutionMode.BLOCK_ALL,
                        route=route.route,
                        calibration_receipt_sha256="e" * 64,
                        calculation_permitted=False,
                        checkpointing_permitted=False,
                        admission_permitted=False,
                        publication_permitted=False,
                        result_code="BLOCKED_BY_ADMISSION_POLICY",
                    )
                    if block_all
                    else require_locked_bf40_determinant_error_issuance_authority(
                        route=route.route
                    )
                )
                for ordinal, route in routes.items()
            }
            result = _strict_run(
                self.plan,
                self.selection,
                checkpoint,
                checkpoint_path=Path(temporary) / "checkpoint.json",
                root_seal_lookup=root_seal_lookup,
                root_seal_publish=lambda leaf, seal: published.__setitem__(
                    leaf.leaf_id, seal
                ),
                backend_factory=(
                    backend_factory
                    if backend_factory is not None
                    else lambda leaf, digits: _Backend(
                        leaf, digits,
                        flat40 if digits == 40 else flat80,
                        calls,
                        failure40 if digits == 40 else failure80,
                    )
                ),
                primary_root_runner=(
                    root_runner
                    if root_runner is not None
                    else lambda leaf, backend, digits: _durable_root_result(
                        leaf, digits
                    )
                ),
                horizon_runner=lambda leaf: self.fail("unexpected horizon"),
                layer1_guard=_TestLayer1Guard(),
                locked_routes_by_ordinal=routes,
                promoted_preflights_by_ordinal=preflights,
                layer1_lock_receipt_sha256="f" * 64,
                diagnostic_session=diagnostic_session,
                checkpoint_committed=checkpoint_committed,
            )
        return result, calls

    def _interrupt_after_control_state(
        self,
        target: str,
        *,
        failure_code: str = "EXTERIOR_ENDPOINT_ARITHMETIC_INADEQUATE",
    ):
        durable: list[dict[str, object]] = []

        def stop_after_commit(checkpoint):
            entry = checkpoint["promotion_queue"]["entries"][0]
            if entry["disposition"] == target:
                durable.append(copy.deepcopy(checkpoint))
                raise KeyboardInterrupt
            return checkpoint

        with self.assertRaises(KeyboardInterrupt):
            self._run(
                self._checkpoint(),
                failure40=failure_code,
                checkpoint_committed=stop_after_commit,
            )
        self.assertEqual(1, len(durable))
        return durable[0]

    def _forged_bf80_decision_stage(self, checkpoint):
        """Reseal a promotion decision over an actually deferred return."""

        leaf_id = self.leaves[0].leaf_id
        return_stage = copy.deepcopy(
            checkpoint["promoted_stage_ledger"]["0"][leaf_id]
        )
        control_return = return_stage["control_return"]
        return_authority = authenticate_persisted_control_return(
            control_return,
            expected_schema=str(control_return["schema"]),
            expected_leaf_id=leaf_id,
            expected_current_action_kind="RESPONSE",
            expected_queue_ordinal=0,
        )
        authority = resolve_persisted_control_return(return_authority)
        decision = authority.normalized_decision(
            schema=PROMOTED_CONTROL_DECISION_SCHEMA,
            current_tier="BF40",
            current_action_kind="RESPONSE",
        )
        self.assertEqual("DEFERRED", decision["disposition"])
        decision.update({
            "disposition": "PROMOTION_PENDING",
            "queue_kind": "RESPONSE",
            "next_tier": "BF80",
            "next_action_kind": "RESPONSE",
        })
        decision["control_decision_sha256"] = _sha256({
            key: value
            for key, value in decision.items()
            if key != "control_decision_sha256"
        })

        decision_stage = copy.deepcopy(return_stage)
        decision_stage.update({
            "schema": PROMOTED_CONTROL_DECISION_STAGE_SCHEMA,
            "admission_state": (
                PromotionQueueDisposition.CONTROL_DECISION_RETAINED.value
            ),
            "operation_identity": "promoted-exterior-control-decision/v1",
            "numerical_disposition": "PROMOTION_PENDING",
            "source_calculation_stage_sha256": return_stage["stage_sha256"],
            "calculation_chain": [
                *copy.deepcopy(return_stage["calculation_chain"]),
                copy.deepcopy(return_stage),
            ],
            "control_decision": decision,
        })
        decision_stage.pop("control_return")
        decision_stage["stage_sha256"] = _sha256({
            key: value
            for key, value in decision_stage.items()
            if key != "stage_sha256"
        })
        return decision_stage

    def _forged_bf80_continuation_stage(self, decision_stage):
        return_stage = decision_stage["calculation_chain"][-1]
        control_return = return_stage["control_return"]
        decision = decision_stage["control_decision"]
        proof_content = {
            "schema": PROMOTED_CONTROL_CONTINUATION_PROOF_SCHEMA,
            "control_return_stage_sha256": return_stage["stage_sha256"],
            "control_return_sha256": control_return["control_return_sha256"],
            "control_decision_stage_sha256": decision_stage["stage_sha256"],
            "control_decision_sha256": decision["control_decision_sha256"],
            "transition_id": decision["transition_id"],
            "current_tier": "BF40",
            "current_action_kind": "RESPONSE",
            "next_tier": "BF80",
            "next_action_kind": "RESPONSE",
        }
        continuation = copy.deepcopy(decision_stage)
        continuation.update({
            "schema": PROMOTED_CONTROL_CONTINUATION_STAGE_SCHEMA,
            "admission_state": (
                PromotionQueueDisposition.NUMERICAL_CONTINUATION.value
            ),
            "next_precision_tier": "BF80",
            "numerical_disposition": "AWAITING_BF80",
            "source_calculation_stage_sha256": decision_stage["stage_sha256"],
            "calculation_chain": [
                *copy.deepcopy(decision_stage["calculation_chain"]),
                copy.deepcopy(decision_stage),
            ],
            "control_proof": {
                **proof_content,
                "proof_sha256": _sha256(proof_content),
            },
        })
        continuation.pop("control_decision")
        continuation["stage_sha256"] = _sha256({
            key: value
            for key, value in continuation.items()
            if key != "stage_sha256"
        })
        return continuation

    def _reseal_current_promoted_stage(self, checkpoint):
        leaf_id = self.leaves[0].leaf_id
        stage = checkpoint["promoted_stage_ledger"]["0"][leaf_id]
        stage["stage_sha256"] = _sha256({
            key: value for key, value in stage.items() if key != "stage_sha256"
        })
        entry = checkpoint["promotion_queue"]["entries"][0]
        entry["retained_promoted_stage_sha256"] = stage["stage_sha256"]
        entry["disposition_receipt_sha256"] = _sha256({
            "schema": "windows-solver.test-resealed-stage-pointer/1",
            "stage_sha256": stage["stage_sha256"],
            "disposition": entry["disposition"],
        })

    def test_calculate_only_stops_at_bf40_and_retains_without_admission(self):
        first, calls = self._run(
            self._checkpoint(),
            calculate_only=True,
        )

        leaf_id = self.leaves[0].leaf_id
        queue_entry = first.checkpoint["promotion_queue"]["entries"][0]
        stage = first.checkpoint["promoted_stage_ledger"]["0"][leaf_id]
        self.assertEqual([40, 40], calls)
        self.assertEqual("AWAITING_ADMISSION", queue_entry["disposition"])
        self.assertEqual(
            "CALCULATED_AWAITING_ADMISSION",
            first.checkpoint["survey_pass_ledger"]["promoted"][leaf_id][
                "disposition"
            ],
        )
        self.assertEqual("CALCULATE_ONLY", stage["execution_mode"])
        self.assertEqual("EXTERIOR_BF40", stage["route"])
        self.assertEqual("f" * 64, stage["layer1_lock_receipt_sha256"])
        self.assertEqual(["bigfloat-40", "bigfloat-40"], [
            batch["precision_tier"] for batch in stage["raw_promoted_batches"]
        ])
        self.assertEqual([], first.checkpoint["records"])
        self.assertEqual({}, first.checkpoint["evidence_ledger"])
        self.assertEqual(1, first.review_pending_count)

        resumed, resumed_calls = self._run(
            first.checkpoint,
            calculate_only=True,
        )
        self.assertEqual([], resumed_calls)
        self.assertEqual(
            stage,
            resumed.checkpoint["promoted_stage_ledger"]["0"][leaf_id],
        )

    def test_block_all_returns_typed_policy_result_without_backend_work(self):
        result, calls = self._run(self._checkpoint(), block_all=True)

        self.assertEqual([], calls)
        self.assertEqual(1, result.policy_blocked_count)
        entry = result.checkpoint["promotion_queue"]["entries"][0]
        leaf_id = entry["leaf_id"]
        stage = result.checkpoint["promoted_stage_ledger"]["0"][leaf_id]
        self.assertEqual("DEFERRED", entry["disposition"])
        self.assertEqual(PROMOTED_POLICY_TERMINAL_STAGE_SCHEMA, stage["schema"])
        self.assertEqual(stage["stage_sha256"], entry[
            "retained_promoted_stage_sha256"
        ])
        self.assertEqual("DEFERRED", stage["policy_terminal"]["disposition"])
        self.assertEqual(1, len(result.route_results))
        self.assertEqual(
            "BLOCKED_BY_ADMISSION_POLICY",
            result.route_results[0].result_code,
        )
        self.assertFalse(result.route_results[0].numerical_work_performed)

        erased = copy.deepcopy(result.checkpoint)
        del erased["promoted_stage_ledger"]["0"]
        erased["promotion_queue"]["entries"][0][
            "retained_promoted_stage_sha256"
        ] = None
        del erased["survey_pass_ledger"]["promoted"][leaf_id]
        with self.assertRaisesRegex(ValueError, "retained authority stage"):
            validate_schema11_checkpoint(erased)

    def test_calculate_only_reuses_same_tier_promoted_background(self):
        result, calls = self._run(
            self._checkpoint(count=2),
            calculate_only=True,
        )

        self.assertEqual([40, 40, 40], calls)
        background_entries = result.checkpoint["promoted_background_ledger"]
        self.assertEqual(["0"], list(background_entries))
        source_leaf = self.leaves[0]
        receipt = background_entries["0"][source_leaf.leaf_id]["payload"][
            "background_receipts"
        ][0]
        self.assertEqual(0, receipt["source_queue_ordinal"])
        self.assertEqual(source_leaf.leaf_id, receipt["source_leaf_id"])
        bindings = [
            result.checkpoint["promoted_stage_ledger"][str(ordinal)][leaf.leaf_id][
                "calculation_artifact"
            ]["background"]
            for ordinal, leaf in enumerate(self.leaves)
        ]
        self.assertEqual(
            [receipt["receipt_sha256"], receipt["receipt_sha256"]],
            [binding["background_receipt_sha256"] for binding in bindings],
        )
        self.assertEqual(
            [receipt["background_sha256"], receipt["background_sha256"]],
            [binding["background_sha256"] for binding in bindings],
        )
        promoted_ledger = result.checkpoint["survey_pass_ledger"]["promoted"]
        self.assertEqual(
            [9, 4],
            [promoted_ledger[leaf.leaf_id]["sample_count"] for leaf in self.leaves],
        )

    def test_calculate_only_retains_bf80_numerical_exhaustion_without_screening(self):
        result, calls = self._run(
            self._checkpoint(),
            calculate_only=True,
            failure40="EXTERIOR_ENDPOINT_ARITHMETIC_INADEQUATE",
            failure80="EXTERIOR_ENDPOINT_ARITHMETIC_INADEQUATE",
        )

        leaf_id = self.leaves[0].leaf_id
        queue_entry = result.checkpoint["promotion_queue"]["entries"][0]
        retained = result.checkpoint["promoted_stage_ledger"]["0"][leaf_id]
        self.assertEqual([40, 80], calls)
        self.assertEqual("UNRESOLVED", queue_entry["disposition"])
        self.assertEqual(
            "UNRESOLVED",
            result.checkpoint["survey_pass_ledger"]["promoted"][leaf_id][
                "disposition"
            ],
        )
        self.assertEqual(
            "EXTERIOR_ENDPOINT_ARITHMETIC_INADEQUATE", retained["reason_code"]
        )
        self.assertEqual(["BF40", "BF80"], retained["precision_tiers"])
        self.assertEqual({}, result.checkpoint["evidence_ledger"])
        self.assertEqual([], result.checkpoint["records"])

    def test_bf80_interruption_resumes_from_the_retained_bf40_stage(self):
        checkpoint = self._checkpoint(PromotionQueueKind.ROOT)
        interrupted_calls: list[int] = []
        resumed_calls: list[int] = []
        root_calls: list[int] = []

        def root_seal_lookup(_leaf, _entry):
            return None

        def primary_root_runner(leaf, _backend, digits):
            root_calls.append(digits)
            return _durable_root_result(leaf, digits)

        class InterruptingBackend(_Backend):
            def fixed_root_survey_batch(self, job, **kwargs):
                if self.digits == 40:
                    self.failure_code = "EXTERIOR_ENDPOINT_ARITHMETIC_INADEQUATE"
                    return super().fixed_root_survey_batch(job, **kwargs)
                if self.digits == 80:
                    self.calls.append(self.digits)
                    raise KeyboardInterrupt
                return super().fixed_root_survey_batch(job, **kwargs)

        preflight = require_locked_bf40_determinant_error_issuance_authority(
            route="EXTERIOR_BF40"
        )
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "checkpoint.json"
            with self.assertRaises(KeyboardInterrupt):
                _strict_run(
                    self.plan,
                    self.selection,
                    checkpoint,
                    checkpoint_path=path,
                    root_seal_lookup=root_seal_lookup,
                    provisional_stage_lookup=lambda _leaf, entry: entry[
                        "provisional_stage"
                    ],
                    root_seal_publish=lambda *_args: None,
                    backend_factory=lambda leaf, digits: InterruptingBackend(
                        leaf,
                        digits,
                        False,
                        interrupted_calls,
                    ),
                    primary_root_runner=primary_root_runner,
                    horizon_runner=lambda _leaf: self.fail("unexpected horizon"),
                    promoted_preflights_by_ordinal={0: preflight},
                    layer1_lock_receipt_sha256="f" * 64,
                )

            interrupted = json.loads(path.read_text(encoding="utf-8"))
            partial = interrupted["promoted_stage_ledger"]["0"][
                self.leaves[0].leaf_id
            ]
            self.assertEqual([40, 80], interrupted_calls)
            self.assertEqual([40], root_calls)
            self.assertEqual(
                "NUMERICAL_CONTINUATION",
                interrupted["promotion_queue"]["entries"][0]["disposition"],
            )
            self.assertEqual("NUMERICAL_CONTINUATION", partial["admission_state"])
            self.assertEqual(["BF40"], partial["precision_tiers"])

            resumed = _strict_run(
                self.plan,
                self.selection,
                interrupted,
                checkpoint_path=path,
                root_seal_lookup=root_seal_lookup,
                provisional_stage_lookup=lambda _leaf, entry: entry[
                    "provisional_stage"
                ],
                root_seal_publish=lambda *_args: None,
                backend_factory=lambda leaf, digits: _Backend(
                    leaf, digits, False, resumed_calls
                ),
                primary_root_runner=lambda *_args: self.fail(
                    "resume must reuse the retained BF40 root seal"
                ),
                horizon_runner=lambda _leaf: self.fail("unexpected horizon"),
                promoted_preflights_by_ordinal={0: preflight},
                layer1_lock_receipt_sha256="f" * 64,
            )

        retained = resumed.checkpoint["promoted_stage_ledger"]["0"][
            self.leaves[0].leaf_id
        ]
        self.assertEqual([80, 80], resumed_calls)
        self.assertEqual([40], root_calls)
        self.assertEqual(
            "AWAITING_ADMISSION",
            resumed.checkpoint["promotion_queue"]["entries"][0]["disposition"],
        )
        self.assertEqual(["BF40", "BF80"], retained["precision_tiers"])

    def test_resume_reloads_promoted_background_without_reacquiring_it(self):
        first, _ = self._run(
            self._checkpoint(count=1),
            calculate_only=True,
        )
        resumable = self._checkpoint(count=2)
        resumable["promotion_queue"]["entries"][0] = copy.deepcopy(
            first.checkpoint["promotion_queue"]["entries"][0]
        )
        resumable["survey_pass_ledger"]["promoted"] = copy.deepcopy(
            first.checkpoint["survey_pass_ledger"]["promoted"]
        )
        for ledger_name in (
            "promoted_stage_ledger",
            "promoted_background_ledger",
            "promoted_root_ledger",
        ):
            resumable[ledger_name] = copy.deepcopy(first.checkpoint[ledger_name])

        resumed, calls = self._run(resumable, calculate_only=True)

        first_leaf, second = self.leaves
        receipt = resumed.checkpoint["promoted_background_ledger"]["0"][
            first_leaf.leaf_id
        ]["payload"]["background_receipts"][0]
        second_binding = resumed.checkpoint["promoted_stage_ledger"]["1"][
            second.leaf_id
        ]["calculation_artifact"]["background"]
        self.assertEqual([40], calls)
        self.assertEqual(0, receipt["source_queue_ordinal"])
        self.assertEqual(first_leaf.leaf_id, receipt["source_leaf_id"])
        self.assertEqual(
            receipt["receipt_sha256"],
            second_binding["background_receipt_sha256"],
        )
        self.assertEqual(
            4,
            resumed.checkpoint["survey_pass_ledger"]["promoted"][
                second.leaf_id
            ]["sample_count"],
        )

    def test_interruption_after_background_acquisition_reuses_it_on_resume(self):
        """The five shared samples survive an interruption before mechanisms run."""

        checkpoint = self._checkpoint(count=1)
        first_roles: list[tuple[str, ...]] = []
        resumed_roles: list[tuple[str, ...]] = []
        preflight = require_locked_bf40_determinant_error_issuance_authority(
            route="EXTERIOR_BF40"
        )

        def root_seal_lookup(leaf, entry):
            return AuthenticatedRootSeal(
                leaf.job.root.omega,
                leaf.job.root.branch_id,
                str(entry["source_root_seal_sha256"]),
            )

        def subset_batch(backend, kwargs):
            seal = AuthenticatedRootSeal(
                kwargs["fixed_root"],
                kwargs["branch_identity"],
                kwargs["root_seal_sha256"],
            )
            contract = _requested_contract(kwargs)
            return _batch(
                backend.leaf,
                seal,
                backend.digits,
                plan=contract.plan,
                prepared_request=kwargs.get("prepared_request"),
            )

        class InterruptingBackend(_Backend):
            def fixed_root_survey_batch(self, job, **kwargs):
                roles = _requested_contract(kwargs).sample_roles
                first_roles.append(roles)
                self.calls.append(self.digits)
                if roles == tuple(BINARY64_FIXED_ROOT_SAMPLE_ROLES[:5]):
                    return subset_batch(self, kwargs)
                if roles == tuple(BINARY64_FIXED_ROOT_SAMPLE_ROLES[5:]):
                    raise KeyboardInterrupt
                raise AssertionError("unexpected promoted sample request")

        class ResumeBackend(_Backend):
            def fixed_root_survey_batch(self, job, **kwargs):
                roles = _requested_contract(kwargs).sample_roles
                resumed_roles.append(roles)
                self.calls.append(self.digits)
                if roles != tuple(BINARY64_FIXED_ROOT_SAMPLE_ROLES[5:]):
                    raise AssertionError(
                        "resume must not reacquire the promoted background"
                    )
                return subset_batch(self, kwargs)

        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "checkpoint.json"
            with self.assertRaises(KeyboardInterrupt):
                _strict_run(
                    self.plan,
                    self.selection,
                    checkpoint,
                    checkpoint_path=path,
                    root_seal_lookup=root_seal_lookup,
                    provisional_stage_lookup=lambda _leaf, entry: entry[
                        "provisional_stage"
                    ],
                    root_seal_publish=lambda *_args: None,
                    backend_factory=lambda leaf, digits: InterruptingBackend(
                        leaf, digits, False, []
                    ),
                    primary_root_runner=lambda *_args: self.fail("unexpected root"),
                    horizon_runner=lambda _leaf: self.fail("unexpected horizon"),
                    promoted_preflights_by_ordinal={0: preflight},
                    layer1_lock_receipt_sha256="f" * 64,
                )

            interrupted = json.loads(path.read_text(encoding="utf-8"))
            leaf_id = self.leaves[0].leaf_id
            background_receipts = interrupted["promoted_background_ledger"]["0"][
                leaf_id
            ]["payload"]["background_receipts"]
            self.assertEqual(0, background_receipts[0]["source_queue_ordinal"])
            self.assertEqual(leaf_id, background_receipts[0]["source_leaf_id"])
            self.assertEqual(
                list(BINARY64_FIXED_ROOT_SAMPLE_ROLES[:5]),
                background_receipts[0]["background_worker_batch"]["sample_roles"],
            )
            self.assertEqual(
                "PENDING", interrupted["promotion_queue"]["entries"][0]["disposition"]
            )
            self.assertEqual({}, interrupted["promoted_stage_ledger"])

            resumed = _strict_run(
                self.plan,
                self.selection,
                interrupted,
                checkpoint_path=path,
                root_seal_lookup=root_seal_lookup,
                provisional_stage_lookup=lambda _leaf, entry: entry[
                    "provisional_stage"
                ],
                root_seal_publish=lambda *_args: None,
                backend_factory=lambda leaf, digits: ResumeBackend(
                    leaf, digits, False, []
                ),
                primary_root_runner=lambda *_args: self.fail("unexpected root"),
                horizon_runner=lambda _leaf: self.fail("unexpected horizon"),
                promoted_preflights_by_ordinal={0: preflight},
                layer1_lock_receipt_sha256="f" * 64,
            )

        self.assertEqual(
            [
                tuple(BINARY64_FIXED_ROOT_SAMPLE_ROLES[:5]),
                tuple(BINARY64_FIXED_ROOT_SAMPLE_ROLES[5:]),
            ],
            first_roles,
        )
        self.assertEqual(
            [tuple(BINARY64_FIXED_ROOT_SAMPLE_ROLES[5:])], resumed_roles
        )
        self.assertEqual(
            "AWAITING_ADMISSION",
            resumed.checkpoint["promotion_queue"]["entries"][0]["disposition"],
        )
        promoted = resumed.checkpoint["survey_pass_ledger"]["promoted"][
            self.leaves[0].leaf_id
        ]
        self.assertEqual(9, promoted["sample_count"])
        self.assertEqual(2, promoted["worker_launch_count"])

    def test_component_control_accounts_from_durable_background_and_attempt(self):
        durable: list[dict[str, object]] = []
        calls: list[int] = []

        class ComponentFailureBackend(_Backend):
            def fixed_root_survey_batch(self, job, **kwargs):
                if (
                    self.digits == 40
                    and FixedRootSurveyPlan(kwargs["plan"])
                    is FixedRootSurveyPlan.MECHANISM_COMPONENT_FOUR
                ):
                    self.failure_code = "EXTERIOR_ENDPOINT_ARITHMETIC_INADEQUATE"
                return super().fixed_root_survey_batch(job, **kwargs)

        def stop_after_control_return(checkpoint):
            if checkpoint["promotion_queue"]["entries"][0]["disposition"] == (
                PromotionQueueDisposition.CONTROL_RETURN_RETAINED.value
            ):
                durable.append(copy.deepcopy(checkpoint))
                raise KeyboardInterrupt
            return checkpoint

        with self.assertRaises(KeyboardInterrupt):
            self._run(
                self._checkpoint(),
                backend_factory=lambda leaf, digits: ComponentFailureBackend(
                    leaf, digits, False, calls
                ),
                checkpoint_committed=stop_after_control_return,
            )

        stage = durable[0]["promoted_stage_ledger"]["0"][self.leaves[0].leaf_id]
        control_return = stage["control_return"]
        self.assertEqual(
            "windows-solver.promoted-exterior-control-return/4",
            control_return["schema"],
        )
        self.assertEqual(
            {"schema", "evidence_receipts", "attempt_records"},
            set(control_return["partial_work"]),
        )
        self.assertEqual(5, stage["sample_count"])
        self.assertEqual(0, stage["root_read_count"])
        self.assertEqual(2, stage["worker_launch_count"])
        self.assertEqual(1, len(control_return["partial_work"]["attempt_records"]))
        expected = control_return["expected_action"]
        self.assertEqual(
            FixedRootSurveyPlan.MECHANISM_COMPONENT_FOUR.value,
            expected["plan"],
        )
        self.assertEqual(control_return["request_sha256"], expected["request_sha256"])

    def test_background_control_rejects_component_phase_receipt(self):
        calls: list[int] = []

        class WrongPhaseBackend(_Backend):
            def fixed_root_survey_batch(self, job, **kwargs):
                if FixedRootSurveyPlan(kwargs["plan"]) is (
                    FixedRootSurveyPlan.CANONICAL_BACKGROUND_FIVE
                ):
                    forged = dict(kwargs)
                    forged.pop("prepared_request", None)
                    forged["plan"] = FixedRootSurveyPlan.MECHANISM_COMPONENT_FOUR
                    self.failure_code = "EXTERIOR_ENDPOINT_ARITHMETIC_INADEQUATE"
                    return super().fixed_root_survey_batch(job, **forged)
                return super().fixed_root_survey_batch(job, **kwargs)

        with self.assertRaises(CampaignSystemFailure):
            self._run(
                self._checkpoint(),
                backend_factory=lambda leaf, digits: WrongPhaseBackend(
                    leaf, digits, False, calls
                ),
            )

    def test_requested_events_name_the_exact_dispatched_authority(self):
        with tempfile.TemporaryDirectory() as temporary:
            session = StructuralDiagnosticSession.open(
                checkpoint_path=Path(temporary) / "diagnostic-checkpoint.json",
                session_id="prepared-request-events",
                campaign_id=self.selection.campaign_id,
                selection_id=self.selection.selection_id,
            )
            try:
                self._run(self._checkpoint(), diagnostic_session=session)
                events = session.final_events()
            finally:
                session.close_completed()

        for prefix in ("PROMOTED_BACKGROUND", "PROMOTED_COMPONENT"):
            requested = next(
                event for event in events
                if event["event_kind"] == f"{prefix}_REQUESTED"
            )["compact_diagnostics"]
            returned = next(
                event for event in events
                if event["event_kind"] == f"{prefix}_RETURNED"
            )["compact_diagnostics"]
            self.assertEqual(
                returned["worker_request_sha256"], requested["request_sha256"]
            )
            self.assertEqual(
                returned["execution_identity_sha256"],
                requested["execution_identity_sha256"],
            )

    def test_calculated_root_evidence_is_retained_in_root_ledger(self):
        result, calls = self._run(
            self._checkpoint(PromotionQueueKind.ROOT),
            calculate_only=True,
        )

        leaf_id = self.leaves[0].leaf_id
        root_payload = result.checkpoint["promoted_root_ledger"]["0"][leaf_id][
            "payload"
        ]
        self.assertEqual([40, 40], calls)
        self.assertEqual(1, len(root_payload["root_receipts"]))
        self.assertEqual(
            "BF40", root_payload["root_receipts"][0]["precision_tier"]
        )
        self.assertEqual(
            1,
            result.checkpoint["survey_pass_ledger"]["promoted"][leaf_id][
                "root_read_count"
            ],
        )

    def test_adequate_response_queue_waits_for_independent_admission(self):
        result, calls = self._run(self._checkpoint())
        self.assertEqual([40, 40], calls)
        self.assertEqual(0, result.completed_count)
        self.assertEqual(0, result.unresolved_count)
        self.assertEqual(1, result.review_pending_count)
        reuse_receipt = result.checkpoint["promotion_queue"]["entries"][0][
            "provisional_reuse_receipt"
        ]
        self.assertEqual("COMPATIBLE", reuse_receipt["status"])
        self.assertEqual(
            result.checkpoint["promotion_queue"]["entries"][0][
                "provisional_stage_sha256"
            ],
            reuse_receipt["provisional_stage_sha256"],
        )
        self.assertEqual("BF40", reuse_receipt["target_precision_tier"])
        self.assertEqual("CALCULATED_AWAITING_ADMISSION", result.checkpoint[
            "survey_pass_ledger"
        ]["promoted"][self.leaves[0].leaf_id]["disposition"])
        self.assertEqual("AWAITING_ADMISSION", result.checkpoint[
            "promotion_queue"
        ]["entries"][0]["disposition"])
        ledger = result.checkpoint["survey_pass_ledger"]["promoted"][
            self.leaves[0].leaf_id
        ]
        self.assertEqual(0, ledger["root_read_limit"])
        self.assertEqual(2, ledger["worker_launch_count"])
        self.assertEqual(4, ledger["worker_launch_limit"])
        self.assertEqual(["BF40"], [
            item["tier"] for item in ledger["tier_timing"]
        ])
        self.assertTrue(all(
            item["source"] == "direct" for item in ledger["tier_timing"]
        ))
        self.assertEqual(
            ["STARTED", "COMPLETED"],
            [fragment["state"] for fragment in ledger["session_fragments"]],
        )

    def test_awaiting_admission_disposition_is_committed_before_return(self):
        checkpoint = self._checkpoint()
        calls: list[int] = []
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "checkpoint.json"
            result = _strict_run(
                self.plan,
                self.selection,
                checkpoint,
                checkpoint_path=path,
                root_seal_lookup=lambda leaf, entry: AuthenticatedRootSeal(
                    leaf.job.root.omega,
                    leaf.job.root.branch_id,
                    entry["source_root_seal_sha256"],
                ),
                provisional_stage_lookup=lambda _leaf, entry: entry[
                    "provisional_stage"
                ],
                root_seal_publish=lambda *_args: self.fail(
                    "response promotion must not publish a root"
                ),
                backend_factory=lambda leaf, digits: _Backend(
                    leaf, digits, False, calls
                ),
                primary_root_runner=lambda *args: self.fail("unexpected root"),
                horizon_runner=lambda leaf: self.fail("unexpected horizon"),
            )

            durable = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(result.checkpoint, durable)
        self.assertEqual(
            "CALCULATED_AWAITING_ADMISSION",
            durable["survey_pass_ledger"]["promoted"][
                self.leaves[0].leaf_id
            ]["disposition"],
        )

    def test_success_response_cannot_authorize_bf80_without_control_proof(self):
        result, calls = self._run(
            self._checkpoint(), flat40=True, flat80=False
        )
        self.assertEqual([40, 40], calls)
        self.assertEqual(0, result.completed_count)
        self.assertEqual(0, result.unresolved_count)
        self.assertEqual(1, result.review_pending_count)
        tiers = result.checkpoint["survey_pass_ledger"]["promoted"][
            self.leaves[0].leaf_id
        ]["precision_tiers"]
        self.assertEqual(["BF40"], tiers)
        self.assertEqual("AWAITING_ADMISSION", result.checkpoint[
            "promotion_queue"
        ]["entries"][0]["disposition"])
        self.assertNotIn("BF80", str(tiers))

    def test_bf80_control_exhaustion_is_unresolved_not_another_promotion(self):
        result, calls = self._run(
            self._checkpoint(),
            failure40="EXTERIOR_ENDPOINT_ARITHMETIC_INADEQUATE",
            failure80="EXTERIOR_ENDPOINT_ARITHMETIC_INADEQUATE",
        )
        self.assertEqual([40, 80], calls)
        self.assertEqual(1, result.unresolved_count)
        self.assertEqual([], result.checkpoint["records"])
        self.assertEqual("UNRESOLVED", result.checkpoint[
            "promotion_queue"
        ]["entries"][0]["disposition"])
        self.assertNotIn("BF120", str(result.checkpoint))

    def test_allowlisted_bf40_control_failure_advances_only_to_bf80(self):
        result, calls = self._run(
            self._checkpoint(),
            failure40="EXTERIOR_ENDPOINT_ARITHMETIC_INADEQUATE",
        )
        self.assertEqual([40, 80, 80], calls)
        self.assertEqual(0, result.completed_count)
        self.assertEqual(0, result.unresolved_count)
        self.assertEqual(1, result.review_pending_count)

    def test_generic_asymptotic_condition_cannot_authorize_bf80(self):
        result, calls = self._run(
            self._checkpoint(),
            failure40="INSUFFICIENT_ASYMPTOTIC_PRECISION",
        )
        self.assertEqual([40], calls)
        self.assertEqual(1, result.unresolved_count)

    def test_order_and_geometry_exhaustion_remain_at_bf40(self):
        for failure_code in (
            "EXTERIOR_ENDPOINT_MAXIMUM_ORDER_INADEQUATE",
            "EXTERIOR_ENDPOINT_GEOMETRY_EXHAUSTED",
        ):
            with self.subTest(failure_code=failure_code):
                result, calls = self._run(
                    self._checkpoint(), failure40=failure_code
                )
                self.assertEqual([40], calls)
                self.assertEqual(1, result.unresolved_count)
                self.assertEqual("UNRESOLVED", result.checkpoint[
                    "promotion_queue"
                ]["entries"][0]["disposition"])
                self.assertNotIn("BF80", str(result.checkpoint[
                    "survey_pass_ledger"
                ]["promoted"][self.leaves[0].leaf_id]["precision_tiers"]))

    def test_interrupt_after_control_return_resumes_through_durable_decision(self):
        interrupted = self._interrupt_after_control_state(
            PromotionQueueDisposition.CONTROL_RETURN_RETAINED.value
        )
        leaf_id = self.leaves[0].leaf_id
        stage = interrupted["promoted_stage_ledger"]["0"][leaf_id]
        self.assertEqual(
            "windows-solver.promoted-control-return-stage/1", stage["schema"]
        )
        self.assertIn("control_return", stage)
        self.assertNotIn("calculation_artifact", stage)

        resumed, calls = self._run(interrupted)
        self.assertEqual([80, 80], calls)
        self.assertEqual(
            PromotionQueueDisposition.AWAITING_ADMISSION.value,
            resumed.checkpoint["promotion_queue"]["entries"][0]["disposition"],
        )

    def test_interrupt_after_control_decision_resumes_without_decision_loss(self):
        interrupted = self._interrupt_after_control_state(
            PromotionQueueDisposition.CONTROL_DECISION_RETAINED.value
        )
        leaf_id = self.leaves[0].leaf_id
        stage = interrupted["promoted_stage_ledger"]["0"][leaf_id]
        self.assertEqual(
            "windows-solver.promoted-control-decision-stage/1", stage["schema"]
        )
        self.assertIn("control_decision", stage)
        self.assertEqual(
            "windows-solver.promoted-control-return-stage/1",
            stage["calculation_chain"][-1]["schema"],
        )

        resumed, calls = self._run(interrupted)
        self.assertEqual([80, 80], calls)
        self.assertEqual(
            PromotionQueueDisposition.AWAITING_ADMISSION.value,
            resumed.checkpoint["promotion_queue"]["entries"][0]["disposition"],
        )

    def test_retained_decision_round_trips_canonical_transition(self):
        interrupted = self._interrupt_after_control_state(
            PromotionQueueDisposition.CONTROL_DECISION_RETAINED.value
        )
        leaf_id = self.leaves[0].leaf_id
        decision_stage = interrupted["promoted_stage_ledger"]["0"][leaf_id]
        return_stage = decision_stage["calculation_chain"][-1]
        decision = decision_stage["control_decision"]
        with patch(
            "windows_solver.promoted_control_authority."
            "classify_control_receipt_material",
            side_effect=AssertionError("durable replay reclassified raw receipt"),
        ):
            authority = authenticate_persisted_control_decision(
                return_stage["control_return"],
                decision,
                expected_return_schema=return_stage["control_return"]["schema"],
                expected_decision_schema=PROMOTED_CONTROL_DECISION_SCHEMA,
                expected_leaf_id=leaf_id,
                expected_current_action_kind="RESPONSE",
                expected_queue_ordinal=0,
            )
        transition = authority.transition
        self.assertEqual(transition.transition_id, decision["transition_id"])
        self.assertEqual(transition.to_mapping(), decision["transition"])
        self.assertEqual(
            "PROMOTION_PENDING", decision["transition"]["outcome"]["kind"]
        )
        self.assertTrue(decision["transition"]["outcome"]["retryable"])
        self.assertFalse(decision["transition"]["outcome"]["terminal"])
        dashboard = project_schema11_dashboard(
            interrupted,
            selected_leaf_ids=[leaf_id],
            leaf_metadata=None,
        )
        self.assertEqual(1, len(dashboard.control_transition_rows))
        row = dashboard.control_transition_rows[0]
        self.assertEqual(transition.transition_id, row.transition_id)
        self.assertEqual("PROMOTION_PENDING", row.outcome_kind)
        self.assertEqual("BF80", row.next_tier)

        forged = copy.deepcopy(decision)
        forged["transition"]["outcome"]["terminal"] = True
        forged["control_decision_sha256"] = _sha256({
            key: value
            for key, value in forged.items()
            if key != "control_decision_sha256"
        })
        with self.assertRaisesRegex(
            ValueError, "does not match registry authority"
        ):
            authenticate_persisted_control_decision(
                return_stage["control_return"],
                forged,
                expected_return_schema=return_stage["control_return"]["schema"],
                expected_decision_schema=PROMOTED_CONTROL_DECISION_SCHEMA,
                expected_leaf_id=leaf_id,
                expected_current_action_kind="RESPONSE",
                expected_queue_ordinal=0,
            )

    def test_deferred_control_cannot_be_resealed_as_promotion_on_retention(self):
        interrupted = self._interrupt_after_control_state(
            PromotionQueueDisposition.CONTROL_RETURN_RETAINED.value,
            failure_code="ODE_RESOURCE_LIMIT",
        )
        forged_stage = self._forged_bf80_decision_stage(interrupted)

        with self.assertRaisesRegex(
            ValueError,
            "does not match registry authority",
        ):
            retain_promoted_control_decision(
                interrupted,
                queue_ordinal=0,
                promoted_stage=forged_stage,
                execution_mode="CALCULATE_ONLY",
                disposition_receipt={
                    "schema": (
                        "windows-solver.promoted-control-decision-retention/1"
                    ),
                    "queue_ordinal": 0,
                },
            )

    def test_checkpoint_rejects_resealed_deferred_as_bf80_decision_and_proof(
        self,
    ):
        interrupted = self._interrupt_after_control_state(
            PromotionQueueDisposition.CONTROL_RETURN_RETAINED.value,
            failure_code="ODE_RESOURCE_LIMIT",
        )
        leaf_id = self.leaves[0].leaf_id
        decision_stage = self._forged_bf80_decision_stage(interrupted)

        forged_decision = copy.deepcopy(interrupted)
        decision_entry = forged_decision["promotion_queue"]["entries"][0]
        forged_decision["promoted_stage_ledger"]["0"][leaf_id] = decision_stage
        decision_entry["disposition"] = (
            PromotionQueueDisposition.CONTROL_DECISION_RETAINED.value
        )
        decision_entry["retained_promoted_stage_sha256"] = decision_stage[
            "stage_sha256"
        ]
        decision_entry["disposition_receipt_sha256"] = _sha256({
            "schema": "windows-solver.test-forged-control-decision/1",
            "retained_promoted_stage_sha256": decision_stage["stage_sha256"],
        })
        with self.assertRaisesRegex(
            ValueError,
            "does not match registry authority",
        ):
            validate_schema11_checkpoint(forged_decision)

        continuation = self._forged_bf80_continuation_stage(decision_stage)
        forged_proof = copy.deepcopy(interrupted)
        proof_entry = forged_proof["promotion_queue"]["entries"][0]
        forged_proof["promoted_stage_ledger"]["0"][leaf_id] = continuation
        proof_entry["disposition"] = (
            PromotionQueueDisposition.NUMERICAL_CONTINUATION.value
        )
        proof_entry["retained_promoted_stage_sha256"] = continuation[
            "stage_sha256"
        ]
        proof_entry["disposition_receipt_sha256"] = _sha256({
            "schema": "windows-solver.promoted-numerical-continuation/2",
            "queue_ordinal": 0,
            "leaf_id": leaf_id,
            "retained_promoted_stage_sha256": continuation["stage_sha256"],
            "source_fingerprint_sha256": proof_entry[
                "source_fingerprint_sha256"
            ],
        })
        with self.assertRaisesRegex(
            ValueError,
            "does not match registry authority",
        ):
            validate_schema11_checkpoint(forged_proof)

    def test_resealed_control_stage_accounting_cannot_change_reported_work(self):
        checkpoints = [
            self._interrupt_after_control_state(
                PromotionQueueDisposition.CONTROL_RETURN_RETAINED.value
            ),
            self._interrupt_after_control_state(
                PromotionQueueDisposition.CONTROL_DECISION_RETAINED.value
            ),
            self._interrupt_after_control_state(
                PromotionQueueDisposition.NUMERICAL_CONTINUATION.value
            ),
        ]
        terminal, _calls = self._run(
            self._checkpoint(), failure40="ODE_RESOURCE_LIMIT"
        )
        checkpoints.append(terminal.checkpoint)
        leaf_id = self.leaves[0].leaf_id
        mutations = {
            "sample_count": lambda stage: stage.__setitem__(
                "sample_count", stage["sample_count"] + 1
            ),
            "root_read_count": lambda stage: stage.__setitem__(
                "root_read_count", stage["root_read_count"] + 1
            ),
            "worker_launch_count": lambda stage: stage.__setitem__(
                "worker_launch_count", stage["worker_launch_count"] + 1
            ),
            "receipts": lambda stage: stage["receipts"].append(
                {"schema": "windows-solver.forged-receipt/1"}
            ),
            "negative_limit": lambda stage: stage.__setitem__(
                "sample_limit", -1
            ),
            "inflated_limit": lambda stage: stage.__setitem__(
                "worker_launch_limit", 999
            ),
        }
        for checkpoint in checkpoints:
            for label, mutate in mutations.items():
                with self.subTest(
                    state=checkpoint["promotion_queue"]["entries"][0][
                        "disposition"
                    ],
                    mutation=label,
                ):
                    forged = copy.deepcopy(checkpoint)
                    stage = forged["promoted_stage_ledger"]["0"][leaf_id]
                    mutate(stage)
                    self._reseal_current_promoted_stage(forged)
                    with self.assertRaisesRegex(
                        ValueError, "CONTROL stage (accounting|limit)"
                    ):
                        validate_schema11_checkpoint(forged)

    def test_forged_continuation_without_control_proof_fails_closed(self):
        interrupted = self._interrupt_after_control_state(
            PromotionQueueDisposition.NUMERICAL_CONTINUATION.value
        )
        forged = copy.deepcopy(interrupted)
        leaf_id = self.leaves[0].leaf_id
        stage = forged["promoted_stage_ledger"]["0"][leaf_id]
        self.assertEqual(
            "windows-solver.promoted-control-continuation-stage/1",
            stage["schema"],
        )
        stage.pop("control_proof")
        stage["stage_sha256"] = _sha256({
            key: value for key, value in stage.items() if key != "stage_sha256"
        })
        entry = forged["promotion_queue"]["entries"][0]
        entry["retained_promoted_stage_sha256"] = stage["stage_sha256"]
        entry["disposition_receipt_sha256"] = _sha256({
            "schema": "windows-solver.promoted-numerical-continuation/2",
            "queue_ordinal": 0,
            "leaf_id": leaf_id,
            "retained_promoted_stage_sha256": stage["stage_sha256"],
            "source_fingerprint_sha256": entry["source_fingerprint_sha256"],
        })
        with self.assertRaisesRegex(ValueError, "continuation proof"):
            validate_schema11_checkpoint(forged)

    def test_unknown_self_hashed_artifact_schema_fails_closed(self):
        result, _calls = self._run(self._checkpoint())
        forged = copy.deepcopy(result.checkpoint)
        leaf_id = self.leaves[0].leaf_id
        stage = forged["promoted_stage_ledger"]["0"][leaf_id]
        artifact = stage["calculation_artifact"]
        artifact["schema"] = "windows-solver.promoted-exterior-calculatio/3"
        artifact["calculation_sha256"] = _sha256({
            key: value
            for key, value in artifact.items()
            if key != "calculation_sha256"
        })
        stage["stage_sha256"] = _sha256({
            key: value for key, value in stage.items() if key != "stage_sha256"
        })
        forged["promotion_queue"]["entries"][0][
            "retained_promoted_stage_sha256"
        ] = stage["stage_sha256"]
        with self.assertRaisesRegex(ValueError, "schema is unsupported"):
            validate_schema11_checkpoint(forged)

    def test_invented_self_hashed_root_receipt_is_not_success_evidence(self):
        """A digest authenticates bytes; it cannot invent a successful root."""

        from windows_solver.campaign_survey import _validated_promoted_partial_work

        leaf = self.leaves[0]
        dependency = RootDependencyKey.from_leaf(
            leaf, arithmetic_tier="root-promotion"
        )
        invented_authority = {
            "schema": "windows-solver.invented-root-success/1",
            "fixed_root": {
                "real": format(leaf.job.root.omega.real, ".17g"),
                "imaginary": format(leaf.job.root.omega.imag, ".17g"),
            },
            "root_seal_sha256": "b" * 64,
        }
        content = {
            "schema": "windows-solver.promoted-root-evidence-receipt/2",
            "queue_ordinal": 0,
            "leaf_id": leaf.leaf_id,
            "job_id": leaf.job.job_id,
            "precision_tier": "BF40",
            "root_seal_sha256": "b" * 64,
            "branch_identity": leaf.job.root.branch_id,
            "fixed_root": invented_authority["fixed_root"],
            "root_dependency_key": dependency.to_mapping(),
            "root_dependency_key_sha256": dependency.sha256,
            "root_success_authority": invented_authority,
            "root_success_authority_sha256": _sha256(invented_authority),
        }
        receipt = {**content, "receipt_sha256": _sha256(content)}
        with self.assertRaisesRegex(ValueError, "authority schema is unsupported"):
            _validated_promoted_partial_work(
                {
                    "schema": "windows-solver.promoted-partial-work/2",
                    "evidence_receipts": [receipt],
                    "attempt_records": [],
                },
                queue_ordinal=0,
                leaf_id=leaf.leaf_id,
                leaf=leaf,
            )

    def test_root_continuation_requires_authenticated_transition_authority(self):
        from windows_solver.campaign_survey import _continuation_root_seal

        leaf = self.leaves[0]
        with self.assertRaisesRegex(
            ValueError, "lacks mandatory CONTROL proof"
        ):
            _continuation_root_seal(
                {
                    "receipts": [],
                    "calculation_chain": [{
                        "control_decision": {"next_action_kind": "RESPONSE"}
                    }],
                },
                leaf=leaf,
                entry={
                    "queue_kind": PromotionQueueKind.ROOT.value,
                    "queue_ordinal": 0,
                    "leaf_id": leaf.leaf_id,
                },
                fallback_seal=None,
            )

    def test_root_response_continuation_requires_root_success_evidence(self):
        from windows_solver.campaign_survey import _continuation_root_seal

        durable: list[dict[str, object]] = []

        def stop_after_continuation(checkpoint):
            if checkpoint["promotion_queue"]["entries"][0]["disposition"] == (
                PromotionQueueDisposition.NUMERICAL_CONTINUATION.value
            ):
                durable.append(copy.deepcopy(checkpoint))
                raise KeyboardInterrupt
            return checkpoint

        with self.assertRaises(KeyboardInterrupt):
            self._run(
                self._checkpoint(PromotionQueueKind.ROOT),
                failure40="EXTERIOR_ENDPOINT_ARITHMETIC_INADEQUATE",
                checkpoint_committed=stop_after_continuation,
            )
        checkpoint = durable[0]
        leaf = self.leaves[0]
        stage = checkpoint["promoted_stage_ledger"]["0"][leaf.leaf_id]
        stage["receipts"] = [
            receipt
            for receipt in stage["receipts"]
            if receipt.get("schema")
            != "windows-solver.promoted-root-evidence-receipt/2"
        ]
        with self.assertRaisesRegex(
            ValueError, "lacks authenticated root success evidence"
        ):
            _continuation_root_seal(
                stage,
                leaf=leaf,
                entry=checkpoint["promotion_queue"]["entries"][0],
                fallback_seal=None,
            )

    def test_fully_resealed_invented_root_receipt_cannot_authorize_bf80(self):
        """Rehashing every envelope cannot turn invented root bytes into proof."""

        durable: list[dict[str, object]] = []

        def stop_after_continuation(checkpoint):
            if checkpoint["promotion_queue"]["entries"][0]["disposition"] == (
                PromotionQueueDisposition.NUMERICAL_CONTINUATION.value
            ):
                durable.append(copy.deepcopy(checkpoint))
                raise KeyboardInterrupt
            return checkpoint

        with self.assertRaises(KeyboardInterrupt):
            self._run(
                self._checkpoint(PromotionQueueKind.ROOT),
                failure40="EXTERIOR_ENDPOINT_ARITHMETIC_INADEQUATE",
                checkpoint_committed=stop_after_continuation,
            )
        forged = copy.deepcopy(durable[0])
        leaf = self.leaves[0]
        stage = forged["promoted_stage_ledger"]["0"][leaf.leaf_id]
        authentic = next(
            receipt
            for receipt in stage["receipts"]
            if receipt.get("schema")
            == "windows-solver.promoted-root-evidence-receipt/2"
        )
        invented_authority = {
            "schema": "windows-solver.invented-root-success/1",
            "leaf_id": leaf.leaf_id,
            "job_id": leaf.job.job_id,
            "fixed_root": copy.deepcopy(authentic["fixed_root"]),
            "root_seal_sha256": authentic["root_seal_sha256"],
        }
        invented = copy.deepcopy(authentic)
        invented["root_success_authority"] = invented_authority
        invented["root_success_authority_sha256"] = _sha256(invented_authority)
        invented["receipt_sha256"] = _sha256({
            key: value
            for key, value in invented.items()
            if key != "receipt_sha256"
        })

        def replace_receipt(receipts):
            return [
                copy.deepcopy(invented)
                if item.get("schema")
                == "windows-solver.promoted-root-evidence-receipt/2"
                else copy.deepcopy(item)
                for item in receipts
            ]

        def reseal_return(original):
            retained = copy.deepcopy(original)
            retained["receipts"] = replace_receipt(retained["receipts"])
            control_return = retained["control_return"]
            partial = control_return["partial_work"]
            partial["evidence_receipts"] = replace_receipt(
                partial["evidence_receipts"]
            )
            control_return["control_return_sha256"] = _sha256({
                key: value
                for key, value in control_return.items()
                if key != "control_return_sha256"
            })
            retained["stage_sha256"] = _sha256({
                key: value
                for key, value in retained.items()
                if key != "stage_sha256"
            })
            return retained

        original_return, original_decision = stage["calculation_chain"]
        forged_return = reseal_return(original_return)
        forged_decision = copy.deepcopy(original_decision)
        forged_decision["receipts"] = replace_receipt(
            forged_decision["receipts"]
        )
        nested_return = reseal_return(
            forged_decision["calculation_chain"][-1]
        )
        forged_decision["calculation_chain"][-1] = nested_return
        decision = forged_decision["control_decision"]
        decision["control_return_sha256"] = nested_return["control_return"][
            "control_return_sha256"
        ]
        decision["control_decision_sha256"] = _sha256({
            key: value
            for key, value in decision.items()
            if key != "control_decision_sha256"
        })
        forged_decision["source_calculation_stage_sha256"] = nested_return[
            "stage_sha256"
        ]
        forged_decision["stage_sha256"] = _sha256({
            key: value
            for key, value in forged_decision.items()
            if key != "stage_sha256"
        })

        stage["receipts"] = replace_receipt(stage["receipts"])
        stage["calculation_chain"] = [forged_return, forged_decision]
        stage["source_calculation_stage_sha256"] = forged_decision[
            "stage_sha256"
        ]
        proof = stage["control_proof"]
        proof.update({
            "control_return_stage_sha256": forged_return["stage_sha256"],
            "control_return_sha256": forged_return["control_return"][
                "control_return_sha256"
            ],
            "control_decision_stage_sha256": forged_decision["stage_sha256"],
            "control_decision_sha256": decision["control_decision_sha256"],
        })
        proof["proof_sha256"] = _sha256({
            key: value for key, value in proof.items() if key != "proof_sha256"
        })
        stage["stage_sha256"] = _sha256({
            key: value for key, value in stage.items() if key != "stage_sha256"
        })
        entry = forged["promotion_queue"]["entries"][0]
        entry["retained_promoted_stage_sha256"] = stage["stage_sha256"]
        entry["disposition_receipt_sha256"] = _sha256({
            "schema": "windows-solver.promoted-numerical-continuation/2",
            "queue_ordinal": 0,
            "leaf_id": leaf.leaf_id,
            "retained_promoted_stage_sha256": stage["stage_sha256"],
            "source_fingerprint_sha256": entry["source_fingerprint_sha256"],
        })

        backend_calls: list[int] = []

        def backend_factory(_leaf, digits):
            backend_calls.append(digits)
            return _Backend(leaf, digits, False, [])

        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(
                ValueError, "root success authority schema is unsupported"
            ):
                _strict_run(
                    self.plan,
                    self.selection,
                    forged,
                    checkpoint_path=Path(temporary) / "checkpoint.json",
                    root_seal_lookup=lambda *_args: None,
                    root_seal_publish=lambda *_args: self.fail(
                        "forged continuation must not publish a root"
                    ),
                    backend_factory=backend_factory,
                    primary_root_runner=lambda *_args: self.fail(
                        "forged continuation must not run a root solve"
                    ),
                    horizon_runner=lambda _leaf: self.fail("unexpected horizon"),
                )
        self.assertEqual([], backend_calls)

    def test_root_queue_allows_one_primary_then_one_fixed_root_batch(self):
        root_calls: list[int] = []

        def root_runner(leaf, backend, digits):
            root_calls.append(digits)
            return _durable_root_result(leaf, digits)

        result, batch_calls = self._run(
            self._checkpoint(PromotionQueueKind.ROOT),
            root_runner=root_runner,
        )
        self.assertEqual([40], root_calls)
        self.assertEqual([40, 40], batch_calls)
        entry = result.checkpoint["survey_pass_ledger"]["promoted"][
            self.leaves[0].leaf_id
        ]
        self.assertEqual(1, entry["root_read_count"])
        self.assertEqual(3, entry["worker_launch_count"])
        self.assertEqual("CALCULATED_AWAITING_ADMISSION", entry["disposition"])
        retained = result.checkpoint["promoted_stage_ledger"]["0"][
            self.leaves[0].leaf_id
        ]
        root_receipt = next(
            receipt
            for receipt in retained["receipts"]
            if receipt.get("schema")
            == "windows-solver.promoted-root-evidence-receipt/2"
        )
        self.assertEqual(
            "windows-solver.authenticated-root-evidence/3",
            root_receipt["root_success_authority"]["schema"],
        )
        self.assertEqual(
            root_receipt["root_dependency_key_sha256"],
            _sha256(root_receipt["root_dependency_key"]),
        )

    def test_root_control_continuation_retries_root_at_bf80(self):
        root_calls: list[int] = []

        def root_runner(leaf, _backend, digits):
            root_calls.append(digits)
            if digits == 40:
                request = JuliaPrecisionRootBackend(
                    VettedNativeDeterminantKernel.identity,
                    FakeAdapter(),
                    40,
                ).preview_root_request(leaf.job, 0.0j)
                request_sha256 = _sha256(request)
                identity = execution_identity_from_request(
                    request,
                    request_sha256=request_sha256,
                )
                receipt = validate_operation_control_receipt(
                    build_operation_control_receipt(
                        origin=JULIA_WORKER_ORIGIN,
                        failure_code="DETERMINANT_UNCERTAINTY_TOO_LARGE",
                        stage="root-authentication",
                        identity=identity,
                        retryable=True,
                        retryable_basis=JULIA_PRODUCER_RETRYABILITY_BASIS,
                        diagnostics=valid_control_failure_diagnostics(
                            "DETERMINANT_UNCERTAINTY_TOO_LARGE",
                            precision_bits=int(
                                request["working_precision_bits"]
                            ),
                        ),
                    ),
                    request=request,
                    request_sha256=request_sha256,
                )
                raise JuliaNumericalControlError(
                    "BF40 root determinant uncertainty",
                    "DETERMINANT_UNCERTAINTY_TOO_LARGE",
                    control_receipt=receipt,
                )
            return _durable_root_result(leaf, digits)

        result, batch_calls = self._run(
            self._checkpoint(PromotionQueueKind.ROOT),
            root_runner=root_runner,
        )

        self.assertEqual([40, 80], root_calls)
        self.assertEqual([80, 80], batch_calls)
        self.assertEqual(
            PromotionQueueDisposition.AWAITING_ADMISSION.value,
            result.checkpoint["promotion_queue"]["entries"][0]["disposition"],
        )

    def test_exact_root_queue_group_uses_one_primary_root_solve(self):
        """One exact background root is shared by every dependent leaf."""

        root_calls: list[int] = []

        def root_runner(leaf, backend, digits):
            root_calls.append(digits)
            return _durable_root_result(leaf, digits)

        result, batch_calls = self._run(
            self._checkpoint(PromotionQueueKind.ROOT, count=2),
            root_runner=root_runner,
        )

        self.assertEqual([40], root_calls)
        self.assertEqual([40, 40, 40], batch_calls)
        first, second = (
            result.checkpoint["survey_pass_ledger"]["promoted"][leaf.leaf_id]
            for leaf in self.leaves
        )
        self.assertEqual(1, first["root_read_count"])
        self.assertEqual(0, second["root_read_count"])
        self.assertEqual(3, first["worker_launch_count"])
        self.assertEqual(1, second["worker_launch_count"])

    def test_exact_root_queue_group_records_compact_structural_summary(self):
        with tempfile.TemporaryDirectory() as temporary:
            session = StructuralDiagnosticSession.open(
                checkpoint_path=Path(temporary) / "diagnostic-checkpoint.json",
                session_id="root-group-test",
                campaign_id=self.selection.campaign_id,
                selection_id=self.selection.selection_id,
            )
            try:
                result, _ = self._run(
                    self._checkpoint(PromotionQueueKind.ROOT, count=2),
                    diagnostic_session=session,
                )
                events = session.final_events()
            finally:
                session.close_completed()

        group_events = [
            event for event in events
            if event["event_kind"] == "ROOT_PROMOTION_GROUP_FINISHED"
        ]
        self.assertEqual(1, len(group_events))
        event = group_events[0]
        self.assertEqual(self.leaves[0].leaf_id, event["leaf"]["leaf_id"])
        self.assertEqual(
            [leaf.leaf_id for leaf in self.leaves],
            event["compact_diagnostics"]["member_leaf_ids"],
        )
        self.assertEqual(2, event["compact_diagnostics"]["member_leaf_count"])
        self.assertEqual(1, event["compact_diagnostics"]["root_solve_count"])
        self.assertEqual(1, event["compact_diagnostics"]["publication_count"])
        self.assertEqual("RESOLVED", event["compact_diagnostics"]["status"])
        self.assertEqual(
            event["connections"]["root_dependency_key_sha256"],
            _sha256(event["compact_diagnostics"]["root_dependency_key"]),
        )
        self.assertEqual([], result.checkpoint["system_failures"])

    def test_distinct_root_dependency_keys_do_not_share_primary_work(self):
        first = self.leaves[0]
        incompatible = next(
            leaf for leaf in self.plan.leaves
            if leaf.role == first.role
            and leaf.mechanism_id != "horizon-admittance"
            and leaf.leaf.mode != first.leaf.mode
        )
        selected = build_campaign_selection(
            self.plan,
            role=first.role,
            leaf_ids=(first.leaf_id, incompatible.leaf_id),
        )
        selection = RecoverySelection(
            campaign_id=self.plan.campaign_id,
            selection_id=selected.selection_id,
            ordered_leaf_ids=tuple(selected.leaf_ids),
            roles={leaf.leaf_id: leaf.role for leaf in (first, incompatible)},
            scientific_identities={
                leaf.leaf_id: scientific_computation_identity_sha256(self.plan, leaf)
                for leaf in (first, incompatible)
            },
        )
        checkpoint = empty_schema11_checkpoint(
            selection.campaign_id, selection.selection_id
        )
        for leaf in (first, incompatible):
            checkpoint = append_promotion(
                checkpoint,
                leaf_id=leaf.leaf_id,
                queue_kind=PromotionQueueKind.ROOT,
                reason_code="DETERMINANT_UNCERTAINTY_TOO_LARGE",
                minimum_requested_tier="BF40",
                scientific_computation_identity=selection.scientific_identities[
                    leaf.leaf_id
                ],
            )

        root_calls: list[tuple[str, int]] = []
        batch_calls: list[tuple[str, int]] = []
        published: dict[str, AuthenticatedRootSeal] = {}

        def root_runner(leaf, _backend, digits):
            root_calls.append((leaf.leaf_id, digits))
            return _durable_root_result(leaf, digits)

        class Backend(_Backend):
            def fixed_root_survey_batch(self, job, **kwargs):
                batch_calls.append((self.leaf.leaf_id, self.digits))
                return super().fixed_root_survey_batch(job, **kwargs)

        with tempfile.TemporaryDirectory() as temporary:
            result = _strict_run(
                self.plan,
                selection,
                checkpoint,
                checkpoint_path=Path(temporary) / "checkpoint.json",
                root_seal_lookup=lambda leaf, _entry: published.get(leaf.leaf_id),
                provisional_stage_lookup=lambda _leaf, entry: entry[
                    "provisional_stage"
                ],
                root_seal_publish=lambda leaf, seal: published.__setitem__(
                    leaf.leaf_id, seal
                ),
                backend_factory=lambda leaf, digits: Backend(
                    leaf, digits, False, [], None
                ),
                primary_root_runner=root_runner,
                horizon_runner=lambda _leaf: self.fail("unexpected horizon"),
            )

        self.assertEqual(
            [(first.leaf_id, 40), (incompatible.leaf_id, 40)], root_calls
        )
        self.assertEqual(
            [
                (first.leaf_id, 40),
                (first.leaf_id, 40),
                (incompatible.leaf_id, 40),
                (incompatible.leaf_id, 40),
            ],
            batch_calls,
        )
        for leaf in (first, incompatible):
            self.assertEqual(
                1,
                result.checkpoint["survey_pass_ledger"]["promoted"][leaf.leaf_id][
                    "root_read_count"
                ],
            )

    def test_static_guard_root_groups_require_publication_and_exact_key(self):
        source_root = Path(__file__).parents[1] / "src" / "windows_solver"
        survey_source = (source_root / "campaign_survey.py").read_text(
            encoding="utf-8"
        )
        runtime_source = (source_root / "campaign_runtime.py").read_text(
            encoding="utf-8"
        )

        self.assertIn("root_promotion_groups", survey_source)
        self.assertIn("_ROOT_PROMOTION_ARITHMETIC_TIER", survey_source)
        self.assertIn("ROOT_PROMOTION_GROUP_FINISHED", survey_source)
        self.assertNotIn("else lambda _leaf, _seal: None", survey_source)
        self.assertIn("source.leaf.mode == target.leaf.mode", runtime_source)
        self.assertIn("source.job.spin == target.job.spin", runtime_source)

    def test_static_guards_require_authenticated_exterior_provisional_stage(self):
        """The production adapter must not silently drop a RESPONSE precursor."""

        source_root = Path(__file__).parents[1] / "src" / "windows_solver"
        survey_source = (source_root / "campaign_survey.py").read_text(
            encoding="utf-8"
        )
        runtime_source = (source_root / "campaign_runtime.py").read_text(
            encoding="utf-8"
        )
        wiring_source = (source_root / "production_wiring.py").read_text(
            encoding="utf-8"
        )

        self.assertIn(
            "exterior RESPONSE promotion lacks a provisional stage", survey_source
        )
        self.assertIn(
            "consume_authenticated_binary64_provisional_predecessor", survey_source
        )
        self.assertIn("PROVISIONAL_STAGE_PUBLISHED", runtime_source)
        self.assertNotIn(
            "provisional_stage_lookup", runtime_source
        )
        self.assertIn('"layer1_guard"', wiring_source)
        self.assertIn('"locked_routes_by_ordinal"', wiring_source)
        self.assertIn('"provisional_stage_committed"', wiring_source)
        self.assertIn('"terminal_record_committed"', wiring_source)
        self.assertIn('"diagnostic_session"', wiring_source)

    def test_unexpected_error_is_durable_and_stops_before_next_queue_entry(self):
        started: list[str] = []

        def broken_factory(leaf, digits):
            started.append(leaf.leaf_id)
            raise TypeError("unexpected software error")

        checkpoint = self._checkpoint(count=2)
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "checkpoint.json"
            with self.assertRaises(CampaignSystemFailure):
                _strict_run(
                    self.plan,
                    self.selection,
                    checkpoint,
                    checkpoint_path=path,
                    root_seal_lookup=lambda leaf, entry: AuthenticatedRootSeal(
                        leaf.job.root.omega,
                        leaf.job.root.branch_id,
                        entry["source_root_seal_sha256"],
                    ),
                    provisional_stage_lookup=lambda _leaf, entry: entry[
                        "provisional_stage"
                    ],
                    root_seal_publish=lambda *_args: self.fail(
                        "response promotion must not publish a root"
                    ),
                    backend_factory=broken_factory,
                    primary_root_runner=lambda *args: self.fail("unexpected root"),
                    horizon_runner=lambda leaf: self.fail("unexpected horizon"),
                )
            self.assertEqual([self.leaves[0].leaf_id], started)
            self.assertTrue(path.is_file())
            timing = CampaignTimingLog(
                path.with_name(f"{path.name}.timing.jsonl")
            ).read()
            self.assertEqual("INTERRUPTED", timing[-1].state)


if __name__ == "__main__":
    unittest.main()
