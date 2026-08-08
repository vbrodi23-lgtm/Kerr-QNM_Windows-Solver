from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from windows_solver.contracts import ModeKey, canonical_json_bytes
from windows_solver.evidence_intake import (
    BUNDLE_SCHEMA_VERSION,
    B_PRIME_CONTRACT_SHA256,
    PINNED_FIXTURE_SOURCE_COMMIT,
    PINNED_FIXTURE_SOURCE_REPOSITORY,
    evidence_bundle_digest,
    load_evidence_bundle,
    load_representative_fixture_receipt,
    validate_evidence_bundle,
)
from windows_solver.linear_response import (
    B_PRIME_RELEASE_DOMAIN,
    LINEAR_RESPONSE_DESCRIPTOR,
    baseline_root_reference_id,
)
from windows_solver.response_engine import (
    NumericalPolicy,
    ResponseComponentJob,
    VettedNativeDeterminantKernel,
)
from windows_solver.spectrum import SpectralCatalogProvider


ROOT = Path(__file__).resolve().parents[1]


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _git_blob_sha(data: bytes) -> str:
    material = f"blob {len(data)}\0".encode("ascii") + data
    return hashlib.sha1(material, usedforsecurity=False).hexdigest()


def _comparator_identity_sha256(item: dict[str, object]) -> str:
    return _sha256(canonical_json_bytes({
        "fixture_id": item["fixture_id"],
        "fixture_kind": item["fixture_kind"],
        "disposition": item["disposition"],
        "source_path": str(item["source_path"]).replace("\\", "/"),
        "source_blob_sha": item["source_blob_sha"],
        "source_sha256": item["source_sha256"],
    }))


_ROOT_IDENTITIES: dict[str, dict[str, object]] | None = None
_CAMPAIGN_SPECTRAL_RECEIPT: dict[str, object] | None = None


def _root_identity(leaf: object) -> dict[str, object]:
    global _ROOT_IDENTITIES
    if _ROOT_IDENTITIES is None:
        _ROOT_IDENTITIES = {
            item.leaf_id: ResponseComponentJob.from_leaf_id(
                item.leaf_id,
                policy=NumericalPolicy(),
                backend_identity=VettedNativeDeterminantKernel.identity,
            ).root.to_mapping()
            for item in B_PRIME_RELEASE_DOMAIN.production_leaves
        }
    return deepcopy(_ROOT_IDENTITIES[leaf.leaf_id])


def _campaign_spectral_receipt() -> dict[str, object]:
    global _CAMPAIGN_SPECTRAL_RECEIPT
    if _CAMPAIGN_SPECTRAL_RECEIPT is not None:
        return deepcopy(_CAMPAIGN_SPECTRAL_RECEIPT)
    roots: dict[str, dict[str, object]] = {}
    for leaf in B_PRIME_RELEASE_DOMAIN.production_leaves:
        identity = _root_identity(leaf)
        digest = _sha256(canonical_json_bytes(identity))
        roots.setdefault(digest, identity)
    _CAMPAIGN_SPECTRAL_RECEIPT = {
        "provider": SpectralCatalogProvider.descriptor.to_mapping(),
        "root_count": len(roots),
        "root_set_sha256": _sha256(canonical_json_bytes(list(roots.values()))),
    }
    return deepcopy(_CAMPAIGN_SPECTRAL_RECEIPT)


def _record(leaf: object, payload_path: str, payload_bytes: bytes) -> dict[str, object]:
    mode = ModeKey(
        s=-2,
        ell=leaf.mode[0],
        m=leaf.mode[1],
        n=leaf.mode[2],
        branch="schwarzschild-overtone-continuation",
        polarization="gravitational",
    )
    root_identity = _root_identity(leaf)
    return {
        "leaf_id": leaf.leaf_id,
        "role": leaf.role,
        "mode": list(leaf.mode),
        "sampling_coordinate": {
            "coordinate_id": "a-over-M" if leaf.spin_role == "direct" else "M-kappa",
            "exact": [leaf.coordinate.numerator, leaf.coordinate.denominator],
            "spin_binary64_hex": leaf.spin.hex(),
        },
        "mechanism_id": leaf.mechanism_id,
        "numerical_state": "ACCEPTED",
        "payload_path": payload_path,
        "payload_size": len(payload_bytes),
        "payload_sha256": _sha256(payload_bytes),
        "source_reference": "sources/operator.json",
        "root_reference_id": baseline_root_reference_id(mode, leaf.spin),
        "root_identity": root_identity,
        "root_identity_sha256": _sha256(canonical_json_bytes(root_identity)),
        "uncertainty_scope": "component-local",
    }


