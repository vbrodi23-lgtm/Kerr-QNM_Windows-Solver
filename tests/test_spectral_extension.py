from __future__ import annotations

import csv
from contextlib import redirect_stderr
from dataclasses import replace
from fractions import Fraction
import hashlib
import importlib
import importlib.util
import io
import json
import math
from pathlib import Path
import shutil
import tempfile
import threading
import unittest
from unittest.mock import patch

from windows_solver.contracts import Capability, StudyRequest
from windows_solver.linear_response import (
    B_PRIME_RELEASE_DOMAIN,
    B_PRIME_UNRESOLVED_IS_PRODUCED,
    spin_from_dimensionless_surface_gravity,
)


try:
    from tools import compute_kerr_qnm_overlay as overlay_builder
    from tools import kerr_cf_solver
except ImportError:
    overlay_builder = None
    kerr_cf_solver = None


BASE_CSV = Path(__file__).resolve().parents[1] / (
    "src/windows_solver/data/kerr_qnm_roots_2736.csv"
)
BASE_RECEIPT = BASE_CSV.with_name("kerr_qnm_lattice_receipt.json")
BASE_CSV_SHA256 = (
    "9ebae4271309cd45a1b26c90d31155602ed8ef33bb79069adb5897e8afe7a564"
)
BASE_RECEIPT_SHA256 = (
    "61a428a858de1eb7e42fe4cbbda37bf1fddcc808d98be2a62fd33ef4b5b74379"
)


def _builder():
    if overlay_builder is None:
        raise AssertionError("TASK-070 overlay builder is absent")
    return overlay_builder


def _literal_target_identities() -> frozenset[tuple[object, ...]]:
    direct_high = (Fraction(1999, 2000), Fraction(9999, 10000))
    direct_all = (
        Fraction(19, 20), Fraction(97, 100), Fraction(49, 50),
        Fraction(99, 100), Fraction(199, 200), Fraction(997, 1000),
        Fraction(999, 1000), *direct_high,
    )
    identities: set[tuple[object, ...]] = set()
    for ell, m, overtones, spins in (
        (2, 2, (0, 1, 2), direct_high),
        (3, 3, (0, 1), direct_high),
        (4, 4, (0, 1), direct_all),
    ):
        for n in overtones:
            for spin in spins:
                value = float(spin)
                identities.add(
                    (ell, m, n, "a-over-M", spin.numerator, spin.denominator,
                     value.as_integer_ratio(), value.hex())
                )
    for ell, m, n in ((2, 2, 0), (2, 2, 1), (2, 2, 2), (2, 1, 0)):
        for coordinate in (
            Fraction(1, 100), Fraction(1, 200),
            Fraction(1, 500), Fraction(1, 1000),
        ):
            value = spin_from_dimensionless_surface_gravity(float(coordinate))
            identities.add(
                (ell, m, n, "M-kappa", coordinate.numerator,
                 coordinate.denominator, value.as_integer_ratio(), value.hex())
            )
    return frozenset(identities)


class _DeterministicBackend:
    identity = {"backend_id": "deterministic-test-double", "version": 1}

    def __init__(self) -> None:
        self.calls = 0
        self._lock = threading.Lock()

    def solve_cohort(self, targets, base_roots, policy):
        del base_roots, policy
        with self._lock:
            self.calls += len(targets)
        builder = _builder()
        return tuple(
            builder.OverlayResult(
                target=target,
                omega=complex(
                    0.4 + 0.01 * target.ell + 0.001 * target.n
                    + 1e-6 * target.spin,
                    -0.05 - 0.01 * target.n,
                ),
                angular_a=complex(target.ell * (target.ell + 1) - 2, 0.01),
                optimizer_residual_abs=1e-12,
                continued_fraction_error=1e-13,
                continued_fraction_terms=1000,
                angular_refinement_abs=1e-12,
                repeat_polish_delta_abs=1e-12,
                predictor_correction_abs=0.01,
                predictor_correction_over_separation=0.1,
                assigned_separation_abs=0.1,
                assignment_relative_gap=0.5,
                canonical_polish_delta_abs=1e-12,
                independent_path_delta_abs=2e-12,
                reverse_delta_abs=3e-12,
                angular_overlap_min=0.999,
                schedule_a_steps=2,
                schedule_b_steps=3,
                minimum_adaptive_step=0.01,
            )
            for target in targets
        )


