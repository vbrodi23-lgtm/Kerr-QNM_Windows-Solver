from __future__ import annotations

import copy
import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from windows_solver.binary64_layer_lock import (
    BINARY64_LAYER_LOCK_SCHEMA,
    Layer1Guard,
    Binary64LayerLockViolation,
    assert_binary64_layer_unchanged,
    binary64_layer_lock_path,
    build_binary64_layer_lock,
    load_binary64_layer_lock,
    validate_binary64_layer_lock,
    write_binary64_layer_lock,
)
from windows_solver.campaign_policy import (
    PromotionQueueDisposition,
    PromotionQueueKind,
    SurveyDisposition,
    SurveyPass,
    add_numerical_record,
    append_promotion,
    empty_schema11_checkpoint,
    finish_promotion,
    promotion_source_fingerprint_sha256,
    record_evidence,
    record_survey_disposition,
)
from windows_solver.campaign_recovery import RecoverySelection
from windows_solver.cli import build_parser
from windows_solver.contracts import canonical_json_bytes
from windows_solver.campaign_survey import binary64_pass_exhaustion
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


def _sha256(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


class Binary64LayerLockTests(unittest.TestCase):
    """The lock protects Layer 1 while permitting the Layer-2 queue lifecycle."""

    @classmethod
    def setUpClass(cls) -> None:
        plan = build_campaign_plan(
            policy=NumericalPolicy(),
            backend_identity=VettedNativeDeterminantKernel.identity,
            precision_capabilities=PrecisionCapabilities((64, 80)),
        )
        cls.leaf = next(
            leaf
            for leaf in plan.leaves
            if leaf.mechanism_id != "horizon-admittance"
        )
        selected = build_campaign_selection(
            plan,
            role=cls.leaf.role,
            leaf_ids=(cls.leaf.leaf_id,),
        )
        cls.selection = RecoverySelection(
            campaign_id=plan.campaign_id,
            selection_id=selected.selection_id,
            ordered_leaf_ids=(cls.leaf.leaf_id,),
            roles={cls.leaf.leaf_id: cls.leaf.role},
            scientific_identities={
                cls.leaf.leaf_id: scientific_computation_identity_sha256(
                    plan, cls.leaf
                )
            },
        )

    def _provisional_stage(self) -> dict[str, object]:
        scientific_identity = self.selection.scientific_identities[
            self.leaf.leaf_id
        ]
        content: dict[str, object] = {
            "schema": "windows-solver.binary64-fixed-root-provisional-stage/1",
            "operation_identity": "binary64-fixed-root-provisional/v1",
            "leaf_id": self.leaf.leaf_id,
            "mechanism_id": self.leaf.mechanism_id,
            "scientific_computation_identity": scientific_identity,
            "root_seal_sha256": "a" * 64,
            "raw_sample_count": 9,
            "combined_sample_count": 9,
            "canonical_background": {
                "schema": "windows-solver.canonical-exterior-background/1",
                "operation_identity": "canonical-exterior-background/v1",
                "reuse_key": {"test": "exact-background-key"},
            },
        }
        return {**content, "stage_sha256": _sha256(content)}

    def _checkpoint(self) -> tuple[dict[str, object], dict[str, object]]:
        stage = self._provisional_stage()
        checkpoint = empty_schema11_checkpoint(
            self.selection.campaign_id, self.selection.selection_id
        )
        checkpoint = record_survey_disposition(
            checkpoint,
            survey_pass=SurveyPass.BINARY64,
            leaf_id=self.leaf.leaf_id,
            disposition=SurveyDisposition.PROMOTION_PENDING_RESPONSE,
            operation_identity="exterior-fixed-root-survey-raw/v1",
            precision_tiers=("binary64",),
            reason_code="BLOCKED_BY_REVIEWED_ERROR_EVIDENCE",
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
            self.leaf.leaf_id
        ]["disposition_receipt_sha256"]
        checkpoint = append_promotion(
            checkpoint,
            leaf_id=self.leaf.leaf_id,
            queue_kind=PromotionQueueKind.RESPONSE,
            reason_code="BLOCKED_BY_REVIEWED_ERROR_EVIDENCE",
            minimum_requested_tier="BF40",
            scientific_computation_identity=self.selection.scientific_identities[
                self.leaf.leaf_id
            ],
            source_stage_sha256=str(stage["stage_sha256"]),
            source_root_seal_sha256="a" * 64,
            provisional_stage=stage,
            provisional_stage_sha256=str(stage["stage_sha256"]),
            provisional_operation_identity=str(stage["operation_identity"]),
            source_binary64_disposition_receipt_sha256=str(disposition_receipt),
        )
        return checkpoint, stage

    def _auxiliary_manifest(
        self, stage: dict[str, object]
    ) -> tuple[dict[str, object], ...]:
        background = stage["canonical_background"]
        assert isinstance(background, dict)
        return (
            {
                "logical_key": {
                    "kind": "root-evidence",
                    "root_seal_sha256": "a" * 64,
                },
                "object_schema": "windows-solver.test-root-evidence/1",
                "object_sha256": "a" * 64,
                "store_identity": "test-root-evidence-store",
            },
            {
                "logical_key": {
                    "kind": "canonical-background",
                    "background_sha256": _sha256(background),
                },
                "object_schema": "windows-solver.canonical-exterior-background/1",
                "object_sha256": _sha256(background),
                "store_identity": "test-background-evidence-store",
            },
        )

    def _lock(self, checkpoint: dict[str, object], stage: dict[str, object]):
        return build_binary64_layer_lock(
            checkpoint,
            selection=self.selection,
            leaf_mechanism_ids={self.leaf.leaf_id: self.leaf.mechanism_id},
            auxiliary_evidence_manifest=self._auxiliary_manifest(stage),
        )

    def test_completed_binary64_handoff_builds_a_deterministic_lock(self) -> None:
        """Break caught: nondeterministic or incomplete lock construction."""

        checkpoint, stage = self._checkpoint()

        first = self._lock(checkpoint, stage)
        second = self._lock(checkpoint, stage)

        self.assertEqual(BINARY64_LAYER_LOCK_SCHEMA, first["schema"])
        self.assertEqual(first, second)
        self.assertEqual(1, first["selected_leaf_count"])
        self.assertEqual(1, first["binary64_processed_count"])
        self.assertEqual(1, first["pending_promotion_count"])
        self.assertEqual({"EXTERIOR_BF40": 1, "HORIZON_BF80": 0}, first["route_counts"])
        self.assertEqual(first, validate_binary64_layer_lock(
            first,
            checkpoint,
            selection=self.selection,
            leaf_mechanism_ids={self.leaf.leaf_id: self.leaf.mechanism_id},
            auxiliary_evidence_manifest=self._auxiliary_manifest(stage),
        ))

    def test_unbound_promotion_keeps_binary64_handoff_partial(self) -> None:
        """Break caught: a promotion without a lockable source is marked ready."""

        checkpoint = empty_schema11_checkpoint(
            self.selection.campaign_id, self.selection.selection_id
        )
        checkpoint = record_survey_disposition(
            checkpoint,
            survey_pass=SurveyPass.BINARY64,
            leaf_id=self.leaf.leaf_id,
            disposition=SurveyDisposition.PROMOTION_PENDING_RESPONSE,
            operation_identity="exterior-fixed-root-survey-raw/v1",
            precision_tiers=("binary64",),
            reason_code="BLOCKED_BY_REVIEWED_ERROR_EVIDENCE",
            sample_count=9,
            sample_limit=9,
            root_read_count=0,
            root_read_limit=0,
            worker_launch_count=0,
            worker_launch_limit=0,
            tier_timing=(),
            session_fragments=(),
        )
        checkpoint = append_promotion(
            checkpoint,
            leaf_id=self.leaf.leaf_id,
            queue_kind=PromotionQueueKind.RESPONSE,
            reason_code="BLOCKED_BY_REVIEWED_ERROR_EVIDENCE",
            minimum_requested_tier="BF40",
            scientific_computation_identity=self.selection.scientific_identities[
                self.leaf.leaf_id
            ],
            source_root_seal_sha256="a" * 64,
        )

        exhaustion = binary64_pass_exhaustion(checkpoint, self.selection)

        self.assertFalse(exhaustion.exhausted)
        self.assertIn("UNLOCKABLE_PROMOTION_SOURCE", exhaustion.reasons)

    def test_promoted_queue_completion_preserves_the_layer1_lock(self) -> None:
        """Break caught: the lock incorrectly includes Layer-2 disposition state."""

        checkpoint, stage = self._checkpoint()
        lock = self._lock(checkpoint, stage)
        guard = Layer1Guard.from_authenticated_lock(
            lock,
            checkpoint,
            selection=self.selection,
            leaf_mechanism_ids={self.leaf.leaf_id: self.leaf.mechanism_id},
            auxiliary_evidence_manifest=self._auxiliary_manifest(stage),
        )
        self.assertEqual(
            promotion_source_fingerprint_sha256(
                checkpoint["promotion_queue"]["entries"][0]
            ),
            checkpoint["promotion_queue"]["entries"][0][
                "source_fingerprint_sha256"
            ],
        )
        disposition_receipt = {"schema": "windows-solver.test-disposition/1"}
        promoted = finish_promotion(
            checkpoint,
            queue_ordinal=0,
            disposition=PromotionQueueDisposition.COMPLETED,
            disposition_receipt=disposition_receipt,
            layer1_guard=guard,
        )
        self.assertEqual(
            _sha256({
                **disposition_receipt,
                "source_fingerprint_sha256": checkpoint["promotion_queue"][
                    "entries"
                ][0]["source_fingerprint_sha256"],
            }),
            promoted["promotion_queue"]["entries"][0][
                "disposition_receipt_sha256"
            ],
        )

        promoted = record_survey_disposition(
            promoted,
            survey_pass=SurveyPass.PROMOTED,
            leaf_id=self.leaf.leaf_id,
            disposition=SurveyDisposition.COMPLETED,
            operation_identity="promoted-fixed-root-survey/v1",
            precision_tiers=("BF40",),
            reason_code="BOUNDED_PROMOTED_FIXED_ROOT_RESPONSE",
            sample_count=0,
            sample_limit=0,
            root_read_count=0,
            root_read_limit=0,
            worker_launch_count=0,
            worker_launch_limit=0,
            tier_timing=(),
            session_fragments=(),
            layer1_guard=guard,
        )

        self.assertEqual(lock, assert_binary64_layer_unchanged(
            lock,
            promoted,
            selection=self.selection,
            leaf_mechanism_ids={self.leaf.leaf_id: self.leaf.mechanism_id},
            auxiliary_evidence_manifest=self._auxiliary_manifest(stage),
        ))

    def test_layer1_guard_rejects_a_new_or_rewritten_queue_source(self) -> None:
        """Break caught: promoted work can append a second Layer-1 source."""

        checkpoint, stage = self._checkpoint()
        lock = self._lock(checkpoint, stage)
        guard = Layer1Guard.from_authenticated_lock(
            lock,
            checkpoint,
            selection=self.selection,
            leaf_mechanism_ids={self.leaf.leaf_id: self.leaf.mechanism_id},
            auxiliary_evidence_manifest=self._auxiliary_manifest(stage),
        )

        with self.assertRaisesRegex(
            Binary64LayerLockViolation, "BINARY64_LAYER_LOCK_VIOLATION"
        ):
            append_promotion(
                checkpoint,
                leaf_id=self.leaf.leaf_id,
                queue_kind=PromotionQueueKind.RESPONSE,
                reason_code="BLOCKED_BY_REVIEWED_ERROR_EVIDENCE",
                minimum_requested_tier="BF40",
                scientific_computation_identity=self.selection.scientific_identities[
                    self.leaf.leaf_id
                ],
                source_stage_sha256=str(stage["stage_sha256"]),
                source_root_seal_sha256="a" * 64,
                provisional_stage=stage,
                provisional_stage_sha256=str(stage["stage_sha256"]),
                provisional_operation_identity=str(stage["operation_identity"]),
                source_binary64_disposition_receipt_sha256=checkpoint[
                    "survey_pass_ledger"
                ]["binary64"][self.leaf.leaf_id]["disposition_receipt_sha256"],
                layer1_guard=guard,
            )

    def test_source_stage_mutation_raises_a_layer1_lock_violation(self) -> None:
        """Break caught: Layer 1 can be edited after the lock is issued."""

        checkpoint, stage = self._checkpoint()
        lock = self._lock(checkpoint, stage)
        mutated = copy.deepcopy(checkpoint)
        entry = mutated["promotion_queue"]["entries"][0]
        entry["provisional_stage"]["raw_sample_count"] = 4

        with self.assertRaisesRegex(
            Binary64LayerLockViolation, "BINARY64_LAYER_LOCK_VIOLATION"
        ):
            assert_binary64_layer_unchanged(
                lock,
                mutated,
                selection=self.selection,
                leaf_mechanism_ids={self.leaf.leaf_id: self.leaf.mechanism_id},
                auxiliary_evidence_manifest=self._auxiliary_manifest(stage),
            )

    def test_manifest_objects_must_match_the_referenced_source_digests(self) -> None:
        """Break caught: a key-only manifest can substitute foreign evidence."""

        checkpoint, stage = self._checkpoint()
        manifest = list(self._auxiliary_manifest(stage))
        manifest[0] = {**manifest[0], "object_sha256": "c" * 64}

        with self.assertRaisesRegex(ValueError, "root evidence"):
            build_binary64_layer_lock(
                checkpoint,
                selection=self.selection,
                leaf_mechanism_ids={self.leaf.leaf_id: self.leaf.mechanism_id},
                auxiliary_evidence_manifest=manifest,
            )

    def test_horizon_route_locks_its_immutable_binary64_source_record(self) -> None:
        """Break caught: a BF80 horizon source is mistaken for an exterior stage."""

        plan = build_campaign_plan(
            policy=NumericalPolicy(),
            backend_identity=VettedNativeDeterminantKernel.identity,
            precision_capabilities=PrecisionCapabilities((64, 80)),
        )
        leaf = next(
            candidate
            for candidate in plan.leaves
            if candidate.mechanism_id == "horizon-admittance"
        )
        selected = build_campaign_selection(
            plan, role=leaf.role, leaf_ids=(leaf.leaf_id,)
        )
        recovery = RecoverySelection(
            campaign_id=plan.campaign_id,
            selection_id=selected.selection_id,
            ordered_leaf_ids=(leaf.leaf_id,),
            roles={leaf.leaf_id: leaf.role},
            scientific_identities={
                leaf.leaf_id: scientific_computation_identity_sha256(plan, leaf)
            },
        )
        stage_content = {
            "schema": "windows-solver.test-horizon-stage/1",
            "operation_identity": "binary64-horizon-production/v3",
        }
        stage = {**stage_content, "stage_sha256": _sha256(stage_content)}
        record_content = {
            "schema": "windows-solver.test-horizon-record/1",
            "leaf_id": leaf.leaf_id,
            "state": "UNRESOLVED",
            "stages": [stage],
        }
        record = {**record_content, "record_sha256": _sha256(record_content)}
        checkpoint = add_numerical_record(
            empty_schema11_checkpoint(plan.campaign_id, selected.selection_id), record
        )
        checkpoint = record_survey_disposition(
            checkpoint,
            survey_pass=SurveyPass.BINARY64,
            leaf_id=leaf.leaf_id,
            disposition=SurveyDisposition.PROMOTION_PENDING_RESPONSE,
            result_record_sha256=str(record["record_sha256"]),
            operation_identity="binary64-horizon-production/v3",
            precision_tiers=("binary64",),
            reason_code="ROOT_UNCERTAINTY_EVIDENCE_UNAVAILABLE",
            sample_count=0,
            sample_limit=0,
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
            reason_code="ROOT_UNCERTAINTY_EVIDENCE_UNAVAILABLE",
            minimum_requested_tier="BF80",
            scientific_computation_identity=recovery.scientific_identities[
                leaf.leaf_id
            ],
            source_record_sha256=str(record["record_sha256"]),
            source_stage_sha256=str(stage["stage_sha256"]),
            source_root_seal_sha256="d" * 64,
            source_binary64_disposition_receipt_sha256=str(disposition_receipt),
        )
        lock = build_binary64_layer_lock(
            checkpoint,
            selection=recovery,
            leaf_mechanism_ids={leaf.leaf_id: leaf.mechanism_id},
            auxiliary_evidence_manifest=(
                {
                    "logical_key": {
                        "kind": "root-evidence",
                        "root_seal_sha256": "d" * 64,
                    },
                    "object_schema": "windows-solver.test-root-evidence/1",
                    "object_sha256": "d" * 64,
                    "store_identity": "test-root-evidence-store",
                },
            ),
        )

        self.assertEqual({"EXTERIOR_BF40": 0, "HORIZON_BF80": 1}, lock["route_counts"])
        promoted_evidence = record_evidence(
            checkpoint,
            leaf_id=leaf.leaf_id,
            central_record_sha256=str(record["record_sha256"]),
            central_stage_sha256=str(stage["stage_sha256"]),
            evidence_level="SCREENED",
            receipts=({"schema": "windows-solver.test-promoted-evidence/1"},),
        )

        self.assertEqual(lock, assert_binary64_layer_unchanged(
            lock,
            promoted_evidence,
            selection=recovery,
            leaf_mechanism_ids={leaf.leaf_id: leaf.mechanism_id},
            auxiliary_evidence_manifest=(
                {
                    "logical_key": {
                        "kind": "root-evidence",
                        "root_seal_sha256": "d" * 64,
                    },
                    "object_schema": "windows-solver.test-root-evidence/1",
                    "object_sha256": "d" * 64,
                    "store_identity": "test-root-evidence-store",
                },
            ),
        ))

    def test_binary64_layer_lock_path_is_a_deterministic_sidecar(self) -> None:
        """Break caught: callers reproduce or vary the lock suffix."""

        self.assertEqual(
            Path("checkpoint.json.binary64-lock.json"),
            binary64_layer_lock_path(Path("checkpoint.json")),
        )

    def test_lock_sidecar_round_trips_canonical_receipt_bytes(self) -> None:
        """Break caught: lock I/O changes or weakens the receipt payload."""

        checkpoint, stage = self._checkpoint()
        lock = self._lock(checkpoint, stage)
        with TemporaryDirectory() as directory:
            path = Path(directory) / "checkpoint.json.binary64-lock.json"
            write_binary64_layer_lock(path, lock)

            self.assertEqual(canonical_json_bytes(lock), path.read_bytes())
            self.assertEqual(lock, load_binary64_layer_lock(path))

    def test_locking_and_promoted_commands_require_the_shared_sidecar(self) -> None:
        """Break caught: the promoted path can bypass the binary64 receipt."""

        parser = build_parser()
        lock = parser.parse_args([
            "campaign-lock-binary64",
            "selection.json",
            "--checkpoint",
            "checkpoint.json",
        ])
        promoted = parser.parse_args([
            "campaign-survey-promoted",
            "selection.json",
            "--checkpoint",
            "checkpoint.json",
            "--binary64-lock",
            "checkpoint.json.binary64-lock.json",
        ])
        validation = parser.parse_args([
            "campaign-schema11-validate",
            "selection.json",
            "--checkpoint",
            "checkpoint.json",
            "--pass",
            "promoted",
            "--binary64-lock",
            "checkpoint.json.binary64-lock.json",
        ])

        self.assertEqual("campaign-lock-binary64", lock.command)
        self.assertIsNone(lock.output)
        self.assertEqual(Path("checkpoint.json.binary64-lock.json"), promoted.binary64_lock)
        self.assertEqual(Path("checkpoint.json.binary64-lock.json"), validation.binary64_lock)
        with self.assertRaises(ValueError):
            parser.parse_args([
                "campaign-survey-promoted",
                "selection.json",
                "--checkpoint",
                "checkpoint.json",
            ])


if __name__ == "__main__":
    unittest.main()