def _write_manifest(
    directory: Path,
    leaves: list[object],
    *,
    state: str = "partial-smoke",
    comparators: list[dict[str, object]] | None = None,
    windows_paths: bool = False,
) -> dict[str, object]:
    source_bytes = canonical_json_bytes({"operator": "fixture-only"})
    source_path = directory / "sources" / "operator.json"
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_bytes(source_bytes)
    records: list[dict[str, object]] = []
    for index, leaf in enumerate(leaves):
        payload_bytes = canonical_json_bytes({"finite_fixture_value": index + 0.25})
        relative = f"payloads/{index:03d}.json"
        payload_path = directory / relative
        payload_path.parent.mkdir(parents=True, exist_ok=True)
        payload_path.write_bytes(payload_bytes)
        records.append(_record(leaf, relative, payload_bytes))
    required = list(B_PRIME_RELEASE_DOMAIN.production_leaf_ids)
    produced = {record["leaf_id"] for record in records}
    manifest: dict[str, object] = {
        "schema_version": BUNDLE_SCHEMA_VERSION,
        "bundle_state": state,
        "contract": {
            "release_domain_fingerprint": B_PRIME_CONTRACT_SHA256,
            "numerical_policy_fingerprint": LINEAR_RESPONSE_DESCRIPTOR.numerical_policy_fingerprint,
            "required_leaf_ids": required,
            "campaign_spectral_receipt": _campaign_spectral_receipt(),
        },
        "producer": {
            "producer_id": "powershell-fixture-producer",
            "runtime_fingerprint": "cpython-3.12-windows-amd64",
            "source_repository": "https://example.invalid/operator",
            "source_commit": "b" * 40,
            "source_sha256s": [_sha256(source_bytes)],
        },
        "source_files": [{
            "path": "sources/operator.json",
            "byte_size": len(source_bytes),
            "sha256": _sha256(source_bytes),
            "media_type": "application/json",
            "purpose": "operator-source-lineage",
        }],
        "produced_records": records,
        "missing_leaf_ids": [item for item in required if item not in produced],
        "comparator_fixtures": comparators or [],
    }
    if windows_paths:
        manifest["source_files"][0]["path"] = "sources\\operator.json"
        for record in records:
            record["payload_path"] = str(record["payload_path"]).replace("/", "\\")
            record["source_reference"] = "sources\\operator.json"
    manifest["bundle_sha256"] = evidence_bundle_digest(manifest)
    (directory / "evidence-bundle.json").write_bytes(canonical_json_bytes(manifest))
    return manifest


