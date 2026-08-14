from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from windows_solver.artifacts import ArtifactEnvelope
from windows_solver.builtin import default_registry
from windows_solver.contracts import (
    Capability,
    CarrierState,
    EvidenceState,
    ExecutionState,
    NumericalState,
    ScientificState,
    StudyRequest,
    canonical_json_bytes,
)
from windows_solver.evidence_intake import (
    B_PRIME_RELEASE_DOMAIN,
    evidence_bundle_digest,
)
from windows_solver.linear_response_admission import (
    ADMITTED_LINEAR_RESPONSE_DESCRIPTOR,
    AdmittedLinearResponseProvider,
    LinearResponseAdmissionPackage,
    _validate_projective_reduction_bindings,
    admit_linear_response_bundle,
    load_linear_response_admission,
    validate_linear_response_bundle,
)
from windows_solver.providers import ProviderUnavailableError
from windows_solver.response_reduction import (
    ComputedUnresolvedComponentEvidence,
    ResolvedComponentEvidence,
    SignedErrorContribution,
    build_projective_row_plans,
    reduce_projective_rows,
)
from windows_solver.spectrum import (
    SPECTRAL_OUTPUT_ARTIFACT_TYPE,
    SpectralCatalogProvider,
    build_spectral_payload,
)

from tests.test_linear_response_contract import b_prime_payload, b_prime_request
from tests.test_linear_response_evidence_intake import _write_manifest


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


_APPROVED_REGULARISED_GSN_REVIEW_POLICY = {
    "human_math_review_receipt_status": "approved/v1",
    "human_math_review_receipt_sha256": "a" * 64,
    "independent_reference_fixture_receipt_status": "reviewed/v1",
    "independent_reference_fixture_receipt_sha256": "b" * 64,
}


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json_bytes(value))


def _spectral_upstream(request: StudyRequest) -> ArtifactEnvelope:
    scoped = request.for_capability(Capability.SPECTRAL_CORE)
    return ArtifactEnvelope(
        schema_version=1,
        artifact_type=SPECTRAL_OUTPUT_ARTIFACT_TYPE,
        capability=Capability.SPECTRAL_CORE,
        provider=SpectralCatalogProvider.descriptor.to_mapping(),
        request=scoped.to_mapping(),
        upstream_artifact_ids=("0" * 64,),
        payload=build_spectral_payload(scoped),
        evidence=EvidenceState(
            carrier=CarrierState.VALID,
            execution=ExecutionState.SUCCEEDED,
            numerical=NumericalState.ACCEPTED,
            scientific=ScientificState.NOT_EVALUATED,
        ),
    )


