from __future__ import annotations

from copy import deepcopy
from fractions import Fraction
import json
from pathlib import Path
import tempfile
import unittest

from windows_solver.artifacts import (
    ArtifactEnvelope,
    ArtifactStore,
    ArtifactVerificationError,
)
from windows_solver.builtin import default_registry
from windows_solver.contracts import (
    Capability,
    CarrierState,
    EvidenceState,
    ExecutionState,
    ModeKey,
    NumericalState,
    ScientificState,
    StudyRequest,
)
from windows_solver.linear_response import (
    B_PRIME_RELEASE_DOMAIN,
    LINEAR_RESPONSE_DESCRIPTOR,
    LINEAR_RESPONSE_EQUATIONS_ID,
    LINEAR_RESPONSE_OUTPUT_ARTIFACT_TYPE,
    MECHANISM_CONTRACTS,
    baseline_root_reference_id,
    linear_response_leaf_id,
    spin_from_dimensionless_surface_gravity,
    validate_linear_response_admission,
    validate_linear_response_payload,
    validate_linear_response_request,
)
from windows_solver.payload_validation import validate_provider_payload
from windows_solver.providers import ProviderUnavailableError
from windows_solver.release_manifest import load_release_manifest
from tests.fixtures import EXPECTED_KAPPA_SPINS


ROOT = Path(__file__).resolve().parents[1]


def example_request() -> StudyRequest:
    return StudyRequest.from_mapping(
        json.loads(
            (ROOT / "examples" / "linear-response.json").read_text(
                encoding="utf-8"
            )
        )
    )


def complex_value(real: float, imaginary: float, units: str) -> dict[str, object]:
    return {"real": real, "imaginary": imaginary, "units": units}


def spin_identity(spin: float) -> dict[str, object]:
    exact = Fraction(str(float(spin)))
    return {
        "spin": spin,
        "spin_exact": {
            "numerator": exact.numerator,
            "denominator": exact.denominator,
        },
        "spin_binary64_hex": spin.hex(),
    }


def resolved_component(
    mode: ModeKey,
    spin: float,
    selection: object,
    sampling_coordinate: dict[str, object],
    *,
    centre_real: float = -0.0117695667,
    centre_imaginary: float = -0.1158019697,
    disk_radius: float = 2.0e-9,
    numerical_state: str = "ACCEPTED",
) -> dict[str, object]:
    coordinate = selection.coordinate_id
    units = f"Mdeltaomega-per-{coordinate}"
    centre = complex_value(centre_real, centre_imaginary, units)
    return {
        "component_id": linear_response_leaf_id(mode, spin, selection),
        "baseline_root_reference_id": baseline_root_reference_id(mode, spin),
        "mode": mode.to_mapping(),
        **spin_identity(spin),
        "sampling_coordinate": deepcopy(sampling_coordinate),
        "mechanism": selection.to_mapping(),
        "branch_class": "damped",
        "numerical_state": numerical_state,
        "diagnostics": {
            "baseline_residual_abs": 2.7e-12,
            "determinant_derivative_abs": 7.8,
            "signed_root_uncertainty_radius_abs": 1.4e-9,
            "method": "complex-axis-richardson-holdout",
        },
        "result": {
            "centre": centre,
            "local_covariance": {
                "basis": ["real", "imaginary"],
                "matrix": [[1.0e-18, 2.0e-19], [2.0e-19, 2.0e-18]],
                "representation": "real-block-covariance",
                "kind": "component-local-empirical",
            },
            "uncertainty_disk": {
                "centre": deepcopy(centre),
                "radius": disk_radius,
                "units": units,
                "kind": "component-local-empirical-not-interval",
            },
            "reason": None,
        },
    }


def covariance_block(components: list[dict[str, object]]) -> dict[str, object]:
    basis: list[dict[str, object]] = []
    matrix: list[list[float]] = []
    for component in components:
        units = component["result"]["centre"]["units"]
        for quadrature in ("real", "imaginary"):
            basis.append(
                {
                    "component_id": component["component_id"],
                    "quadrature": quadrature,
                    "units": units,
                }
            )
    dimension = len(basis)
    matrix = [[0.0 for _ in range(dimension)] for _ in range(dimension)]
    for index in range(0, dimension, 2):
        matrix[index][index] = 1.0e-18
        matrix[index][index + 1] = 2.0e-19
        matrix[index + 1][index] = 2.0e-19
        matrix[index + 1][index + 1] = 2.0e-18
    return {
        "covariance_id": "all-resolved-components",
        "basis": basis,
        "matrix": matrix,
        "representation": "real-block-covariance-in-declared-basis-units",
        "kind": "component-local-correlated-empirical",
    }


def valid_payload(request: StudyRequest | None = None) -> dict[str, object]:
    request = example_request() if request is None else request
    selections = validate_linear_response_request(request)
    sampling_by_spin = {
        item["spin_binary64_hex"]: item
        for item in request.numerical_policy["linear-response"][
            "sampling_coordinates"
        ]
    }
    roots = [
        {
            "root_reference_id": baseline_root_reference_id(mode, spin),
            "mode": mode.to_mapping(),
            **spin_identity(spin),
            "sampling_coordinate": deepcopy(sampling_by_spin[spin.hex()]),
        }
        for mode in request.modes
        for spin in request.spins
    ]
    components = [
        resolved_component(mode, spin, selection, deepcopy(sampling_by_spin[spin.hex()]))
        for mode in request.modes
        for spin in request.spins
        for selection in selections
    ]
    component_ids = sorted(component["component_id"] for component in components)
    return {
        "schema_version": 1, "quantity": "first-order-complex-qnm-frequency-shift",
        "equations_id": LINEAR_RESPONSE_EQUATIONS_ID,
        "baseline_theory_id": request.theory_id, "baseline_convention_id": request.convention_id,
        "time_dependence": "exp(-i omega t + i m phi)", "frequency_units": "Momega",
        "spin_coordinate": "a_over_M", "horizon_contact_coordinate": "delta-B",
        "lineage": {
            "source_commit": "a" * 40, "source_sha256s": ["b" * 64],
            "runtime_fingerprint": LINEAR_RESPONSE_DESCRIPTOR.runtime_fingerprint,
            "numerical_policy_fingerprint": LINEAR_RESPONSE_DESCRIPTOR.numerical_policy_fingerprint,
            "evidence_ceiling": "component-local-empirical-not-formal-enclosure",
        },
        "baseline_root_references": roots, "response_components": components,
        "covariance_blocks": [covariance_block(components)], "projective_comparisons": [],
        "completeness": {
            "required_leaf_count": len(component_ids), "produced_leaf_count": len(component_ids),
            "unresolved_leaf_count": 0, "missing_leaf_count": 0,
            "required_leaf_ids": component_ids, "produced_leaf_ids": component_ids,
            "unresolved_leaf_ids": [], "missing_leaf_ids": [],
        },
    }