class EvidenceBundleValidationTests(unittest.TestCase):
    def test_partial_and_complete_structural_states_never_admit_provider(self) -> None:
        """Catches treating partial input or structural completeness as provider admission."""

        leaves = list(B_PRIME_RELEASE_DOMAIN.production_leaves)
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            partial = _write_manifest(directory, [leaves[0], leaves[-1]])
            summary = validate_evidence_bundle(partial, bundle_directory=directory)
            self.assertEqual(summary.bundle_state, "partial-smoke")
            self.assertEqual((summary.produced_count, summary.missing_count), (2, 551))
            self.assertFalse(summary.release_admissible)
            self.assertFalse(LINEAR_RESPONSE_DESCRIPTOR.available)

        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            complete = _write_manifest(directory, leaves, state="complete-operator")
            summary = validate_evidence_bundle(complete, bundle_directory=directory)
            self.assertEqual((summary.produced_count, summary.missing_count), (553, 0))
            self.assertEqual(summary.validation_status, "STRUCTURALLY_VALID")
            self.assertFalse(summary.release_admissible)

    def test_rejects_identity_partition_hash_lineage_path_and_evidence_leakage(self) -> None:
        """Catches forged or quarantined inputs crossing the pre-reduction boundary."""

        leaf = B_PRIME_RELEASE_DOMAIN.production_leaves[0]
        mutations = {
            "duplicate leaf": lambda m: m["produced_records"].append(deepcopy(m["produced_records"][0])),
            "off-domain": lambda m: m["produced_records"][0].__setitem__("leaf_id", "b-prime-leaf-" + "f" * 64),
            "partition overlap": lambda m: m["missing_leaf_ids"].append(leaf.leaf_id),
            "incomplete partition": lambda m: m["missing_leaf_ids"].pop(),
            "forged size": lambda m: m["produced_records"][0].__setitem__("payload_size", 999),
            "forged hash": lambda m: m["produced_records"][0].__setitem__("payload_sha256", "0" * 64),
            "malformed lineage": lambda m: m["producer"].__setitem__("source_commit", "not-a-commit"),
            "unknown field": lambda m: m.__setitem__("surprise", True),
            "global uncertainty": lambda m: m["produced_records"][0].__setitem__("uncertainty_scope", "atlas-wide-global-cover"),
            "comparator leakage": lambda m: m["comparator_fixtures"].append({"leaf_id": leaf.leaf_id}),
            "source code payload": lambda m: m["produced_records"][0].__setitem__("payload_path", "payloads/evidence.py"),
            "nonfinite": lambda m: m["producer"].__setitem__("runtime_fingerprint", math.nan),
        }
        for label, mutate in mutations.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temporary:
                directory = Path(temporary)
                manifest = _write_manifest(directory, [leaf])
                mutate(manifest)
                with self.assertRaises(ValueError, msg=label):
                    manifest["bundle_sha256"] = evidence_bundle_digest(manifest)
                    validate_evidence_bundle(manifest, bundle_directory=directory)

        for unsafe in ("../escape.json", "/absolute.json", "C:\\absolute.json", "\\\\server\\share.json"):
            with self.subTest(path=unsafe), tempfile.TemporaryDirectory() as temporary:
                directory = Path(temporary)
                manifest = _write_manifest(directory, [leaf])
                manifest["produced_records"][0]["payload_path"] = unsafe
                with self.assertRaisesRegex(ValueError, "safe relative path"):
                    manifest["bundle_sha256"] = evidence_bundle_digest(manifest)
                    validate_evidence_bundle(manifest, bundle_directory=directory)

    def test_windows_and_posix_paths_have_one_digest_and_load_surface(self) -> None:
        """Catches OS-specific separators changing bundle identity or file lookup."""

        leaves = [B_PRIME_RELEASE_DOMAIN.production_leaves[0]]
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            posix = _write_manifest(directory, leaves)
            windows = deepcopy(posix)
            windows["source_files"][0]["path"] = "sources\\operator.json"
            windows["produced_records"][0]["payload_path"] = "payloads\\000.json"
            windows["produced_records"][0]["source_reference"] = "sources\\operator.json"
            self.assertEqual(evidence_bundle_digest(posix), evidence_bundle_digest(windows))
            windows["bundle_sha256"] = evidence_bundle_digest(windows)
            (directory / "evidence-bundle.json").write_bytes(canonical_json_bytes(windows))
            summary = load_evidence_bundle(directory)
            self.assertEqual(summary.bundle_sha256, windows["bundle_sha256"])

    def test_root_reference_and_duplicate_json_keys_fail_closed(self) -> None:
        """Catches shape-only root bindings and ambiguous JSON canonicalization."""

        leaf = B_PRIME_RELEASE_DOMAIN.production_leaves[0]
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            manifest = _write_manifest(directory, [leaf])
            manifest["produced_records"][0]["root_reference_id"] = (
                "spectral-root-reference-" + "f" * 64
            )
            manifest["bundle_sha256"] = evidence_bundle_digest(manifest)
            with self.assertRaisesRegex(ValueError, "root_reference_id"):
                validate_evidence_bundle(manifest, bundle_directory=directory)

        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            manifest = _write_manifest(directory, [leaf])
            payload = b'{"value":1,"value":2}'
            (directory / "payloads" / "000.json").write_bytes(payload)
            manifest["produced_records"][0]["payload_size"] = len(payload)
            manifest["produced_records"][0]["payload_sha256"] = _sha256(payload)
            manifest["bundle_sha256"] = evidence_bundle_digest(manifest)
            with self.assertRaisesRegex(ValueError, "duplicate evidence JSON key"):
                validate_evidence_bundle(manifest, bundle_directory=directory)

        with tempfile.TemporaryDirectory() as temporary:
            manifest_path = Path(temporary) / "evidence-bundle.json"
            manifest_path.write_text(
                '{"schema_version":1,"schema_version":1}', encoding="utf-8"
            )
            with self.assertRaisesRegex(ValueError, "duplicate evidence JSON key"):
                load_evidence_bundle(manifest_path)

    def test_producer_and_comparator_provenance_bindings_fail_closed(self) -> None:
        """Catches well-shaped but forged runtime/source/blob/identity provenance."""

        leaf = B_PRIME_RELEASE_DOMAIN.production_leaves[0]
        for label, mutate, message in (
            (
                "undefined runtime",
                lambda m: m["producer"].__setitem__("runtime_fingerprint", "arbitrary-runtime"),
                "runtime_fingerprint",
            ),
            (
                "unbound producer hash",
                lambda m: m["producer"].__setitem__("source_sha256s", ["c" * 64]),
                "source_sha256s",
            ),
            (
                "extra producer hash",
                lambda m: m["producer"]["source_sha256s"].append("d" * 64),
                "source_sha256s",
            ),
        ):
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temporary:
                directory = Path(temporary)
                manifest = _write_manifest(directory, [leaf])
                mutate(manifest)
                manifest["bundle_sha256"] = evidence_bundle_digest(manifest)
                with self.assertRaisesRegex(ValueError, message):
                    validate_evidence_bundle(manifest, bundle_directory=directory)

        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            manifest = _write_manifest(directory, [leaf])
            source = manifest["source_files"][0]
            comparator = {
                "fixture_id": "pilot:220:19/20:horizon-admittance",
                "fixture_kind": "legacy-gr-pilot",
                "disposition": "migration-only",
                "source_path": source["path"],
                "source_blob_sha": _git_blob_sha(
                    (directory / "sources" / "operator.json").read_bytes()
                ),
                "source_sha256": source["sha256"],
                "identity_sha256": "",
            }
            comparator["identity_sha256"] = _comparator_identity_sha256(comparator)
            manifest["comparator_fixtures"] = [comparator]
            manifest["bundle_sha256"] = evidence_bundle_digest(manifest)
            validate_evidence_bundle(manifest, bundle_directory=directory)

            for field, forged, message in (
                ("source_blob_sha", "e" * 40, "Git blob"),
                ("identity_sha256", "f" * 64, "identity_sha256"),
            ):
                tampered = deepcopy(manifest)
                tampered["comparator_fixtures"][0][field] = forged
                tampered["bundle_sha256"] = evidence_bundle_digest(tampered)
                with self.subTest(field=field), self.assertRaisesRegex(ValueError, message):
                    validate_evidence_bundle(tampered, bundle_directory=directory)

    def test_drive_relative_unc_and_ads_paths_fail_before_file_access(self) -> None:
        """Catches Windows namespace paths being interpreted relative on POSIX."""

        leaf = B_PRIME_RELEASE_DOMAIN.production_leaves[0]
        unsafe_paths = (
            "C:relative.json",
            "C:\\relative.json",
            "\\\\server\\share.json",
            "payloads/000.json:alternate-stream",
        )
        for unsafe in unsafe_paths:
            with self.subTest(path=unsafe), tempfile.TemporaryDirectory() as temporary:
                directory = Path(temporary)
                manifest = _write_manifest(directory, [leaf])
                manifest["produced_records"][0]["payload_path"] = unsafe
                with self.assertRaisesRegex(ValueError, "safe relative path"):
                    evidence_bundle_digest(manifest)

    def test_malformed_numerical_state_type_is_a_validation_error(self) -> None:
        """Catches unhashable state values escaping the declared validation boundary."""

        leaf = B_PRIME_RELEASE_DOMAIN.production_leaves[0]
        for malformed in ({"state": "ACCEPTED"}, ["ACCEPTED"]):
            with self.subTest(value=malformed), tempfile.TemporaryDirectory() as temporary:
                directory = Path(temporary)
                manifest = _write_manifest(directory, [leaf])
                manifest["produced_records"][0]["numerical_state"] = malformed
                manifest["bundle_sha256"] = evidence_bundle_digest(manifest)
                with self.assertRaisesRegex(ValueError, "numerical_state"):
                    validate_evidence_bundle(manifest, bundle_directory=directory)


