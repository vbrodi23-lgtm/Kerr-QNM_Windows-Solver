"""PR69 regression: authenticate committed provisional stages by schema."""

from __future__ import annotations

import copy
import hashlib
import inspect
import os
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

import windows_solver.campaign_runtime as campaign_runtime
from windows_solver.campaign_failures import (
    CampaignSystemFailure,
    resolve_layer1_system_failure_for_resume,
)
from windows_solver.campaign_policy import empty_schema11_checkpoint
from windows_solver.campaign_recovery import RecoverySelection
from windows_solver.campaign_survey import (
    AuthenticatedRootSeal,
    Binary64SurveyRun,
    run_binary64_survey,
)
from windows_solver.contracts import canonical_json_bytes
from windows_solver.native_response_kernel import VettedNativeDeterminantKernel
from windows_solver.response_batches import (
    HORIZON_SCREENING_STAGE_SCHEMA,
    NativeCampaignStageBackend,
    PrecisionCapabilities,
    build_campaign_plan,
    build_campaign_selection,
    scientific_computation_identity_sha256,
)
from windows_solver.response_engine import (
    BINARY64_FIXED_ROOT_SAMPLE_ROLES,
    BINARY64_HORIZON_OPERATION_V3,
    BackgroundEquivalenceReceipt,
    Binary64FixedRootBatch,
    Binary64FixedRootSample,
    ComponentResult,
    ComponentStatus,
    DeterminantPartials,
    EXTERIOR_PROVISIONAL_STAGE_SCHEMA,
    NumericalPolicy,
    _exterior_support,
    build_exterior_background_reuse_key,
    build_exterior_provisional_stage,
    canonical_background_from_binary64_batch,
    validate_exterior_provisional_stage,
)
from windows_solver.root_evidence import AuthenticatedRootEvidence
from windows_solver.solved_leaf_cache import SolvedLeafStore
from windows_solver.structural_diagnostics import StructuralDiagnosticSession


