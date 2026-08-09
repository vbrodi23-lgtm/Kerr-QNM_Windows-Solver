from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from windows_solver.gsn_cache_producer import (
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


class GsnCacheProducerTests(unittest.TestCase):
    def test_selected_leaf_maps_to_exact_julia_parameter_pair(self) -> None:
        plan = _campaign_plan()
        selection = build_campaign_selection(
            plan, role="primary", leaf_ids=(SELECTED_LEAF_ID,)
        )

        pairs = parameter_pairs_for_selection(plan, selection)

        self.assertEqual(pairs, (GsnParameterPair(19, 20, 2),))
        self.assertEqual(pairs[0].cache_key, "m=2;a=0.95")

    def test_producer_invocation_authenticates_the_generated_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            runtime_root = root / ".runtime"
            script = root / "stage01_generate_gsn_cache.jl"
            script.write_text("# test producer\n", encoding="utf-8")
            source_root = root / "GeneralizedSasakiNakamura.jl"
            potentials = source_root / "src" / "Homogeneous" / "Potentials.jl"
            potentials.parent.mkdir(parents=True)
            kerr = potentials.parent / "Kerr.jl"
            kerr.write_text("# test Kerr\n", encoding="utf-8")
            potentials.write_text("# test potentials\n", encoding="utf-8")
            julia = root / "julia.exe"
            julia.write_bytes(b"test executable")
            pair = GsnParameterPair(19, 20, 2)

            def run(command, **kwargs):
                self.assertEqual(Path(command[0]), julia)
                self.assertIn("--startup-file=no", command)
                pairs_path = Path(command[command.index("--pairs-file") + 1])
                self.assertEqual(pairs_path.read_text(encoding="ascii"), "19,20,2\n")
                output = Path(command[command.index("--output-cache") + 1])
                status = Path(command[command.index("--status-output") + 1])
                source_sha256 = hashlib.sha256(potentials.read_bytes()).hexdigest()
                output.write_text(
                    json.dumps(
                        {
                            "schema_version": 1,
                            "spin_weight": -2,
                            "mass_normalization": 1,
                            "source_relative_path": (
                                "src/Homogeneous/Potentials.jl"
                            ),
                            "source_sha256": source_sha256,
                            "declared_parameter_pairs": [
                                {"spin": 0.95, "azimuthal_index": 2}
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

            with (
                patch(
                    "windows_solver.gsn_cache_producer.PINNED_GSN_KERR_SHA256",
                    hashlib.sha256(kerr.read_bytes()).hexdigest(),
                ),
                patch(
                    "windows_solver.gsn_cache_producer.PINNED_GSN_POTENTIALS_SHA256",
                    hashlib.sha256(potentials.read_bytes()).hexdigest(),
                ),
            ):
                generated = ensure_generated_gsn_cache(
                    (pair,),
                    runtime_root=runtime_root,
                    julia_executable=julia,
                    producer_script=script,
                    gsn_source_root=source_root,
                    runner=run,
                )

            self.assertTrue(generated.path.is_file())
            self.assertEqual(
                generated.sha256,
                hashlib.sha256(generated.path.read_bytes()).hexdigest(),
            )
            self.assertEqual(generated.parameter_pairs, (pair,))

    def test_native_campaign_backend_uses_generated_digest_not_historic_digest(
        self,
    ) -> None:
        plan = _campaign_plan()
        selection = build_campaign_selection(
            plan, role="primary", leaf_ids=(SELECTED_LEAF_ID,)
        )
        generated = SimpleNamespace(
            path=Path("generated-cache.json"),
            sha256="a" * 64,
            parameter_pairs=(GsnParameterPair(19, 20, 2),),
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
                    {
                        "records": {
                            "m=2;a=0.95": _coefficient_record(),
                        }
                    },
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
                self.assertEqual(
                    os.environ["GSN_INFINITY_SERIES_CACHE_SHA256"], digest
                )

            imported.assert_called_once_with("windows_solver._native_sn_standard")
            self.assertEqual(kernel.cache_path, cache.resolve())
            with self.assertRaisesRegex(RuntimeError, "digest mismatch"):
                VettedNativeDeterminantKernel.from_generated_resource(
                    cache, "0" * 64
                )


if __name__ == "__main__":
    unittest.main()
