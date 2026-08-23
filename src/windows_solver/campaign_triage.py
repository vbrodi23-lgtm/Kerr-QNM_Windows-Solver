"""Deterministic whole-atlas triage and certification-queue construction."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import math
from typing import Mapping, Sequence

from .campaign_evidence import (
    EvidencePassRequest,
    EvidenceStrengtheningPolicy,
    build_evidence_pass_request,
)
from .campaign_policy import EvidenceLevel, ExecutionProfile, validate_schema11_checkpoint
from .contracts import canonical_json_bytes


TRIAGE_SCHEMA = "windows-solver.whole-atlas-triage/1"
CERTIFICATION_QUEUE_SCHEMA = "windows-solver.certification-queue/1"


def _sha256(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _is_sha256(value: object) -> bool:
    if not isinstance(value, str) or len(value) != 64:
        return False
    try:
        int(value, 16)
    except ValueError:
        return False
    return True


def _optional_nonnegative(value: object, label: str) -> float | None:
    if value is None:
        return None
    converted = float(value)
    if not math.isfinite(converted) or converted < 0:
        raise ValueError(f"triage {label} is invalid")
    return converted


@dataclass(frozen=True, slots=True)
class TriagePolicy:
    maximum_queue_size: int = 32
    relative_disk_risk_threshold: float = 0.25
    projective_angle_risk_threshold: float = 0.1
    allow_complete_selection: bool = False

    def __post_init__(self) -> None:
        if (
            isinstance(self.maximum_queue_size, bool)
            or not isinstance(self.maximum_queue_size, int)
            or self.maximum_queue_size < 1
        ):
            raise ValueError("triage queue size is invalid")
        for name in (
            "relative_disk_risk_threshold",
            "projective_angle_risk_threshold",
        ):
            value = float(getattr(self, name))
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"triage {name} is invalid")
            object.__setattr__(self, name, value)
        if type(self.allow_complete_selection) is not bool:
            raise ValueError("triage complete-selection policy is invalid")

    @property
    def identity_material(self) -> dict[str, object]:
        return {
            "schema": "windows-solver.whole-atlas-triage-policy/1",
            "maximum_queue_size": self.maximum_queue_size,
            "relative_disk_risk_threshold": self.relative_disk_risk_threshold,
            "projective_angle_risk_threshold": (
                self.projective_angle_risk_threshold
            ),
            "allow_complete_selection": self.allow_complete_selection,
        }

    @property
    def identity_sha256(self) -> str:
        return _sha256(self.identity_material)


@dataclass(frozen=True, slots=True)
class TriageLeaf:
    leaf_id: str
    role: str
    mode_family: str
    mechanism_id: str
    numerical_state: str
    evidence_level: EvidenceLevel | None
    response_magnitude: float | None
    response_disk_radius: float | None
    binary64_promoted_disagreement: bool
    derivative_disagreement: bool
    branch_risk: bool
    near_extremal_support: bool
    projective_angle_lower_bound: float | None
    controls_projective_classification: bool

    def __post_init__(self) -> None:
        for name in ("leaf_id", "role", "mode_family", "mechanism_id"):
            if not isinstance(getattr(self, name), str) or not getattr(self, name):
                raise ValueError(f"triage leaf {name} is invalid")
        if self.numerical_state not in {
            "PRODUCED",
            "UNRESOLVED",
            "DEFERRED",
            "REJECTED",
        }:
            raise ValueError("triage leaf numerical state is invalid")
        if self.evidence_level is not None:
            object.__setattr__(
                self, "evidence_level", EvidenceLevel(self.evidence_level)
            )
        for name in (
            "response_magnitude",
            "response_disk_radius",
            "projective_angle_lower_bound",
        ):
            object.__setattr__(
                self, name, _optional_nonnegative(getattr(self, name), name)
            )
        booleans = (
            "binary64_promoted_disagreement",
            "derivative_disagreement",
            "branch_risk",
            "near_extremal_support",
            "controls_projective_classification",
        )
        if any(type(getattr(self, name)) is not bool for name in booleans):
            raise ValueError("triage leaf risk flags are invalid")


@dataclass(frozen=True, slots=True)
class AtlasTriageEntry:
    leaf_id: str
    role: str
    mode_family: str
    mechanism_id: str
    priority_score: int
    relative_disk_radius: float | None
    reasons: tuple[str, ...]
    certification_eligible: bool

    def __post_init__(self) -> None:
        for name in ("leaf_id", "role", "mode_family", "mechanism_id"):
            if not isinstance(getattr(self, name), str) or not getattr(self, name):
                raise ValueError(f"atlas triage {name} is invalid")
        if (
            isinstance(self.priority_score, bool)
            or not isinstance(self.priority_score, int)
            or self.priority_score < 0
        ):
            raise ValueError("atlas triage priority is invalid")
        object.__setattr__(
            self,
            "relative_disk_radius",
            _optional_nonnegative(
                self.relative_disk_radius, "relative disk radius"
            ),
        )
        if any(not isinstance(reason, str) or not reason for reason in self.reasons):
            raise ValueError("atlas triage reasons are invalid")
        if type(self.certification_eligible) is not bool:
            raise ValueError("atlas triage eligibility is invalid")

    def to_mapping(self) -> dict[str, object]:
        return {
            "leaf_id": self.leaf_id,
            "role": self.role,
            "mode_family": self.mode_family,
            "mechanism_id": self.mechanism_id,
            "priority_score": self.priority_score,
            "relative_disk_radius": self.relative_disk_radius,
            "reasons": list(self.reasons),
            "certification_eligible": self.certification_eligible,
        }

    @classmethod
    def from_mapping(cls, value: object) -> "AtlasTriageEntry":
        fields = {
            "leaf_id",
            "role",
            "mode_family",
            "mechanism_id",
            "priority_score",
            "relative_disk_radius",
            "reasons",
            "certification_eligible",
        }
        if not isinstance(value, Mapping) or set(value) != fields:
            raise ValueError("atlas triage entry fields are invalid")
        reasons = value["reasons"]
        if not isinstance(reasons, list) or any(
            not isinstance(reason, str) or not reason for reason in reasons
        ):
            raise ValueError("atlas triage reasons are invalid")
        score = value["priority_score"]
        if isinstance(score, bool) or not isinstance(score, int) or score < 0:
            raise ValueError("atlas triage priority is invalid")
        if type(value["certification_eligible"]) is not bool:
            raise ValueError("atlas triage eligibility is invalid")
        return cls(
            leaf_id=value["leaf_id"],
            role=value["role"],
            mode_family=value["mode_family"],
            mechanism_id=value["mechanism_id"],
            priority_score=score,
            relative_disk_radius=_optional_nonnegative(
                value["relative_disk_radius"], "relative disk radius"
            ),
            reasons=tuple(reasons),
            certification_eligible=value["certification_eligible"],
        )


@dataclass(frozen=True, slots=True)
class WholeAtlasTriage:
    campaign_id: str
    selection_id: str
    source_checkpoint_sha256: str
    triage_policy_identity: str
    survey_policy_identity: str
    evidence_request: EvidencePassRequest
    atlas_entries: tuple[AtlasTriageEntry, ...]
    queue_entries: tuple[AtlasTriageEntry, ...]
    queue_sha256: str

    @property
    def content_mapping(self) -> dict[str, object]:
        return {
            "schema": CERTIFICATION_QUEUE_SCHEMA,
            "triage_schema": TRIAGE_SCHEMA,
            "campaign_id": self.campaign_id,
            "selection_id": self.selection_id,
            "source_checkpoint_sha256": self.source_checkpoint_sha256,
            "triage_policy_identity": self.triage_policy_identity,
            "survey_policy_identity": self.survey_policy_identity,
            "evidence_request": self.evidence_request.to_mapping(),
            "atlas_entries": [entry.to_mapping() for entry in self.atlas_entries],
            "queue_entries": [entry.to_mapping() for entry in self.queue_entries],
        }

    def to_mapping(self) -> dict[str, object]:
        return {**self.content_mapping, "queue_sha256": self.queue_sha256}

    def __post_init__(self) -> None:
        if not self.campaign_id or not self.selection_id:
            raise ValueError("certification queue campaign binding is invalid")
        for digest in (
            self.source_checkpoint_sha256,
            self.triage_policy_identity,
            self.survey_policy_identity,
            self.queue_sha256,
        ):
            if not _is_sha256(digest):
                raise ValueError("certification queue digest is invalid")
        if self.queue_sha256 != _sha256(self.content_mapping):
            raise ValueError("certification queue authentication failed")
        if self.evidence_request.profile is not ExecutionProfile.CERTIFY:
            raise ValueError("certification queue request profile is invalid")
        if (
            self.evidence_request.campaign_id != self.campaign_id
            or self.evidence_request.selection_id != self.selection_id
            or self.evidence_request.source_checkpoint_sha256
            != self.source_checkpoint_sha256
        ):
            raise ValueError("certification queue request binding is inconsistent")
        atlas_by_leaf = {entry.leaf_id: entry for entry in self.atlas_entries}
        if len(atlas_by_leaf) != len(self.atlas_entries):
            raise ValueError("certification queue atlas leaf IDs are not unique")
        queue_ids = tuple(entry.leaf_id for entry in self.queue_entries)
        if not queue_ids or len(set(queue_ids)) != len(queue_ids):
            raise ValueError("certification queue leaf IDs are invalid")
        if any(
            entry.leaf_id not in atlas_by_leaf
            or not entry.certification_eligible
            or entry != atlas_by_leaf[entry.leaf_id]
            for entry in self.queue_entries
        ):
            raise ValueError("certification queue entry is not an eligible atlas row")
        if tuple(entry.leaf_id for entry in self.queue_entries) != (
            self.evidence_request.ordered_leaf_ids
        ):
            raise ValueError("certification queue order is inconsistent")

    @classmethod
    def from_mapping(cls, value: object) -> "WholeAtlasTriage":
        fields = {
            "schema",
            "triage_schema",
            "campaign_id",
            "selection_id",
            "source_checkpoint_sha256",
            "triage_policy_identity",
            "survey_policy_identity",
            "evidence_request",
            "atlas_entries",
            "queue_entries",
            "queue_sha256",
        }
        if not isinstance(value, Mapping) or set(value) != fields:
            raise ValueError("certification queue fields are invalid")
        if (
            value["schema"] != CERTIFICATION_QUEUE_SCHEMA
            or value["triage_schema"] != TRIAGE_SCHEMA
        ):
            raise ValueError("certification queue schema is invalid")
        atlas = value["atlas_entries"]
        queue = value["queue_entries"]
        if not isinstance(atlas, list) or not isinstance(queue, list):
            raise ValueError("certification queue entries are invalid")
        return cls(
            campaign_id=value["campaign_id"],
            selection_id=value["selection_id"],
            source_checkpoint_sha256=value["source_checkpoint_sha256"],
            triage_policy_identity=value["triage_policy_identity"],
            survey_policy_identity=value["survey_policy_identity"],
            evidence_request=EvidencePassRequest.from_mapping(
                value["evidence_request"]
            ),
            atlas_entries=tuple(
                AtlasTriageEntry.from_mapping(entry) for entry in atlas
            ),
            queue_entries=tuple(
                AtlasTriageEntry.from_mapping(entry) for entry in queue
            ),
            queue_sha256=value["queue_sha256"],
        )


def _entry(leaf: TriageLeaf, policy: TriagePolicy) -> AtlasTriageEntry:
    reasons: list[str] = []
    score = 0
    if leaf.numerical_state in {"UNRESOLVED", "DEFERRED", "REJECTED"}:
        reasons.append(leaf.numerical_state)
        score += {"UNRESOLVED": 120, "DEFERRED": 110, "REJECTED": 100}[
            leaf.numerical_state
        ]
    relative = None
    if leaf.response_magnitude is not None and leaf.response_disk_radius is not None:
        if leaf.response_magnitude == 0:
            reasons.append("ZERO_RESPONSE")
            score += 100
        else:
            relative = leaf.response_disk_radius / leaf.response_magnitude
            if leaf.response_disk_radius >= leaf.response_magnitude:
                reasons.append("RESPONSE_DISK_CONTAINS_ZERO")
                score += 100
            elif relative >= policy.relative_disk_risk_threshold:
                reasons.append("LARGE_RELATIVE_DISK")
                score += 50
    if leaf.binary64_promoted_disagreement:
        reasons.append("BINARY64_PROMOTED_DISAGREEMENT")
        score += 45
    if leaf.derivative_disagreement:
        reasons.append("DERIVATIVE_DISAGREEMENT")
        score += 40
    if leaf.branch_risk:
        reasons.append("BRANCH_RISK")
        score += 35
    if leaf.near_extremal_support:
        reasons.append("NEAR_EXTREMAL_SUPPORT")
        score += 30
    if leaf.controls_projective_classification:
        reasons.append("PROJECTIVE_CLASSIFICATION_CONTROLLER")
        score += 25
    if (
        leaf.projective_angle_lower_bound is not None
        and leaf.projective_angle_lower_bound
        <= policy.projective_angle_risk_threshold
    ):
        reasons.append("SMALL_PROJECTIVE_ANGLE")
        score += 20
    eligible = (
        leaf.numerical_state == "PRODUCED"
        and leaf.evidence_level is EvidenceLevel.SCREENED
    )
    return AtlasTriageEntry(
        leaf_id=leaf.leaf_id,
        role=leaf.role,
        mode_family=leaf.mode_family,
        mechanism_id=leaf.mechanism_id,
        priority_score=score,
        relative_disk_radius=relative,
        reasons=tuple(reasons),
        certification_eligible=eligible,
    )


def _rank_key(entry: AtlasTriageEntry) -> tuple[object, ...]:
    relative = entry.relative_disk_radius
    bounded_relative = relative if relative is not None else -1.0
    return (
        -entry.priority_score,
        -bounded_relative,
        entry.mode_family,
        entry.mechanism_id,
        entry.role,
        entry.leaf_id,
    )


def build_whole_atlas_triage(
    checkpoint: Mapping[str, object],
    leaves: Sequence[TriageLeaf],
    *,
    triage_policy: TriagePolicy,
    evidence_policy: EvidenceStrengtheningPolicy,
    survey_policy_identity: str,
    engine_identity: str,
) -> WholeAtlasTriage:
    """Rank the full atlas and emit one authenticated mixed-role queue."""

    validated = validate_schema11_checkpoint(checkpoint)
    if not isinstance(triage_policy, TriagePolicy):
        raise ValueError("triage policy is invalid")
    if (
        not isinstance(evidence_policy, EvidenceStrengtheningPolicy)
        or evidence_policy.profile is not ExecutionProfile.CERTIFY
    ):
        raise ValueError("triage requires an explicit certification policy")
    if not _is_sha256(survey_policy_identity) or not _is_sha256(engine_identity):
        raise ValueError("triage survey-policy or engine identity is invalid")
    leaf_tuple = tuple(leaves)
    if not leaf_tuple:
        raise ValueError("whole-atlas triage requires selected leaves")
    if any(not isinstance(leaf, TriageLeaf) for leaf in leaf_tuple):
        raise ValueError("whole-atlas triage leaf is invalid")
    leaf_ids = tuple(leaf.leaf_id for leaf in leaf_tuple)
    if len(set(leaf_ids)) != len(leaf_ids):
        raise ValueError("whole-atlas triage contains duplicate leaf IDs")

    entries = tuple(sorted(
        (_entry(leaf, triage_policy) for leaf in leaf_tuple), key=_rank_key
    ))
    eligible = tuple(entry for entry in entries if entry.certification_eligible)
    if not eligible:
        raise ValueError("whole-atlas triage found no SCREENED certification input")
    checkpoint_record_map = {
        record["leaf_id"]: record for record in validated["records"]
    }
    checkpoint_evidence = validated["evidence_ledger"]
    for leaf in leaf_tuple:
        ledger = checkpoint_evidence.get(leaf.leaf_id)
        actual_level = (
            EvidenceLevel(ledger["evidence_level"])
            if isinstance(ledger, Mapping)
            else None
        )
        if actual_level is not leaf.evidence_level:
            raise ValueError(
                f"triage evidence disagrees with checkpoint for {leaf.leaf_id}"
            )
        record = checkpoint_record_map.get(leaf.leaf_id)
        if record is not None and record["state"] != leaf.numerical_state:
            raise ValueError(
                f"triage numerical state disagrees with checkpoint for {leaf.leaf_id}"
            )
    for entry in eligible:
        ledger = checkpoint_evidence.get(entry.leaf_id)
        if (
            entry.leaf_id not in checkpoint_record_map
            or not isinstance(ledger, Mapping)
            or ledger.get("evidence_level") != EvidenceLevel.SCREENED.value
        ):
            raise ValueError(
                f"triage eligibility disagrees with checkpoint for {entry.leaf_id}"
            )

    selected: dict[str, AtlasTriageEntry] = {}
    for field in ("mechanism_id", "mode_family", "role"):
        groups = sorted({getattr(entry, field) for entry in eligible})
        for group in groups:
            sentinel = next(
                entry for entry in eligible if getattr(entry, field) == group
            )
            selected[sentinel.leaf_id] = sentinel
    if len(selected) > triage_policy.maximum_queue_size:
        raise ValueError("triage sentinel coverage exceeds the queue budget")
    for entry in eligible:
        if entry.priority_score <= 0 or entry.leaf_id in selected:
            continue
        if len(selected) >= triage_policy.maximum_queue_size:
            break
        selected[entry.leaf_id] = entry
    queue_entries = tuple(
        entry for entry in eligible if entry.leaf_id in selected
    )
    if (
        len(queue_entries) == len(eligible)
        and not triage_policy.allow_complete_selection
    ):
        raise ValueError(
            "triage policy would silently select the entire eligible atlas"
        )

    request = build_evidence_pass_request(
        validated,
        policy=evidence_policy,
        ordered_leaf_ids=tuple(entry.leaf_id for entry in queue_entries),
        engine_identity=engine_identity,
    )
    content = {
        "schema": CERTIFICATION_QUEUE_SCHEMA,
        "triage_schema": TRIAGE_SCHEMA,
        "campaign_id": validated["campaign_id"],
        "selection_id": validated["selection_id"],
        "source_checkpoint_sha256": request.source_checkpoint_sha256,
        "triage_policy_identity": triage_policy.identity_sha256,
        "survey_policy_identity": survey_policy_identity,
        "evidence_request": request.to_mapping(),
        "atlas_entries": [entry.to_mapping() for entry in entries],
        "queue_entries": [entry.to_mapping() for entry in queue_entries],
    }
    return WholeAtlasTriage(
        campaign_id=validated["campaign_id"],
        selection_id=validated["selection_id"],
        source_checkpoint_sha256=request.source_checkpoint_sha256,
        triage_policy_identity=triage_policy.identity_sha256,
        survey_policy_identity=survey_policy_identity,
        evidence_request=request,
        atlas_entries=entries,
        queue_entries=queue_entries,
        queue_sha256=_sha256(content),
    )


__all__ = [
    "AtlasTriageEntry",
    "CERTIFICATION_QUEUE_SCHEMA",
    "TRIAGE_SCHEMA",
    "TriageLeaf",
    "TriagePolicy",
    "WholeAtlasTriage",
    "build_whole_atlas_triage",
]