def _sha256(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _rehash_stage(stage: dict[str, object]) -> None:
    stage["stage_sha256"] = _sha256(
        {key: value for key, value in stage.items() if key != "stage_sha256"}
    )


def _mock_binary64_backend() -> NativeCampaignStageBackend:
    """Return a Python-only horizon backend with no root or worker launch."""

    class Kernel:
        identity = VettedNativeDeterminantKernel.identity

        def horizon_partials(self, **kwargs):
            job = kwargs["job"]
            horizon_radius = 1.0 + (1.0 - job.spin * job.spin) ** 0.5
            omega_h = job.spin / (2.0 * horizon_radius)
            p_h = job.root.omega - job.mode.m * omega_h
            coordinate = -0.5 + 0.1j
            return DeterminantPartials(
                frequency_derivative=1.0 + 0.25j,
                coordinate_derivative=coordinate,
                simple_root_valid=True,
                frequency_derivative_error_abs=1.0e-12,
                dD_dR=coordinate * (2.0j * p_h),
                dD_dR_error_abs=1.0e-12,
                dR_ddeltaB=1.0 / (2.0j * p_h),
                dD_ddeltaB=coordinate,
                dD_domega=1.0 + 0.25j,
                dD_domega_error_abs=1.0e-12,
            )

        def evaluate_root(self, **_kwargs):
            raise AssertionError("binary64 horizon entered a root ladder")

    kernel = Kernel()
    return NativeCampaignStageBackend(
        SimpleNamespace(identity=kernel.identity, kernel=kernel),
        PrecisionCapabilities((64,)),
        SimpleNamespace(
            record_artifact_ids=(),
            path=Path("mocked-gsn-cache"),
            sha256="a" * 64,
            parameter_pairs=(),
        ),
    )


def _canonical_exterior_stage(
    leaf: object,
    *,
    scientific_identity: str,
    root_seal_sha256: str,
) -> dict[str, object]:
    """Build the exact package-owned exterior predecessor envelope."""

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
    stage, _ = build_exterior_provisional_stage(
        job=leaf.job,
        scientific_computation_identity=scientific_identity,
        root_seal_sha256=root_seal_sha256,
        raw_batch=batch,
        combined_batch=batch,
        background=background,
        background_receipt=receipt,
        reason_code="DETERMINANT_ERROR_EVIDENCE_UNAVAILABLE",
    )
    return stage


class ProvisionalStagePublicationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.plan = build_campaign_plan(
            policy=NumericalPolicy(),
            backend_identity=VettedNativeDeterminantKernel.identity,
            precision_capabilities=PrecisionCapabilities((64, 80)),
        )
        cls.horizons = tuple(
            leaf
            for leaf in cls.plan.leaves
            if leaf.mechanism_id == "horizon-admittance"
            and leaf.role == "primary"
        )[:2]
        cls.exteriors = tuple(
            leaf
            for leaf in cls.plan.leaves
            if leaf.mechanism_id != "horizon-admittance"
            and leaf.role == "primary"
        )[:2]
        if len(cls.horizons) != 2 or len(cls.exteriors) != 2:
            raise AssertionError("PR69 fixtures require two leaves per mechanism family")

    def _selection_and_recovery(self, leaves):
        selection = build_campaign_selection(
            self.plan,
            role=leaves[0].role,
            leaf_ids=tuple(leaf.leaf_id for leaf in leaves),
        )
        recovery = RecoverySelection(
            campaign_id=self.plan.campaign_id,
            selection_id=selection.selection_id,
            ordered_leaf_ids=tuple(leaf.leaf_id for leaf in leaves),
            roles={leaf.leaf_id: leaf.role for leaf in leaves},
            scientific_identities={
                leaf.leaf_id: scientific_computation_identity_sha256(
                    self.plan, leaf
                )
                for leaf in leaves
            },
        )
        return selection, recovery

    def _canonical_horizon_stage(self, leaf=None) -> dict[str, object]:
        target = self.horizons[0] if leaf is None else leaf
        outcome = campaign_runtime._horizon_outcome(
            self.plan,
            _mock_binary64_backend(),
            target,
            root_evidence=AuthenticatedRootEvidence.from_bound_leaf(target),
        )
        self.assertIsNotNone(outcome.provisional_stage)
        return copy.deepcopy(dict(outcome.provisional_stage))

    def test_seed_only_horizon_provisional_stage_is_authenticated_after_durable_commit(
        self,
    ) -> None:
        """Reproduce the exact failed transition through real orchestration."""

        leaf = self.horizons[0]
        selection, recovery = self._selection_and_recovery((leaf,))
        captured_stage_bytes: list[bytes] = []
        original_builder = campaign_runtime.build_schema11_horizon_stage

        def capture_stage(*args, **kwargs):
            stage, digest = original_builder(*args, **kwargs)
            captured_stage_bytes.append(canonical_json_bytes(stage))
            return stage, digest

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            checkpoint_path = root / "checkpoint.json"
            session = StructuralDiagnosticSession.open(
                checkpoint_path=checkpoint_path,
                session_id="pr69-horizon-publication",
                campaign_id=self.plan.campaign_id,
                selection_id=selection.selection_id,
            )
            try:
                with patch.dict(
                    os.environ, {"KERR_QNM_ROOT_READOUT_CACHE": "0"}
                ), patch.object(
                    campaign_runtime,
                    "_binary64_backend",
                    return_value=_mock_binary64_backend(),
                ), patch.object(
                    campaign_runtime,
                    "build_schema11_horizon_stage",
                    side_effect=capture_stage,
                ), patch.object(
                    campaign_runtime,
                    "_refresh_runtime_reports",
                    side_effect=(
                        lambda _plan, _selection, _path, checkpoint, **_kwargs:
                        dict(checkpoint)
                    ),
                ):
                    result = campaign_runtime.run_native_binary64_pass(
                        self.plan,
                        selection,
                        recovery,
                        empty_schema11_checkpoint(
                            self.plan.campaign_id, selection.selection_id
                        ),
                        checkpoint_path=checkpoint_path,
                        solved_leaf_store=SolvedLeafStore(root / "solved-leaves"),
                        diagnostic_session=session,
                    )
                events = session.final_events(100)
            finally:
                session.close_completed()

        self.assertEqual(1, result.queued_count)
        self.assertEqual(1, len(result.checkpoint["survey_pass_ledger"]["binary64"]))
        ledger = result.checkpoint["survey_pass_ledger"]["binary64"][leaf.leaf_id]
        self.assertEqual("PROMOTION_PENDING_RESPONSE", ledger["disposition"])
        self.assertEqual("ROOT_UNCERTAINTY_EVIDENCE_UNAVAILABLE", ledger["reason_code"])
        self.assertEqual(0, ledger["worker_launch_count"])
        self.assertEqual([], result.checkpoint["records"])
        self.assertEqual({}, result.checkpoint["evidence_ledger"])
        self.assertEqual([], result.checkpoint["system_failures"])

        entries = result.checkpoint["promotion_queue"]["entries"]
        self.assertEqual(1, len(entries))
        entry = entries[0]
        self.assertEqual("RESPONSE", entry["queue_kind"])
        self.assertEqual("PENDING", entry["disposition"])
        self.assertEqual("BF80", entry["minimum_requested_tier"])
        stage = entry["provisional_stage"]
        self.assertEqual(captured_stage_bytes, [canonical_json_bytes(stage)])
        self.assertEqual(HORIZON_SCREENING_STAGE_SCHEMA, stage["schema"])
        self.assertEqual(BINARY64_HORIZON_OPERATION_V3, stage["operation_identity"])
        self.assertEqual("binary64", stage["precision_tier"])
        self.assertIsNone(stage["response_disk"])
        parsed = ComponentResult.from_mapping(stage["component_result"]["result"])
        self.assertIs(ComponentStatus.DERIVATIVE_UNRESOLVED, parsed.status)
        evidence = parsed.analytic_horizon_evidence
        self.assertIsNotNone(evidence)
        self.assertEqual("SEED_ONLY", evidence["root_evidence_level"])
        self.assertEqual(
            "ROOT_UNCERTAINTY_EVIDENCE_UNAVAILABLE", evidence["failure_code"]
        )
        self.assertNotIn("root_seal_sha256", stage)
        self.assertEqual(evidence["root_seal_sha256"], entry["source_root_seal_sha256"])

        published = [
            event
            for event in events
            if event["event_kind"] == "PROVISIONAL_STAGE_PUBLISHED"
        ]
        self.assertEqual(1, len(published))
        event = published[0]
        self.assertEqual(
            evidence["root_seal_sha256"], event["connections"]["root_seal_sha256"]
        )
        self.assertEqual(
            {
                "stage_schema": HORIZON_SCREENING_STAGE_SCHEMA,
                "numerical_state": "DERIVATIVE_UNRESOLVED",
                "failure_code": "ROOT_UNCERTAINTY_EVIDENCE_UNAVAILABLE",
            },
            event["compact_diagnostics"],
        )

    def test_canonical_v3_horizon_stage_is_accepted(self) -> None:
        leaf = self.horizons[0]
        stage = self._canonical_horizon_stage(leaf)
        result = ComponentResult.from_mapping(stage["component_result"]["result"])
        evidence = result.analytic_horizon_evidence
        metadata = campaign_runtime._provisional_stage_publication_metadata(
            self.plan, leaf, stage
        )
        self.assertEqual(stage["stage_sha256"], metadata[0])
        self.assertEqual(evidence["root_seal_sha256"], metadata[1])
        self.assertEqual(HORIZON_SCREENING_STAGE_SCHEMA, metadata[2]["stage_schema"])

    def test_modified_horizon_stage_digest_is_rejected(self) -> None:
        stage = self._canonical_horizon_stage()
        stage["numerical_state"] = "CONVERGED"
        with self.assertRaises(ValueError):
            campaign_runtime._provisional_stage_publication_metadata(
                self.plan, self.horizons[0], stage
            )

    def test_v2_horizon_operation_is_rejected(self) -> None:
        stage = self._canonical_horizon_stage()
        stage["operation_identity"] = "binary64-horizon-production/v2"
        _rehash_stage(stage)
        with self.assertRaises(ValueError):
            campaign_runtime._provisional_stage_publication_metadata(
                self.plan, self.horizons[0], stage
            )

    def test_horizon_precision_must_be_binary64(self) -> None:
        stage = self._canonical_horizon_stage()
        stage["precision_tier"] = "BF80"
        _rehash_stage(stage)
        with self.assertRaises(ValueError):
            campaign_runtime._provisional_stage_publication_metadata(
                self.plan, self.horizons[0], stage
            )

    def test_missing_or_malformed_nested_root_seal_is_rejected(self) -> None:
        for replacement in (None, "not-a-sha256"):
            with self.subTest(replacement=replacement):
                stage = self._canonical_horizon_stage()
                evidence = stage["component_result"]["result"][
                    "analytic_horizon_evidence"
                ]
                if replacement is None:
                    evidence.pop("root_seal_sha256")
                else:
                    evidence["root_seal_sha256"] = replacement
                _rehash_stage(stage)
                with self.assertRaises(ValueError):
                    campaign_runtime._provisional_stage_publication_metadata(
                        self.plan, self.horizons[0], stage
                    )

    def test_exterior_leaf_cannot_publish_horizon_stage(self) -> None:
        stage = self._canonical_horizon_stage()
        with self.assertRaises(ValueError):
            campaign_runtime._provisional_stage_publication_metadata(
                self.plan, self.exteriors[0], stage
            )

    def test_unknown_provisional_stage_schema_fails_closed(self) -> None:
        leaf = self.exteriors[0]
        stage = _canonical_exterior_stage(
            leaf,
            scientific_identity=scientific_computation_identity_sha256(
                self.plan, leaf
            ),
            root_seal_sha256="b" * 64,
        )
        stage["schema"] = "windows-solver.unknown-provisional-stage/1"
        _rehash_stage(stage)
        with self.assertRaises(ValueError):
            campaign_runtime._provisional_stage_publication_metadata(
                self.plan, leaf, stage
            )

    def test_canonical_exterior_stage_uses_strict_validator_and_sample_event(
        self,
    ) -> None:
        leaf = self.exteriors[0]
        selection, recovery = self._selection_and_recovery((leaf,))
        scientific_identity = scientific_computation_identity_sha256(
            self.plan, leaf
        )
        stage = _canonical_exterior_stage(
            leaf,
            scientific_identity=scientific_identity,
            root_seal_sha256="c" * 64,
        )
        self.assertEqual(EXTERIOR_PROVISIONAL_STAGE_SCHEMA, stage["schema"])
        authenticated = validate_exterior_provisional_stage(
            stage,
            job=leaf.job,
            scientific_computation_identity=scientific_identity,
            root_seal_sha256="c" * 64,
        )
        self.assertEqual(stage, authenticated)

        def scheduler_stub(_plan, _recovery, checkpoint, **kwargs):
            kwargs["provisional_stage_committed"](leaf, stage)
            return Binary64SurveyRun(
                checkpoint=dict(checkpoint),
                completed_count=0,
                queued_count=0,
                cache_reused_count=0,
                skipped_count=0,
                pass_exhausted=False,
            )

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            checkpoint_path = root / "checkpoint.json"
            session = StructuralDiagnosticSession.open(
                checkpoint_path=checkpoint_path,
                session_id="pr69-exterior-publication",
                campaign_id=self.plan.campaign_id,
                selection_id=selection.selection_id,
            )
            try:
                with patch.object(
                    campaign_runtime,
                    "run_binary64_survey",
                    side_effect=scheduler_stub,
                ):
                    campaign_runtime.run_native_binary64_pass(
                        self.plan,
                        selection,
                        recovery,
                        empty_schema11_checkpoint(
                            self.plan.campaign_id, selection.selection_id
                        ),
                        checkpoint_path=checkpoint_path,
                        solved_leaf_store=SolvedLeafStore(root / "solved-leaves"),
                        diagnostic_session=session,
                    )
                events = session.final_events(100)
            finally:
                session.close_completed()

        published = [
            event
            for event in events
            if event["event_kind"] == "PROVISIONAL_STAGE_PUBLISHED"
        ]
        self.assertEqual(1, len(published))
        self.assertEqual("c" * 64, published[0]["connections"]["root_seal_sha256"])
        self.assertEqual(
            {
                "raw_sample_count": stage["raw_sample_count"],
                "raw_sample_limit": stage["raw_sample_limit"],
                "nonadmission_reason_code": stage["nonadmission_reason_code"],
            },
            published[0]["compact_diagnostics"],
        )

    def test_exterior_stage_is_bound_to_the_exact_leaf(self) -> None:
        source, target = self.exteriors
        stage = _canonical_exterior_stage(
            source,
            scientific_identity=scientific_computation_identity_sha256(
                self.plan, source
            ),
            root_seal_sha256="d" * 64,
        )
        with self.assertRaises(ValueError):
            campaign_runtime._provisional_stage_publication_metadata(
                self.plan, target, stage
            )

    def test_post_failure_checkpoint_resume_skips_leaf_one_and_advances_leaf_two(
        self,
    ) -> None:
        first, second = self.horizons
        _selection, recovery = self._selection_and_recovery((first, second))
        checkpoint = empty_schema11_checkpoint(
            self.plan.campaign_id, recovery.selection_id
        )
        evidence = {
            leaf.leaf_id: AuthenticatedRootEvidence.from_bound_leaf(leaf)
            for leaf in (first, second)
        }
        seals = {
            leaf.leaf_id: AuthenticatedRootSeal(
                fixed_root=item.fixed_root,
                branch_identity=item.branch_identity,
                root_seal_sha256=item.root_seal_sha256,
            )
            for leaf, item in (
                (first, evidence[first.leaf_id]),
                (second, evidence[second.leaf_id]),
            )
        }
        backend = _mock_binary64_backend()
        calls: list[str] = []

        def horizon_runner(leaf):
            calls.append(leaf.leaf_id)
            return campaign_runtime._horizon_outcome(
                self.plan,
                backend,
                leaf,
                root_evidence=evidence[leaf.leaf_id],
            )

        with tempfile.TemporaryDirectory() as temporary:
            checkpoint_path = Path(temporary) / "checkpoint.json"
            with self.assertRaises(CampaignSystemFailure) as raised:
                run_binary64_survey(
                    self.plan,
                    recovery,
                    checkpoint,
                    checkpoint_path=checkpoint_path,
                    root_seal_lookup=lambda leaf: seals[leaf.leaf_id],
                    native_backend_factory=lambda: self.fail(
                        "horizon resume requested an exterior backend"
                    ),
                    horizon_runner=horizon_runner,
                    produced_record_builder=lambda *_args: self.fail(
                        "horizon resume fabricated a numerical record"
                    ),
                    provisional_stage_committed=lambda *_args: (_ for _ in ()).throw(
                        ValueError("provisional stage publication is unauthenticated")
                    ),
                )
            failed = raised.exception.checkpoint
            self.assertEqual(
                "provisional stage publication is unauthenticated",
                str(raised.exception),
            )
            self.assertEqual([first.leaf_id], calls)
            first_queue_bytes = canonical_json_bytes(
                failed["promotion_queue"]["entries"][0]
            )
            failure_bytes = canonical_json_bytes(failed["system_failures"])
            first_ledger_bytes = canonical_json_bytes(
                failed["survey_pass_ledger"]["binary64"][first.leaf_id]
            )
            resolved, _resolution = resolve_layer1_system_failure_for_resume(
                failed,
                system_failure_receipt_sha256=(
                    raised.exception.receipt["receipt_sha256"]
                ),
                repair_commit_sha="d" * 40,
                reason="repair provisional-stage publication before resuming",
            )

            calls.clear()
            published: list[str] = []
            resumed = run_binary64_survey(
                self.plan,
                recovery,
                resolved,
                checkpoint_path=checkpoint_path,
                root_seal_lookup=lambda leaf: seals[leaf.leaf_id],
                native_backend_factory=lambda: self.fail(
                    "horizon resume requested an exterior backend"
                ),
                horizon_runner=horizon_runner,
                produced_record_builder=lambda *_args: self.fail(
                    "horizon resume fabricated a numerical record"
                ),
                provisional_stage_committed=lambda leaf, _stage: published.append(
                    leaf.leaf_id
                ),
            )

        self.assertEqual([second.leaf_id], calls)
        self.assertEqual([second.leaf_id], published)
        self.assertEqual(1, resumed.skipped_count)
        self.assertIn(
            second.leaf_id, resumed.checkpoint["survey_pass_ledger"]["binary64"]
        )
        self.assertEqual(2, len(resumed.checkpoint["promotion_queue"]["entries"]))
        self.assertEqual(
            first_queue_bytes,
            canonical_json_bytes(resumed.checkpoint["promotion_queue"]["entries"][0]),
        )
        self.assertEqual(
            first_ledger_bytes,
            canonical_json_bytes(
                resumed.checkpoint["survey_pass_ledger"]["binary64"][first.leaf_id]
            ),
        )
        self.assertEqual(
            failure_bytes, canonical_json_bytes(resumed.checkpoint["system_failures"])
        )
        self.assertEqual(1, len(resumed.checkpoint["system_failures"]))
        self.assertEqual([], resumed.checkpoint["records"])
        self.assertEqual({}, resumed.checkpoint["evidence_ledger"])

    def test_publication_policy_has_one_schema_discriminating_owner(self) -> None:
        helper_source = inspect.getsource(
            campaign_runtime._provisional_stage_publication_metadata
        )
        runtime_source = inspect.getsource(campaign_runtime.run_native_binary64_pass)
        normalized_runtime_source = " ".join(runtime_source.split())
        self.assertIn("validate_schema11_horizon_stage", helper_source)
        self.assertIn("validate_exterior_provisional_stage", helper_source)
        self.assertIn("EXTERIOR_PROVISIONAL_STAGE_SCHEMA", helper_source)
        self.assertIn(
            "_provisional_stage_publication_metadata(plan, leaf, stage)",
            normalized_runtime_source,
        )
        self.assertIn("compact_diagnostics=compact_diagnostics", runtime_source)
        obsolete_exterior_schema = (
            "windows-solver.binary64-fixed-root-" + "provisional/1"
        )
        self.assertNotIn(
            obsolete_exterior_schema, runtime_source
        )


if __name__ == "__main__":
    unittest.main()
