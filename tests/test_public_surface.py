from __future__ import annotations

from pathlib import Path
import hashlib
import json
import os
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

    @unittest.skipUnless(os.name == "nt", "requires Windows PowerShell 5.1")
    def test_solver_launcher_preserves_positional_command_arguments(self) -> None:
        """Runtime options must not consume the public solver command position."""

        root = Path(__file__).resolve().parents[1]
        windows_powershell = Path(os.environ["SystemRoot"]).joinpath(
            "System32", "WindowsPowerShell", "v1.0", "powershell.exe"
        )
        with tempfile.TemporaryDirectory() as temporary:
            package_root = Path(temporary) / "solver-launcher-binding"
            (package_root / "runtime").mkdir(parents=True)
            (package_root / "src").mkdir()
            shutil.copy2(root / "solver.ps1", package_root / "solver.ps1")
            shutil.copy2(
                root / "runtime" / "resolve-runtime-root.ps1",
                package_root / "runtime" / "resolve-runtime-root.ps1",
            )
            argument_log = package_root / "solver-arguments.json"
            (package_root / "src" / "windows_solver.py").write_text(
                "import json\n"
                "import os\n"
                "import sys\n"
                "from pathlib import Path\n"
                "Path(os.environ['SOLVER_ARGUMENT_LOG']).write_text(\n"
                "    json.dumps(sys.argv[1:]), encoding='utf-8'\n"
                ")\n",
                encoding="utf-8",
            )
            environment = dict(os.environ)
            environment["KERR_QNM_RUNTIME_ROOT"] = str(package_root / "managed")
            environment["SOLVER_ARGUMENT_LOG"] = str(argument_log)
            result = subprocess.run(
                [
                    str(windows_powershell),
                    "-NoLogo",
                    "-NoProfile",
                    "-NonInteractive",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(package_root / "solver.ps1"),
                    "plan",
                    "study.json",
                ],
                cwd=package_root,
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )

            self.assertEqual(
                result.returncode,
                0,
                f"stdout={result.stdout!r} stderr={result.stderr!r}",
            )
            self.assertEqual(
                json.loads(argument_log.read_text(encoding="utf-8")),
                ["plan", "study.json"],
            )

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

    def test_bootstrap_provisions_a_persistent_receipted_interpreter(
        self,
    ) -> None:
        root = Path(__file__).resolve().parents[1]
        launcher = (root / "solver.ps1").read_text(encoding="utf-8")
        bootstrap = (root / "runtime" / "bootstrap.ps1").read_text(
            encoding="utf-8"
        )
        resolver = (root / "runtime" / "resolve-runtime-root.ps1").read_text(
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

        # The launcher follows the receipt written by the bootstrap rather
        # than baking a source-checkout path into its executable preference.
        self.assertIn("Resolve-KerrQnmRuntimeRoot", launcher)
        self.assertIn('Join-Path $ResolvedRuntimeRoot "python-runtime.json"', launcher)
        self.assertIn('$RuntimeReceipt.python.venv', launcher)
        self.assertIn(r'Join-Path $VenvRoot "Scripts\python.exe"', bootstrap)
        self.assertIn(r'Join-Path $RuntimeRoot "python-env', bootstrap)
        self.assertIn("$NumericalEnvironmentId", bootstrap)
        self.assertIn("Get-PythonIdentity", bootstrap)
        self.assertIn("Test-NumericalKernel", bootstrap)
        self.assertIn("source_kind", bootstrap)
        self.assertIn(r".\runtime\bootstrap.ps1", launcher)

        self.assertIn("LOCALAPPDATA", resolver)
        self.assertIn("Kerr-QNM_Windows-Solver\\runtime-1", resolver)
        self.assertIn("[switch]$PortableRuntime", resolver)

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

        # Portable bytes remain untracked; the normal runtime is outside the
        # repository and therefore cannot be accidentally packaged.
        self.assertIn(
            ".runtime/",
            (root / ".gitignore").read_text(encoding="utf-8").splitlines(),
        )

    def test_m02_bootstrap_pins_and_receipts_persistent_julia_contracts(
        self,
    ) -> None:
        root = Path(__file__).resolve().parents[1]
        bootstrap = (root / "runtime" / "bootstrap.ps1").read_text(
            encoding="utf-8"
        )
        discovery = (root / "runtime" / "julia-runtime-discovery.ps1").read_text(
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
        self.assertIn(r'Join-Path $RuntimeRoot "julia\$JuliaVersion"', bootstrap)
        self.assertIn(r'Join-Path $ManagedJuliaRoot "bin\julia.exe"', bootstrap)
        self.assertIn("$Policy.julia.sha256", bootstrap)
        self.assertIn("Get-JuliaCandidate", bootstrap)
        self.assertIn("print(Sys.WORD_SIZE)", discovery)
        self.assertIn("print(Sys.BINDIR)", discovery)
        self.assertIn("windowsapps-juliaup-shim", discovery)
        self.assertIn("julia-runtime-discovery.ps1", bootstrap)
        self.assertIn('"juliaup"', bootstrap)
        self.assertIn(r'Join-Path $RuntimeRoot "scientific-sources\$M02DependencyId"', bootstrap)
        self.assertIn(r'Join-Path $RuntimeRoot "m02-environments\$M02DependencyId"', bootstrap)
        self.assertIn(r'Join-Path $RuntimeRoot "julia-depot\$M02DependencyId"', bootstrap)
        self.assertIn("Test-PersistentDependencySources", bootstrap)
        self.assertIn("julia_runtime", bootstrap)

    def test_m02_dependency_environment_identity_excludes_worker_telemetry(
        self,
    ) -> None:
        """Worker-only edits must not select a new Julia project or depot.

        Removing the dependency-only IDs, or using the worker/aggregate ID in
        either environment path, must make this regression fail.
        """

        root = Path(__file__).resolve().parents[1]
        bootstrap = (root / "runtime" / "bootstrap.ps1").read_text(
            encoding="utf-8"
        )
        policy = json.loads(
            (root / "runtime" / "runtime_policy.json").read_text(
                encoding="utf-8"
            )
        )
        lifecycles = {
            source["id"]: source.get("lifecycle")
            for source in policy["scientific_sources"]
        }

        self.assertEqual(lifecycles["m02-julia-worker"], "worker")
        self.assertEqual(lifecycles["m02-julia-project"], "dependency")
        self.assertEqual(
            lifecycles["m02-julia-manifest-seed"], "dependency"
        )
        self.assertEqual(lifecycles["gsn-cache-producer"], "gsn-cache")
        self.assertIn('$M02DependencyId = "m02-deps-"', bootstrap)
        self.assertIn('$M02WorkerId = "m02-worker-"', bootstrap)
        self.assertIn('$M02GsnCacheId = "m02-gsn-"', bootstrap)
        self.assertIn(
            r'Join-Path $RuntimeRoot "m02-environments\$M02DependencyId"',
            bootstrap,
        )
        self.assertIn(
            r'Join-Path $RuntimeRoot "julia-depot\$M02DependencyId"',
            bootstrap,
        )
        self.assertIn(
            r'Join-Path $RuntimeRoot "m02-workers\$M02WorkerId"',
            bootstrap,
        )
        self.assertIn(
            r'Join-Path $RuntimeRoot "gsn-producers\$M02GsnCacheId"',
            bootstrap,
        )
        self.assertNotIn(
            r'Join-Path $RuntimeRoot "m02-environments\$M02ContractId"',
            bootstrap,
        )
        self.assertNotIn(
            r'Join-Path $RuntimeRoot "julia-depot\$M02ContractId"',
            bootstrap,
        )
        self.assertIn(
            "M02 worker source changed; refreshing worker only", bootstrap
        )
        self.assertIn("M02 dependency environment reused", bootstrap)
        self.assertIn(
            "M02 dependency Manifest changed; rebuilding Julia environment",
            bootstrap,
        )
        warm_path = bootstrap[
            bootstrap.index("    if ($M02Ready) {") : bootstrap.index(
                "\n    else {", bootstrap.index("    if ($M02Ready) {")
            )
        ]
        self.assertIn(
            "M02 worker probe failed; retaining the authenticated dependency environment",
            warm_path,
        )
        self.assertIn("            throw", warm_path)
        self.assertNotIn("Remove-ManagedDirectory", warm_path)
        self.assertNotIn("Pkg.precompile", warm_path)
        self.assertIn("Get-CompatibleLegacyM02Environment", bootstrap)
        self.assertIn(
            "M02 dependency environment reused from authenticated legacy aggregate contract",
            bootstrap,
        )
        self.assertIn("Test-ManifestReferencesPath", bootstrap)
        self.assertIn("$tomlEscapedWindowsPath", bootstrap)
        self.assertIn(
            "$checkoutSourceRoot = [IO.Path]::GetFullPath($JuliaDataRoot)",
            bootstrap,
        )
        self.assertNotIn(
            "$checkoutRoot = [IO.Path]::GetFullPath($PackageRoot)",
            bootstrap,
        )
        self.assertIn("Write-ValidatedM02DependencyReceipt", bootstrap)
        self.assertIn("M02 dependency receipt written:", bootstrap)
        for diagnostic in (
            "M02 dependency SHA-256:",
            "M02 dependency ID:",
            "Dependency receipt path:",
            "Dependency receipt exists:",
            "Expected Project SHA-256:",
            "Receipt Project SHA-256:",
            "Observed Project SHA-256:",
            "Expected Manifest SHA-256:",
            "Observed Manifest SHA-256:",
            "Julia executable SHA-256:",
            "GSN vendor-tree SHA-256:",
            "Angular vendor-tree SHA-256:",
            "Reuse rejected:",
        ):
            self.assertIn(diagnostic, bootstrap)

    def test_m02_bootstrap_extracts_julia_with_windows_tar(self) -> None:
        root = Path(__file__).resolve().parents[1]
        bootstrap = (root / "runtime" / "bootstrap.ps1").read_text(
            encoding="utf-8"
        )
        install_start = bootstrap.index('    if ($null -eq $JuliaCandidate) {\n        $JuliaArchive')
        julia_install = bootstrap[install_start : bootstrap.index("\n    $SourceReceipts", install_start)]

        self.assertIn(
            'Remove-ManagedDirectory $JuliaExtract "previous Julia extraction directory"',
            julia_install,
        )
        self.assertIn(
            'Remove-ManagedDirectory $ManagedJuliaRoot "previous managed Julia runtime directory"',
            julia_install,
        )
        self.assertIn(
            "Windows tar.exe is required to extract the managed Julia runtime.",
            julia_install,
        )
        self.assertIn(
            'Get-Command tar.exe -ErrorAction SilentlyContinue',
            julia_install,
        )
        self.assertIn(
            "Windows tar.exe is required to extract the managed Julia runtime.",
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
        self.assertIn('New-Item -ItemType Directory -Force -Path $JuliaExtract', julia_install)
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

    def test_m02_bootstrap_deploys_worker_data_json_files(self) -> None:
        root = Path(__file__).resolve().parents[1]
        bootstrap = (root / "runtime" / "bootstrap.ps1").read_text(
            encoding="utf-8"
        )
        data_root = root / "src" / "windows_solver" / "data"

        self.assertTrue(
            (data_root / "fixed_root_reliability_projection_authority_v1.json").is_file(),
            "fixed_root_reliability_projection_authority_v1.json must exist in package data",
        )
        self.assertTrue(
            (data_root / "promoted_control_empirical_calibration_v1.json").is_file(),
            "promoted_control_empirical_calibration_v1.json must exist in package data",
        )

        # The bootstrap must deploy both JSON files to the m02-workers parent
        # directory so the worker resolves them via @__DIR__/../<filename>.json.
        deploy_start = bootstrap.index(
            '    $WorkerJsonRoot = Join-Path $RuntimeRoot "m02-workers"'
        )
        deploy_end = bootstrap.index("\n    $DependencyRejectionReason", deploy_start)
        deploy_block = bootstrap[deploy_start:deploy_end]

        self.assertIn(
            '"fixed_root_reliability_projection_authority_v1.json"', deploy_block
        )
        self.assertIn(
            '"promoted_control_empirical_calibration_v1.json"', deploy_block
        )
        self.assertIn(r"src\windows_solver\data", deploy_block)
        self.assertIn("Copy-Item", deploy_block)
        self.assertNotIn(r"m02-workers\$M02WorkerId", deploy_block)

    def test_m02_bootstrap_configures_utf8_console_before_julia(self) -> None:
        root = Path(__file__).resolve().parents[1]
        bootstrap = (root / "runtime" / "bootstrap.ps1").read_text(
            encoding="utf-8"
        )
        m02_start = bootstrap.index("function Set-JuliaUtf8Console")
        m02_bootstrap = bootstrap[
            m02_start : bootstrap.index("\n. (Join-Path $PSScriptRoot", m02_start)
        ]
        chcp = "& $Chcp.Source 65001 | Out-Null"
        input_encoding = "[Console]::InputEncoding = $Utf8NoBom"
        output_encoding = "[Console]::OutputEncoding = $Utf8NoBom"
        native_input_encoding = "$OutputEncoding = $Utf8NoBom"

        self.assertIn(
            "$Utf8NoBom = [System.Text.UTF8Encoding]::new($false)",
            m02_bootstrap,
        )
        self.assertIn(
            "Get-Command chcp.com -ErrorAction SilentlyContinue",
            m02_bootstrap,
        )
        self.assertIn("if ($null -eq $Chcp)", m02_bootstrap)
        self.assertIn(chcp, m02_bootstrap)
        self.assertIn(
            "Could not switch the active console code page to UTF-8 (65001).",
            m02_bootstrap,
        )
        self.assertIn(input_encoding, m02_bootstrap)
        self.assertIn(output_encoding, m02_bootstrap)
        self.assertIn(native_input_encoding, m02_bootstrap)
        self.assertLess(
            m02_bootstrap.index(chcp),
            m02_bootstrap.index(input_encoding),
        )
        self.assertLess(
            m02_bootstrap.index(input_encoding),
            m02_bootstrap.index(output_encoding),
        )
        self.assertLess(
            m02_bootstrap.index(output_encoding),
            m02_bootstrap.index(native_input_encoding),
        )

    def test_m02_bootstrap_installs_julia_by_renaming_the_extracted_tree(
        self,
    ) -> None:
        root = Path(__file__).resolve().parents[1]
        bootstrap = (root / "runtime" / "bootstrap.ps1").read_text(
            encoding="utf-8"
        )
        install_start = bootstrap.index('    if ($null -eq $JuliaCandidate) {\n        $JuliaArchive')
        julia_install = bootstrap[install_start : bootstrap.index("\n    $SourceReceipts", install_start)]
        move = (
            "Move-Item -LiteralPath $ExtractedJuliaRoot "
            "-Destination $ManagedJuliaRoot"
        )
        installed_runtime_check = (
            "if ($null -eq $JuliaCandidate)"
        )

        self.assertIn(move, julia_install)
        self.assertNotIn(
            "Copy-Item -LiteralPath $ExtractedJuliaRoot",
            julia_install,
        )
        self.assertIn(installed_runtime_check, julia_install)
        self.assertIn(
            "Installed managed Julia runtime is absent or incompatible",
            julia_install,
        )
        move_index = julia_install.index(move)
        installed_runtime_check_index = julia_install.index(installed_runtime_check, move_index)
        self.assertLess(
            julia_install.index('if ($null -eq $FoundJulia)'),
            move_index,
        )
        self.assertLess(move_index, installed_runtime_check_index)
        self.assertLess(installed_runtime_check_index, len(julia_install))

    def test_force_reprovision_uses_long_path_safe_runtime_cleanup(self) -> None:
        root = Path(__file__).resolve().parents[1]
        bootstrap = (root / "runtime" / "bootstrap.ps1").read_text(
            encoding="utf-8"
        )
        force_cleanup = bootstrap[
            bootstrap.index("if ($Force -and") : bootstrap.index("\nforeach ($path")
        ]

        self.assertIn(
            'Remove-ManagedDirectory $RuntimeRoot "existing managed runtime directory"',
            force_cleanup,
        )
        helper = bootstrap[
            bootstrap.index("function Remove-ManagedDirectory") : bootstrap.index(
                "\nfunction Read-JsonOrNull"
            )
        ]
        self.assertIn('cmd.exe /c rd /s /q "\\\\?\\$fullPath"', helper)
        self.assertIn("Refusing to remove a filesystem root", helper)

    def test_m02_bootstrap_runs_package_setup_from_a_julia_script(self) -> None:
        root = Path(__file__).resolve().parents[1]
        bootstrap = (root / "runtime" / "bootstrap.ps1").read_text(
            encoding="utf-8"
        )
        setup_start = bootstrap.index("        $SetupExpression = @'")
        project_setup = bootstrap[
            setup_start : bootstrap.index(
                '\n        Write-Step "M02 Julia project, depot, and precision worker are ready"',
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
        setup_invoke = project_setup.index("            Invoke-Julia @(")
        setup_cleanup = project_setup.index(
            "                Remove-Item -LiteralPath $SetupScript -Force"
        )
        worker_path = project_setup.index(
            "        $WorkerPath = $PersistentWorkerPath"
        )
        worker_probe = project_setup.index('        "--probe"')

        self.assertIn(
            "$SetupScript",
            project_setup[setup_invoke:setup_cleanup],
        )
        self.assertLess(setup_invoke, setup_cleanup)
        self.assertLess(setup_cleanup, worker_path)
        self.assertLess(worker_path, worker_probe)

    def test_retired_campaign_runbook_is_absent(self) -> None:
        root = Path(__file__).resolve().parents[1]
        self.assertFalse(
            (root / "docs" / "response-replay-powershell.md").exists()
        )

    def test_m02_launcher_exposes_separate_schema11_passes(self) -> None:
        root = Path(__file__).resolve().parents[1]
        launcher = (root / "m02.ps1").read_text(encoding="utf-8")
        solver_launcher = (root / "solver.ps1").read_text(encoding="utf-8")
        selection = json.loads(
            (root / "examples" / "m02-campaign.json").read_text(encoding="utf-8")
        )

        self.assertEqual(selection["role"], "all")
        self.assertIsNone(selection["leaf_ids"])
        self.assertEqual(selection["precision_digits"], [64, 80, 120])
        self.assertIn("[switch]$RebuildRuntime", launcher)
        self.assertIn("[switch]$NewCampaign", launcher)
        self.assertIn(
            '[ValidateSet("survey", "admit", "certify", "validate", "resolve-system-failure")]',
            launcher,
        )
        self.assertIn(
            '[ValidateSet("binary64", "promoted", "full")]',
            launcher,
        )
        self.assertIn('[string]$SurveyPass = "full"', launcher)
        self.assertIn('"campaign-plan"', launcher)
        self.assertIn('Write-Host "M02 campaign startup"', launcher)
        self.assertIn('"campaign-survey-binary64"', launcher)
        self.assertIn('"campaign-lock-binary64"', launcher)
        self.assertIn('"campaign-survey-promoted"', launcher)
        self.assertIn('"campaign-certify"', launcher)
        self.assertIn('"campaign-evidence-validate"', launcher)
        self.assertIn('"campaign-schema11-validate"', launcher)
        self.assertNotIn('campaign-resume', launcher)
        self.assertIn('if ($RebuildRuntime)', launcher)
        self.assertIn('[ValidateSet("quiet", "normal", "trace")]', launcher)
        self.assertIn('[string]$Progress = "normal"', launcher)
        self.assertIn('"--progress"', launcher)
        self.assertIn('$RunSessionId = [Guid]::NewGuid().ToString("N")', launcher)
        self.assertIn('Start-Transcript -Path $TranscriptStagingPath -Force', launcher)
        self.assertIn('"--diagnostic-session-id", $RunSessionId', launcher)
        self.assertIn('"console-transcript.txt"', launcher)
        self.assertIn("if ($CommandExitCode -eq 130)", launcher)
        self.assertIn("exit 130", launcher)
        self.assertIn("PipelineStoppedException", launcher)
        self.assertIn("PipelineStoppedException", solver_launcher)
        self.assertIn("-1073741510", solver_launcher)
        self.assertIn('"campaign-plan",\n        $SelectionPath\n', launcher)
        self.assertNotIn('"campaign-plan",\n        $Selection\n', launcher)

    def test_m02_launcher_forwards_only_sha_pinned_calibration_overrides(self) -> None:
        root = Path(__file__).resolve().parents[1]
        launcher = (root / "m02.ps1").read_text(encoding="utf-8")

        self.assertIn("[string]$CalibrationReceiptPath", launcher)
        self.assertIn("[string]$CalibrationReceiptSha256", launcher)
        self.assertIn(
            "calibration receipt path and SHA-256 must be supplied together",
            launcher,
        )
        self.assertIn('"--calibration-receipt-path"', launcher)
        self.assertIn('"--calibration-receipt-sha256"', launcher)

    @unittest.skipUnless(os.name == "nt", "requires Windows PowerShell 5.1")
    def test_m02_launcher_binds_bootstrap_switches_at_the_script_boundary(
        self,
    ) -> None:
        """The launcher must bind, rather than merely construct, bootstrap switches.

        A real PowerShell invocation runs a copied ``m02.ps1`` against a
        parameter-bearing bootstrap stub.  The stub records its bound switch
        values; no runtime, Julia, or scientific command is executed.
        """

        root = Path(__file__).resolve().parents[1]
        windows_powershell = Path(os.environ["SystemRoot"]).joinpath(
            "System32", "WindowsPowerShell", "v1.0", "powershell.exe"
        )

        with tempfile.TemporaryDirectory() as temporary:
            package_root = Path(temporary) / "m02-bootstrap-binding"
            (package_root / "examples").mkdir(parents=True)
            (package_root / "runtime").mkdir()
            (package_root / "src" / "windows_solver" / "data").mkdir(parents=True)
            shutil.copy2(root / "m02.ps1", package_root / "m02.ps1")
            shutil.copy2(
                root / "runtime" / "resolve-runtime-root.ps1",
                package_root / "runtime" / "resolve-runtime-root.ps1",
            )
            shutil.copy2(
                root / "examples" / "m02-campaign.json",
                package_root / "examples" / "m02-campaign.json",
            )
            shutil.copy2(
                root
                / "src"
                / "windows_solver"
                / "data"
                / "promoted_control_empirical_calibration_v1.json",
                package_root
                / "src"
                / "windows_solver"
                / "data"
                / "promoted_control_empirical_calibration_v1.json",
            )
            bootstrap_log = package_root / "bootstrap-bindings.jsonl"
            argument_log = package_root / "arguments.jsonl"
            (package_root / "runtime" / "bootstrap.ps1").write_text(
r'''param(
    [switch]$WithM02,
    [switch]$Force,
    [switch]$PortableRuntime,
    [string]$RuntimeRoot
)

$record = [ordered]@{
    with_m02 = [bool]$WithM02
    force = [bool]$Force
    portable_runtime = [bool]$PortableRuntime
    runtime_root = $RuntimeRoot
}
[IO.File]::AppendAllText(
    $env:M02_TEST_BOOTSTRAP_LOG,
    ($record | ConvertTo-Json -Compress) + [Environment]::NewLine,
    [System.Text.UTF8Encoding]::new($false)
)
exit 0
''',
                encoding="utf-8",
            )
            (package_root / "solver.ps1").write_text(
                r'''param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$SolverArguments
)

$record = $SolverArguments | ConvertTo-Json -Compress
[IO.File]::AppendAllText(
    $env:M02_TEST_ARGUMENT_LOG,
    $record + [Environment]::NewLine,
    [System.Text.UTF8Encoding]::new($false)
)
if ($SolverArguments[0] -eq "campaign-prepare-resources") {
    exit 0
}
if ($SolverArguments[0] -eq "campaign-plan") {
    '{"role_counts":{"primary":140,"control":24,"deep":48},"leaf_count":212}'
    exit 0
}
if ($SolverArguments[0] -eq "campaign-new") {
    $outputIndex = [Array]::IndexOf($SolverArguments, "--output")
    $checkpoint = [IO.Path]::GetFullPath($SolverArguments[$outputIndex + 1])
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $checkpoint) |
        Out-Null
    [IO.File]::WriteAllText($checkpoint, "{}")
    exit 0
}
if ($SolverArguments[0] -eq "campaign-lock-binary64") {
    $outputIndex = [Array]::IndexOf($SolverArguments, "--output")
    $lock = [IO.Path]::GetFullPath($SolverArguments[$outputIndex + 1])
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $lock) |
        Out-Null
    [IO.File]::WriteAllText($lock, "{}")
    exit 0
}
if ($SolverArguments[0] -eq "campaign-schema11-validate") {
    '{"selection_id":"selection-1","schema_version":11,"recovered_terminal_count":0,"binary64_pass_count":0,"promotion_queue_count":0,"evidence_counts":{},"basic_report_directory":"reports"}'
    exit 0
}
$checkpointIndex = [Array]::IndexOf($SolverArguments, "--checkpoint")
if ($checkpointIndex -lt 0) {
    exit 91
}
exit 0
''',
                encoding="utf-8",
            )
            environment = dict(os.environ)
            environment["M02_TEST_BOOTSTRAP_LOG"] = str(bootstrap_log)
            environment["M02_TEST_ARGUMENT_LOG"] = str(argument_log)
            environment["KERR_QNM_RUNTIME_ROOT"] = str(package_root / "managed")

            for extra_arguments in (
                ["-NewCampaign"],
                ["-RebuildRuntime"],
                ["-PortableRuntime"],
            ):
                result = subprocess.run(
                    [
                        str(windows_powershell),
                        "-NoLogo",
                        "-NoProfile",
                        "-NonInteractive",
                        "-ExecutionPolicy",
                        "Bypass",
                        "-File",
                        str(package_root / "m02.ps1"),
                        *extra_arguments,
                    ],
                    cwd=root,
                    env=environment,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    check=False,
                )
                self.assertEqual(
                    result.returncode,
                    0,
                    f"stdout={result.stdout!r} stderr={result.stderr!r}",
                )

            bindings = [
                json.loads(line)
                for line in bootstrap_log.read_text(encoding="utf-8").splitlines()
            ]

        self.assertEqual(
            bindings,
            [
                {
                    "with_m02": True,
                    "force": False,
                    "portable_runtime": False,
                    "runtime_root": "",
                },
                {
                    "with_m02": True,
                    "force": True,
                    "portable_runtime": False,
                    "runtime_root": "",
                },
                {
                    "with_m02": True,
                    "force": False,
                    "portable_runtime": True,
                    "runtime_root": "",
                },
            ],
        )

    @unittest.skipUnless(os.name == "nt", "requires Windows PowerShell 5.1")
    def test_runtime_root_resolver_uses_localappdata_unless_portable(self) -> None:
        """Exercise the actual resolver without provisioning any runtime."""

        root = Path(__file__).resolve().parents[1]
        windows_powershell = Path(os.environ["SystemRoot"]).joinpath(
            "System32", "WindowsPowerShell", "v1.0", "powershell.exe"
        )
        with tempfile.TemporaryDirectory() as temporary:
            temporary_root = Path(temporary)
            package_root = temporary_root / "downloaded-solver"
            local_app_data = temporary_root / "local-app-data"
            package_root.mkdir()
            environment = dict(os.environ)
            environment["M02_TEST_RUNTIME_RESOLVER"] = str(
                root / "runtime" / "resolve-runtime-root.ps1"
            )
            environment["M02_TEST_PACKAGE_ROOT"] = str(package_root)
            environment["M02_TEST_LOCALAPPDATA"] = str(local_app_data)
            resolver_log = temporary_root / "resolver.json"
            environment["M02_TEST_RESOLVER_LOG"] = str(resolver_log)
            script = r'''
$env:LOCALAPPDATA = $env:M02_TEST_LOCALAPPDATA
Remove-Item Env:KERR_QNM_RUNTIME_ROOT -ErrorAction SilentlyContinue
. $env:M02_TEST_RUNTIME_RESOLVER
$default = Resolve-KerrQnmRuntimeRoot -PackageRoot $env:M02_TEST_PACKAGE_ROOT
$portable = Resolve-KerrQnmRuntimeRoot -PackageRoot $env:M02_TEST_PACKAGE_ROOT -PortableRuntime
$record = [ordered]@{ default = $default; portable = $portable } | ConvertTo-Json -Compress
[IO.File]::WriteAllText(
    $env:M02_TEST_RESOLVER_LOG,
    $record,
    [System.Text.UTF8Encoding]::new($false)
)
'''
            result = subprocess.run(
                [
                    str(windows_powershell),
                    "-NoLogo",
                    "-NoProfile",
                    "-NonInteractive",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-Command",
                    script,
                ],
                cwd=root,
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            self.assertEqual(
                result.returncode,
                0,
                f"stdout={result.stdout!r} stderr={result.stderr!r}",
            )
            resolved = json.loads(resolver_log.read_text(encoding="utf-8"))
            expected_default = (
                local_app_data / "Kerr-QNM_Windows-Solver" / "runtime-1"
            )
            expected_portable = package_root / ".runtime"
            expected_default.mkdir(parents=True)
            expected_portable.mkdir()
            self.assertTrue(Path(resolved["default"]).samefile(expected_default))
            self.assertTrue(Path(resolved["portable"]).samefile(expected_portable))

    @unittest.skipUnless(os.name == "nt", "requires Windows PowerShell 5.1")
    def test_m02_public_default_invocation_runs_locked_full_chain(self) -> None:
        root = Path(__file__).resolve().parents[1]
        windows_powershell = Path(os.environ["SystemRoot"]).joinpath(
            "System32", "WindowsPowerShell", "v1.0", "powershell.exe"
        )

        with tempfile.TemporaryDirectory() as temporary:
            package_root = Path(temporary) / "m02-public"
            (package_root / "examples").mkdir(parents=True)
            (package_root / "runtime").mkdir()
            (package_root / "src" / "windows_solver" / "data").mkdir(parents=True)
            shutil.copy2(root / "m02.ps1", package_root / "m02.ps1")
            shutil.copy2(
                root / "runtime" / "resolve-runtime-root.ps1",
                package_root / "runtime" / "resolve-runtime-root.ps1",
            )
            shutil.copy2(
                root / "examples" / "m02-campaign.json",
                package_root / "examples" / "m02-campaign.json",
            )
            calibration_path = (
                package_root
                / "src"
                / "windows_solver"
                / "data"
                / "promoted_control_empirical_calibration_v1.json"
            )
            shutil.copy2(
                root
                / "src"
                / "windows_solver"
                / "data"
                / "promoted_control_empirical_calibration_v1.json",
                calibration_path,
            )
            calibration_sha256 = hashlib.sha256(
                calibration_path.read_bytes()
            ).hexdigest()
            argument_log = package_root / "arguments.jsonl"
            (package_root / "solver.ps1").write_text(
                r'''param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$SolverArguments
)

$record = $SolverArguments | ConvertTo-Json -Compress
[IO.File]::AppendAllText(
    $env:M02_TEST_ARGUMENT_LOG,
    $record + [Environment]::NewLine,
    [System.Text.UTF8Encoding]::new($false)
)
if ($SolverArguments[0] -eq "campaign-prepare-resources") {
    exit 0
}
if ($SolverArguments[0] -eq "campaign-plan") {
    '{"role_counts":{"primary":140,"control":24,"deep":48},"leaf_count":212}'
    exit 0
}
if ($SolverArguments[0] -eq "campaign-lock-binary64") {
    $outputIndex = [Array]::IndexOf($SolverArguments, "--output")
    $lock = [IO.Path]::GetFullPath($SolverArguments[$outputIndex + 1])
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $lock) |
        Out-Null
    [IO.File]::WriteAllText($lock, "{}")
    exit 0
}
if ($SolverArguments[0] -eq "campaign-schema11-validate") {
    '{"selection_id":"selection-1","schema_version":11,"recovered_terminal_count":0,"binary64_pass_count":0,"promotion_queue_count":0,"evidence_counts":{},"basic_report_directory":"reports"}'
    exit 0
}
$checkpointIndex = [Array]::IndexOf($SolverArguments, "--checkpoint")
if ($checkpointIndex -lt 0) {
    exit 91
}
exit 0
''',
                encoding="utf-8",
            )
            environment = dict(os.environ)
            environment["M02_TEST_ARGUMENT_LOG"] = str(argument_log)
            environment["KERR_QNM_RUNTIME_ROOT"] = str(package_root / "managed")
            checkpoint_path = (
                package_root / "m02-output" / "m02-campaign-checkpoint.json"
            )
            checkpoint_path.parent.mkdir()
            checkpoint_path.write_text("{}", encoding="utf-8")
            result = subprocess.run(
                [
                    str(windows_powershell),
                    "-NoLogo",
                    "-NoProfile",
                    "-NonInteractive",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(package_root / "m02.ps1"),
                    "-SkipBootstrap",
                ],
                cwd=root,
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            self.assertEqual(
                result.returncode,
                0,
                f"stdout={result.stdout!r} stderr={result.stderr!r}",
            )
            calls = [
                json.loads(line)
                for line in argument_log.read_text(encoding="utf-8").splitlines()
            ]
            selection_path = package_root / "examples" / "m02-campaign.json"
            binary64_lock_path = Path(f"{checkpoint_path}.binary64-lock.json")
            for call in calls:
                self.assertTrue(Path(call[1]).samefile(selection_path))
                call[1] = str(selection_path)
            for call in calls[2:]:
                checkpoint_index = call.index("--checkpoint") + 1
                self.assertTrue(
                    Path(call[checkpoint_index]).samefile(checkpoint_path)
                )
                call[checkpoint_index] = str(checkpoint_path)
            for call in calls:
                if "--output" in call:
                    output_index = call.index("--output") + 1
                    self.assertTrue(
                        Path(call[output_index]).samefile(binary64_lock_path)
                    )
                    call[output_index] = str(binary64_lock_path)
                if "--binary64-lock" in call:
                    lock_index = call.index("--binary64-lock") + 1
                    self.assertTrue(
                        Path(call[lock_index]).samefile(binary64_lock_path)
                    )
                    call[lock_index] = str(binary64_lock_path)
                if "--calibration-receipt-path" in call:
                    calibration_index = call.index("--calibration-receipt-path") + 1
                    self.assertTrue(
                        Path(call[calibration_index]).samefile(calibration_path)
                    )
                    call[calibration_index] = str(calibration_path)
            for call in calls:
                if "--diagnostic-session-id" in call:
                    session_index = call.index("--diagnostic-session-id") + 1
                    self.assertRegex(call[session_index], r"^[0-9a-f]{32}$")
                    call[session_index] = "generated-session-id"

        selection = str(selection_path)
        checkpoint = str(checkpoint_path)
        binary64_lock = str(binary64_lock_path)
        calibration = str(calibration_path)
        self.assertEqual(
            calls,
            [
                [
                    "campaign-prepare-resources",
                    selection,
                ],
                [
                    "campaign-plan",
                    selection,
                ],
                [
                    "campaign-schema11-validate",
                    selection,
                    "--checkpoint",
                    checkpoint,
                ],
                [
                    "campaign-survey-binary64",
                    selection,
                    "--checkpoint",
                    checkpoint,
                    "--progress",
                    "normal",
                    "--diagnostic-session-id",
                    "generated-session-id",
                ],
                [
                    "campaign-lock-binary64",
                    selection,
                    "--checkpoint",
                    checkpoint,
                    "--output",
                    binary64_lock,
                ],
                [
                    "campaign-survey-promoted",
                    selection,
                    "--checkpoint",
                    checkpoint,
                    "--progress",
                    "normal",
                    "--diagnostic-session-id",
                    "generated-session-id",
                    "--calibration-receipt-path",
                    calibration,
                    "--calibration-receipt-sha256",
                    calibration_sha256,
                    "--binary64-lock",
                    binary64_lock,
                ],
                [
                    "campaign-schema11-validate",
                    selection,
                    "--checkpoint",
                    checkpoint,
                    "--pass",
                    "promoted",
                    "--binary64-lock",
                    binary64_lock,
                ],
            ],
        )
        self.assertTrue(Path(checkpoint).is_absolute())

    @unittest.skipUnless(os.name == "nt", "requires Windows PowerShell 5.1")
    def test_m02_public_default_invocation_starts_new_campaign_when_checkpoint_absent(
        self,
    ) -> None:
        """A fresh checkout has no default checkpoint. Plain ``m02.ps1``
        must treat that as an ordinary first run under the default full
        survey profile, not require a separate ``-NewCampaign`` flag."""

        root = Path(__file__).resolve().parents[1]
        windows_powershell = Path(os.environ["SystemRoot"]).joinpath(
            "System32", "WindowsPowerShell", "v1.0", "powershell.exe"
        )

        with tempfile.TemporaryDirectory() as temporary:
            package_root = Path(temporary) / "m02-cold-start"
            (package_root / "examples").mkdir(parents=True)
            (package_root / "runtime").mkdir()
            (package_root / "src" / "windows_solver" / "data").mkdir(parents=True)
            shutil.copy2(root / "m02.ps1", package_root / "m02.ps1")
            shutil.copy2(
                root / "runtime" / "resolve-runtime-root.ps1",
                package_root / "runtime" / "resolve-runtime-root.ps1",
            )
            shutil.copy2(
                root / "examples" / "m02-campaign.json",
                package_root / "examples" / "m02-campaign.json",
            )
            calibration_path = (
                package_root
                / "src"
                / "windows_solver"
                / "data"
                / "promoted_control_empirical_calibration_v1.json"
            )
            shutil.copy2(
                root
                / "src"
                / "windows_solver"
                / "data"
                / "promoted_control_empirical_calibration_v1.json",
                calibration_path,
            )
            calibration_sha256 = hashlib.sha256(
                calibration_path.read_bytes()
            ).hexdigest()
            argument_log = package_root / "arguments.jsonl"
            (package_root / "solver.ps1").write_text(
                r'''param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$SolverArguments
)

$record = $SolverArguments | ConvertTo-Json -Compress
[IO.File]::AppendAllText(
    $env:M02_TEST_ARGUMENT_LOG,
    $record + [Environment]::NewLine,
    [System.Text.UTF8Encoding]::new($false)
)
if ($SolverArguments[0] -eq "campaign-prepare-resources") {
    exit 0
}
if ($SolverArguments[0] -eq "campaign-new") {
    $outputIndex = [Array]::IndexOf($SolverArguments, "--output")
    $checkpoint = [IO.Path]::GetFullPath($SolverArguments[$outputIndex + 1])
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $checkpoint) |
        Out-Null
    [IO.File]::WriteAllText($checkpoint, "{}")
    exit 0
}
if ($SolverArguments[0] -eq "campaign-plan") {
    '{"role_counts":{"primary":140,"control":24,"deep":48},"leaf_count":212}'
    exit 0
}
if ($SolverArguments[0] -eq "campaign-lock-binary64") {
    $outputIndex = [Array]::IndexOf($SolverArguments, "--output")
    $lock = [IO.Path]::GetFullPath($SolverArguments[$outputIndex + 1])
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $lock) |
        Out-Null
    [IO.File]::WriteAllText($lock, "{}")
    exit 0
}
if ($SolverArguments[0] -eq "campaign-schema11-validate") {
    '{"selection_id":"selection-1","schema_version":11,"recovered_terminal_count":0,"binary64_pass_count":0,"promotion_queue_count":0,"evidence_counts":{},"basic_report_directory":"reports"}'
    exit 0
}
$checkpointIndex = [Array]::IndexOf($SolverArguments, "--checkpoint")
if ($checkpointIndex -lt 0) {
    exit 91
}
exit 0
''',
                encoding="utf-8",
            )
            environment = dict(os.environ)
            environment["M02_TEST_ARGUMENT_LOG"] = str(argument_log)
            environment["KERR_QNM_RUNTIME_ROOT"] = str(package_root / "managed")
            checkpoint_path = (
                package_root / "m02-output" / "m02-campaign-checkpoint.json"
            )
            self.assertFalse(checkpoint_path.exists())
            result = subprocess.run(
                [
                    str(windows_powershell),
                    "-NoLogo",
                    "-NoProfile",
                    "-NonInteractive",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(package_root / "m02.ps1"),
                    "-SkipBootstrap",
                ],
                cwd=root,
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            self.assertEqual(
                result.returncode,
                0,
                f"stdout={result.stdout!r} stderr={result.stderr!r}",
            )
            self.assertTrue(checkpoint_path.is_file())
            calls = [
                json.loads(line)
                for line in argument_log.read_text(encoding="utf-8").splitlines()
            ]
            selection_path = package_root / "examples" / "m02-campaign.json"
            for call in calls:
                self.assertTrue(Path(call[1]).samefile(selection_path))
                call[1] = str(selection_path)
            output_index = calls[1].index("--output") + 1
            self.assertTrue(Path(calls[1][output_index]).samefile(checkpoint_path))
            calls[1][output_index] = str(checkpoint_path)
            binary64_lock_path = Path(f"{checkpoint_path}.binary64-lock.json")
            for call in calls[3:]:
                checkpoint_index = call.index("--checkpoint") + 1
                self.assertTrue(
                    Path(call[checkpoint_index]).samefile(checkpoint_path)
                )
                call[checkpoint_index] = str(checkpoint_path)
            for call in calls:
                if "--output" in call and call[0] == "campaign-lock-binary64":
                    output_index = call.index("--output") + 1
                    self.assertTrue(
                        Path(call[output_index]).samefile(binary64_lock_path)
                    )
                    call[output_index] = str(binary64_lock_path)
                if "--binary64-lock" in call:
                    lock_index = call.index("--binary64-lock") + 1
                    self.assertTrue(
                        Path(call[lock_index]).samefile(binary64_lock_path)
                    )
                    call[lock_index] = str(binary64_lock_path)
                if "--calibration-receipt-path" in call:
                    calibration_index = call.index("--calibration-receipt-path") + 1
                    self.assertTrue(
                        Path(call[calibration_index]).samefile(calibration_path)
                    )
                    call[calibration_index] = str(calibration_path)
            for call in calls:
                if "--diagnostic-session-id" in call:
                    session_index = call.index("--diagnostic-session-id") + 1
                    self.assertRegex(call[session_index], r"^[0-9a-f]{32}$")
                    call[session_index] = "generated-session-id"

        selection = str(selection_path)
        checkpoint = str(checkpoint_path)
        binary64_lock = str(binary64_lock_path)
        calibration = str(calibration_path)
        self.assertEqual(
            calls,
            [
                [
                    "campaign-prepare-resources",
                    selection,
                ],
                [
                    "campaign-new",
                    selection,
                    "--output",
                    checkpoint,
                ],
                [
                    "campaign-plan",
                    selection,
                ],
                [
                    "campaign-schema11-validate",
                    selection,
                    "--checkpoint",
                    checkpoint,
                ],
                [
                    "campaign-survey-binary64",
                    selection,
                    "--checkpoint",
                    checkpoint,
                    "--progress",
                    "normal",
                    "--diagnostic-session-id",
                    "generated-session-id",
                ],
                [
                    "campaign-lock-binary64",
                    selection,
                    "--checkpoint",
                    checkpoint,
                    "--output",
                    binary64_lock,
                ],
                [
                    "campaign-survey-promoted",
                    selection,
                    "--checkpoint",
                    checkpoint,
                    "--progress",
                    "normal",
                    "--diagnostic-session-id",
                    "generated-session-id",
                    "--calibration-receipt-path",
                    calibration,
                    "--calibration-receipt-sha256",
                    calibration_sha256,
                    "--binary64-lock",
                    binary64_lock,
                ],
                [
                    "campaign-schema11-validate",
                    selection,
                    "--checkpoint",
                    checkpoint,
                    "--pass",
                    "promoted",
                    "--binary64-lock",
                    binary64_lock,
                ],
            ],
        )

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

    @unittest.skipUnless(os.name == "nt", "requires Windows PowerShell 5.1")
    def test_actual_bootstrap_parses_and_executes_safe_powershell51_smoke(self) -> None:
        """Catch parser and path-character regressions before provisioning.

        The production change that must fail this test is either an invalid
        PowerShell interpolation such as ``$Label:`` or a two-character value
        passed to a ``[char[]]`` path-trimming call.  It runs the actual
        bootstrap's safe smoke path, which creates and removes only its own
        temporary directory; no runtime, package, Julia, or solver work runs.
        """

        root = Path(__file__).resolve().parents[1]
        windows_powershell = Path(os.environ["SystemRoot"]).joinpath(
            "System32", "WindowsPowerShell", "v1.0", "powershell.exe"
        )
        result = subprocess.run(
            [
                str(windows_powershell),
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(root / "runtime" / "bootstrap.ps1"),
                "-PowerShell51Smoke",
            ],
            cwd=root,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        self.assertEqual(
            result.returncode,
            0,
            f"stdout={result.stdout!r} stderr={result.stderr!r}",
        )
        self.assertIn(
            b"PowerShell 5.1 compatibility smoke passed", result.stdout
        )
        self.assertIn(
            b"M02 dependency lifecycle smoke passed", result.stdout
        )
        self.assertIn(b"Dependency receipt exists: False", result.stdout)
        self.assertIn(
            b"Reuse rejected: dependency receipt is absent", result.stdout
        )
        self.assertIn(
            b"Reuse rejected: dependency receipt is malformed:", result.stdout
        )

    @unittest.skipUnless(os.name == "nt", "requires Windows PowerShell 5.1")
    def test_juliaup_windowsapps_shim_resolves_and_hashes_real_julia_executable(
        self,
    ) -> None:
        """A WindowsApps shim is a launcher, never the hash/receipt target.

        The test executes the shared production Julia discovery function in
        Windows PowerShell 5.1.  Native probing is controlled only because the
        test fixture is not a Julia installation; filesystem resolution and
        the discovery logic remain real.  Hashing the WindowsApps alias throws
        immediately, while hashing the resolved ``Sys.BINDIR\\julia.exe`` is
        required to succeed.
        """

        root = Path(__file__).resolve().parents[1]
        windows_powershell = Path(os.environ["SystemRoot"]).joinpath(
            "System32", "WindowsPowerShell", "v1.0", "powershell.exe"
        )
        with tempfile.TemporaryDirectory() as temporary:
            fixture_root = Path(temporary)
            windows_apps = fixture_root / "WindowsApps"
            real_bin = fixture_root / "Julia-1.10.11" / "bin"
            windows_apps.mkdir()
            real_bin.mkdir(parents=True)
            launcher = windows_apps / "julia.exe"
            real_executable = real_bin / "julia.exe"
            launcher.write_text("shim", encoding="utf-8")
            real_executable.write_text("real-julia", encoding="utf-8")
            record_path = fixture_root / "candidate.json"
            environment = dict(os.environ)
            environment["M02_TEST_JULIA_DISCOVERY"] = str(
                root / "runtime" / "julia-runtime-discovery.ps1"
            )
            environment["M02_TEST_JULIA_LAUNCHER"] = str(launcher)
            environment["M02_TEST_JULIA_BINDIR"] = str(real_bin)
            environment["M02_TEST_JULIA_RECORD"] = str(record_path)
            script = r'''
$Policy = [pscustomobject]@{ julia = [pscustomobject]@{ version = "1.10.11" } }
function Try-InvokeNativeCapture([string]$FilePath, [string[]]$Arguments) {
    $joined = $Arguments -join " "
    if ($joined -eq "+1.10.11 --version" -or $joined -eq "--version") {
        return "julia version 1.10.11"
    }
    if ($joined -match "Sys.WORD_SIZE") { return "64" }
    if ($joined -match "Sys.BINDIR") { return $env:M02_TEST_JULIA_BINDIR }
    throw "unexpected Julia probe: $FilePath $joined"
}
function Get-Sha256([string]$Path) {
    if ($Path -like "*WindowsApps*") { throw "WindowsApps shim must not be hashed" }
    if ((Get-Content -LiteralPath $Path -Raw) -ne "real-julia") {
        throw "unexpected hash target: $Path"
    }
    return "real-julia-sha256"
}
. $env:M02_TEST_JULIA_DISCOVERY
$candidate = Get-JuliaCandidate $env:M02_TEST_JULIA_LAUNCHER @("+1.10.11") "juliaup"
$candidate | ConvertTo-Json -Compress | Set-Content -LiteralPath $env:M02_TEST_JULIA_RECORD -Encoding UTF8
'''
            environment["M02_TEST_JULIA_REAL"] = str(real_executable)
            result = subprocess.run(
                [
                    str(windows_powershell),
                    "-NoLogo",
                    "-NoProfile",
                    "-NonInteractive",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-Command",
                    script,
                ],
                cwd=root,
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            self.assertEqual(
                result.returncode,
                0,
                f"stdout={result.stdout!r} stderr={result.stderr!r}",
            )
            candidate = json.loads(record_path.read_text(encoding="utf-8-sig"))
            self.assertEqual(candidate["source"], "juliaup")
            self.assertTrue(Path(candidate["launcher"]).samefile(launcher))
            self.assertTrue(
                Path(candidate["executable"]).samefile(real_executable)
            )
            self.assertEqual(
                candidate["executable_sha256"], "real-julia-sha256"
            )
            self.assertEqual(candidate["arguments"], [])

    def test_public_surface_contains_no_private_lineage_identifiers(self) -> None:
        root = Path(__file__).resolve().parents[1]
        paths = [
            root / "README.md",
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
        approved_regularised_gsn_identities = frozenset({
            "exterior-wronskian/v1",
            "canonical-exterior-background-wronskian/v1",
            "background-equivalence/v1",
            "exterior-fixed-root-survey-raw/v1",
            "fixed-root-deep-v1",
            "producer-retryability-capability/v1",
            "zero-coupling-profile-elision/v1",
            "real-axis-wronskian-at-readout/v1",
            "relative-1e-5-times-one-plus-abs-omega/v1",
            "legacy-compatibility/v1",
            "solved-leaf-cache/v1",
            "windows-solver.campaign-recovery/v1",
            "windows-solver.recovery-summary/v1",
            "windows-solver.root-readout-recovery-index/v2",
            "windows-solver.promoted-cache-supersession/v1",
            "promoted-policy-preflight/v1",
            "promoted-independent-review-admission/v1",
            "promoted-admission-checkpoint-commit/v1",
            "promoted-admission-publication-retry/v1",
            "promoted-publication-completion/v1",
            "solved-leaf-store-publication/v1",
            "promoted-exterior-checkpoint-reduction/v1",
            "promoted-horizon-checkpoint-reduction/v1",
            "promoted-exterior-control-return/v1",
            "promoted-exterior-control-return/v2",
            "promoted-exterior-control-decision/v1",
            "promoted-horizon-control-return/v2",
            "promoted-horizon-control-decision/v1",
            "promoted-exterior-retained-artifact/v2",
            "promoted-fixed-root-composite/v2",
            "promoted-fixed-root-survey/v2",
            "promoted-horizon-calculation/v2",
            "windows-solver.system-failure/v1",
            "windows-solver.system-failure-resolution/1",
            "windows-solver.system-failure-resolution/2",
            "windows-solver.structural-event/1",
            "windows-solver.structural-event/2",
            "windows-solver.independent-promoted-review-receipt/1",
            "windows-solver.promoted-background-reuse-key/1",
            "windows-solver.promoted-calculation-stage/1",
            "windows-solver.promoted-calculation-stage/2",
            "windows-solver.promoted-canonical-background/1",
            "windows-solver.promoted-exterior-determinant-rederivation/1",
            "windows-solver.promoted-fixed-root-batch-receipt/1",
            "windows-solver.promoted-fixed-root-composite/2",
            "windows-solver.promoted-horizon-calculation/2",
            "windows-solver.promoted-horizon-failure/1",
            "windows-solver.promoted-horizon-lineage-reduction/1",
            "windows-solver.promoted-numerical-continuation/2",
            "windows-solver.promoted-queue-disposition/1",
            "windows-solver.promoted-raw-calculation-retention/2",
            "windows-solver.promoted-root-evidence-receipt/1",
            "windows-solver.promoted-root-evidence-receipt/2",
            "windows-solver.response-component-job/1",
            "windows-solver.m02-report-status/v1",
            "windows-solver.m02-schema11-report-status/v1",
            "binary64-horizon-production/v1",
            "binary64-horizon-production/v2",
            "binary64-horizon-analytic-component/v1",
            "binary64-fixed-root-horizon-response/v1",
            "promoted-horizon-component/v1",
            "promoted-horizon-component/v2",
            "promoted-horizon-production/v2",
            "promoted-horizon-comparison/v2",
            "promoted-survey-production/v1",
            "production-certification-comparator/v1",
            "independent-validation-comparator/v1",
            "same-backend-refinement/v1",
            "exterior-finite-amplitude-root-displacement/v1",
            "horizon-finite-amplitude-scattering/v1",
            "windows-solver.projective-triage-projection/v1",
            "approved-reviewed-error/v1",
            "adaptive-exterior-gap-standoff/v2",
            "factored-homogeneous-gsn/v1",
            "factored-plane-wave-gsn/v1",
            "horizon-scattering/v1",
            "same-precision-120-base-vs-refinement/v1",
            "typed-batch-horner-compensated/v1",
            "scaled-factored-horizon-basis/v1",
            "factored-three-leg-horizon-basis-at-match-gsn/v1",
            "real-inner-tortoise-contour/v1",
            "scaled-horizon-basis-at-match/v1",
            "staged-real-axis-h-h2/v1",
            "full-h-h2-2h-ih-ladder/v1",
            "verified-endpoint-absolute-error/v1",
            "verified-endpoint-control-equivalence-absolute-error/v2",
            "adaptive-horizon-endpoint-recovery/v1",
            "adequate/v1",
            "no-geometry-valid-candidate/v1",
            "maximum-series-order-inadequate/v1",
            "arithmetic-precision-inadequate/v1",
            "coordinate-inversion-failure/v1",
            "fewer-than-two-verified-endpoints/v1",
            "approved/v1",
            "reviewed/v1",
            "absent-unapproved/v1",
            "absent-unreviewed/v1",
            "cinc-over-cref-minus-reflectivity/v1",
            "series-recurrence-basis-fd/v1",
            "gsn-complex-rho/v1",
            (
                "column1=horizon-ingoing-Cref;"
                "column2=horizon-outgoing-Cinc/v1"
            ),
            "state2=dX/drho/v1",
            "cinc-over-cref-minus-R/v1",
            "known-carrier-times-regular-remainder/v1",
            "state1=Y;state2=dY/drho/v1",
            "unit-asymptotic-branch-wronskian/v1",
            "wronskian-perturbed-Xin-with-Xup/v1",
            (
                "blocked-pending-human-math-review-and-independent-"
                "reference/v1"
            ),
            "available/v1",
            "unavailable-overflow/v1",
            "not-applicable/v1",
            "coordinate-inversion-stalled/v1",
            "coordinate-inversion/v1",
            "finite-difference-derivative/v1",
            "invalid-frequency-step/v1",
            "finite-difference-request-policy/v1",
            "binary64-parity-primary-fixed-root-diagnostics/v1",
            "binary64-parity-primary-fixed-root-diagnostics-frequency-disk/v2",
            "abs-determinant-over-abs-complex-derivative/v1",
            "single-promoted-root-analytic-horizon-component/v1",
            "analytic-horizon-from-promoted-primary-derivative/v1",
            "single-promoted-horizon-root-after-80-preflight/v1",
            "finest-resolved-consecutive-epsilon-window/v1",
            "coarser-amplitude-expansion-with-resolved-window/v1",
            "NOT_REQUIRED_BY_V1_4_PROMOTED_ROOT_POLICY",
            "bounded-analytic-horizon-from-promoted-primary-derivative/v2",
            "direct-fixed-root-determinant-derivative/v1",
            "exterior-derivative-response-disk/v1",
            "failed-preflight-120-fixed-root-exterior-derivative/v1",
            "fixed-root-exterior-derivative-component/v1",
            "fixed-root-h-h2-conditioning/v1",
            "fixed-root-frequency-h-h2-stencil/v1",
            "fixed-root-holomorphic-axis-validation/v1",
            "full-complex-ladder-validation/v1",
            "primary-derivative-authentication/v1",
            "authenticated-promoted-root-seal/v1",
            "root-sealed-fixed-root-response-repair/v1",
            "root-sealed-stale-exterior-response-discarded/v1",
            "fixed-root-domega-stencil-only/v1",
            "fixed-root-dc-stencil-only/v1",
            "fixed-root-domega-dc-stencils-only/v1",
            "max-accepted-correction-plus-arithmetic/v1",
            "primary-root-controls-and-derivative-disk/v1",
            "readout-specific-semantic-tier/v1",
            "run_promoted_horizon_component/v2",
            "same-equation-signed-root-component-journal/v1",
            "selective-signed-root-promotion-component/v1",
            "single-promoted-root-bounded-analytic-horizon-component/v2",
            "promoted-horizon-typed-failure-component/v1",
            "promoted-horizon-typed-failure/v1",
            "PROMOTED_HORIZON_BOUNDED_COMPONENT_IDENTITY",
            "PROMOTED_HORIZON_BOUNDED_RESPONSE_METHOD",
            "M02_Production_222_A9999_Endpoint_Recovery_v1.ps1",
            "M02_Production_LightRing_A9999_Response_Recovery_v1.ps1",
            "selective-signed-root-promotion-component/v1/",
            "unavailable/v1",
            "insufficient-series-order/v1",
            "insufficient-arithmetic-precision/v1",
            "insufficient-geometric-depth/v1",
            "cause-aware-fixed-root-exterior-endpoint-recovery/v1",
            "bounded-doubling-prefix/v1",
            "bounded-negative-rho-depth/v1",
            "bounded-positive-rho-depth/v1",
            "windows-solver.fixed-root-v2-forensic-history/1",
            "forensic_fixed_root_v2_history",
            "_contains_fixed_root_v2_artifact",
            "_migrate_fixed_root_v2_forensic_history",
            "promoted-control-empirical-calibration/v1",
            "fixed-root-reliability-projection-authority/v1",
            "data/fixed_root_reliability_projection_authority_v1.json",
            "minus-log10-target-plus-required-digit-guard/v1",
            "julia-control-diagnostics/v1",
            "supervisor-timeout/v1",
            "bounded-worker-wall-clock-resource-exhausted/v1",
            "first-determinant-linear-lower-bound/v1",
            "exterior-determinant-absolute-error-certificate/empirical-v1",
            "operator-approved/v1",
            "permitted/v1",
            "blocked-pending-independent-review/v1",
            "independent-promoted-review-retained-stage/v1",
            "empirical-current-run-only/v1",
            "windows-solver.horizon-promotion-trigger/v1",
            "windows-solver.promoted-horizon-survey-comparison/v1",
            "windows-solver.deep-trigger-policy/v1",
            "windows-solver.fixed-sentinel-set/v1",
            "data/promoted_control_empirical_calibration_v1.json",
            "data/promoted_control_derivative_lower_bound_source_audit_v1.json",
            # PR69 public scientific identities: the additive-channels
            # provisional exterior model, the v2 horizon response contract,
            # the provisional-stage operation identity, and the root
            # evidence store identities all authenticate real current
            # production output.
            "exterior-determinant-additive-channels/provisional-v1",
            "binary64-fixed-root-horizon-response/v2",
            "binary64-horizon-analytic-component/v2",
            "binary64-fixed-root-provisional/v1",
            "m02-horizon-exterior-response-math/v1",
            "finite-radius-endpoint-wedge/raw-oriented/v1",
            "fixed-kerr-background-coordinate/v1",
            "scientific-compatibility/v1",
            "windows-solver.repeated-outcome-diagnostics/v1",
            "authenticated-root-evidence-v2",
            "root-evidence-v2",
            # The frozen binary64 handoff uses explicit public receipt and
            # evidence-store identities for its externally inspectable
            # checkpoint sidecar.
            "windows-solver.binary64-layer-lock/1",
            "windows-solver.binary64-layer-projection/1",
            "windows-solver.root-evidence-store/v2",
            "windows-solver.canonical-background-evidence-store/v1",
            "windows-solver.root-readout-store/v3",
            "windows-solver.root-readout-cache/3",
            # PR69 keeps the forensic v2 horizon lineage readable without
            # letting it re-authenticate as current science. The
            # constants below name that forensic path in code, in
            # persisted receipts, and in the recovery reason field; each
            # points at internal legacy handling, not a public scientific
            # identity, so they are approved as tokens the guard should
            # treat as expected internal references.
            "binary64-horizon-production/v2",
            "BINARY64_HORIZON_COMPONENT",
            "BINARY64_HORIZON_RESPONSE_METHOD",
            "STALE_HORIZON_REASON",
            "HORIZON_RESPONSE_V2_SCIENTIFICALLY_STALE",
            "FORENSIC_V2_STALE",
            "MIXED_V2_V3_INVALID",
            "HORIZON_RESPONSE_MIXED_V2_V3_INVALID",
            # Internal helper names for legacy-forensic paths. They only
            # appear inside the package's Python source and never reach
            # a persisted receipt or a public identifier, so approving
            # the identifier tokens keeps the guard tight without
            # renaming symbols that document the forensic boundary.
            "_stale_horizon_v2_receipt",
            "legacy_v2_horizon_response_disk",
            "forensic_v2_scientific_computation_identity_sha256",
            "_forensic_v2_root_seed",
            "_V2_HORIZON_OPERATION",
        })
        lineage_character = r"A-Za-z0-9_/:;=+\-"
        approved_identity = re.compile(
            rf"(?<![{lineage_character}])(?:"
            + "|".join(
                re.escape(identity)
                for identity in sorted(
                    approved_regularised_gsn_identities,
                    key=len,
                    reverse=True,
                )
            )
            + rf")(?![{lineage_character}])"
        )

        def contains_unapproved_lineage_version(text: str) -> bool:
            text = re.sub(r'''["']\s*["']''', "", text)
            remaining = approved_identity.sub("", text).casefold()
            return version_one in remaining or version_two in remaining

        for identity in approved_regularised_gsn_identities:
            self.assertFalse(contains_unapproved_lineage_version(identity))
        for arbitrary_label in (
            "private-lineage/v1",
            "private-lineage/v2",
            "private-factored-plane-wave-gsn/v1",
            "factored-plane-wave-gsn/v1-private",
            "available/v1-private",
            "unavailable-overflow/v2",
            "not-applicable/v1-extra",
        ):
            self.assertTrue(
                contains_unapproved_lineage_version(arbitrary_label)
            )
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
            if contains_unapproved_lineage_version(text):
                findings.append(str(path.relative_to(root)))
            if numbered_sequence.search(text):
                findings.append(str(path.relative_to(root)))
            if "flagship" in lowered:
                findings.append(str(path.relative_to(root)))
            if wrong_scope_language.search(text):
                findings.append(str(path.relative_to(root)))

        self.assertEqual(findings, [])

    def test_current_status_documents_describe_the_current_solver_boundary(
        self,
    ) -> None:
        root = Path(__file__).resolve().parents[1]
        current_status_files = (
            root / "README.md",
            root / "docs" / "architecture.md",
        )
        stale = re.compile(
            r"only the problem-contract provider|"
            r"numerical science providers are unavailable until migrated",
            re.IGNORECASE,
        )

        for path in current_status_files:
            text = path.read_text(encoding="utf-8")
            with self.subTest(path=path.relative_to(root)):
                self.assertIn("M02", text)
                self.assertIn("pure-Kerr", text)
                self.assertIn("linear-response", text)
                self.assertIn("release", text.casefold())
                self.assertIsNone(stale.search(text))

    def test_current_status_states_complete_pure_kerr_lattice_without_legacy_scope(
        self,
    ) -> None:
        root = Path(__file__).resolve().parents[1]
        current_status_files = (
            root / "README.md",
            root / "docs" / "architecture.md",
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
                self.assertIn("2,736", text)
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
