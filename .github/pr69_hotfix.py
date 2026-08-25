from pathlib import Path

runtime_path = Path("src/windows_solver/campaign_runtime.py")
text = runtime_path.read_text(encoding="utf-8")

marker = "\ndef run_native_binary64_pass(\n"
helper = '''

def _provisional_stage_publication_metadata(
    leaf: object,
    stage: Mapping[str, object],
) -> tuple[str, str]:
    """Authenticate one durable provisional stage for publication diagnostics.

    Horizon and exterior provisional stages intentionally use different
    envelopes.  The horizon root seal belongs to its authenticated analytic
    evidence; exterior stages retain the seal at the stage top level.
    """

    if not isinstance(stage, Mapping):
        raise ValueError("provisional stage publication is invalid")
    stage_sha256 = stage.get("stage_sha256")
    content = {
        key: item for key, item in stage.items() if key != "stage_sha256"
    }
    if not _is_sha256(stage_sha256) or stage_sha256 != _sha256(content):
        raise ValueError("provisional stage publication digest is invalid")

    if stage.get("schema") == HORIZON_SCREENING_STAGE_SCHEMA:
        if (
            getattr(leaf, "mechanism_id", None) != "horizon-admittance"
            or stage.get("operation_identity") != BINARY64_HORIZON_OPERATION_V3
        ):
            raise ValueError("horizon provisional stage identity is invalid")
        payload = stage.get("component_result")
        raw_result = payload.get("result") if isinstance(payload, Mapping) else None
        evidence = (
            raw_result.get("analytic_horizon_evidence")
            if isinstance(raw_result, Mapping)
            else None
        )
        if (
            not isinstance(raw_result, Mapping)
            or raw_result.get("leaf_id") != getattr(leaf, "leaf_id", None)
            or raw_result.get("mechanism_id") != "horizon-admittance"
            or not isinstance(evidence, Mapping)
        ):
            raise ValueError("horizon provisional stage binding is invalid")
        root_seal_sha256 = evidence.get("root_seal_sha256")
    else:
        if getattr(leaf, "mechanism_id", None) == "horizon-admittance":
            raise ValueError("horizon provisional stage schema is invalid")
        root_seal_sha256 = stage.get("root_seal_sha256")

    if not _is_sha256(root_seal_sha256):
        raise ValueError("provisional stage publication root seal is invalid")
    return str(stage_sha256), str(root_seal_sha256)
'''
if "def _provisional_stage_publication_metadata(" in text:
    raise SystemExit("provisional-stage helper already exists")
if text.count(marker) != 1:
    raise SystemExit("run_native_binary64_pass insertion marker changed")
text = text.replace(marker, helper + marker, 1)

old = '''    def publish_provisional_stage(leaf, stage):
        """Publish the checkpoint-committed exterior source-stage transition."""

        if not isinstance(stage, Mapping):
            raise ValueError("provisional stage publication is invalid")
        stage_sha256 = stage.get("stage_sha256")
        root_seal_sha256 = stage.get("root_seal_sha256")
        if (
            not isinstance(stage_sha256, str)
            or len(stage_sha256) != 64
            or not isinstance(root_seal_sha256, str)
            or len(root_seal_sha256) != 64
        ):
            raise ValueError("provisional stage publication is unauthenticated")
        if diagnostic_session is not None:
'''
new = '''    def publish_provisional_stage(leaf, stage):
        """Publish one authenticated checkpoint-committed provisional stage."""

        stage_sha256, root_seal_sha256 = (
            _provisional_stage_publication_metadata(leaf, stage)
        )
        if diagnostic_session is not None:
'''
if text.count(old) != 1:
    raise SystemExit("provisional publication block changed")
text = text.replace(old, new, 1)
runtime_path.write_text(text, encoding="utf-8")