class RepresentativeFixtureTests(unittest.TestCase):
    def test_pinned_pilot_cubic_and_missing_ladder_ledger_are_exact(self) -> None:
        """Catches source drift, cubic promotion, or invention of absent local ladders."""

        receipt = load_representative_fixture_receipt()
        self.assertEqual(PINNED_FIXTURE_SOURCE_REPOSITORY, "vbrodi23-lgtm/Windows-Solver_V2-whiteboard")
        self.assertEqual(PINNED_FIXTURE_SOURCE_COMMIT, "0c1e8a3d3bca6e608c34e111476a4f6dcb73e86e")
        expected_sources = {
            "v2_local_response_protocol.json": ("ed729c8420b6c08abc534212dc2a593c1c65cf36", "421e0751f5a68f95cd69fc0b5cdb155c96fe5cbb83d81e59489bf9130636673b"),
            "v2_local_response_reduction.json": ("3b9034df6eada7ec60ac347518a6f616d4f6683e", "b6a5018c1f4875ebea2f26d544c354896edb33c2bb176ccebc90a1d511c46203"),
            "v2_local_response_components.csv": ("3f24cb859b4d13641bf0649d214dfd0ded498239", "20aa65b184e7866827f2283d64148fc68f2a0f16d02f701afc8cd516157b42f4"),
            "v2_07_physical_cubic_even_resolved.csv": ("b6a6620702ce264e0467d7daf0358bae83d5d5d4", "89f28eabdf0be247a1db87fb13c6f0c8a60bb9065518426b8a9d5a24630b0bd1"),
            "v2_07_physical_cubic_even_status.json": ("8924859018574c0eda7941a2024b03a6e971a012", "07b12e64fa22783a9429371facfc14990b70fbc28dcf60039c477ec3bdec1d9f"),
        }
        self.assertEqual(
            {Path(item["repository_path"]).name: (item["git_blob_sha"], item["sha256"]) for item in receipt["source_files"]},
            expected_sources,
        )
        pilot = receipt["pilot_components"]
        self.assertEqual(len(pilot), 9)
        self.assertEqual({item["mode_label"] for item in pilot}, {"220", "330", "440"})
        self.assertEqual({item["mechanism_id"] for item in pilot}, {"horizon-admittance", "exterior-fixed-r3", "exterior-light-ring"})
        self.assertEqual({item["spin_exact"] for item in pilot}, {(19, 20)})
        self.assertEqual({item["uncertainty_origin"] for item in pilot}, {"V2_COMPONENT_LOCAL_SIGNED_AMPLITUDE_LADDER"})
        cubic = receipt["cubic_comparator_rows"]
        self.assertEqual(len(cubic), 8)
        self.assertEqual({item["mode"] for item in cubic}, {(2, 2, 0)})
        self.assertEqual({item["spin_exact"] for item in cubic}, {(0, 1), (3, 10), (1, 2), (7, 10)})
        self.assertEqual({item["polarization"] for item in cubic}, {"plus", "minus"})
        self.assertEqual({item["disposition"] for item in cubic}, {"comparator-only"})
        ledger = receipt["legacy_local_ladder_ledger"]
        self.assertEqual(len(ledger), 147)
        self.assertEqual(sum(item["state"] == "AUTHENTICATED_PILOT_SUBSET" for item in ledger), 9)
        missing = [item for item in ledger if item["state"] == "MISSING_SOURCE_EVIDENCE"]
        self.assertEqual(len(missing), 138)
        self.assertTrue(all(set(item) == {"mode_label", "spin_exact", "mechanism_id", "state"} for item in missing))

    def test_predeclared_head_tail_and_risky_fixture_smoke_ids_are_stable(self) -> None:
        """Catches post-hoc fixture sampling or loss of edge identities."""

        receipt = load_representative_fixture_receipt()
        self.assertEqual(receipt["operator_smoke_leaf_ids"], [
            "b-prime-leaf-9e5777728144433e089f9559b92b6e139e16115a5a53099f40403a45297aa3c3",
            "b-prime-leaf-59894e4af3913286bb06cb36d1f01f508f728588937fbc5a45eab6da2906b77d",
            "b-prime-leaf-3ee2b2dcdc5276cbcd51264f1210002314acd3ff845bb7a464f1e9333e9115c5",
            "b-prime-leaf-ea3be34f9f06cab547552a6b774adba5305ed328a3a8ae4e8e49b2d78562d79f",
        ])
        self.assertEqual(receipt["fixture_smoke_ids"], [
            "pilot:220:19/20:exterior-light-ring",
            "pilot:440:19/20:horizon-admittance",
            "cubic:220:0/1:plus",
            "cubic:220:7/10:minus",
        ])


