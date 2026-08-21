from __future__ import annotations

import copy
from dataclasses import replace
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from windows_solver.contracts import canonical_json_bytes
from windows_solver.julia_response_backend import (
    JuliaResponseAdapter,
    JuliaResponseBackendError,
    _validate_promoted_request_preflight_response,
    build_promoted_request_contract_fixture,
    promoted_request_preflight_documents,
)
from windows_solver.promoted_control_calibration import (
    load_default_calibration_receipt,
)
from windows_solver.response_batches import (
    NativeCampaignStageBackend,
    NativeResourceUnavailableError,
    PrecisionCapabilities,
    build_campaign_plan,
)
from windows_solver.response_engine import NumericalPolicy, VettedNativeDeterminantKernel


LEAF_42_ID = (
    "b-prime-leaf-5a27a5fdc15f95de33d6773b16f89a9f594fe5ffd018f9ee94bbab91949fd653"
)
LEAF_42_HORIZON_ID = (
    "b-prime-leaf-28b8e2f139fae4ebbb839320057a127429f7a01a3cc2cac60b526815ad0e7252"
)
WORKER = (
    Path(__file__).resolve().parents[1]
    / "src/windows_solver/data/julia/m02_worker.jl"
)
JULIA_SPEC = WORKER.with_name("m02_worker_request_contract_spec.jl")


def _plan():
    return build_campaign_plan(
        policy=NumericalPolicy(),
        backend_identity=VettedNativeDeterminantKernel.identity,
        precision_capabilities=PrecisionCapabilities((64, 80, 120)),
    )


def _preflight_documents():
    plan = _plan()
    exterior = next(leaf.job for leaf in plan.leaves if leaf.leaf_id == LEAF_42_ID)
    horizon = next(
        leaf.job for leaf in plan.leaves if leaf.leaf_id == LEAF_42_HORIZON_ID
    )
    receipt = load_default_calibration_receipt()
    documents = promoted_request_preflight_documents(
        exterior,
        horizon,
        SimpleNamespace(runtime_provenance={}),
        receipt,
    )
    return plan, receipt, documents


def _runtime_receipt(root: Path) -> Path:
    julia = root / "julia"
    worker = root / "m02_worker.jl"
    project = root / "project"
    depot = root / "depot"
    project.mkdir()
    depot.mkdir()
    julia.write_text("julia", encoding="ascii")
    worker.write_text("worker", encoding="ascii")
    (project / "Project.toml").write_text("project", encoding="ascii")
    manifest = project / "Manifest.toml"
    manifest.write_text("manifest", encoding="ascii")
    runtime = root / "runtime"
    runtime.mkdir()
    (runtime / "python-runtime.json").write_bytes(canonical_json_bytes({
            "policy_sha256": "f" * 64,
            "julia_runtime": {
                "requested": True,
                "version": "1.10.11",
                "executable": str(julia),
                "executable_sha256": hashlib.sha256(
                    julia.read_bytes()
                ).hexdigest(),
                "arguments": [],
                "worker": str(worker),
                "worker_sha256": hashlib.sha256(
                    worker.read_bytes()
                ).hexdigest(),
                "depot": str(depot),
                "project": str(project),
                "manifest_sha256": hashlib.sha256(
                    manifest.read_bytes()
                ).hexdigest(),
                "sources": [],
            },
        }))
    return runtime


class _PreflightRunner:
    def __init__(self) -> None:
        self.commands: list[tuple[str, ...]] = []

    def __call__(self, command, **kwargs):
        del kwargs
        self.commands.append(tuple(command))
        if "--validate-request-batch" not in command:
            raise AssertionError("preflight entered the numerical worker mode")
        batch = json.loads(Path(command[-2]).read_text(encoding="utf-8"))
        request_sha256s = [item["request_sha256"] for item in batch["requests"]]
        Path(command[-1]).write_bytes(canonical_json_bytes({
            "schema_version": 1,
            "status": "ok",
            "operation": "promoted-request-preflight",
            "request_count": len(request_sha256s),
            "request_set_sha256": batch["request_set_sha256"],
            "request_sha256s": request_sha256s,
        }))
        return SimpleNamespace(returncode=0, stdout="", stderr="")


