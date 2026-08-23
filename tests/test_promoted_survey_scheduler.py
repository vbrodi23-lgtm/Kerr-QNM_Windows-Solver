from __future__ import annotations

from decimal import Decimal
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from windows_solver.campaign_failures import CampaignSystemFailure
from windows_solver.campaign_policy import (
    PromotionQueueKind,
    append_promotion,
    empty_schema11_checkpoint,
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
from windows_solver.response_batches import (
    PrecisionCapabilities,
    build_campaign_plan,
    build_campaign_selection,
    scientific_computation_identity_sha256,
)
from windows_solver.response_engine import (
    BINARY64_FIXED_ROOT_SAMPLE_ROLES,
    DecimalComplex,
    NumericalPolicy,
    VettedNativeDeterminantKernel,
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
                scientific_computation_identity=(
                    self.selection.scientific_identities[leaf.leaf_id]
                ),
                source_root_seal_sha256=(
                    "a" * 64 if kind is PromotionQueueKind.RESPONSE else None
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
        root_runner=None,
    ):
        calls: list[int] = []
        with tempfile.TemporaryDirectory() as temporary:
            result = run_promoted_survey(
                self.plan,
                self.selection,
                checkpoint,
                checkpoint_path=Path(temporary) / "checkpoint.json",
                root_seal_lookup=lambda leaf, entry: AuthenticatedRootSeal(
                    leaf.job.root.omega,
                    leaf.job.root.branch_id,
                    entry["source_root_seal_sha256"],
                ),
                backend_factory=lambda leaf, digits: _Backend(
                    leaf, digits,
                    flat40 if digits == 40 else flat80,
                    calls,
                    failure40 if digits == 40 else None,
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
            )
        return result, calls

    def test_response_queue_completes_at_bf40_with_one_worker_request(self):
        result, calls = self._run(self._checkpoint())
        self.assertEqual([40], calls)
        self.assertEqual(1, result.completed_count)
        self.assertEqual("COMPLETED", result.checkpoint[
            "survey_pass_ledger"
        ]["promoted"][self.leaves[0].leaf_id]["disposition"])
        self.assertEqual("COMPLETED", result.checkpoint[
            "promotion_queue"
        ]["entries"][0]["disposition"])
        ledger = result.checkpoint["survey_pass_ledger"]["promoted"][
            self.leaves[0].leaf_id
        ]
        self.assertEqual(0, ledger["root_read_limit"])
        self.assertEqual(2, ledger["worker_launch_limit"])
        self.assertEqual("BF40", ledger["tier_timing"][0]["tier"])
        self.assertEqual("direct", ledger["tier_timing"][0]["source"])
        self.assertEqual(
            ["STARTED", "COMPLETED"],
            [fragment["state"] for fragment in ledger["session_fragments"]],
        )

    def test_completed_disposition_is_committed_before_return(self):
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
            "COMPLETED",
            durable["survey_pass_ledger"]["promoted"][
                self.leaves[0].leaf_id
            ]["disposition"],
        )

    def test_response_queue_escalates_once_to_bf80_then_stops(self):
        result, calls = self._run(
            self._checkpoint(), flat40=True, flat80=False
        )
        self.assertEqual([40, 80], calls)
        self.assertEqual(1, result.completed_count)
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
        self.assertEqual(1, result.completed_count)
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
        self.assertEqual([40], batch_calls)
        entry = result.checkpoint["survey_pass_ledger"]["promoted"][
            self.leaves[0].leaf_id
        ]
        self.assertEqual(1, entry["root_read_count"])
        self.assertEqual(2, entry["worker_launch_count"])

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
