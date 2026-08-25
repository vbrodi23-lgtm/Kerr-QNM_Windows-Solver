from __future__ import annotations

import hashlib
import json
import math
import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import windows_solver.campaign_checkpoint_migration as migration_module

from tests import test_linear_response_precision as precision_tests
from tests.fixtures import frozen_pr58_native_backend_identity
from windows_solver import julia_response_backend as julia_backend
from windows_solver import response_batches as batch_module
from windows_solver.campaign_checkpoint_migration import (
    CAMPAIGN_MIGRATION_SCHEMA,
    migrate_campaign_checkpoint,
)
from windows_solver.contracts import canonical_json_bytes
from windows_solver.response_batches import (
    CAMPAIGN_CHECKPOINT_SCHEMA_VERSION,
    validate_campaign_checkpoint,
)
from windows_solver.response_engine import (
    HISTORICAL_PROMOTED_ROOT_READOUT_POLICY,
    NumericalPolicy,
    regularised_gsn_precision_policy,
)


_OLD_ENDPOINT_POLICY = "adaptive-horizon-endpoint-recovery/v1"
_NEW_ENDPOINT_POLICY = "adaptive-horizon-endpoint-recovery/v2"
_ORIGIN_SCHEMA7_PRECISION_CONTRACT_SHA256 = (
    "3f6364f6fc28eebeeb788af20524f8ada3c97f23e41fb68f4ead3da365368dcb"
)
_ORIGIN_CAMPAIGN_ID = (
    "b-prime-campaign-0e93d89e98650d1e2db109d41ca0b68919067f6627ccd320fddc1e83f4720024"
)
_ORIGIN_CAMPAIGN_BINDINGS = {
    "schema_version": 2,
    "ordered_leaf_set_sha256": (
        "b84cbba359285dae8f283d11dff1c5ff63f4e7a03c5b77f5f0ebc09703016599"
    ),
    "root_set_sha256": (
        "477a3bcb8d629ba890bbb320723e365743685bdb89f23382d5ce22fbbbcc0a3f"
    ),
    "policy_sha256": (
        "2d7cee336c6126a11bccd652ee35e73de60837e9418476849b9026cd27bf6171"
    ),
    "engine_source_sha256": (
        "6bc9938b91d7de59669574b89b58a6bec8335d48f8b0678815350b0fba977be4"
    ),
    "campaign_source_sha256": (
        "504133318d896d436f92399dd8ea95424bbac3889fa8043ba3ed89bfab65d968"
    ),
    "backend_identity_sha256": (
        "035f123f04d02079c6e7d7bed5255069c6152d53be266185b303af8c48c36f5c"
    ),
    "precision_capabilities_sha256": (
        "7b4eda35c340dc53cf8a11bd5c657cddb1b04faa55a991ea874a13be6ee09b78"
    ),
    "precision_factory_identity": {
        "factory": (
            "windows_solver.response_batches:"
            "NativeCampaignStageBackend.from_selection"
        ),
        "module_sha256": (
            "504133318d896d436f92399dd8ea95424bbac3889fa8043ba3ed89bfab65d968"
        ),
    },
    "cohort_set_sha256": (
        "ec538cf3ae5a11b4a16808e779a5721dc713ea9e1c67e6d94bdd248815d5f421"
    ),
}


