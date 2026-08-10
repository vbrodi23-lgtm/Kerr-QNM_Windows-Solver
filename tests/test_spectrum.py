from __future__ import annotations

from dataclasses import replace
import csv
from fractions import Fraction
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from windows_solver.artifacts import (
    ArtifactEnvelope,
    ArtifactStore,
    ArtifactVerificationError,
    computation_cache_key,
)
from windows_solver.builtin import ProblemContractProvider, default_registry
from windows_solver.contracts import (
    Capability,
    NumericalState,
    ScientificState,
    StudyRequest,
)
from windows_solver.engine import ExecutionEngine, RunRecord, verify_run_integrity
from windows_solver.providers import ProviderRegistry, ProviderResult
from windows_solver.payload_validation import validate_provider_payload
from windows_solver.spectrum import (
    CATALOG_DATA_SHA256,
    CATALOG_RECEIPT_RESOURCE,
    CATALOG_RESOURCE,
    SpectralCatalogProvider,
    SpectrumCatalog,
    build_spectral_payload,
    load_catalog_receipt,
    load_spectrum_catalog,
    validate_spectral_payload,
)

from tests.fixtures import (
    SUPPORTED_SPECTRUM_STUDY,
    expected_lattice_keys,
)
from windows_solver.linear_response import B_PRIME_RELEASE_DOMAIN


def _csv_rows(data: bytes) -> tuple[tuple[str, ...], list[dict[str, str]]]:
    reader = csv.DictReader(io.StringIO(data.decode("utf-8")), strict=True)
    return tuple(reader.fieldnames or ()), list(reader)


def _csv_bytes(fieldnames: tuple[str, ...], rows: list[dict[str, str]]) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=fieldnames, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue().encode("utf-8")


def _mutated_catalog_bytes(mutator) -> bytes:
    fieldnames, rows = _csv_rows(CATALOG_RESOURCE.read_bytes())
    mutator(rows)
    return _csv_bytes(fieldnames, rows)


class ExactLatticeContractTests(unittest.TestCase):
    def test_expected_lattice_keys_are_complete_and_l_dependent(self) -> None:
        keys = expected_lattice_keys()
        high = {
            Fraction(97, 100),
            Fraction(49, 50),
            Fraction(99, 100),
            Fraction(199, 200),
            Fraction(997, 1000),
            Fraction(999, 1000),
        }

        self.assertEqual(len(keys), 2_736)
        self.assertEqual(
            {ell: sum(key[0] == ell for key in keys) for ell in (2, 3, 4)},
            {2: 690, 3: 966, 4: 1_080},
        )
        for ell, expected_spin_count in ((2, 46), (3, 46), (4, 40)):
            with self.subTest(ell=ell):
                spins_by_mode = {
                    (m, n): {
                        Fraction(numerator, denominator)
                        for key_ell, key_m, key_n, numerator, denominator in keys
                        if key_ell == ell and key_m == m and key_n == n
                    }
                    for m in range(-ell, ell + 1)
                    for n in range(3)
                }
                self.assertEqual(
                    {len(spins) for spins in spins_by_mode.values()},
                    {expected_spin_count},
                )

        for ell in (2, 3):
            for m in range(-ell, ell + 1):
                for n in range(3):
                    spins = {
                        Fraction(numerator, denominator)
                        for key_ell, key_m, key_n, numerator, denominator in keys
                        if (key_ell, key_m, key_n) == (ell, m, n)
                    }
                    self.assertEqual(sum(spin == Fraction(19, 20) for spin in spins), 1)

        ell4_spins = {
            Fraction(numerator, denominator)
            for ell, _, _, numerator, denominator in keys
            if ell == 4
        }
        self.assertEqual(ell4_spins, {Fraction(i, 52) for i in range(40)})
        self.assertTrue(high.isdisjoint(ell4_spins))


