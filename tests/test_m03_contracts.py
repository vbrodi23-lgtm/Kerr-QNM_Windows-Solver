from __future__ import annotations

import copy
from dataclasses import replace
import hashlib
import json
import re
import unittest

from windows_solver.m03_contracts import (
    M02LineageAnchor,
    M03ArtifactEnvelope,
    M03ArtifactKind,
    M03CacheIdentity,
    M03EvidenceState,
    M03RootSeed,
    adapt_spectral_payload,
    build_m03_envelope,
)
from windows_solver.precision_tiers import (
    PrecisionTierPresentation,
    SemanticPrecisionPresentation,
    precision_tier_presentation,
    semantic_precision_presentation,
)


SHA256 = re.compile(r"[0-9a-f]{64}\Z")


def _fixture_sha256(value: object) -> str:
    encoded = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _reseal_m02_receipt(receipt: dict[str, object]) -> None:
    record = receipt["record"]
    assert isinstance(record, dict)
    record_content = {
        key: value for key, value in record.items() if key != "record_sha256"
    }
    record_sha256 = _fixture_sha256(record_content)
    record["record_sha256"] = record_sha256
    receipt["canonical_leaf_record_sha256"] = record_sha256
    sealed = {
        key: value for key, value in receipt.items() if key != "receipt_sha256"
    }
    receipt["receipt_sha256"] = _fixture_sha256(sealed)


def _base_root() -> dict[str, object]:
    return {
        "mode": {
            "s": -2,
            "ell": 2,
            "m": 2,
            "n": 0,
            "branch": "schwarzschild-overtone-continuation",
            "polarization": "gravitational",
        },
        "spin": 0.95,
        "spin_exact": {"numerator": 19, "denominator": 20},
        "spin_binary64_hex": float(0.95).hex(),
        "frequency": {
            "real": 0.7463199987169307,
            "imaginary": -0.053149008045981994,
            "units": "Momega",
        },
        "angular_separation_constant_A": {
            "real": 2.1,
            "imaginary": 0.02,
        },
        "numerical_evidence": {
            "optimizer_residual_abs": 1.4e-11,
            "continued_fraction_error": 8.0e-15,
            "continued_fraction_terms": 1200,
            "angular_refinement_abs": 2.0e-13,
            "repeat_polish_delta_abs": 3.0e-12,
            "branch_seed_delta_abs": 5.0e-12,
            "nearest_overtone_separation_abs": 0.1,
        },
        "independent_comparison": None,
    }


def _overlay_root() -> dict[str, object]:
    return {
        "mode": {
            "s": -2,
            "ell": 4,
            "m": 4,
            "n": 0,
            "branch": "schwarzschild-overtone-continuation",
            "polarization": "gravitational",
        },
        "source_coordinate": {
            "coordinate_id": "a-over-M",
            "numerator": 9999,
            "denominator": 10000,
            "transformation_id": "identity-a-over-M",
        },
        "spin": 0.9999,
        "spin_binary64_ratio": {
            "numerator": 4503149267407759,
            "denominator": 4503599627370496,
        },
        "spin_binary64_hex": float(0.9999).hex(),
        "frequency": {
            "real": 1.95,
            "imaginary": -0.012,
            "units": "Momega",
        },
        "angular_separation_constant_A": {
            "real": 10.2,
            "imaginary": 0.3,
        },
        "numerical_evidence": {
            "optimizer_residual_abs": 2.0e-11,
            "continued_fraction_error": 9.0e-15,
            "continued_fraction_terms": 3200,
            "angular_refinement_abs": 3.0e-13,
            "repeat_polish_delta_abs": 4.0e-12,
            "predictor_correction_abs": 1.0e-5,
            "predictor_correction_over_separation": 0.01,
            "assigned_separation_abs": 0.02,
            "assignment_relative_gap": 0.5,
            "canonical_polish_delta_abs": 1.0e-10,
            "independent_path_delta_abs": 2.0e-10,
            "reverse_delta_abs": 2.5e-10,
            "angular_overlap_min": 0.999,
            "schedule_a_steps": 20,
            "schedule_b_steps": 22,
            "minimum_adaptive_step": 0.0005,
            "formal_root_enclosure": False,
        },
        "independent_comparison": None,
    }