class Pr59CheckpointCompatibilityTests(unittest.TestCase):
    def test_pr58_checkpoint_and_schema7_bindings_remain_byte_stable(self):
        """Freeze current and historical identities used by Leaf 42 resume."""

        plan = batch_module.build_campaign_plan(
            policy=NumericalPolicy(),
            backend_identity=frozen_pr58_native_backend_identity(),
            precision_capabilities=batch_module.PrecisionCapabilities(
                (64, 80, 120)
            ),
        )
        selection = batch_module.build_campaign_selection(plan, role="all")

        self.assertEqual(
            plan.campaign_id,
            "b-prime-campaign-5bed3823a9c565d29b79292702a50b98dad1823b58cfb0ad2760ec3dcc5b7b8a",
        )
        self.assertEqual(
            plan.policy.identity_sha256,
            "2d7cee336c6126a11bccd652ee35e73de60837e9418476849b9026cd27bf6171",
        )
        self.assertEqual(
            plan.precision_factory_identity.module_sha256,
            "f9cf83ce874f0c93086aa79a29dc76ab043ce98d4e02df3558ccb49340beeb50",
        )
        self.assertEqual(
            selection.selection_id,
            "campaign-selection-f2b224d967cf66c80ca59e8029680e47ac440410f2e0b8fe56e2680a6892d4c0",
        )
        self.assertEqual(
            batch_module._checkpoint_precision_contract_sha256(
                CAMPAIGN_CHECKPOINT_SCHEMA_VERSION
            ),
            "6aed848e453a4a4b81331e857982447631d152a43521b9397dec250a42e5cb7b",
        )
        checkpoint_bindings = batch_module._checkpoint_bindings(
            plan, selection
        )
        self.assertEqual(
            checkpoint_bindings["selection_jobs_sha256"],
            "32e39a65e273635434026133fca6f77fb137c816df5c6949b266d9734c9ac842",
        )
        self.assertEqual(
            hashlib.sha256(
                canonical_json_bytes(
                    checkpoint_bindings["campaign_bindings"]
                )
            ).hexdigest(),
            "5bed3823a9c565d29b79292702a50b98dad1823b58cfb0ad2760ec3dcc5b7b8a",
        )
        self.assertEqual(
            hashlib.sha256(
                canonical_json_bytes(checkpoint_bindings)
            ).hexdigest(),
            "d4b3fc99e0bcfc7557696d76104aebce1e55d6dba85334bb9eb2bd284cc81162",
        )

        expected_schema7_digests = {
            "b-prime-leaf-28b8e2f139fae4ebbb839320057a127429f7a01a3cc2cac60b526815ad0e7252": (
                "95fa2510c95393a691e4301eead301ff78cdde19a1498bca4dea76f9a9a5d32a"
            ),
            "b-prime-leaf-5a27a5fdc15f95de33d6773b16f89a9f594fe5ffd018f9ee94bbab91949fd653": (
                "ed87c8cdef4156b6970f069f2a13061cf8e6b8a3e45092480ea7eb1cfe494794"
            ),
        }
        leaves = {leaf.leaf_id: leaf for leaf in plan.leaves}
        for leaf_id, expected_digest in expected_schema7_digests.items():
            with self.subTest(leaf_id=leaf_id):
                request = batch_module._schema7_julia_root_request(
                    leaves[leaf_id].job,
                    80,
                    0,
                    0.0j,
                    None,
                    None,
                )
                self.assertEqual(
                    request["policy"]["determinant_error_safety_factor"],
                    "64",
                )
                self.assertEqual(
                    hashlib.sha256(canonical_json_bytes(request)).hexdigest(),
                    expected_digest,
                )


def _origin_schema7_request(leaf, request):
    regularised = dict(regularised_gsn_precision_policy(leaf.job.mechanism_id))
    regularised["promoted_root_readout_policy"] = (
        HISTORICAL_PROMOTED_ROOT_READOUT_POLICY
    )
    controls = julia_backend.promoted_precision_numerical_controls()["80"][
        "base"
    ]
    historical = dict(request)
    historical.pop("semantic_precision_tier", None)
    # Real schema-7 checkpoints predate the PR69 raw-determinant contract
    # top-level fields. The fixture generates the base binding through the
    # current _request() constructor, so strip the post-schema-7 additions
    # to model an actual origin-era wire binding.
    for field in (
        "diagnostic_model_identity",
        "required_raw_determinant_roles",
        "required_raw_determinant_count",
    ):
        historical.pop(field, None)
    historical["policy"] = {
        "readout_radius": format(leaf.job.policy.readout_radius, ".17g"),
        **controls,
        **julia_backend.horizon_geometry_controls(),
        "determinant_error_safety_factor": "64",
        **regularised,
        "endpoint_series_order": leaf.job.policy.endpoint_series_order,
        "support_subinterval_count": leaf.job.policy.support_subinterval_count,
        "angular_pad": 18,
        "rho_in": "-5000",
        "rho_out": "5000",
        "branch_enclosure_radius_abs": format(
            julia_backend._mode_specific_branch_enclosure_radius(leaf.job),
            ".17g",
        ),
        "max_newton_iterations": 16,
    }
    self_bits = math.ceil(80 * math.log2(10)) + 32
    assert historical["working_precision_bits"] == self_bits
    return historical