class FullLatticeCatalogContractTests(unittest.TestCase):
    def test_catalog_preserves_the_immutable_base_while_b_prime_records_overlay_gap(self) -> None:
        catalog = load_spectrum_catalog()

        self.assertEqual(len(catalog.roots), 2_736)
        self.assertEqual({root.s for root in catalog.roots}, {-2})
        self.assertEqual(
            {
                (root.s, root.ell, root.m, root.n, root.branch_id)
                for root in catalog.roots
            },
            {
                (-2, ell, m, n, "schwarzschild-overtone-continuation")
                for ell in (2, 3, 4)
                for m in range(-ell, ell + 1)
                for n in range(3)
            },
        )
        self.assertEqual(len(catalog.overlay.roots), 44)
        self.assertEqual(len(B_PRIME_RELEASE_DOMAIN.root_selectors), 48)
        self.assertEqual(len(B_PRIME_RELEASE_DOMAIN.missing_root_selector_ids), 25)

    def test_catalog_exactly_matches_the_2736_root_rational_lattice(self) -> None:
        catalog = load_spectrum_catalog()
        expected_keys = frozenset(expected_lattice_keys())

        self.assertEqual(len(catalog.roots), 2_736)
        self.assertEqual(catalog.keys, expected_keys)
        self.assertEqual(
            {ell: sum(root.ell == ell for root in catalog.roots) for ell in (2, 3, 4)},
            {2: 690, 3: 966, 4: 1_080},
        )
        self.assertTrue(
            all(
                isinstance(key[3], int)
                and isinstance(key[4], int)
                and Fraction(key[3], key[4]).denominator == key[4]
                for key in catalog.keys
            )
        )

    def test_full_lattice_rows_reject_tampering_before_receipt_binding(self) -> None:
        catalog = load_spectrum_catalog()
        self.assertEqual(len(catalog.roots), 2_736)
        baseline_receipt = json.loads(
            CATALOG_RECEIPT_RESOURCE.read_text(encoding="utf-8")
        )

        def remove_row(rows: list[dict[str, str]]) -> None:
            rows.pop()

        def duplicate_row(rows: list[dict[str, str]]) -> None:
            rows[-1] = dict(rows[0])

        def append_row(rows: list[dict[str, str]]) -> None:
            rows.append(dict(rows[0]))

        def cross_ell_row(rows: list[dict[str, str]]) -> None:
            row = next(
                row
                for row in rows
                if row["ell"] == "2"
                and row["chi_numerator"] == "97"
                and row["chi_denominator"] == "100"
            )
            row["ell"] = "4"

        def unreduced_rational_row(rows: list[dict[str, str]]) -> None:
            row = next(
                row
                for row in rows
                if row["chi_numerator"] == "19"
                and row["chi_denominator"] == "780"
            )
            row["chi_numerator"] = "38"
            row["chi_denominator"] = "1560"

        def nonfinite_row(rows: list[dict[str, str]]) -> None:
            rows[0]["omega_re_M"] = "nan"

        def nondamped_row(rows: list[dict[str, str]]) -> None:
            rows[0]["omega_im_M"] = "0"

        def over_threshold_diagnostic(rows: list[dict[str, str]]) -> None:
            rows[0]["optimizer_residual_abs"] = "1.0000001e-8"

        def over_threshold_continued_fraction_error(
            rows: list[dict[str, str]],
        ) -> None:
            rows[0]["continued_fraction_error"] = "1.0000001e-9"

        def false_solver_flag(rows: list[dict[str, str]]) -> None:
            rows[0]["root_solver_success"] = "false"

        def wrong_branch(rows: list[dict[str, str]]) -> None:
            rows[0]["branch_id"] = "different-branch"

        def wrong_grid_identity(rows: list[dict[str, str]]) -> None:
            rows[0]["chi_grid_index"] = "1"

        def over_threshold_angular(rows: list[dict[str, str]]) -> None:
            rows[0]["angular_refinement_abs"] = "1.0000001e-9"

        def over_threshold_repeat(rows: list[dict[str, str]]) -> None:
            rows[0]["repeat_polish_delta_abs"] = "1.0000001e-9"

        def over_threshold_seed(rows: list[dict[str, str]]) -> None:
            rows[0]["branch_seed_delta_abs"] = "5.0000001e-9"

        def exhausted_fraction(rows: list[dict[str, str]]) -> None:
            rows[0]["continued_fraction_terms"] = "60000"

        def wrong_order(rows: list[dict[str, str]]) -> None:
            rows[0], rows[1] = rows[1], rows[0]

        cases = (
            (remove_row, "count|missing|key"),
            (duplicate_row, "duplicate|key"),
            (append_row, "count|extra|duplicate|key"),
            (cross_ell_row, "key|lattice|spin"),
            (unreduced_rational_row, "reduced|rational|canonical"),
            (nonfinite_row, "finite"),
            (nondamped_row, "damped"),
            (over_threshold_diagnostic, "diagnostic|residual|threshold"),
            (
                over_threshold_continued_fraction_error,
                "diagnostic|continued.?fraction|threshold",
            ),
            (false_solver_flag, "solver"),
            (wrong_branch, "mode|branch"),
            (wrong_grid_identity, "lattice|spin|grid"),
            (over_threshold_angular, "diagnostic|angular|threshold"),
            (over_threshold_repeat, "diagnostic|repeat|threshold"),
            (over_threshold_seed, "diagnostic|seed|threshold"),
            (exhausted_fraction, "policy|fraction|depth"),
            (wrong_order, "order"),
        )
        for mutator, message in cases:
            with self.subTest(mutator=mutator.__name__):
                data = _mutated_catalog_bytes(mutator)
                expected_sha256 = hashlib.sha256(data).hexdigest()
                receipt = json.loads(json.dumps(baseline_receipt))
                receipt["catalog"]["sha256"] = expected_sha256
                with patch(
                    "windows_solver.spectrum.load_catalog_receipt",
                    return_value=receipt,
                ), self.assertRaisesRegex(ValueError, message):
                    SpectrumCatalog.from_csv_bytes(
                        data,
                        expected_sha256=expected_sha256,
                    )

    def test_full_lattice_rejects_a_stale_receipt_binding(self) -> None:
        catalog = load_spectrum_catalog()
        self.assertEqual(len(catalog.roots), 2_736)

        with patch(
            "windows_solver.spectrum.load_catalog_receipt",
            return_value={"catalog": {"sha256": "0" * 64}},
        ), self.assertRaisesRegex(ValueError, "receipt"):
            SpectrumCatalog.from_csv_bytes(
                CATALOG_RESOURCE.read_bytes(),
                expected_sha256=CATALOG_DATA_SHA256,
            )

    def test_catalog_keys_and_scope_have_no_polarization_or_eft_axis(self) -> None:
        catalog = load_spectrum_catalog()
        self.assertEqual(len(catalog.roots), 2_736)
        self.assertEqual(catalog.keys, frozenset(expected_lattice_keys()))

        fieldnames, _ = _csv_rows(CATALOG_RESOURCE.read_bytes())
        self.assertNotIn("polarization", fieldnames)
        self.assertNotIn("sector", fieldnames)

        scope = catalog.scope.to_mapping()
        self.assertEqual(
            scope["computed_lattice"],
            {
                "mode_count": 63,
                "root_count": 2_736,
                "roots_by_ell": {"2": 690, "3": 966, "4": 1_080},
                "spin_points_by_ell": {"2": 46, "3": 46, "4": 40},
            },
        )
        serialized_scope = repr(scope).casefold()
        self.assertNotIn("polarization", serialized_scope)
        self.assertNotIn("sector", serialized_scope)


