from __future__ import annotations

import copy
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from windows_solver.campaign_failures import CampaignSystemFailure
from windows_solver.campaign_policy import (
    PromotionQueueKind,
    SurveyDisposition,
    SurveyPass,
    append_promotion,
    empty_schema11_checkpoint,
    record_survey_disposition,
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
    JuliaFixedRootSurveyBatch,
    JuliaFixedRootSurveySample,
    JuliaNumericalControlError,
)
from windows_solver.precision_tiers import PrecisionTier
from windows_solver.reviewed_determinant_error_issuance import (
    PromotedExecutionPreflight,
    require_locked_bf40_determinant_error_issuance_authority,
)
from windows_solver.promoted_control_calibration import PromotedExecutionMode
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


def _sha256(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _record(leaf_id: str, digits: int):
    stage_content = {
        "schema": "windows-solver.test-promoted-stage/1",
        "digits": digits,
    }
    stage = {**stage_content, "stage_sha256": _sha256(stage_content)}
    content = {"leaf_id": leaf_id, "state": "PRODUCED", "stages": [stage]}
    return {**content, "record_sha256": _sha256(content)}, stage["stage_sha256"]


def _conditioning(digits: int) -> FixedRootSurveyConditioning:
    return FixedRootSurveyConditioning({
        "schema": "windows-solver.fixed-root-survey-conditioning/1",
        "determinant_family": "exterior-wronskian/v1",
        "homogeneous_representation": "factored-plane-wave-gsn/v1",
        "branch_convention": "gsn-complex-rho/v1",
        "determinant_convention": "wronskian-perturbed-Xin-with-Xup/v1",
        "determinant_normalisation": "unit-asymptotic-branch-wronskian/v1",
        "maximum_series_digits_lost": "1",
        "maximum_recurrence_digits_lost": "1",
        "minimum_asymptotic_predicted_reliable_digits": str(digits - 5),
        "endpoint_remainders_regular": True,
        "maximum_endpoint_reconstruction_error": f"1e-{digits - 5}",
        "maximum_contour_angle_deformation": "0",
        "predicted_reliable_digits": str(digits - 6),
        "required_reliable_digits": "20",
        "precision_limited": False,
        "determinant_count": 1,
    })


def _batch(leaf, seal: AuthenticatedRootSeal, digits: int, *, flat=False):
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
    samples = []
    for role, (omega, amplitude) in zip(BINARY64_FIXED_ROOT_SAMPLE_ROLES, points):
        frequency = 0.0 if flat else 3.0 * (omega.real - root.real)
        determinant = DecimalComplex(
            Decimal(str(frequency + 2.0 * amplitude)), Decimal(0)
        )
        samples.append(JuliaFixedRootSurveySample(
            role,
            complex(omega),
            complex(amplitude),
            determinant,
            _conditioning(digits),
        ))
    return JuliaFixedRootSurveyBatch(
        leaf_id=leaf.leaf_id,
        job_id=leaf.job.job_id,
        mechanism_id=leaf.mechanism_id,
        root_reference_id=leaf.job.root.root_reference_id,
        root_seal_sha256=seal.root_seal_sha256,
        branch_identity=seal.branch_identity,
        fixed_root=root,
        frequency_step=Decimal(str(h)),
        coordinate_step=Decimal(str(epsilon)),
        scientific_operation_identity="exterior-fixed-root-survey-raw/v1",
        request_sha256=str(digits // 40) * 64,
        precision_tier=(
            PrecisionTier.BIGFLOAT_40
            if digits == 40 else PrecisionTier.BIGFLOAT_80
        ),
        working_precision_bits=digits * 4,
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

    def fixed_root_survey_batch(self, job, **kwargs):
        self.calls.append(self.digits)
        if self.failure_code is not None:
            raise JuliaNumericalControlError(
                "reviewed numerical insufficiency", self.failure_code
            )
        seal = AuthenticatedRootSeal(
            kwargs["fixed_root"], kwargs["branch_identity"],
            kwargs["root_seal_sha256"],
        )
        return _batch(self.leaf, seal, self.digits, flat=self.flat)


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
        terminal_commits=None,
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
            result = run_promoted_survey(
                self.plan,
                self.selection,
                checkpoint,
                checkpoint_path=Path(temporary) / "checkpoint.json",
                root_seal_lookup=root_seal_lookup,
                provisional_stage_lookup=lambda _leaf, entry: entry[
                    "provisional_stage"
                ],
                root_seal_publish=lambda leaf, seal: published.__setitem__(
                    leaf.leaf_id, seal
                ),
                backend_factory=lambda leaf, digits: _Backend(
                    leaf, digits,
                    flat40 if digits == 40 else flat80,
                    calls,
                    failure40 if digits == 40 else failure80,
                ),
                primary_root_runner=(
                    root_runner
                    if root_runner is not None
                    else lambda leaf, backend, digits: PromotedRootSolveResult(
                        AuthenticatedRootSeal(
                            leaf.job.root.omega,
                            leaf.job.root.branch_id,
                            str(digits // 40) * 64,
                        ),
                        precision_tier=f"BF{digits}",
                    )
                ),
                horizon_runner=lambda leaf: self.fail("unexpected horizon"),
                produced_record_builder=lambda leaf, batch, screening, digits: (
                    _record(leaf.leaf_id, digits)
                ),
                promoted_preflights_by_ordinal=(
                    {
                        ordinal: (
                            PromotedExecutionPreflight(
                                mode=PromotedExecutionMode.BLOCK_ALL,
                                route="EXTERIOR_BF40",
                                calibration_receipt_sha256="e" * 64,
                                calculation_permitted=False,
                                checkpointing_permitted=False,
                                admission_permitted=False,
                                publication_permitted=False,
                                result_code="BLOCKED_BY_ADMISSION_POLICY",
                            )
                            if block_all
                            else require_locked_bf40_determinant_error_issuance_authority(
                                route="EXTERIOR_BF40"
                            )
                        )
                        for ordinal in range(
                            len(checkpoint["promotion_queue"]["entries"])
                        )
                    }
                    if calculate_only or block_all
                    else None
                ),
                layer1_lock_receipt_sha256=(
                    "f" * 64 if calculate_only or block_all else None
                ),
                terminal_record_committed=(
                    None
                    if terminal_commits is None
                    else lambda leaf, record: terminal_commits.append(
                        (leaf.leaf_id, record["record_sha256"])
                    )
                ),
                diagnostic_session=diagnostic_session,
            )
        return result, calls

    def test_calculate_only_stops_at_bf40_and_retains_without_admission(self):
        terminal_commits: list[tuple[str, str]] = []
        first, calls = self._run(
            self._checkpoint(),
            calculate_only=True,
            terminal_commits=terminal_commits,
        )

        leaf_id = self.leaves[0].leaf_id
        queue_entry = first.checkpoint["promotion_queue"]["entries"][0]
        stage = first.checkpoint["promoted_stage_ledger"]["0"][leaf_id]
        self.assertEqual([40], calls)
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
        self.assertEqual(["bigfloat-40"], [
            batch["precision_tier"] for batch in stage["raw_promoted_batches"]
        ])
        self.assertEqual([], first.checkpoint["records"])
        self.assertEqual({}, first.checkpoint["evidence_ledger"])
        self.assertEqual([], terminal_commits)
        self.assertEqual(1, first.review_pending_count)

        resumed, resumed_calls = self._run(
            first.checkpoint,
            calculate_only=True,
            terminal_commits=terminal_commits,
        )
        self.assertEqual([], resumed_calls)
        self.assertEqual(
            stage,
            resumed.checkpoint["promoted_stage_ledger"]["0"][leaf_id],
        )
        self.assertEqual([], terminal_commits)

    def test_block_all_returns_typed_policy_result_without_backend_work(self):
        result, calls = self._run(self._checkpoint(), block_all=True)

        self.assertEqual([], calls)
        self.assertEqual(1, result.policy_blocked_count)
        self.assertEqual("DEFERRED", result.checkpoint[
            "promotion_queue"
        ]["entries"][0]["disposition"])
        self.assertEqual(1, len(result.route_results))
        self.assertEqual(
            "BLOCKED_BY_ADMISSION_POLICY",
            result.route_results[0].result_code,
        )
        self.assertFalse(result.route_results[0].numerical_work_performed)

    def test_calculate_only_reuses_same_tier_promoted_background(self):
        result, calls = self._run(
            self._checkpoint(count=2),
            calculate_only=True,
        )

        self.assertEqual([40, 40], calls)
        background_entries = result.checkpoint["promoted_background_ledger"]
        receipts = [
            background_entries[str(ordinal)][leaf.leaf_id]["payload"][
                "background_receipts"
            ][0]
            for ordinal, leaf in enumerate(self.leaves)
        ]
        self.assertEqual(["ACQUIRED", "REUSED"], [
            receipt["status"] for receipt in receipts
        ])
        self.assertEqual(
            receipts[0]["background_sha256"],
            receipts[1]["background_sha256"],
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
            failure40="INSUFFICIENT_ASYMPTOTIC_PRECISION",
            failure80="INSUFFICIENT_ASYMPTOTIC_PRECISION",
        )

        leaf_id = self.leaves[0].leaf_id
        queue_entry = result.checkpoint["promotion_queue"]["entries"][0]
        retained = result.checkpoint["promoted_stage_ledger"]["0"][leaf_id]
        self.assertEqual([40, 80], calls)
        self.assertEqual("AWAITING_ADMISSION", queue_entry["disposition"])
        self.assertEqual(
            "CALCULATED_AWAITING_ADMISSION",
            result.checkpoint["survey_pass_ledger"]["promoted"][leaf_id][
                "disposition"
            ],
        )
        self.assertEqual(
            "INSUFFICIENT_ASYMPTOTIC_PRECISION", retained["reason_code"]
        )
        self.assertEqual(["BF40", "BF80"], retained["precision_tiers"])
        self.assertEqual({}, result.checkpoint["evidence_ledger"])
        self.assertEqual([], result.checkpoint["records"])

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

        second = self.leaves[1]
        receipt = resumed.checkpoint["promoted_background_ledger"]["1"][
            second.leaf_id
        ]["payload"]["background_receipts"][0]
        self.assertEqual([40], calls)
        self.assertEqual("REUSED", receipt["status"])
        self.assertEqual(
            4,
            resumed.checkpoint["survey_pass_ledger"]["promoted"][
                second.leaf_id
            ]["sample_count"],
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
        self.assertEqual([40], calls)
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

    def test_response_queue_stops_unresolved_without_approved_error_model(self):
        result, calls = self._run(self._checkpoint())
        self.assertEqual([40, 80], calls)
        self.assertEqual(0, result.completed_count)
        self.assertEqual(1, result.unresolved_count)
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
        self.assertEqual("UNRESOLVED", result.checkpoint[
            "survey_pass_ledger"
        ]["promoted"][self.leaves[0].leaf_id]["disposition"])
        self.assertEqual("UNRESOLVED", result.checkpoint[
            "promotion_queue"
        ]["entries"][0]["disposition"])
        ledger = result.checkpoint["survey_pass_ledger"]["promoted"][
            self.leaves[0].leaf_id
        ]
        self.assertEqual(0, ledger["root_read_limit"])
        self.assertEqual(2, ledger["worker_launch_limit"])
        self.assertEqual(["BF40", "BF80"], [
            item["tier"] for item in ledger["tier_timing"]
        ])
        self.assertTrue(all(
            item["source"] == "direct" for item in ledger["tier_timing"]
        ))
        self.assertEqual(
            ["STARTED", "COMPLETED", "STARTED", "COMPLETED"],
            [fragment["state"] for fragment in ledger["session_fragments"]],
        )

    def test_unresolved_disposition_is_committed_before_return(self):
        checkpoint = self._checkpoint()
        calls: list[int] = []
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "checkpoint.json"
            result = run_promoted_survey(
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
                produced_record_builder=lambda leaf, batch, screening, digits: (
                    _record(leaf.leaf_id, digits)
                ),
            )

            durable = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(result.checkpoint, durable)
        self.assertEqual(
            "UNRESOLVED",
            durable["survey_pass_ledger"]["promoted"][
                self.leaves[0].leaf_id
            ]["disposition"],
        )

    def test_response_queue_escalates_once_to_bf80_then_stops(self):
        result, calls = self._run(
            self._checkpoint(), flat40=True, flat80=False
        )
        self.assertEqual([40, 80], calls)
        self.assertEqual(0, result.completed_count)
        self.assertEqual(1, result.unresolved_count)
        tiers = result.checkpoint["survey_pass_ledger"]["promoted"][
            self.leaves[0].leaf_id
        ]["precision_tiers"]
        self.assertEqual(["BF40", "BF80"], tiers)
        self.assertNotIn("BF120", str(result.checkpoint))

    def test_bf80_exhaustion_is_unresolved_not_another_promotion(self):
        result, calls = self._run(
            self._checkpoint(), flat40=True, flat80=True
        )
        self.assertEqual([40, 80], calls)
        self.assertEqual(1, result.unresolved_count)
        self.assertEqual([], result.checkpoint["records"])
        self.assertEqual("UNRESOLVED", result.checkpoint[
            "promotion_queue"
        ]["entries"][0]["disposition"])

    def test_allowlisted_bf40_control_failure_advances_only_to_bf80(self):
        result, calls = self._run(
            self._checkpoint(),
            failure40="INSUFFICIENT_ASYMPTOTIC_PRECISION",
        )
        self.assertEqual([40, 80], calls)
        self.assertEqual(0, result.completed_count)
        self.assertEqual(1, result.unresolved_count)
        self.assertNotIn("BF120", str(result.checkpoint))

    def test_root_queue_allows_one_primary_then_one_fixed_root_batch(self):
        root_calls: list[int] = []

        def root_runner(leaf, backend, digits):
            root_calls.append(digits)
            return PromotedRootSolveResult(
                AuthenticatedRootSeal(
                    leaf.job.root.omega, leaf.job.root.branch_id, "b" * 64
                ),
                precision_tier=f"BF{digits}",
            )

        result, batch_calls = self._run(
            self._checkpoint(PromotionQueueKind.ROOT),
            root_runner=root_runner,
        )
        self.assertEqual([40], root_calls)
        self.assertEqual([40, 80], batch_calls)
        entry = result.checkpoint["survey_pass_ledger"]["promoted"][
            self.leaves[0].leaf_id
        ]
        self.assertEqual(1, entry["root_read_count"])
        self.assertEqual(3, entry["worker_launch_count"])
        self.assertEqual("UNRESOLVED", entry["disposition"])

    def test_exact_root_queue_group_uses_one_primary_root_solve(self):
        """One exact background root is shared by every dependent leaf."""

        root_calls: list[int] = []

        def root_runner(leaf, backend, digits):
            root_calls.append(digits)
            return PromotedRootSolveResult(
                AuthenticatedRootSeal(
                    leaf.job.root.omega, leaf.job.root.branch_id, "c" * 64
                ),
                precision_tier=f"BF{digits}",
            )

        result, batch_calls = self._run(
            self._checkpoint(PromotionQueueKind.ROOT, count=2),
            root_runner=root_runner,
        )

        self.assertEqual([40], root_calls)
        self.assertEqual([40, 80, 40, 80], batch_calls)
        first, second = (
            result.checkpoint["survey_pass_ledger"]["promoted"][leaf.leaf_id]
            for leaf in self.leaves
        )
        self.assertEqual(1, first["root_read_count"])
        self.assertEqual(0, second["root_read_count"])
        self.assertEqual(3, first["worker_launch_count"])
        self.assertEqual(2, second["worker_launch_count"])

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
            return PromotedRootSolveResult(
                AuthenticatedRootSeal(
                    leaf.job.root.omega, leaf.job.root.branch_id, "d" * 64
                ),
                precision_tier=f"BF{digits}",
            )

        class Backend(_Backend):
            def fixed_root_survey_batch(self, job, **kwargs):
                batch_calls.append((self.leaf.leaf_id, self.digits))
                return super().fixed_root_survey_batch(job, **kwargs)

        with tempfile.TemporaryDirectory() as temporary:
            result = run_promoted_survey(
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
                produced_record_builder=lambda leaf, batch, screening, digits: (
                    _record(leaf.leaf_id, digits)
                ),
            )

        self.assertEqual(
            [(first.leaf_id, 40), (incompatible.leaf_id, 40)], root_calls
        )
        self.assertEqual(
            [
                (first.leaf_id, 40),
                (first.leaf_id, 80),
                (incompatible.leaf_id, 40),
                (incompatible.leaf_id, 80),
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
                run_promoted_survey(
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
                    produced_record_builder=lambda *args: self.fail(
                        "unexpected record"
                    ),
                )
            self.assertEqual([self.leaves[0].leaf_id], started)
            self.assertTrue(path.is_file())
            timing = CampaignTimingLog(
                path.with_name(f"{path.name}.timing.jsonl")
            ).read()
            self.assertEqual("INTERRUPTED", timing[-1].state)


if __name__ == "__main__":
    unittest.main()