def _bind_origin_schema7(mapping):
    bindings = mapping["bindings"]
    selection = copy.deepcopy(bindings["selection"])
    selection_material = {
        "campaign_id": _ORIGIN_CAMPAIGN_ID,
        "role": selection["role"],
        "leaf_ids": selection["leaf_ids"],
        "cohort_ids": selection["cohort_ids"],
    }
    selection["selection_id"] = "campaign-selection-" + hashlib.sha256(
        canonical_json_bytes(selection_material)
    ).hexdigest()
    bindings.update({
        "campaign_id": _ORIGIN_CAMPAIGN_ID,
        "campaign_bindings": copy.deepcopy(_ORIGIN_CAMPAIGN_BINDINGS),
        "selection": selection,
        "precision_factory_identity": copy.deepcopy(
            _ORIGIN_CAMPAIGN_BINDINGS["precision_factory_identity"]
        ),
        "precision_contract_sha256": (
            _ORIGIN_SCHEMA7_PRECISION_CONTRACT_SHA256
        ),
    })
    for record in mapping["records"]:
        for stage in record["stages"]:
            stage["runner_provenance"]["precision_factory_identity"] = (
                copy.deepcopy(
                    _ORIGIN_CAMPAIGN_BINDINGS["precision_factory_identity"]
                )
            )
    # Schema 7 predates the distinct attempted-rung and typed limitation
    # fields. Keep its frozen failure receipt shape rather than relabelling
    # historical evidence with the current schema.
    for attempt in mapping.get("attempts", []):
        receipt = attempt.get("failure_receipt")
        failure = receipt.get("failure") if isinstance(receipt, dict) else None
        diagnostics = (
            failure.get("diagnostics") if isinstance(failure, dict) else None
        )
        evidence = (
            diagnostics.get("recovery_evidence")
            if isinstance(diagnostics, dict)
            else None
        )
        if not isinstance(evidence, dict):
            continue
        for candidate in (
            evidence.get("selected_pair", [])
            + evidence.get("rejected_candidates", [])
        ):
            attempted = candidate.pop("attempted_endpoint_order", None)
            if attempted is not None:
                candidate["endpoint_order"] = attempted
                candidate["ingoing_best_prefix_order"] = min(
                    candidate["ingoing_best_prefix_order"], attempted
                )
                candidate["outgoing_best_prefix_order"] = min(
                    candidate["outgoing_best_prefix_order"], attempted
                )
            candidate.pop("limitation", None)
            candidate.pop("precision_limited", None)
            candidate.pop("limitation_conditioning", None)


def _stopped_schema7_checkpoint():
    fixture = precision_tests.PromotedResourceContainmentTests()
    run = fixture._run_with_failure(
        julia_backend.JuliaNumericalControlError,
        "HORIZON_GEOMETRY_EXHAUSTED",
    )
    temporary, root, plan, _, _, _, _, _, _ = run
    mapping = json.loads((root / "checkpoint.json").read_bytes())
    mapping["schema_version"] = 7
    _bind_origin_schema7(mapping)
    leaf_by_id = {leaf.leaf_id: leaf for leaf in plan.leaves}
    attempt = mapping["attempts"][0]
    failure = attempt["failure_receipt"]["failure"]
    historical_request = _origin_schema7_request(
        leaf_by_id[attempt["leaf_id"]], failure["request_binding"]
    )
    failure["request_binding"] = historical_request
    failure["request_sha256"] = hashlib.sha256(
        canonical_json_bytes(historical_request)
    ).hexdigest()
    attempt_material = {
        key: value for key, value in attempt.items() if key != "attempt_sha256"
    }
    attempt["attempt_sha256"] = hashlib.sha256(
        canonical_json_bytes(attempt_material)
    ).hexdigest()
    mapping["attempts_sha256"] = hashlib.sha256(
        canonical_json_bytes(mapping["attempts"])
    ).hexdigest()
    precision_tests.reseal(mapping)
    source = canonical_json_bytes(mapping)
    temporary.cleanup()
    return plan, source


