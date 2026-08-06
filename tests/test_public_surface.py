from __future__ import annotations

from pathlib import Path
import re
import unittest


class PublicSurfaceTests(unittest.TestCase):
    def test_windows_launcher_accepts_any_supported_py_runtime(self) -> None:
        root = Path(__file__).resolve().parents[1]
        launcher = (root / "solver.ps1").read_text(encoding="utf-8")

        self.assertIn('PrefixArguments @("-3")', launcher)
        self.assertIn('$PythonPrefixArguments = @("-3")', launcher)
        self.assertNotIn('PrefixArguments @("-3.12")', launcher)

    def test_windows_ci_clears_expected_failure_status(self) -> None:
        root = Path(__file__).resolve().parents[1]
        workflow = (root / ".github" / "workflows" / "ci.yml").read_text(
            encoding="utf-8"
        )

        self.assertRegex(workflow, r"(?m)^          exit 0\s*$")

    def test_public_surface_contains_no_private_lineage_identifiers(self) -> None:
        root = Path(__file__).resolve().parents[1]
        paths = [
            root / "README.md",
            root / "docs" / "architecture.md",
            root / "examples" / "problem-contract.json",
            root / "examples" / "evidence-plan.json",
            root / "solver.ps1",
            *sorted((root / "src" / "windows_solver").glob("*.py")),
        ]
        version_one = "v" + "1"
        version_two = "v" + "2"
        numbered_sequence = re.compile(
            r"(?:stage|target)[\s_-]*\d+", re.IGNORECASE
        )

        findings: list[str] = []
        for path in paths:
            text = path.read_text(encoding="utf-8")
            lowered = text.casefold()
            if version_one in lowered or version_two in lowered:
                findings.append(str(path.relative_to(root)))
            if numbered_sequence.search(text):
                findings.append(str(path.relative_to(root)))

        self.assertEqual(findings, [])
