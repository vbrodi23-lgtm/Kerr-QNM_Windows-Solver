from __future__ import annotations

import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from windows_solver.binary64_layer_lock import (
    CANONICAL_BACKGROUND_STORE_IDENTITY,
    ROOT_EVIDENCE_STORE_IDENTITY,
    Layer1Guard,
    build_binary64_layer_lock,
    project_binary64_layer,
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
from windows_solver.campaign_survey import (
    AuthenticatedRootSeal,
    PromotedPassOutcome,
    run_promoted_survey,
)
from windows_solver.contracts import canonical_json_bytes
from windows_solver.response_batches import (
    PrecisionCapabilities,
    build_campaign_plan,
    build_campaign_selection,
    scientific_computation_identity_sha256,
)
from windows_solver.response_engine import (
    BINARY64_HORIZON_OPERATION_V3,
    EXTERIOR_PROVISIONAL_REUSE_RECEIPT_SCHEMA,
    NumericalPolicy,
    VettedNativeDeterminantKernel,
    build_exterior_background_reuse_key,
)
from windows_solver.reviewed_determinant_error_issuance import (
    require_locked_bf40_determinant_error_issuance_authority,
)

from tests.test_promoted_survey_scheduler import _Backend, _record


def _sha256(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _stage(content: dict[str, object]) -> dict[str, object]:
    return {**content, "stage_sha256": _sha256(content)}


class PR73CalculateOnlyProductionShapeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.plan = build_campaign_plan(
            policy=NumericalPolicy(),
            backend_identity=VettedNativeDeterminantKernel.identity,
            precision_capabilities=PrecisionCapabilities((64, 80)),
        )
        selected = build_campaign_selection(cls.plan, role="all")
        leaves = {leaf.leaf_id: leaf for leaf in cls.plan.leaves}
        cls.selection = RecoverySelection(
            campaign_id=cls.plan.campaign_id,
            selection_id=selected.selection_id,
            ordered_leaf_ids=tuple(selected.leaf_ids),
            roles={leaf_id: leaves[leaf_id].role for leaf_id in selected.leaf_ids},
            scientific_identities={
                leaf_id: scientific_computation_identity_sha256(
                    cls.plan, leaves[leaf_id]
                )
                for leaf_id in selected.leaf_ids
            },
        )
        cls.leaf_mechanism_ids = {
            leaf.leaf_id: leaf.mechanism_id for leaf in cls.plan.leaves
        }

    def _layer1_checkpoint(self):
        checkpoint = empty_schema11_checkpoint(
            self.selection.campaign_id, self.selection.selection_id
        )
        leaves = {leaf.leaf_id: leaf for leaf in self.plan.leaves}
        exterior_reuse_groups: set[str] = set()
        for leaf_id in self.selection.ordered_leaf_ids:
            leaf = leaves[leaf_id]
            scientific_identity = self.selection.scientific_identities[leaf_id]
            root_seal_sha256 = _sha256({
                "root_identity": leaf.job.root.identity_sha256
            })
            if leaf.mechanism_id == "horizon-admittance":
                operation = BINARY64_HORIZON_OPERATION_V3
                reason_code = "ROOT_UNCERTAINTY_EVIDENCE_UNAVAILABLE"
                minimum_tier = "BF80"
                raw_sample_count = 0
                stage = _stage({
                    "schema": "windows-solver.test-binary64-horizon-stage/1",
                    "operation_identity": operation,
                    "leaf_id": leaf_id,
                    "precision_tier": "binary64",
                    "numerical_state": "REVIEW_PENDING",
                })
            else:
                operation = "binary64-fixed-root-provisional/v1"
                reason_code = "DETERMINANT_ERROR_EVIDENCE_UNAVAILABLE"
                minimum_tier = "BF40"
                reuse_key = build_exterior_background_reuse_key(
                    leaf.job,
                    root_seal_sha256=root_seal_sha256,
                    fixed_root=leaf.job.root.omega,
                ).to_mapping()
                reuse_group_sha256 = _sha256(reuse_key)
                raw_sample_count = (
                    4 if reuse_group_sha256 in exterior_reuse_groups else 9
                )
                exterior_reuse_groups.add(reuse_group_sha256)
                stage = _stage({
                    "schema": "windows-solver.test-binary64-provisional/1",
                    "operation_identity": operation,
                    "leaf_id": leaf_id,
                    "scientific_computation_identity": scientific_identity,
                    "root_seal_sha256": root_seal_sha256,
                    "mechanism_id": leaf.mechanism_id,
                    "raw_sample_count": raw_sample_count,
                    "combined_sample_count": 9,
                    "canonical_background": {
                        "schema": "windows-solver.test-canonical-background/1",
                        "reuse_key": reuse_key,
                    },
                })
            checkpoint = record_survey_disposition(
                checkpoint,
                survey_pass=SurveyPass.BINARY64,
                leaf_id=leaf_id,
                disposition=SurveyDisposition.PROMOTION_PENDING_RESPONSE,
                operation_identity=operation,
                precision_tiers=("binary64",),
                reason_code=reason_code,
                sample_count=raw_sample_count,
                sample_limit=9 if minimum_tier == "BF40" else 0,
                root_read_count=0,
                root_read_limit=0,
                worker_launch_count=0,
                worker_launch_limit=0,
                tier_timing=(),
                session_fragments=(),
            )
            receipt_sha256 = checkpoint["survey_pass_ledger"]["binary64"][
                leaf_id
            ]["disposition_receipt_sha256"]
            checkpoint = append_promotion(
                checkpoint,
                leaf_id=leaf_id,
                queue_kind=PromotionQueueKind.RESPONSE,
                reason_code=reason_code,
                minimum_requested_tier=minimum_tier,
                scientific_computation_identity=scientific_identity,
                source_stage_sha256=str(stage["stage_sha256"]),
                source_root_seal_sha256=root_seal_sha256,
                provisional_stage=stage,
                provisional_stage_sha256=str(stage["stage_sha256"]),
                provisional_operation_identity=operation,
                source_binary64_disposition_receipt_sha256=str(receipt_sha256),
            )
        self.assertEqual(48, len(exterior_reuse_groups))
        return checkpoint

    @staticmethod
    def _promoted_horizon_outcome(leaf) -> PromotedPassOutcome:
        record, stage_sha256 = _record(leaf.leaf_id, 80)
        record_stage = record["stages"][0]
        record_stage["precision_tier"] = "BF80"
        record_stage["component_result"] = {
            "result": {
                "schema": "windows-solver.test-promoted-horizon-batch/1",
                "precision_tier": "BF80",
                "leaf_id": leaf.leaf_id,
            }
        }
        record_stage["stage_sha256"] = _sha256({
            key: value
            for key, value in record_stage.items()
            if key != "stage_sha256"
        })
        record["record_sha256"] = _sha256({
            key: value for key, value in record.items() if key != "record_sha256"
        })
        return PromotedPassOutcome(
            disposition=SurveyDisposition.COMPLETED,
            reason_code="BOUNDED_PROMOTED_HORIZON_RESPONSE",
            precision_tiers=("BF80",),
            operation_identity="promoted-horizon-production/v2",
            record=record,
            stage_sha256=str(record_stage["stage_sha256"]),
            sample_count=1,
            sample_limit=1,
            root_read_count=1,
            root_read_limit=1,
            worker_launch_count=1,
            worker_launch_limit=1,
            evidence_receipts=({
                "schema": "windows-solver.test-promoted-horizon-raw-batch/1",
                "batch": {
                    "schema": "windows-solver.test-promoted-horizon-batch/1",
                    "precision_tier": "BF80",
                    "leaf_id": leaf.leaf_id,
                    "samples": [],
                },
            },),
        )

    @staticmethod
    def _auxiliary_manifest(checkpoint):
        entries: dict[bytes, dict[str, object]] = {}
        for queue_entry in checkpoint["promotion_queue"]["entries"]:
            root_sha256 = str(queue_entry["source_root_seal_sha256"])
            root_entry = {
                "logical_key": {
                    "kind": "root-evidence",
                    "root_seal_sha256": root_sha256,
                },
                "object_schema": "windows-solver.test-root-evidence/1",
                "object_sha256": root_sha256,
                "store_identity": ROOT_EVIDENCE_STORE_IDENTITY,
            }
            entries[canonical_json_bytes(root_entry["logical_key"])] = root_entry
            provisional = queue_entry["provisional_stage"]
            if provisional.get("operation_identity") != (
                "binary64-fixed-root-provisional/v1"
            ):
                continue
            background = provisional["canonical_background"]
            background_sha256 = _sha256(background)
            background_entry = {
                "logical_key": {
                    "kind": "canonical-background",
                    "background_sha256": background_sha256,
                },
                "object_schema": str(background["schema"]),
                "object_sha256": background_sha256,
                "store_identity": CANONICAL_BACKGROUND_STORE_IDENTITY,
            }
            entries[
                canonical_json_bytes(background_entry["logical_key"])
            ] = background_entry
        return tuple(entries.values())

    def test_official_212_leaf_calculate_only_shape_is_durable_and_resumable(self):
        self.assertEqual(212, len(self.selection.ordered_leaf_ids))
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            durable_state: dict[str, object] = {}

            def retain_in_memory(_path, value):
                durable_state["checkpoint"] = value

            def reload_in_memory(_path):
                return durable_state["checkpoint"]

            checkpoint = self._layer1_checkpoint()
            manifest = self._auxiliary_manifest(checkpoint)
            lock = build_binary64_layer_lock(
                checkpoint,
                selection=self.selection,
                leaf_mechanism_ids=self.leaf_mechanism_ids,
                auxiliary_evidence_manifest=manifest,
            )
            guard = Layer1Guard.from_authenticated_lock(
                lock,
                checkpoint,
                selection=self.selection,
                leaf_mechanism_ids=self.leaf_mechanism_ids,
                auxiliary_evidence_manifest=manifest,
            )
            layer1_before = project_binary64_layer(
                checkpoint,
                selection=self.selection,
                leaf_mechanism_ids=self.leaf_mechanism_ids,
                auxiliary_evidence_manifest=manifest,
            )
            preflights = {
                ordinal: require_locked_bf40_determinant_error_issuance_authority(
                    route=route.route
                )
                for ordinal, route in guard.locked_routes_by_ordinal.items()
            }
            promoted_calls: list[int] = []
            horizon_calls: list[str] = []
            terminal_commits: list[str] = []
            binary64_predecessor_evaluations_consumed = 0
            guard_phase_counts = {
                "pre_write": 0,
                "post_write": 0,
                "post_callback": 0,
            }

            class ShapeGuard:
                """Keep locked-route binding while focused tests cover each guard phase."""

                def pre_write(self, _checkpoint):
                    guard_phase_counts["pre_write"] += 1

                def post_write(self, _checkpoint):
                    guard_phase_counts["post_write"] += 1

                def post_callback(self, _checkpoint):
                    guard_phase_counts["post_callback"] += 1

                def assert_unchanged(self, _checkpoint):
                    guard_phase_counts.setdefault("assert_unchanged", 0)
                    guard_phase_counts["assert_unchanged"] += 1

            def horizon_runner(leaf):
                horizon_calls.append(leaf.leaf_id)
                return self._promoted_horizon_outcome(leaf)

            def consume_predecessor(stage, **_bindings):
                nonlocal binary64_predecessor_evaluations_consumed
                raw_sample_count = int(stage["raw_sample_count"])
                binary64_predecessor_evaluations_consumed += raw_sample_count
                content = {
                    "schema": EXTERIOR_PROVISIONAL_REUSE_RECEIPT_SCHEMA,
                    "status": "COMPATIBLE",
                    "provisional_stage_sha256": stage["stage_sha256"],
                    "target_precision_tier": "BF40",
                    "consumed_binary64_evaluation_count": raw_sample_count,
                }
                return {**content, "receipt_sha256": _sha256(content)}

            def compact_retained_stage(**arguments):
                outcome = arguments["outcome"]
                queue_entry = arguments["queue_entry"]
                raw_batch_digests = [
                    _sha256(receipt["batch"])
                    for receipt in outcome.evidence_receipts
                    if isinstance(receipt, dict)
                    and isinstance(receipt.get("batch"), dict)
                ]
                material = {
                    "schema": "windows-solver.promoted-calculation-stage/1",
                    "queue_ordinal": arguments["queue_ordinal"],
                    "leaf_id": queue_entry["leaf_id"],
                    "scientific_computation_identity": arguments[
                        "scientific_computation_identity"
                    ],
                    "route": arguments["route"],
                    "execution_mode": arguments["preflight"].mode.value,
                    "admission_state": "AWAITING_ADMISSION",
                    "layer1_lock_receipt_sha256": arguments[
                        "layer1_lock_receipt_sha256"
                    ],
                    "source_fingerprint_sha256": queue_entry[
                        "source_fingerprint_sha256"
                    ],
                    "predecessor_stage_sha256": queue_entry[
                        "source_stage_sha256"
                    ],
                    "source_root_seal_sha256": queue_entry[
                        "source_root_seal_sha256"
                    ],
                    "calibration_receipt_sha256": arguments[
                        "preflight"
                    ].calibration_receipt_sha256,
                    "precision_tiers": list(outcome.precision_tiers),
                    "raw_promoted_batches": [{
                        "schema": "windows-solver.test-retained-batch-pointer/1",
                        "precision_tier": outcome.precision_tiers[-1],
                        "batch_sha256s": raw_batch_digests,
                    }],
                    "current_run_disagreement_terms": [],
                    "sample_count": outcome.sample_count,
                    "root_read_count": outcome.root_read_count,
                    "worker_launch_count": outcome.worker_launch_count,
                }
                return {**material, "stage_sha256": _sha256(material)}

            with patch(
                "windows_solver.campaign_survey._atomic_json",
                side_effect=retain_in_memory,
            ), patch(
                "windows_solver.campaign_survey._load_durable_schema11_checkpoint",
                side_effect=reload_in_memory,
            ), patch(
                "windows_solver.campaign_survey.consume_authenticated_binary64_provisional_predecessor",
                side_effect=consume_predecessor,
            ), patch(
                "windows_solver.campaign_survey._retained_promoted_stage",
                side_effect=compact_retained_stage,
            ):
                promoted = run_promoted_survey(
                    self.plan,
                    self.selection,
                    checkpoint,
                    checkpoint_path=root / "checkpoint.json",
                    root_seal_lookup=lambda leaf, entry: AuthenticatedRootSeal(
                        leaf.job.root.omega,
                        leaf.job.root.branch_id,
                        str(entry["source_root_seal_sha256"]),
                    ),
                    root_seal_publish=lambda *_args: self.fail(
                        "fixed-root response promotion must not publish a root"
                    ),
                    backend_factory=lambda leaf, digits: _Backend(
                        leaf, digits, False, promoted_calls
                    ),
                    primary_root_runner=lambda *_args: self.fail(
                        "official fixture contains no root-promotion route"
                    ),
                    horizon_runner=horizon_runner,
                    produced_record_builder=(
                        lambda leaf, _batch, _screening, digits: _record(
                            leaf.leaf_id, digits
                        )
                    ),
                    layer1_guard=ShapeGuard(),
                    locked_routes_by_ordinal=guard.locked_routes_by_ordinal,
                    promoted_preflights_by_ordinal=preflights,
                    layer1_lock_receipt_sha256=str(lock["receipt_sha256"]),
                    terminal_record_committed=lambda leaf, _record: (
                        terminal_commits.append(leaf.leaf_id)
                    ),
                )

            layer1_after = project_binary64_layer(
                promoted.checkpoint,
                selection=self.selection,
                leaf_mechanism_ids=self.leaf_mechanism_ids,
                auxiliary_evidence_manifest=manifest,
            )
            self.assertEqual(layer1_before, layer1_after)
            self.assertEqual(
                {"EXTERIOR_BF40": 172, "HORIZON_BF80": 40},
                lock["route_counts"],
            )
            self.assertEqual(
                928,
                lock["retained_sample_counts"][
                    "retained_binary64_determinant_evaluations"
                ],
            )
            self.assertEqual(
                928, binary64_predecessor_evaluations_consumed
            )
            # The 48 canonical groups acquire five shared samples before
            # their four mechanisms; the other 124 routes reuse them.
            self.assertEqual(220, len(promoted_calls))
            self.assertEqual([40] * 220, promoted_calls)
            self.assertEqual(0, sum(digits == 64 for digits in promoted_calls))
            self.assertEqual(40, len(horizon_calls))
            self.assertEqual(212, promoted.review_pending_count)
            self.assertEqual(212, promoted.locked_route_count)
            self.assertEqual(172, promoted.exterior_bf40_route_count)
            self.assertEqual(40, promoted.horizon_bf80_route_count)
            self.assertEqual(172, promoted.exterior_bf40_executed_count)
            self.assertEqual(40, promoted.horizon_bf80_executed_count)
            self.assertEqual(928, promoted.binary64_predecessor_evaluation_count)
            self.assertEqual(0, promoted.binary64_recomputed_evaluation_count)
            self.assertEqual(48, promoted.promoted_background_acquired_count)
            self.assertEqual(124, promoted.promoted_background_reused_count)
            self.assertEqual(212, promoted.calculated_awaiting_admission_count)
            self.assertEqual(0, promoted.admitted_count)
            self.assertEqual(0, promoted.screened_count)
            self.assertEqual(0, promoted.terminal_publication_count)
            self.assertEqual(0, promoted.policy_blocked_count)
            self.assertEqual(0, promoted.completed_count)
            self.assertEqual([], terminal_commits)
            self.assertEqual({}, promoted.checkpoint["evidence_ledger"])
            self.assertEqual([], promoted.checkpoint["records"])
            self.assertEqual(212, len(promoted.checkpoint["promoted_stage_ledger"]))
            self.assertEqual(
                172, len(promoted.checkpoint["promoted_background_ledger"])
            )
            self.assertEqual(40, len(promoted.checkpoint["promoted_root_ledger"]))
            background_statuses = [
                entry[leaf_id]["payload"]["background_receipts"][0]["status"]
                for entry in promoted.checkpoint[
                    "promoted_background_ledger"
                ].values()
                for leaf_id in entry
            ]
            self.assertEqual(48, background_statuses.count("ACQUIRED"))
            self.assertEqual(124, background_statuses.count("REUSED"))
            self.assertGreater(guard_phase_counts["pre_write"], 212)
            self.assertEqual(
                guard_phase_counts["pre_write"],
                guard_phase_counts["post_write"],
            )
            self.assertEqual(
                guard_phase_counts["pre_write"],
                guard_phase_counts["post_callback"],
            )
            self.assertTrue(all(
                entry["disposition"] == "AWAITING_ADMISSION"
                and isinstance(entry["retained_promoted_stage_sha256"], str)
                for entry in promoted.checkpoint["promotion_queue"]["entries"]
            ))
            self.assertTrue(all(
                ledger[leaf_id]["raw_promoted_batches"]
                and isinstance(
                    ledger[leaf_id]["current_run_disagreement_terms"], list
                )
                for ledger in promoted.checkpoint["promoted_stage_ledger"].values()
                for leaf_id in ledger
            ))
            self.assertEqual(
                {"BF40": 172, "BF80": 40},
                {
                    tier: sum(
                        route.route == expected
                        for route in guard.locked_routes_by_ordinal.values()
                    )
                    for tier, expected in (
                        ("BF40", "EXTERIOR_BF40"),
                        ("BF80", "HORIZON_BF80"),
                    )
                },
            )

            retained_stage_ledger = promoted.checkpoint["promoted_stage_ledger"]
            retained_background_ledger = promoted.checkpoint[
                "promoted_background_ledger"
            ]
            retained_root_ledger = promoted.checkpoint["promoted_root_ledger"]
            with patch(
                "windows_solver.campaign_survey._atomic_json",
                side_effect=retain_in_memory,
            ), patch(
                "windows_solver.campaign_survey._load_durable_schema11_checkpoint",
                side_effect=reload_in_memory,
            ):
                resumed = run_promoted_survey(
                    self.plan,
                    self.selection,
                    promoted.checkpoint,
                    checkpoint_path=root / "checkpoint.json",
                    root_seal_lookup=lambda *_args: self.fail(
                        "resume repeated a root lookup"
                    ),
                    root_seal_publish=lambda *_args: self.fail(
                        "resume published a root"
                    ),
                    backend_factory=lambda *_args: self.fail(
                        "resume repeated promoted numerical work"
                    ),
                    primary_root_runner=lambda *_args: self.fail(
                        "resume repeated a root solve"
                    ),
                    horizon_runner=lambda *_args: self.fail(
                        "resume repeated BF80 horizon work"
                    ),
                    produced_record_builder=lambda *_args: self.fail(
                        "resume rebuilt a record"
                    ),
                    layer1_guard=ShapeGuard(),
                    locked_routes_by_ordinal=guard.locked_routes_by_ordinal,
                    promoted_preflights_by_ordinal=preflights,
                    layer1_lock_receipt_sha256=str(lock["receipt_sha256"]),
                )
            self.assertEqual(212, resumed.skipped_count)
            self.assertTrue(resumed.pass_exhausted)
            self.assertEqual(
                retained_stage_ledger,
                resumed.checkpoint["promoted_stage_ledger"],
            )
            self.assertEqual(
                retained_background_ledger,
                resumed.checkpoint["promoted_background_ledger"],
            )
            self.assertEqual(
                retained_root_ledger,
                resumed.checkpoint["promoted_root_ledger"],
            )
            guard.assert_unchanged(resumed.checkpoint)


if __name__ == "__main__":
    unittest.main()