def _origin_schema7_stopped_preflight_checkpoint(
    *,
    retain_missing_precision: bool = False,
    failure_code: str = "INSUFFICIENT_ASYMPTOTIC_PRECISION",
):
    fixture = precision_tests.PromotedResourceContainmentTests()
    run = fixture._run_with_failure(
        julia_backend.JuliaNumericalControlError,
        failure_code,
    )
    temporary, root, plan, _, incident, _, _, _, _ = run
    mapping = json.loads((root / "checkpoint.json").read_bytes())
    mapping["schema_version"] = 7
    mapping["state"] = "PARTIAL"
    _bind_origin_schema7(mapping)
    record = next(
        item for item in mapping["records"] if item["leaf_id"] == incident.leaf_id
    )
    record["state"] = (
        "MISSING_PRECISION" if retain_missing_precision else "IN_PROGRESS"
    )
    record["stages"] = record["stages"][:1]
    record["computed"] = False
    record["missing_precision_digits"] = (
        120 if retain_missing_precision else None
    )
    record["sentinel_comparison"] = None
    leaf_by_id = {leaf.leaf_id: leaf for leaf in plan.leaves}
    attempt = mapping["attempts"][0]
    failure = attempt["failure_receipt"]["failure"]
    historical_request = _origin_schema7_request(
        leaf_by_id[attempt["leaf_id"]], failure["request_binding"]
    )
    failure["request_binding"] = historical_request
    failure["request_sha256"] = hashlib.sha256(
        canonical_json_bytes(historical_request)
    ).hexdigest()
    attempt_material = {
        key: value for key, value in attempt.items() if key != "attempt_sha256"
    }
    attempt["attempt_sha256"] = hashlib.sha256(
        canonical_json_bytes(attempt_material)
    ).hexdigest()
    mapping["attempts_sha256"] = hashlib.sha256(
        canonical_json_bytes(mapping["attempts"])
    ).hexdigest()
    precision_tests.reseal(mapping)
    source = canonical_json_bytes(mapping)
    temporary.cleanup()
    return plan, source


def _origin_schema7_promoted_component_checkpoint():
    fixture = precision_tests.PromotedResourceContainmentTests()
    plan, capabilities, _, _, _ = fixture._plan_and_leaves()
    selected = tuple(
        leaf
        for leaf in plan.leaves
        if leaf.role == "primary"
        and leaf.mechanism_id in {
            "horizon-admittance",
            "exterior-light-ring",
        }
    )[:2]
    if {leaf.mechanism_id for leaf in selected} != {
        "horizon-admittance",
        "exterior-light-ring",
    }:
        selected = (
            next(
                leaf for leaf in plan.leaves
                if leaf.role == "primary"
                and leaf.mechanism_id == "horizon-admittance"
            ),
            next(
                leaf for leaf in plan.leaves
                if leaf.role == "primary"
                and leaf.mechanism_id == "exterior-light-ring"
            ),
        )
        selected = tuple(sorted(
            selected,
            key=lambda leaf: tuple(item.leaf_id for item in plan.leaves).index(
                leaf.leaf_id
            ),
        ))
    selection = batch_module.build_campaign_selection(
        plan,
        role="primary",
        leaf_ids=tuple(leaf.leaf_id for leaf in selected),
    )
    provenance = {
        "precision_factory_identity": (
            plan.precision_factory_identity.to_mapping()
        ),
        "available_precision_digits": list(capabilities.digits),
    }
    records = []
    for leaf in selected:
        binary = batch_module.CampaignStageRecord(
            precision_tests._authenticated_primary_stage(
                leaf, 64, batch_module.ComponentStatus.NOT_CONVERGED
            ),
            provenance,
        )
        promoted_outcome = precision_tests._authenticated_primary_stage(
            leaf,
            80,
            batch_module.ComponentStatus.CONVERGED,
            self_refinement_enclosed=True,
            discrepancy_from_previous_abs=1.0e-9,
            discrepancy_enclosed=True,
        )
        promoted = batch_module.CampaignStageRecord(
            batch_module._stage_with_promotion_decision(
                promoted_outcome,
                batch_module._primary_precision120_decision(
                    promoted_outcome
                ),
            ),
            provenance,
        )
        records.append(batch_module.CampaignLeafRecord(
            leaf_id=leaf.leaf_id,
            role=leaf.role,
            state="PRODUCED",
            stages=(binary, promoted),
        ))
    mapping = batch_module._checkpoint_mapping(
        plan, selection, tuple(records)
    )
    mapping["schema_version"] = 7
    _bind_origin_schema7(mapping)
    precision_tests.reseal(mapping)
    return plan, canonical_json_bytes(mapping)