test_path = Path("tests/test_pr69_provisional_stage_publication.py")
test_path.write_text(r'''"""PR69 regression: horizon and exterior provisional stages share one callback."""

from __future__ import annotations

import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from windows_solver.campaign_policy import (
    PromotionQueueKind,
    SurveyDisposition,
    empty_schema11_checkpoint,
)
from windows_solver.campaign_recovery import RecoverySelection
from windows_solver.campaign_runtime import (
    _provisional_stage_publication_metadata,
    run_native_binary64_pass,
)
from windows_solver.campaign_survey import Binary64PassOutcome
from windows_solver.contracts import canonical_json_bytes
from windows_solver.native_response_kernel import VettedNativeDeterminantKernel
from windows_solver.response_batches import (
    HORIZON_SCREENING_STAGE_SCHEMA,
    PrecisionCapabilities,
    build_campaign_plan,
    build_campaign_selection,
    scientific_computation_identity_sha256,
)
from windows_solver.response_engine import (
    BINARY64_HORIZON_OPERATION_V3,
    NumericalPolicy,
)
from windows_solver.root_evidence import AuthenticatedRootEvidence
from windows_solver.solved_leaf_cache import SolvedLeafStore


def _sha256(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _sealed_stage(content: dict[str, object]) -> dict[str, object]:
    return {**content, "stage_sha256": _sha256(content)}


class ProvisionalStagePublicationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.plan = build_campaign_plan(
            policy=NumericalPolicy(),
            backend_identity=VettedNativeDeterminantKernel.identity,
            precision_capabilities=PrecisionCapabilities((64, 80)),
        )
        cls.horizon = next(
            leaf
            for leaf in cls.plan.leaves
            if leaf.mechanism_id == "horizon-admittance"
            and leaf.role == "primary"
        )
        cls.exterior = next(
            leaf
            for leaf in cls.plan.leaves
            if leaf.mechanism_id != "horizon-admittance"
            and leaf.role == "primary"
        )

    def _horizon_stage(self, root_seal_sha256: str) -> dict[str, object]:
        return _sealed_stage({
            "schema": HORIZON_SCREENING_STAGE_SCHEMA,
            "operation_identity": BINARY64_HORIZON_OPERATION_V3,
            "precision_tier": "binary64",
            "component_result": {
                "result": {
                    "leaf_id": self.horizon.leaf_id,
                    "mechanism_id": "horizon-admittance",
                    "analytic_horizon_evidence": {
                        "root_seal_sha256": root_seal_sha256,
                    },
                },
            },
            "response_disk": None,
            "numerical_state": "DERIVATIVE_UNRESOLVED",
        })

    def test_horizon_provisional_stage_uses_nested_root_seal(self) -> None:
        stage = self._horizon_stage("a" * 64)
        self.assertEqual(
            (stage["stage_sha256"], "a" * 64),
            _provisional_stage_publication_metadata(self.horizon, stage),
        )

    def test_exterior_provisional_stage_keeps_top_level_root_seal(self) -> None:
        stage = _sealed_stage({
            "schema": "windows-solver.binary64-fixed-root-provisional/1",
            "operation_identity": "binary64-fixed-root-provisional/v1",
            "root_seal_sha256": "b" * 64,
            "leaf_id": self.exterior.leaf_id,
        })
        self.assertEqual(
            (stage["stage_sha256"], "b" * 64),
            _provisional_stage_publication_metadata(self.exterior, stage),
        )

    def test_tampered_provisional_stage_fails_closed(self) -> None:
        stage = self._horizon_stage("c" * 64)
        stage["numerical_state"] = "CONVERGED"
        with self.assertRaisesRegex(ValueError, "digest is invalid"):
            _provisional_stage_publication_metadata(self.horizon, stage)

    def test_horizon_provisional_stage_requires_nested_root_seal(self) -> None:
        stage = self._horizon_stage("d" * 64)
        stage["component_result"]["result"]["analytic_horizon_evidence"].pop(
            "root_seal_sha256"
        )
        content = {key: value for key, value in stage.items() if key != "stage_sha256"}
        stage["stage_sha256"] = _sha256(content)
        with self.assertRaisesRegex(ValueError, "root seal is invalid"):
            _provisional_stage_publication_metadata(self.horizon, stage)

    def test_native_binary64_horizon_promotion_commits_without_callback_failure(
        self,
    ) -> None:
        selection = build_campaign_selection(
            self.plan,
            role=self.horizon.role,
            leaf_ids=(self.horizon.leaf_id,),
        )
        recovery = RecoverySelection(
            campaign_id=self.plan.campaign_id,
            selection_id=selection.selection_id,
            ordered_leaf_ids=(self.horizon.leaf_id,),
            roles={self.horizon.leaf_id: self.horizon.role},
            scientific_identities={
                self.horizon.leaf_id: scientific_computation_identity_sha256(
                    self.plan, self.horizon
                ),
            },
        )
        root_seal_sha256 = AuthenticatedRootEvidence.from_bound_leaf(
            self.horizon
        ).root_seal_sha256
        stage = self._horizon_stage(root_seal_sha256)
        outcome = Binary64PassOutcome(
            disposition=SurveyDisposition.PROMOTION_PENDING_RESPONSE,
            operation_identity=BINARY64_HORIZON_OPERATION_V3,
            reason_code="ROOT_UNCERTAINTY_EVIDENCE_UNAVAILABLE",
            queue_kind=PromotionQueueKind.RESPONSE,
            minimum_requested_tier="BF80",
            provisional_stage=stage,
            provisional_stage_sha256=stage["stage_sha256"],
            provisional_operation_identity=BINARY64_HORIZON_OPERATION_V3,
        )

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            checkpoint_path = root / "checkpoint.json"
            store = SolvedLeafStore(root / "solved-leaves")
            with patch(
                "windows_solver.campaign_runtime._binary64_backend",
                return_value=object(),
            ), patch(
                "windows_solver.campaign_runtime._horizon_outcome",
                return_value=outcome,
            ), patch(
                "windows_solver.campaign_runtime._refresh_runtime_reports",
                side_effect=(
                    lambda _plan, _selection, _path, value, **_kwargs: dict(value)
                ),
            ):
                result = run_native_binary64_pass(
                    self.plan,
                    selection,
                    recovery,
                    empty_schema11_checkpoint(
                        self.plan.campaign_id, selection.selection_id
                    ),
                    checkpoint_path=checkpoint_path,
                    solved_leaf_store=store,
                )

        self.assertEqual(1, result.queued_count)
        self.assertEqual([], result.checkpoint["system_failures"])
        entry = result.checkpoint["promotion_queue"]["entries"][0]
        self.assertEqual("PENDING", entry["disposition"])
        self.assertEqual("BF80", entry["minimum_requested_tier"])
        self.assertEqual(stage, entry["provisional_stage"])
        self.assertEqual(root_seal_sha256, entry["source_root_seal_sha256"])


if __name__ == "__main__":
    unittest.main()
''', encoding="utf-8")
