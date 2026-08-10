"""Strict admission and ownership rules for the frozen release domain."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from importlib import resources
import json
import math
from pathlib import Path
import re
from types import MappingProxyType
from typing import Any, Mapping, TYPE_CHECKING

from .contracts import (
    Capability,
    CarrierState,
    ExecutionState,
    NumericalState,
    ScientificState,
)

if TYPE_CHECKING:
    from .providers import ProviderRegistry


RELEASE_MANIFEST_RESOURCE = resources.files("windows_solver").joinpath(
    "data", "release_domain_manifest.json"
)
RELEASE_MANIFEST_SHA256 = (
    "d924949307d225342a6f12961c19bb40da1b7078b4ebf25ac07e806814c374dd"
)

_MAX_MANIFEST_BYTES = 2 * 1024 * 1024
_MAX_JSON_DEPTH = 64
_HEX_40 = re.compile(r"[0-9a-f]{40}")
_HEX_64 = re.compile(r"[0-9a-f]{64}")
_MILESTONE = re.compile(r"M(?:0[1-9]|1[0-2])")
_CLASSIFICATIONS = frozenset(
    {
        "publicly_admitted",
        "validated_legacy_evidence",
        "framework_only",
        "missing",
        "invalid",
        "superseded",
    }
)
_MODULE_ROLES = frozenset(
    {
        "active_provider",
        "validator",
        "comparator",
        "extension",
        "retired_fixture",
        "infrastructure",
    }
)
_NON_PRODUCTION_ROLES = frozenset(
    {"comparator", "extension", "retired_fixture"}
)
_TOP_LEVEL_FIELDS = frozenset(
    {
        "schema_version",
        "manifest_id",
        "baseline",
        "release_domain",
        "capabilities",
        "claims",
        "source_receipts",
        "module_ownership",
        "conventions",
        "evidence_ceilings",
        "governance_decisions",
        "blockers",
        "closure",
    }
)


def _exact_fields(
    mapping: Mapping[str, Any], expected: frozenset[str], subject: str
) -> None:
    unknown = sorted(set(mapping) - expected)
    if unknown:
        raise ValueError(f"unknown {subject} fields: {', '.join(unknown)}")
    missing = sorted(expected - set(mapping))
    if missing:
        raise ValueError(f"missing {subject} fields: {', '.join(missing)}")


def _object(value: object, subject: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{subject} must be an object")
    if not all(isinstance(key, str) for key in value):
        raise ValueError(f"{subject} keys must be strings")
    return value


def _list(value: object, subject: str) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError(f"{subject} must be an array")
    return value


def _string(value: object, subject: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{subject} must be a non-empty string")
    return value


def _optional_string(value: object, subject: str) -> str | None:
    if value is None:
        return None
    return _string(value, subject)


def _boolean(value: object, subject: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{subject} must be boolean")
    return value


def _integer(value: object, subject: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{subject} must be an integer")
    return value


def _unique_strings(value: object, subject: str, *, allow_empty: bool = False) -> list[str]:
    items = _list(value, subject)
    if not allow_empty and not items:
        raise ValueError(f"{subject} must not be empty")
    strings = [_string(item, f"{subject} item") for item in items]
    if len(strings) != len(set(strings)):
        raise ValueError(f"{subject} contains duplicate entries")
    return strings


def _number_list(value: object, subject: str) -> list[int | float]:
    items = _list(value, subject)
    if not items:
        raise ValueError(f"{subject} must not be empty")
    numbers: list[int | float] = []
    for item in items:
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            raise ValueError(f"{subject} items must be finite numbers")
        if not math.isfinite(item):
            raise ValueError(f"{subject} items must be finite numbers")
        numbers.append(item)
    if len(numbers) != len(set(numbers)):
        raise ValueError(f"{subject} contains duplicate entries")
    return numbers


def _hex(value: object, subject: str, pattern: re.Pattern[str]) -> str:
    text = _string(value, subject)
    if pattern.fullmatch(text) is None:
        raise ValueError(f"{subject} must be a lowercase hexadecimal digest")
    return text


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"duplicate release manifest JSON key: {key}")
        value[key] = item
    return value


def _reject_nonfinite(value: str) -> object:
    raise ValueError(f"non-finite release manifest JSON number: {value}")


def _validate_json_depth(value: object) -> None:
    pending = [(value, 0)]
    while pending:
        item, depth = pending.pop()
        if depth > _MAX_JSON_DEPTH:
            raise ValueError(
                f"release manifest JSON nesting must not exceed {_MAX_JSON_DEPTH} levels"
            )
        if isinstance(item, Mapping):
            pending.extend((child, depth + 1) for child in item.values())
        elif isinstance(item, list):
            pending.extend((child, depth + 1) for child in item)


def _freeze(value: object) -> object:
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    return value


def _plain(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return value


@dataclass(frozen=True, slots=True)
class ReleaseManifest:
    """An immutable validated snapshot of the release domain."""

    _mapping: Mapping[str, object]

    def to_mapping(self) -> dict[str, object]:
        return _plain(self._mapping)  # type: ignore[return-value]


def _validate_baseline(value: object) -> None:
    baseline = _object(value, "baseline")
    _exact_fields(
        baseline,
        frozenset(
            {
                "repository",
                "accepted_commit",
                "accepted_pull_request",
                "delivery_pull_request",
                "package_license",
                "accepted_artifact_id",
                "immutable",
            }
        ),
        "baseline",
    )
    if baseline["repository"] != "https://api.github.com/repositories/1325068580":
        raise ValueError("baseline repository does not match the accepted repository")
    if baseline["accepted_commit"] != "da313b60faa3f2c5fff93cf9f4669c8c0091dab5":
        raise ValueError("baseline commit does not match the accepted commit")
    if _integer(baseline["accepted_pull_request"], "baseline accepted_pull_request") != 2:
        raise ValueError("accepted baseline must remain pull request 2")
    if _integer(baseline["delivery_pull_request"], "baseline delivery_pull_request") != 3:
        raise ValueError("release-baseline delivery must remain pull request 3")
    if baseline["package_license"] != "LicenseRef-Proprietary":
        raise ValueError("baseline package license does not match the release")
    if baseline["accepted_artifact_id"] != "pure-kerr-qnm-lattice-2736":
        raise ValueError("baseline artifact does not match the accepted artifact")
    if not _boolean(baseline["immutable"], "baseline immutable"):
        raise ValueError("accepted baseline must be immutable")


def _validate_release_domain(value: object) -> None:
    domain = _object(value, "release_domain")
    expected = frozenset(
        {
            "theories",
            "evidence_profiles",
            "platforms",
            "spectrum",
            "linear_response",
            "operator_stability",
            "quadratic_ringdown",
            "response_matrix",
            "waveforms",
            "detector_cases",
            "detector_inputs",
            "evidence_package",
        }
    )
    _exact_fields(domain, expected, "release_domain")
    if domain["theories"] != [
        "general-relativity",
        "parity-even-cubic-higher-curvature-eft",
    ]:
        raise ValueError("release theories do not match the frozen domain")
    if domain["evidence_profiles"] != ["research", "publication"]:
        raise ValueError("release evidence profiles do not match the frozen domain")
    if domain["platforms"] != [
        "windows-powershell-5.1-cpython-3.12-x64",
        "ubuntu-cpython-3.12-x64",
        "oci-linux-amd64-cpython-3.12",
    ]:
        raise ValueError("release platforms do not match the frozen domain")
    if domain["detector_cases"] != [
        "gw250114-h1-l1",
        "lisa-equal-arm-tdi-x-reference",
    ]:
        raise ValueError("detector cases do not match the frozen domain")

    spectrum = _object(domain["spectrum"], "release_domain spectrum")
    _exact_fields(
        spectrum,
        frozenset(
            {
                "spin_weight",
                "ell",
                "m_rule",
                "n",
                "branches",
                "polarizations",
                "spin_points_by_ell",
                "mode_count",
                "root_count",
                "roots_by_ell",
                "catalog_sha256",
                "receipt_sha256",
                "m02_overlay_root_count",
                "m02_selector_union_count",
                "m02_overlay_catalog_sha256",
                "m02_overlay_receipt_sha256",
            }
        ),
        "release_domain spectrum",
    )
    if _integer(spectrum["spin_weight"], "spectrum spin_weight") != -2:
        raise ValueError("spectrum spin_weight must be -2")
    if spectrum["ell"] != [2, 3, 4] or spectrum["n"] != [0, 1, 2]:
        raise ValueError("spectrum ell and overtone domains do not match the baseline")
    if spectrum["spin_points_by_ell"] != {"2": 46, "3": 46, "4": 40}:
        raise ValueError("spectrum spin grids do not match the baseline")
    if _integer(spectrum["mode_count"], "spectrum mode_count") != 63:
        raise ValueError("spectrum mode_count must be 63")
    if _integer(spectrum["root_count"], "spectrum root_count") != 2736:
        raise ValueError("spectrum root_count must be 2736")
    if spectrum["roots_by_ell"] != {"2": 690, "3": 966, "4": 1080}:
        raise ValueError("spectrum roots_by_ell does not match the baseline")
    if spectrum["catalog_sha256"] != (
        "9ebae4271309cd45a1b26c90d31155602ed8ef33bb79069adb5897e8afe7a564"
    ):
        raise ValueError("spectrum catalog SHA-256 does not match the baseline")
    if spectrum["receipt_sha256"] != (
        "61a428a858de1eb7e42fe4cbbda37bf1fddcc808d98be2a62fd33ef4b5b74379"
    ):
        raise ValueError("spectrum receipt SHA-256 does not match the baseline")
    if _integer(
        spectrum["m02_overlay_root_count"], "spectrum M02 overlay root_count"
    ) != 44:
        raise ValueError("spectrum M02 overlay root_count must be 44")
    if _integer(
        spectrum["m02_selector_union_count"],
        "spectrum M02 selector union count",
    ) != 87:
        raise ValueError("spectrum M02 selector union count must be 87")
    if spectrum["m02_overlay_catalog_sha256"] != (
        "c4c61a1b73e850d537dba5f5eb947af100449aa2a1958a1ec8ea086f60ffe8e8"
    ):
        raise ValueError("spectrum M02 overlay catalog SHA-256 does not match")
    if spectrum["m02_overlay_receipt_sha256"] != (
        "93a2e7586878d9c84e32d19ed9e7ad44d03572a91640625c44501bfbc46a5525"
    ):
        raise ValueError("spectrum M02 overlay receipt SHA-256 does not match")
    if spectrum["m_rule"] != "every integer from -ell through +ell":
        raise ValueError("spectrum m_rule does not match the baseline")
    if spectrum["branches"] != ["schwarzschild-overtone-continuation"]:
        raise ValueError("spectrum branch domain does not match the baseline")
    if spectrum["polarizations"] != ["gravitational"]:
        raise ValueError("spectrum polarization domain does not match the baseline")

    linear = _object(domain["linear_response"], "release_domain linear_response")
    _exact_fields(
        linear,
        frozenset(
            {
                "primary_modes",
                "control_modes",
                "direct_spins",
                "surface_gravity_values",
                "mechanisms",
                "branch_classes",
                "required_outputs",
                "b_prime",
            }
        ),
        "release_domain linear_response",
    )
    if linear["primary_modes"] != ["220", "221", "222", "330", "331", "440", "441"]:
        raise ValueError("linear-response primary modes do not match the frozen domain")
    if linear["control_modes"] != ["210", "2-minus-2-0", "320", "3-minus-3-0"]:
        raise ValueError("linear-response control modes do not match the frozen domain")
    if _number_list(linear["direct_spins"], "linear-response direct_spins") != [
        0.95,
        0.99,
        0.999,
        0.9999,
    ]:
        raise ValueError("linear-response direct spins do not match the frozen domain")
    if _number_list(
        linear["surface_gravity_values"],
        "linear-response surface_gravity_values",
    ) != [0.01, 0.002, 0.001]:
        raise ValueError("surface-gravity values do not match the frozen domain")
    if linear["mechanisms"] != [
        "horizon-admittance",
        "exterior-fixed-r3",
        "exterior-light-ring",
        "exterior-throat-kappa",
        "exterior-alpha-zero",
        "exterior-alpha-half",
        "exterior-alpha-one",
        "cubic-eft",
    ]:
        raise ValueError("linear-response mechanisms do not match the frozen domain")
    if linear["branch_classes"] != ["damped", "zero-damping", "unresolved"]:
        raise ValueError("branch classes do not match the frozen domain")
    _unique_strings(linear["required_outputs"], "linear-response required_outputs")
    b_prime = _object(linear["b_prime"], "linear-response B-prime")
    _exact_fields(
        b_prime,
        frozenset(
            {
                "leaf_counts", "selector_counts", "missing_selector_counts",
                "projective_counts", "primary_supports", "deep_support",
                "control_role", "cubic_role", "completeness_rule",
                "primary_direct_spin_coordinates",
                "control_direct_spin_coordinates",
                "deep_surface_gravity_coordinates", "primary_mechanisms",
                "control_mechanisms", "deep_mechanisms", "precision_policy",
                "wolfram_receipt",
            }
        ),
        "linear-response B-prime",
    )
    if b_prime["leaf_counts"] != {"primary": 140, "control": 24, "deep": 48, "total": 212}:
        raise ValueError("B-prime leaf counts do not match the frozen domain")
    if b_prime["selector_counts"] != {"primary": 28, "control": 8, "deep": 12, "total": 48}:
        raise ValueError("B-prime selector counts do not match the frozen domain")
    if b_prime["missing_selector_counts"] != {"primary": 13, "control": 0, "deep": 12, "total": 25}:
        raise ValueError("B-prime missing-selector counts do not match the frozen domain")
    if b_prime["projective_counts"] != {"primary": 48, "deep": 9, "total": 57}:
        raise ValueError("B-prime projective counts do not match the frozen domain")
    if b_prime["primary_supports"] != {"K0": ["220", "330", "440"], "K1": ["221", "331", "441"], "K22": ["220", "221", "222"]}:
        raise ValueError("B-prime primary supports do not match the frozen domain")
    if b_prime["deep_support"] != ["220", "221", "222"]:
        raise ValueError("B-prime deep support does not match the frozen domain")
    if b_prime["control_role"] != "claim-negative exterior-only; negative-m positive-spin rows are counterrotating":
        raise ValueError("B-prime control role does not match the frozen domain")
    if b_prime["cubic_role"] != "eight retained parity-even 220 rows are comparator-only and outside production":
        raise ValueError("B-prime cubic role does not match the frozen domain")
    if b_prime["primary_direct_spin_coordinates"] != [[19, 20], [99, 100], [999, 1000], [9999, 10000]]:
        raise ValueError("B-prime primary direct-spin coordinates do not match the frozen domain")
    if b_prime["control_direct_spin_coordinates"] != [[19, 20], [999, 1000]]:
        raise ValueError("B-prime control direct-spin coordinates do not match the frozen domain")
    if b_prime["deep_surface_gravity_coordinates"] != [[1, 100], [1, 500], [1, 1000]]:
        raise ValueError("B-prime deep surface-gravity coordinates do not match the frozen domain")
    if b_prime["primary_mechanisms"] != [
        "horizon-admittance", "exterior-fixed-r3", "exterior-alpha-half",
        "exterior-light-ring", "exterior-throat-kappa",
    ]:
        raise ValueError("B-prime primary mechanisms do not match the frozen domain")
    if b_prime["control_mechanisms"] != [
        "exterior-fixed-r3", "exterior-light-ring", "exterior-throat-kappa",
    ]:
        raise ValueError("B-prime control mechanisms do not match the frozen domain")
    if b_prime["deep_mechanisms"] != [
        "horizon-admittance", "exterior-alpha-one", "exterior-light-ring",
        "exterior-throat-kappa",
    ]:
        raise ValueError("B-prime deep mechanisms do not match the frozen domain")
    if b_prime["completeness_rule"] != "admission requires 212 produced leaves and zero missing; evidence-bearing UNRESOLVED is produced":
        raise ValueError("B-prime completeness rule does not match the frozen domain")
    precision = _object(b_prime["precision_policy"], "B-prime precision policy")
    _exact_fields(precision, frozenset({"promote_digits", "repeat_digits", "sentinel_count", "promotion_gate_count"}), "B-prime precision policy")
    if precision != {"promote_digits": 80, "repeat_digits": 120, "sentinel_count": 6, "promotion_gate_count": 4}:
        raise ValueError("B-prime precision policy does not match the frozen domain")
    if b_prime["wolfram_receipt"] != "docs/evidence/m02-b-prime-wolfram-arithmetic-receipt.json":
        raise ValueError("B-prime Wolfram receipt path does not match the frozen domain")

    operator = _object(
        domain["operator_stability"], "release_domain operator_stability"
    )
    _exact_fields(
        operator,
        frozenset({"required_outputs", "evidence_layers", "formal_requirement"}),
        "release_domain operator_stability",
    )
    _unique_strings(operator["required_outputs"], "operator-stability required_outputs")
    if operator["evidence_layers"] != [
        "discrete-numerical",
        "truncation",
        "continuum",
    ]:
        raise ValueError("operator evidence layers do not match the frozen domain")
    _string(operator["formal_requirement"], "operator formal_requirement")

    quadratic = _object(domain["quadratic_ringdown"], "quadratic_ringdown")
    _exact_fields(
        quadratic,
        frozenset(
            {
                "parent_pair",
                "forced_azimuthal_number",
                "forced_frequency_rule",
                "observable",
                "spins",
                "gauge",
                "tetrad",
                "parent_amplitude_normalization",
            }
        ),
        "release_domain quadratic_ringdown",
    )
    if quadratic["parent_pair"] != ["220-plus", "220-plus"]:
        raise ValueError("quadratic parent pair does not match the frozen domain")
    if quadratic["forced_azimuthal_number"] != 4:
        raise ValueError("quadratic forced azimuthal number must be 4")
    if quadratic["forced_frequency_rule"] != "omega-parent-1-plus-omega-parent-2":
        raise ValueError("quadratic forced frequency rule does not match")
    if quadratic["observable"] != "R-plus-plus-44":
        raise ValueError("quadratic observable does not match the frozen domain")
    if _number_list(quadratic["spins"], "quadratic spins") != [
        0.0,
        0.3,
        0.5,
        0.7,
        0.9,
        0.95,
    ]:
        raise ValueError("quadratic spins do not match the frozen domain")
    for field in ("gauge", "tetrad", "parent_amplitude_normalization"):
        _string(quadratic[field], f"quadratic {field}")

    response = _object(domain["response_matrix"], "release_domain response_matrix")
    _exact_fields(
        response,
        frozenset({"parameter_basis", "blocks", "required_diagnostics"}),
        "release_domain response_matrix",
    )
    for field in ("parameter_basis", "blocks", "required_diagnostics"):
        _unique_strings(response[field], f"response-matrix {field}")

    waveforms = _object(domain["waveforms"], "release_domain waveforms")
    _exact_fields(
        waveforms,
        frozenset({"cases", "time_support", "strain_conversion"}),
        "release_domain waveforms",
    )
    if waveforms["cases"] != [
        "causal-linear-multimode",
        "quadratic-220-plus-220",
        "psi4-to-strain",
        "tails-and-greybody",
    ]:
        raise ValueError("waveform cases do not match the frozen domain")
    _string(waveforms["time_support"], "waveforms time_support")
    _string(waveforms["strain_conversion"], "waveforms strain_conversion")

    detector_inputs = _object(
        domain["detector_inputs"], "release_domain detector_inputs"
    )
    if set(detector_inputs) != set(domain["detector_cases"]):
        raise ValueError("detector inputs do not cover the detector cases")
    ground = _object(detector_inputs["gw250114-h1-l1"], "ground detector input")
    _exact_fields(
        ground,
        frozenset(
            {"event_time_gps", "channels", "sample_rates_hz", "duration_seconds", "data_license"}
        ),
        "ground detector input",
    )
    if ground["event_time_gps"] != 1420878141.2:
        raise ValueError("ground detector event time does not match the frozen case")
    if ground["channels"] != [
        "H1-GDS-CALIB-STRAIN-CLEAN-AR",
        "L1-GDS-CALIB-STRAIN-CLEAN-AR",
    ]:
        raise ValueError("ground detector channels do not match the frozen case")
    if ground["sample_rates_hz"] != [4096, 16384] or ground["duration_seconds"] != 4096:
        raise ValueError("ground detector sampling does not match the frozen case")
    if ground["data_license"] != "CC-BY-4.0":
        raise ValueError("ground detector data license does not match the frozen case")
    space = _object(
        detector_inputs["lisa-equal-arm-tdi-x-reference"],
        "space detector input",
    )
    _exact_fields(
        space,
        frozenset({"arm_length_km", "observable", "response", "noise"}),
        "space detector input",
    )
    if space["arm_length_km"] != 2500000:
        raise ValueError("space detector arm length does not match the frozen case")
    for field in ("observable", "response", "noise"):
        _string(space[field], f"space detector {field}")

    package = _object(domain["evidence_package"], "release_domain evidence_package")
    _exact_fields(
        package,
        frozenset({"profiles", "required_properties"}),
        "release_domain evidence_package",
    )
    if package["profiles"] != domain["evidence_profiles"]:
        raise ValueError("evidence-package profiles do not match the release profiles")
    _unique_strings(package["required_properties"], "evidence-package required_properties")


def _validate_capabilities(value: object) -> dict[str, Mapping[str, Any]]:
    capabilities = _object(value, "capabilities")
    expected = {capability.value for capability in Capability}
    if set(capabilities) != expected:
        raise ValueError("capability manifest coverage is incomplete")
    validated: dict[str, Mapping[str, Any]] = {}
    for capability_id in sorted(capabilities):
        record = _object(capabilities[capability_id], f"capability {capability_id}")
        _exact_fields(
            record,
            frozenset(
                {
                    "programme_milestone",
                    "provider_state",
                    "active_provider_id",
                    "required_outputs",
                    "required_evidence_ids",
                    "convention_ids",
                }
            ),
            f"capability {capability_id}",
        )
        milestone = _string(
            record["programme_milestone"],
            f"capability {capability_id} programme_milestone",
        )
        if _MILESTONE.fullmatch(milestone) is None:
            raise ValueError(f"capability {capability_id} has an invalid milestone")
        state = _string(
            record["provider_state"], f"capability {capability_id} provider_state"
        )
        if state not in {"publicly_admitted", "future_required"}:
            raise ValueError(f"capability {capability_id} has an invalid provider state")
        provider_id = _optional_string(
            record["active_provider_id"],
            f"capability {capability_id} active_provider_id",
        )
        if state == "publicly_admitted" and provider_id is None:
            raise ValueError(f"admitted capability {capability_id} needs a provider")
        if state != "publicly_admitted" and provider_id is not None:
            raise ValueError(f"future capability {capability_id} cannot name a provider")
        _unique_strings(
            record["required_outputs"], f"capability {capability_id} required_outputs"
        )
        _unique_strings(
            record["required_evidence_ids"],
            f"capability {capability_id} required_evidence_ids",
            allow_empty=True,
        )
        _unique_strings(
            record["convention_ids"], f"capability {capability_id} convention_ids"
        )
        validated[capability_id] = record
    admitted = {
        capability_id
        for capability_id, record in validated.items()
        if record["provider_state"] == "publicly_admitted"
    }
    if admitted != {Capability.PROBLEM_CONTRACT.value, Capability.SPECTRAL_CORE.value}:
        raise ValueError("only the problem contract and spectral core are admitted")
    expected_milestones = {
        "problem-contract": "M01",
        "spectral-core": "M03",
        "linear-response": "M02",
        "operator-stability": "M04",
        "quadratic-ringdown": "M06",
        "response-matrix": "M07",
        "inverse-inference": "M08",
        "signals": "M09",
        "detector-inference": "M10",
        "evidence-package": "M11",
    }
    if {
        capability_id: record["programme_milestone"]
        for capability_id, record in validated.items()
    } != expected_milestones:
        raise ValueError("capability milestone mapping does not match the programme")
    return validated


def _validate_evidence_ceilings(value: object) -> set[str]:
    ceilings = _list(value, "evidence_ceilings")
    if not ceilings:
        raise ValueError("evidence_ceilings must not be empty")
    identifiers: set[str] = set()
    fields = frozenset(
        {
            "evidence_ceiling_id",
            "carrier",
            "execution",
            "numerical",
            "scientific",
            "formal_enclosure",
            "maximum_claim",
        }
    )
    for index, item in enumerate(ceilings):
        record = _object(item, f"evidence ceiling {index}")
        _exact_fields(record, fields, f"evidence ceiling {index}")
        identifier = _string(record["evidence_ceiling_id"], "evidence_ceiling_id")
        if identifier in identifiers:
            raise ValueError(f"duplicate evidence ceiling: {identifier}")
        identifiers.add(identifier)
        try:
            CarrierState(_string(record["carrier"], f"{identifier} carrier"))
            ExecutionState(_string(record["execution"], f"{identifier} execution"))
            NumericalState(_string(record["numerical"], f"{identifier} numerical"))
            ScientificState(_string(record["scientific"], f"{identifier} scientific"))
        except ValueError as error:
            raise ValueError(f"invalid state in evidence ceiling {identifier}") from error
        _boolean(record["formal_enclosure"], f"{identifier} formal_enclosure")
        _string(record["maximum_claim"], f"{identifier} maximum_claim")
    return identifiers


def _validate_conventions(value: object) -> set[str]:
    conventions = _list(value, "conventions")
    if not conventions:
        raise ValueError("conventions must not be empty")
    identifiers: set[str] = set()
    fields = frozenset(
        {
            "convention_id",
            "equations_id",
            "time_fourier",
            "boundary_conditions",
            "gauge",
            "tetrad",
            "units",
            "field_normalization",
            "amplitude_normalization",
            "branch_rule",
            "applies_to",
            "status",
        }
    )
    for index, item in enumerate(conventions):
        record = _object(item, f"convention {index}")
        _exact_fields(record, fields, f"convention {index}")
        identifier = _string(record["convention_id"], "convention_id")
        if identifier in identifiers:
            raise ValueError(f"duplicate convention: {identifier}")
        identifiers.add(identifier)
        for field in fields - {"convention_id", "applies_to"}:
            _string(record[field], f"convention {identifier} {field}")
        _unique_strings(record["applies_to"], f"convention {identifier} applies_to")
    return identifiers


def _validate_receipts(
    value: object, convention_ids: set[str], evidence_ids: set[str]
) -> dict[str, Mapping[str, Any]]:
    receipts = _list(value, "source_receipts")
    records: dict[str, Mapping[str, Any]] = {}
    fields = frozenset(
        {
            "receipt_id",
            "status",
            "repository",
            "immutable_url",
            "commit",
            "pull_request",
            "artifact",
            "artifact_sha256",
            "artifact_blob",
            "generator_identity",
            "tests",
            "license",
            "runtime",
            "convention_id",
            "evidence_ceiling_id",
            "retrieval",
            "owner",
            "unblock_action",
        }
    )
    for index, item in enumerate(receipts):
        record = _object(item, f"source receipt {index}")
        _exact_fields(record, fields, f"source receipt {index}")
        identifier = _string(record["receipt_id"], "receipt_id")
        if identifier in records:
            raise ValueError(f"duplicate source receipt: {identifier}")
        status = _string(record["status"], f"receipt {identifier} status")
        if status not in {"available", "missing"}:
            raise ValueError(f"receipt {identifier} has an invalid status")
        convention_id = _string(
            record["convention_id"], f"receipt {identifier} convention_id"
        )
        if convention_id not in convention_ids:
            raise ValueError(f"receipt {identifier} names an unknown convention")
        evidence_id = _string(
            record["evidence_ceiling_id"],
            f"receipt {identifier} evidence_ceiling_id",
        )
        if evidence_id not in evidence_ids:
            raise ValueError(f"receipt {identifier} names an unknown evidence ceiling")
        repository = _string(
            record["repository"], f"receipt {identifier} repository"
        )
        if not repository.startswith("https://"):
            raise ValueError(f"receipt {identifier} repository must use HTTPS")
        _string(record["artifact"], f"receipt {identifier} artifact")
        _string(record["license"], f"receipt {identifier} license")
        _string(record["runtime"], f"receipt {identifier} runtime")
        _string(record["owner"], f"receipt {identifier} owner")
        _unique_strings(
            record["tests"],
            f"receipt {identifier} tests",
            allow_empty=status == "missing",
        )
        if status == "available":
            immutable_url = _string(
                record["immutable_url"], f"receipt {identifier} immutable_url"
            )
            if not immutable_url.startswith("https://"):
                raise ValueError(f"receipt {identifier} immutable_url must use HTTPS")
            commit = _hex(record["commit"], f"receipt {identifier} commit", _HEX_40)
            artifact_blob = _hex(
                record["artifact_blob"],
                f"receipt {identifier} artifact_blob",
                _HEX_40,
            )
            _hex(
                record["artifact_sha256"],
                f"receipt {identifier} artifact_sha256",
                _HEX_64,
            )
            _string(
                record["generator_identity"],
                f"receipt {identifier} generator_identity",
            )
            _string(record["retrieval"], f"receipt {identifier} retrieval")
            _optional_string(
                record["pull_request"], f"receipt {identifier} pull_request"
            )
            if commit not in immutable_url and artifact_blob not in immutable_url:
                raise ValueError(f"receipt {identifier} URL is not content bound")
            if record["unblock_action"] is not None:
                raise ValueError(f"available receipt {identifier} cannot have an unblock action")
        else:
            for field in (
                "immutable_url",
                "commit",
                "pull_request",
                "artifact_sha256",
                "artifact_blob",
                "generator_identity",
                "retrieval",
            ):
                if record[field] is not None:
                    raise ValueError(f"missing receipt {identifier} must leave {field} null")
            _string(record["unblock_action"], f"receipt {identifier} unblock_action")
        records[identifier] = record
    if not records:
        raise ValueError("source_receipts must not be empty")
    return records


def _validate_claims(
    value: object,
    capabilities: Mapping[str, Mapping[str, Any]],
    receipts: Mapping[str, Mapping[str, Any]],
    evidence_ids: set[str],
) -> None:
    claims = _list(value, "claims")
    seen: set[str] = set()
    covered: set[str] = set()
    admitted_claim_capabilities: set[str] = set()
    fields = frozenset(
        {
            "claim_id",
            "capability",
            "classification",
            "statement",
            "source_receipt_ids",
            "evidence_ceiling_id",
            "production_dependency",
        }
    )
    for index, item in enumerate(claims):
        claim = _object(item, f"claim {index}")
        _exact_fields(claim, fields, f"claim {index}")
        claim_id = _string(claim["claim_id"], "claim_id")
        if claim_id in seen:
            raise ValueError(f"duplicate claim: {claim_id}")
        seen.add(claim_id)
        capability = _string(claim["capability"], f"claim {claim_id} capability")
        if capability not in capabilities:
            raise ValueError(f"claim {claim_id} names an unknown capability")
        covered.add(capability)
        classification = _string(
            claim["classification"], f"claim {claim_id} classification"
        )
        if classification not in _CLASSIFICATIONS:
            raise ValueError(f"claim {claim_id} has an invalid classification")
        _string(claim["statement"], f"claim {claim_id} statement")
        source_ids = _unique_strings(
            claim["source_receipt_ids"],
            f"claim {claim_id} source_receipt_ids",
            allow_empty=True,
        )
        for source_id in source_ids:
            if source_id not in receipts:
                raise ValueError(f"claim {claim_id} names an unknown source receipt")
        evidence_id = _string(
            claim["evidence_ceiling_id"], f"claim {claim_id} evidence_ceiling_id"
        )
        if evidence_id not in evidence_ids:
            raise ValueError(f"claim {claim_id} names an unknown evidence ceiling")
        production_dependency = _boolean(
            claim["production_dependency"],
            f"claim {claim_id} production_dependency",
        )
        if classification == "publicly_admitted":
            if not source_ids or any(receipts[item]["status"] != "available" for item in source_ids):
                raise ValueError(f"publicly admitted claim {claim_id} needs available receipts")
            if capabilities[capability]["provider_state"] != "publicly_admitted":
                raise ValueError(f"publicly admitted claim {claim_id} needs an admitted provider")
            if not production_dependency:
                raise ValueError(f"publicly admitted claim {claim_id} must be a production dependency")
            if any(
                receipts[item]["evidence_ceiling_id"] != evidence_id
                for item in source_ids
            ):
                raise ValueError(
                    f"publicly admitted claim {claim_id} has incompatible receipt evidence"
                )
            admitted_claim_capabilities.add(capability)
        elif classification == "validated_legacy_evidence":
            if production_dependency:
                raise ValueError(
                    f"non-admitted claim {claim_id} cannot be a production dependency"
                )
            if not source_ids or any(
                receipts[item]["status"] != "available" for item in source_ids
            ):
                raise ValueError(
                    f"validated retained claim {claim_id} needs available receipts"
                )
            if any(
                receipts[item]["evidence_ceiling_id"] != evidence_id
                for item in source_ids
            ):
                raise ValueError(
                    f"validated retained claim {claim_id} has incompatible receipt evidence"
                )
        elif production_dependency:
            raise ValueError(f"non-admitted claim {claim_id} cannot be a production dependency")
        if classification in {"missing", "framework_only"} and not any(
            receipts[item]["status"] == "missing" for item in source_ids
        ):
            raise ValueError(f"{classification} claim {claim_id} needs a missing receipt")
    if covered != set(capabilities):
        raise ValueError("claims do not cover every capability")
    admitted_capabilities = {
        capability
        for capability, record in capabilities.items()
        if record["provider_state"] == "publicly_admitted"
    }
    if admitted_claim_capabilities != admitted_capabilities:
        raise ValueError("admitted capabilities do not have exactly matching admitted claims")


def _validate_module_ownership(
    value: object,
    capabilities: Mapping[str, Mapping[str, Any]],
    receipts: Mapping[str, Mapping[str, Any]],
) -> None:
    modules = _list(value, "module_ownership")
    seen: set[str] = set()
    active_owners: dict[str, str] = {}
    fields = frozenset(
        {
            "module_id",
            "role",
            "capability",
            "source_receipt_id",
            "input_contract",
            "output_contract",
            "production_dependency",
            "replacement_gate",
        }
    )
    for index, item in enumerate(modules):
        record = _object(item, f"module ownership {index}")
        _exact_fields(record, fields, f"module ownership {index}")
        module_id = _string(record["module_id"], "module_id")
        if module_id in seen:
            raise ValueError(f"duplicate module ownership: {module_id}")
        seen.add(module_id)
        role = _string(record["role"], f"module {module_id} role")
        if role not in _MODULE_ROLES:
            raise ValueError(f"module {module_id} has an invalid role")
        capability = _optional_string(
            record["capability"], f"module {module_id} capability"
        )
        if capability is not None and capability not in capabilities:
            raise ValueError(f"module {module_id} names an unknown capability")
        source_id = _optional_string(
            record["source_receipt_id"], f"module {module_id} source_receipt_id"
        )
        if source_id is not None and source_id not in receipts:
            raise ValueError(f"module {module_id} names an unknown source receipt")
        _string(record["input_contract"], f"module {module_id} input_contract")
        _string(record["output_contract"], f"module {module_id} output_contract")
        production = _boolean(
            record["production_dependency"], f"module {module_id} production_dependency"
        )
        _optional_string(record["replacement_gate"], f"module {module_id} replacement_gate")
        if role in _NON_PRODUCTION_ROLES and production:
            raise ValueError(f"non-production module {module_id} cannot be a production dependency")
        if role == "active_provider":
            if capability is None or not production:
                raise ValueError(f"active provider module {module_id} has incomplete ownership")
            if capability in active_owners:
                raise ValueError(f"capability {capability} has multiple active owners")
            active_owners[capability] = module_id
    admitted = {
        capability
        for capability, record in capabilities.items()
        if record["provider_state"] == "publicly_admitted"
    }
    if set(active_owners) != admitted:
        raise ValueError("active module ownership does not match admitted capabilities")


def _validate_registry(
    capabilities: Mapping[str, Mapping[str, Any]], registry: "ProviderRegistry"
) -> None:
    actual = {
        descriptor.capability.value: descriptor.provider_id
        for descriptor in registry.descriptors()
        if descriptor.available
    }
    expected = {
        capability: record["active_provider_id"]
        for capability, record in capabilities.items()
        if record["provider_state"] == "publicly_admitted"
    }
    if actual != expected:
        raise ValueError("provider registry does not match release manifest ownership")


def _validate_governance(value: object, subject: str) -> None:
    records = _list(value, subject)
    if not records:
        raise ValueError(f"{subject} must not be empty")
    seen: set[str] = set()
    fields = (
        frozenset({"decision_id", "decision", "rationale"})
        if subject == "governance_decisions"
        else frozenset({"blocker_id", "capability", "owner", "unblock_action"})
    )
    identifier_field = "decision_id" if subject == "governance_decisions" else "blocker_id"
    for index, item in enumerate(records):
        record = _object(item, f"{subject} {index}")
        _exact_fields(record, fields, f"{subject} {index}")
        identifier = _string(record[identifier_field], identifier_field)
        if identifier in seen:
            raise ValueError(f"duplicate {subject} identifier: {identifier}")
        seen.add(identifier)
        for field in fields - {identifier_field}:
            _string(record[field], f"{subject} {identifier} {field}")


def _validate_closure(value: object) -> None:
    closure = _object(value, "closure")
    _exact_fields(
        closure,
        frozenset(
            {
                "milestone",
                "task_ids",
                "scope_frozen",
                "human_reconciliation",
                "automated_validation",
                "future_missing_evidence_blocks_capabilities",
            }
        ),
        "closure",
    )
    if closure["milestone"] != "M01":
        raise ValueError("closure milestone must be M01")
    if closure["task_ids"] != ["TASK-001", "TASK-002", "TASK-003", "TASK-004", "TASK-005"]:
        raise ValueError("closure task coverage must be TASK-001 through TASK-005")
    for field in (
        "scope_frozen",
        "human_reconciliation",
        "automated_validation",
        "future_missing_evidence_blocks_capabilities",
    ):
        if not _boolean(closure[field], f"closure {field}"):
            raise ValueError(f"closure {field} must be true")


def validate_release_manifest_mapping(
    mapping: Mapping[str, Any], *, registry: "ProviderRegistry | None" = None
) -> None:
    """Validate all release-domain, evidence, and ownership invariants."""

    root = _object(mapping, "release manifest")
    _exact_fields(root, _TOP_LEVEL_FIELDS, "release manifest")
    if _integer(root["schema_version"], "schema_version") != 1:
        raise ValueError("release manifest schema_version must be 1")
    if root["manifest_id"] != "nonlinear-kerr-ringdown-release-domain-2026-08-07":
        raise ValueError("release manifest_id does not match the frozen release")
    _validate_baseline(root["baseline"])
    _validate_release_domain(root["release_domain"])
    capabilities = _validate_capabilities(root["capabilities"])
    evidence_ids = _validate_evidence_ceilings(root["evidence_ceilings"])
    convention_ids = _validate_conventions(root["conventions"])
    for capability_id, record in capabilities.items():
        if not set(record["required_evidence_ids"]).issubset(evidence_ids):
            raise ValueError(f"capability {capability_id} names an unknown evidence ceiling")
        if not set(record["convention_ids"]).issubset(convention_ids):
            raise ValueError(f"capability {capability_id} names an unknown convention")
    receipts = _validate_receipts(root["source_receipts"], convention_ids, evidence_ids)
    _validate_claims(root["claims"], capabilities, receipts, evidence_ids)
    _validate_module_ownership(root["module_ownership"], capabilities, receipts)
    _validate_governance(root["governance_decisions"], "governance_decisions")
    _validate_governance(root["blockers"], "blockers")
    _validate_closure(root["closure"])
    if registry is not None:
        _validate_registry(capabilities, registry)


def load_release_manifest(
    path: str | Path | None = None, *, registry: "ProviderRegistry | None" = None
) -> ReleaseManifest:
    """Load, authenticate, validate, and freeze a release manifest."""

    if path is None:
        data = RELEASE_MANIFEST_RESOURCE.read_bytes()
        if hashlib.sha256(data).hexdigest() != RELEASE_MANIFEST_SHA256:
            raise ValueError("packaged release manifest SHA-256 does not match")
    else:
        source = Path(path)
        if source.stat().st_size > _MAX_MANIFEST_BYTES:
            raise ValueError("release manifest exceeds the maximum size")
        data = source.read_bytes()
    if len(data) > _MAX_MANIFEST_BYTES:
        raise ValueError("release manifest exceeds the maximum size")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValueError("release manifest must be UTF-8") from error
    try:
        value = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_nonfinite,
        )
    except json.JSONDecodeError as error:
        raise ValueError("release manifest is not valid JSON") from error
    except RecursionError as error:
        raise ValueError("release manifest JSON nesting exceeds the parser limit") from error
    _validate_json_depth(value)
    mapping = _object(value, "release manifest")
    validate_release_manifest_mapping(mapping, registry=registry)
    return ReleaseManifest(_freeze(mapping))  # type: ignore[arg-type]
