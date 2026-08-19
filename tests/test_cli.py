from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from dataclasses import replace
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from windows_solver.cli import _campaign_selected, main
from windows_solver.artifacts import ArtifactStore
from windows_solver.builtin import ProblemContractProvider
from windows_solver.contracts import canonical_json_bytes
from windows_solver.engine import RunRecord
from windows_solver.providers import ProviderRegistry

from tests.fixtures import SUPPORTED_SPECTRUM_STUDY, VALID_STUDY


class ExplodingProblemProvider(ProblemContractProvider):
    def execute(self, request, upstream):
        raise RuntimeError("root provider exploded")


class CliTests(unittest.TestCase):
    def invoke(self, arguments: list[str]) -> tuple[int, dict, str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            status = main(arguments)
        output = json.loads(stdout.getvalue()) if stdout.getvalue() else {}
        return status, output, stderr.getvalue()

    def write_study(self, directory: str, **changes) -> Path:
        value = dict(VALID_STUDY, **changes)
        path = Path(directory, "study.json")
        path.write_bytes(canonical_json_bytes(value))
        return path

    def test_plan_prints_deterministic_dependency_closure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            study = self.write_study(directory, target="evidence-package")

            status, output, error = self.invoke(["plan", str(study)])

        self.assertEqual(status, 0)
        self.assertEqual(error, "")
        self.assertEqual(output["command"], "plan")
        self.assertEqual(
            output["plan"]["capabilities"],
            [
                "problem-contract",
                "spectral-core",
                "linear-response",
                "operator-stability",
                "quadratic-ringdown",
                "response-matrix",
                "inverse-inference",
                "signals",
                "detector-inference",
                "evidence-package",
            ],
        )
        self.assertEqual(
            output["unavailable_capabilities"],
            [
                "linear-response",
                "operator-stability",
                "quadratic-ringdown",
                "response-matrix",
                "inverse-inference",
                "signals",
                "detector-inference",
                "evidence-package",
            ],
        )
        self.assertEqual(
            [provider["capability"] for provider in output["providers"]],
            ["problem-contract", "spectral-core"],
        )
        self.assertEqual(
            output["providers"][1]["provider_id"],
            "kerr-qnm-computed-lattice-2736",
        )

    def test_run_then_verify_inspect_and_export(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            study = self.write_study(directory)
            store = Path(directory, "store")
            export = Path(directory, "export.json")

            first_status, first, _ = self.invoke(
                ["run", str(study), "--store", str(store)]
            )
            second_status, second, _ = self.invoke(
                ["run", str(study), "--store", str(store)]
            )
            verify_status, verified, _ = self.invoke(
                ["verify", second["run_id"], "--store", str(store)]
            )
            inspect_status, inspected, _ = self.invoke(
                ["inspect", second["run_id"], "--store", str(store)]
            )
            export_status, exported, _ = self.invoke(
                [
                    "export",
                    second["run_id"],
                    "--store",
                    str(store),
                    "--output",
                    str(export),
                ]
            )
            package = json.loads(export.read_text(encoding="utf-8"))

        self.assertEqual(first_status, 0)
        self.assertEqual(first["provider_execution_count"], 1)
        self.assertEqual(second_status, 0)
        self.assertEqual(second["provider_execution_count"], 0)
        self.assertEqual(second["cache_hit_count"], 1)
        self.assertEqual(verify_status, 0)
        self.assertTrue(verified["verified"])
        self.assertEqual(inspect_status, 0)
        self.assertEqual(inspected["run"]["run_id"], second["run_id"])
        self.assertEqual(export_status, 0)
        self.assertEqual(exported["artifact_count"], 1)
        self.assertEqual(package["run"]["run_id"], second["run_id"])
        self.assertEqual(len(package["artifacts"]), 1)

    def test_spectral_run_is_available_and_verifiable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            study = Path(directory, "spectrum.json")
            study.write_bytes(canonical_json_bytes(SUPPORTED_SPECTRUM_STUDY))
            store = Path(directory, "store")
            export = Path(directory, "spectrum-export.json")

            status, output, error = self.invoke(
                ["run", str(study), "--store", str(store)]
            )
            verify_status, verified, verify_error = self.invoke(
                ["verify", output["run_id"], "--store", str(store)]
            )
            inspect_status, inspected, inspect_error = self.invoke(
                ["inspect", output["run_id"], "--store", str(store)]
            )
            export_status, exported, export_error = self.invoke(
                [
                    "export",
                    output["run_id"],
                    "--store",
                    str(store),
                    "--output",
                    str(export),
                ]
            )
            package = json.loads(export.read_text(encoding="utf-8"))

        self.assertEqual(status, 0)
        self.assertEqual(error, "")
        self.assertEqual(output["provider_execution_count"], 2)
        self.assertEqual(set(output["artifact_ids"]), {
            "problem-contract",
            "spectral-core",
        })
        self.assertEqual(verify_status, 0)
        self.assertEqual(verify_error, "")
        self.assertEqual(verified["artifact_count"], 2)
        self.assertEqual(inspect_status, 0)
        self.assertEqual(inspect_error, "")
        self.assertEqual(
            inspected["artifacts"]["spectral-core"]["payload"][
                "requested_root_count"
            ],
            2,
        )
        self.assertEqual(export_status, 0)
        self.assertEqual(export_error, "")
        self.assertEqual(exported["artifact_count"], 2)
        self.assertEqual(
            package["artifacts"]["spectral-core"]["payload"][
                "requested_root_count"
            ],
            2,
        )

    def test_unavailable_scientific_run_has_distinct_exit_code(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            study = self.write_study(directory, target="linear-response")

            status, output, error = self.invoke(
                ["run", str(study), "--store", str(Path(directory, "store"))]
            )

        self.assertEqual(status, 3)
        self.assertEqual(output, {})
        failure = json.loads(error)
        self.assertEqual(failure["error"]["code"], "PROVIDER_UNAVAILABLE")
        self.assertEqual(failure["error"]["run"]["status"], "FAILED")
        self.assertEqual(
            failure["error"]["run"]["unavailable_capability"],
            "linear-response",
        )

    def test_provider_failure_uses_structured_stderr_and_persists_run(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            study = self.write_study(directory)
            store = Path(directory, "store")
            registry = ProviderRegistry((ExplodingProblemProvider(),))

            with patch(
                "windows_solver.cli.default_registry",
                return_value=registry,
            ):
                status, output, error = self.invoke(
                    ["run", str(study), "--store", str(store)]
                )
            failure = json.loads(error)
            run = failure["error"]["run"]
            inspect_status, inspected, inspect_error = self.invoke(
                ["inspect", run["run_id"], "--store", str(store)]
            )

        self.assertEqual(status, 1)
        self.assertEqual(output, {})
        self.assertEqual(failure["error"]["code"], "EXECUTION_FAILED")
        self.assertEqual(run["failed_capability"], "problem-contract")
        self.assertEqual(run["provider_execution_count"], 0)
        self.assertEqual(inspect_status, 0)
        self.assertEqual(inspect_error, "")
        self.assertEqual(inspected["run"]["run_id"], run["run_id"])

    def test_invalid_study_returns_structured_input_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            study = self.write_study(directory, unexpected=True)

            status, output, error = self.invoke(["plan", str(study)])

        self.assertEqual(status, 2)
        self.assertEqual(output, {})
        self.assertEqual(
            json.loads(error),
            {
                "error": {
                    "code": "INVALID_INPUT",
                    "message": "unknown study fields: unexpected",
                }
            },
        )

    def test_excessively_nested_study_returns_structured_input_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            study = Path(directory, "deep-study.json")
            study.write_text("[" * 2000 + "]" * 2000, encoding="utf-8")

            status, output, error = self.invoke(["plan", str(study)])

        self.assertEqual(status, 2)
        self.assertEqual(output, {})
        self.assertEqual(json.loads(error)["error"]["code"], "INVALID_INPUT")

    def test_duplicate_study_keys_return_structured_input_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            study = Path(directory, "duplicate-study.json")
            canonical = canonical_json_bytes(VALID_STUDY).decode("utf-8")
            study.write_text(
                '{"target":"spectral-core",' + canonical[1:],
                encoding="utf-8",
            )

            status, output, error = self.invoke(["plan", str(study)])

        self.assertEqual(status, 2)
        self.assertEqual(output, {})
        self.assertIn("duplicate study JSON key: target", error)

    def test_publication_verification_rejects_incomplete_capability_scope(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            study = self.write_study(directory)
            store = Path(directory, "store")
            _, run, _ = self.invoke(["run", str(study), "--store", str(store)])

            status, output, error = self.invoke(
                [
                    "verify",
                    run["run_id"],
                    "--store",
                    str(store),
                    "--profile",
                    "publication",
                ]
            )

        self.assertEqual(status, 4)
        self.assertEqual(output, {})
        self.assertIn("complete evidence-package run", error)

    def test_verification_rejects_resealed_truncated_run_closure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            study = self.write_study(directory)
            store_path = Path(directory, "store")
            _, output, _ = self.invoke(
                ["run", str(study), "--store", str(store_path)]
            )
            store = ArtifactStore(store_path)
            record = RunRecord.from_mapping(
                store.load_run_mapping(output["run_id"]),
                expected_run_id=output["run_id"],
            )
            forged = replace(record, artifact_ids={})
            store.put_run_mapping(record.run_id, forged.to_mapping())

            status, _, error = self.invoke(
                ["verify", record.run_id, "--store", str(store_path)]
            )

        self.assertEqual(status, 4)
        self.assertIn("run artifact closure is incomplete", error)

    def test_inspect_rejects_path_traversal_run_id(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            status, output, error = self.invoke(
                ["inspect", "../outside", "--store", directory]
            )

        self.assertEqual(status, 4)
        self.assertEqual(output, {})
        self.assertIn("run identity is invalid", error)

    def test_export_cannot_overwrite_source_store(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            study = self.write_study(directory)
            store = Path(directory, "store")
            _, run, _ = self.invoke(["run", str(study), "--store", str(store)])
            artifact_id = run["artifact_ids"]["problem-contract"]
            artifact_path = store / "artifacts" / f"{artifact_id}.json"

            status, output, error = self.invoke(
                [
                    "export",
                    run["run_id"],
                    "--store",
                    str(store),
                    "--output",
                    str(artifact_path),
                ]
            )
            verify_status, _, _ = self.invoke(
                ["verify", run["run_id"], "--store", str(store)]
            )

        self.assertEqual(status, 4)
        self.assertEqual(output, {})
        self.assertIn("export output must be outside the artifact store", error)
        self.assertEqual(verify_status, 0)

    def test_malformed_run_returns_structured_verification_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = Path(directory, "store")
            run_id = "a" * 32
            path = store / "runs" / f"{run_id}.json"
            path.parent.mkdir(parents=True)
            path.write_text('{"run_id":"' + run_id + '"}', encoding="utf-8")

            status, output, error = self.invoke(
                ["verify", run_id, "--store", str(store)]
            )

        self.assertEqual(status, 4)
        self.assertEqual(output, {})
        self.assertEqual(json.loads(error)["error"]["code"], "VERIFICATION_FAILED")

    def test_nonfinite_stored_artifact_is_a_verification_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            study = self.write_study(directory)
            store = Path(directory, "store")
            _, run, _ = self.invoke(
                ["run", str(study), "--store", str(store)]
            )
            artifact_id = run["artifact_ids"]["problem-contract"]
            path = store / "artifacts" / f"{artifact_id}.json"
            stored = json.loads(path.read_text(encoding="utf-8"))
            stored["payload"]["nonfinite"] = float("nan")
            path.write_text(
                json.dumps(
                    stored,
                    allow_nan=True,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                ),
                encoding="utf-8",
            )

            status, output, error = self.invoke(
                ["verify", run["run_id"], "--store", str(store)]
            )

        self.assertEqual(status, 4)
        self.assertEqual(output, {})
        self.assertEqual(
            json.loads(error)["error"]["code"],
            "VERIFICATION_FAILED",
        )

    def test_campaign_keyboard_interrupt_returns_structured_exit_130(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            selection = root / "selection.json"
            selection.write_bytes(canonical_json_bytes({}))
            with patch("windows_solver.cli.Path.cwd", return_value=root), patch(
                "windows_solver.cli._campaign_selected",
                side_effect=KeyboardInterrupt,
            ):
                status, output, error = self.invoke([
                    "campaign-run",
                    "selection.json",
                    "--checkpoint",
                    "checkpoint.json",
                    "--progress",
                    "quiet",
                ])

        self.assertEqual(status, 130)
        self.assertEqual(output, {})
        self.assertEqual(json.loads(error)["error"]["code"], "INTERRUPTED")

    def test_campaign_calibration_override_requires_path_and_sha_together(self) -> None:
        status, output, error = self.invoke([
            "campaign-run",
            "selection.json",
            "--checkpoint",
            "checkpoint.json",
            "--calibration-receipt-path",
            "override.json",
        ])

        self.assertEqual(status, 2)
        self.assertEqual(output, {})
        diagnostic = json.loads(error)["error"]
        self.assertEqual(diagnostic["code"], "INVALID_INPUT")
        self.assertIn(
            "calibration receipt path and SHA-256 must be supplied together",
            diagnostic["message"],
        )

    def test_campaign_calibration_override_reaches_native_backend_loader(self) -> None:
        digest = "a" * 64
        with patch(
            "windows_solver.cli._campaign_selected",
            return_value=(0, {"command": "campaign-run", "state": "COMPLETE"}),
        ) as selected:
            status, output, error = self.invoke([
                "campaign-run",
                "selection.json",
                "--checkpoint",
                "checkpoint.json",
                "--progress",
                "quiet",
                "--calibration-receipt-path",
                "override.json",
                "--calibration-receipt-sha256",
                digest,
            ])

        self.assertEqual(status, 0)
        self.assertEqual(error, "")
        self.assertEqual(output["state"], "COMPLETE")
        self.assertEqual(
            selected.call_args.kwargs["calibration_receipt_path"],
            Path("override.json"),
        )
        self.assertEqual(
            selected.call_args.kwargs["calibration_receipt_sha256"], digest
        )

    def test_complete_schema_six_resume_enters_checkpoint_migration(self) -> None:
        plan = SimpleNamespace(
            backend_identity=object(), campaign_id="campaign-1"
        )
        selection = SimpleNamespace(
            selection_id="selection-1", leaf_ids=("leaf-1",)
        )
        cached = SimpleNamespace(state="COMPLETE", selection_id="selection-1")
        migrated = SimpleNamespace()
        backend = object()

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            checkpoint = root / "checkpoint.json"
            checkpoint.write_bytes(canonical_json_bytes({"schema_version": 6}))
            with (
                patch(
                    "windows_solver.cli._campaign_plan_and_selection",
                    return_value=(plan, selection, None),
                ),
                patch(
                    "windows_solver.cli.validate_campaign_checkpoint",
                    return_value=cached,
                ),
                patch(
                    "windows_solver.cli._validate_campaign_capability_superset"
                ),
                patch(
                    "windows_solver.cli._load_campaign_backend",
                    return_value=backend,
                ) as load_backend,
                patch(
                    "windows_solver.cli.run_campaign_selection",
                    return_value=migrated,
                ) as run_campaign,
                patch(
                    "windows_solver.cli.import_campaign_checkpoint_to_solved_leaf_store"
                ) as import_cache,
                patch(
                    "windows_solver.cli._campaign_console_mapping",
                    return_value={"migrated": True},
                ),
                patch("windows_solver.cli.Path.cwd", return_value=root),
            ):
                status, output = _campaign_selected(
                    "campaign-resume",
                    root / "selection.json",
                    Path("checkpoint.json"),
                )

        self.assertEqual(status, 0)
        self.assertEqual(output, {"migrated": True})
        load_backend.assert_called_once_with(
            None,
            plan=plan,
            selection=selection,
            calibration_receipt_path=None,
            calibration_receipt_sha256=None,
        )
        run_campaign.assert_called_once()
        self.assertIs(run_campaign.call_args.args[2], backend)
        self.assertTrue(run_campaign.call_args.kwargs["resume"])
        import_cache.assert_not_called()


if __name__ == "__main__":
    unittest.main()