def _spectral_payload() -> dict[str, object]:
    roots = [_base_root(), _overlay_root()]
    return {
        "schema_version": 1,
        "catalog_id": (
            "pure-kerr-qnm-lattice-2736-plus-m02-b-prime-sparse-overlay-44"
        ),
        "delivery_mode": "computed-base-plus-sparse-overlay-exact-selection",
        "catalog_data_sha256": "1" * 64,
        "overlay_data_sha256": "2" * 64,
        "physics_contract": {
            "spin_weight": -2,
            "boundary_conditions": {
                "horizon": "ingoing",
                "infinity": "outgoing",
            },
            "time_dependence": "exp(-i omega t)",
            "frequency_units": "Momega",
            "angular_eigenvalue": "A",
            "pure_kerr": True,
        },
        "provenance": {},
        "scope": {},
        "validation": {},
        "requested_root_count": len(roots),
        "roots": roots,
    }


def _m02_receipt() -> dict[str, object]:
    receipt: dict[str, object] = {
        "canonical_leaf_record_sha256": "",
        "created_utc": "2026-08-10T01:58:09.243375Z",
        "leaf_id": "b-prime-leaf-" + "4" * 64,
        "receipt_sha256": "",
        "record": {
            "computed": True,
            "leaf_id": "b-prime-leaf-" + "4" * 64,
            "missing_precision_digits": None,
            "record_sha256": "",
            "role": "primary",
            "sentinel": None,
            "sentinel_comparison": None,
            "stages": [
                {
                    "component_result": {
                        "evidence_kind": "native-physical-response",
                        "result": {
                            "baseline": {
                                "branch_id": (
                                    "schwarzschild-overtone-continuation"
                                ),
                                "equation_id": (
                                    "same-equation-complex-amplitude-root-readout-v1"
                                ),
                                "omega": {
                                    "real": 0.7463199987169307,
                                    "imaginary": -0.053149008045981994,
                                },
                                "root_reference_id": (
                                    "spectral-root-reference-" + "6" * 64
                                ),
                            },
                            "lineage": {
                                "backend_identity_sha256": "7" * 64,
                                "equation_id": (
                                    "same-equation-complex-amplitude-root-readout-v1"
                                ),
                                "leaf_id": "b-prime-leaf-" + "4" * 64,
                                "policy_sha256": "8" * 64,
                                "root_identity_sha256": "9" * 64,
                                "root_reference_id": (
                                    "spectral-root-reference-" + "6" * 64
                                ),
                                "sampling_coordinate": {
                                    "coordinate_id": "a_over_M",
                                    "exact": {
                                        "numerator": 19,
                                        "denominator": 20,
                                    },
                                    "transformation_id": "identity-a-over-M",
                                    "value": 0.95,
                                },
                                "source_root_mapping": None,
                            },
                            "mechanism_id": "exterior-alpha-half",
                            "response": {
                                "real": 0.001263451674967872,
                                "imaginary": 0.00047320716119296963,
                            },
                            "status": "CONVERGED",
                            "usable": True,
                        },
                        "scientific_runtime": {
                            "backend": "julia-gsn",
                            "cache_path": "redacted",
                            "cache_sha256_observed": "a" * 64,
                            "parameter_pairs": [],
                            "record_artifact_ids": [],
                        },
                    },
                    "deep_diagnostics": None,
                    "digits": 64,
                    "discrepancy_enclosed": True,
                    "discrepancy_from_previous_abs": None,
                    "local_disk_radius_abs": 5.0e-9,
                    "numerical_state": "CONVERGED",
                    "runner_provenance": {},
                    "self_refinement_enclosed": True,
                    "signed_error_channels": {},
                    "stage_sha256": "b" * 64,
                }
            ],
            "state": "PRODUCED",
            "trigger_ids": [],
        },
        "schema_version": 1,
        "scientific_computation_identity_sha256": "c" * 64,
        "source_type": "originating-campaign",
        "stage_count": 1,
        "terminal_state": "PRODUCED",
    }
    _reseal_m02_receipt(receipt)
    return receipt