class SpectrumCatalogTests(unittest.TestCase):
    def test_payload_declares_and_enforces_full_grid_row_diagnostic_ceilings(self) -> None:
        catalog = load_spectrum_catalog()
        self.assertEqual(len(catalog.roots), 2_736)
        request = StudyRequest.from_mapping(SUPPORTED_SPECTRUM_STUDY)
        diagnostics = build_spectral_payload(request)["validation"][
            "full_grid_diagnostics"
        ]

        for field in ("optimizer_residual_abs", "continued_fraction_error"):
            with self.subTest(field=field):
                self.assertLessEqual(
                    diagnostics[f"observed_maximum_{field}"],
                    diagnostics[f"maximum_{field}"],
                )
        self.assertFalse(diagnostics["formal_root_enclosure"])

    def test_catalog_hash_rejects_modified_bytes(self) -> None:
        raw = _mutated_catalog_bytes(
            lambda rows: rows[0].__setitem__("omega_re_M", "0")
        )

        with self.assertRaisesRegex(ValueError, "catalog SHA-256 does not match"):
            SpectrumCatalog.from_csv_bytes(
                raw,
                expected_sha256=CATALOG_DATA_SHA256,
            )

    def test_exact_selection_rejects_unsupported_pair_without_partial_result(self) -> None:
        catalog = load_spectrum_catalog()
        supported = StudyRequest.from_mapping(SUPPORTED_SPECTRUM_STUDY)

        selected = catalog.select(supported)

        self.assertEqual(len(selected), 2)
        self.assertEqual([root.spin for root in selected], [0.95, 0.997])
        for unsupported_spin in (0.9500000000004, 0.9997917317482359):
            unsupported = StudyRequest.from_mapping(
                dict(SUPPORTED_SPECTRUM_STUDY, spins=[unsupported_spin])
            )
            with self.subTest(spin=unsupported_spin), self.assertRaisesRegex(
                ValueError, "catalog has no exact root"
            ):
                catalog.select(unsupported)

        signed_zero = StudyRequest.from_mapping(
            dict(SUPPORTED_SPECTRUM_STUDY, spins=[-0.0])
        )
        with self.assertRaisesRegex(ValueError, "catalog has no exact root"):
            catalog.select(signed_zero)

        exact_near_extremal = StudyRequest.from_mapping(
            dict(SUPPORTED_SPECTRUM_STUDY, spins=[0.999])
        )
        selected_near_extremal = catalog.select(exact_near_extremal)
        self.assertEqual(
            [root.spin for root in selected_near_extremal],
            list(exact_near_extremal.spins),
        )

    def test_duplicate_mode_or_spin_selection_is_rejected(self) -> None:
        catalog = load_spectrum_catalog()
        duplicate_mode = StudyRequest.from_mapping(
            dict(
                SUPPORTED_SPECTRUM_STUDY,
                modes=SUPPORTED_SPECTRUM_STUDY["modes"] * 2,
                spins=[0.95],
            )
        )
        duplicate_spin = StudyRequest.from_mapping(
            dict(SUPPORTED_SPECTRUM_STUDY, spins=[0.95, 0.95])
        )

        for request in (duplicate_mode, duplicate_spin):
            with self.assertRaisesRegex(ValueError, "duplicate mode-spin pair"):
                catalog.select(request)

    def test_selection_rejects_incompatible_identity_and_policy(self) -> None:
        catalog = load_spectrum_catalog()
        supported = StudyRequest.from_mapping(SUPPORTED_SPECTRUM_STUDY)

        for request, message in (
            (
                replace(supported, theory_id="not-general-relativity"),
                "theory_id",
            ),
            (
                replace(supported, convention_id="different-convention"),
                "convention_id",
            ),
            (
                StudyRequest.from_mapping(
                    dict(
                        SUPPORTED_SPECTRUM_STUDY,
                        numerical_policy={"precision_bits": 128},
                    )
                ),
                "numerical policy overrides",
            ),
        ):
            with self.subTest(message=message), self.assertRaisesRegex(
                ValueError, message
            ):
                catalog.select(request)


