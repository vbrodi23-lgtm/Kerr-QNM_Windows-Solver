"""Fail-closed admission package and evidence-bound linear-response provider."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from types import MappingProxyType
from typing import Mapping

from .contracts import (
    Capability,
    CarrierState,
    EvidenceState,
    ExecutionState,
    NumericalState,
    ScientificState,
    StudyRequest,
    canonical_json_bytes,
)
from .evidence_intake import B_PRIME_CONTRACT_SHA256, load_evidence_bundle
from .linear_response import (
    B_PRIME_RELEASE_DOMAIN,
    LINEAR_RESPONSE_ADMITTED_DESCRIPTOR,
    LINEAR_RESPONSE_DESCRIPTOR,
    validate_linear_response_admission,
)
from .providers import ProviderResult
from .response_batches import resolve_campaign_relative_path
from .response_reduction import (
    CampaignReductionSummary,
    build_projective_row_plans,
)


ADMISSION_SCHEMA_VERSION = 1
ADMITTED_LINEAR_RESPONSE_DESCRIPTOR = LINEAR_RESPONSE_ADMITTED_DESCRIPTOR
_INPUT_KIND = "m02-linear-response-admission-input"
_PACKAGE_KIND = "m02-linear-response-admission"
_HEX_64 = frozenset("0123456789abcdef")


def _digest_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _digest(value: object, subject: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in _HEX_64 for character in value)
    ):
        raise ValueError(f"{subject} must be a lowercase SHA-256 digest")
    return value


def _mapping(value: object, subject: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or not all(
        isinstance(key, str) for key in value
    ):
        raise ValueError(f"{subject} must be an object")
    return value


def _freeze_json(value: object) -> object:
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze_json(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_json(item) for item in value)
    return value


def _thaw_json(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _thaw_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_thaw_json(item) for item in value]
    return value


def _exact_fields(
    value: Mapping[str, object], expected: frozenset[str], subject: str
) -> None:
    if set(value) != expected:
        raise ValueError(f"{subject} fields are invalid")


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    output: dict[str, object] = {}
    for key, value in pairs:
        if key in output:
            raise ValueError(f"duplicate admission JSON key: {key}")
        output[key] = value
    return output


def _load_json_bytes(data: bytes, subject: str) -> Mapping[str, object]:
    try:
        value = json.loads(
            data,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=lambda item: (_ for _ in ()).throw(
                ValueError(f"{subject} contains non-finite constant {item}")
            ),
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"{subject} must be UTF-8 JSON") from error
    return _mapping(value, subject)


def _load_bound_file(
    base: Path, value: object, subject: str
) -> tuple[Path, bytes]:
    entry = _mapping(value, f"{subject} file")
    _exact_fields(entry, frozenset({"path", "sha256"}), f"{subject} file")
    path = resolve_campaign_relative_path(base, entry["path"])
    if not path.is_file():
        raise ValueError(f"{subject} file is missing")
    data = path.read_bytes()
    if _digest(entry["sha256"], f"{subject} file SHA-256") != _digest_bytes(data):
        raise ValueError(f"{subject} file SHA-256 is invalid")
    return path, data


def _expected_reduction_component_ids() -> tuple[str, ...]:
    return tuple(dict.fromkeys(
        component_id
        for plan in build_projective_row_plans()
        for component_id in (*plan.left_component_ids, *plan.right_component_ids)
    ))


def _validate_complete_reduction(summary: CampaignReductionSummary) -> None:
    plans = build_projective_row_plans()
    expected_rows = tuple(plan.row_id for plan in plans)
    if len(expected_rows) != 174:
        raise ValueError("frozen projective row contract is not exactly 174 rows")
    if (
        summary.reducer_state != "COMPLETE"
        or summary.selected_row_ids != expected_rows
        or len(summary.results) != 174
        or any(result.reducer_state != "COMPLETE" for result in summary.results)
        or summary.missing_component_ids
        or summary.present_component_ids != _expected_reduction_component_ids()
    ):
        raise ValueError("admission requires the complete aligned 174-row reduction")


def _validate_evidence_receipt(value: object) -> Mapping[str, object]:
    receipt = _mapping(value, "admission evidence receipt")
    _exact_fields(
        receipt,
        frozenset({
            "bundle_state", "bundle_sha256", "manifest_sha256",
            "produced_count", "missing_count", "unresolved_leaf_ids",
            "release_domain_fingerprint", "numerical_policy_fingerprint",
            "runtime_fingerprint",
        }),
        "admission evidence receipt",
    )
    unresolved = receipt["unresolved_leaf_ids"]
    if not isinstance(unresolved, list) or len(unresolved) != len(set(unresolved)):
        raise ValueError("admission unresolved leaf IDs are invalid")
    domain = set(B_PRIME_RELEASE_DOMAIN.production_leaf_ids)
    if any(item not in domain for item in unresolved):
        raise ValueError("admission unresolved leaf IDs are off-domain")
    if (
        receipt["bundle_state"] != "complete-operator"
        or receipt["produced_count"] != 553
        or receipt["missing_count"] != 0
        or receipt["release_domain_fingerprint"] != B_PRIME_CONTRACT_SHA256
        or receipt["numerical_policy_fingerprint"]
        != LINEAR_RESPONSE_DESCRIPTOR.numerical_policy_fingerprint
        or not isinstance(receipt["runtime_fingerprint"], str)
        or not receipt["runtime_fingerprint"]
    ):
        raise ValueError("admission evidence receipt is not a complete 553-leaf receipt")
    _digest(receipt["bundle_sha256"], "evidence bundle SHA-256")
    _digest(receipt["manifest_sha256"], "evidence manifest SHA-256")
    return receipt


def _reduction_receipt(summary: CampaignReductionSummary) -> dict[str, object]:
    return {
        "campaign_id": summary.campaign_id,
        "reduction_id": summary.reduction_id,
        "row_count": len(summary.results),
        "row_plan_sha256": summary.row_plan_sha256,
        "source_hashes": list(summary.source_hashes),
    }


@dataclass(frozen=True, slots=True)
class LinearResponseAdmissionPackage:
    request: Mapping[str, object]
    payload: Mapping[str, object]
    evidence_receipt: Mapping[str, object]
    reduction: Mapping[str, object]
    reduction_receipt: Mapping[str, object]
    source_files: Mapping[str, object]
    admission_id: str
    release_admissible: bool = True
    scientific_claims_admitted: bool = False

    def __post_init__(self) -> None:
        for name in (
            "request", "payload", "evidence_receipt", "reduction",
            "reduction_receipt", "source_files",
        ):
            object.__setattr__(self, name, _freeze_json(getattr(self, name)))

    def to_mapping(self) -> dict[str, object]:
        return {
            "schema_version": ADMISSION_SCHEMA_VERSION,
            "kind": _PACKAGE_KIND,
            "descriptor": ADMITTED_LINEAR_RESPONSE_DESCRIPTOR.to_mapping(),
            "request": _thaw_json(self.request),
            "payload": _thaw_json(self.payload),
            "evidence_receipt": _thaw_json(self.evidence_receipt),
            "reduction": _thaw_json(self.reduction),
            "reduction_receipt": _thaw_json(self.reduction_receipt),
            "source_files": _thaw_json(self.source_files),
            "scientific_claims_admitted": False,
            "release_admissible": True,
            "admission_id": self.admission_id,
        }

    @classmethod
    def from_mapping(cls, value: object) -> "LinearResponseAdmissionPackage":
        mapping = _mapping(value, "linear-response admission package")
        _exact_fields(
            mapping,
            frozenset({
                "schema_version", "kind", "descriptor", "request", "payload",
                "evidence_receipt", "reduction", "reduction_receipt",
                "source_files", "scientific_claims_admitted",
                "release_admissible", "admission_id",
            }),
            "linear-response admission package",
        )
        if (
            mapping["schema_version"] != ADMISSION_SCHEMA_VERSION
            or mapping["kind"] != _PACKAGE_KIND
            or mapping["descriptor"]
            != ADMITTED_LINEAR_RESPONSE_DESCRIPTOR.to_mapping()
            or mapping["scientific_claims_admitted"] is not False
            or mapping["release_admissible"] is not True
        ):
            raise ValueError("linear-response admission package envelope is invalid")
        request_mapping = _mapping(mapping["request"], "admission request")
        request = StudyRequest.from_mapping(deepcopy(dict(request_mapping)))
        if request.to_mapping() != request_mapping:
            raise ValueError("admission request is not canonical")
        payload = _mapping(mapping["payload"], "admission payload")
        validate_linear_response_admission(
            request, ADMITTED_LINEAR_RESPONSE_DESCRIPTOR.to_mapping(), payload
        )
        evidence_receipt = _validate_evidence_receipt(mapping["evidence_receipt"])
        reduction = CampaignReductionSummary.from_mapping(mapping["reduction"])
        _validate_complete_reduction(reduction)
        expected_reduction_receipt = _reduction_receipt(reduction)
        if mapping["reduction_receipt"] != expected_reduction_receipt:
            raise ValueError("admission reduction receipt is invalid")
        source_files = _mapping(mapping["source_files"], "admission source files")
        _exact_fields(
            source_files,
            frozenset({"evidence_bundle", "request", "reduction", "payload"}),
            "admission source files",
        )
        for name, digest in source_files.items():
            _digest(digest, f"admission {name} source SHA-256")
        lineage_hashes = set(payload["lineage"]["source_sha256s"])
        required_lineage = {
            evidence_receipt["bundle_sha256"],
            evidence_receipt["manifest_sha256"],
            source_files["reduction"],
            *(item.removeprefix("sha256:") for item in reduction.source_hashes),
        }
        if not required_lineage.issubset(lineage_hashes):
            raise ValueError("admission payload lineage omits evidence receipts")
        material = {
            key: item for key, item in mapping.items() if key != "admission_id"
        }
        expected_id = "m02-admission-" + _digest_bytes(canonical_json_bytes(material))
        if mapping["admission_id"] != expected_id:
            raise ValueError("linear-response admission identity is invalid")
        package = cls(
            request=deepcopy(dict(request_mapping)),
            payload=deepcopy(dict(payload)),
            evidence_receipt=deepcopy(dict(evidence_receipt)),
            reduction=deepcopy(dict(mapping["reduction"])),
            reduction_receipt=deepcopy(dict(expected_reduction_receipt)),
            source_files=deepcopy(dict(source_files)),
            admission_id=expected_id,
        )
        if package.to_mapping() != value:
            raise ValueError("linear-response admission package is not canonical")
        return package


def admit_linear_response_bundle(
    manifest_path: str | Path,
) -> LinearResponseAdmissionPackage:
    path = Path(manifest_path)
    manifest = _load_json_bytes(path.read_bytes(), "admission input manifest")
    _exact_fields(
        manifest,
        frozenset({
            "schema_version", "kind", "evidence_bundle", "request",
            "reduction", "payload",
        }),
        "admission input manifest",
    )
    if (
        manifest["schema_version"] != ADMISSION_SCHEMA_VERSION
        or manifest["kind"] != _INPUT_KIND
    ):
        raise ValueError("admission input manifest envelope is invalid")
    loaded = {
        name: _load_bound_file(path.parent, manifest[name], name)
        for name in ("evidence_bundle", "request", "reduction", "payload")
    }
    evidence_path, evidence_bytes = loaded["evidence_bundle"]
    evidence_summary = load_evidence_bundle(evidence_path)
    evidence_manifest = _load_json_bytes(evidence_bytes, "evidence bundle")
    if (
        evidence_summary.bundle_state != "complete-operator"
        or evidence_summary.produced_count != 553
        or evidence_summary.missing_count != 0
    ):
        raise ValueError("admission requires one complete 553-leaf evidence bundle")
    records = evidence_manifest["produced_records"]
    unresolved_ids = [
        record["leaf_id"]
        for record in records
        if record["numerical_state"] == "UNRESOLVED"
    ]
    request = StudyRequest.from_mapping(
        deepcopy(dict(_load_json_bytes(loaded["request"][1], "admission request")))
    )
    reduction = CampaignReductionSummary.from_mapping(
        _load_json_bytes(loaded["reduction"][1], "campaign reduction")
    )
    _validate_complete_reduction(reduction)
    payload = _load_json_bytes(loaded["payload"][1], "linear-response payload")
    validate_linear_response_admission(
        request, ADMITTED_LINEAR_RESPONSE_DESCRIPTOR.to_mapping(), payload
    )
    evidence_receipt = {
        "bundle_state": evidence_summary.bundle_state,
        "bundle_sha256": evidence_summary.bundle_sha256,
        "manifest_sha256": _digest_bytes(evidence_bytes),
        "produced_count": evidence_summary.produced_count,
        "missing_count": evidence_summary.missing_count,
        "unresolved_leaf_ids": unresolved_ids,
        "release_domain_fingerprint": evidence_manifest["contract"][
            "release_domain_fingerprint"
        ],
        "numerical_policy_fingerprint": evidence_manifest["contract"][
            "numerical_policy_fingerprint"
        ],
        "runtime_fingerprint": evidence_manifest["producer"]["runtime_fingerprint"],
    }
    source_files = {
        name: _digest_bytes(data) for name, (_, data) in loaded.items()
    }
    package_material = {
        "schema_version": ADMISSION_SCHEMA_VERSION,
        "kind": _PACKAGE_KIND,
        "descriptor": ADMITTED_LINEAR_RESPONSE_DESCRIPTOR.to_mapping(),
        "request": request.to_mapping(),
        "payload": deepcopy(dict(payload)),
        "evidence_receipt": evidence_receipt,
        "reduction": reduction.to_mapping(),
        "reduction_receipt": _reduction_receipt(reduction),
        "source_files": source_files,
        "scientific_claims_admitted": False,
        "release_admissible": True,
    }
    package_material["admission_id"] = (
        "m02-admission-" + _digest_bytes(canonical_json_bytes(package_material))
    )
    return LinearResponseAdmissionPackage.from_mapping(package_material)


def load_linear_response_admission(
    path: str | Path,
) -> LinearResponseAdmissionPackage:
    return LinearResponseAdmissionPackage.from_mapping(
        _load_json_bytes(Path(path).read_bytes(), "linear-response admission package")
    )


class AdmittedLinearResponseProvider:
    descriptor = ADMITTED_LINEAR_RESPONSE_DESCRIPTOR

    def __init__(self, package: LinearResponseAdmissionPackage) -> None:
        if not isinstance(package, LinearResponseAdmissionPackage):
            raise ValueError("admitted provider requires a validated package")
        LinearResponseAdmissionPackage.from_mapping(package.to_mapping())
        self._package = package

    def execute(
        self, request: StudyRequest, upstream: Mapping[Capability, object]
    ) -> ProviderResult:
        if request.to_mapping() != _thaw_json(self._package.request):
            raise ValueError("admission package does not bind this request")
        if set(upstream) != {Capability.SPECTRAL_CORE}:
            raise ValueError("linear-response provider requires the spectral artifact")
        numerical = (
            NumericalState.UNRESOLVED
            if self._package.evidence_receipt["unresolved_leaf_ids"]
            else NumericalState.ACCEPTED
        )
        return ProviderResult(
            payload=_thaw_json(self._package.payload),
            evidence=EvidenceState(
                carrier=CarrierState.VALID,
                execution=ExecutionState.SUCCEEDED,
                numerical=numerical,
                scientific=ScientificState.NOT_EVALUATED,
            ),
        )
