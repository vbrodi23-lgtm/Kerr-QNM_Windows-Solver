from __future__ import annotations

import hashlib
import random
import unittest

from windows_solver.campaign_evidence import EvidenceStrengtheningPolicy
from windows_solver.campaign_policy import (
    EvidenceLevel,
    add_numerical_record,
    empty_schema11_checkpoint,
    record_evidence,
)
from windows_solver.campaign_triage import (
    TriageLeaf,
    TriagePolicy,
    WholeAtlasTriage,
    build_whole_atlas_triage,
)
from windows_solver.contracts import canonical_json_bytes


def _sha256(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _checkpoint(leaf_ids):
    checkpoint = empty_schema11_checkpoint("campaign-1", "selection-1")
    for index, leaf_id in enumerate(leaf_ids):
        stage_content = {"schema": "test-stage/1", "ordinal": index}
        stage_sha256 = _sha256(stage_content)
        content = {
            "leaf_id": leaf_id,
            "state": "PRODUCED",
            "stages": [{**stage_content, "stage_sha256": stage_sha256}],
        }
        record = {**content, "record_sha256": _sha256(content)}
        checkpoint = add_numerical_record(checkpoint, record)
        checkpoint = record_evidence(
            checkpoint,
            leaf_id=leaf_id,
            central_record_sha256=record["record_sha256"],
            central_stage_sha256=stage_sha256,
            evidence_level=EvidenceLevel.SCREENED,
        )
    return checkpoint


def _leaf(
    leaf_id,
    role,
    mode,
    mechanism,
    *,
    magnitude=1.0,
    radius=0.01,
    branch=False,
    near=False,
    controller=False,
    disagreement=False,
):
    return TriageLeaf(
        leaf_id=leaf_id,
        role=role,
        mode_family=mode,
        mechanism_id=mechanism,
        numerical_state="PRODUCED",
        evidence_level=EvidenceLevel.SCREENED,
        response_magnitude=magnitude,
        response_disk_radius=radius,
        binary64_promoted_disagreement=disagreement,
        derivative_disagreement=False,
        branch_risk=branch,
        near_extremal_support=near,
        projective_angle_lower_bound=0.3,
        controls_projective_classification=controller,
    )


class WholeAtlasTriageTests(unittest.TestCase):
    def setUp(self):
        self.leaves = (
            _leaf("a", "Primary", "220", "horizon", radius=1.2),
            _leaf("b", "Control", "220", "exterior-light", branch=True),
            _leaf("c", "Deep", "332", "exterior-throat", near=True),
            _leaf("d", "Primary", "332", "exterior-light"),
            _leaf("e", "Control", "442", "exterior-throat", controller=True),
            _leaf("f", "Deep", "442", "horizon"),
            _leaf("g", "Primary", "220", "exterior-light", disagreement=True),
            _leaf("h", "Control", "332", "horizon"),
            _leaf("i", "Deep", "442", "exterior-throat"),
        )
        self.checkpoint = _checkpoint(tuple(leaf.leaf_id for leaf in self.leaves))
        self.evidence_policy = EvidenceStrengtheningPolicy.certification()

    def _build(self, leaves=None):
        return build_whole_atlas_triage(
            self.checkpoint,
            self.leaves if leaves is None else leaves,
            triage_policy=TriagePolicy(maximum_queue_size=8),
            evidence_policy=self.evidence_policy,
            survey_policy_identity="e" * 64,
            engine_identity="d" * 64,
        )

    def test_queue_is_deterministic_under_input_permutation(self):
        expected = self._build().to_mapping()
        shuffled = list(self.leaves)
        random.Random(73).shuffle(shuffled)
        actual = self._build(tuple(shuffled)).to_mapping()
        self.assertEqual(expected, actual)

    def test_queue_is_mixed_role_and_covers_each_mode_and_mechanism(self):
        triage = self._build()
        selected = {entry.leaf_id for entry in triage.queue_entries}
        chosen = [leaf for leaf in self.leaves if leaf.leaf_id in selected]
        self.assertEqual({"Primary", "Control", "Deep"}, {x.role for x in chosen})
        self.assertEqual({"220", "332", "442"}, {x.mode_family for x in chosen})
        self.assertEqual(
            {"horizon", "exterior-light", "exterior-throat"},
            {x.mechanism_id for x in chosen},
        )
        self.assertLess(len(selected), len(self.leaves))

    def test_queue_binds_checkpoint_policy_engine_and_exact_order(self):
        triage = self._build()
        request = triage.evidence_request
        self.assertEqual(
            tuple(entry.leaf_id for entry in triage.queue_entries),
            request.ordered_leaf_ids,
        )
        self.assertEqual(self.evidence_policy.identity_sha256, request.evidence_policy_identity)
        self.assertEqual("d" * 64, request.engine_identity)
        self.assertEqual("CERTIFY", request.profile.value)

    def test_unresolved_and_deferred_are_ranked_but_not_certification_eligible(self):
        unresolved = TriageLeaf(
            leaf_id="u",
            role="Primary",
            mode_family="550",
            mechanism_id="future-mechanism",
            numerical_state="UNRESOLVED",
            evidence_level=None,
            response_magnitude=None,
            response_disk_radius=None,
            binary64_promoted_disagreement=False,
            derivative_disagreement=False,
            branch_risk=False,
            near_extremal_support=False,
            projective_angle_lower_bound=None,
            controls_projective_classification=False,
        )
        triage = build_whole_atlas_triage(
            self.checkpoint,
            self.leaves + (unresolved,),
            triage_policy=TriagePolicy(maximum_queue_size=8),
            evidence_policy=self.evidence_policy,
            survey_policy_identity="e" * 64,
            engine_identity="d" * 64,
        )
        report = {entry.leaf_id: entry for entry in triage.atlas_entries}
        self.assertIn("UNRESOLVED", report["u"].reasons)
        self.assertFalse(report["u"].certification_eligible)
        self.assertNotIn("u", triage.evidence_request.ordered_leaf_ids)

    def test_policy_refuses_to_silently_select_the_entire_atlas(self):
        two = self.leaves[:2]
        checkpoint = _checkpoint(tuple(leaf.leaf_id for leaf in two))
        with self.assertRaisesRegex(ValueError, "entire eligible atlas"):
            build_whole_atlas_triage(
                checkpoint,
                two,
                triage_policy=TriagePolicy(maximum_queue_size=2),
                evidence_policy=self.evidence_policy,
                survey_policy_identity="e" * 64,
                engine_identity="d" * 64,
            )

    def test_duplicate_leaf_input_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "duplicate"):
            self._build(self.leaves + (self.leaves[0],))

    def test_authenticated_queue_round_trips_and_tampering_fails(self):
        mapping = self._build().to_mapping()
        self.assertEqual(mapping, WholeAtlasTriage.from_mapping(mapping).to_mapping())
        mapping["queue_entries"][0]["priority_score"] += 1
        with self.assertRaisesRegex(ValueError, "authentication failed"):
            WholeAtlasTriage.from_mapping(mapping)


if __name__ == "__main__":
    unittest.main()