def mechanism_mapping(mechanism_id: str) -> dict[str, object]:
    contract = MECHANISM_CONTRACTS[mechanism_id]
    return {
        "mechanism_id": contract.mechanism_id,
        "coordinate_id": contract.coordinate_id,
        "theory_id": contract.theory_id,
        "convention_id": contract.convention_id,
        "response_quantity_id": contract.response_quantity_id,
        "parameters": {name: values[0] for name, values in contract.parameter_values},
    }


def b_prime_request() -> StudyRequest:
    domain = B_PRIME_RELEASE_DOMAIN
    coordinate_by_spin: dict[str, dict[str, object]] = {}
    mode_by_identity: dict[tuple[int, int, int], dict[str, object]] = {}
    role_scoped_leaves: list[dict[str, object]] = []
    mechanism_ids: set[str] = set()
    for leaf in domain.production_leaves:
        mode = ModeKey(
            s=-2, ell=leaf.mode[0], m=leaf.mode[1], n=leaf.mode[2],
            branch="schwarzschild-overtone-continuation", polarization="gravitational",
        )
        mode_by_identity[leaf.mode] = mode.to_mapping()
        coordinate = {
            "coordinate_id": "a_over_M" if leaf.spin_role == "direct" else "M-kappa",
            "coordinate_value": float(leaf.coordinate),
            "coordinate_exact": {"numerator": leaf.coordinate.numerator, "denominator": leaf.coordinate.denominator},
            **spin_identity(leaf.spin),
            "transformation_id": (
                "identity-a-over-M" if leaf.spin_role == "direct"
                else "kerr-prograde-spin-from-dimensionless-surface-gravity"
            ),
        }
        coordinate_by_spin[leaf.spin.hex()] = coordinate
        mechanism_ids.add(leaf.mechanism_id)
        role_scoped_leaves.append({
            "role": leaf.role,
            "mode": mode.to_mapping(),
            "sampling_coordinate": deepcopy(coordinate),
            "mechanism": mechanism_mapping(leaf.mechanism_id),
        })
    return StudyRequest.from_mapping({
        "schema_version": 1,
        "target": "linear-response",
        "theory_id": "general-relativity",
        "convention_id": "kerr-mass-normalized-outgoing",
        "modes": list(mode_by_identity.values()),
        "spins": [coordinate["spin"] for coordinate in coordinate_by_spin.values()],
        "evidence_profile": "research",
        "numerical_policy": {"linear-response": {
            "sampling_coordinates": list(coordinate_by_spin.values()),
            "mechanisms": [mechanism_mapping(item) for item in sorted(mechanism_ids)],
            "role_scoped_leaves": role_scoped_leaves,
        }},
    })


def b_prime_payload(request: StudyRequest) -> dict[str, object]:
    policy = request.numerical_policy["linear-response"]
    leaves = policy["role_scoped_leaves"]
    selections_by_mapping = {
        json.dumps(item.to_mapping(), sort_keys=True): item
        for item in validate_linear_response_request(request)
    }
    roots: dict[str, dict[str, object]] = {}
    components: list[dict[str, object]] = []
    sentinel_inputs = {
        ((2, 2, 0), "horizon-admittance"),
        ((2, 2, 2), "exterior-throat-kappa"),
    }
    for leaf in leaves:
        mode = ModeKey.from_mapping(leaf["mode"])
        coordinate = leaf["sampling_coordinate"]
        spin = coordinate["spin"]
        selection = selections_by_mapping[json.dumps(leaf["mechanism"], sort_keys=True)]
        component = resolved_component(mode, spin, selection, deepcopy(coordinate))
        component["numerical_state"] = "UNRESOLVED"
        component["result"] = {
            "centre": None, "local_covariance": None, "uncertainty_disk": None,
            "reason": "contract-only precision evidence",
        }
        if leaf["role"] == "deep":
            sentinel = ((mode.ell, mode.m, mode.n), selection.mechanism_id) in sentinel_inputs
            component["diagnostics"]["precision_evidence"] = {
                "trigger_ids": [] if sentinel else ["fewer-than-ten-predicted-reliable-decimal-digits"],
                "promoted": True,
                "precision_digits": 80,
                "repeat_precision_digits": None,
                "self_refinement_enclosed": True,
                "discrepancy_enclosed": True,
                "sentinel": sentinel,
                "sentinel_comparison": (
                    {
                        "binary64_to_80_discrepancy_abs": 0.0,
                        "trigger_threshold_abs": 1.0e-9,
                        "trigger_policy_false_negative": False,
                    }
                    if sentinel
                    else None
                ),
            }
        root_id = baseline_root_reference_id(mode, spin)
        roots[root_id] = {
            "root_reference_id": root_id, "mode": mode.to_mapping(),
            **spin_identity(spin), "sampling_coordinate": deepcopy(coordinate),
        }
        components.append(component)
    component_ids = sorted(item["component_id"] for item in components)
    return {
        "schema_version": 1,
        "quantity": "first-order-complex-qnm-frequency-shift",
        "equations_id": LINEAR_RESPONSE_EQUATIONS_ID,
        "baseline_theory_id": request.theory_id,
        "baseline_convention_id": request.convention_id,
        "time_dependence": "exp(-i omega t + i m phi)",
        "frequency_units": "Momega", "spin_coordinate": "a_over_M",
        "horizon_contact_coordinate": "delta-B",
        "lineage": {
            "source_commit": "a" * 40, "source_sha256s": ["b" * 64],
            "runtime_fingerprint": LINEAR_RESPONSE_DESCRIPTOR.runtime_fingerprint,
            "numerical_policy_fingerprint": LINEAR_RESPONSE_DESCRIPTOR.numerical_policy_fingerprint,
            "evidence_ceiling": "component-local-empirical-not-formal-enclosure",
        },
        "baseline_root_references": list(roots.values()),
        "response_components": components, "covariance_blocks": [],
        "projective_comparisons": [],
        "completeness": {
            "required_leaf_count": 553, "produced_leaf_count": 553,
            "unresolved_leaf_count": 553, "missing_leaf_count": 0,
            "required_leaf_ids": component_ids, "produced_leaf_ids": component_ids,
            "unresolved_leaf_ids": component_ids, "missing_leaf_ids": [],
        },
    }
