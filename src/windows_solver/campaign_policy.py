"""Execution and evidence policy for staged M02 atlas production.

The profile controls which existing numerical operations may run.  Evidence
levels describe what has been established around a numerical leaf and remain
independent of that leaf's terminal state.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import math
import re
from typing import Mapping

from .contracts import canonical_json_bytes


CAMPAIGN_EVIDENCE_SCHEMA = "windows-solver.campaign-evidence/1"
BACKGROUND_ROOT_KEY_SCHEMA = "windows-solver.background-root-key/1"
FIXED_ROOT_DOMEGA_KEY_SCHEMA = "windows-solver.fixed-root-domega-key/1"
FIXED_ROOT_DOMEGA_EVIDENCE_SCHEMA = (
    "windows-solver.fixed-root-domega-evidence/1"
)
EXTERIOR_ZERO_COUPLING_IDENTITY = (
    "exterior-profile-amplitude-zero-background/v1"
)
_HEX_64 = re.compile(r"[0-9a-f]{64}")


class ExecutionProfile(str, Enum):
    SURVEY = "survey"
    CERTIFY = "certify"
    VALIDATE = "validate"


class EvidenceLevel(str, Enum):
    SCREENED = "SCREENED"
    CERTIFIED = "CERTIFIED"
    VALIDATED = "VALIDATED"


_EVIDENCE_RANK = {
    EvidenceLevel.SCREENED: 0,
    EvidenceLevel.CERTIFIED: 1,
    EvidenceLevel.VALIDATED: 2,
}


def stronger_evidence_level(
    left: EvidenceLevel,
    right: EvidenceLevel,
) -> EvidenceLevel:
    if not isinstance(left, EvidenceLevel) or not isinstance(
        right, EvidenceLevel
    ):
        raise ValueError("campaign evidence level is invalid")
    return left if _EVIDENCE_RANK[left] >= _EVIDENCE_RANK[right] else right


def evidence_level_at_least(
    actual: EvidenceLevel,
    required: EvidenceLevel,
) -> bool:
    if not isinstance(actual, EvidenceLevel) or not isinstance(
        required, EvidenceLevel
    ):
        raise ValueError("campaign evidence level is invalid")
    return _EVIDENCE_RANK[actual] >= _EVIDENCE_RANK[required]


@dataclass(frozen=True, slots=True)
class CampaignExecutionPolicy:
    profile: ExecutionProfile
    target_evidence_level: EvidenceLevel
    prerequisite_evidence_level: EvidenceLevel | None
    binary64_first: bool
    stop_at_bounded_response: bool
    continue_after_leaf_failure: bool
    allow_truncation_root_solve: bool
    allow_resolution_root_solve: bool
    allow_seed_path_root_solve: bool
    allow_expanded_derivative_ladder: bool
    allow_full_complex_root_ladder: bool
    allow_independent_validation: bool
    allow_automatic_max_precision: bool

    @classmethod
    def for_profile(
        cls, profile: ExecutionProfile
    ) -> "CampaignExecutionPolicy":
        if not isinstance(profile, ExecutionProfile):
            raise ValueError("campaign execution profile is invalid")
        if profile is ExecutionProfile.SURVEY:
            return cls(
                profile=profile,
                target_evidence_level=EvidenceLevel.SCREENED,
                prerequisite_evidence_level=None,
                binary64_first=True,
                stop_at_bounded_response=True,
                continue_after_leaf_failure=True,
                allow_truncation_root_solve=False,
                allow_resolution_root_solve=False,
                allow_seed_path_root_solve=False,
                allow_expanded_derivative_ladder=False,
                allow_full_complex_root_ladder=False,
                allow_independent_validation=False,
                allow_automatic_max_precision=False,
            )
        if profile is ExecutionProfile.CERTIFY:
            return cls(
                profile=profile,
                target_evidence_level=EvidenceLevel.CERTIFIED,
                prerequisite_evidence_level=EvidenceLevel.SCREENED,
                binary64_first=False,
                stop_at_bounded_response=False,
                continue_after_leaf_failure=True,
                allow_truncation_root_solve=True,
                allow_resolution_root_solve=True,
                allow_seed_path_root_solve=True,
                allow_expanded_derivative_ladder=True,
                allow_full_complex_root_ladder=False,
                allow_independent_validation=False,
                allow_automatic_max_precision=True,
            )
        return cls(
            profile=profile,
            target_evidence_level=EvidenceLevel.VALIDATED,
            prerequisite_evidence_level=EvidenceLevel.CERTIFIED,
            binary64_first=False,
            stop_at_bounded_response=False,
            continue_after_leaf_failure=True,
            allow_truncation_root_solve=True,
            allow_resolution_root_solve=True,
            allow_seed_path_root_solve=True,
            allow_expanded_derivative_ladder=True,
            allow_full_complex_root_ladder=True,
            allow_independent_validation=True,
            allow_automatic_max_precision=True,
        )

    def to_mapping(self) -> dict[str, object]:
        return {
            "profile": self.profile.value,
            "target_evidence_level": self.target_evidence_level.value,
            "prerequisite_evidence_level": (
                None
                if self.prerequisite_evidence_level is None
                else self.prerequisite_evidence_level.value
            ),
            "binary64_first": self.binary64_first,
            "stop_at_bounded_response": self.stop_at_bounded_response,
            "continue_after_leaf_failure": self.continue_after_leaf_failure,
            "allow_truncation_root_solve": self.allow_truncation_root_solve,
            "allow_resolution_root_solve": self.allow_resolution_root_solve,
            "allow_seed_path_root_solve": self.allow_seed_path_root_solve,
            "allow_expanded_derivative_ladder": (
                self.allow_expanded_derivative_ladder
            ),
            "allow_full_complex_root_ladder": (
                self.allow_full_complex_root_ladder
            ),
            "allow_independent_validation": self.allow_independent_validation,
            "allow_automatic_max_precision": (
                self.allow_automatic_max_precision
            ),
        }


def _sha256(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _validated_digest(value: object, subject: str) -> str:
    if not isinstance(value, str) or _HEX_64.fullmatch(value) is None:
        raise ValueError(f"{subject} digest is invalid")
    return value


@dataclass(frozen=True, slots=True)
class BackgroundRootKey:
    """Exact c-independent identity for one reusable exterior Kerr root."""

    root_reference_id: str
    branch_id: str
    equation_id: str
    mode_sha256: str
    spin_binary64_hex: str
    bound_root_sha256: str
    determinant_family: str
    determinant_convention: str
    determinant_normalisation: str
    backend_identity_sha256: str
    numerical_policy_sha256: str
    controls_sha256: str
    precision_tier: str
    working_precision_bits: int
    zero_coupling_identity: str = EXTERIOR_ZERO_COUPLING_IDENTITY

    def __post_init__(self) -> None:
        for name in (
            "root_reference_id",
            "branch_id",
            "equation_id",
            "spin_binary64_hex",
            "determinant_family",
            "determinant_convention",
            "determinant_normalisation",
            "precision_tier",
        ):
            if not isinstance(getattr(self, name), str) or not getattr(
                self, name
            ):
                raise ValueError(f"background root {name} is invalid")
        for name in (
            "mode_sha256",
            "bound_root_sha256",
            "backend_identity_sha256",
            "numerical_policy_sha256",
            "controls_sha256",
        ):
            _validated_digest(getattr(self, name), f"background root {name}")
        if (
            type(self.working_precision_bits) is not int
            or self.working_precision_bits <= 0
        ):
            raise ValueError("background root working precision is invalid")
        if self.zero_coupling_identity != EXTERIOR_ZERO_COUPLING_IDENTITY:
            raise ValueError("background root zero-coupling identity is invalid")

    @property
    def content(self) -> dict[str, object]:
        return {
            "schema": BACKGROUND_ROOT_KEY_SCHEMA,
            "root_reference_id": self.root_reference_id,
            "branch_id": self.branch_id,
            "equation_id": self.equation_id,
            "mode_sha256": self.mode_sha256,
            "spin_binary64_hex": self.spin_binary64_hex,
            "bound_root_sha256": self.bound_root_sha256,
            "determinant_family": self.determinant_family,
            "determinant_convention": self.determinant_convention,
            "determinant_normalisation": self.determinant_normalisation,
            "backend_identity_sha256": self.backend_identity_sha256,
            "numerical_policy_sha256": self.numerical_policy_sha256,
            "controls_sha256": self.controls_sha256,
            "precision_tier": self.precision_tier,
            "working_precision_bits": self.working_precision_bits,
            "zero_coupling_identity": self.zero_coupling_identity,
        }

    @property
    def sha256(self) -> str:
        return _sha256(self.content)

    def to_mapping(self) -> dict[str, object]:
        return {**self.content, "key_sha256": self.sha256}

    @classmethod
    def from_mapping(cls, value: object) -> "BackgroundRootKey":
        fields = {
            "schema",
            "root_reference_id",
            "branch_id",
            "equation_id",
            "mode_sha256",
            "spin_binary64_hex",
            "bound_root_sha256",
            "determinant_family",
            "determinant_convention",
            "determinant_normalisation",
            "backend_identity_sha256",
            "numerical_policy_sha256",
            "controls_sha256",
            "precision_tier",
            "working_precision_bits",
            "zero_coupling_identity",
            "key_sha256",
        }
        if not isinstance(value, Mapping) or set(value) != fields:
            raise ValueError("background root key fields are invalid")
        if value.get("schema") != BACKGROUND_ROOT_KEY_SCHEMA:
            raise ValueError("background root key schema is invalid")
        key = cls(**{
            name: value[name]
            for name in fields - {"schema", "key_sha256"}
        })
        if value.get("key_sha256") != key.sha256:
            raise ValueError("background root key digest is invalid")
        if key.to_mapping() != value:
            raise ValueError("background root key is not canonical")
        return key


@dataclass(frozen=True, slots=True)
class FixedRootDomegaKey:
    background_key_sha256: str
    determinant_family: str
    determinant_normalisation: str
    controls_sha256: str
    precision_tier: str
    working_precision_bits: int
    derivative_method: str
    derivative_step_hex: str

    def __post_init__(self) -> None:
        _validated_digest(
            self.background_key_sha256, "fixed-root Domega background key"
        )
        _validated_digest(self.controls_sha256, "fixed-root Domega controls")
        for name in (
            "determinant_family",
            "determinant_normalisation",
            "precision_tier",
            "derivative_method",
            "derivative_step_hex",
        ):
            if not isinstance(getattr(self, name), str) or not getattr(
                self, name
            ):
                raise ValueError(f"fixed-root Domega {name} is invalid")
        if (
            type(self.working_precision_bits) is not int
            or self.working_precision_bits <= 0
        ):
            raise ValueError("fixed-root Domega precision is invalid")
        try:
            step = float.fromhex(self.derivative_step_hex)
        except (TypeError, ValueError) as error:
            raise ValueError("fixed-root Domega derivative step is invalid") from error
        if not math.isfinite(step) or step <= 0.0:
            raise ValueError("fixed-root Domega derivative step is invalid")

    @property
    def content(self) -> dict[str, object]:
        return {
            "schema": FIXED_ROOT_DOMEGA_KEY_SCHEMA,
            "background_key_sha256": self.background_key_sha256,
            "determinant_family": self.determinant_family,
            "determinant_normalisation": self.determinant_normalisation,
            "controls_sha256": self.controls_sha256,
            "precision_tier": self.precision_tier,
            "working_precision_bits": self.working_precision_bits,
            "derivative_method": self.derivative_method,
            "derivative_step_hex": self.derivative_step_hex,
        }

    @property
    def sha256(self) -> str:
        return _sha256(self.content)

    def to_mapping(self) -> dict[str, object]:
        return {**self.content, "key_sha256": self.sha256}

    @classmethod
    def from_mapping(cls, value: object) -> "FixedRootDomegaKey":
        fields = {
            "schema",
            "background_key_sha256",
            "determinant_family",
            "determinant_normalisation",
            "controls_sha256",
            "precision_tier",
            "working_precision_bits",
            "derivative_method",
            "derivative_step_hex",
            "key_sha256",
        }
        if not isinstance(value, Mapping) or set(value) != fields:
            raise ValueError("fixed-root Domega key fields are invalid")
        if value.get("schema") != FIXED_ROOT_DOMEGA_KEY_SCHEMA:
            raise ValueError("fixed-root Domega key schema is invalid")
        key = cls(**{
            name: value[name]
            for name in fields - {"schema", "key_sha256"}
        })
        if value.get("key_sha256") != key.sha256:
            raise ValueError("fixed-root Domega key digest is invalid")
        if key.to_mapping() != value:
            raise ValueError("fixed-root Domega key is not canonical")
        return key


@dataclass(frozen=True, slots=True)
class FixedRootDomegaEvidence:
    key: FixedRootDomegaKey
    source_leaf_id: str
    source_job_id: str
    source_root_seal_sha256: str
    derivative_disk: Mapping[str, object]
    derivative_radius_provenance: Mapping[str, object]
    frequency_samples: tuple[Mapping[str, object], ...]

    def __post_init__(self) -> None:
        if not isinstance(self.key, FixedRootDomegaKey):
            raise ValueError("fixed-root Domega evidence key is invalid")
        if not all(
            isinstance(value, str) and value
            for value in (self.source_leaf_id, self.source_job_id)
        ):
            raise ValueError("fixed-root Domega source identity is invalid")
        _validated_digest(
            self.source_root_seal_sha256,
            "fixed-root Domega source seal",
        )
        if not isinstance(self.derivative_disk, Mapping) or not isinstance(
            self.derivative_radius_provenance, Mapping
        ):
            raise ValueError("fixed-root Domega derivative evidence is invalid")
        samples = tuple(self.frequency_samples)
        if len(samples) != 4 or any(
            not isinstance(item, Mapping) for item in samples
        ):
            raise ValueError("fixed-root Domega sample evidence is invalid")
        object.__setattr__(self, "derivative_disk", dict(self.derivative_disk))
        object.__setattr__(
            self,
            "derivative_radius_provenance",
            dict(self.derivative_radius_provenance),
        )
        object.__setattr__(
            self,
            "frequency_samples",
            tuple(dict(item) for item in samples),
        )

    @property
    def content(self) -> dict[str, object]:
        return {
            "schema": FIXED_ROOT_DOMEGA_EVIDENCE_SCHEMA,
            "key": self.key.to_mapping(),
            "source_leaf_id": self.source_leaf_id,
            "source_job_id": self.source_job_id,
            "source_root_seal_sha256": self.source_root_seal_sha256,
            "derivative_disk": dict(self.derivative_disk),
            "derivative_radius_provenance": dict(
                self.derivative_radius_provenance
            ),
            "frequency_samples": [
                dict(item) for item in self.frequency_samples
            ],
        }

    @property
    def evidence_sha256(self) -> str:
        return _sha256(self.content)

    def to_mapping(self) -> dict[str, object]:
        return {**self.content, "evidence_sha256": self.evidence_sha256}

    @classmethod
    def from_mapping(cls, value: object) -> "FixedRootDomegaEvidence":
        fields = {
            "schema",
            "key",
            "source_leaf_id",
            "source_job_id",
            "source_root_seal_sha256",
            "derivative_disk",
            "derivative_radius_provenance",
            "frequency_samples",
            "evidence_sha256",
        }
        if not isinstance(value, Mapping) or set(value) != fields:
            raise ValueError("fixed-root Domega evidence fields are invalid")
        if value.get("schema") != FIXED_ROOT_DOMEGA_EVIDENCE_SCHEMA:
            raise ValueError("fixed-root Domega evidence schema is invalid")
        samples = value.get("frequency_samples")
        if not isinstance(samples, list):
            raise ValueError("fixed-root Domega evidence samples are invalid")
        evidence = cls(
            key=FixedRootDomegaKey.from_mapping(value["key"]),
            source_leaf_id=str(value["source_leaf_id"]),
            source_job_id=str(value["source_job_id"]),
            source_root_seal_sha256=str(value["source_root_seal_sha256"]),
            derivative_disk=value["derivative_disk"],
            derivative_radius_provenance=value[
                "derivative_radius_provenance"
            ],
            frequency_samples=tuple(samples),
        )
        if value.get("evidence_sha256") != evidence.evidence_sha256:
            raise ValueError("fixed-root Domega evidence digest is invalid")
        if evidence.to_mapping() != value:
            raise ValueError("fixed-root Domega evidence is not canonical")
        return evidence


class SurveyEvidenceCache:
    """In-memory exact-key cache used during one atlas survey pass."""

    def __init__(self) -> None:
        self._domega: dict[str, FixedRootDomegaEvidence] = {}
        self._keys: dict[str, FixedRootDomegaKey] = {}
        self._background_seals: dict[str, Mapping[str, object]] = {}

    @property
    def domega_evidence_count(self) -> int:
        return len(self._domega)

    @property
    def domega_keys(self) -> tuple[FixedRootDomegaKey, ...]:
        return tuple(self._keys[key] for key in self._domega)

    def lookup_domega(
        self, key: FixedRootDomegaKey
    ) -> FixedRootDomegaEvidence | None:
        if not isinstance(key, FixedRootDomegaKey):
            raise ValueError("fixed-root Domega cache key is invalid")
        evidence = self._domega.get(key.sha256)
        if evidence is None or evidence.key != key:
            return None
        return evidence

    def store_domega(self, evidence: FixedRootDomegaEvidence) -> None:
        if not isinstance(evidence, FixedRootDomegaEvidence):
            raise ValueError("fixed-root Domega cache evidence is invalid")
        key = evidence.key.sha256
        existing = self._domega.get(key)
        if existing is not None and existing != evidence:
            raise ValueError("fixed-root Domega cache evidence disagrees")
        self._domega[key] = evidence
        self._keys[key] = evidence.key

    @property
    def background_seal_mappings(self) -> tuple[Mapping[str, object], ...]:
        return tuple(dict(value) for value in self._background_seals.values())

    def store_background_seal(
        self,
        key: BackgroundRootKey,
        seal_mapping: Mapping[str, object],
    ) -> None:
        if not isinstance(key, BackgroundRootKey):
            raise ValueError("survey background cache key is invalid")
        if not isinstance(seal_mapping, Mapping):
            raise ValueError("survey background seal mapping is invalid")
        raw_key = seal_mapping.get("background_key")
        if BackgroundRootKey.from_mapping(raw_key) != key:
            raise ValueError("survey background seal key does not match")
        canonical = dict(seal_mapping)
        existing = self._background_seals.get(key.sha256)
        if existing is not None and dict(existing) != canonical:
            raise ValueError("survey background seal evidence disagrees")
        self._background_seals[key.sha256] = canonical


@dataclass(frozen=True, slots=True)
class EvidenceReceipt:
    execution_profile: ExecutionProfile
    evidence_level: EvidenceLevel
    receipt_sha256: str

    def __post_init__(self) -> None:
        if not isinstance(self.execution_profile, ExecutionProfile):
            raise ValueError("campaign evidence execution profile is invalid")
        if not isinstance(self.evidence_level, EvidenceLevel):
            raise ValueError("campaign evidence level is invalid")
        if (
            not isinstance(self.receipt_sha256, str)
            or _HEX_64.fullmatch(self.receipt_sha256) is None
        ):
            raise ValueError("campaign evidence receipt digest is invalid")
        expected = CampaignExecutionPolicy.for_profile(
            self.execution_profile
        ).target_evidence_level
        if self.evidence_level is not expected:
            raise ValueError("campaign evidence receipt profile/level is invalid")

    def to_mapping(self) -> dict[str, str]:
        return {
            "execution_profile": self.execution_profile.value,
            "evidence_level": self.evidence_level.value,
            "receipt_sha256": self.receipt_sha256,
        }

    @classmethod
    def from_mapping(cls, value: object) -> "EvidenceReceipt":
        if not isinstance(value, Mapping) or set(value) != {
            "execution_profile", "evidence_level", "receipt_sha256"
        }:
            raise ValueError("campaign evidence receipt fields are invalid")
        try:
            receipt = cls(
                execution_profile=ExecutionProfile(value["execution_profile"]),
                evidence_level=EvidenceLevel(value["evidence_level"]),
                receipt_sha256=str(value["receipt_sha256"]),
            )
        except (TypeError, ValueError) as error:
            raise ValueError("campaign evidence receipt is invalid") from error
        if receipt.to_mapping() != value:
            raise ValueError("campaign evidence receipt is not canonical")
        return receipt


@dataclass(frozen=True, slots=True)
class CampaignEvidenceRecord:
    leaf_id: str
    central_stage_sha256: str
    receipts: tuple[EvidenceReceipt, ...]
    discrepancy_codes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.leaf_id, str) or not self.leaf_id:
            raise ValueError("campaign evidence leaf ID is invalid")
        if (
            not isinstance(self.central_stage_sha256, str)
            or _HEX_64.fullmatch(self.central_stage_sha256) is None
        ):
            raise ValueError("campaign evidence central-stage digest is invalid")
        receipts = tuple(self.receipts)
        if not receipts or any(
            not isinstance(item, EvidenceReceipt) for item in receipts
        ):
            raise ValueError("campaign evidence receipts are invalid")
        receipt_ids = tuple(item.receipt_sha256 for item in receipts)
        if len(receipt_ids) != len(set(receipt_ids)):
            raise ValueError("campaign evidence receipt digests are duplicated")
        discrepancy_codes = tuple(self.discrepancy_codes)
        if (
            len(discrepancy_codes) != len(set(discrepancy_codes))
            or any(
                not isinstance(item, str) or not item
                for item in discrepancy_codes
            )
        ):
            raise ValueError("campaign evidence discrepancy codes are invalid")
        object.__setattr__(self, "receipts", receipts)
        object.__setattr__(self, "discrepancy_codes", discrepancy_codes)

    @property
    def evidence_level(self) -> EvidenceLevel:
        level = self.receipts[0].evidence_level
        for receipt in self.receipts[1:]:
            level = stronger_evidence_level(level, receipt.evidence_level)
        return level

    @property
    def execution_profile(self) -> ExecutionProfile:
        strongest_rank = _EVIDENCE_RANK[self.evidence_level]
        return next(
            receipt.execution_profile
            for receipt in reversed(self.receipts)
            if _EVIDENCE_RANK[receipt.evidence_level] == strongest_rank
        )

    @property
    def content(self) -> dict[str, object]:
        return {
            "schema": CAMPAIGN_EVIDENCE_SCHEMA,
            "leaf_id": self.leaf_id,
            "central_stage_sha256": self.central_stage_sha256,
            "execution_profile": self.execution_profile.value,
            "evidence_level": self.evidence_level.value,
            "receipts": [item.to_mapping() for item in self.receipts],
            "discrepancy_codes": list(self.discrepancy_codes),
        }

    @property
    def evidence_sha256(self) -> str:
        return hashlib.sha256(canonical_json_bytes(self.content)).hexdigest()

    def to_mapping(self) -> dict[str, object]:
        return {**self.content, "evidence_sha256": self.evidence_sha256}

    @classmethod
    def create(
        cls,
        *,
        leaf_id: str,
        central_stage_sha256: str,
        receipt: EvidenceReceipt,
    ) -> "CampaignEvidenceRecord":
        return cls(
            leaf_id=leaf_id,
            central_stage_sha256=central_stage_sha256,
            receipts=(receipt,),
        )

    def with_receipt(
        self, receipt: EvidenceReceipt
    ) -> "CampaignEvidenceRecord":
        if not isinstance(receipt, EvidenceReceipt):
            raise ValueError("campaign evidence receipt is invalid")
        for existing in self.receipts:
            if existing.receipt_sha256 == receipt.receipt_sha256:
                if existing != receipt:
                    raise ValueError("campaign evidence receipt digest is ambiguous")
                return self
        return CampaignEvidenceRecord(
            leaf_id=self.leaf_id,
            central_stage_sha256=self.central_stage_sha256,
            receipts=(*self.receipts, receipt),
            discrepancy_codes=self.discrepancy_codes,
        )

    def with_discrepancy(self, code: str) -> "CampaignEvidenceRecord":
        if not isinstance(code, str) or not code:
            raise ValueError("campaign evidence discrepancy code is invalid")
        if code in self.discrepancy_codes:
            return self
        return CampaignEvidenceRecord(
            leaf_id=self.leaf_id,
            central_stage_sha256=self.central_stage_sha256,
            receipts=self.receipts,
            discrepancy_codes=(*self.discrepancy_codes, code),
        )

    @classmethod
    def from_mapping(cls, value: object) -> "CampaignEvidenceRecord":
        fields = {
            "schema",
            "leaf_id",
            "central_stage_sha256",
            "execution_profile",
            "evidence_level",
            "receipts",
            "discrepancy_codes",
            "evidence_sha256",
        }
        if not isinstance(value, Mapping) or set(value) != fields:
            raise ValueError("campaign evidence record fields are invalid")
        if value.get("schema") != CAMPAIGN_EVIDENCE_SCHEMA:
            raise ValueError("campaign evidence schema is invalid")
        raw_receipts = value.get("receipts")
        raw_discrepancies = value.get("discrepancy_codes")
        if not isinstance(raw_receipts, list) or not isinstance(
            raw_discrepancies, list
        ):
            raise ValueError("campaign evidence record collections are invalid")
        record = cls(
            leaf_id=str(value["leaf_id"]),
            central_stage_sha256=str(value["central_stage_sha256"]),
            receipts=tuple(
                EvidenceReceipt.from_mapping(item) for item in raw_receipts
            ),
            discrepancy_codes=tuple(raw_discrepancies),
        )
        if value.get("execution_profile") != record.execution_profile.value:
            raise ValueError("campaign evidence execution profile is inconsistent")
        if value.get("evidence_level") != record.evidence_level.value:
            raise ValueError("campaign evidence level is inconsistent")
        if value.get("evidence_sha256") != record.evidence_sha256:
            raise ValueError("campaign evidence record digest is invalid")
        if record.to_mapping() != value:
            raise ValueError("campaign evidence record is not canonical")
        return record
