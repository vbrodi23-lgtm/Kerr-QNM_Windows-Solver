from __future__ import annotations

from pathlib import Path
import json
import os
import shutil
import subprocess
import tempfile
import unittest


@unittest.skipUnless(
    os.name == "nt" and os.environ.get("M02_RUNTIME_INTEGRATION") == "1",
    "requires explicit Windows M02_RUNTIME_INTEGRATION=1 execution",
)
class M02PersistentRuntimeIntegrationTests(unittest.TestCase):
    """Exercise a real cold then cross-checkout warm M02 runtime lifecycle.

    This deliberately does not run in ordinary CI: it provisions/uses a real
    Julia runtime and persistent Julia environment.  It is the acceptance
    gate for a clean Windows host with the execution environment explicitly
    opting in.
    """

    def test_clean_runtime_is_reused_by_a_second_clean_checkout(self) -> None:
        root = Path(__file__).resolve().parents[1]
        windows_powershell = Path(os.environ["SystemRoot"]).joinpath(
            "System32", "WindowsPowerShell", "v1.0", "powershell.exe"
        )
        with tempfile.TemporaryDirectory() as temporary:
            temporary_root = Path(temporary)
            runtime_root = temporary_root / "LocalAppData" / "runtime-1"
            checkout_one = temporary_root / "checkout-one"
            checkout_two = temporary_root / "checkout-two"
            ignore = shutil.ignore_patterns(
                ".git", ".runtime", "m02-output", ".solver-store", "dist"
            )
            shutil.copytree(root, checkout_one, ignore=ignore)
            shutil.copytree(root, checkout_two, ignore=ignore)

            def bootstrap(checkout: Path) -> subprocess.CompletedProcess[bytes]:
                return subprocess.run(
                    [
                        str(windows_powershell),
                        "-NoLogo",
                        "-NoProfile",
                        "-NonInteractive",
                        "-ExecutionPolicy",
                        "Bypass",
                        "-File",
                        str(checkout / "runtime" / "bootstrap.ps1"),
                        "-WithM02",
                        "-SkipSmokeTest",
                        "-RuntimeRoot",
                        str(runtime_root),
                    ],
                    cwd=checkout,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    check=False,
                )

            first = bootstrap(checkout_one)
            self.assertEqual(
                first.returncode,
                0,
                f"cold stdout={first.stdout!r} stderr={first.stderr!r}",
            )
            receipt = json.loads(
                (runtime_root / "python-runtime.json").read_text(encoding="utf-8-sig")
            )
            julia = receipt["julia_runtime"]
            dependency_id = julia["dependency_contract_id"]
            environment_receipt = (
                runtime_root
                / "metadata"
                / "m02-environments"
                / f"{dependency_id}.json"
            )
            before = environment_receipt.read_bytes()
            environment = json.loads(before)
            self.assertEqual(
                environment["dependency_contract_id"], dependency_id
            )
            self.assertEqual(
                Path(environment["dependency_source_root"]),
                runtime_root / "scientific-sources" / dependency_id,
            )

            unchanged = bootstrap(checkout_one)
            self.assertEqual(
                unchanged.returncode,
                0,
                f"same-checkout stdout={unchanged.stdout!r} "
                f"stderr={unchanged.stderr!r}",
            )
            self.assertEqual(environment_receipt.read_bytes(), before)
            self.assertIn(
                b"M02 Julia project/depot receipt and probe are valid",
                unchanged.stdout,
            )
            self.assertNotIn(b"Pkg.precompile", unchanged.stdout)
            self.assertNotIn(b"Instantiating and precompiling", unchanged.stdout)

            worker = (
                checkout_two
                / "src"
                / "windows_solver"
                / "data"
                / "julia"
                / "m02_worker.jl"
            )
            worker.write_text(
                worker.read_text(encoding="utf-8")
                + "\n# telemetry-only cross-checkout identity regression\n",
                encoding="utf-8",
            )
            telemetry = bootstrap(checkout_two)
            self.assertEqual(
                telemetry.returncode,
                0,
                f"telemetry stdout={telemetry.stdout!r} "
                f"stderr={telemetry.stderr!r}",
            )
            self.assertEqual(environment_receipt.read_bytes(), before)
            self.assertIn(
                b"M02 worker source changed; refreshing worker only",
                telemetry.stdout,
            )
            self.assertIn(b"M02 dependency environment reused", telemetry.stdout)
            self.assertNotIn(b"Pkg.precompile", telemetry.stdout)
            self.assertNotIn(b"Instantiating and precompiling", telemetry.stdout)
            telemetry_receipt = json.loads(
                (runtime_root / "python-runtime.json").read_text(encoding="utf-8-sig")
            )["julia_runtime"]
            self.assertEqual(
                telemetry_receipt["dependency_contract_id"], dependency_id
            )
            self.assertNotEqual(
                telemetry_receipt["worker_contract_id"],
                julia["worker_contract_id"],
            )
            self.assertEqual(telemetry_receipt["project"], julia["project"])
            self.assertEqual(telemetry_receipt["depot"], julia["depot"])

            project = Path(julia["project"])
            manifest = (project / "Manifest.toml").read_text(encoding="utf-8")
            self.assertNotIn(str(checkout_one), manifest)
            self.assertNotIn(str(checkout_two), manifest)
            self.assertNotIn("../vendor/", manifest)
            for package in (
                "GeneralizedSasakiNakamura.jl",
                "SpinWeightedSpheroidalHarmonics.jl",
            ):
                source = runtime_root / "scientific-sources" / dependency_id / package
                native_source = str(source)
                self.assertTrue(
                    source.as_posix() in manifest
                    or native_source.replace("\\", "\\\\") in manifest,
                    f"Manifest does not bind {source}",
                )
                self.assertTrue(
                    (source / "Project.toml").is_file(), source / "Project.toml"
                )
