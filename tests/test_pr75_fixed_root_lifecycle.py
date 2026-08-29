from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest

from tests.pr75_fixed_root_contract_fixture import (
    CapturedJuliaAdapter,
    ROOT_SEAL_SHA256,
    _backend,
    parsed_case_batch,
    parsed_result_batch,
    verify_case_matrix,
)
from tests.test_promoted_survey_scheduler import (
    _TestLayer1Guard,
    _locked_routes,
    _provisional_stage,
    _strict_run,
)
from windows_solver.campaign_policy import (
    PromotionQueueKind,
    SurveyDisposition,
    SurveyPass,
    append_promotion,
    empty_schema11_checkpoint,
    record_survey_disposition,
)
from windows_solver.campaign_recovery import RecoverySelection
from windows_solver.campaign_survey import AuthenticatedRootSeal
from windows_solver.julia_response_backend import FixedRootSurveyPlan
from windows_solver.reviewed_determinant_error_issuance import (
    require_locked_bf40_determinant_error_issuance_authority,
)
from windows_solver.response_batches import (
    PrecisionCapabilities,
    build_campaign_plan,
    build_campaign_selection,
    scientific_computation_identity_sha256,
)
from windows_solver.response_engine import (
    NumericalPolicy,
    VettedNativeDeterminantKernel,
)


class _MatrixBackend:
    def __init__(
        self,
        digits: int,
        cases: dict[str, object],
        results: dict[str, object],
        calls: list[tuple[int, str]],
        *,
        fail_bf40_component: bool,
        interrupt_bf80: bool,
    ) -> None:
        self.digits = digits
        self.cases = cases
        self.results = results
        self.calls = calls
        self.fail_bf40_component = fail_bf40_component
        self.interrupt_bf80 = interrupt_bf80

    def _captured_backend(self, plan: FixedRootSurveyPlan):
        prefix = "success"
        suffix = ""
        if (
            self.digits == 40
            and plan is FixedRootSurveyPlan.MECHANISM_COMPONENT_FOUR
            and self.fail_bf40_component
        ):
            prefix = "failure"
            suffix = ":0"
        case_id = f"{prefix}:{self.digits}:{plan.value}{suffix}"
        case = self.cases[case_id]
        response = self.results[case_id]["response"]
        return _backend(CapturedJuliaAdapter(case, response), self.digits)

    def prepare_fixed_root_survey_request(self, job, **kwargs):
        plan = FixedRootSurveyPlan(kwargs["plan"])
        return self._captured_backend(plan).prepare_fixed_root_survey_request(
            job, **kwargs
        )

    def fixed_root_survey_batch(self, job, **kwargs):
        plan = FixedRootSurveyPlan(kwargs["plan"])
        self.calls.append((self.digits, plan.value))
        if self.digits == 80 and self.interrupt_bf80:
            raise KeyboardInterrupt
        backend = self._captured_backend(plan)
        return backend.fixed_root_survey_batch(job, **kwargs)