class CampaignCheckpointMigrationTests(unittest.TestCase):
    def test_schema7_binding_uses_frozen_origin_not_current_platform_plan(self):
        """Historical authentication cannot depend on current float rebuilds."""

        plan, source_bytes = _stopped_schema7_checkpoint()
        drifted_bindings = copy.deepcopy(plan.bindings)
        drifted_bindings["root_set_sha256"] = "0" * 64
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "schema7.json"
            source.write_bytes(source_bytes)
            with patch.object(
                batch_module.CampaignPlan,
                "bindings",
                property(lambda _self: drifted_bindings),
            ):
                _selection, records, attempts, state, version = (
                    batch_module._load_checkpoint_with_attempts(plan, source)
                )

        self.assertEqual(version, 7)
        self.assertEqual(state, "PARTIAL")
        self.assertTrue(records)
        self.assertTrue(attempts)

    def test_invalidated_retry_predecessor_normalizes_missing_precision(self):
        for failure_code in (
            "INSUFFICIENT_ASYMPTOTIC_PRECISION",
            "HORIZON_ARITHMETIC_INADEQUATE",
        ):
            with self.subTest(failure_code=failure_code):
                plan, source_bytes = (
                    _origin_schema7_stopped_preflight_checkpoint(
                        retain_missing_precision=True,
                        failure_code=failure_code,
                    )
                )
                with tempfile.TemporaryDirectory() as temporary:
                    root = Path(temporary)
                    source = root / "missing-schema7.json"
                    destination = root / "schema8.json"
                    source.write_bytes(source_bytes)

                    migrate_campaign_checkpoint(
                        source,
                        destination,
                        plan=plan,
                        expected_source_sha256=hashlib.sha256(
                            source_bytes
                        ).hexdigest(),
                        changed_endpoint_policy_identities={},
                    )

                    migrated = json.loads(destination.read_bytes())
                    validate_campaign_checkpoint(plan, destination)
                    record = migrated["records"][0]
                    self.assertEqual(record["state"], "IN_PROGRESS")
                    self.assertIsNone(record["missing_precision_digits"])
                    self.assertEqual(
                        [stage["digits"] for stage in record["stages"]],
                        [64],
                    )
                    self.assertEqual(migrated["attempts"], [])

    def test_schema7_promoted_component_suffixes_are_invalidated_by_identity(self):
        plan, source_bytes = _origin_schema7_promoted_component_checkpoint()
        historical = json.loads(source_bytes)
        leaf_by_id = {leaf.leaf_id: leaf for leaf in plan.leaves}
        self.assertEqual(
            {
                leaf_by_id[record["leaf_id"]].mechanism_id
                for record in historical["records"]
            },
            {"horizon-admittance", "exterior-light-ring"},
        )
        self.assertTrue(all(
            record["stages"][1]["component_result"]["evidence_kind"]
            == "package-owned-julia-promoted-component-engine"
            for record in historical["records"]
        ))
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "promoted-schema7.json"
            destination = root / "schema8.json"
            source.write_bytes(source_bytes)

            migrate_campaign_checkpoint(
                source,
                destination,
                plan=plan,
                expected_source_sha256=hashlib.sha256(
                    source_bytes
                ).hexdigest(),
                changed_endpoint_policy_identities={},
            )

            migrated = json.loads(destination.read_bytes())
            validate_campaign_checkpoint(plan, destination)
            self.assertEqual(len(migrated["records"]), 2)
            for old, new in zip(historical["records"], migrated["records"]):
                self.assertEqual(len(old["stages"]), 2)
                self.assertEqual(new["stages"], old["stages"][:1])
                self.assertEqual(new["state"], "IN_PROGRESS")
            receipt = json.loads(
                destination.with_name(
                    f"{destination.name}.migration-receipt.json"
                ).read_bytes()
            )
            invalidated = [
                item for item in receipt["invalidated_evidence"]
                if item["evidence_kind"] == "campaign-stage-suffix"
            ]
            self.assertEqual(len(invalidated), 2)
            self.assertEqual(
                {item["reason"] for item in invalidated},
                {"SCHEMA7_PROMOTED_COMPONENT_IDENTITY_CHANGED"},
            )

    def test_origin_schema7_preflight_request_migrates_without_current_budget(self):
        plan, source_bytes = _origin_schema7_stopped_preflight_checkpoint()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "origin-schema7.json"
            destination = root / "schema8.json"
            source.write_bytes(source_bytes)
            before = source.read_bytes()

            migrate_campaign_checkpoint(
                source,
                destination,
                plan=plan,
                expected_source_sha256=hashlib.sha256(before).hexdigest(),
                changed_endpoint_policy_identities={},
            )

            self.assertEqual(source.read_bytes(), before)
            validate_campaign_checkpoint(plan, destination)

    def test_real_stopped_checkpoint_migrates_to_normal_resumable_schema8(self):
        plan, source_bytes = _stopped_schema7_checkpoint()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "stopped-checkpoint.json"
            destination = root / "migrated-checkpoint.json"
            source.write_bytes(source_bytes)
            before = source.read_bytes()
            source_sha256 = hashlib.sha256(before).hexdigest()

            result = migrate_campaign_checkpoint(
                source,
                destination,
                plan=plan,
                expected_source_sha256=source_sha256,
                changed_endpoint_policy_identities={
                    _OLD_ENDPOINT_POLICY: _NEW_ENDPOINT_POLICY
                },
            )

            self.assertEqual(source.read_bytes(), before)
            migrated = json.loads(destination.read_bytes())
            historical = json.loads(before)
            self.assertEqual(
                set(migrated),
                {
                    "schema_version",
                    "state",
                    "bindings",
                    "records",
                    "records_sha256",
                    "attempts",
                    "attempts_sha256",
                    "release_admissible",
                },
            )
            self.assertEqual(
                migrated["schema_version"], CAMPAIGN_CHECKPOINT_SCHEMA_VERSION
            )
            validate_campaign_checkpoint(plan, destination)
            migrated_by_leaf = {
                record["leaf_id"]: record for record in migrated["records"]
            }
            for source_record in historical["records"]:
                retained = migrated_by_leaf.get(source_record["leaf_id"])
                if retained is not None:
                    self.assertEqual(
                        retained["stages"],
                        source_record["stages"][: len(retained["stages"])],
                    )
            self.assertEqual(migrated["attempts"], [])
            self.assertGreaterEqual(result.retained_record_count, 1)
            self.assertEqual(result.invalidated_evidence_count, 1)

            receipt_path = destination.with_name(
                f"{destination.name}.migration-receipt.json"
            )
            receipt = json.loads(receipt_path.read_bytes())
            self.assertEqual(receipt["schema"], CAMPAIGN_MIGRATION_SCHEMA)
            self.assertEqual(
                receipt["source_checkpoint_sha256"], source_sha256
            )
            self.assertEqual(
                receipt["destination_checkpoint_sha256"],
                hashlib.sha256(destination.read_bytes()).hexdigest(),
            )
            self.assertEqual(
                receipt["invalidated_evidence"][0]["evidence_kind"],
                "campaign-execution-attempt",
            )

    def test_authentication_failure_writes_no_destination(self):
        plan, source_bytes = _stopped_schema7_checkpoint()
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "stopped-checkpoint.json"
            destination = Path(temporary) / "migrated-checkpoint.json"
            source.write_bytes(source_bytes)
            with self.assertRaisesRegex(ValueError, "source checkpoint SHA-256"):
                migrate_campaign_checkpoint(
                    source,
                    destination,
                    plan=plan,
                    expected_source_sha256="0" * 64,
                    changed_endpoint_policy_identities={},
                )
            self.assertFalse(destination.exists())

    def test_existing_destination_is_never_overwritten(self):
        plan, source_bytes = _stopped_schema7_checkpoint()
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "stopped-checkpoint.json"
            destination = Path(temporary) / "migrated-checkpoint.json"
            source.write_bytes(source_bytes)
            destination.write_bytes(b"operator-owned\n")
            with self.assertRaisesRegex(ValueError, "destination already exists"):
                migrate_campaign_checkpoint(
                    source,
                    destination,
                    plan=plan,
                    expected_source_sha256=hashlib.sha256(
                        source.read_bytes()
                    ).hexdigest(),
                    changed_endpoint_policy_identities={},
                )
            self.assertEqual(destination.read_bytes(), b"operator-owned\n")

    def test_second_install_failure_rolls_back_checkpoint_and_receipt(self):
        plan, source_bytes = _stopped_schema7_checkpoint()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "stopped-checkpoint.json"
            destination = root / "migrated-checkpoint.json"
            receipt = root / "migration-receipt.json"
            source.write_bytes(source_bytes)
            original_install = migration_module._install_staged_file
            installs = 0

            def fail_second(staged, target):
                nonlocal installs
                installs += 1
                if installs == 2:
                    raise OSError("injected checkpoint install failure")
                return original_install(staged, target)

            with patch.object(
                migration_module,
                "_install_staged_file",
                side_effect=fail_second,
            ), self.assertRaisesRegex(
                OSError, "injected checkpoint install failure"
            ):
                migrate_campaign_checkpoint(
                    source,
                    destination,
                    plan=plan,
                    expected_source_sha256=hashlib.sha256(
                        source_bytes
                    ).hexdigest(),
                    changed_endpoint_policy_identities={},
                    migration_receipt_path=receipt,
                )

            self.assertFalse(destination.exists())
            self.assertFalse(receipt.exists())

    def test_authenticated_orphan_receipt_is_recovered_on_retry(self):
        plan, source_bytes = _stopped_schema7_checkpoint()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "stopped-checkpoint.json"
            destination = root / "migrated-checkpoint.json"
            receipt = root / "migration-receipt.json"
            source.write_bytes(source_bytes)

            def hard_stop_after_receipt(
                staged_checkpoint,
                checkpoint,
                staged_receipt,
                receipt_target,
            ):
                del staged_checkpoint, checkpoint
                migration_module._install_staged_file(
                    staged_receipt, receipt_target
                )
                raise SystemExit("synthetic hard stop")

            with patch.object(
                migration_module,
                "_install_staged_pair",
                side_effect=hard_stop_after_receipt,
            ), self.assertRaises(SystemExit):
                migrate_campaign_checkpoint(
                    source,
                    destination,
                    plan=plan,
                    expected_source_sha256=hashlib.sha256(
                        source_bytes
                    ).hexdigest(),
                    changed_endpoint_policy_identities={},
                    migration_receipt_path=receipt,
                )

            self.assertFalse(destination.exists())
            self.assertTrue(receipt.exists())
            migrate_campaign_checkpoint(
                source,
                destination,
                plan=plan,
                expected_source_sha256=hashlib.sha256(
                    source_bytes
                ).hexdigest(),
                changed_endpoint_policy_identities={},
                migration_receipt_path=receipt,
            )
            validate_campaign_checkpoint(plan, destination)
            self.assertTrue(receipt.exists())

    def test_source_late_race_installs_neither_output(self):
        plan, source_bytes = _stopped_schema7_checkpoint()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "stopped-checkpoint.json"
            destination = root / "migrated-checkpoint.json"
            receipt = root / "migration-receipt.json"
            source.write_bytes(source_bytes)
            original_recheck = migration_module._recheck_source

            def race(path, authenticated):
                path.write_bytes(authenticated + b"late-race")
                return original_recheck(path, authenticated)

            with patch.object(
                migration_module,
                "_recheck_source",
                side_effect=race,
            ), self.assertRaisesRegex(
                RuntimeError, "source checkpoint changed during migration"
            ):
                migrate_campaign_checkpoint(
                    source,
                    destination,
                    plan=plan,
                    expected_source_sha256=hashlib.sha256(
                        source_bytes
                    ).hexdigest(),
                    changed_endpoint_policy_identities={},
                    migration_receipt_path=receipt,
                )

            self.assertFalse(destination.exists())
            self.assertFalse(receipt.exists())


if __name__ == "__main__":
    unittest.main()
