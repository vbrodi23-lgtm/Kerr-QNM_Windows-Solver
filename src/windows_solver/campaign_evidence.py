"""Explicit certification, validation, and release-evidence boundaries."""

from __future__ import annotations

import copy
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import tempfile
from typing import Callable, Mapping, Sequence

from .campaign_failures import abort_unexpected_system_failure
from .campaign_policy import (
    EvidenceLevel,
    ExecutionProfile,
    record_evidence,
    validate_schema11_checkpoint,
)
from .contracts import canonical_json_bytes


EVIDENCE_PASS_REQUEST_SCHEMA = "windows-solver.evidence-pass-request/1"
_EVIDENCE_RANK = {
    EvidenceLevel.SCREENED: 1,
    EvidenceLevel.CERTIFIED: 2,
    EvidenceLevel.VALIDATED: 3,
}


def _sha256(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def checkpoint_evidence_source_sha256(
    checkpoint: Mapping[str, object],
) -> str:
    """Bind scientific state while excluding disposable report status."""

    material = dict(checkpoint)
    material["report_status_receipt"] = None
    return _sha256(material)


def _is_sha256(value: object) -> bool:
    if not isinstance(value, str) or len(value) != 64:
        return False
    try:
        int(value, 16)
    except ValueError:
        return False
    return True


@dataclass(frozen=True, slots=True)
class EvidenceStrengtheningPolicy:
    """Reviewed work policy for one explicitly invoked evidence pass."""

    profile: ExecutionProfile
    precision_tiers: tuple[str, ...] = ("BF80",)
    bf120_review_receipt_sha256: str | None = None

    def __post_init__(self) -> None:
        try:
            profile = ExecutionProfile(self.profile)
        except (TypeError, ValueError) as error:
            raise ValueError("evidence policy profile is invalid") from error
        if profile not in {ExecutionProfile.CERTIFY, ExecutionProfile.VALIDATE}:
            raise ValueError("survey is not an evidence-strengthening profile")
        object.__setattr__(self, "profile", profile)
        if (
            not self.precision_tiers
            or len(set(self.precision_tiers)) != len(self.precision_tiers)
            or any(tier not in {"BF40", "BF80", "BF120"} for tier in self.precision_tiers)
        ):
            raise ValueError("evidence policy precision tiers are invalid")
        if "BF120" in self.precision_tiers:
            if not _is_sha256(self.bf120_review_receipt_sha256):
                raise ValueError("BF120 requires an explicit reviewed-policy receipt")
        elif self.bf120_review_receipt_sha256 is not None:
            raise ValueError("BF120 review receipt is invalid without BF120")

    @classmethod
    def certification(cls) -> "EvidenceStrengtheningPolicy":
        return cls(profile=ExecutionProfile.CERTIFY)

    @classmethod
    def validation(cls) -> "EvidenceStrengtheningPolicy":
        return cls(profile=ExecutionProfile.VALIDATE)

    @property
    def required_input_level(self) -> EvidenceLevel:
        return (
            EvidenceLevel.SCREENED
            if self.profile is ExecutionProfile.CERTIFY
            else EvidenceLevel.CERTIFIED
        )

    @property
    def successful_output_level(self) -> EvidenceLevel:
        return (
            EvidenceLevel.CERTIFIED
            if self.profile is ExecutionProfile.CERTIFY
            else EvidenceLevel.VALIDATED
        )

    @property
    def certificate_path_allowed(self) -> bool:
        return self.profile is ExecutionProfile.CERTIFY

    @property
    def independent_validation_allowed(self) -> bool:
        return self.profile is ExecutionProfile.VALIDATE

    @property
    def identity_material(self) -> dict[str, object]:
        return {
            "schema": "windows-solver.evidence-strengthening-policy/1",
            "profile": self.profile.value,
            "precision_tiers": list(self.precision_tiers),
            "bf120_review_receipt_sha256": self.bf120_review_receipt_sha256,
            "certificate_path_allowed": self.certificate_path_allowed,
            "independent_validation_allowed": self.independent_validation_allowed,
        }

    @property
    def identity_sha256(self) -> str:
        return _sha256(self.identity_material)


@dataclass(frozen=True, slots=True)
class EvidencePassRequest:
    profile: ExecutionProfile
    campaign_id: str
    selection_id: str
    source_checkpoint_sha256: str
    ordered_leaf_ids: tuple[str, ...]
    evidence_policy_identity: str
    engine_identity: str
    request_sha256: str

    def __post_init__(self) -> None:
        try:
            profile = ExecutionProfile(self.profile)
        except (TypeError, ValueError) as error:
            raise ValueError("evidence request profile is invalid") from error
        if profile not in {ExecutionProfile.CERTIFY, ExecutionProfile.VALIDATE}:
            raise ValueError("evidence request must be certify or validate")
        object.__setattr__(self, "profile", profile)
        if not self.campaign_id or not self.selection_id:
            raise ValueError("evidence request campaign binding is invalid")
        for value in (
            self.source_checkpoint_sha256,
            self.evidence_policy_identity,
            self.engine_identity,
            self.request_sha256,
        ):
            if not _is_sha256(value):
                raise ValueError("evidence request digest is invalid")
        if (
            not self.ordered_leaf_ids
            or len(set(self.ordered_leaf_ids)) != len(self.ordered_leaf_ids)
            or any(not isinstance(item, str) or not item for item in self.ordered_leaf_ids)
        ):
            raise ValueError("evidence request leaf selection is invalid")
        if self.request_sha256 != _sha256(self.content_mapping):
            raise ValueError("evidence request authentication failed")

    @property
    def content_mapping(self) -> dict[str, object]:
        return {
            "schema": EVIDENCE_PASS_REQUEST_SCHEMA,
            "profile": self.profile.value,
            "campaign_id": self.campaign_id,
            "selection_id": self.selection_id,
            "source_checkpoint_sha256": self.source_checkpoint_sha256,
            "ordered_leaf_ids": list(self.ordered_leaf_ids),
            "evidence_policy_identity": self.evidence_policy_identity,
            "engine_identity": self.engine_identity,
        }

    def to_mapping(self) -> dict[str, object]:
        return {**self.content_mapping, "request_sha256": self.request_sha256}

    @classmethod
    def from_mapping(cls, value: object) -> "EvidencePassRequest":
        fields = {
            "schema",
            "profile",
            "campaign_id",
            "selection_id",
            "source_checkpoint_sha256",
            "ordered_leaf_ids",
            "evidence_policy_identity",
            "engine_identity",
            "request_sha256",
        }
        if not isinstance(value, Mapping) or set(value) != fields:
            raise ValueError("evidence request fields are invalid")
        if value["schema"] != EVIDENCE_PASS_REQUEST_SCHEMA:
            raise ValueError("evidence request schema is invalid")
        leaf_ids = value["ordered_leaf_ids"]
        if not isinstance(leaf_ids, list):
            raise ValueError("evidence request leaf IDs are invalid")
        return cls(
            profile=ExecutionProfile(value["profile"]),
            campaign_id=value["campaign_id"],
            selection_id=value["selection_id"],
            source_checkpoint_sha256=value["source_checkpoint_sha256"],
            ordered_leaf_ids=tuple(leaf_ids),
            evidence_policy_identity=value["evidence_policy_identity"],
            engine_identity=value["engine_identity"],
            request_sha256=value["request_sha256"],
        )


@dataclass(frozen=True, slots=True)
class EvidencePassOutcome:
    leaf_id: str
    profile: ExecutionProfile
    central_record_sha256: str
    central_stage_sha256: str
    centre_agrees: bool
    discrepancy_code: str | None
    receipt: Mapping[str, object]

    def __post_init__(self) -> None:
        try:
            profile = ExecutionProfile(self.profile)
        except (TypeError, ValueError) as error:
            raise ValueError("evidence outcome profile is invalid") from error
        if profile not in {ExecutionProfile.CERTIFY, ExecutionProfile.VALIDATE}:
            raise ValueError("evidence outcome profile is invalid")
        object.__setattr__(self, "profile", profile)
        if not self.leaf_id:
            raise ValueError("evidence outcome leaf ID is invalid")
        if not _is_sha256(self.central_record_sha256) or not _is_sha256(
            self.central_stage_sha256
        ):
            raise ValueError("evidence outcome centre binding is invalid")
        if type(self.centre_agrees) is not bool:
            raise ValueError("evidence outcome centre comparison is invalid")
        if self.centre_agrees:
            if self.discrepancy_code is not None:
                raise ValueError("agreeing evidence cannot carry a discrepancy")
        elif not isinstance(self.discrepancy_code, str) or not self.discrepancy_code:
            raise ValueError("disagreeing evidence requires a discrepancy code")
        if not isinstance(self.receipt, Mapping):
            raise ValueError("evidence outcome receipt is invalid")
        receipt = copy.deepcopy(dict(self.receipt))
        supplied = receipt.pop("receipt_sha256", None)
        if not _is_sha256(supplied) or supplied != _sha256(receipt):
            raise ValueError("evidence outcome receipt authentication failed")
        object.__setattr__(self, "receipt", copy.deepcopy(dict(self.receipt)))


def build_evidence_pass_request(
    checkpoint: Mapping[str, object],
    *,
    policy: EvidenceStrengtheningPolicy,
    ordered_leaf_ids: Sequence[str],
    engine_identity: str,
) -> EvidencePassRequest:
    validated = validate_schema11_checkpoint(checkpoint)
    if not isinstance(policy, EvidenceStrengtheningPolicy):
        raise ValueError("evidence pass policy is invalid")
    content = {
        "schema": EVIDENCE_PASS_REQUEST_SCHEMA,
        "profile": policy.profile.value,
        "campaign_id": validated["campaign_id"],
        "selection_id": validated["selection_id"],
        "source_checkpoint_sha256": checkpoint_evidence_source_sha256(
            validated
        ),
        "ordered_leaf_ids": list(ordered_leaf_ids),
        "evidence_policy_identity": policy.identity_sha256,
        "engine_identity": engine_identity,
    }
    return EvidencePassRequest(
        profile=policy.profile,
        campaign_id=validated["campaign_id"],
        selection_id=validated["selection_id"],
        source_checkpoint_sha256=content["source_checkpoint_sha256"],
        ordered_leaf_ids=tuple(ordered_leaf_ids),
        evidence_policy_identity=policy.identity_sha256,
        engine_identity=engine_identity,
        request_sha256=_sha256(content),
    )


def _atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(canonical_json_bytes(value))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    except BaseException:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def _input_level(checkpoint: Mapping[str, object], leaf_id: str) -> EvidenceLevel:
    ledger = checkpoint["evidence_ledger"]
    entry = ledger.get(leaf_id)
    if not isinstance(entry, Mapping):
        raise ValueError(f"evidence pass leaf {leaf_id} has no SCREENED evidence")
    return EvidenceLevel(entry["evidence_level"])


def run_evidence_pass(
    checkpoint: Mapping[str, object],
    request: EvidencePassRequest,
    policy: EvidenceStrengtheningPolicy,
    *,
    checkpoint_path: str | os.PathLike[str] | Path,
    execute_leaf: Callable[
        [str, EvidenceStrengtheningPolicy], EvidencePassOutcome
    ],
    checkpoint_committed: Callable[
        [Mapping[str, object]], Mapping[str, object]
    ] | None = None,
) -> dict[str, object]:
    """Run one explicit evidence pass without replacing a numerical centre."""

    result = validate_schema11_checkpoint(checkpoint)
    if not isinstance(request, EvidencePassRequest):
        raise ValueError("evidence pass request is invalid")
    if not isinstance(policy, EvidenceStrengtheningPolicy):
        raise ValueError("evidence pass policy is invalid")
    if request.profile is not policy.profile:
        raise ValueError("evidence request and policy profiles differ")
    if request.evidence_policy_identity != policy.identity_sha256:
        raise ValueError("evidence request policy binding is stale")
    if (
        request.campaign_id != result["campaign_id"]
        or request.selection_id != result["selection_id"]
    ):
        raise ValueError("evidence request campaign binding is stale")
    if request.source_checkpoint_sha256 != checkpoint_evidence_source_sha256(
        result
    ):
        raise ValueError("evidence request checkpoint binding is stale")
    record_by_leaf = {record["leaf_id"]: record for record in result["records"]}
    for leaf_id in request.ordered_leaf_ids:
        if leaf_id not in record_by_leaf:
            raise ValueError(f"evidence request leaf {leaf_id} has no numerical record")
        level = _input_level(result, leaf_id)
        if _EVIDENCE_RANK[level] < _EVIDENCE_RANK[policy.required_input_level]:
            raise ValueError(
                f"{policy.profile.value} requires "
                f"{policy.required_input_level.value} evidence for {leaf_id}"
            )

    path = Path(checkpoint_path)

    def persist(value: Mapping[str, object]) -> dict[str, object]:
        durable = validate_schema11_checkpoint(value)
        _atomic_json(path, durable)
        if checkpoint_committed is not None:
            durable = validate_schema11_checkpoint(checkpoint_committed(durable))
        return durable

    result = persist(result)
    for leaf_id in request.ordered_leaf_ids:
        committed_before_leaf = result
        try:
            outcome = execute_leaf(leaf_id, policy)
            if not isinstance(outcome, EvidencePassOutcome):
                raise ValueError("evidence executor returned an invalid outcome")
            if outcome.leaf_id != leaf_id or outcome.profile is not policy.profile:
                raise ValueError("evidence outcome identity mismatch")
            record = record_by_leaf[leaf_id]
            evidence = result["evidence_ledger"][leaf_id]
            if (
                outcome.central_record_sha256 != record["record_sha256"]
                or outcome.central_stage_sha256
                != evidence["central_stage_sha256"]
            ):
                raise ValueError("evidence outcome attempted to replace the centre")
            current_level = EvidenceLevel(evidence["evidence_level"])
            next_level = (
                policy.successful_output_level
                if outcome.centre_agrees
                else current_level
            )
            discrepancy_codes = (
                () if outcome.centre_agrees else (outcome.discrepancy_code,)
            )
            disposition_content = {
                "schema": "windows-solver.evidence-pass-disposition/1",
                "profile": policy.profile.value,
                "request_sha256": request.request_sha256,
                "evidence_policy_identity": policy.identity_sha256,
                "engine_identity": request.engine_identity,
                "leaf_id": leaf_id,
                "central_record_sha256": outcome.central_record_sha256,
                "central_stage_sha256": outcome.central_stage_sha256,
                "centre_agrees": outcome.centre_agrees,
                "discrepancy_code": outcome.discrepancy_code,
                "precision_tiers": list(policy.precision_tiers),
                "source_receipt": copy.deepcopy(dict(outcome.receipt)),
            }
            disposition_receipt = {
                **disposition_content,
                "receipt_sha256": _sha256(disposition_content),
            }
            result = record_evidence(
                result,
                leaf_id=leaf_id,
                central_record_sha256=outcome.central_record_sha256,
                central_stage_sha256=outcome.central_stage_sha256,
                evidence_level=next_level,
                receipts=(disposition_receipt,),
                discrepancy_codes=discrepancy_codes,
            )
        except KeyboardInterrupt:
            raise
        except Exception as error:
            abort_unexpected_system_failure(
                committed_before_leaf,
                leaf_id=leaf_id,
                error=error,
                persist_checkpoint=lambda value: persist(value),
            )
            raise AssertionError("system failure abort returned unexpectedly")
        result = persist(result)
    return validate_schema11_checkpoint(result)


def require_release_evidence(
    checkpoint: Mapping[str, object],
    requirements: Mapping[str, EvidenceLevel | str],
) -> None:
    """Reject release admission unless every required leaf is strong enough."""

    validated = validate_schema11_checkpoint(checkpoint)
    records_by_leaf_id = {
        str(record["leaf_id"]): record for record in validated["records"]
    }
    for leaf_id, required in requirements.items():
        try:
            required_level = EvidenceLevel(required)
        except (TypeError, ValueError) as error:
            raise ValueError("release evidence requirement is invalid") from error
        if required_level is EvidenceLevel.SCREENED:
            raise ValueError(
                "release evidence requirements must be CERTIFIED or VALIDATED"
            )
        entry = validated["evidence_ledger"].get(leaf_id)
        if not isinstance(entry, Mapping):
            raise ValueError(
                f"release admission requires {required_level.value} evidence "
                f"for {leaf_id}"
            )
        record = records_by_leaf_id.get(leaf_id)
        if not isinstance(record, Mapping):
            raise ValueError(
                f"release evidence record binding is invalid for {leaf_id}"
            )
        stages = record.get("stages")
        if not isinstance(stages, list) or not stages:
            raise ValueError(
                f"release evidence stage binding is invalid for {leaf_id}"
            )
        terminal_stage = stages[-1]
        if (
            not isinstance(terminal_stage, Mapping)
            or entry.get("central_record_sha256") != record.get("record_sha256")
            or entry.get("central_stage_sha256")
            != terminal_stage.get("stage_sha256")
        ):
            raise ValueError(
                f"release evidence stage binding is invalid for {leaf_id}"
            )
        actual = EvidenceLevel(entry["evidence_level"])
        if _EVIDENCE_RANK[actual] < _EVIDENCE_RANK[required_level]:
            raise ValueError(
                f"release admission requires {required_level.value} evidence "
                f"for {leaf_id}"
            )


__all__ = [
    "EVIDENCE_PASS_REQUEST_SCHEMA",
    "EvidencePassOutcome",
    "EvidencePassRequest",
    "EvidenceStrengtheningPolicy",
    "build_evidence_pass_request",
    "checkpoint_evidence_source_sha256",
    "require_release_evidence",
    "run_evidence_pass",
]
