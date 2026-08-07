from __future__ import annotations

import csv
from fractions import Fraction
import hashlib
import io
import json
import math
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile

from tools import compute_kerr_qnm_lattice as builder
from tests.fixtures import expected_lattice_keys


def _synthetic_archive() -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_STORED) as archive:
        for ell, m, n in builder.MODES:
            spins = list(builder.spins_for_ell(ell))
            if (ell, m, n) in ((2, 1, 2), (3, 2, 2)):
                spins = [
                    chi
                    for chi in spins
                    if chi not in (Fraction(199, 200), Fraction(997, 1000))
                ]
            rows = [
                ", ".join(
                    (
                        f"{float(chi):.12f}",
                        "1.4",
                        "-0.2",
                        "1.0",
                        "0.2",
                        "1",
                        "-1",
                        "0",
                        "0",
                    )
                )
                for chi in spins
            ]
            archive.writestr(
                f"KerrQNMEFs-2/l{ell}/s-2l{ell}m{m}n{n}.dat",
                ("\n".join(rows) + "\n").encode("ascii"),
            )
    return output.getvalue()


def _synthetic_rows() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    by_tower: dict[tuple[int, int, int, int], list[complex]] = {}
    for point in builder.lattice_points():
        chi_float = float(point.chi)
        omega = complex(0.7 + point.n * 0.01, -0.1 - point.n * 0.01)
        tower = by_tower.setdefault(
            (point.ell, point.m, point.chi.numerator, point.chi.denominator),
            [],
        )
        separation = min((abs(omega - other) for other in tower), default=math.inf)
        tower.append(omega)
        rows.append(
            {
                "s": -2,
                "ell": point.ell,
                "m": point.m,
                "n": point.n,
                "branch_id": builder.BRANCH_ID,
                "chi_grid_family": point.grid_family,
                "chi_grid_index": point.grid_index,
                "chi_numerator": point.chi.numerator,
                "chi_denominator": point.chi.denominator,
                "chi_float": repr(chi_float),
                "chi_float_hex": chi_float.hex(),
                "omega_re_M": repr(omega.real),
                "omega_im_M": repr(omega.imag),
                "angular_A_re": "1.0",
                "angular_A_im": "0.2",
                "root_solver_success": "true",
                "optimizer_residual_abs": "1e-12",
                "continued_fraction_error": "1e-12",
                "continued_fraction_terms": 1001,
                "angular_padding": builder.ANGULAR_PADDING,
                "angular_refinement_padding": builder.ANGULAR_REFINEMENT_PADDING,
                "angular_refinement_abs": "1e-12",
                "repeat_polish_delta_abs": "1e-12",
                "branch_seed_delta_abs": "1e-12",
                "branch_seed_optimizer_residual_abs": "1e-12",
                "continuation_step_maximum": repr(
                    builder.QNM_CONTINUATION_STEP_MAXIMUM
                ),
                "nearest_overtone_separation_abs": (
                    "" if math.isinf(separation) else repr(separation)
                ),
                "reference_member": "",
                "reference_row": "",
                "reference_abs_delta_omega_M": "",
                "reference_abs_delta_A": "",
            }
        )
    return rows