def _request_for_selector(selector) -> StudyRequest:
    ell, m, n = selector.mode
    return StudyRequest.from_mapping(
        {
            "schema_version": 1,
            "target": "spectral-core",
            "theory_id": "general-relativity",
            "convention_id": "kerr-mass-normalized-outgoing",
            "modes": [{
                "s": -2, "ell": ell, "m": m, "n": n,
                "branch": "schwarzschild-overtone-continuation",
                "polarization": "gravitational",
            }],
            "spins": [selector.spin],
            "evidence_profile": "research",
            "numerical_policy": {},
        }
    )


OverlaySmokeRowId = tuple[int, int, int, str, int, int, str]
OVERLAY_SMOKE_HEAD_ID: OverlaySmokeRowId = (
    2, 1, 0, "M-kappa", 1, 100, "0x1.ffe4b3ad56fa5p-1"
)
OVERLAY_SMOKE_TAIL_ID: OverlaySmokeRowId = (
    4, 4, 1, "a-over-M", 9999, 10000, "0x1.fff2e48e8a71ep-1"
)
OVERLAY_SMOKE_ORDERING_MIDDLE_ID: OverlaySmokeRowId = (
    4, 4, 1, "a-over-M", 999, 1000, "0x1.ff7ced916872bp-1"
)
OVERLAY_SMOKE_MAXIMUM_RESIDUAL_ID: OverlaySmokeRowId = (
    2, 1, 0, "M-kappa", 1, 1000, "0x1.ffffbc9f2ff3bp-1"
)
OVERLAY_SMOKE_MINIMUM_SEPARATION_AND_GAP_ID: OverlaySmokeRowId = (
    2, 2, 0, "M-kappa", 1, 1000, "0x1.ffffbc9f2ff3bp-1"
)
OVERLAY_SMOKE_MAXIMUM_CORRECTION_AND_MINIMUM_OVERLAP_ID: OverlaySmokeRowId = (
    4, 4, 1, "a-over-M", 9999, 10000, "0x1.fff2e48e8a71ep-1"
)
OVERLAY_SMOKE_ROW_IDS: tuple[OverlaySmokeRowId, ...] = (
    OVERLAY_SMOKE_HEAD_ID,
    OVERLAY_SMOKE_TAIL_ID,
    OVERLAY_SMOKE_ORDERING_MIDDLE_ID,
    OVERLAY_SMOKE_MAXIMUM_RESIDUAL_ID,
    OVERLAY_SMOKE_MINIMUM_SEPARATION_AND_GAP_ID,
    (2, 2, 1, "M-kappa", 1, 1000, "0x1.ffffbc9f2ff3bp-1"),
    (2, 2, 2, "M-kappa", 1, 1000, "0x1.ffffbc9f2ff3bp-1"),
    (4, 4, 0, "a-over-M", 9999, 10000, "0x1.fff2e48e8a71ep-1"),
)


def _overlay_row_id(root) -> OverlaySmokeRowId:
    return (
        root.ell,
        root.m,
        root.n,
        root.source_coordinate_id,
        root.source_coordinate.numerator,
        root.source_coordinate.denominator,
        root.spin_hex,
    )


def _overlay_smoke_rows(roots):
    by_id = {_overlay_row_id(root): root for root in roots}
    missing = set(OVERLAY_SMOKE_ROW_IDS) - set(by_id)
    if missing:
        raise AssertionError(f"overlay smoke rows are absent: {sorted(missing)!r}")
    return tuple(by_id[row_id] for row_id in OVERLAY_SMOKE_ROW_IDS)


def _request_for_overlay_root(root) -> StudyRequest:
    return StudyRequest.from_mapping(
        {
            "schema_version": 1,
            "target": "spectral-core",
            "theory_id": "general-relativity",
            "convention_id": "kerr-mass-normalized-outgoing",
            "modes": [
                {
                    "s": -2,
                    "ell": root.ell,
                    "m": root.m,
                    "n": root.n,
                    "branch": "schwarzschild-overtone-continuation",
                    "polarization": "gravitational",
                }
            ],
            "spins": [root.spin],
            "evidence_profile": "research",
            "numerical_policy": {},
        }
    )