class M03CatalogAdapterTests(unittest.TestCase):
    def test_adapts_base_and_overlay_roots_deterministically(self) -> None:
        first = adapt_spectral_payload(_spectral_payload())
        second = adapt_spectral_payload(_spectral_payload())

        self.assertEqual(len(first), 2)
        self.assertEqual(first[0].source_realization, "base-catalogue")
        self.assertEqual(first[1].source_realization, "exact-selector-overlay")
        self.assertRegex(first[0].identity_sha256, SHA256)
        self.assertRegex(first[1].identity_sha256, SHA256)
        self.assertEqual(
            [item.to_mapping() for item in first],
            [item.to_mapping() for item in second],
        )

    def test_rejects_ambiguous_root_realization(self) -> None:
        payload = _spectral_payload()
        roots = payload["roots"]
        assert isinstance(roots, list)
        root = roots[0]
        assert isinstance(root, dict)
        root["source_coordinate"] = copy.deepcopy(
            _overlay_root()["source_coordinate"]
        )
        root["spin_binary64_ratio"] = copy.deepcopy(
            _overlay_root()["spin_binary64_ratio"]
        )

        with self.assertRaisesRegex(ValueError, "ambiguous root realization"):
            adapt_spectral_payload(payload)

    def test_rejects_duplicate_root_identity(self) -> None:
        payload = _spectral_payload()
        payload["roots"] = [_base_root(), _base_root()]
        payload["requested_root_count"] = 2

        with self.assertRaisesRegex(ValueError, "duplicate M03 root seed"):
            adapt_spectral_payload(payload)

    def test_rejects_base_exact_spin_that_disagrees_with_binary64_spin(self) -> None:
        payload = _spectral_payload()
        roots = payload["roots"]
        assert isinstance(roots, list)
        root = roots[0]
        assert isinstance(root, dict)
        root["spin_exact"] = {"numerator": 97, "denominator": 100}

        with self.assertRaisesRegex(ValueError, "base exact spin is inconsistent"):
            adapt_spectral_payload(payload)

    def test_rejects_mode_outside_admitted_catalogue_domain(self) -> None:
        for field, invalid in (
            ("ell", 5),
            ("n", 3),
            ("branch", "unfrozen-branch"),
            ("polarization", "unfrozen-polarization"),
        ):
            with self.subTest(field=field):
                payload = _spectral_payload()
                roots = payload["roots"]
                assert isinstance(roots, list)
                root = roots[0]
                assert isinstance(root, dict)
                mode = root["mode"]
                assert isinstance(mode, dict)
                mode[field] = invalid

                with self.assertRaisesRegex(
                    ValueError,
                    "outside the admitted M03 catalogue domain",
                ):
                    adapt_spectral_payload(payload)

    def test_root_seed_factory_rejects_malformed_catalogue_binding(self) -> None:
        """Catches direct factory bypass of admitted catalogue identities."""

        cases = (
            ("", "1" * 64, "2" * 64, "catalog ID"),
            ("admitted-catalogue", "not-a-sha", "2" * 64, "catalog data identity"),
            ("admitted-catalogue", "1" * 64, "not-a-sha", "overlay data identity"),
        )
        for catalog_id, catalog_hash, overlay_hash, message in cases:
            with self.subTest(message=message):
                with self.assertRaisesRegex(ValueError, message):
                    M03RootSeed.from_spectral_root(
                        _base_root(),
                        catalog_id=catalog_id,
                        catalog_data_sha256=catalog_hash,
                        overlay_data_sha256=overlay_hash,
                    )