class CatalogBuilderTests(unittest.TestCase):
    def test_exact_enumerator_is_the_complete_reduced_rational_lattice(self) -> None:
        points = builder.lattice_points()
        self.assertEqual(len(points), 2_736)
        self.assertEqual({point.key for point in points}, expected_lattice_keys())
        self.assertEqual(
            {ell: sum(point.ell == ell for point in points) for ell in (2, 3, 4)},
            {2: 690, 3: 966, 4: 1_080},
        )
        self.assertEqual(
            {ell: len(builder.spins_for_ell(ell)) for ell in (2, 3, 4)},
            {2: 46, 3: 46, 4: 40},
        )
        self.assertEqual(
            [(point.ell, point.m, point.n, point.chi) for point in points],
            sorted((point.ell, point.m, point.n, point.chi) for point in points),
        )

    def test_compute_lattice_emits_canonical_complete_bytes(self) -> None:
        archive = _synthetic_archive()
        points = builder.lattice_points()
        seeds = tuple(
            builder.BranchSeed(point, 0.7 - 0.1j, 1.0 + 0.2j, 1e-12)
            for point in points
        )
        rows = _synthetic_rows()
        # The synthetic source matches only n=0. Keep all exact comparison
        # deltas inside the gate without allowing source rows to construct the
        # solver output.
        for row in rows:
            row["omega_re_M"] = "0.7"
            row["omega_im_M"] = "-0.1"
        overrides = {
            "ARCHIVE_SIZE_BYTES": len(archive),
            "ARCHIVE_MD5": hashlib.md5(archive).hexdigest(),
            "ARCHIVE_SHA256": hashlib.sha256(archive).hexdigest(),
        }
        with (
            patch.multiple(builder, **overrides),
            patch.object(builder, "_qnm_branch_seeds", return_value=seeds),
            patch.object(builder, "_canonical_rows", return_value=rows),
            patch.object(
                builder,
                "_dependency_versions",
                return_value={
                    "numpy": "test",
                    "scipy": "test",
                    "numba": "test",
                    "qnm": builder.QNM_VERSION,
                },
            ),
            patch.object(builder.platform, "platform", return_value="test-platform"),
            patch.object(builder.platform, "python_version", return_value="3.12.0"),
        ):
            catalog, receipt_bytes = builder.compute_lattice(
                archive, qnm_wheel_bytes=b"synthetic-wheel"
            )

        reader = csv.DictReader(io.StringIO(catalog.decode("utf-8")), strict=True)
        emitted = list(reader)
        receipt = json.loads(receipt_bytes)
        self.assertEqual(tuple(reader.fieldnames or ()), builder.OUTPUT_COLUMNS)
        self.assertEqual(len(emitted), 2_736)
        self.assertEqual(
            {
                (
                    int(row["ell"]),
                    int(row["m"]),
                    int(row["n"]),
                    int(row["chi_numerator"]),
                    int(row["chi_denominator"]),
                )
                for row in emitted
            },
            expected_lattice_keys(),
        )
        self.assertEqual(receipt["catalog"]["sha256"], hashlib.sha256(catalog).hexdigest())
        self.assertEqual(receipt["catalog"]["row_count_excluding_header"], 2_736)
        self.assertEqual(receipt["source_comparison"]["comparison_count"], 392)
        self.assertEqual(
            receipt["source_comparison"]["acceptance_ceilings"],
            {
                "absolute_delta_A": builder.MAXIMUM_REFERENCE_DELTA_A,
                "absolute_delta_omega_M": builder.MAXIMUM_REFERENCE_DELTA_OMEGA_M,
            },
        )
        self.assertEqual(
            receipt["lattice"]["spin_grid_rationals_by_ell"],
            {
                str(ell): [
                    [spin.numerator, spin.denominator]
                    for spin in builder.spins_for_ell(ell)
                ]
                for ell in (2, 3, 4)
            },
        )
        self.assertEqual(
            receipt["lattice"]["mode_rule"],
            {
                "ell": [2, 3, 4],
                "m": "every integer from -ell through +ell",
                "n": [0, 1, 2],
            },
        )
        self.assertEqual(
            receipt["backend"]["branch_tracker"],
            {
                "name": "qnm",
                "version": builder.QNM_VERSION,
                "wheel_sha256": builder.QNM_WHEEL_SHA256,
                "role": "branch-labelled seed generation only",
                "angular_seed_role": (
                    "not used; catalog A is recomputed by the canonical backend "
                    "and compared at the 392 exact Motohashi overlaps"
                ),
                "package_files_authenticated_before_import": True,
                "source_url": builder.QNM_SOURCE_URL,
                "joss_doi": builder.QNM_JOSS_DOI,
                "license": builder.QNM_LICENSE,
                "license_sha256": builder.QNM_LICENSE_SHA256,
            },
        )
        self.assertEqual(
            receipt["backend"]["canonical_backend_license"],
            {
                "license": "MIT",
                "path": (
                    "src/windows_solver/data/"
                    "LICENSE-CANONICAL-BACKEND-MIT.txt"
                ),
                "sha256": builder.CANONICAL_BACKEND_LICENSE_SHA256,
                "scope": "offline canonical numerical backend only",
            },
        )
        self.assertEqual(
            receipt["numerical_policy"]["frequency_units"], "Momega"
        )
        self.assertEqual(
            receipt["backend"]["branch_tracker"]["angular_seed_role"],
            (
                "not used; catalog A is recomputed by the canonical backend "
                "and compared at the 392 exact Motohashi overlaps"
            ),
        )
        self.assertEqual(
            receipt["numerical_policy"]["time_dependence"],
            "exp(-i omega t)",
        )
        self.assertEqual(
            receipt["numerical_policy"]["qnm_fraction_maximum_terms"],
            builder.QNM_MAXIMUM_FRACTION_TERMS,
        )
        self.assertTrue(receipt_bytes.endswith(b"\n"))
        self.assertEqual(
            receipt_bytes,
            json.dumps(
                receipt,
                allow_nan=False,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
            + b"\n",
        )

    def test_archive_hash_mismatch_fails_before_numerical_work(self) -> None:
        archive = _synthetic_archive()
        with patch.object(builder, "ARCHIVE_SIZE_BYTES", len(archive)):
            with self.assertRaisesRegex(ValueError, "MD5"):
                builder.compute_lattice(
                    archive, qnm_wheel_bytes=b"synthetic-wheel"
                )

    def test_qnm_wheel_hash_is_verified_before_branch_tracking(self) -> None:
        with self.assertRaisesRegex(ValueError, "qnm wheel SHA-256"):
            builder._authenticate_qnm_installation(b"not-the-pinned-wheel")

    def test_qnm_package_data_must_match_the_authenticated_wheel(self) -> None:
        real_import = __import__

        def reject_qnm_import(name, globals=None, locals=None, fromlist=(), level=0):
            if name == "qnm" or name.startswith("qnm."):
                raise AssertionError("qnm executed before authentication")
            return real_import(name, globals, locals, fromlist, level)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            package = root / "qnm"
            package.joinpath("schwarzschild", "data").mkdir(parents=True)
            package.joinpath("__init__.py").write_bytes(b"# exact\n")
            package.joinpath("schwarzschild", "data", "Schw_dict.pickle").write_bytes(
                b"tampered-branch-origins"
            )
            wheel_output = io.BytesIO()
            with zipfile.ZipFile(wheel_output, "w") as wheel:
                wheel.writestr("qnm/__init__.py", b"# exact\n")
                wheel.writestr(
                    "qnm/schwarzschild/data/Schw_dict.pickle",
                    b"authenticated-branch-origins",
                )
            wheel_bytes = wheel_output.getvalue()

            class FakeDistribution:
                version = builder.QNM_VERSION

                @staticmethod
                def locate_file(member: str) -> Path:
                    return root / member

            with (
                patch.object(
                    builder, "QNM_WHEEL_SHA256", hashlib.sha256(wheel_bytes).hexdigest()
                ),
                patch.object(
                    builder.metadata,
                    "distribution",
                    return_value=FakeDistribution(),
                ),
                patch("builtins.__import__", side_effect=reject_qnm_import),
                self.assertRaisesRegex(ValueError, "Schw_dict.pickle"),
            ):
                builder._authenticate_qnm_installation(wheel_bytes)

    def test_qnm_shadow_package_is_rejected_before_import(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            package = root / "qnm"
            package.mkdir()
            package.joinpath("__init__.py").write_bytes(b"# authenticated\n")
            wheel_output = io.BytesIO()
            with zipfile.ZipFile(wheel_output, "w") as wheel:
                wheel.writestr("qnm/__init__.py", b"# authenticated\n")
            wheel_bytes = wheel_output.getvalue()

            class FakeDistribution:
                version = builder.QNM_VERSION

                @staticmethod
                def locate_file(member: str) -> Path:
                    return root / member

            shadow = root / "shadow" / "qnm" / "__init__.py"
            with (
                patch.object(
                    builder, "QNM_WHEEL_SHA256", hashlib.sha256(wheel_bytes).hexdigest()
                ),
                patch.object(
                    builder.metadata,
                    "distribution",
                    return_value=FakeDistribution(),
                ),
                patch.object(
                    builder.importlib_util,
                    "find_spec",
                    return_value=SimpleNamespace(
                        origin=str(shadow),
                        submodule_search_locations=[str(shadow.parent)],
                    ),
                ),
                self.assertRaisesRegex(ValueError, "shadow|origin"),
            ):
                builder._authenticate_qnm_installation(wheel_bytes)

    def test_output_pair_rejects_alias_and_rolls_back_partial_replace(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            catalog = Path(directory, "catalog.csv")
            receipt = Path(directory, "receipt.json")
            catalog.write_bytes(b"old-catalog")
            receipt.write_bytes(b"old-receipt")
            with self.assertRaisesRegex(ValueError, "different paths"):
                builder._atomic_write_pair(catalog, catalog, b"new", b"new")

            real_replace = builder.os.replace
            calls = 0

            def fail_second_replace(source, destination):
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise OSError("simulated receipt replacement failure")
                return real_replace(source, destination)

            with (
                patch.object(builder.os, "replace", side_effect=fail_second_replace),
                self.assertRaisesRegex(OSError, "simulated"),
            ):
                builder._atomic_write_pair(
                    catalog,
                    receipt,
                    b"new-catalog",
                    b"new-receipt",
                )

            self.assertEqual(catalog.read_bytes(), b"old-catalog")
            self.assertEqual(receipt.read_bytes(), b"old-receipt")

            real_write_temporary = builder._write_temporary
            temporary_calls = 0

            def fail_second_temporary(path, data):
                nonlocal temporary_calls
                temporary_calls += 1
                if temporary_calls == 2:
                    raise OSError("simulated receipt temporary failure")
                return real_write_temporary(path, data)

            with (
                patch.object(
                    builder,
                    "_write_temporary",
                    side_effect=fail_second_temporary,
                ),
                self.assertRaisesRegex(OSError, "temporary"),
            ):
                builder._atomic_write_pair(
                    catalog,
                    receipt,
                    b"new-catalog",
                    b"new-receipt",
                )

            self.assertEqual(catalog.read_bytes(), b"old-catalog")
            self.assertEqual(receipt.read_bytes(), b"old-receipt")
            self.assertEqual(
                list(Path(directory).glob(".catalog.csv.*")),
                [],
            )

    def test_row_validation_rejects_both_diagnostic_ceilings(self) -> None:
        for field, value in (
            ("optimizer_residual_abs", "1.000001e-8"),
            ("continued_fraction_error", "1.000001e-9"),
        ):
            rows = _synthetic_rows()
            rows[0][field] = value
            with self.subTest(field=field), self.assertRaisesRegex(
                ValueError, f"{field} exceeds its threshold"
            ):
                builder._validate_rows(rows)

    def test_canonical_polish_rejects_raw_solver_failure(self) -> None:
        point = builder.lattice_points()[0]
        seed = builder.BranchSeed(point, 0.7 - 0.1j, 1.0 + 0.2j, 2e-13)
        first = (
            0.7 - 0.1j,
            1.0 + 0.2j,
            3e-13,
            4e-14,
            1200,
            False,
            "flag is diagnostic",
        )
        repeat = (*first[:5], True, "ok")
        with (
            patch.object(
                builder.kerr_cf_solver,
                "solve_mode",
                side_effect=(first, repeat),
            ),
            patch.object(
                builder.kerr_cf_solver,
                "coupled_error",
                return_value=(0j, 1.0 + 0.2j, 4e-14, 1200),
            ),
            self.assertRaisesRegex(ValueError, "root solver"),
        ):
            builder._canonical_rows((seed,))

    def test_canonical_polish_uses_branch_seed_and_records_both_gates(self) -> None:
        point = builder.lattice_points()[0]
        seed = builder.BranchSeed(point, 0.7 - 0.1j, 1.0 + 0.2j, 2e-13)
        first = (
            0.7 - 0.1j,
            1.0 + 0.2j,
            3e-13,
            4e-14,
            1200,
            True,
            "ok",
        )
        repeat = first
        with (
            patch.object(
                builder.kerr_cf_solver,
                "solve_mode",
                side_effect=(first, repeat),
            ) as solve,
            patch.object(
                builder.kerr_cf_solver,
                "coupled_error",
                return_value=(0j, 1.0 + 0.2j, 4e-14, 1200),
            ),
        ):
            row = builder._canonical_rows((seed,))[0]

        self.assertEqual(solve.call_args_list[0].args[5], seed.omega)
        self.assertEqual(row["root_solver_success"], "true")
        self.assertEqual(float(row["optimizer_residual_abs"]), 3e-13)
        self.assertEqual(float(row["continued_fraction_error"]), 4e-14)
        self.assertEqual(float(row["branch_seed_delta_abs"]), 0.0)


if __name__ == "__main__":
    unittest.main()