def _one_leaf_campaign():
    plan = build_campaign_plan(
        policy=NumericalPolicy(),
        backend_identity=VettedNativeDeterminantKernel.identity,
        precision_capabilities=PrecisionCapabilities((64, 80)),
    )
    leaf = next(
        item for item in plan.leaves
        if item.job.mechanism_id == "exterior-light-ring"
    )
    selected = build_campaign_selection(
        plan, role="primary", leaf_ids=(leaf.leaf_id,)
    )
    selection = RecoverySelection(
        campaign_id=plan.campaign_id,
        selection_id=selected.selection_id,
        ordered_leaf_ids=(leaf.leaf_id,),
        roles={leaf.leaf_id: leaf.role},
        scientific_identities={
            leaf.leaf_id: scientific_computation_identity_sha256(plan, leaf)
        },
    )
    checkpoint = empty_schema11_checkpoint(
        selection.campaign_id, selection.selection_id
    )
    scientific_identity = selection.scientific_identities[leaf.leaf_id]
    provisional, provisional_sha256 = _provisional_stage(
        leaf, scientific_identity, ROOT_SEAL_SHA256
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
    disposition_receipt = checkpoint["survey_pass_ledger"]["binary64"][
        leaf.leaf_id
    ]["disposition_receipt_sha256"]
    checkpoint = append_promotion(
        checkpoint,
        leaf_id=leaf.leaf_id,
        queue_kind=PromotionQueueKind.RESPONSE,
        reason_code="FINITE_DIFFERENCE_NOISE_LIMIT",
        minimum_requested_tier="BF40",
        scientific_computation_identity=scientific_identity,
        source_root_seal_sha256=ROOT_SEAL_SHA256,
        source_stage_sha256=provisional_sha256,
        provisional_stage=provisional,
        provisional_stage_sha256=provisional_sha256,
        provisional_operation_identity=str(provisional["operation_identity"]),
        source_binary64_disposition_receipt_sha256=disposition_receipt,
    )
    return plan, leaf, selection, checkpoint


class PR75FixedRootLifecycleTests(unittest.TestCase):
    def test_deterministic_evaluator_is_not_wire_or_dispatch_selectable(self):
        root = Path(__file__).resolve().parents[1]
        worker = (
            root / "src/windows_solver/data/julia/m02_worker.jl"
        ).read_text(encoding="utf-8")
        cli = (root / "src/windows_solver/cli.py").read_text(encoding="utf-8")
        main_call = (
            "fixed_root_survey_batch_fields(\n"
            "                    request, digits, bits, roles, samples\n"
            "                )"
        )
        self.assertIn(main_call, worker)
        self.assertIn("exit(main())", worker)
        self.assertIn("function main()", worker)
        self.assertNotIn("function main(;", worker)
        self.assertNotIn("_fixed_root_survey_sample_evaluator", worker)
        self.assertNotIn("deterministic_success_sample", worker)
        self.assertNotIn("deterministic_insufficient_precision", worker)
        self.assertNotIn("PR75_FIXED_ROOT", worker)
        self.assertNotIn("PR75_REAL_WORKER_PROCESS", worker)
        self.assertNotIn("pr75_fixed_root_process_worker", worker)
        self.assertNotIn("PR75_REAL_WORKER_PROCESS", cli)
        self.assertNotIn("pr75_fixed_root_process_worker", cli)
        self.assertNotIn("sample_evaluator", cli)

        main_source = worker.split("function main()", 1)[1]
        self.assertIn("try\n        document = JSON.parsefile(request_path)", main_source)
        self.assertLess(
            main_source.index("validate_fixed_root_survey_request(request)"),
            main_source.index('progress_emit("request_validated"'),
        )
        self.assertEqual(
            main_source.count(
                "operation_control_receipt(request, failure_details(failure))"
            ),
            1,
        )
        self.assertNotIn('request_failure["failure"]', main_source)
        self.assertIn('"control_receipt_sha256"', main_source)

    @unittest.skipUnless(
        os.environ.get("PR75_FIXED_ROOT_CASES")
        and os.environ.get("PR75_FIXED_ROOT_RESULTS"),
        "hosted real-Julia PR75 matrix is not attached",
    )
    def test_real_julia_control_checkpoint_reload_bf80_success_and_reduction(self):
        case_batch = parsed_case_batch(Path(os.environ["PR75_FIXED_ROOT_CASES"]))
        result_batch = parsed_result_batch(
            Path(os.environ["PR75_FIXED_ROOT_RESULTS"])
        )
        self.assertEqual(
            verify_case_matrix(case_batch, result_batch),
            {
                "success_count": 6,
                "failure_count": 36,
                "reliability_negative_count": 14,
                "compatibility_success_count": 2,
                "compatibility_control_count": 2,
            },
        )
        cases = {item["case_id"]: item for item in case_batch["cases"]}
        results = {item["case_id"]: item for item in result_batch["results"]}
        plan, leaf, selection, checkpoint = _one_leaf_campaign()
        routes = _locked_routes(checkpoint, (leaf,))
        preflight = require_locked_bf40_determinant_error_issuance_authority(
            route="EXTERIOR_BF40"
        )

        interrupted_calls: list[tuple[int, str]] = []
        resumed_calls: list[tuple[int, str]] = []

        def root_lookup(active_leaf, entry):
            return AuthenticatedRootSeal(
                active_leaf.job.root.omega,
                active_leaf.job.root.branch_id,
                entry["source_root_seal_sha256"],
            )

        with tempfile.TemporaryDirectory() as temporary:
            checkpoint_path = Path(temporary) / "checkpoint.json"
            with self.assertRaises(KeyboardInterrupt):
                _strict_run(
                    plan,
                    selection,
                    checkpoint,
                    checkpoint_path=checkpoint_path,
                    root_seal_lookup=root_lookup,
                    root_seal_publish=lambda *_args: self.fail(
                        "response route must not recompute or publish a root"
                    ),
                    backend_factory=lambda _leaf, digits: _MatrixBackend(
                        digits,
                        cases,
                        results,
                        interrupted_calls,
                        fail_bf40_component=True,
                        interrupt_bf80=True,
                    ),
                    primary_root_runner=lambda *_args: self.fail(
                        "response route must not run a root solver"
                    ),
                    horizon_runner=lambda *_args: self.fail(
                        "exterior route must not run the horizon worker"
                    ),
                    layer1_guard=_TestLayer1Guard(),
                    locked_routes_by_ordinal=routes,
                    promoted_preflights_by_ordinal={0: preflight},
                    layer1_lock_receipt_sha256="f" * 64,
                )
            interrupted = json.loads(checkpoint_path.read_bytes())
            entry = interrupted["promotion_queue"]["entries"][0]
            continuation = interrupted["promoted_stage_ledger"]["0"][
                leaf.leaf_id
            ]
            self.assertEqual(entry["disposition"], "NUMERICAL_CONTINUATION")
            self.assertEqual(continuation["admission_state"], "NUMERICAL_CONTINUATION")
            self.assertEqual(continuation["precision_tiers"], ["BF40"])
            self.assertEqual(continuation["sample_count"], 5)
            self.assertEqual(continuation["worker_launch_count"], 2)
            self.assertEqual(
                interrupted_calls,
                [
                    (40, FixedRootSurveyPlan.CANONICAL_BACKGROUND_FIVE.value),
                    (40, FixedRootSurveyPlan.MECHANISM_COMPONENT_FOUR.value),
                    (80, FixedRootSurveyPlan.CANONICAL_BACKGROUND_FIVE.value),
                ],
            )

            resumed = _strict_run(
                plan,
                selection,
                interrupted,
                checkpoint_path=checkpoint_path,
                root_seal_lookup=root_lookup,
                root_seal_publish=lambda *_args: self.fail(
                    "resume must retain the existing root"
                ),
                backend_factory=lambda _leaf, digits: _MatrixBackend(
                    digits,
                    cases,
                    results,
                    resumed_calls,
                    fail_bf40_component=False,
                    interrupt_bf80=False,
                ),
                primary_root_runner=lambda *_args: self.fail(
                    "resume must not replay the root"
                ),
                horizon_runner=lambda *_args: self.fail(
                    "resume must not run the horizon worker"
                ),
                layer1_guard=_TestLayer1Guard(),
                locked_routes_by_ordinal=routes,
                promoted_preflights_by_ordinal={0: preflight},
                layer1_lock_receipt_sha256="f" * 64,
            )

        final_entry = resumed.checkpoint["promotion_queue"]["entries"][0]
        final_stage = resumed.checkpoint["promoted_stage_ledger"]["0"][
            leaf.leaf_id
        ]
        self.assertEqual(
            resumed_calls,
            [
                (80, FixedRootSurveyPlan.CANONICAL_BACKGROUND_FIVE.value),
                (80, FixedRootSurveyPlan.MECHANISM_COMPONENT_FOUR.value),
            ],
        )
        self.assertEqual(final_entry["disposition"], "AWAITING_ADMISSION")
        self.assertEqual(final_stage["precision_tiers"], ["BF40", "BF80"])
        self.assertEqual(final_stage["sample_count"], 14)
        self.assertEqual(final_stage["root_read_count"], 0)
        self.assertEqual(final_stage["worker_launch_count"], 4)
        self.assertEqual(
            final_stage["calculation_artifact"]["schema"],
            "windows-solver.promoted-exterior-calculation/4",
        )
        self.assertNotIn("BF120", json.dumps(resumed.checkpoint))


if __name__ == "__main__":
    unittest.main()