class FrozenM02BPrimeDomainTests(unittest.TestCase):
    def test_b_prime_release_domain_is_the_literal_212_leaf_contract(self) -> None:
        domain = B_PRIME_RELEASE_DOMAIN

        self.assertEqual(domain.leaf_counts_by_role, {"primary": 140, "control": 24, "deep": 48})
        self.assertEqual(len(domain.production_leaf_ids), 212)
        self.assertEqual(len(set(domain.production_leaf_ids)), 212)
        self.assertEqual(domain.selector_counts_by_role, {"primary": 28, "control": 8, "deep": 12})
        self.assertEqual(len(domain.root_selectors), 48)
        self.assertEqual(domain.missing_selector_counts_by_role, {"primary": 13, "control": 0, "deep": 12})
        self.assertEqual(len(domain.missing_root_selector_ids), 25)
        self.assertEqual(domain.projective_counts, {"primary": 48, "deep": 9, "total": 57})
        self.assertEqual(domain.primary_supports, {"K0": ("220", "330", "440"), "K1": ("221", "331", "441"), "K22": ("220", "221", "222")})
        self.assertEqual(domain.deep_support, ("220", "221", "222"))
        self.assertEqual(domain.cubic_comparator_row_count, 8)
        self.assertTrue(B_PRIME_UNRESOLVED_IS_PRODUCED)

        leaves = tuple(domain.production_leaves)
        self.assertFalse(any(leaf.mechanism_id == "cubic-eft" for leaf in leaves))
        primary = [leaf for leaf in leaves if leaf.role == "primary"]
        self.assertEqual(
            {leaf.mode_label for leaf in primary},
            {"220", "221", "222", "330", "331", "440", "441"},
        )
        self.assertEqual(
            {leaf.coordinate for leaf in primary},
            {Fraction(19, 20), Fraction(99, 100), Fraction(999, 1000), Fraction(9999, 10000)},
        )
        self.assertEqual(
            {leaf.mechanism_id for leaf in primary},
            {
                "horizon-admittance", "exterior-fixed-r3", "exterior-alpha-half",
                "exterior-light-ring", "exterior-throat-kappa",
            },
        )
        controls = [leaf for leaf in leaves if leaf.role == "control"]
        self.assertEqual(
            {leaf.coordinate for leaf in controls},
            {Fraction(19, 20), Fraction(999, 1000)},
        )
        self.assertEqual(
            {leaf.mechanism_id for leaf in controls},
            {"exterior-fixed-r3", "exterior-light-ring", "exterior-throat-kappa"},
        )
        self.assertTrue(any(leaf.mode_label in {"2-minus-2-0", "3-minus-3-0"} for leaf in controls))
        self.assertTrue(all(leaf.spin_role == "direct" for leaf in controls))
        deep = [leaf for leaf in leaves if leaf.role == "deep"]
        self.assertEqual(
            {leaf.coordinate for leaf in deep},
            {Fraction(1, 100), Fraction(1, 500), Fraction(1, 1000)},
        )
        self.assertEqual(
            {leaf.mechanism_id for leaf in deep},
            {
                "horizon-admittance", "exterior-alpha-one", "exterior-light-ring",
                "exterior-throat-kappa",
            },
        )
        self.assertFalse(any(
            leaf.mechanism_id == "exterior-alpha-zero"
            or (
                leaf.role == "primary"
                and leaf.mechanism_id == "exterior-alpha-one"
            )
            for leaf in leaves
        ))