def component_for(
    payload: dict[str, object],
    *,
    ell: int,
    mechanism_id: str,
) -> dict[str, object]:
    return next(
        component
        for component in payload["response_components"]
        if component["mode"]["ell"] == ell
        and component["mechanism"]["mechanism_id"] == mechanism_id
    )


class LinearResponseContractTests(unittest.TestCase):
    def test_b_prime_role_scoped_request_admits_exact_complete_domain(self) -> None:
        request = b_prime_request()
        payload = b_prime_payload(request)

        validate_linear_response_admission(
            request, LINEAR_RESPONSE_DESCRIPTOR.to_mapping(), payload
        )

        leaked = request.to_mapping()
        leaked["numerical_policy"]["linear-response"]["role_scoped_leaves"][0]["role"] = "control"
        with self.assertRaisesRegex(ValueError, "role-scoped leaves"):
            validate_linear_response_request(StudyRequest.from_mapping(leaked))

        omitted = request.to_mapping()
        omitted["numerical_policy"]["linear-response"]["role_scoped_leaves"].pop()
        with self.assertRaisesRegex(ValueError, "role-scoped leaves"):
            validate_linear_response_request(StudyRequest.from_mapping(omitted))

        added = request.to_mapping()
        off_domain = deepcopy(
            added["numerical_policy"]["linear-response"]["role_scoped_leaves"][0]
        )
        self.assertEqual(off_domain["role"], "primary")
        off_domain["role"] = "control"
        added["numerical_policy"]["linear-response"]["role_scoped_leaves"].append(
            off_domain
        )
        with self.assertRaisesRegex(ValueError, "must exactly match"):
            validate_linear_response_request(StudyRequest.from_mapping(added))

        deep_component = next(
            component
            for component in payload["response_components"]
            if component["sampling_coordinate"]["coordinate_id"] == "M-kappa"
        )
        deep_component["diagnostics"]["precision_evidence"] = {"forged": True}
        with self.assertRaisesRegex(ValueError, "precision evidence"):
            validate_linear_response_payload(
                request, LINEAR_RESPONSE_DESCRIPTOR.to_mapping(), payload
            )

        payload = b_prime_payload(request)
        sentinel = next(
            component
            for component in payload["response_components"]
            if component["mode"]["ell"] == 2
            and component["mode"]["m"] == 2
            and component["mode"]["n"] == 0
            and component["mechanism"]["mechanism_id"] == "horizon-admittance"
            and component["sampling_coordinate"]["coordinate_id"] == "M-kappa"
        )
        sentinel["diagnostics"]["precision_evidence"]["sentinel"] = False
        with self.assertRaisesRegex(ValueError, "sentinel identity"):
            validate_linear_response_payload(
                request, LINEAR_RESPONSE_DESCRIPTOR.to_mapping(), payload
            )

    def test_b_prime_deep_precision_ladder_rejects_frozen_failures(self) -> None:
        request = b_prime_request()

        def component_with_evidence(
            payload: dict[str, object], *, sentinel: bool
        ) -> dict[str, object]:
            return next(
                component
                for component in payload["response_components"]
                if "precision_evidence" in component["diagnostics"]
                and component["diagnostics"]["precision_evidence"]["sentinel"]
                is sentinel
            )

        payload = b_prime_payload(request)
        evidence = component_with_evidence(payload, sentinel=True)["diagnostics"][
            "precision_evidence"
        ]
        evidence["sentinel_comparison"] = {
            "binary64_to_80_discrepancy_abs": 2.0e-9,
            "trigger_threshold_abs": 1.0e-9,
            "trigger_policy_false_negative": True,
        }
        with self.assertRaisesRegex(ValueError, "sentinel false negative"):
            validate_linear_response_admission(
                request, LINEAR_RESPONSE_DESCRIPTOR.to_mapping(), payload
            )

        payload = b_prime_payload(request)
        evidence = component_with_evidence(payload, sentinel=True)["diagnostics"][
            "precision_evidence"
        ]
        evidence["sentinel_comparison"]["binary64_to_80_discrepancy_abs"] = 2.0e-9
        with self.assertRaisesRegex(ValueError, "false-negative outcome is invalid"):
            validate_linear_response_payload(
                request, LINEAR_RESPONSE_DESCRIPTOR.to_mapping(), payload
            )

        payload = b_prime_payload(request)
        evidence = component_with_evidence(payload, sentinel=False)["diagnostics"][
            "precision_evidence"
        ]
        evidence["promoted"] = False
        with self.assertRaisesRegex(ValueError, "promotion rule"):
            validate_linear_response_payload(
                request, LINEAR_RESPONSE_DESCRIPTOR.to_mapping(), payload
            )

        payload = b_prime_payload(request)
        evidence = component_with_evidence(payload, sentinel=False)["diagnostics"][
            "precision_evidence"
        ]
        evidence["precision_digits"] = 64
        with self.assertRaisesRegex(ValueError, "precision digits"):
            validate_linear_response_payload(
                request, LINEAR_RESPONSE_DESCRIPTOR.to_mapping(), payload
            )

        payload = b_prime_payload(request)
        evidence = component_with_evidence(payload, sentinel=False)["diagnostics"][
            "precision_evidence"
        ]
        evidence["self_refinement_enclosed"] = False
        with self.assertRaisesRegex(ValueError, "repeat must run at 120"):
            validate_linear_response_payload(
                request, LINEAR_RESPONSE_DESCRIPTOR.to_mapping(), payload
            )

        payload = b_prime_payload(request)
        component = component_with_evidence(payload, sentinel=False)
        component["numerical_state"] = "ACCEPTED"
        component["diagnostics"]["precision_evidence"][
            "discrepancy_enclosed"
        ] = False
        with self.assertRaisesRegex(ValueError, "enclosed 80/120 discrepancy"):
            validate_linear_response_payload(
                request, LINEAR_RESPONSE_DESCRIPTOR.to_mapping(), payload
            )

    def test_b_prime_precision_and_completeness_contract_is_frozen_before_production(
        self,
    ) -> None:
        domain = B_PRIME_RELEASE_DOMAIN
        self.assertEqual(
            tuple(spin.hex() for spin in (
                spin_from_dimensionless_surface_gravity(value)
                for value in (0.01, 0.005, 0.002, 0.001)
            )),
            (
                "0x1.ffe4b3ad56fa5p-1", "0x1.fff9502b91917p-1",
                "0x1.fffef1672c027p-1", "0x1.ffffbc9f2ff3bp-1",
            ),
        )
        self.assertEqual(len(domain.fixed_precision_sentinel_leaf_ids), 8)
        self.assertEqual(len(domain.precision_promotion_gates), 4)
        manifest_contract = load_release_manifest().to_mapping()["release_domain"][
            "linear_response"
        ]["b_prime"]
        self.assertEqual(manifest_contract["leaf_counts"], {"primary": 441, "control": 48, "deep": 64, "total": 553})
        self.assertEqual(manifest_contract["selector_counts"], {"primary": 63, "control": 8, "deep": 16, "total": 87})
        self.assertEqual(manifest_contract["missing_selector_counts"], {"primary": 28, "control": 0, "deep": 16, "total": 44})
        self.assertEqual(manifest_contract["projective_counts"], {"primary": 162, "deep": 12, "total": 174})

        with self.assertRaisesRegex(ValueError, "explicit role-scoped leaves"):
            validate_linear_response_admission(
                example_request(),
                LINEAR_RESPONSE_DESCRIPTOR.to_mapping(),
                valid_payload(),
            )

    def test_descriptor_is_defined_but_not_admitted(self) -> None:
        self.assertEqual(
            LINEAR_RESPONSE_DESCRIPTOR.capability,
            Capability.LINEAR_RESPONSE,
        )
        self.assertEqual(
            LINEAR_RESPONSE_DESCRIPTOR.output_artifact_type,
            LINEAR_RESPONSE_OUTPUT_ARTIFACT_TYPE,
        )
        self.assertFalse(LINEAR_RESPONSE_DESCRIPTOR.available)
        with self.assertRaises(ProviderUnavailableError):
            default_registry().resolve(Capability.LINEAR_RESPONSE)

    def test_mechanism_contracts_exactly_cover_the_frozen_manifest(self) -> None:
        manifest = load_release_manifest().to_mapping()
        expected = set(
            manifest["release_domain"]["linear_response"]["mechanisms"]
        )
        self.assertEqual(set(MECHANISM_CONTRACTS), expected)
        horizon = MECHANISM_CONTRACTS["horizon-admittance"]
        self.assertEqual(horizon.coordinate_id, "unit-complex-deltaB")
        self.assertEqual(horizon.response_quantity_id, "h_B")

    def test_example_keeps_kerr_baseline_and_native_horizon_selection(self) -> None:
        request = example_request()
        selections = validate_linear_response_request(request)

        self.assertEqual(request.theory_id, "general-relativity")
        self.assertEqual(request.convention_id, "kerr-mass-normalized-outgoing")
        self.assertEqual(len(selections), 1)
        self.assertEqual(selections[0].mechanism_id, "horizon-admittance")
        self.assertEqual(selections[0].coordinate_id, "unit-complex-deltaB")
        self.assertEqual(selections[0].response_quantity_id, "h_B")

    def test_sampling_contract_covers_direct_spin_and_surface_gravity_axes(
        self,
    ) -> None:
        manifest = load_release_manifest().to_mapping()["release_domain"][
            "linear_response"
        ]
        direct_values = set(manifest["direct_spins"])
        surface_gravities = set(manifest["surface_gravity_values"])
        self.assertEqual(
            direct_values,
            {0.95, 0.97, 0.98, 0.99, 0.995, 0.997, 0.999, 0.9995, 0.9999},
        )
        self.assertEqual(surface_gravities, {0.01, 0.005, 0.002, 0.001})

        for kappa_exact, (expected_spin, expected_hex) in (
            EXPECTED_KAPPA_SPINS.items()
        ):
            with self.subTest(kappa=kappa_exact):
                spin = spin_from_dimensionless_surface_gravity(
                    float(kappa_exact)
                )
                self.assertEqual(spin, expected_spin)
                self.assertEqual(spin.hex(), expected_hex)

        self.assertEqual(spin_from_dimensionless_surface_gravity(0.25), 0.0)
        with self.assertRaisesRegex(ValueError, "0.25"):
            spin_from_dimensionless_surface_gravity(0.2500000001)

        kappa = 0.01
        spin = spin_from_dimensionless_surface_gravity(kappa)
        exact_spin = Fraction(str(spin))
        mapping = example_request().to_mapping()
        mapping["spins"] = [spin]
        mapping["numerical_policy"]["linear-response"][
            "sampling_coordinates"
        ] = [
            {
                "coordinate_id": "M-kappa",
                "coordinate_value": kappa,
                "coordinate_exact": {"numerator": 1, "denominator": 100},
                "spin": spin,
                "spin_exact": {
                    "numerator": exact_spin.numerator,
                    "denominator": exact_spin.denominator,
                },
                "spin_binary64_hex": spin.hex(),
                "transformation_id": (
                    "kerr-prograde-spin-from-dimensionless-surface-gravity"
                ),
            }
        ]
        validate_linear_response_request(StudyRequest.from_mapping(mapping))

        mapping["numerical_policy"]["linear-response"][
            "sampling_coordinates"
        ][0]["coordinate_value"] = 0.02
        mapping["numerical_policy"]["linear-response"][
            "sampling_coordinates"
        ][0]["coordinate_exact"] = {"numerator": 1, "denominator": 50}
        with self.assertRaisesRegex(ValueError, "outside the frozen"):
            validate_linear_response_request(StudyRequest.from_mapping(mapping))

    def test_request_rejects_reflectivity_unknown_mechanism_and_nested_fields(
        self,
    ) -> None:
        mapping = example_request().to_mapping()
        mechanism = mapping["numerical_policy"]["linear-response"]["mechanisms"][0]
        mechanism["coordinate_id"] = "unit-complex-reflectivity-R"
        with self.assertRaisesRegex(ValueError, "coordinate"):
            validate_linear_response_request(StudyRequest.from_mapping(mapping))

        mechanism["mechanism_id"] = "unknown-mechanism"
        with self.assertRaisesRegex(ValueError, "unsupported mechanism"):
            validate_linear_response_request(StudyRequest.from_mapping(mapping))

        mapping = example_request().to_mapping()
        mechanism = mapping["numerical_policy"]["linear-response"]["mechanisms"][0]
        mechanism["parameters"]["unknown"] = "value"
        with self.assertRaisesRegex(ValueError, "unknown horizon-admittance parameters"):
            validate_linear_response_request(StudyRequest.from_mapping(mapping))

    def test_request_rejects_duplicates_and_non_kerr_baseline(self) -> None:
        mapping = example_request().to_mapping()
        mechanisms = mapping["numerical_policy"]["linear-response"]["mechanisms"]
        mechanisms.append(deepcopy(mechanisms[0]))
        with self.assertRaisesRegex(ValueError, "duplicate"):
            validate_linear_response_request(StudyRequest.from_mapping(mapping))

        mapping = example_request().to_mapping()
        mapping["theory_id"] = "parity-even-cubic-higher-curvature-eft"
        mapping["convention_id"] = "cubic-even-220-reference"
        with self.assertRaisesRegex(ValueError, "baseline theory"):
            validate_linear_response_request(StudyRequest.from_mapping(mapping))

    def test_cubic_polarizations_are_distinct_local_selections(self) -> None:
        mapping = example_request().to_mapping()
        mapping["numerical_policy"]["linear-response"]["mechanisms"] = [
            {
                "mechanism_id": "cubic-eft",
                "coordinate_id": "unit-dimensionless-cubic-coupling",
                "theory_id": "parity-even-cubic-higher-curvature-eft",
                "convention_id": "cubic-even-220-reference",
                "response_quantity_id": "delta-omega-cubic",
                "parameters": {"polarization": "plus"},
            },
            {
                "mechanism_id": "cubic-eft",
                "coordinate_id": "unit-dimensionless-cubic-coupling",
                "theory_id": "parity-even-cubic-higher-curvature-eft",
                "convention_id": "cubic-even-220-reference",
                "response_quantity_id": "delta-omega-cubic",
                "parameters": {"polarization": "minus"},
            },
        ]
        selections = validate_linear_response_request(StudyRequest.from_mapping(mapping))
        self.assertEqual(len(selections), 2)
        self.assertNotEqual(selections[0], selections[1])

    def test_valid_correlated_payload_passes_direct_and_dispatch_validation(self) -> None:
        request = example_request()
        payload = valid_payload(request)
        provider = LINEAR_RESPONSE_DESCRIPTOR.to_mapping()

        validate_linear_response_payload(request, provider, payload)
        validate_provider_payload(
            Capability.LINEAR_RESPONSE,
            LINEAR_RESPONSE_OUTPUT_ARTIFACT_TYPE,
            provider,
            request,
            payload,
        )

    def test_stored_linear_response_payload_revalidates_after_freeze_and_load(self) -> None:
        request = example_request()
        provider = LINEAR_RESPONSE_DESCRIPTOR.to_mapping()
        envelope = ArtifactEnvelope(
            schema_version=1,
            artifact_type=LINEAR_RESPONSE_OUTPUT_ARTIFACT_TYPE,
            capability=Capability.LINEAR_RESPONSE,
            provider=provider,
            request=request.to_mapping(),
            upstream_artifact_ids=(),
            payload=valid_payload(request),
            evidence=EvidenceState(
                carrier=CarrierState.VALID,
                execution=ExecutionState.SUCCEEDED,
                numerical=NumericalState.ACCEPTED,
                scientific=ScientificState.NOT_EVALUATED,
            ),
        )
        with tempfile.TemporaryDirectory() as temporary:
            store = ArtifactStore(temporary)
            loaded = store.load_artifact(store.put_artifact(envelope))
            validate_provider_payload(
                loaded.capability,
                loaded.artifact_type,
                loaded.provider,
                request,
                loaded.payload,
            )

    def test_dispatch_rejects_wrong_provider_and_output_type(self) -> None:
        request = example_request()
        payload = valid_payload(request)
        provider = LINEAR_RESPONSE_DESCRIPTOR.to_mapping()
        provider["provider_id"] = "wrong-provider"
        with self.assertRaisesRegex(ArtifactVerificationError, "unsupported"):
            validate_provider_payload(
                Capability.LINEAR_RESPONSE,
                LINEAR_RESPONSE_OUTPUT_ARTIFACT_TYPE,
                provider,
                request,
                payload,
            )

    def test_payload_rejects_a_self_consistent_forged_descriptor(self) -> None:
        request = example_request()
        payload = valid_payload(request)
        provider = LINEAR_RESPONSE_DESCRIPTOR.to_mapping()
        provider["numerical_policy_fingerprint"] = "forged-policy"
        payload["lineage"]["numerical_policy_fingerprint"] = "forged-policy"

        with self.assertRaisesRegex(ValueError, "provider contract"):
            validate_linear_response_payload(request, provider, payload)
        with self.assertRaisesRegex(ArtifactVerificationError, "output type"):
            validate_provider_payload(
                Capability.LINEAR_RESPONSE,
                "wrong-output",
                LINEAR_RESPONSE_DESCRIPTOR.to_mapping(),
                request,
                payload,
            )

    def test_payload_rejects_unknown_layers_bool_numbers_and_nonfinite_values(
        self,
    ) -> None:
        request = example_request()
        provider = LINEAR_RESPONSE_DESCRIPTOR.to_mapping()
        payload = valid_payload(request)
        payload["response_matrix"] = []
        with self.assertRaisesRegex(ValueError, "unknown linear-response payload"):
            validate_linear_response_payload(request, provider, payload)

        payload = valid_payload(request)
        payload["response_components"][0]["diagnostics"][
            "baseline_residual_abs"
        ] = True
        with self.assertRaisesRegex(ValueError, "finite number"):
            validate_linear_response_payload(request, provider, payload)

        payload = valid_payload(request)
        payload["response_components"][0]["result"]["centre"]["real"] = float(
            "nan"
        )
        with self.assertRaisesRegex(ValueError, "finite"):
            validate_linear_response_payload(request, provider, payload)

    def test_branch_class_type_error_uses_declared_value_error_boundary(self) -> None:
        request = example_request()
        payload = valid_payload(request)
        payload["response_components"][0]["branch_class"] = ["damped"]
        with self.assertRaisesRegex(ValueError, "branch_class"):
            validate_linear_response_payload(
                request, LINEAR_RESPONSE_DESCRIPTOR.to_mapping(), payload
            )

    def test_spin_identity_must_match_spectral_coordinate_representation(self) -> None:
        request = example_request()
        provider = LINEAR_RESPONSE_DESCRIPTOR.to_mapping()
        payload = valid_payload(request)
        payload["response_components"][0]["spin_binary64_hex"] = "0x0.0p+0"
        with self.assertRaisesRegex(ValueError, "binary64"):
            validate_linear_response_payload(request, provider, payload)

        payload = valid_payload(request)
        payload["baseline_root_references"][0]["spin_exact"]["denominator"] = 21
        with self.assertRaisesRegex(ValueError, "exact spin"):
            validate_linear_response_payload(request, provider, payload)

    def test_covariance_blocks_are_correlated_complete_symmetric_and_psd(self) -> None:
        mapping = example_request().to_mapping()
        mapping["modes"].append(
            {
                "s": -2,
                "ell": 3,
                "m": 3,
                "n": 0,
                "branch": "schwarzschild-overtone-continuation",
                "polarization": "gravitational",
            }
        )
        request = StudyRequest.from_mapping(mapping)
        payload = valid_payload(request)
        matrix = payload["covariance_blocks"][0]["matrix"]
        matrix[0][2] = 1.0e-20
        matrix[2][0] = 1.0e-20
        validate_linear_response_payload(
            request,
            LINEAR_RESPONSE_DESCRIPTOR.to_mapping(),
            payload,
        )

        payload["covariance_blocks"][0]["basis"].pop()
        with self.assertRaisesRegex(ValueError, "dimension"):
            validate_linear_response_payload(
                request,
                LINEAR_RESPONSE_DESCRIPTOR.to_mapping(),
                payload,
            )

        payload = valid_payload(request)
        payload["covariance_blocks"][0]["matrix"][0][1] = 9.0e-19
        with self.assertRaisesRegex(ValueError, "symmetric"):
            validate_linear_response_payload(
                request,
                LINEAR_RESPONSE_DESCRIPTOR.to_mapping(),
                payload,
            )

        payload = valid_payload(request)
        payload["covariance_blocks"][0]["matrix"][0][0] = -1.0
        with self.assertRaisesRegex(ValueError, "positive semidefinite"):
            validate_linear_response_payload(
                request,
                LINEAR_RESPONSE_DESCRIPTOR.to_mapping(),
                payload,
            )

        payload = valid_payload(request)
        component = payload["response_components"][0]
        component["result"]["local_covariance"]["matrix"] = [
            [1.0e20, 0.0],
            [0.0, -1.0],
        ]
        block_matrix = payload["covariance_blocks"][0]["matrix"]
        block_matrix[0][0] = 1.0e20
        block_matrix[0][1] = 0.0
        block_matrix[1][0] = 0.0
        block_matrix[1][1] = -1.0
        with self.assertRaisesRegex(ValueError, "positive semidefinite"):
            validate_linear_response_payload(
                request,
                LINEAR_RESPONSE_DESCRIPTOR.to_mapping(),
                payload,
            )

    def test_rank_deficient_outer_product_covariance_is_valid_psd(self) -> None:
        request = example_request()
        payload = valid_payload(request)
        vector = (-3.1812657685587836e-10, 5.7100781472823224e-11)
        matrix = [
            [vector[row] * vector[column] for column in range(2)]
            for row in range(2)
        ]
        payload["response_components"][0]["result"]["local_covariance"][
            "matrix"
        ] = deepcopy(matrix)
        payload["covariance_blocks"][0]["matrix"] = deepcopy(matrix)
        validate_linear_response_payload(
            request, LINEAR_RESPONSE_DESCRIPTOR.to_mapping(), payload
        )

    def test_covariance_blocks_allow_overlapping_reduction_gram_bases(self) -> None:
        request = example_request()
        payload = valid_payload(request)
        overlapping = deepcopy(payload["covariance_blocks"][0])
        overlapping["covariance_id"] = "overlapping-projective-row-gram"
        payload["covariance_blocks"].append(overlapping)
        validate_linear_response_payload(
            request, LINEAR_RESPONSE_DESCRIPTOR.to_mapping(), payload
        )

    def test_nonfinite_cholesky_intermediate_rejects_extreme_indefinite_matrix(
        self,
    ) -> None:
        request = example_request()
        payload = valid_payload(request)
        matrix = [[1.0e-308, 1.0e308], [1.0e308, 1.0]]
        payload["response_components"][0]["result"]["local_covariance"][
            "matrix"
        ] = deepcopy(matrix)
        payload["covariance_blocks"][0]["matrix"] = deepcopy(matrix)
        with self.assertRaisesRegex(ValueError, "positive semidefinite"):
            validate_linear_response_payload(
                request, LINEAR_RESPONSE_DESCRIPTOR.to_mapping(), payload
            )

    def test_payload_rejects_disk_not_centred_on_response(self) -> None:
        request = example_request()
        payload = valid_payload(request)
        payload["response_components"][0]["result"]["uncertainty_disk"][
            "centre"
        ]["real"] += 1.0e-4
        with self.assertRaisesRegex(ValueError, "disk centre"):
            validate_linear_response_payload(
                request,
                LINEAR_RESPONSE_DESCRIPTOR.to_mapping(),
                payload,
            )

    def test_unresolved_result_has_attempt_evidence_and_no_fabricated_response(
        self,
    ) -> None:
        request = example_request()
        payload = valid_payload(request)
        component = payload["response_components"][0]
        component["numerical_state"] = "UNRESOLVED"
        component["result"] = {
            "centre": None,
            "local_covariance": None,
            "uncertainty_disk": None,
            "reason": "simple-root derivative is below the declared floor",
        }
        leaf_id = component["component_id"]
        payload["covariance_blocks"] = []
        payload["completeness"]["unresolved_leaf_count"] = 1
        payload["completeness"]["unresolved_leaf_ids"] = [leaf_id]
        validate_linear_response_payload(
            request,
            LINEAR_RESPONSE_DESCRIPTOR.to_mapping(),
            payload,
        )

        component["result"]["centre"] = complex_value(
            1.0,
            0.0,
            "Mdeltaomega-per-unit-complex-deltaB",
        )
        with self.assertRaisesRegex(ValueError, "unresolved result"):
            validate_linear_response_payload(
                request,
                LINEAR_RESPONSE_DESCRIPTOR.to_mapping(),
                payload,
            )

    def test_rejected_component_is_listed_as_unresolved_and_not_admissible(self) -> None:
        request = example_request()
        payload = valid_payload(request)
        component = payload["response_components"][0]
        component["numerical_state"] = "REJECTED"
        component["result"] = {
            "centre": None,
            "local_covariance": None,
            "uncertainty_disk": None,
            "reason": "numerical acceptance gate rejected the attempted result",
        }
        leaf_id = component["component_id"]
        payload["covariance_blocks"] = []
        payload["completeness"]["unresolved_leaf_count"] = 1
        payload["completeness"]["unresolved_leaf_ids"] = [leaf_id]
        validate_linear_response_payload(
            request, LINEAR_RESPONSE_DESCRIPTOR.to_mapping(), payload
        )
        with self.assertRaisesRegex(ValueError, "ACCEPTED or UNRESOLVED"):
            validate_linear_response_admission(
                request, LINEAR_RESPONSE_DESCRIPTOR.to_mapping(), payload
            )

        payload["completeness"]["unresolved_leaf_count"] = 0
        payload["completeness"]["unresolved_leaf_ids"] = []
        with self.assertRaisesRegex(ValueError, "unresolved leaf IDs"):
            validate_linear_response_payload(
                request, LINEAR_RESPONSE_DESCRIPTOR.to_mapping(), payload
            )

    def test_missing_computation_is_distinct_and_blocks_admission(self) -> None:
        request = example_request()
        payload = valid_payload(request)
        leaf_id = payload["response_components"][0]["component_id"]
        payload["response_components"] = []
        payload["covariance_blocks"] = []
        payload["completeness"].update(
            {
                "produced_leaf_count": 0,
                "unresolved_leaf_count": 0,
                "missing_leaf_count": 1,
                "produced_leaf_ids": [],
                "unresolved_leaf_ids": [],
                "missing_leaf_ids": [leaf_id],
            }
        )
        validate_linear_response_payload(
            request,
            LINEAR_RESPONSE_DESCRIPTOR.to_mapping(),
            payload,
        )
        with self.assertRaisesRegex(ValueError, "missing leaves"):
            validate_linear_response_admission(
                request,
                LINEAR_RESPONSE_DESCRIPTOR.to_mapping(),
                payload,
            )

        payload["completeness"]["unresolved_leaf_count"] = 1
        payload["completeness"]["unresolved_leaf_ids"] = [leaf_id]
        with self.assertRaisesRegex(ValueError, "missing and unresolved"):
            validate_linear_response_payload(
                request,
                LINEAR_RESPONSE_DESCRIPTOR.to_mapping(),
                payload,
            )

    def test_converged_component_is_structural_but_not_admitted(self) -> None:
        request = example_request()
        payload = valid_payload(request)
        payload["response_components"][0]["numerical_state"] = "CONVERGED"
        validate_linear_response_payload(
            request,
            LINEAR_RESPONSE_DESCRIPTOR.to_mapping(),
            payload,
        )
        with self.assertRaisesRegex(ValueError, "must be ACCEPTED"):
            validate_linear_response_admission(
                request,
                LINEAR_RESPONSE_DESCRIPTOR.to_mapping(),
                payload,
            )

    def test_projective_comparison_requires_aligned_multimode_vectors(self) -> None:
        mapping = example_request().to_mapping()
        mapping["modes"].append(
            {
                "s": -2,
                "ell": 3,
                "m": 3,
                "n": 0,
                "branch": "schwarzschild-overtone-continuation",
                "polarization": "gravitational",
            }
        )
        mapping["numerical_policy"]["linear-response"]["mechanisms"].append(
            {
                "mechanism_id": "exterior-fixed-r3",
                "coordinate_id": "unit-complex-profile-amplitude",
                "theory_id": "general-relativity",
                "convention_id": "kerr-mass-normalized-outgoing",
                "response_quantity_id": "e_F",
                "parameters": {
                    "profile_id": "fixed-r3",
                    "centre_rule": "r_over_M=3",
                    "half_width_rule": "0.45M",
                },
            }
        )
        request = StudyRequest.from_mapping(mapping)
        payload = valid_payload(request)
        horizon_220 = component_for(payload, ell=2, mechanism_id="horizon-admittance")
        horizon_330 = component_for(payload, ell=3, mechanism_id="horizon-admittance")
        fixed_220 = component_for(payload, ell=2, mechanism_id="exterior-fixed-r3")
        fixed_330 = component_for(payload, ell=3, mechanism_id="exterior-fixed-r3")
        payload["projective_comparisons"] = [
            {
                "comparison_id": "horizon-versus-fixed-r3",
                "mode_order": [horizon_220["mode"], horizon_330["mode"]],
                "left_component_ids": [
                    horizon_220["component_id"],
                    horizon_330["component_id"],
                ],
                "right_component_ids": [
                    fixed_220["component_id"],
                    fixed_330["component_id"],
                ],
                "calibration_mode": horizon_220["mode"],
                "calibration_numerator_component_id": horizon_220["component_id"],
                "calibration_denominator_component_id": fixed_220["component_id"],
                "covariance_id": "all-resolved-components",
                "empirical_gram_id": "empirical-error-gram-" + "0" * 64,
                "nominal_angle_radians": 0.8,
                "bounded_angle_interval_radians": [0.7, 0.9],
                "calibration_disk_contains_zero": False,
                "projective_outcome": "SEPARATED",
                "scientific_state": "CONTRADICTED",
                "reason": "bounded component-local comparison",
            }
        ]
        validate_linear_response_payload(
            request,
            LINEAR_RESPONSE_DESCRIPTOR.to_mapping(),
            payload,
        )

        payload["projective_comparisons"][0]["left_component_ids"] = [
            horizon_220["component_id"]
        ]
        with self.assertRaisesRegex(ValueError, "multimode"):
            validate_linear_response_payload(
                request,
                LINEAR_RESPONSE_DESCRIPTOR.to_mapping(),
                payload,
            )

    def test_zero_containing_calibration_disk_forces_unbounded_unresolved_result(
        self,
    ) -> None:
        mapping = example_request().to_mapping()
        mapping["modes"].append(
            {
                "s": -2,
                "ell": 3,
                "m": 3,
                "n": 0,
                "branch": "schwarzschild-overtone-continuation",
                "polarization": "gravitational",
            }
        )
        mapping["numerical_policy"]["linear-response"]["mechanisms"].append(
            {
                "mechanism_id": "exterior-fixed-r3",
                "coordinate_id": "unit-complex-profile-amplitude",
                "theory_id": "general-relativity",
                "convention_id": "kerr-mass-normalized-outgoing",
                "response_quantity_id": "e_F",
                "parameters": {
                    "profile_id": "fixed-r3",
                    "centre_rule": "r_over_M=3",
                    "half_width_rule": "0.45M",
                },
            }
        )
        request = StudyRequest.from_mapping(mapping)
        payload = valid_payload(request)
        horizon_220 = component_for(payload, ell=2, mechanism_id="horizon-admittance")
        horizon_330 = component_for(payload, ell=3, mechanism_id="horizon-admittance")
        fixed_220 = component_for(payload, ell=2, mechanism_id="exterior-fixed-r3")
        fixed_330 = component_for(payload, ell=3, mechanism_id="exterior-fixed-r3")
        fixed_220["result"]["centre"].update({"real": 1.0e-9, "imaginary": 0.0})
        fixed_220["result"]["uncertainty_disk"]["centre"] = deepcopy(
            fixed_220["result"]["centre"]
        )
        fixed_220["result"]["uncertainty_disk"]["radius"] = 2.0e-9
        payload["projective_comparisons"] = [
            {
                "comparison_id": "horizon-versus-fixed-r3",
                "mode_order": [horizon_220["mode"], horizon_330["mode"]],
                "left_component_ids": [
                    horizon_220["component_id"],
                    horizon_330["component_id"],
                ],
                "right_component_ids": [
                    fixed_220["component_id"],
                    fixed_330["component_id"],
                ],
                "calibration_mode": horizon_220["mode"],
                "calibration_numerator_component_id": horizon_220["component_id"],
                "calibration_denominator_component_id": fixed_220["component_id"],
                "covariance_id": "all-resolved-components",
                "empirical_gram_id": "empirical-error-gram-" + "0" * 64,
                "nominal_angle_radians": None,
                "bounded_angle_interval_radians": None,
                "calibration_disk_contains_zero": True,
                "projective_outcome": "UNRESOLVED",
                "scientific_state": "UNRESOLVED",
                "reason": "calibration disk contains zero",
            }
        ]
        validate_linear_response_payload(
            request,
            LINEAR_RESPONSE_DESCRIPTOR.to_mapping(),
            payload,
        )

        payload["projective_comparisons"][0]["projective_outcome"] = "SEPARATED"
        with self.assertRaisesRegex(ValueError, "must be UNRESOLVED"):
            validate_linear_response_payload(
                request,
                LINEAR_RESPONSE_DESCRIPTOR.to_mapping(),
                payload,
            )


if __name__ == "__main__":
    unittest.main()
