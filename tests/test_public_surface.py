from __future__ import annotations

from pathlib import Path
import hashlib
import json
import re
import shutil
import subprocess
import tempfile
import tomllib
import unittest

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

    def test_launcher_probe_cannot_abort_on_a_stderr_writing_candidate(
        self,
    ) -> None:
        """A rejected candidate must fall through, not terminate the launcher.

        The Windows App Execution Alias stub for ``python.exe`` writes to
        stderr, which Windows PowerShell 5.1 raises as a terminating
        ``NativeCommandError`` while ``ErrorActionPreference`` is ``Stop``.
        The probe must therefore hold its own preference and report failure
        through the exit code alone, or the remaining candidates and the
        actionable "not found" message become unreachable.
        """

        root = Path(__file__).resolve().parents[1]
        launcher = (root / "solver.ps1").read_text(encoding="utf-8")
        probe = launcher[launcher.index("function Test-Python312") :]
        probe = probe[: probe.index("\n$PythonExecutable")]

        self.assertIn('$ErrorActionPreference = "Continue"', probe)
        self.assertIn("$previous = $ErrorActionPreference", probe)
        self.assertIn("finally", probe)
        self.assertIn("$ErrorActionPreference = $previous", probe)
        self.assertIn("return $false", probe)

    def test_bootstrap_provisions_the_launcher_preferred_interpreter(
        self,
    ) -> None:
        root = Path(__file__).resolve().parents[1]
        launcher = (root / "solver.ps1").read_text(encoding="utf-8")
        bootstrap = (root / "runtime" / "bootstrap.ps1").read_text(
            encoding="utf-8"
        )
        policy = json.loads(
            (root / "runtime" / "runtime_policy.json").read_text(
                encoding="utf-8"
            )
        )
        configuration = tomllib.loads(
            (root / "pyproject.toml").read_text(encoding="utf-8")
        )

        # The launcher must prefer exactly the path the bootstrap creates.
        self.assertIn(r".runtime\venv\Scripts\python.exe", launcher)
        self.assertIn(r'Join-Path $VenvRoot "Scripts\python.exe"', bootstrap)
        self.assertIn(r'Join-Path $RuntimeRoot "venv"', bootstrap)
        self.assertIn(r".\runtime\bootstrap.ps1", launcher)

        # The provisioned runtime must match the recorded spectral provenance.
        recorded = json.loads(
            (
                root
                / "src"
                / "windows_solver"
                / "data"
                / "kerr_qnm_lattice_receipt.json"
            ).read_text(encoding="utf-8")
        )["runtime"]
        self.assertEqual(
            policy["python"]["python_version"], recorded["python"]
        )
        self.assertEqual(policy["python"]["implementation"], "CPython")
        self.assertEqual(policy["python"]["bits"], 64)

        # The optional numerical tier must not drift from the declared extra.
        self.assertEqual(
            [
                f"{package['name']}=={package['version']}"
                for package in policy["numerical_kernel"]["packages"]
            ],
            configuration["project"]["optional-dependencies"][
                "numerical-tests"
            ],
        )

        # .runtime must stay untracked so the provisioned bytes never ship.
        self.assertIn(
            ".runtime/",
            (root / ".gitignore").read_text(encoding="utf-8").splitlines(),
        )

    def test_m02_bootstrap_pins_package_local_julia_for_the_cache_producer(
        self,
    ) -> None:
        root = Path(__file__).resolve().parents[1]
        bootstrap = (root / "runtime" / "bootstrap.ps1").read_text(
            encoding="utf-8"
        )
        policy = json.loads(
            (root / "runtime" / "runtime_policy.json").read_text(
                encoding="utf-8"
            )
        )
        julia = policy["julia"]

        self.assertEqual(julia["version"], "1.10.11")
        self.assertEqual(julia["archive"], "julia-1.10.11-win64.zip")
        self.assertEqual(
            julia["sha256"],
            "11ba52fd1384f82d09ea232eb1552b6694bb2083e6adfe3ae2f9e1e663ed8cf8",
        )
        self.assertTrue(julia["url"].startswith("https://julialang-s3.julialang.org/"))
        self.assertIn("[switch]$WithM02", bootstrap)
        self.assertIn(r'Join-Path $RuntimeRoot "julia"', bootstrap)
        self.assertIn(r'Join-Path $JuliaRoot "bin\julia.exe"', bootstrap)
        self.assertIn("$Policy.julia.sha256", bootstrap)
        self.assertIn("julia_runtime", bootstrap)

    def test_m02_bootstrap_extracts_julia_with_windows_tar(self) -> None:
        root = Path(__file__).resolve().parents[1]
        bootstrap = (root / "runtime" / "bootstrap.ps1").read_text(
            encoding="utf-8"
        )
        julia_install = bootstrap[
            bootstrap.index(
                'if (-not (Test-Path -LiteralPath $JuliaExe -PathType Leaf))'
            ) : bootstrap.index("\n    $JuliaIdentity")
        ]

        self.assertIn(
            'cmd.exe /c rd /s /q "\\\\?\\$JuliaExtract"',
            julia_install,
        )
        self.assertIn(
            'cmd.exe /c rd /s /q "\\\\?\\$JuliaRoot"',
            julia_install,
        )
        self.assertIn(
            "Could not remove previous Julia extraction directory",
            julia_install,
        )
        self.assertIn(
            "Could not remove previous Julia runtime directory",
            julia_install,
        )
        self.assertIn(
            "Could not remove Julia extraction directory after installation",
            julia_install,
        )
        self.assertEqual(julia_install.count("cmd.exe /c rd /s /q"), 3)
        self.assertNotIn("Remove-Item -LiteralPath $Julia", julia_install)
        self.assertIn(
            'Get-Command tar.exe -ErrorAction SilentlyContinue',
            julia_install,
        )
        self.assertIn(
            "Windows tar.exe is required to extract the portable Julia runtime.",
            julia_install,
        )
        self.assertIn(
            '& $Tar.Source -xf $JuliaArchive -C $JuliaExtract',
            julia_install,
        )
        self.assertIn(
            "Julia archive extraction failed with tar.exe exit code",
            julia_install,
        )
        self.assertIn(
            'New-Item -ItemType Directory -Force -Path $JuliaExtract',
            julia_install,
        )
        self.assertIn(
            'Get-ChildItem -LiteralPath $JuliaExtract -Filter "julia.exe"',
            julia_install,
        )
        self.assertIn(
            'if ($null -eq $FoundJulia)',
            julia_install,
        )
        self.assertIn(
            "Verified Julia archive contains no julia.exe.",
            julia_install,
        )
        self.assertNotIn("Expand-Archive", julia_install)

    def test_m02_bootstrap_installs_julia_by_renaming_the_extracted_tree(
        self,
    ) -> None:
        root = Path(__file__).resolve().parents[1]
        bootstrap = (root / "runtime" / "bootstrap.ps1").read_text(
            encoding="utf-8"
        )
        julia_install = bootstrap[
            bootstrap.index(
                'if (-not (Test-Path -LiteralPath $JuliaExe -PathType Leaf))'
            ) : bootstrap.index("\n    $JuliaIdentity")
        ]
        move = (
            "Move-Item -LiteralPath $ExtractedJuliaRoot "
            "-Destination $JuliaRoot"
        )
        installed_runtime_check = (
            "if (-not (Test-Path -LiteralPath $JuliaExe -PathType Leaf))"
        )

        self.assertIn(move, julia_install)
        self.assertNotIn(
            "Copy-Item -LiteralPath $ExtractedJuliaRoot",
            julia_install,
        )
        self.assertIn(installed_runtime_check, julia_install)
        self.assertIn(
            "Installed Julia runtime contains no julia.exe.",
            julia_install,
        )
        move_index = julia_install.index(move)
        installed_runtime_check_index = julia_install.index(
            installed_runtime_check,
            move_index,
        )
        self.assertLess(
            julia_install.index('if ($null -eq $FoundJulia)'),
            move_index,
        )
        self.assertLess(move_index, installed_runtime_check_index)
        self.assertLess(
            installed_runtime_check_index,
            julia_install.index(
                "Could not remove Julia extraction directory after installation"
            ),
        )

    def test_force_reprovision_uses_long_path_safe_runtime_cleanup(self) -> None:
        root = Path(__file__).resolve().parents[1]
        bootstrap = (root / "runtime" / "bootstrap.ps1").read_text(
            encoding="utf-8"
        )
        force_cleanup = bootstrap[
            bootstrap.index("if ($Force -and") : bootstrap.index(
                "\nforeach ($path"
            )
        ]

        self.assertIn(
            'cmd.exe /c rd /s /q "\\\\?\\$RuntimeRoot"',
            force_cleanup,
        )
        self.assertIn(
            "Could not remove existing runtime directory",
            force_cleanup,
        )
        self.assertNotIn("Remove-Item", force_cleanup)

    def test_m02_bootstrap_runs_package_setup_from_a_julia_script(self) -> None:
        root = Path(__file__).resolve().parents[1]
        bootstrap = (root / "runtime" / "bootstrap.ps1").read_text(
            encoding="utf-8"
        )
        setup_start = bootstrap.index("    $SetupExpression = @'")
        project_setup = bootstrap[
            setup_start : bootstrap.index(
                '\n    Write-Step "Julia runtime, pinned GSN sources, and precision worker ready"',
                setup_start,
            )
        ]

        self.assertIn(
            '$SetupScript = Join-Path $TempRoot "m02-setup.jl"',
            project_setup,
        )
        self.assertIn("[IO.File]::WriteAllText", project_setup)
        self.assertIn(
            "[System.Text.UTF8Encoding]::new($false)",
            project_setup,
        )
        self.assertNotIn('"-e"', project_setup)
        setup_invoke = project_setup.index("    Invoke-Native $JuliaExe @(")
        setup_cleanup = project_setup.index(
            "    Remove-Item -LiteralPath $SetupScript -Force"
        )
        worker_path = project_setup.index(
            '    $WorkerPath = Join-Path $JuliaDataRoot "m02_worker.jl"'
        )
        worker_probe = project_setup.index('        "--probe"')
        receipt = project_setup.index("    $JuliaReceipt = [ordered]@{")

        self.assertIn(
            "$SetupScript",
            project_setup[setup_invoke:setup_cleanup],
        )
        self.assertLess(setup_invoke, setup_cleanup)
        self.assertLess(setup_cleanup, worker_path)
        self.assertLess(worker_path, worker_probe)
        self.assertLess(worker_probe, receipt)

    def test_campaign_runbook_has_no_historic_cache_environment_prerequisite(
        self,
    ) -> None:
        root = Path(__file__).resolve().parents[1]
        runbook = (root / "docs" / "response-replay-powershell.md").read_text(
            encoding="utf-8"
        )

        self.assertNotIn("GSN_INFINITY_SERIES_CACHE", runbook)
        self.assertIn(r".\runtime\bootstrap.ps1 -WithM02", runbook)
        self.assertIn("campaign-run", runbook)

    def test_m02_launcher_runs_the_full_selection_and_can_rebuild_runtime(self) -> None:
        root = Path(__file__).resolve().parents[1]
        launcher = (root / "m02.ps1").read_text(encoding="utf-8")
        selection = json.loads(
            (root / "examples" / "m02-campaign.json").read_text(encoding="utf-8")
        )

        self.assertEqual(selection["role"], "all")
        self.assertIsNone(selection["leaf_ids"])
        self.assertEqual(selection["precision_digits"], [64, 80, 120])
        self.assertIn("[switch]$RebuildRuntime", launcher)
        self.assertIn('campaign-resume', launcher)
        self.assertIn('"--full"', launcher)
        self.assertIn('if ($RebuildRuntime)', launcher)
        self.assertIn('$BootstrapArguments += "-Force"', launcher)

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

    def test_current_status_names_pr2_pr3_m01_and_pr4_linear_response(self) -> None:
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
                self.assertIn("PR #4", text)
                self.assertIn("M01", text)
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

    def test_authenticated_package_data_survives_autocrlf_checkout(self) -> None:
        root = Path(__file__).resolve().parents[1]
        data_root = root / "src" / "windows_solver" / "data"
        relative_resources = tuple(
            path.relative_to(root)
            for path in sorted(data_root.rglob("*"))
            if path.is_file()
        )
        expected = {
            path: hashlib.sha256((root / path).read_bytes()).hexdigest()
            for path in relative_resources
        }
        with (
            tempfile.TemporaryDirectory() as source_directory,
            tempfile.TemporaryDirectory() as checkout_directory,
        ):
            source = Path(source_directory)
            checkout = Path(checkout_directory)
            shutil.copyfile(root / ".gitattributes", source / ".gitattributes")
            for relative in relative_resources:
                target = source / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(root / relative, target)
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
                    *(str(path) for path in relative_resources),
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
            actual = {
                path: hashlib.sha256((checkout / path).read_bytes()).hexdigest()
                for path in relative_resources
            }

        self.assertEqual(actual, expected)