class SparseOverlayBuilderContractTests(unittest.TestCase):
    def test_exact_target_set_is_literal_sparse_and_preserves_coordinates(self) -> None:
        builder = _builder()
        targets = builder.overlay_targets()

        self.assertEqual(len(targets), 44)
        self.assertEqual(len({target.selection_key for target in targets}), 44)
        self.assertEqual(
            {
                (
                    target.ell, target.m, target.n,
                    target.source_coordinate_id,
                    target.source_coordinate.numerator,
                    target.source_coordinate.denominator,
                    target.spin.as_integer_ratio(), target.spin_hex,
                )
                for target in targets
            },
            _literal_target_identities(),
        )
        self.assertEqual(
            [target.order_key for target in targets],
            sorted(target.order_key for target in targets),
        )
        for mode in sorted({(target.ell, target.m, target.n) for target in targets}):
            spins = [
                target.spin
                for target in targets
                if (target.ell, target.m, target.n) == mode
            ]
            with self.subTest(mode=mode):
                self.assertEqual(spins, sorted(spins))

    def test_parent_authentication_fails_before_any_numerical_work(self) -> None:
        builder = _builder()
        base_data = BASE_CSV.read_bytes()
        receipt_data = BASE_RECEIPT.read_bytes()
        mutations = (
            (bytes([base_data[0] ^ 1]) + base_data[1:], receipt_data),
            (base_data, bytes([receipt_data[0] ^ 1]) + receipt_data[1:]),
        )
        for forged_base, forged_receipt in mutations:
            backend = _DeterministicBackend()
            with self.subTest(parent="csv" if forged_base != base_data else "receipt"):
                with self.assertRaisesRegex(ValueError, "base|parent|SHA-256"):
                    builder.build_overlay(
                        forged_base, forged_receipt, backend=backend, workers=1
                    )
                self.assertEqual(backend.calls, 0)

    def test_candidate_assignment_and_adaptive_steps_fail_closed(self) -> None:
        builder = _builder()
        predictions = (
            builder.BranchPrediction(0, -1 + 0j, (1 + 0j, 0j)),
            builder.BranchPrediction(1, 1 + 0j, (1 + 0j, 0j)),
        )
        ambiguous = (
            builder.CandidateRoot(-1j, 4 + 0j, (1 + 0j, 0j)),
            builder.CandidateRoot(1j, 4 + 0j, (1 + 0j, 0j)),
        )
        with self.assertRaisesRegex(ValueError, "assignment.*gap|ambiguous"):
            builder.assign_candidate_clusters(predictions, ambiguous)
        with self.assertRaisesRegex(ValueError, "distinct.*cluster|candidate"):
            builder.assign_candidate_clusters(predictions, ambiguous[:1])

        attempted: list[float] = []

        def always_ambiguous(start: float, stop: float):
            attempted.append(abs(stop - start))
            raise builder.GenealogyError("ambiguous assignment")

        with self.assertRaisesRegex(ValueError, "minimum.*step|fail.*closed"):
            builder.adaptive_advance(
                0.0, 0.02, always_ambiguous, minimum_step=0.003
            )
        self.assertEqual(attempted, [0.02, 0.01, 0.005])

    def test_exact_target_remainder_is_not_reported_as_adaptive_halving(self) -> None:
        builder = _builder()
        self.assertTrue(
            hasattr(builder, "_updated_minimum_adaptive_step"),
            "adaptive-step evidence helper is absent",
        )
        self.assertEqual(
            builder._updated_minimum_adaptive_step(
                previous=0.12, planned_step=0.001, accepted_step=0.001
            ),
            0.12,
        )
        self.assertEqual(
            builder._updated_minimum_adaptive_step(
                previous=0.12, planned_step=0.12, accepted_step=0.03
            ),
            0.03,
        )

    def test_path_and_reverse_gates_reject_computed_rows(self) -> None:
        builder = _builder()
        backend = _DeterministicBackend()
        target = builder.overlay_targets()[0]
        accepted = backend.solve_cohort((target,), {}, builder.OVERLAY_POLICY)[0]
        builder.validate_results((accepted,), expected_targets=(target,))

        for field in ("independent_path_delta_abs", "reverse_delta_abs"):
            with self.subTest(field=field), self.assertRaisesRegex(
                ValueError, "independent|reverse"
            ):
                builder.validate_results(
                    (replace(accepted, **{field: 1.1e-8}),),
                    expected_targets=(target,),
                )

        with self.assertRaisesRegex(ValueError, "angular overlap"):
            builder.validate_results(
                (replace(accepted, angular_overlap_min=0.899),),
                expected_targets=(target,),
            )

    def test_output_order_receipt_and_complete_checkpoint_are_deterministic(self) -> None:
        builder = _builder()
        base_data = BASE_CSV.read_bytes()
        receipt_data = BASE_RECEIPT.read_bytes()
        serial_backend = _DeterministicBackend()
        parallel_backend = _DeterministicBackend()

        serial = builder.build_overlay(
            base_data, receipt_data, backend=serial_backend, workers=1
        )
        parallel = builder.build_overlay(
            base_data, receipt_data, backend=parallel_backend, workers=4
        )
        self.assertEqual(serial.catalog_bytes, parallel.catalog_bytes)
        self.assertEqual(serial.receipt_bytes, parallel.receipt_bytes)
        self.assertEqual(serial.checkpoint_bytes, parallel.checkpoint_bytes)

        reader = csv.DictReader(
            io.StringIO(serial.catalog_bytes.decode("utf-8")), strict=True
        )
        rows = list(reader)
        receipt = json.loads(serial.receipt_bytes)
        self.assertEqual(tuple(reader.fieldnames or ()), builder.OUTPUT_COLUMNS)
        self.assertEqual(len(rows), 44)
        self.assertEqual(receipt["overlay"]["row_count_excluding_header"], 44)
        self.assertEqual(
            receipt["overlay"]["ordering"],
            ["ell", "m", "n", "spin_binary64"],
        )
        for mode in sorted(
            {(int(row["ell"]), int(row["m"]), int(row["n"])) for row in rows}
        ):
            spins = [
                float(row["spin_float"])
                for row in rows
                if (int(row["ell"]), int(row["m"]), int(row["n"])) == mode
            ]
            with self.subTest(serialized_mode=mode):
                self.assertEqual(spins, sorted(spins))
        self.assertEqual(
            receipt["overlay"]["sha256"],
            hashlib.sha256(serial.catalog_bytes).hexdigest(),
        )
        self.assertEqual(receipt["parents"]["base_catalog_sha256"], BASE_CSV_SHA256)
        self.assertEqual(receipt["parents"]["base_receipt_sha256"], BASE_RECEIPT_SHA256)

        warm_backend = _DeterministicBackend()
        warm = builder.build_overlay(
            base_data,
            receipt_data,
            backend=warm_backend,
            workers=4,
            checkpoint_bytes=serial.checkpoint_bytes,
        )
        self.assertEqual(warm_backend.calls, 0)
        self.assertEqual(warm.catalog_bytes, serial.catalog_bytes)
        self.assertEqual(warm.receipt_bytes, serial.receipt_bytes)

        forged_complete = json.loads(serial.checkpoint_bytes)
        forged_complete["results"][0]["omega_re_M"] += 1e-6
        forged_complete_bytes = builder._canonical_json_bytes(forged_complete)
        rejected_complete_backend = _DeterministicBackend()
        with self.assertRaisesRegex(ValueError, "checkpoint.*content|SHA-256"):
            builder.build_overlay(
                base_data,
                receipt_data,
                backend=rejected_complete_backend,
                checkpoint_bytes=forged_complete_bytes,
            )
        self.assertEqual(rejected_complete_backend.calls, 0)

        for corrupt in (
            serial.checkpoint_bytes[:-1],
            serial.checkpoint_bytes.replace(
                builder.POLICY_SHA256.encode("ascii"), b"0" * 64, 1
            ),
        ):
            rejected_backend = _DeterministicBackend()
            with self.subTest(checkpoint=hashlib.sha256(corrupt).hexdigest()):
                with self.assertRaisesRegex(
                    ValueError, "checkpoint|canonical|policy"
                ):
                    builder.build_overlay(
                        base_data,
                        receipt_data,
                        backend=rejected_backend,
                        checkpoint_bytes=corrupt,
                    )
                self.assertEqual(rejected_backend.calls, 0)

    def test_cohort_checkpoints_resume_without_recomputing_completed_roots(self) -> None:
        builder = _builder()
        checkpoints: list[bytes] = []
        baseline_backend = _DeterministicBackend()
        baseline = builder.build_overlay(
            BASE_CSV.read_bytes(),
            BASE_RECEIPT.read_bytes(),
            backend=baseline_backend,
            checkpoint_callback=checkpoints.append,
        )
        self.assertEqual(len(checkpoints), 4)
        self.assertFalse(json.loads(checkpoints[0])["complete"])
        self.assertTrue(json.loads(checkpoints[-1])["complete"])

        completed_count = len(json.loads(checkpoints[1])["results"])
        resumed_backend = _DeterministicBackend()
        resumed = builder.build_overlay(
            BASE_CSV.read_bytes(),
            BASE_RECEIPT.read_bytes(),
            backend=resumed_backend,
            checkpoint_bytes=checkpoints[1],
        )
        self.assertEqual(resumed_backend.calls, 44 - completed_count)
        self.assertEqual(resumed.catalog_bytes, baseline.catalog_bytes)
        self.assertEqual(resumed.receipt_bytes, baseline.receipt_bytes)

        forged_partial = json.loads(checkpoints[1])
        forged_partial["results"][0]["predictor_correction_abs"] += 1e-6
        forged_partial_bytes = builder._canonical_json_bytes(forged_partial)
        rejected_partial_backend = _DeterministicBackend()
        with self.assertRaisesRegex(ValueError, "checkpoint.*content|SHA-256"):
            builder.build_overlay(
                BASE_CSV.read_bytes(),
                BASE_RECEIPT.read_bytes(),
                backend=rejected_partial_backend,
                checkpoint_bytes=forged_partial_bytes,
            )
        self.assertEqual(rejected_partial_backend.calls, 0)