class PromotedRequestPreflightTests(unittest.TestCase):
    def test_worker_batch_mode_is_structurally_no_solver(self):
        source = WORKER.read_text(encoding="utf-8")
        start = source.index("function validate_request_batch(")
        end = source.index("function evaluate_request(", start)
        body = source[start:end]

        self.assertIn("flatten_request(document)", body)
        self.assertIn("validate_worker_request_contract(request)", body)
        for forbidden in (
            "evaluate_request(",
            "result_fields(",
            "fixed_root_determinant_sample_fields(",
            "setprecision(",
        ):
            self.assertNotIn(forbidden, body)
        self.assertIn('ARGS[1] == "--validate-request-batch"', source)
        self.assertIn("typeof(safety_factor) === Int", source)

    def test_julia_contract_reads_the_python_generated_fixture(self):
        source = JULIA_SPEC.read_text(encoding="utf-8")

        self.assertIn("JSON.parsefile(ARGS[1])", source)
        self.assertNotIn("function promoted_exterior_document()", source)
        self.assertIn('case["label"]', source)

    def test_matrix_uses_actual_production_requests_and_wire_types(self):
        _, receipt, documents = _preflight_documents()

        self.assertEqual(
            [
                (
                    item["mechanism_id"],
                    item["precision_digits"],
                    item["refinement_level"],
                )
                for item in documents
            ],
            [
                ("exterior-light-ring", 40, 0),
                ("exterior-light-ring", 40, 1),
                ("exterior-light-ring", 80, 0),
                ("exterior-light-ring", 80, 1),
                ("exterior-light-ring", 120, 0),
                ("exterior-light-ring", 120, 1),
                ("horizon-admittance", 80, 0),
                ("horizon-admittance", 80, 1),
                ("horizon-admittance", 120, 0),
                ("horizon-admittance", 120, 1),
            ],
        )
        for document in documents:
            value = document["policy"]["determinant_error_safety_factor"]
            if document["mechanism_id"] == "horizon-admittance":
                self.assertIs(type(value), str)
                self.assertEqual(value, "64")
            else:
                self.assertIs(type(value), int)
                self.assertEqual(value, receipt.certificate_safety_factor)

    def test_contract_fixture_is_canonical_python_json_with_typed_negatives(self):
        _, _, documents = _preflight_documents()
        fixture = build_promoted_request_contract_fixture(documents)
        round_tripped = json.loads(canonical_json_bytes(fixture))

        self.assertEqual(len(round_tripped["requests"]), 10)
        self.assertEqual(
            [case["label"] for case in round_tripped["invalid_exterior_cases"]],
            ["string", "floating-point", "boolean", "wrong-integer", "null"],
        )
        self.assertEqual(
            [
                case["document"]["policy"]["determinant_error_safety_factor"]
                for case in round_tripped["invalid_exterior_cases"]
            ],
            ["64", 64.0, True, 63, None],
        )

    def test_preflight_response_integer_fields_are_type_exact(self):
        request_sha256s = ("a" * 64,)
        response = {
            "schema_version": 1,
            "status": "ok",
            "operation": "promoted-request-preflight",
            "request_count": 1,
            "request_set_sha256": "b" * 64,
            "request_sha256s": list(request_sha256s),
        }
        for field, invalid in (
            ("schema_version", True),
            ("schema_version", 1.0),
            ("request_count", True),
            ("request_count", 1.0),
        ):
            with self.subTest(field=field, invalid=invalid):
                malformed = {**response, field: invalid}
                with self.assertRaisesRegex(
                    JuliaResponseBackendError,
                    "response authentication failed",
                ):
                    _validate_promoted_request_preflight_response(
                        malformed,
                        request_set_sha256="b" * 64,
                        request_sha256s=request_sha256s,
                    )

    def test_success_is_cached_against_every_required_binding(self):
        plan, receipt, documents = _preflight_documents()
        with tempfile.TemporaryDirectory() as temporary:
            runtime = _runtime_receipt(Path(temporary))
            first_runner = _PreflightRunner()
            first = JuliaResponseAdapter.from_runtime_receipt(
                runtime_root=runtime, runner=first_runner
            )
            result = first.preflight_promoted_requests(
                documents,
                calibration_receipt_sha256=receipt.sha256,
                policy_sha256=plan.policy.identity_sha256,
                precision_capabilities_sha256=(
                    plan.precision_capabilities.identity_sha256
                ),
            )
            self.assertFalse(result.reused)
            self.assertEqual(len(first_runner.commands), 1)
            self.assertIn("python_backend_source_sha256", result.binding)
            self.assertIn("julia_worker_sha256", result.binding)
            self.assertEqual(
                result.binding["calibration_receipt_sha256"], receipt.sha256
            )
            self.assertEqual(
                result.binding["policy_sha256"], plan.policy.identity_sha256
            )
            self.assertEqual(
                result.binding["precision_capabilities_sha256"],
                plan.precision_capabilities.identity_sha256,
            )

            second_runner = _PreflightRunner()
            second = JuliaResponseAdapter.from_runtime_receipt(
                runtime_root=runtime, runner=second_runner
            )
            reused = second.preflight_promoted_requests(
                documents,
                calibration_receipt_sha256=receipt.sha256,
                policy_sha256=plan.policy.identity_sha256,
                precision_capabilities_sha256=(
                    plan.precision_capabilities.identity_sha256
                ),
            )
            self.assertTrue(reused.reused)
            self.assertEqual(second_runner.commands, [])

    def test_each_binding_change_reruns_the_preflight(self):
        plan, receipt, documents = _preflight_documents()
        base_arguments = {
            "calibration_receipt_sha256": receipt.sha256,
            "policy_sha256": plan.policy.identity_sha256,
            "precision_capabilities_sha256": (
                plan.precision_capabilities.identity_sha256
            ),
        }
        for changed in (
            "python-source",
            "worker",
            "calibration-receipt",
            "policy",
            "precision-capabilities",
            "request-set",
        ):
            with (
                self.subTest(changed=changed),
                tempfile.TemporaryDirectory() as temporary,
            ):
                runtime = _runtime_receipt(Path(temporary))
                first_runner = _PreflightRunner()
                first = JuliaResponseAdapter.from_runtime_receipt(
                    runtime_root=runtime, runner=first_runner
                )
                first.preflight_promoted_requests(documents, **base_arguments)

                second_runner = _PreflightRunner()
                second = replace(first, runner=second_runner)
                second_arguments = dict(base_arguments)
                second_documents = documents
                source_patch = (
                    patch(
                        "windows_solver.julia_response_backend._sha256",
                        return_value="9" * 64,
                    )
                    if changed == "python-source"
                    else None
                )
                if changed == "worker":
                    second = replace(
                        second,
                        runtime_provenance={
                            **dict(second.runtime_provenance),
                            "worker_sha256": "8" * 64,
                        },
                    )
                elif changed == "calibration-receipt":
                    second_arguments["calibration_receipt_sha256"] = "7" * 64
                elif changed == "policy":
                    second_arguments["policy_sha256"] = "6" * 64
                elif changed == "precision-capabilities":
                    second_arguments["precision_capabilities_sha256"] = (
                        "5" * 64
                    )
                elif changed == "request-set":
                    modified = copy.deepcopy(documents)
                    modified[0]["amplitude"] = {
                        "real": "1e-6",
                        "imaginary": "0",
                    }
                    second_documents = tuple(modified)

                if source_patch is None:
                    result = second.preflight_promoted_requests(
                        second_documents, **second_arguments
                    )
                else:
                    with source_patch:
                        result = second.preflight_promoted_requests(
                            second_documents, **second_arguments
                        )
                self.assertFalse(result.reused)
                self.assertEqual(len(second_runner.commands), 1)

    def test_failed_preflight_is_never_cached_as_a_success(self):
        plan, receipt, documents = _preflight_documents()
        arguments = {
            "calibration_receipt_sha256": receipt.sha256,
            "policy_sha256": plan.policy.identity_sha256,
            "precision_capabilities_sha256": (
                plan.precision_capabilities.identity_sha256
            ),
        }

        def failing(command, **kwargs):
            del kwargs
            Path(command[-1]).write_bytes(canonical_json_bytes({
                "schema_version": 1,
                "status": "error",
                "operation": "promoted-request-preflight",
                "error_type": "ErrorException",
                "message": "determinant_error_safety_factor is invalid",
            }))
            return SimpleNamespace(returncode=21, stdout="", stderr="")

        with tempfile.TemporaryDirectory() as temporary:
            runtime = _runtime_receipt(Path(temporary))
            failed = JuliaResponseAdapter.from_runtime_receipt(
                runtime_root=runtime, runner=failing
            )
            with self.assertRaisesRegex(
                JuliaResponseBackendError,
                "determinant_error_safety_factor is invalid",
            ):
                failed.preflight_promoted_requests(documents, **arguments)

            successful_runner = _PreflightRunner()
            retry = JuliaResponseAdapter.from_runtime_receipt(
                runtime_root=runtime, runner=successful_runner
            )
            result = retry.preflight_promoted_requests(documents, **arguments)

        self.assertFalse(result.reused)
        self.assertEqual(len(successful_runner.commands), 1)

    def test_corrupt_cache_is_revalidated_and_replaced_without_deletion(self):
        plan, receipt, documents = _preflight_documents()
        arguments = {
            "calibration_receipt_sha256": receipt.sha256,
            "policy_sha256": plan.policy.identity_sha256,
            "precision_capabilities_sha256": (
                plan.precision_capabilities.identity_sha256
            ),
        }
        with tempfile.TemporaryDirectory() as temporary:
            runtime = _runtime_receipt(Path(temporary))
            first_runner = _PreflightRunner()
            first = JuliaResponseAdapter.from_runtime_receipt(
                runtime_root=runtime, runner=first_runner
            )
            result = first.preflight_promoted_requests(documents, **arguments)
            assert first.promoted_request_preflight_cache is not None
            entry_path = first.promoted_request_preflight_cache._path(
                result.binding
            )
            entry_path.write_text("not JSON", encoding="ascii")

            retry_runner = _PreflightRunner()
            retry = JuliaResponseAdapter.from_runtime_receipt(
                runtime_root=runtime, runner=retry_runner
            )
            refreshed = retry.preflight_promoted_requests(
                documents, **arguments
            )

            final_runner = _PreflightRunner()
            final = JuliaResponseAdapter.from_runtime_receipt(
                runtime_root=runtime, runner=final_runner
            )
            reused = final.preflight_promoted_requests(documents, **arguments)

        self.assertFalse(refreshed.reused)
        self.assertEqual(len(retry_runner.commands), 1)
        self.assertTrue(reused.reused)
        self.assertEqual(final_runner.commands, [])

    def test_success_is_not_blocked_when_preflight_cache_is_unwritable(self):
        plan, receipt, documents = _preflight_documents()

        class UnwritableStore:
            def lookup(self, binding):
                del binding
                return None

            def publish(self, binding, response):
                del binding, response
                raise OSError("read-only preflight cache")

        runner = _PreflightRunner()
        adapter = JuliaResponseAdapter(
            Path("julia"),
            Path("project"),
            Path("depot"),
            Path("worker"),
            {"worker_sha256": "a" * 64},
            runner,
            promoted_request_preflight_cache=UnwritableStore(),
        )
        result = adapter.preflight_promoted_requests(
            documents,
            calibration_receipt_sha256=receipt.sha256,
            policy_sha256=plan.policy.identity_sha256,
            precision_capabilities_sha256=(
                plan.precision_capabilities.identity_sha256
            ),
        )

        self.assertFalse(result.reused)
        self.assertEqual(len(runner.commands), 1)

    def test_subprocess_launch_failure_is_a_preflight_backend_error(self):
        plan, receipt, documents = _preflight_documents()

        def unavailable(command, **kwargs):
            del command, kwargs
            raise OSError("Julia executable is unavailable")

        adapter = JuliaResponseAdapter(
            Path("julia"),
            Path("project"),
            Path("depot"),
            Path("worker"),
            {"worker_sha256": "a" * 64},
            unavailable,
            promoted_request_preflight_cache=None,
        )
        with self.assertRaisesRegex(
            JuliaResponseBackendError,
            "could not start: Julia executable is unavailable",
        ):
            adapter.preflight_promoted_requests(
                documents,
                calibration_receipt_sha256=receipt.sha256,
                policy_sha256=plan.policy.identity_sha256,
                precision_capabilities_sha256=(
                    plan.precision_capabilities.identity_sha256
                ),
            )

    def test_failed_launch_preflight_precedes_generated_cache_and_numerics(self):
        plan = _plan()
        selection = SimpleNamespace()
        adapter = SimpleNamespace()
        for failure in (
            JuliaResponseBackendError("policy rejected"),
            ValueError("request constructor rejected policy"),
            OSError("preflight request file is unavailable"),
        ):
            with (
                self.subTest(failure=type(failure).__name__),
                patch(
                    "windows_solver.response_batches.JuliaResponseAdapter.from_runtime_receipt",
                    return_value=adapter,
                ),
                patch(
                    "windows_solver.response_batches._preflight_promoted_request_contracts",
                    side_effect=failure,
                ) as preflight,
                patch(
                    "windows_solver.response_batches.ensure_generated_gsn_cache"
                ) as generated,
            ):
                with self.assertRaisesRegex(
                    NativeResourceUnavailableError,
                    "promoted request preflight failed:",
                ):
                    NativeCampaignStageBackend.from_selection(plan, selection)

                preflight.assert_called_once()
                generated.assert_not_called()


if __name__ == "__main__":
    unittest.main()
