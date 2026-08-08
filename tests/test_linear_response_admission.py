from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from windows_solver.builtin import default_registry
from windows_solver.contracts import Capability, canonical_json_bytes
from windows_solver.evidence_intake import (
    B_PRIME_RELEASE_DOMAIN,
    evidence_bundle_digest,
)
from windows_solver.linear_response_admission import (
    ADMITTED_LINEAR_RESPONSE_DESCRIPTOR,
    AdmittedLinearResponseProvider,
    LinearResponseAdmissionPackage,
    admit_linear_response_bundle,
)
from windows_solver.providers import ProviderUnavailableError
from windows_solver.response_reduction import (
    ComputedUnresolvedComponentEvidence,
    SignedErrorContribution,
    build_projective_row_plans,
    reduce_projective_rows,
)
from windows_solver.spectrum import build_spectral_payload

from tests.test_linear_response_contract import b_prime_payload, b_prime_request
from tests.test_linear_response_evidence_intake import _write_manifest


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json_bytes(value))


def _admission_fixture(directory: Path, *, complete: bool) -> Path:
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


class LinearResponseAdmissionTests(unittest.TestCase):
    def test_role_scoped_request_derives_exact_sparse_spectral_upstream(self) -> None:
        request = b_prime_request().for_capability(Capability.SPECTRAL_CORE)
        self.assertEqual(
            set(request.numerical_policy), {"exact-spectral-selection"}
        )
        payload = build_spectral_payload(request)
        self.assertEqual(payload["requested_root_count"], 87)
        self.assertEqual(len(payload["roots"]), 87)

    def test_partial_bundle_cannot_register_provider(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            manifest = _admission_fixture(Path(temporary), complete=False)
            with self.assertRaisesRegex(ValueError, "553|complete"):
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
            self.assertEqual(package.evidence_receipt["produced_count"], 553)
            self.assertEqual(package.reduction_receipt["row_count"], 174)

            provider = AdmittedLinearResponseProvider(package)
            self.assertEqual(provider.descriptor, ADMITTED_LINEAR_RESPONSE_DESCRIPTOR)
            registry = default_registry(provider)
            self.assertIs(registry.resolve(Capability.LINEAR_RESPONSE), provider)
            result = provider.execute(
                b_prime_request(), {Capability.SPECTRAL_CORE: object()}
            )
            self.assertEqual(result.payload, package.to_mapping()["payload"])
            self.assertEqual(result.evidence.scientific.value, "NOT_EVALUATED")

            with self.assertRaises(TypeError):
                package.payload["quantity"] = "mutated-after-admission"

    def test_admission_package_revalidates_content_and_rejects_tamper(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            package = admit_linear_response_bundle(
                _admission_fixture(Path(temporary), complete=True)
            )
        mapping = package.to_mapping()
        self.assertEqual(LinearResponseAdmissionPackage.from_mapping(mapping), package)
        forged = deepcopy(mapping)
        forged["evidence_receipt"]["produced_count"] = 552
        with self.assertRaisesRegex(ValueError, "evidence|identity|553"):
            LinearResponseAdmissionPackage.from_mapping(forged)

        malformed = deepcopy(mapping)
        malformed["evidence_receipt"]["unresolved_leaf_ids"] = [{}]
        with self.assertRaisesRegex(ValueError, "unresolved leaf IDs"):
            LinearResponseAdmissionPackage.from_mapping(malformed)

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

    def test_cli_validates_admits_exports_and_runs_cold_then_warm(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            _admission_fixture(directory, complete=True)

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

            admitted = invoke(
                "m02-admit", "admission-input.json", "--output", "admitted.json"
            )
            self.assertEqual(admitted.returncode, 0, admitted.stderr)
            self.assertTrue(json.loads(admitted.stdout)["release_admissible"])
            package = LinearResponseAdmissionPackage.from_mapping(
                json.loads((directory / "admitted.json").read_text(encoding="utf-8"))
            )

            exported = invoke(
                "m02-export", "admitted.json", "--output", "exported.json"
            )
            self.assertEqual(exported.returncode, 0, exported.stderr)
            self.assertEqual(
                (directory / "exported.json").read_bytes(),
                canonical_json_bytes(package.to_mapping()),
            )

            planned = invoke(
                "plan", "request.json",
                "--linear-response-admission", "admitted.json",
            )
            self.assertEqual(planned.returncode, 0, planned.stderr)
            self.assertEqual(json.loads(planned.stdout)["unavailable_capabilities"], [])

            first = invoke(
                "run", "request.json", "--store", "store",
                "--linear-response-admission", "admitted.json",
            )
            second = invoke(
                "run", "request.json", "--store", "store",
                "--linear-response-admission", "admitted.json",
            )
            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertEqual(json.loads(first.stdout)["provider_execution_count"], 3)
            self.assertEqual(json.loads(second.stdout)["cache_hit_count"], 3)


if __name__ == "__main__":
    unittest.main()