class AdmittedSparseOverlayTests(unittest.TestCase):
    def test_packaged_overlay_is_authenticated_without_mutating_the_base(self) -> None:
        spectrum = importlib.import_module("windows_solver.spectrum")
        for name in (
            "OVERLAY_RESOURCE", "OVERLAY_RECEIPT_RESOURCE",
            "OVERLAY_DATA_SHA256", "OVERLAY_RECEIPT_SHA256",
            "load_overlay_catalog",
        ):
            self.assertTrue(hasattr(spectrum, name), f"missing runtime binding {name}")

        self.assertEqual(hashlib.sha256(BASE_CSV.read_bytes()).hexdigest(), BASE_CSV_SHA256)
        self.assertEqual(
            hashlib.sha256(BASE_RECEIPT.read_bytes()).hexdigest(),
            BASE_RECEIPT_SHA256,
        )
        overlay = spectrum.load_overlay_catalog()
        self.assertEqual(len(overlay.roots), 44)
        self.assertEqual(
            hashlib.sha256(spectrum.OVERLAY_RESOURCE.read_bytes()).hexdigest(),
            spectrum.OVERLAY_DATA_SHA256,
        )
        self.assertEqual(
            hashlib.sha256(spectrum.OVERLAY_RECEIPT_RESOURCE.read_bytes()).hexdigest(),
            spectrum.OVERLAY_RECEIPT_SHA256,
        )

    def test_existing_spectral_owner_selects_every_b_prime_root_exactly(self) -> None:
        spectrum = importlib.import_module("windows_solver.spectrum")
        catalog = spectrum.load_spectrum_catalog()
        self.assertTrue(
            hasattr(catalog, "base") and hasattr(catalog, "overlay"),
            "existing spectral owner does not load the base+overlay union",
        )
        self.assertEqual(len(catalog.base.roots), 2736)
        self.assertEqual(len(catalog.overlay.roots), 44)

        selected_keys = set()
        for selector in B_PRIME_RELEASE_DOMAIN.root_selectors:
            with self.subTest(selector=selector.selector_id):
                selected = catalog.select(_request_for_selector(selector))
                self.assertEqual(len(selected), 1)
                root = selected[0]
                key = (*selector.mode, selector.spin.hex())
                self.assertEqual(root.selection_key, key)
                selected_keys.add(key)
        self.assertEqual(len(selected_keys), 48)

    def test_union_rejects_duplicate_or_ambiguous_selection_keys(self) -> None:
        spectrum = importlib.import_module("windows_solver.spectrum")
        self.assertTrue(hasattr(spectrum, "SpectralCatalogUnion"))
        base = spectrum.SpectrumCatalog.from_csv_bytes(
            BASE_CSV.read_bytes(), expected_sha256=BASE_CSV_SHA256
        )
        overlay = spectrum.load_overlay_catalog()
        forged = replace(overlay, roots=(base.roots[0], *overlay.roots[1:]))
        with self.assertRaisesRegex(ValueError, "duplicate|ambiguous"):
            spectrum.SpectralCatalogUnion(base=base, overlay=forged)


