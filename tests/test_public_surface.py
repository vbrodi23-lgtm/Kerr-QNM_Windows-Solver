from __future__ import annotations

from pathlib import Path
import hashlib
import re
import shutil
import subprocess
import tempfile
import tomllib
import unittest

from windows_solver.spectrum import CATALOG_DATA_SHA256, CATALOG_RECEIPT_SHA256


class PublicSurfaceTests(unittest.TestCase):
    def test_ci_installs_pinned_numerical_test_dependencies_only_as_an_extra(
        self,
    ) -> None:
        root = Path(__file__).resolve().parents[1]
        configuration = tomllib.loads(
            (root / "pyproject.toml").read_text(encoding="utf-8")
        )
        workflow = (root / ".github" / "workflows" / "ci.yml").read_text(
            encoding="utf-8"
        )

        self.assertEqual(configuration["project"]["dependencies"], [])
        self.assertEqual(
            configuration["project"]["optional-dependencies"][
                "numerical-tests"
            ],
            ["numpy==2.4.6", "scipy==1.18.0"],
        )
        self.assertIn('python -m pip install ".[numerical-tests]"', workflow)

    def test_windows_launcher_accepts_any_supported_py_runtime(self) -> None:
        root = Path(__file__).resolve().parents[1]
        launcher = (root / "solver.ps1").read_text(encoding="utf-8")

        self.assertIn('PrefixArguments @("-3")', launcher)
        self.assertIn('$PythonPrefixArguments = @("-3")', launcher)
        self.assertNotIn('PrefixArguments @("-3.12")', launcher)

    def test_windows_ci_captures_native_streams_outside_powershell(self) -> None:
        root = Path(__file__).resolve().parents[1]
        workflow = (root / ".github" / "workflows" / "ci.yml").read_text(
            encoding="utf-8"
        )

        self.assertIn("shell: python", workflow)
        self.assertIn("subprocess.run", workflow)
        self.assertRegex(
            workflow,
            r'"WindowsPowerShell",\s+"v1\.0",\s+"powershell\.exe"',
        )
        self.assertNotIn("2>&1", workflow)

    def test_public_surface_contains_no_private_lineage_identifiers(self) -> None:
        root = Path(__file__).resolve().parents[1]
        paths = [
            root / "README.md",
            root / "NOTICE.md",
            root / "solver.ps1",
            *sorted((root / "docs").rglob("*.md")),
            *sorted((root / "examples").glob("*.json")),
            *sorted((root / "src" / "windows_solver").rglob("*.py")),
            *sorted((root / "src" / "windows_solver").rglob("*.csv")),
            *sorted((root / "src" / "windows_solver").rglob("*.json")),
            *sorted((root / "src" / "windows_solver").rglob("*.txt")),
        ]
        version_one = "v" + "1"
        version_two = "v" + "2"
        numbered_sequence = re.compile(
            r"(?:stage|target)[\s_-]*\d+", re.IGNORECASE
        )
        wrong_scope_language = re.compile(
            r"(?:819[- ]root|819 declared roots|728 roots)", re.IGNORECASE
        )

        findings: list[str] = []
        for path in paths:
            text = path.read_text(encoding="utf-8")
            lowered = text.casefold()
            if version_one in lowered or version_two in lowered:
                findings.append(str(path.relative_to(root)))
            if numbered_sequence.search(text):
                findings.append(str(path.relative_to(root)))
            if "flagship" in lowered:
                findings.append(str(path.relative_to(root)))
            if wrong_scope_language.search(text):
                findings.append(str(path.relative_to(root)))

        self.assertEqual(findings, [])

    def test_current_status_names_pr2_boundary_and_pr3_linear_response_only(self) -> None:
        root = Path(__file__).resolve().parents[1]
        current_status_files = (
            root / "README.md",
            root / "docs" / "architecture.md",
            root
            / "docs"
            / "superpowers"
            / "specs"
            / "2026-08-06-public-solver-design.md",
            root
            / "docs"
            / "superpowers"
            / "specs"
            / "2026-08-07-authenticated-spectral-catalog-design.md",
            root
            / "docs"
            / "superpowers"
            / "plans"
            / "2026-08-06-public-capability-dag.md",
            root
            / "docs"
            / "superpowers"
            / "plans"
            / "2026-08-07-authenticated-spectral-catalog.md",
        )
        stale = re.compile(
            r"only the problem-contract provider|"
            r"numerical science providers are unavailable until migrated",
            re.IGNORECASE,
        )

        for path in current_status_files:
            text = path.read_text(encoding="utf-8")
            with self.subTest(path=path.relative_to(root)):
                self.assertIn("PR #2", text)
                self.assertIn("PR #3", text)
                self.assertIn("linear-response", text)
                self.assertIsNone(stale.search(text))

    def test_current_status_states_complete_pure_kerr_lattice_without_legacy_scope(self) -> None:
        root = Path(__file__).resolve().parents[1]
        current_status_files = (
            root / "README.md",
            root / "docs" / "architecture.md",
            root
            / "docs"
            / "superpowers"
            / "specs"
            / "2026-08-06-public-solver-design.md",
            root
            / "docs"
            / "superpowers"
            / "specs"
            / "2026-08-07-authenticated-spectral-catalog-design.md",
            root
            / "docs"
            / "superpowers"
            / "plans"
            / "2026-08-06-public-capability-dag.md",
            root
            / "docs"
            / "superpowers"
            / "plans"
            / "2026-08-07-authenticated-spectral-catalog.md",
        )
        legacy_scope = re.compile(
            r"\b(?:91[- ](?:row|root|pair)|"
            r"819[- ](?:row|root|pair)|"
            r"728[- ](?:row|root|pair)|"
            r"2,?520[- ](?:row|root|pair)|"
            r"5,?508[- ](?:row|root|pair))\b",
            re.IGNORECASE,
        )

        for path in current_status_files:
            text = path.read_text(encoding="utf-8")
            with self.subTest(path=path.relative_to(root)):
                for count in ("2,736", "690", "966", "1,080"):
                    self.assertIn(count, text)
                self.assertIsNone(legacy_scope.search(text))

    def test_authenticated_catalog_survives_autocrlf_checkout(self) -> None:
        root = Path(__file__).resolve().parents[1]
        relative_catalog = Path("src/windows_solver/data/kerr_qnm_roots_2736.csv")
        relative_receipt = Path(
            "src/windows_solver/data/kerr_qnm_lattice_receipt.json"
        )
        with (
            tempfile.TemporaryDirectory() as source_directory,
            tempfile.TemporaryDirectory() as checkout_directory,
        ):
            source = Path(source_directory)
            checkout = Path(checkout_directory)
            (source / relative_catalog.parent).mkdir(parents=True)
            shutil.copyfile(root / ".gitattributes", source / ".gitattributes")
            shutil.copyfile(
                root / relative_catalog,
                source / relative_catalog,
            )
            shutil.copyfile(
                root / relative_receipt,
                source / relative_receipt,
            )
            subprocess.run(
                ["git", "init", "--quiet"],
                cwd=source,
                check=True,
                capture_output=True,
                text=True,
            )
            subprocess.run(
                [
                    "git",
                    "add",
                    ".gitattributes",
                    str(relative_catalog),
                    str(relative_receipt),
                ],
                cwd=source,
                check=True,
                capture_output=True,
                text=True,
            )
            subprocess.run(
                [
                    "git",
                    "-c",
                    "core.autocrlf=true",
                    f"--work-tree={checkout}",
                    "checkout-index",
                    "--force",
                    "--all",
                ],
                cwd=source,
                check=True,
                capture_output=True,
                text=True,
            )
            catalog_bytes = (checkout / relative_catalog).read_bytes()
            receipt_bytes = (checkout / relative_receipt).read_bytes()

        self.assertNotIn(b"\r", catalog_bytes)
        self.assertNotIn(b"\r", receipt_bytes)
        self.assertEqual(
            hashlib.sha256(catalog_bytes).hexdigest(),
            CATALOG_DATA_SHA256,
        )
        self.assertEqual(
            hashlib.sha256(receipt_bytes).hexdigest(),
            CATALOG_RECEIPT_SHA256,
        )