class M03LineageAndCacheTests(unittest.TestCase):
    def test_m02_receipt_preserves_lineage_without_response_values(self) -> None:
        anchor = M02LineageAnchor.from_receipt(_m02_receipt())
        mapping = anchor.to_mapping()

        self.assertEqual(anchor.reconciliation_state, "UNRECONCILED")
        self.assertEqual(
            anchor.precision_tier,
            precision_tier_presentation(64),
        )
        self.assertEqual(
            mapping["precision_tier"],
            {
                "arithmetic": "IEEE-754 binary64",
                "legacy_tier_value": 64,
                "nominal_decimal_digits": 15.95,
                "precision_tier": "binary64",
                "presentation_label": "binary64 (~15.95 dec)",
            },
        )
        self.assertEqual(anchor.root_identity_sha256, "9" * 64)
        self.assertEqual(
            anchor.root_reference_id,
            "spectral-root-reference-" + "6" * 64,
        )
        self.assertEqual(
            mapping["sampling_coordinate"],
            {
                "coordinate_id": "a_over_M",
                "exact": {"numerator": 19, "denominator": 20},
                "transformation_id": "identity-a-over-M",
                "value": 0.95,
            },
        )
        self.assertNotIn("response", repr(mapping))
        self.assertNotIn("baseline_omega", mapping)
        self.assertNotIn("0.7463199987169307", repr(mapping))

    def test_cache_identity_changes_when_pairing_changes(self) -> None:
        seed = adapt_spectral_payload(_spectral_payload())[0]
        first = _cache(seed, pairing_id="bilinear-pairing-v1")
        second = _cache(seed, pairing_id="sesquilinear-pairing-v1")

        self.assertRegex(first.cache_sha256, SHA256)
        self.assertNotEqual(first.cache_sha256, second.cache_sha256)

    def test_cache_rejects_unreconciled_m02_anchor(self) -> None:
        seed = adapt_spectral_payload(_spectral_payload())[0]
        anchor = M02LineageAnchor.from_receipt(_m02_receipt())

        with self.assertRaisesRegex(ValueError, "explicitly reconciled"):
            M03CacheIdentity.build(
                seed=seed,
                artifact_kind=M03ArtifactKind.RADIAL_ANGULAR_FIELD,
                equation_version="separated-teukolsky-field-v1",
                convention_version="kerr-field-conventions-v1",
                radial_grid={"coordinate": "compactified-r", "points": 256},
                angular_grid={"basis": "spheroidal", "modes": 48},
                normalization_id="unit-outgoing-scri-amplitude-v1",
                pairing_id="not-applicable",
                backend_revisions={"gsn": "pinned-commit"},
                precision_tier=semantic_precision_presentation("bigfloat-40"),
                validation_policy={"field-equation-residual-max": 1.0e-10},
                m02_lineage=anchor,
            )

    def test_cache_rejects_forged_precision_presentation(self) -> None:
        seed = adapt_spectral_payload(_spectral_payload())[0]
        forged = SemanticPrecisionPresentation(
            precision_tier="decimal-64",
            arithmetic="fabricated decimal arithmetic",
            working_precision_bits=213,
            nominal_decimal_digits=64,
            presentation_label="64 decimal digits",
        )

        with self.assertRaisesRegex(ValueError, "canonical precision tier"):
            _cache(seed, pairing_id="not-applicable", precision_tier=forged)

    def test_cache_rejects_non_string_json_keys(self) -> None:
        seed = adapt_spectral_payload(_spectral_payload())[0]

        with self.assertRaisesRegex(
            (TypeError, ValueError),
            "JSON object keys must be strings",
        ):
            _cache(
                seed,
                pairing_id="not-applicable",
                radial_grid={1: "integer-key", "1": "string-key"},
            )

    def test_m02_lineage_rejects_tampered_sealed_record(self) -> None:
        receipt = _m02_receipt()
        record = receipt["record"]
        assert isinstance(record, dict)
        record["role"] = "tampered-role"

        with self.assertRaisesRegex(
            ValueError,
            "canonical record digest is invalid",
        ):
            M02LineageAnchor.from_receipt(receipt)

    def test_m02_lineage_rejects_checkpoint_only_terminal_state(self) -> None:
        receipt = _m02_receipt()
        record = receipt["record"]
        assert isinstance(record, dict)
        record["state"] = "FAILED"
        receipt["terminal_state"] = "FAILED"
        _reseal_m02_receipt(receipt)

        with self.assertRaisesRegex(
            ValueError,
            "solved-leaf receipt terminal state is invalid",
        ):
            M02LineageAnchor.from_receipt(receipt)

    def test_m02_lineage_rejects_response_in_sampling_coordinate(self) -> None:
        """Catches nested M02 response data crossing the lineage boundary."""

        receipt = _m02_receipt()
        record = receipt["record"]
        assert isinstance(record, dict)
        stages = record["stages"]
        assert isinstance(stages, list)
        component = stages[-1]["component_result"]
        assert isinstance(component, dict)
        result = component["result"]
        assert isinstance(result, dict)
        lineage = result["lineage"]
        assert isinstance(lineage, dict)
        coordinate = lineage["sampling_coordinate"]
        assert isinstance(coordinate, dict)
        coordinate["response"] = {"real": 12.34, "imaginary": -56.78}
        _reseal_m02_receipt(receipt)

        with self.assertRaisesRegex(ValueError, "sampling coordinate fields"):
            M02LineageAnchor.from_receipt(receipt)