class SpectralProviderTests(unittest.TestCase):
    def test_payload_validation_rejects_json_type_aliases(self) -> None:
        request = StudyRequest.from_mapping(SUPPORTED_SPECTRUM_STUDY)
        payload = build_spectral_payload(request)
        payload["schema_version"] = True

        with self.assertRaisesRegex(ValueError, "spectral artifact payload"):
            validate_spectral_payload(
                request,
                SpectralCatalogProvider.descriptor.to_mapping(),
                payload,
            )

    def test_unknown_spectral_provider_contract_fails_closed(self) -> None:
        request = StudyRequest.from_mapping(SUPPORTED_SPECTRUM_STUDY)
        provider = SpectralCatalogProvider.descriptor.to_mapping()
        provider["provider_id"] = "unknown-spectral-provider"
        provider["output_artifact_type"] = "unknown-spectrum"

        with self.assertRaisesRegex(
            ArtifactVerificationError, "unsupported spectral provider"
        ):
            validate_provider_payload(
                Capability.SPECTRAL_CORE,
                "unknown-spectrum",
                provider,
                request,
                build_spectral_payload(request),
            )

    def test_spectral_runtime_fingerprint_is_authenticated(self) -> None:
        request = StudyRequest.from_mapping(SUPPORTED_SPECTRUM_STUDY)
        provider = SpectralCatalogProvider.descriptor.to_mapping()
        provider["runtime_fingerprint"] = "forged-runtime"

        with self.assertRaisesRegex(ValueError, "provider contract"):
            validate_spectral_payload(
                request,
                provider,
                build_spectral_payload(request),
            )

    def test_default_provider_materializes_verified_spectral_artifact(self) -> None:
        import tempfile

        catalog = load_spectrum_catalog()
        self.assertEqual(len(catalog.roots), 2_736)

        with tempfile.TemporaryDirectory() as directory:
            store = ArtifactStore(Path(directory))
            request = StudyRequest.from_mapping(SUPPORTED_SPECTRUM_STUDY)

            record = ExecutionEngine(store, default_registry()).run(request)
            artifacts = verify_run_integrity(store, record)
            spectrum = artifacts["spectral-core"]

        self.assertEqual(record.status, "SUCCEEDED")
        self.assertEqual(record.provider_execution_count, 2)
        self.assertEqual(record.cache_hit_count, 0)
        self.assertEqual(spectrum.artifact_type, "kerr-qnm-spectrum")
        self.assertEqual(spectrum.payload["requested_root_count"], 2)
        self.assertEqual(len(spectrum.payload["roots"]), 2)
        self.assertEqual(
            [root["spin"] for root in spectrum.payload["roots"]],
            list(request.spins),
        )
        self.assertEqual(
            spectrum.payload["provenance"]["catalog"]["sha256"],
            CATALOG_DATA_SHA256,
        )
        self.assertEqual(
            spectrum.payload["scope"]["computed_lattice"],
            {
                "mode_count": 63,
                "root_count": 2_736,
                "roots_by_ell": {"2": 690, "3": 966, "4": 1_080},
                "spin_points_by_ell": {"2": 46, "3": 46, "4": 40},
            },
        )
        self.assertIs(spectrum.evidence.numerical, NumericalState.ACCEPTED)
        self.assertIs(
            spectrum.evidence.scientific,
            ScientificState.NOT_EVALUATED,
        )

    def test_identical_warm_spectrum_run_executes_no_provider_work(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as directory:
            store = ArtifactStore(Path(directory))
            request = StudyRequest.from_mapping(SUPPORTED_SPECTRUM_STUDY)
            first = ExecutionEngine(store, default_registry()).run(request)

            second = ExecutionEngine(store, default_registry()).run(request)

        self.assertEqual(first.artifact_ids, second.artifact_ids)
        self.assertEqual(second.provider_execution_count, 0)
        self.assertEqual(second.cache_hit_count, 2)

    def test_unsupported_spectrum_request_records_structured_provider_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = ArtifactStore(Path(directory))
            request = StudyRequest.from_mapping(
                dict(SUPPORTED_SPECTRUM_STUDY, spins=[0.7])
            )

            record = ExecutionEngine(store, default_registry()).run(request)

        self.assertEqual(record.status, "FAILED")
        self.assertEqual(record.failed_capability, "spectral-core")
        self.assertEqual(record.provider_execution_count, 1)
        self.assertEqual(set(record.artifact_ids), {"problem-contract"})
        self.assertIn("catalog has no exact root", record.error)

    def test_provider_output_is_validated_before_it_can_be_persisted(self) -> None:
        class ForgingSpectralProvider(SpectralCatalogProvider):
            def execute(self, request, upstream):
                valid = super().execute(request, upstream)
                forged = dict(valid.payload)
                forged["requested_root_count"] = 2_737
                forged["roots"] = []
                return ProviderResult(payload=forged, evidence=valid.evidence)

        with tempfile.TemporaryDirectory() as directory:
            store = ArtifactStore(Path(directory))
            request = StudyRequest.from_mapping(SUPPORTED_SPECTRUM_STUDY)
            registry = ProviderRegistry(
                (ProblemContractProvider(), ForgingSpectralProvider())
            )

            record = ExecutionEngine(store, registry).run(request)

        self.assertEqual(record.status, "FAILED")
        self.assertEqual(record.failed_capability, "spectral-core")
        self.assertEqual(set(record.artifact_ids), {"problem-contract"})
        self.assertIn("spectral artifact payload", record.error)

    def test_forged_cached_spectrum_fails_warm_run_and_run_verification(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = ArtifactStore(Path(directory))
            request = StudyRequest.from_mapping(SUPPORTED_SPECTRUM_STUDY)
            first = ExecutionEngine(store, default_registry()).run(request)
            problem_id = first.artifact_ids["problem-contract"]
            legitimate = store.load_artifact(first.artifact_ids["spectral-core"])
            provider_mapping = SpectralCatalogProvider.descriptor.to_mapping()
            scoped_request = request.for_capability(
                Capability.SPECTRAL_CORE
            ).to_mapping()
            forged_payload = dict(legitimate.payload)
            forged_payload["catalog_id"] = "forged"
            forged_payload["requested_root_count"] = 2_737
            forged_payload["roots"] = []
            forged = ArtifactEnvelope(
                schema_version=1,
                artifact_type="kerr-qnm-spectrum",
                capability=Capability.SPECTRAL_CORE,
                provider=provider_mapping,
                request=scoped_request,
                upstream_artifact_ids=(problem_id,),
                payload=forged_payload,
                evidence=legitimate.evidence,
            )
            forged_id = store.put_artifact(forged)
            cache_key = computation_cache_key(
                Capability.SPECTRAL_CORE,
                provider_mapping,
                scoped_request,
                (problem_id,),
            )
            store.bind_cache(cache_key, forged_id)
            forged_record = RunRecord(
                schema_version=1,
                run_id="a" * 32,
                target="spectral-core",
                request=request.to_mapping(),
                status="SUCCEEDED",
                plan=("problem-contract", "spectral-core"),
                artifact_ids={
                    "problem-contract": problem_id,
                    "spectral-core": forged_id,
                },
                provider_execution_count=0,
                cache_hit_count=2,
                evidence=legitimate.evidence,
            )

            warm = ExecutionEngine(store, default_registry()).run(request)
            with self.assertRaisesRegex(
                ArtifactVerificationError, "spectral artifact payload"
            ):
                verify_run_integrity(store, forged_record)

        self.assertEqual(warm.status, "FAILED")
        self.assertEqual(warm.failed_capability, "spectral-core")
        self.assertIn("spectral artifact payload", warm.error)

    def test_resealed_request_type_alias_fails_run_verification(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = ArtifactStore(Path(directory))
            request = StudyRequest.from_mapping(SUPPORTED_SPECTRUM_STUDY)
            record = ExecutionEngine(store, default_registry()).run(request)
            legitimate = store.load_artifact(record.artifact_ids["spectral-core"])
            forged_request = dict(legitimate.request)
            forged_request["schema_version"] = True
            forged = ArtifactEnvelope(
                schema_version=legitimate.schema_version,
                artifact_type=legitimate.artifact_type,
                capability=legitimate.capability,
                provider=legitimate.provider,
                request=forged_request,
                upstream_artifact_ids=legitimate.upstream_artifact_ids,
                payload=legitimate.payload,
                evidence=legitimate.evidence,
            )
            forged_id = store.put_artifact(forged)
            forged_record = replace(
                record,
                artifact_ids={
                    **dict(record.artifact_ids),
                    "spectral-core": forged_id,
                },
            )

            with self.assertRaisesRegex(
                ArtifactVerificationError, "request scope mismatch"
            ):
                verify_run_integrity(store, forged_record)


if __name__ == "__main__":
    unittest.main()
