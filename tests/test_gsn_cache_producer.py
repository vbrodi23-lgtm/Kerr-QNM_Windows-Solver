from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace
import tempfile
import threading
import unittest
from unittest.mock import patch

from windows_solver.gsn_cache_producer import (
    GSN_CONSUMER_CONTRACT_VERSION,
    GSN_EQUATION_CONVENTION,
    GSN_PRODUCER_CONTRACT_VERSION,
    GSN_RECORD_SCHEMA_VERSION,
    GsnCacheProductionError,
    GsnParameterPair,
    ensure_generated_gsn_cache,
    parameter_pairs_for_selection,
)
from windows_solver.response_batches import (
    NativeCampaignStageBackend,
    PrecisionCapabilities,
    build_campaign_plan,
    build_campaign_selection,
)
from windows_solver.response_engine import NumericalPolicy, VettedNativeDeterminantKernel


SELECTED_LEAF_ID = (
    "b-prime-leaf-9e5777728144433e089f9559b92b6e139e16115a5a53099f40403a45297aa3c3"
)


def _coefficient_record() -> dict[str, object]:
    series = {
        "numerator_coefficients_ascending": ["1"],
        "denominator_coefficients_ascending": ["1"],
    }
    return {"F": dict(series), "U": dict(series)}


def _campaign_plan():
    return build_campaign_plan(
        policy=NumericalPolicy(),
        backend_identity=VettedNativeDeterminantKernel.identity,
        precision_capabilities=PrecisionCapabilities((64,)),
    )