class EvidenceIntakeCommandTests(unittest.TestCase):
    def test_command_emits_one_deterministic_powershell_friendly_json_object(self) -> None:
        """Catches shell-dependent paths or unstable command output."""

        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            _write_manifest(directory, [B_PRIME_RELEASE_DOMAIN.production_leaves[0]], windows_paths=True)
            command = [sys.executable, "-m", "windows_solver", "validate-evidence", str(directory)]
            first = subprocess.run(command, cwd=ROOT, env={"PYTHONPATH": str(ROOT / "src")}, text=True, capture_output=True)
            second = subprocess.run(command, cwd=ROOT, env={"PYTHONPATH": str(ROOT / "src")}, text=True, capture_output=True)
            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertEqual(first.stdout, second.stdout)
            output = json.loads(first.stdout)
            self.assertEqual(output["command"], "validate-evidence")
            self.assertEqual(output["validation_status"], "STRUCTURALLY_VALID")
            self.assertEqual((output["produced_count"], output["missing_count"]), (1, 552))
            self.assertFalse(output["release_admissible"])

    def test_invalid_command_input_is_machine_readable_and_nonzero(self) -> None:
        """Catches invalid bundles leaking tracebacks or success exit codes."""

        with tempfile.TemporaryDirectory() as temporary:
            manifest = Path(temporary) / "evidence-bundle.json"
            manifest.write_text("{}", encoding="utf-8")
            completed = subprocess.run(
                [sys.executable, "-m", "windows_solver", "validate-evidence", str(manifest)],
                cwd=ROOT, env={"PYTHONPATH": str(ROOT / "src")}, text=True, capture_output=True,
            )
            self.assertEqual(completed.returncode, 2)
            self.assertEqual(json.loads(completed.stderr)["error"]["code"], "INVALID_INPUT")

    def test_malformed_numerical_state_cli_error_is_one_json_object(self) -> None:
        """Catches malformed types leaking a traceback instead of the CLI error contract."""

        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            manifest = _write_manifest(
                directory, [B_PRIME_RELEASE_DOMAIN.production_leaves[0]]
            )
            manifest["produced_records"][0]["numerical_state"] = {"bad": "type"}
            manifest["bundle_sha256"] = evidence_bundle_digest(manifest)
            (directory / "evidence-bundle.json").write_bytes(
                canonical_json_bytes(manifest)
            )
            completed = subprocess.run(
                [sys.executable, "-m", "windows_solver", "validate-evidence", str(directory)],
                cwd=ROOT,
                env={"PYTHONPATH": str(ROOT / "src")},
                text=True,
                capture_output=True,
            )
            self.assertEqual(completed.returncode, 2, completed.stderr)
            self.assertEqual(completed.stdout, "")
            lines = completed.stderr.splitlines()
            self.assertEqual(len(lines), 1)
            error = json.loads(lines[0])["error"]
            self.assertEqual(error["code"], "INVALID_INPUT")
            self.assertIn("numerical_state", error["message"])


if __name__ == "__main__":
    unittest.main()