class OverlayExecutionSmokeTests(unittest.TestCase):
    def test_predeclared_head_tail_and_risk_rows_cover_final_overlay(self) -> None:
        spectrum = importlib.import_module("windows_solver.spectrum")
        overlay = spectrum.load_overlay_catalog()
        selected = _overlay_smoke_rows(overlay.roots)

        self.assertEqual(_overlay_row_id(overlay.roots[0]), OVERLAY_SMOKE_HEAD_ID)
        self.assertEqual(_overlay_row_id(overlay.roots[-1]), OVERLAY_SMOKE_TAIL_ID)
        self.assertEqual(
            tuple(_overlay_row_id(root) for root in selected),
            OVERLAY_SMOKE_ROW_IDS,
        )
        by_id = {_overlay_row_id(root): root for root in selected}
        self.assertEqual(
            by_id[OVERLAY_SMOKE_MAXIMUM_RESIDUAL_ID].optimizer_residual_abs,
            max(root.optimizer_residual_abs for root in overlay.roots),
        )
        self.assertEqual(
            by_id[
                OVERLAY_SMOKE_MINIMUM_SEPARATION_AND_GAP_ID
            ].assigned_separation_abs,
            min(root.assigned_separation_abs for root in overlay.roots),
        )
        self.assertEqual(
            by_id[
                OVERLAY_SMOKE_MINIMUM_SEPARATION_AND_GAP_ID
            ].assignment_relative_gap,
            min(root.assignment_relative_gap for root in overlay.roots),
        )
        correction_and_overlap = by_id[
            OVERLAY_SMOKE_MAXIMUM_CORRECTION_AND_MINIMUM_OVERLAP_ID
        ]
        self.assertEqual(
            correction_and_overlap.predictor_correction_abs,
            max(root.predictor_correction_abs for root in overlay.roots),
        )
        self.assertEqual(
            correction_and_overlap.angular_overlap_min,
            min(root.angular_overlap_min for root in overlay.roots),
        )
        self.assertEqual(
            {
                _overlay_row_id(root)[:6]
                for root in selected
                if root.source_coordinate == Fraction(1, 1000)
            },
            {
                (2, 1, 0, "M-kappa", 1, 1000),
                (2, 2, 0, "M-kappa", 1, 1000),
                (2, 2, 1, "M-kappa", 1, 1000),
                (2, 2, 2, "M-kappa", 1, 1000),
            },
        )
        self.assertEqual(
            {
                (root.ell, root.m, root.n)
                for root in selected
                if root.source_coordinate == Fraction(9999, 10000)
            },
            {(4, 4, 0), (4, 4, 1)},
        )

    def test_smoke_rows_recompute_and_reload_through_installed_owner(self) -> None:
        if kerr_cf_solver is None:
            self.fail("canonical continued-fraction backend is unavailable")
        spectrum = importlib.import_module("windows_solver.spectrum")
        smoke_rows = _overlay_smoke_rows(spectrum.load_overlay_catalog().roots)

        for root in smoke_rows:
            with self.subTest(row_id=_overlay_row_id(root), phase="recompute"):
                omega = complex(root.omega_re, root.omega_im)
                canonical = kerr_cf_solver.coupled_error(
                    omega, root.spin, -2, root.ell, root.m, root.n, 20
                )
                refined = kerr_cf_solver.coupled_error(
                    omega, root.spin, -2, root.ell, root.m, root.n, 24
                )
                catalog_a = complex(root.angular_A_re, root.angular_A_im)
                self.assertLessEqual(abs(canonical[0]), 1e-8)
                self.assertLessEqual(abs(refined[0]), 1e-8)
                self.assertLessEqual(float(canonical[2]), 1e-9)
                self.assertLessEqual(float(refined[2]), 1e-9)
                canonical_a = complex(canonical[1])
                refined_a = complex(refined[1])
                self.assertLessEqual(abs(canonical_a - catalog_a), 1e-11)
                self.assertLessEqual(abs(refined_a - catalog_a), 1e-11)
                self.assertLessEqual(
                    abs(
                        abs(refined_a - canonical_a)
                        - root.angular_refinement_abs
                    ),
                    1e-11,
                )

        spectrum.load_spectrum_catalog.cache_clear()
        spectrum.load_base_spectrum_catalog.cache_clear()
        spectrum.load_overlay_catalog.cache_clear()
        spectrum.load_catalog_receipt.cache_clear()
        spectrum.load_overlay_receipt.cache_clear()
        reloaded = spectrum.load_spectrum_catalog()
        provider = spectrum.SpectralCatalogProvider()
        descriptor = provider.descriptor.to_mapping()
        for expected in smoke_rows:
            request = _request_for_overlay_root(expected)
            with self.subTest(row_id=_overlay_row_id(expected), phase="reload"):
                selected = reloaded.select(request)
                self.assertEqual(len(selected), 1)
                self.assertEqual(_overlay_row_id(selected[0]), _overlay_row_id(expected))
                result = provider.execute(
                    request, {Capability.PROBLEM_CONTRACT: object()}
                )
                spectrum.validate_spectral_payload(
                    request, descriptor, result.payload
                )
                self.assertEqual(result.payload["requested_root_count"], 1)
                payload_root = result.payload["roots"][0]
                self.assertEqual(
                    payload_root["spin_binary64_hex"], expected.spin_hex
                )
                self.assertEqual(
                    payload_root["frequency"],
                    {
                        "real": expected.omega_re,
                        "imaginary": expected.omega_im,
                        "units": "Momega",
                    },
                )