class _ProducerFixture:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.runtime_root = root / ".runtime"
        self.script = root / "generate_gsn_cache.jl"
        self.script.write_text("# test producer\n", encoding="utf-8")
        self.source_root = root / "GeneralizedSasakiNakamura.jl"
        self.potentials = (
            self.source_root / "src" / "Homogeneous" / "Potentials.jl"
        )
        self.potentials.parent.mkdir(parents=True)
        self.kerr = self.potentials.parent / "Kerr.jl"
        self.kerr.write_text("# test Kerr\n", encoding="utf-8")
        self.potentials.write_text("# test potentials\n", encoding="utf-8")
        self.julia = root / "julia.exe"
        self.julia.write_bytes(b"test executable")
        self.invocations: list[GsnParameterPair] = []
        self._guard = threading.Lock()

    def run(self, command, **kwargs):
        self.assert_command(command)
        pairs_path = Path(command[command.index("--pairs-file") + 1])
        fields = pairs_path.read_text(encoding="ascii").strip().split(",")
        pair = GsnParameterPair(int(fields[0]), int(fields[1]), int(fields[2]))
        with self._guard:
            self.invocations.append(pair)
        output = Path(command[command.index("--output-cache") + 1])
        status = Path(command[command.index("--status-output") + 1])
        output.write_text(
            json.dumps(
                {
                    "schema_version": GSN_RECORD_SCHEMA_VERSION,
                    "producer_contract_version": GSN_PRODUCER_CONTRACT_VERSION,
                    "consumer_contract_version": GSN_CONSUMER_CONTRACT_VERSION,
                    "equation_convention": GSN_EQUATION_CONVENTION,
                    "spin_weight": -2,
                    "mass_normalization": 1,
                    "source_relative_path": "src/Homogeneous/Potentials.jl",
                    "source_sha256": hashlib.sha256(
                        self.potentials.read_bytes()
                    ).hexdigest(),
                    "declared_parameter_pairs": [
                        {
                            "spin_numerator": pair.spin_numerator,
                            "spin_denominator": pair.spin_denominator,
                            "spin_binary64_hex": pair.spin_binary64_hex,
                            "azimuthal_index": pair.azimuthal_index,
                        }
                    ],
                    "records": {pair.cache_key: _coefficient_record()},
                },
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        status.write_text(
            (
                "status_code,expected_parameter_pair_count,"
                "computed_parameter_pair_count,accepted_parameter_pair_count,"
                "rejected_parameter_pair_count,expected_validation_sample_count,"
                "computed_validation_sample_count,accepted_validation_sample_count,"
                "rejected_validation_sample_count,source_equations_executed,"
                "exact_symbolic_algebra_used,maximum_scaled_validation_error_finite,"
                "validation_tolerance_satisfied,all_accepted\n"
                "0,1,1,1,0,6,6,6,0,true,true,true,true,true\n"
            ),
            encoding="ascii",
        )
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    def assert_command(self, command) -> None:
        if Path(command[0]) != self.julia or "--startup-file=no" not in command:
            raise AssertionError(f"unexpected producer command: {command!r}")

    def ensure(self, pairs):
        return ensure_generated_gsn_cache(
            pairs,
            runtime_root=self.runtime_root,
            julia_executable=self.julia,
            producer_script=self.script,
            gsn_source_root=self.source_root,
            runner=self.run,
        )


class GsnCacheProducerTests(unittest.TestCase):
    def test_selected_leaf_retains_exact_resolved_spin_and_origin_coordinate(self) -> None:
        plan = _campaign_plan()
        selection = build_campaign_selection(
            plan, role="primary", leaf_ids=(SELECTED_LEAF_ID,)
        )

        pairs = parameter_pairs_for_selection(plan, selection)

        self.assertEqual(pairs, (GsnParameterPair(19, 20, 2),))
        self.assertEqual(pairs[0].cache_key, "m=2;a=0.95")
        self.assertEqual(pairs[0].spin_binary64_hex, float(0.95).hex())
        self.assertEqual(len(pairs[0].origins), 1)
        origin = pairs[0].origins[0].to_mapping()
        self.assertEqual(origin["coordinate_id"], "a_over_M")
        self.assertEqual(origin["coordinate_numerator"], 19)
        self.assertEqual(origin["coordinate_denominator"], 20)
        self.assertEqual(origin["transformation_id"], "identity-a-over-M")

    def test_pair_records_are_reused_for_subsets_independent_of_request_order(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = _ProducerFixture(Path(temporary))
            first = GsnParameterPair(19, 20, 2)
            second = GsnParameterPair(97, 100, 2)

            generated = fixture.ensure((second, first))
            subset = fixture.ensure((first,))
            reordered = fixture.ensure((first, second))

            self.assertEqual(fixture.invocations, [first, second])
            self.assertEqual(
                generated.record_artifact_ids, ("gsn-000001", "gsn-000002")
            )
            self.assertEqual(subset.record_artifact_ids, ("gsn-000001",))
            self.assertEqual(reordered.record_artifact_ids, generated.record_artifact_ids)
            self.assertLess(len(generated.path.name), 64)
            assembled = json.loads(generated.path.read_text(encoding="ascii"))
            self.assertEqual(set(assembled["records"]), {first.cache_key, second.cache_key})
            index_path = fixture.runtime_root / "generated" / "gsn" / "gsn-index.json"
            index = json.loads(index_path.read_text(encoding="ascii"))
            self.assertEqual(len(index["records"]), 2)
            self.assertTrue(
                (index_path.parent / "gsn-index.previous.json").is_file()
            )

    def test_invalid_pair_artifact_regenerates_only_that_pair_under_same_id(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = _ProducerFixture(Path(temporary))
            first = GsnParameterPair(19, 20, 2)
            second = GsnParameterPair(97, 100, 2)
            generated = fixture.ensure((first, second))
            record_directory = generated.path.parent
            (record_directory / "gsn-000002.json").write_text("{}\n", encoding="ascii")

            regenerated = fixture.ensure((second, first))

            self.assertEqual(fixture.invocations, [first, second, second])
            self.assertEqual(
                regenerated.record_artifact_ids, ("gsn-000001", "gsn-000002")
            )

    def test_source_changes_are_observed_but_contract_version_controls_reuse(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = _ProducerFixture(Path(temporary))
            pair = GsnParameterPair(19, 20, 2)
            generated = fixture.ensure((pair,))
            fixture.script.write_text("# evolved producer\n", encoding="utf-8")
            reused = fixture.ensure((pair,))
            self.assertEqual(fixture.invocations, [pair])
            self.assertEqual(reused.record_artifact_ids, generated.record_artifact_ids)

            value = json.loads(
                (generated.path.parent / "gsn-000001.json").read_text(encoding="ascii")
            )
            value["producer_contract_version"] = GSN_PRODUCER_CONTRACT_VERSION - 1
            (generated.path.parent / "gsn-000001.json").write_text(
                json.dumps(value) + "\n", encoding="ascii"
            )
            fixture.ensure((pair,))
            self.assertEqual(fixture.invocations, [pair, pair])

    def test_index_rejects_duplicate_identity_and_inconsistent_binding(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = _ProducerFixture(Path(temporary))
            pair = GsnParameterPair(19, 20, 2)
            fixture.ensure((pair,))
            index_path = fixture.runtime_root / "generated" / "gsn" / "gsn-index.json"
            value = json.loads(index_path.read_text(encoding="ascii"))
            duplicate = dict(value["records"][0])
            duplicate["artifact_id"] = "gsn-000002"
            duplicate["cache_path"] = "gsn-000002.json"
            duplicate["status_path"] = "gsn-000002-status.csv"
            duplicate["journal_path"] = "gsn-000002-journal.jsonl"
            duplicate["receipt_path"] = "gsn-000002-receipt.json"
            duplicate["request_path"] = "gsn-000002-request.csv"
            value["records"].append(duplicate)
            index_path.write_text(json.dumps(value) + "\n", encoding="ascii")

            with self.assertRaisesRegex(GsnCacheProductionError, "duplicated"):
                fixture.ensure((pair,))

            value["records"] = [value["records"][0]]
            value["records"][0]["cache_path"] = "gsn-999999.json"
            index_path.write_text(json.dumps(value) + "\n", encoding="ascii")
            with self.assertRaisesRegex(GsnCacheProductionError, "binding"):
                fixture.ensure((pair,))

    def test_deleted_index_regenerates_without_overwriting_surviving_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = _ProducerFixture(Path(temporary))
            pair = GsnParameterPair(19, 20, 2)
            first = fixture.ensure((pair,))
            index_path = first.path.parent / "gsn-index.json"
            index_path.unlink()

            second = fixture.ensure((pair,))

            self.assertEqual(first.record_artifact_ids, ("gsn-000001",))
            self.assertEqual(second.record_artifact_ids, ("gsn-000002",))
            self.assertEqual(fixture.invocations, [pair, pair])
            self.assertTrue((first.path.parent / "gsn-000001.json").is_file())
            self.assertTrue((first.path.parent / "gsn-000002.json").is_file())

    def test_concurrent_requests_allocate_one_record(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = _ProducerFixture(Path(temporary))
            pair = GsnParameterPair(19, 20, 2)
            barrier = threading.Barrier(2)

            def request():
                barrier.wait(timeout=5)
                return fixture.ensure((pair,)).record_artifact_ids

            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(lambda _: request(), range(2)))

            self.assertEqual(results, [("gsn-000001",), ("gsn-000001",)])
            self.assertEqual(fixture.invocations, [pair])

    def test_native_campaign_backend_uses_assembled_cache_digest(self) -> None:
        plan = _campaign_plan()
        selection = build_campaign_selection(
            plan, role="primary", leaf_ids=(SELECTED_LEAF_ID,)
        )
        generated = SimpleNamespace(
            path=Path("generated-cache.json"),
            sha256="a" * 64,
            parameter_pairs=(GsnParameterPair(19, 20, 2),),
            record_artifact_ids=("gsn-000001",),
        )
        kernel = SimpleNamespace(identity=VettedNativeDeterminantKernel.identity)

        with (
            patch(
                "windows_solver.response_batches.ensure_generated_gsn_cache",
                return_value=generated,
            ) as ensure,
            patch.object(
                VettedNativeDeterminantKernel,
                "from_generated_resource",
                return_value=kernel,
            ) as load,
        ):
            backend = NativeCampaignStageBackend.from_selection(plan, selection)

        ensure.assert_called_once_with((GsnParameterPair(19, 20, 2),))
        load.assert_called_once_with(generated.path, generated.sha256)
        self.assertEqual(backend.precision_capabilities, PrecisionCapabilities((64,)))

    def test_native_consumer_rehashes_the_generated_artifact_before_import(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            cache = Path(temporary) / "generated.json"
            cache.write_text(
                json.dumps(
                    {"records": {"m=2;a=0.95": _coefficient_record()}},
                    sort_keys=True,
                ),
                encoding="utf-8",
            )
            digest = hashlib.sha256(cache.read_bytes()).hexdigest()

            with (
                patch(
                    "windows_solver.native_response_kernel.importlib.import_module",
                    return_value=SimpleNamespace(StandardSN=object),
                ) as imported,
                patch.dict(os.environ, {}, clear=False),
            ):
                kernel = VettedNativeDeterminantKernel.from_generated_resource(
                    cache, digest
                )
                self.assertEqual(os.environ["GSN_INFINITY_SERIES_CACHE_SHA256"], digest)

            imported.assert_called_once_with("windows_solver._native_sn_standard")
            self.assertEqual(kernel.cache_path, cache.resolve())
            with self.assertRaisesRegex(RuntimeError, "digest mismatch"):
                VettedNativeDeterminantKernel.from_generated_resource(cache, "0" * 64)


if __name__ == "__main__":
    unittest.main()