def _projective_comparisons(
    reduction: object, payload: dict[str, object]
) -> list[dict[str, object]]:
    components_by_identity = {
        (
            component["mode"]["ell"],
            component["mode"]["m"],
            component["mode"]["n"],
            component["spin_binary64_hex"],
            component["mechanism"]["mechanism_id"],
        ): component
        for component in payload["response_components"]
    }
    leaves = {
        leaf.leaf_id: leaf for leaf in B_PRIME_RELEASE_DOMAIN.production_leaves
    }

    def component(leaf_id: str) -> dict[str, object]:
        leaf = leaves[leaf_id]
        return components_by_identity[
            (*leaf.mode, leaf.spin.hex(), leaf.mechanism_id)
        ]

    return [
        {
            "comparison_id": result.row_id,
            "mode_order": [
                component(component_id)["mode"]
                for component_id in plan.left_component_ids
            ],
            "left_component_ids": [
                component(component_id)["component_id"]
                for component_id in plan.left_component_ids
            ],
            "right_component_ids": [
                component(component_id)["component_id"]
                for component_id in plan.right_component_ids
            ],
            "calibration_mode": component(
                plan.calibration_component_ids[0]
            )["mode"],
            "calibration_numerator_component_id": (
                component(plan.calibration_component_ids[0])["component_id"]
            ),
            "calibration_denominator_component_id": (
                component(plan.calibration_component_ids[1])["component_id"]
            ),
            "covariance_id": None,
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
        for plan, result in zip(reduction.plans, reduction.results)
    ]


def _admission_fixture(
    directory: Path,
    *,
    complete: bool,
    first_component_reason: str | None = None,
) -> Path:
    evidence_directory = directory / "evidence"
    leaves = list(B_PRIME_RELEASE_DOMAIN.production_leaves)
    manifest = _write_manifest(
        evidence_directory,
        leaves if complete else leaves[:1],
        state="complete-operator" if complete else "partial-smoke",
    )
    for record in manifest["produced_records"]:
        record["numerical_state"] = "UNRESOLVED"

    request = b_prime_request()
    request_path = directory / "request.json"
    _write_json(request_path, request.to_mapping())

    payload = b_prime_payload(request)
    if first_component_reason is not None:
        payload["response_components"][0]["result"]["reason"] = (
            first_component_reason
        )
    components_by_identity = {
        (
            component["mode"]["ell"],
            component["mode"]["m"],
            component["mode"]["n"],
            component["spin_binary64_hex"],
            component["mechanism"]["mechanism_id"],
        ): component
        for component in payload["response_components"]
    }
    for record in manifest["produced_records"]:
        record_identity = (
            *record["mode"],
            record["sampling_coordinate"]["spin_binary64_hex"],
            record["mechanism_id"],
        )
        component_bytes = canonical_json_bytes(
            components_by_identity[record_identity]
        )
        component_path = evidence_directory / record["payload_path"]
        component_path.write_bytes(component_bytes)
        record["payload_size"] = len(component_bytes)
        record["payload_sha256"] = _sha256(component_bytes)
    manifest["bundle_sha256"] = evidence_bundle_digest(manifest)
    evidence_path = evidence_directory / "evidence-bundle.json"
    _write_json(evidence_path, manifest)
    evidence_receipt = "sha256:" + _sha256(evidence_path.read_bytes())

    plans = build_projective_row_plans()
    component_ids = tuple(dict.fromkeys(
        component_id
        for plan in plans
        for component_id in (*plan.left_component_ids, *plan.right_component_ids)
    ))
    components = {
        component_id: ComputedUnresolvedComponentEvidence(
            component_id=component_id,
            units="M-delta-omega-per-native-coordinate",
            contributions=(SignedErrorContribution(
                channel_id=f"local:{component_id}:signed-root",
                family="signed-root",
                shared_group=component_id,
                delta=0.0j,
                units="M-delta-omega-per-native-coordinate",
                source_receipt=evidence_receipt,
                scope="local",
            ),),
            reason="structural test bundle; no scientific value claimed",
            source_receipt=evidence_receipt,
            evidence_kind="authenticated-campaign",
        )
        for component_id in component_ids
    }
    reduction = reduce_projective_rows(
        "structural-test-campaign",
        tuple(plan.row_id for plan in plans),
        components,
        source_hashes=(evidence_receipt,),
    )
    payload["projective_comparisons"] = _projective_comparisons(
        reduction, payload
    )
    reduction_path = directory / "reduction.json"
    _write_json(reduction_path, reduction.to_mapping())

    payload["lineage"]["source_sha256s"] = [
        manifest["bundle_sha256"],
        evidence_receipt.removeprefix("sha256:"),
        _sha256(reduction_path.read_bytes()),
    ]
    payload_path = directory / "payload.json"
    _write_json(payload_path, payload)

    admission_manifest = {
        "schema_version": 1,
        "kind": "m02-linear-response-admission-input",
        "evidence_bundle": {
            "path": "evidence/evidence-bundle.json",
            "sha256": _sha256(evidence_path.read_bytes()),
        },
        "request": {"path": "request.json", "sha256": _sha256(request_path.read_bytes())},
        "reduction": {
            "path": "reduction.json",
            "sha256": _sha256(reduction_path.read_bytes()),
        },
        "payload": {"path": "payload.json", "sha256": _sha256(payload_path.read_bytes())},
    }
    admission_path = directory / "admission-input.json"
    _write_json(admission_path, admission_manifest)
    return admission_path


class RegularisedGSNReleaseGateTests(unittest.TestCase):
    def test_structural_validation_remains_open_without_review_receipts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            manifest = _admission_fixture(Path(temporary), complete=True)

            summary = validate_linear_response_bundle(manifest)

        self.assertEqual(summary["produced_leaf_count"], 212)
        self.assertFalse(summary["scientific_claims_admitted"])
        self.assertFalse(summary["release_admissible"])

    def test_release_admission_is_blocked_without_review_receipts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            manifest = _admission_fixture(Path(temporary), complete=True)

            with self.assertRaisesRegex(
                ValueError, "human mathematical review receipt"
            ):
                admit_linear_response_bundle(manifest)

    def test_each_review_receipt_must_be_sha_bound(self) -> None:
        policies = {
            "missing_human_digest": {
                **_APPROVED_REGULARISED_GSN_REVIEW_POLICY,
                "human_math_review_receipt_sha256": None,
            },
            "unreviewed_reference": {
                **_APPROVED_REGULARISED_GSN_REVIEW_POLICY,
                "independent_reference_fixture_receipt_status": (
                    "absent-unreviewed/v1"
                ),
                "independent_reference_fixture_receipt_sha256": None,
            },
        }
        for label, policy in policies.items():
            with (
                self.subTest(label=label),
                tempfile.TemporaryDirectory() as temporary,
            ):
                manifest = _admission_fixture(Path(temporary), complete=True)
                with patch(
                    "windows_solver.linear_response_admission."
                    "regularised_gsn_precision_policy",
                    return_value=policy,
                ):
                    with self.assertRaises(ValueError):
                        admit_linear_response_bundle(manifest)


class LinearResponseAdmissionTests(unittest.TestCase):
    def setUp(self) -> None:
        review_policy = patch(
            "windows_solver.linear_response_admission."
            "regularised_gsn_precision_policy",
            return_value=_APPROVED_REGULARISED_GSN_REVIEW_POLICY,
        )
        review_policy.start()
        self.addCleanup(review_policy.stop)

    def test_role_scoped_request_derives_exact_sparse_spectral_upstream(self) -> None:
        request = b_prime_request().for_capability(Capability.SPECTRAL_CORE)
        self.assertEqual(
            set(request.numerical_policy), {"exact-spectral-selection"}
        )
        payload = build_spectral_payload(request)
        self.assertEqual(payload["requested_root_count"], 48)
        self.assertEqual(len(payload["roots"]), 48)

    def test_partial_bundle_cannot_register_provider(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            manifest = _admission_fixture(Path(temporary), complete=False)
            with self.assertRaisesRegex(ValueError, "212|complete"):
                admit_linear_response_bundle(manifest)
        with self.assertRaises(ProviderUnavailableError):
            default_registry().resolve(Capability.LINEAR_RESPONSE)

    def test_complete_structural_bundle_transitions_one_provider_without_claim(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            package = admit_linear_response_bundle(
                _admission_fixture(Path(temporary), complete=True)
            )
            self.assertTrue(package.release_admissible)
            self.assertFalse(package.scientific_claims_admitted)
            self.assertEqual(
                dict(package.regularised_gsn_review_receipts),
                _APPROVED_REGULARISED_GSN_REVIEW_POLICY,
            )
            self.assertEqual(package.evidence_receipt["produced_count"], 212)
            self.assertEqual(package.reduction_receipt["row_count"], 57)

            provider = AdmittedLinearResponseProvider(
                package, expected_admission_id=package.admission_id
            )
            expected_descriptor = ADMITTED_LINEAR_RESPONSE_DESCRIPTOR.to_mapping()
            expected_descriptor["implementation_version"] += (
                "+" + package.admission_id
            )
            self.assertEqual(provider.descriptor.to_mapping(), expected_descriptor)
            registry = default_registry(provider)
            self.assertIs(registry.resolve(Capability.LINEAR_RESPONSE), provider)
            result = provider.execute(
                b_prime_request(),
                {Capability.SPECTRAL_CORE: _spectral_upstream(b_prime_request())},
            )
            self.assertEqual(result.payload, package.to_mapping()["payload"])
            self.assertEqual(result.evidence.scientific.value, "NOT_EVALUATED")

            with self.assertRaises(TypeError):
                package.payload["quantity"] = "mutated-after-admission"
            with self.assertRaisesRegex(ValueError, "expected admission identity"):
                AdmittedLinearResponseProvider(
                    package, expected_admission_id="m02-admission-" + "0" * 64
                )

    def test_admitted_provider_rejects_spectral_provider_and_root_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            package = admit_linear_response_bundle(
                _admission_fixture(Path(temporary), complete=True)
            )
        request = b_prime_request()
        provider = AdmittedLinearResponseProvider(
            package, expected_admission_id=package.admission_id
        )
        upstream = _spectral_upstream(request)

        forged_provider = dict(upstream.provider)
        forged_provider["numerical_policy_fingerprint"] = "different-catalog"
        provider_drift = ArtifactEnvelope(
            schema_version=upstream.schema_version,
            artifact_type=upstream.artifact_type,
            capability=upstream.capability,
            provider=forged_provider,
            request=dict(upstream.request),
            upstream_artifact_ids=upstream.upstream_artifact_ids,
            payload=dict(upstream.payload),
            evidence=upstream.evidence,
        )
        with self.assertRaisesRegex(ValueError, "spectral upstream"):
            provider.execute(request, {Capability.SPECTRAL_CORE: provider_drift})

        forged_payload = upstream.identity_mapping()["payload"]
        forged_payload["roots"][0]["frequency"]["real"] += 1.0e-12
        root_drift = ArtifactEnvelope(
            schema_version=upstream.schema_version,
            artifact_type=upstream.artifact_type,
            capability=upstream.capability,
            provider=dict(upstream.provider),
            request=dict(upstream.request),
            upstream_artifact_ids=upstream.upstream_artifact_ids,
            payload=forged_payload,
            evidence=upstream.evidence,
        )
        with self.assertRaisesRegex(ValueError, "spectral upstream"):
            provider.execute(request, {Capability.SPECTRAL_CORE: root_drift})

    def test_admission_rejects_campaign_roots_from_another_catalog(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            admission_path = _admission_fixture(directory, complete=True)
            evidence_path = directory / "evidence" / "evidence-bundle.json"
            evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
            first = evidence["produced_records"][0]
            original_digest = first["root_identity_sha256"]
            for record in evidence["produced_records"]:
                if record["root_identity_sha256"] == original_digest:
                    record["root_identity"]["omega"]["real"] += 1.0e-12
                    record["root_identity_sha256"] = _sha256(
                        canonical_json_bytes(record["root_identity"])
                    )
            roots: dict[str, dict[str, object]] = {}
            for record in evidence["produced_records"]:
                roots.setdefault(
                    record["root_identity_sha256"], record["root_identity"]
                )
            receipt = evidence["contract"]["campaign_spectral_receipt"]
            receipt["root_count"] = len(roots)
            receipt["root_set_sha256"] = _sha256(
                canonical_json_bytes(list(roots.values()))
            )
            evidence["bundle_sha256"] = evidence_bundle_digest(evidence)
            _write_json(evidence_path, evidence)

            payload_path = directory / "payload.json"
            payload = json.loads(payload_path.read_text(encoding="utf-8"))
            for digest in (
                evidence["bundle_sha256"],
                _sha256(evidence_path.read_bytes()),
            ):
                if digest not in payload["lineage"]["source_sha256s"]:
                    payload["lineage"]["source_sha256s"].append(digest)
            _write_json(payload_path, payload)

            admission = json.loads(admission_path.read_text(encoding="utf-8"))
            admission["evidence_bundle"]["sha256"] = _sha256(
                evidence_path.read_bytes()
            )
            admission["payload"]["sha256"] = _sha256(payload_path.read_bytes())
            _write_json(admission_path, admission)
            with self.assertRaisesRegex(ValueError, "campaign roots"):
                admit_linear_response_bundle(admission_path)

    def test_admission_package_revalidates_content_and_rejects_tamper(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            package = admit_linear_response_bundle(
                _admission_fixture(Path(temporary), complete=True)
            )
        mapping = package.to_mapping()
        self.assertEqual(mapping["schema_version"], 2)
        self.assertEqual(LinearResponseAdmissionPackage.from_mapping(mapping), package)
        forged = deepcopy(mapping)
        forged["evidence_receipt"]["produced_count"] = 211
        with self.assertRaisesRegex(ValueError, "evidence|identity|212"):
            LinearResponseAdmissionPackage.from_mapping(forged)

        malformed = deepcopy(mapping)
        malformed["evidence_receipt"]["unresolved_leaf_ids"] = [{}]
        with self.assertRaisesRegex(ValueError, "unresolved leaf IDs"):
            LinearResponseAdmissionPackage.from_mapping(malformed)

        unapproved_review = deepcopy(mapping)
        unapproved_review["regularised_gsn_review_receipts"][
            "human_math_review_receipt_status"
        ] = "absent-unapproved/v1"
        material = {
            key: value for key, value in unapproved_review.items()
            if key != "admission_id"
        }
        unapproved_review["admission_id"] = (
            "m02-admission-" + _sha256(canonical_json_bytes(material))
        )
        with self.assertRaisesRegex(ValueError, "human mathematical review"):
            LinearResponseAdmissionPackage.from_mapping(unapproved_review)

        mismatched_spectral = deepcopy(mapping)
        mismatched_spectral["spectral_upstream_receipt"]["payload_sha256"] = (
            "0" * 64
        )
        material = {
            key: value for key, value in mismatched_spectral.items()
            if key != "admission_id"
        }
        mismatched_spectral["admission_id"] = (
            "m02-admission-" + _sha256(canonical_json_bytes(material))
        )
        with self.assertRaisesRegex(ValueError, "spectral upstream receipt"):
            LinearResponseAdmissionPackage.from_mapping(mismatched_spectral)

        mismatched_reduction = deepcopy(mapping)
        mismatched_reduction["payload"]["projective_comparisons"][0][
            "reason"
        ] = "resealed unrelated projective conclusion"
        material = {
            key: value for key, value in mismatched_reduction.items()
            if key != "admission_id"
        }
        mismatched_reduction["admission_id"] = (
            "m02-admission-" + _sha256(canonical_json_bytes(material))
        )
        with self.assertRaisesRegex(ValueError, "projective.*reduction"):
            LinearResponseAdmissionPackage.from_mapping(mismatched_reduction)

        with tempfile.TemporaryDirectory() as temporary:
            tampered = deepcopy(mapping)
            tampered["payload"]["response_components"][0]["result"]["reason"] = (
                "modified after admission"
            )
            material = {
                key: value for key, value in tampered.items()
                if key != "admission_id"
            }
            tampered["admission_id"] = (
                "m02-admission-" + _sha256(canonical_json_bytes(material))
            )
            path = Path(temporary) / "tampered-admission.json"
            _write_json(path, tampered)
            with self.assertRaisesRegex(ValueError, "expected admission identity"):
                load_linear_response_admission(
                    path, expected_admission_id=package.admission_id
                )

    def test_admission_binds_component_state_and_authenticated_payload_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            admission_path = _admission_fixture(directory, complete=True)
            evidence_path = directory / "evidence" / "evidence-bundle.json"
            evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
            evidence["produced_records"][0]["numerical_state"] = "ACCEPTED"
            evidence["bundle_sha256"] = evidence_bundle_digest(evidence)
            _write_json(evidence_path, evidence)

            payload_path = directory / "payload.json"
            payload = json.loads(payload_path.read_text(encoding="utf-8"))
            for digest in (
                evidence["bundle_sha256"],
                _sha256(evidence_path.read_bytes()),
            ):
                if digest not in payload["lineage"]["source_sha256s"]:
                    payload["lineage"]["source_sha256s"].append(digest)
            _write_json(payload_path, payload)

            admission = json.loads(admission_path.read_text(encoding="utf-8"))
            admission["evidence_bundle"]["sha256"] = _sha256(
                evidence_path.read_bytes()
            )
            admission["payload"]["sha256"] = _sha256(payload_path.read_bytes())
            _write_json(admission_path, admission)
            with self.assertRaisesRegex(
                ValueError, "component numerical state does not match"
            ):
                admit_linear_response_bundle(admission_path)

        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            admission_path = _admission_fixture(directory, complete=True)
            payload_path = directory / "payload.json"
            payload = json.loads(payload_path.read_text(encoding="utf-8"))
            payload["response_components"][0]["result"]["reason"] = (
                "stale unrelated payload"
            )
            _write_json(payload_path, payload)
            admission = json.loads(admission_path.read_text(encoding="utf-8"))
            admission["payload"]["sha256"] = _sha256(payload_path.read_bytes())
            _write_json(admission_path, admission)
            with self.assertRaisesRegex(
                ValueError, "authenticated payload does not match component"
            ):
                admit_linear_response_bundle(admission_path)

    def test_admission_binds_all_projective_rows_to_reduction(self) -> None:
        for mutation in ("empty", "unrelated"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as temporary:
                directory = Path(temporary)
                admission_path = _admission_fixture(directory, complete=True)
                payload_path = directory / "payload.json"
                payload = json.loads(payload_path.read_text(encoding="utf-8"))
                if mutation == "empty":
                    payload["projective_comparisons"] = []
                else:
                    payload["projective_comparisons"][0]["reason"] = (
                        "unrelated projective conclusion"
                    )
                _write_json(payload_path, payload)
                admission = json.loads(admission_path.read_text(encoding="utf-8"))
                admission["payload"]["sha256"] = _sha256(
                    payload_path.read_bytes()
                )
                _write_json(admission_path, admission)
                with self.assertRaisesRegex(
                    ValueError, "projective.*reduction|57"
                ):
                    admit_linear_response_bundle(admission_path)

    def test_admission_binds_covariance_block_to_sealed_empirical_gram(self) -> None:
        request = b_prime_request()
        payload = b_prime_payload(request)
        plans = build_projective_row_plans()
        component_ids = tuple(dict.fromkeys(
            component_id
            for plan in plans
            for component_id in (*plan.left_component_ids, *plan.right_component_ids)
        ))
        receipt = "sha256:" + "7" * 64
        components = {
            component_id: ComputedUnresolvedComponentEvidence(
                component_id=component_id,
                units="M-delta-omega-per-native-coordinate",
                contributions=(SignedErrorContribution(
                    channel_id=f"local:{component_id}:signed-root",
                    family="signed-root",
                    shared_group=component_id,
                    delta=0.0j,
                    units="M-delta-omega-per-native-coordinate",
                    source_receipt=receipt,
                    scope="local",
                ),),
                reason="structural unresolved component",
                source_receipt=receipt,
            )
            for component_id in component_ids
        }
        first_plan = plans[0]
        first_ids = (*first_plan.left_component_ids, *first_plan.right_component_ids)
        for index, component_id in enumerate(first_ids):
            components[component_id] = ResolvedComponentEvidence(
                component_id=component_id,
                centre=complex(index + 1, 0.25 * index),
                units="M-delta-omega-per-native-coordinate",
                contributions=(SignedErrorContribution(
                    channel_id="shared:sealed-rank-one",
                    family="signed-root",
                    shared_group="sealed-rank-one",
                    delta=complex((index + 1) * 1.0e-8, index * 2.0e-9),
                    units="M-delta-omega-per-native-coordinate",
                    source_receipt=receipt,
                    scope="shared",
                ),),
            )
        reduction = reduce_projective_rows(
            "sealed-gram-binding-test",
            tuple(plan.row_id for plan in plans),
            components,
            source_hashes=(receipt,),
        )
        payload["projective_comparisons"] = _projective_comparisons(
            reduction, payload
        )
        gram = next(
            item for item in reduction.empirical_grams
            if item.construction_id == reduction.results[0].empirical_gram_id
        )
        self.assertEqual(len(reduction.empirical_grams), 1)
        comparison = payload["projective_comparisons"][0]
        comparison["covariance_id"] = gram.construction_id
        payload_ids = (
            *comparison["left_component_ids"],
            *comparison["right_component_ids"],
        )
        payload["covariance_blocks"] = [{
            "covariance_id": gram.construction_id,
            "basis": [
                {
                    "component_id": component_id,
                    "quadrature": quadrature,
                    "units": "payload-contract-units",
                }
                for component_id in payload_ids
                for quadrature in ("real", "imaginary")
            ],
            "matrix": [list(row) for row in gram.matrix],
            "representation": "real-block-covariance-in-declared-basis-units",
            "kind": "component-local-correlated-empirical",
        }]
        _validate_projective_reduction_bindings(reduction, payload)

        forged = deepcopy(payload)
        matrix = forged["covariance_blocks"][0]["matrix"]
        for row in range(len(matrix)):
            for column in range(len(matrix)):
                if row // 2 != column // 2:
                    matrix[row][column] = 0.0
        with self.assertRaisesRegex(ValueError, "covariance|Gram"):
            _validate_projective_reduction_bindings(reduction, forged)

    def test_cli_validates_blocks_unapproved_admission_and_loads_sealed_package(
        self,
    ) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            manifest = _admission_fixture(directory, complete=True)
            package = admit_linear_response_bundle(manifest)

            def invoke(*arguments: str) -> subprocess.CompletedProcess[str]:
                return subprocess.run(
                    [sys.executable, "-m", "windows_solver", *arguments],
                    cwd=directory,
                    env={"PYTHONPATH": str(root / "src")},
                    text=True,
                    capture_output=True,
                )

            validated = invoke("m02-validate", "admission-input.json")
            self.assertEqual(validated.returncode, 0, validated.stderr)
            self.assertFalse(json.loads(validated.stdout)["release_admissible"])

            blocked = invoke(
                "m02-admit", "admission-input.json", "--output", "admitted.json"
            )
            self.assertEqual(blocked.returncode, 2)
            self.assertIn("human mathematical review receipt", blocked.stderr)
            self.assertFalse((directory / "admitted.json").exists())

            _write_json(directory / "admitted.json", package.to_mapping())
            admission_id = package.admission_id

            exported = invoke(
                "m02-export", "admitted.json",
                "--admission-id", admission_id,
                "--output", "exported.json",
            )
            self.assertEqual(exported.returncode, 0, exported.stderr)
            self.assertEqual(
                (directory / "exported.json").read_bytes(),
                canonical_json_bytes(package.to_mapping()),
            )

            planned = invoke(
                "plan", "request.json",
                "--linear-response-admission", "admitted.json",
                "--linear-response-admission-id", admission_id,
            )
            self.assertEqual(planned.returncode, 0, planned.stderr)
            self.assertEqual(json.loads(planned.stdout)["unavailable_capabilities"], [])

            first = invoke(
                "run", "request.json", "--store", "store",
                "--linear-response-admission", "admitted.json",
                "--linear-response-admission-id", admission_id,
            )
            second = invoke(
                "run", "request.json", "--store", "store",
                "--linear-response-admission", "admitted.json",
                "--linear-response-admission-id", admission_id,
            )
            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertEqual(json.loads(first.stdout)["provider_execution_count"], 3)
            self.assertEqual(json.loads(second.stdout)["cache_hit_count"], 3)

            unpinned = invoke(
                "plan", "request.json",
                "--linear-response-admission", "admitted.json",
            )
            self.assertEqual(unpinned.returncode, 2)
            self.assertIn("detached admission ID", unpinned.stderr)

    def test_admission_identity_separates_persistent_cache(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            packages: list[tuple[Path, LinearResponseAdmissionPackage]] = []
            for label in ("package-a", "package-b"):
                package_directory = directory / label
                package_directory.mkdir()
                manifest = _admission_fixture(
                    package_directory,
                    complete=True,
                    first_component_reason=label,
                )
                package = admit_linear_response_bundle(manifest)
                package_path = package_directory / "admitted.json"
                _write_json(package_path, package.to_mapping())
                packages.append((package_path, package))

            def run(
                package_path: Path, package: LinearResponseAdmissionPackage
            ) -> subprocess.CompletedProcess[str]:
                return subprocess.run(
                    [
                        sys.executable,
                        "-m",
                        "windows_solver",
                        "run",
                        str(package_path.parent / "request.json"),
                        "--store",
                        str(directory / "shared-store"),
                        "--linear-response-admission",
                        str(package_path),
                        "--linear-response-admission-id",
                        package.admission_id,
                    ],
                    cwd=directory,
                    env={"PYTHONPATH": str(root / "src")},
                    text=True,
                    capture_output=True,
                )

            first = run(*packages[0])
            second = run(*packages[1])
            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertEqual(second.returncode, 0, second.stderr)
            first_run = json.loads(first.stdout)
            second_run = json.loads(second.stdout)
            self.assertEqual(first_run["provider_execution_count"], 3)
            self.assertEqual(second_run["provider_execution_count"], 1)
            self.assertEqual(second_run["cache_hit_count"], 2)
            self.assertNotEqual(
                first_run["artifact_ids"]["linear-response"],
                second_run["artifact_ids"]["linear-response"],
            )


if __name__ == "__main__":
    unittest.main()
