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
from windows_solver.contracts import Capability
from windows_solver.release_manifest import (
    RELEASE_MANIFEST_SHA256,
    load_release_manifest,
    validate_release_manifest_mapping,
)


class ReleaseManifestTests(unittest.TestCase):
    def test_packaged_manifest_freezes_the_complete_release_domain(self) -> None:
        manifest = load_release_manifest(registry=default_registry())
        mapping = manifest.to_mapping()

        self.assertEqual(mapping["schema_version"], 1)
        self.assertEqual(
            mapping["manifest_id"],
            "nonlinear-kerr-ringdown-release-domain-2026-08-07",
        )
        self.assertEqual(
            set(mapping["capabilities"]),
            {capability.value for capability in Capability},
        )
        self.assertEqual(
            mapping["release_domain"]["theories"],
            [
                "general-relativity",
                "parity-even-cubic-higher-curvature-eft",
            ],
        )
        self.assertEqual(
            mapping["release_domain"]["evidence_profiles"],
            ["research", "publication"],
        )
        self.assertEqual(
            mapping["release_domain"]["platforms"],
            [
                "windows-powershell-5.1-cpython-3.12-x64",
                "ubuntu-cpython-3.12-x64",
                "oci-linux-amd64-cpython-3.12",
            ],
        )

        spectrum = mapping["release_domain"]["spectrum"]
        self.assertEqual(spectrum["spin_weight"], -2)
        self.assertEqual(spectrum["ell"], [2, 3, 4])
        self.assertEqual(spectrum["n"], [0, 1, 2])
        self.assertEqual(spectrum["mode_count"], 63)
        self.assertEqual(spectrum["root_count"], 2736)
        self.assertEqual(spectrum["roots_by_ell"], {"2": 690, "3": 966, "4": 1080})
        self.assertEqual(spectrum["catalog_sha256"], "9ebae4271309cd45a1b26c90d31155602ed8ef33bb79069adb5897e8afe7a564")
        self.assertEqual(spectrum["receipt_sha256"], "61a428a858de1eb7e42fe4cbbda37bf1fddcc808d98be2a62fd33ef4b5b74379")
        self.assertTrue(
            {
                "m02_overlay_root_count",
                "m02_selector_union_count",
                "m02_overlay_catalog_sha256",
                "m02_overlay_receipt_sha256",
            }.issubset(spectrum),
            "release spectrum does not bind the M02 sparse overlay",
        )
        self.assertEqual(spectrum["m02_overlay_root_count"], 44)
        self.assertEqual(spectrum["m02_selector_union_count"], 87)
        self.assertEqual(
            spectrum["m02_overlay_catalog_sha256"],
            "c4c61a1b73e850d537dba5f5eb947af100449aa2a1958a1ec8ea086f60ffe8e8",
        )
        self.assertEqual(
            spectrum["m02_overlay_receipt_sha256"],
            "93a2e7586878d9c84e32d19ed9e7ad44d03572a91640625c44501bfbc46a5525",
        )

        quadratic = mapping["release_domain"]["quadratic_ringdown"]
        self.assertEqual(quadratic["parent_pair"], ["220-plus", "220-plus"])
        self.assertEqual(quadratic["forced_azimuthal_number"], 4)
        self.assertEqual(quadratic["forced_frequency_rule"], "omega-parent-1-plus-omega-parent-2")
        self.assertEqual(quadratic["observable"], "R-plus-plus-44")

        self.assertEqual(
            set(mapping["release_domain"]["detector_cases"]),
            {"gw250114-h1-l1", "lisa-equal-arm-tdi-x-reference"},
        )

    def test_manifest_classifies_evidence_without_promoting_external_code(self) -> None:
        mapping = load_release_manifest(registry=default_registry()).to_mapping()
        claims = {claim["claim_id"]: claim for claim in mapping["claims"]}

        self.assertEqual(claims["public-problem-contract"]["classification"], "publicly_admitted")
        self.assertEqual(claims["public-pure-kerr-spectrum"]["classification"], "publicly_admitted")
        self.assertEqual(claims["first-order-org-reference"]["classification"], "validated_legacy_evidence")
        self.assertEqual(claims["cubic-eft-220-reference"]["classification"], "validated_legacy_evidence")
        self.assertEqual(claims["quadratic-ringdown-production"]["classification"], "framework_only")
        self.assertEqual(claims["detector-event-evidence"]["classification"], "missing")

        admitted = {
            capability
            for capability, record in mapping["capabilities"].items()
            if record["provider_state"] == "publicly_admitted"
        }
        self.assertEqual(admitted, {"problem-contract", "spectral-core"})
        for capability, record in mapping["capabilities"].items():
            if capability not in admitted:
                self.assertIsNone(record["active_provider_id"])

    def test_source_receipts_are_immutable_or_have_an_explicit_unblock_action(
        self,
    ) -> None:
        mapping = load_release_manifest().to_mapping()
        receipts = {
            receipt["receipt_id"]: receipt
            for receipt in mapping["source_receipts"]
        }

        for receipt in receipts.values():
            with self.subTest(receipt=receipt["receipt_id"]):
                if receipt["status"] == "available":
                    self.assertIsNotNone(receipt["immutable_url"])
                    self.assertIsNotNone(receipt["commit"])
                    self.assertRegex(receipt["artifact_sha256"], r"[0-9a-f]{64}")
                    self.assertRegex(receipt["artifact_blob"], r"[0-9a-f]{40}")
                    self.assertTrue(
                        receipt["artifact_blob"] in receipt["immutable_url"]
                        or receipt["commit"] in receipt["immutable_url"]
                    )
                    self.assertTrue(receipt["generator_identity"])
                    self.assertTrue(receipt["tests"])
                    self.assertIsNone(receipt["unblock_action"])
                else:
                    self.assertIsNone(receipt["immutable_url"])
                    self.assertIsNone(receipt["artifact_sha256"])
                    self.assertTrue(receipt["owner"])
                    self.assertTrue(receipt["unblock_action"])

        self.assertEqual(
            receipts["org-spin-zero-reconstruction"]["artifact_sha256"],
            "92a68bf1fdd25e27f77ef037ba0c426d14e0c7ed648028a03187c983e7a78171",
        )
        self.assertEqual(
            receipts["org-spin-seven-tenths-reconstruction"]["artifact_sha256"],
            "f4f63bee82627b21a58e1bd85ee767906e1f3b0cfae669cc28198f8e66a58529",
        )
        self.assertIn(
            "comparator use only",
            receipts["cubic-source-potential"]["license"],
        )
        self.assertEqual(
            receipts["cubic-source-potential"]["artifact_blob"],
            "afa13f54d15c4036ffe527e43f413ae5bd8631c0",
        )

    def test_module_ownership_covers_public_entry_points_and_quarantines_evidence(
        self,
    ) -> None:
        mapping = load_release_manifest().to_mapping()
        records = {
            record["module_id"]: record
            for record in mapping["module_ownership"]
        }
        expected_public_modules = {
            "src/windows_solver/artifacts.py",
            "src/windows_solver/contracts.py",
            "src/windows_solver/engine.py",
            "src/windows_solver/payload_validation.py",
            "src/windows_solver/planner.py",
            "src/windows_solver/providers.py",
            "src/windows_solver/release_manifest.py",
            "src/windows_solver/cli.py",
            "src/windows_solver/__init__.py",
            "src/windows_solver/__main__.py",
            "solver.ps1",
            "tools/compute_kerr_qnm_lattice.py",
            "tools/kerr_angular.py",
            "tools/kerr_cf_solver.py",
            "tools/validate_release_manifest.py",
        }
        self.assertTrue(expected_public_modules.issubset(records))
        active = {
            record["capability"]: record["module_id"]
            for record in records.values()
            if record["role"] == "active_provider"
        }
        self.assertEqual(
            set(active),
            {"problem-contract", "spectral-core"},
        )
        for record in records.values():
            if record["role"] in {"comparator", "extension", "retired_fixture"}:
                self.assertFalse(record["production_dependency"])

    def test_conventions_and_evidence_ceilings_cover_every_reference(self) -> None:
        mapping = load_release_manifest().to_mapping()
        convention_ids = {
            convention["convention_id"]
            for convention in mapping["conventions"]
        }
        evidence_ids = {
            ceiling["evidence_ceiling_id"]
            for ceiling in mapping["evidence_ceilings"]
        }
        for capability in mapping["capabilities"].values():
            self.assertTrue(set(capability["convention_ids"]).issubset(convention_ids))
            self.assertTrue(
                set(capability["required_evidence_ids"]).issubset(evidence_ids)
            )
        for claim in mapping["claims"]:
            self.assertIn(claim["evidence_ceiling_id"], evidence_ids)
        for receipt in mapping["source_receipts"]:
            self.assertIn(receipt["convention_id"], convention_ids)
            self.assertIn(receipt["evidence_ceiling_id"], evidence_ids)

    def test_hash_pinned_release_data_bytes_are_content_bound(self) -> None:
        data_directory = (
            Path(__file__).resolve().parents[1]
            / "src"
            / "windows_solver"
            / "data"
        )
        expected = {
            "LICENSE-CANONICAL-BACKEND-MIT.txt": (
                "9d077724a197b552d3fc7547b8f7ef8a781387fab6e687fc312f14e28a9928f4"
            ),
            "LICENSE-CC-BY-4.0.txt": (
                "ca21e12402b18b0ed880cdbf2a5b57980983b61ada45760268672b226ac46457"
            ),
            "LICENSE-QNM-MIT.txt": (
                "da080a799bd23a0d461e6a33896e4a40f2e5c033e15882a64a3f76f397d20731"
            ),
            "kerr_qnm_lattice_receipt.json": (
                "61a428a858de1eb7e42fe4cbbda37bf1fddcc808d98be2a62fd33ef4b5b74379"
            ),
            "kerr_qnm_m02_overlay_44.csv": (
                "c4c61a1b73e850d537dba5f5eb947af100449aa2a1958a1ec8ea086f60ffe8e8"
            ),
            "kerr_qnm_m02_overlay_receipt.json": (
                "93a2e7586878d9c84e32d19ed9e7ad44d03572a91640625c44501bfbc46a5525"
            ),
            "kerr_qnm_roots_2736.csv": (
                "9ebae4271309cd45a1b26c90d31155602ed8ef33bb79069adb5897e8afe7a564"
            ),
            "release_domain_manifest.json": RELEASE_MANIFEST_SHA256,
        }
        actual = {
            name: hashlib.sha256((data_directory / name).read_bytes()).hexdigest()
            for name in expected
        }
        self.assertEqual(actual, expected)

    def test_git_checkout_preserves_manifest_bytes_on_every_platform(self) -> None:
        root = Path(__file__).resolve().parents[1]
        manifest_path = "src/windows_solver/data/release_domain_manifest.json"
        completed = subprocess.run(
            ["git", "check-attr", "text", "--", manifest_path],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.stdout.strip(), f"{manifest_path}: text: unset")

    def test_missing_receipt_cannot_support_an_admitted_claim(self) -> None:
        mapping = load_release_manifest().to_mapping()
        claim = next(
            claim
            for claim in mapping["claims"]
            if claim["claim_id"] == "detector-event-evidence"
        )
        claim["classification"] = "publicly_admitted"
        with self.assertRaisesRegex(ValueError, "publicly admitted claim"):
            validate_release_manifest_mapping(mapping)

    def test_registry_must_match_manifest_provider_ownership(self) -> None:
        mapping = load_release_manifest().to_mapping()
        mapping["capabilities"]["spectral-core"]["active_provider_id"] = "wrong-provider"
        with self.assertRaisesRegex(ValueError, "provider registry does not match"):
            validate_release_manifest_mapping(mapping, registry=default_registry())

    def test_incomplete_release_coordinates_fail_closed(self) -> None:
        mapping = load_release_manifest().to_mapping()
        mapping["release_domain"]["spectrum"]["root_count"] = 2735
        with self.assertRaisesRegex(ValueError, "root_count must be 2736"):
            validate_release_manifest_mapping(mapping)

    def test_retired_or_comparator_module_cannot_be_a_production_dependency(self) -> None:
        mapping = load_release_manifest().to_mapping()
        record = next(
            record
            for record in mapping["module_ownership"]
            if record["role"] == "comparator"
        )
        record["production_dependency"] = True
        with self.assertRaisesRegex(ValueError, "non-production module"):
            validate_release_manifest_mapping(mapping)

    def test_duplicate_json_keys_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "manifest.json"
            path.write_text(
                '{"schema_version":1,"schema_version":1}',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "duplicate release manifest JSON key"):
                load_release_manifest(path)

    def test_excessively_nested_json_fails_without_a_recursion_traceback(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "manifest.json"
            path.write_text("[" * 10_000 + "0" + "]" * 10_000, encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "nesting exceeds the parser limit"):
                load_release_manifest(path)

    def test_oversize_manifest_fails_before_reading_json(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "manifest.json"
            path.write_bytes(b" " * (2 * 1024 * 1024 + 1))
            with self.assertRaisesRegex(ValueError, "exceeds the maximum size"):
                load_release_manifest(path)

    def test_manifest_mapping_is_returned_as_an_independent_copy(self) -> None:
        manifest = load_release_manifest()
        first = manifest.to_mapping()
        expected = deepcopy(first)
        first["release_domain"]["theories"].append("mutated")
        self.assertEqual(manifest.to_mapping(), expected)

    def test_validation_command_reports_the_bound_package(self) -> None:
        root = Path(__file__).resolve().parents[1]
        completed = subprocess.run(
            [sys.executable, str(root / "tools" / "validate_release_manifest.py")],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        )
        summary = json.loads(completed.stdout)
        self.assertEqual(summary["status"], "valid")
        self.assertEqual(summary["manifest_sha256"], RELEASE_MANIFEST_SHA256)
        self.assertEqual(
            summary["provider_ids"],
            ["kerr-qnm-computed-lattice-2736", "public-problem-contract"],
        )


if __name__ == "__main__":
    unittest.main()