def _cache(
    seed: object,
    *,
    pairing_id: str,
    artifact_kind: M03ArtifactKind = M03ArtifactKind.RADIAL_ANGULAR_FIELD,
    precision_tier: SemanticPrecisionPresentation | None = None,
    radial_grid: object | None = None,
) -> M03CacheIdentity:
    validation_policy = (
        {
            "minimum_overlap": 0.99,
            "maximum_exact_node_residual_abs": 1.0e-8,
            "require_branch_resolved": True,
        }
        if artifact_kind is M03ArtifactKind.KAPPA_GENEALOGY
        else {
            "field_equation_residual_abs_max": 1.0e-10,
            "horizon_boundary_residual_abs_max": 1.0e-10,
            "infinity_boundary_residual_abs_max": 1.0e-10,
            "wronskian_relative_drift_max": 1.0e-10,
            "resolution_relative_field_difference_max": 1.0e-8,
        }
    )
    return M03CacheIdentity.build(
        seed=seed,
        artifact_kind=artifact_kind,
        equation_version="separated-teukolsky-field-v1",
        convention_version="kerr-field-conventions-v1",
        radial_grid=(
            {"coordinate": "compactified-r", "points": 256}
            if radial_grid is None
            else radial_grid
        ),
        angular_grid={"basis": "spheroidal", "modes": 48},
        normalization_id="unit-outgoing-scri-amplitude-v1",
        pairing_id=pairing_id,
        backend_revisions={"gsn": "pinned-commit"},
        precision_tier=(
            semantic_precision_presentation("bigfloat-40")
            if precision_tier is None
            else precision_tier
        ),
        validation_policy=validation_policy,
        m02_lineage=None,
    )