class TaskBoardRegressionTests(unittest.TestCase):
    def test_idle_board_rejects_a_higher_same_priority_next_task(self) -> None:
        """Equal-priority ready work is ordered deterministically by task ID."""

        repository_root = Path(__file__).resolve().parents[1]
        source_board = repository_root / ".tasks"
        spec = importlib.util.spec_from_file_location(
            "task_board_validator", source_board / "validate_board.py"
        )
        validator = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(validator)

        with tempfile.TemporaryDirectory() as temporary_directory:
            board = Path(temporary_directory)
            for path in source_board.iterdir():
                if path.is_file():
                    shutil.copy2(path, board / path.name)
            config = json.loads(
                (board / "config.json").read_text(encoding="utf-8")
            )
            tasks = {
                number: body
                for state, filename in config["states"].items()
                for _, number, _, body in validator.sections(
                    (board / filename).read_text(encoding="utf-8")
                )
            }
            task_seven = tasks.pop(7)
            task_eight = tasks.pop(8).replace(
                "- **Blocked by:** TASK-006, TASK-007",
                "- **Blocked by:** TASK-006",
            )
            self.assertNotIn("TASK-007", task_eight)
            (board / config["states"]["Done"]).write_text(
                "# Done\n\n" + "\n".join(tasks.values()), encoding="utf-8"
            )
            (board / config["states"]["Backlog"]).write_text(
                "# Backlog\n\n" + task_seven, encoding="utf-8"
            )
            (board / config["states"]["Next"]).write_text(
                "# Next\n\n" + task_eight, encoding="utf-8"
            )
            (board / config["states"]["In Progress"]).write_text(
                "# In Progress\n", encoding="utf-8"
            )
            (board / config["states"]["Rejected"]).write_text(
                "# Rejected\n", encoding="utf-8"
            )

            validator.ROOT = board
            stderr = io.StringIO()
            with redirect_stderr(stderr):
                result = validator.main()

        self.assertEqual(result, 1)
        self.assertIn("lowest task ID", stderr.getvalue())
