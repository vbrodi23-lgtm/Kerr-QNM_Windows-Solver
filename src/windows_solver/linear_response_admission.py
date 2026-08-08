"""Fail-closed admission package and evidence-bound linear-response provider."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, replace
import hashlib
import json
from pathlib import Path
from types import MappingProxyType
from typing import Mapping

from .artifacts import ArtifactEnvelope
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
from .response_engine import (
    bound_spectral_root_mapping_for_leaf,
    campaign_spectral_receipt,
)
from .spectrum import (
    SPECTRAL_OUTPUT_ARTIFACT_TYPE,
    SpectralCatalogProvider,
    build_spectral_payload,
    validate_spectral_payload,
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


def _array(value: object, subject: str) -> list[object]:
    if not isinstance(value, (list, tuple)):
        raise ValueError(f"{subject} must be an array")
    return list(value)


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
            "campaign_root_set_sha256",
        }),
        "admission evidence receipt",
    )
    unresolved = receipt["unresolved_leaf_ids"]
    if (
        not isinstance(unresolved, list)
        or any(not isinstance(item, str) for item in unresolved)
        or len(unresolved) != len(set(unresolved))
    ):
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
        or receipt["campaign_root_set_sha256"]
        != campaign_spectral_receipt()["root_set_sha256"]
    ):
        raise ValueError("admission evidence receipt is not a complete 553-leaf receipt")
    _digest(receipt["bundle_sha256"], "evidence bundle SHA-256")
    _digest(receipt["manifest_sha256"], "evidence manifest SHA-256")
    _digest(
        receipt["campaign_root_set_sha256"],
        "campaign root-set SHA-256",
    )
    return receipt


def _reduction_receipt(summary: CampaignReductionSummary) -> dict[str, object]:
    return {
        "campaign_id": summary.campaign_id,
        "reduction_id": summary.reduction_id,
        "row_count": len(summary.results),
        "row_plan_sha256": summary.row_plan_sha256,
        "source_hashes": list(summary.source_hashes),
    }


def _spectral_upstream_receipt(request: StudyRequest) -> dict[str, object]:
    scoped_request = request.for_capability(Capability.SPECTRAL_CORE)
    payload = build_spectral_payload(scoped_request)
    return {
        "artifact_type": SPECTRAL_OUTPUT_ARTIFACT_TYPE,
        "capability": Capability.SPECTRAL_CORE.value,
        "provider": SpectralCatalogProvider.descriptor.to_mapping(),
        "request": scoped_request.to_mapping(),
        "payload_sha256": _digest_bytes(canonical_json_bytes(payload)),
        "evidence": {
            "carrier": CarrierState.VALID.value,
            "execution": ExecutionState.SUCCEEDED.value,
            "numerical": NumericalState.ACCEPTED.value,
            "scientific": ScientificState.NOT_EVALUATED.value,
        },
    }


def _validate_spectral_upstream_receipt(
    request: StudyRequest, value: object
) -> Mapping[str, object]:
    receipt = _mapping(value, "admission spectral upstream receipt")
    expected = _spectral_upstream_receipt(request)
    if receipt != expected:
        raise ValueError(
            "admission spectral upstream receipt does not match the admitted catalog"
        )
    return receipt


def _validate_campaign_spectral_bindings(
    records: object,
    receipt_value: object,
    request: StudyRequest,
) -> Mapping[str, object]:
    receipt = _mapping(receipt_value, "campaign spectral receipt")
    expected_receipt = campaign_spectral_receipt()
    if receipt != expected_receipt:
        raise ValueError(
            "admission campaign roots do not match the installed spectral catalog"
        )
    spectral_request = request.for_capability(Capability.SPECTRAL_CORE)
    spectral_payload = build_spectral_payload(spectral_request)
    spectral_roots: dict[tuple[object, ...], Mapping[str, object]] = {}
    for raw_root in _array(
        spectral_payload["roots"], "admission spectral payload roots"
    ):
        root = _mapping(raw_root, "admission spectral payload root")
        mode = _mapping(root["mode"], "admission spectral payload mode")
        identity = (
            mode["ell"], mode["m"], mode["n"], root["spin_binary64_hex"]
        )
        spectral_roots[identity] = root

    seen: dict[str, Mapping[str, object]] = {}
    for raw_record in _array(records, "admission produced records"):
        record = _mapping(raw_record, "admission produced record")
        expected_root = bound_spectral_root_mapping_for_leaf(record["leaf_id"])
        actual_root = _mapping(
            record["root_identity"], "admission campaign root identity"
        )
        actual_digest = _digest(
            record["root_identity_sha256"],
            "admission campaign root identity SHA-256",
        )
        if (
            actual_root != expected_root
            or _digest_bytes(canonical_json_bytes(actual_root)) != actual_digest
        ):
            raise ValueError(
                "admission campaign root identity does not match the installed catalog"
            )
        mode = record["mode"]
        coordinate = _mapping(
            record["sampling_coordinate"], "admission record coordinate"
        )
        spectral_root = spectral_roots.get(
            (*mode, coordinate["spin_binary64_hex"])
        )
        if spectral_root is None or expected_root["owner_record"] != spectral_root:
            raise ValueError(
                "admission campaign root values do not match the spectral payload"
            )
        seen.setdefault(actual_digest, actual_root)
    if (
        len(seen) != receipt["root_count"]
        or _digest_bytes(canonical_json_bytes(list(seen.values())))
        != receipt["root_set_sha256"]
        or receipt["provider"]
        != SpectralCatalogProvider.descriptor.to_mapping()
    ):
        raise ValueError(
            "admission campaign root set does not match the spectral receipt"
        )
    return receipt


def _validate_component_evidence_bindings(
    evidence_directory: Path,
    records: object,
    components: object,
) -> None:
    records_by_identity: dict[tuple[object, ...], Mapping[str, object]] = {}
    for raw_record in records:
        record = _mapping(raw_record, "admission produced record")
        coordinate = _mapping(
            record["sampling_coordinate"], "admission record coordinate"
        )
        identity = (
            *record["mode"],
            coordinate["spin_binary64_hex"],
            record["mechanism_id"],
        )
        records_by_identity[identity] = record

    components_by_identity: dict[tuple[object, ...], Mapping[str, object]] = {}
    for raw_component in components:
        component = _mapping(raw_component, "admission response component")
        mode = _mapping(component["mode"], "admission component mode")
        mechanism = _mapping(
            component["mechanism"], "admission component mechanism"
        )
        identity = (
            mode["ell"],
            mode["m"],
            mode["n"],
            component["spin_binary64_hex"],
            mechanism["mechanism_id"],
        )
        components_by_identity[identity] = component

    if (
        len(records_by_identity) != 553
        or len(components_by_identity) != 553
        or set(records_by_identity) != set(components_by_identity)
    ):
        raise ValueError(
            "admission evidence records do not match response component identities"
        )

    for identity, component in components_by_identity.items():
        record = records_by_identity[identity]
        if record["numerical_state"] != component["numerical_state"]:
            raise ValueError(
                "admission component numerical state does not match evidence record"
            )
        if record["root_reference_id"] != component["baseline_root_reference_id"]:
            raise ValueError(
                "admission component root reference does not match evidence record"
            )
        component_path = resolve_campaign_relative_path(
            evidence_directory, record["payload_path"]
        )
        component_bytes = component_path.read_bytes()
        if (
            len(component_bytes) != record["payload_size"]
            or _digest_bytes(component_bytes) != record["payload_sha256"]
        ):
            raise ValueError(
                "admission produced component payload changed after authentication"
            )
        authenticated_component = _load_json_bytes(
            component_bytes, "admission produced component payload"
        )
        if authenticated_component != component:
            raise ValueError(
                "admission authenticated payload does not match component"
            )


def _validate_projective_reduction_bindings(
    summary: CampaignReductionSummary,
    payload: Mapping[str, object],
) -> None:
    comparisons = _array(
        payload["projective_comparisons"], "admission projective comparisons"
    )
    if len(comparisons) != 174:
        raise ValueError(
            "admission requires exactly 174 projective comparisons from the reduction"
        )
    components_by_identity: dict[tuple[object, ...], Mapping[str, object]] = {}
    for raw_component in _array(
        payload["response_components"], "admission response components"
    ):
        component = _mapping(raw_component, "admission response component")
        mode = _mapping(component["mode"], "admission component mode")
        mechanism = _mapping(
            component["mechanism"], "admission component mechanism"
        )
        identity = (
            mode["ell"], mode["m"], mode["n"],
            component["spin_binary64_hex"], mechanism["mechanism_id"],
        )
        components_by_identity[identity] = component
    leaves = {
        leaf.leaf_id: leaf for leaf in B_PRIME_RELEASE_DOMAIN.production_leaves
    }

    def component_for_leaf(leaf_id: str) -> Mapping[str, object]:
        leaf = leaves[leaf_id]
        return components_by_identity[
            (*leaf.mode, leaf.spin.hex(), leaf.mechanism_id)
        ]

    covariance_blocks: dict[str, Mapping[str, object]] = {}
    for raw_block in _array(
        payload["covariance_blocks"], "admission covariance blocks"
    ):
        block = _mapping(raw_block, "admission covariance block")
        covariance_id = block.get("covariance_id")
        if (
            not isinstance(covariance_id, str)
            or covariance_id in covariance_blocks
        ):
            raise ValueError("admission covariance block identities are invalid")
        covariance_blocks[covariance_id] = block
    grams = {item.construction_id: item for item in summary.empirical_grams}
    referenced_grams: set[str] = set()

    for raw_comparison, plan, result in zip(
        comparisons, summary.plans, summary.results
    ):
        comparison = _mapping(raw_comparison, "admission projective comparison")
        left = tuple(
            component_for_leaf(component_id)
            for component_id in plan.left_component_ids
        )
        right = tuple(
            component_for_leaf(component_id)
            for component_id in plan.right_component_ids
        )
        expected = {
            "comparison_id": result.row_id,
            "mode_order": [component["mode"] for component in left],
            "left_component_ids": [
                component["component_id"] for component in left
            ],
            "right_component_ids": [
                component["component_id"] for component in right
            ],
            "calibration_mode": component_for_leaf(
                plan.calibration_component_ids[0]
            )["mode"],
            "calibration_numerator_component_id": component_for_leaf(
                plan.calibration_component_ids[0]
            )["component_id"],
            "calibration_denominator_component_id": component_for_leaf(
                plan.calibration_component_ids[1]
            )["component_id"],
            "empirical_gram_id": result.empirical_gram_id,
            "nominal_angle_radians": result.nominal_angle_radians,
            "bounded_angle_interval_radians": (
                None
                if result.bounded_angle_interval_radians is None
                else list(result.bounded_angle_interval_radians)
            ),
            "calibration_disk_contains_zero": (
                result.calibration_disk_contains_zero
            ),
            "projective_outcome": result.projective_outcome,
            "scientific_state": result.scientific_state,
            "reason": result.reason,
        }
        if any(comparison.get(key) != value for key, value in expected.items()):
            raise ValueError(
                "admission projective comparison does not match reduction row"
            )
        gram_id = result.empirical_gram_id
        if gram_id is None:
            if comparison.get("covariance_id") is not None:
                raise ValueError(
                    "admission unresolved row has unsealed covariance"
                )
            continue
        referenced_grams.add(gram_id)
        if comparison.get("covariance_id") != gram_id:
            raise ValueError(
                "admission covariance identity does not match reduction Gram"
            )
        block = covariance_blocks.get(gram_id)
        gram = grams.get(gram_id)
        if block is None or gram is None:
            raise ValueError("admission reduction Gram covariance is missing")
        expected_basis = [
            (component["component_id"], quadrature)
            for component in (*left, *right)
            for quadrature in ("real", "imaginary")
        ]
        actual_basis: list[tuple[object, object]] = []
        for raw_entry in _array(
            block.get("basis"), "admission covariance basis"
        ):
            entry = _mapping(raw_entry, "admission covariance basis entry")
            actual_basis.append(
                (entry.get("component_id"), entry.get("quadrature"))
            )
        actual_matrix = [
            _array(row, "admission covariance matrix row")
            for row in _array(
                block.get("matrix"), "admission covariance matrix"
            )
        ]
        if (
            actual_basis != expected_basis
            or actual_matrix != [list(row) for row in gram.matrix]
        ):
            raise ValueError(
                "admission covariance basis or matrix does not match reduction Gram"
            )
    if referenced_grams != set(grams):
        raise ValueError("admission reduction Gram references are incomplete")
    for covariance_id, block in covariance_blocks.items():
        if covariance_id in referenced_grams:
            continue
        component_ids = {
            _mapping(entry, "admission covariance basis entry").get(
                "component_id"
            )
            for entry in _array(
                block.get("basis"), "admission covariance basis"
            )
        }
        if len(component_ids) != 1:
            raise ValueError(
                "admission contains unsealed cross-component covariance"
            )


@dataclass(frozen=True, slots=True)
class LinearResponseAdmissionPackage:
    request: Mapping[str, object]
    payload: Mapping[str, object]
    evidence_receipt: Mapping[str, object]
    spectral_upstream_receipt: Mapping[str, object]
    reduction: Mapping[str, object]
    reduction_receipt: Mapping[str, object]
    source_files: Mapping[str, object]
    admission_id: str
    release_admissible: bool = True
    scientific_claims_admitted: bool = False

    def __post_init__(self) -> None:
        for name in (
            "request", "payload", "evidence_receipt", "reduction",
            "spectral_upstream_receipt", "reduction_receipt", "source_files",
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
            "spectral_upstream_receipt": _thaw_json(
                self.spectral_upstream_receipt
            ),
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
                "evidence_receipt", "spectral_upstream_receipt", "reduction",
                "reduction_receipt", "source_files",
                "scientific_claims_admitted", "release_admissible",
                "admission_id",
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
        spectral_upstream_receipt = _validate_spectral_upstream_receipt(
            request, mapping["spectral_upstream_receipt"]
        )
        reduction = CampaignReductionSummary.from_mapping(mapping["reduction"])
        _validate_complete_reduction(reduction)
        _validate_projective_reduction_bindings(reduction, payload)
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
            spectral_upstream_receipt=deepcopy(
                dict(spectral_upstream_receipt)
            ),
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
    campaign_root_receipt = _validate_campaign_spectral_bindings(
        records,
        evidence_manifest["contract"]["campaign_spectral_receipt"],
        request,
    )
    _validate_component_evidence_bindings(
        evidence_path.parent, records, payload["response_components"]
    )
    _validate_projective_reduction_bindings(reduction, payload)
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
        "campaign_root_set_sha256": campaign_root_receipt["root_set_sha256"],
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
        "spectral_upstream_receipt": _spectral_upstream_receipt(request),
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
    *,
    expected_admission_id: str,
) -> LinearResponseAdmissionPackage:
    package = LinearResponseAdmissionPackage.from_mapping(
        _load_json_bytes(Path(path).read_bytes(), "linear-response admission package")
    )
    if (
        not isinstance(expected_admission_id, str)
        or expected_admission_id != package.admission_id
    ):
        raise ValueError(
            "linear-response package does not match expected admission identity"
        )
    return package


class AdmittedLinearResponseProvider:
    descriptor = ADMITTED_LINEAR_RESPONSE_DESCRIPTOR

    def __init__(
        self,
        package: LinearResponseAdmissionPackage,
        *,
        expected_admission_id: str,
    ) -> None:
        if not isinstance(package, LinearResponseAdmissionPackage):
            raise ValueError("admitted provider requires a validated package")
        LinearResponseAdmissionPackage.from_mapping(package.to_mapping())
        if package.admission_id != expected_admission_id:
            raise ValueError(
                "admitted provider package does not match expected admission identity"
            )
        self.descriptor = replace(
            ADMITTED_LINEAR_RESPONSE_DESCRIPTOR,
            implementation_version=(
                ADMITTED_LINEAR_RESPONSE_DESCRIPTOR.implementation_version
                + "+"
                + package.admission_id
            ),
        )
        self._package = package

    def execute(
        self, request: StudyRequest, upstream: Mapping[Capability, object]
    ) -> ProviderResult:
        if request.to_mapping() != _thaw_json(self._package.request):
            raise ValueError("admission package does not bind this request")
        if set(upstream) != {Capability.SPECTRAL_CORE}:
            raise ValueError("linear-response provider requires the spectral artifact")
        spectral = upstream[Capability.SPECTRAL_CORE]
        if not isinstance(spectral, ArtifactEnvelope):
            raise ValueError("linear-response spectral upstream is not an artifact")
        receipt = _thaw_json(self._package.spectral_upstream_receipt)
        actual = {
            "artifact_type": spectral.artifact_type,
            "capability": spectral.capability.value,
            "provider": _thaw_json(spectral.provider),
            "request": _thaw_json(spectral.request),
            "payload_sha256": _digest_bytes(
                canonical_json_bytes(_thaw_json(spectral.payload))
            ),
            "evidence": spectral.evidence.to_mapping(),
        }
        if actual != receipt:
            raise ValueError(
                "linear-response spectral upstream does not match admission receipt"
            )
        validate_spectral_payload(
            request.for_capability(Capability.SPECTRAL_CORE),
            spectral.provider,
            spectral.payload,
        )
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