class M03ArtifactContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.seed = adapt_spectral_payload(_spectral_payload())[0]
        self.cache = _cache(self.seed, pairing_id="not-applicable")

    def test_math_blocked_contracts_cannot_claim_produced(self) -> None:
        for kind in (
            M03ArtifactKind.COMODE_NORMALIZATION,
            M03ArtifactKind.POLE_RESIDUE,
            M03ArtifactKind.BRANCH_CLASSIFICATION,
            M03ArtifactKind.NHEK_MATCH,
        ):
            with self.subTest(kind=kind):
                cache = _cache(
                    self.seed,
                    pairing_id="human-math-review-required",
                    artifact_kind=kind,
                )
                with self.assertRaisesRegex(ValueError, "human math review"):
                    build_m03_envelope(
                        kind=kind,
                        seed=self.seed,
                        cache_identity=cache,
                        evidence_state=M03EvidenceState.PRODUCED,
                        payload={},
                    )

    def test_contract_ids_and_math_blockers_are_exact(self) -> None:
        self.assertEqual(
            M03ArtifactKind.COMODE_NORMALIZATION.value,
            "co-mode-normalization",
        )
        expected = {
            M03ArtifactKind.COMODE_NORMALIZATION: (
                "HUMAN_MATH_REVIEW_REQUIRED: freeze the separated adjoint "
                "equation, pairing, phase convention, and normalization identity"
            ),
            M03ArtifactKind.POLE_RESIDUE: (
                "HUMAN_MATH_REVIEW_REQUIRED: derive the Green-function "
                "numerator, determinant derivative, source, and readout conventions"
            ),
            M03ArtifactKind.BRANCH_CLASSIFICATION: (
                "HUMAN_MATH_REVIEW_REQUIRED: freeze classification observables, "
                "κ-domain, uncertainty model, and transition policy"
            ),
            M03ArtifactKind.NHEK_MATCH: (
                "HUMAN_MATH_REVIEW_REQUIRED: supply the matched-asymptotic "
                "formula, overlap region, convention map, and error model"
            ),
        }
        for kind, blocker in expected.items():
            with self.subTest(kind=kind):
                cache = _cache(
                    self.seed,
                    pairing_id="human-math-review-required",
                    artifact_kind=kind,
                )
                envelope = build_m03_envelope(
                    kind=kind,
                    seed=self.seed,
                    cache_identity=cache,
                    evidence_state=(
                        M03EvidenceState.BLOCKED_HUMAN_MATH_REVIEW
                    ),
                    payload={},
                )
                self.assertEqual(envelope.blockers, (blocker,))

    def test_invariant_contracts_cannot_be_forged_through_dataclass_init(self) -> None:
        with self.assertRaisesRegex(TypeError, "validated factory"):
            replace(self.seed, identity_sha256="0" * 64)
        with self.assertRaisesRegex(TypeError, "validated factory"):
            replace(self.cache, cache_sha256="0" * 64)
        with self.assertRaisesRegex(TypeError, "validated factory"):
            M03ArtifactEnvelope(
                kind=M03ArtifactKind.RADIAL_ANGULAR_FIELD,
                seed_identity_sha256="0" * 64,
                cache_sha256="1" * 64,
                evidence_state=M03EvidenceState.ADMITTED,
                payload={},
                blockers=(),
                envelope_sha256="2" * 64,
            )

    def test_field_contract_requires_complete_validation(self) -> None:
        with self.assertRaisesRegex(ValueError, "missing validation fields"):
            build_m03_envelope(
                kind=M03ArtifactKind.RADIAL_ANGULAR_FIELD,
                seed=self.seed,
                cache_identity=self.cache,
                evidence_state=M03EvidenceState.PRODUCED,
                payload={"validation": {"field_equation_residual_abs": 1.0e-12}},
            )

        envelope = build_m03_envelope(
            kind=M03ArtifactKind.RADIAL_ANGULAR_FIELD,
            seed=self.seed,
            cache_identity=self.cache,
            evidence_state=M03EvidenceState.PRODUCED,
            payload={
                "validation": {
                    "field_equation_residual_abs": 1.0e-12,
                    "boundary_residuals": {
                        "horizon": 2.0e-12,
                        "infinity": 3.0e-12,
                    },
                    "wronskian_relative_drift": 4.0e-12,
                    "resolution_comparison": {
                        "relative_field_difference": 5.0e-10
                    },
                }
            },
        )
        self.assertEqual(envelope.evidence_state, M03EvidenceState.PRODUCED)

    def test_field_contract_rejects_over_policy_residual(self) -> None:
        with self.assertRaisesRegex(ValueError, "exceeds validation policy"):
            build_m03_envelope(
                kind=M03ArtifactKind.RADIAL_ANGULAR_FIELD,
                seed=self.seed,
                cache_identity=self.cache,
                evidence_state=M03EvidenceState.PRODUCED,
                payload={
                    "validation": {
                        "field_equation_residual_abs": 1.0,
                        "boundary_residuals": {
                            "horizon": 2.0e-12,
                            "infinity": 3.0e-12,
                        },
                        "wronskian_relative_drift": 4.0e-12,
                        "resolution_comparison": {
                            "relative_field_difference": 5.0e-10
                        },
                    }
                },
            )

    def test_genealogy_contract_requires_structural_evidence(self) -> None:
        genealogy_cache = M03CacheIdentity.build(
            seed=self.seed,
            artifact_kind=M03ArtifactKind.KAPPA_GENEALOGY,
            equation_version="teukolsky-root-continuation-v1",
            convention_version="kappa-genealogy-v1",
            radial_grid={"not_applicable": True},
            angular_grid={"not_applicable": True},
            normalization_id="root-frequency-only",
            pairing_id="not-applicable",
            backend_revisions={"spectral-catalog": "admitted"},
            precision_tier=semantic_precision_presentation("bigfloat-40"),
            validation_policy={
                "minimum_overlap": 0.99,
                "maximum_exact_node_residual_abs": 1.0e-8,
                "require_branch_resolved": True,
            },
            m02_lineage=None,
        )
        envelope = build_m03_envelope(
            kind=M03ArtifactKind.KAPPA_GENEALOGY,
            seed=self.seed,
            cache_identity=genealogy_cache,
            evidence_state=M03EvidenceState.PRODUCED,
            payload={
                "validation": {
                    "node_count": 4,
                    "edge_count": 4,
                    "overlap_guards": {"minimum": 0.999},
                    "continuation_invariants": {"branch_resolved": True},
                    "fixed_root_validation": {
                        "maximum_residual_abs": 1.0e-11,
                        "maximum_root_movement_abs": 0.0,
                    },
                }
            },
        )
        self.assertEqual(
            envelope.kind,
            M03ArtifactKind.KAPPA_GENEALOGY,
        )

    def test_genealogy_rejects_failed_semantic_evidence(self) -> None:
        genealogy_cache = M03CacheIdentity.build(
            seed=self.seed,
            artifact_kind=M03ArtifactKind.KAPPA_GENEALOGY,
            equation_version="teukolsky-root-continuation-v1",
            convention_version="kappa-genealogy-v1",
            radial_grid={"not_applicable": True},
            angular_grid={"not_applicable": True},
            normalization_id="root-frequency-only",
            pairing_id="not-applicable",
            backend_revisions={"spectral-catalog": "admitted"},
            precision_tier=semantic_precision_presentation("bigfloat-40"),
            validation_policy={
                "minimum_overlap": 0.99,
                "maximum_exact_node_residual_abs": 1.0e-8,
                "require_branch_resolved": True,
            },
            m02_lineage=None,
        )
        for field, replacement in (
            ("overlap_guards", {"minimum": 0.5}),
            ("continuation_invariants", {"branch_resolved": False}),
            (
                "fixed_root_validation",
                {"maximum_residual_abs": 1.0, "maximum_root_movement_abs": 0.0},
            ),
        ):
            with self.subTest(field=field):
                validation = {
                    "node_count": 4,
                    "edge_count": 4,
                    "overlap_guards": {"minimum": 0.999},
                    "continuation_invariants": {"branch_resolved": True},
                    "fixed_root_validation": {
                        "maximum_residual_abs": 1.0e-11,
                        "maximum_root_movement_abs": 0.0,
                    },
                }
                validation[field] = replacement
                with self.assertRaisesRegex(
                    ValueError,
                    "does not satisfy validation policy",
                ):
                    build_m03_envelope(
                        kind=M03ArtifactKind.KAPPA_GENEALOGY,
                        seed=self.seed,
                        cache_identity=genealogy_cache,
                        evidence_state=M03EvidenceState.PRODUCED,
                        payload={"validation": validation},
                    )

    def test_genealogy_rejects_zero_edges(self) -> None:
        genealogy_cache = _cache(
            self.seed,
            pairing_id="not-applicable",
            artifact_kind=M03ArtifactKind.KAPPA_GENEALOGY,
        )
        with self.assertRaisesRegex(ValueError, "node/edge counts are invalid"):
            build_m03_envelope(
                kind=M03ArtifactKind.KAPPA_GENEALOGY,
                seed=self.seed,
                cache_identity=genealogy_cache,
                evidence_state=M03EvidenceState.PRODUCED,
                payload={
                    "validation": {
                        "node_count": 1,
                        "edge_count": 0,
                        "overlap_guards": {"minimum": 1.0},
                        "continuation_invariants": {"branch_resolved": True},
                        "fixed_root_validation": {
                            "maximum_residual_abs": 1.0e-11,
                            "maximum_root_movement_abs": 0.0,
                        },
                    }
                },
            )

    def test_artifact_production_cannot_admit_any_artifact(self) -> None:
        with self.assertRaisesRegex(ValueError, "cannot perform M03 admission"):
            build_m03_envelope(
                kind=M03ArtifactKind.RADIAL_ANGULAR_FIELD,
                seed=self.seed,
                cache_identity=self.cache,
                evidence_state=M03EvidenceState.ADMITTED,
                payload={},
            )


if __name__ == "__main__":
    unittest.main()
