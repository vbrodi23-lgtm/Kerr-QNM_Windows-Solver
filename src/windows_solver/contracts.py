"""Strict, immutable public scientific contracts."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping


_MAX_STUDY_BYTES = 4 * 1024 * 1024
_MAX_JSON_DEPTH = 64


def canonical_text_bytes(value: bytes) -> bytes:
    """Normalize UTF-8 source text independently of checkout line endings."""

    if not isinstance(value, bytes):
        raise ValueError("canonical text must be bytes")
    normalized = value.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    try:
        normalized.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValueError("canonical text must be UTF-8") from error
    return normalized


def canonical_text_sha256(value: bytes) -> str:
    """Hash UTF-8 source text independently of checkout line endings."""

    return hashlib.sha256(canonical_text_bytes(value)).hexdigest()


class Capability(str, Enum):
    PROBLEM_CONTRACT = "problem-contract"
    SPECTRAL_CORE = "spectral-core"
    LINEAR_RESPONSE = "linear-response"
    OPERATOR_STABILITY = "operator-stability"
    QUADRATIC_RINGDOWN = "quadratic-ringdown"
    RESPONSE_MATRIX = "response-matrix"
    INVERSE_INFERENCE = "inverse-inference"
    SIGNALS = "signals"
    DETECTOR_INFERENCE = "detector-inference"
    EVIDENCE_PACKAGE = "evidence-package"


class CarrierState(str, Enum):
    VALID = "VALID"
    INVALID = "INVALID"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class ExecutionState(str, Enum):
    NOT_RUN = "NOT_RUN"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


class NumericalState(str, Enum):
    NOT_EVALUATED = "NOT_EVALUATED"
    CONVERGED = "CONVERGED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    UNRESOLVED = "UNRESOLVED"


class ScientificState(str, Enum):
    NOT_EVALUATED = "NOT_EVALUATED"
    SUPPORTED = "SUPPORTED"
    CONDITIONALLY_SUPPORTED = "CONDITIONALLY_SUPPORTED"
    FRAGILE = "FRAGILE"
    UNRESOLVED = "UNRESOLVED"
    CONTRADICTED = "CONTRADICTED"


@dataclass(frozen=True, slots=True)
class EvidenceState:
    carrier: CarrierState
    execution: ExecutionState
    numerical: NumericalState
    scientific: ScientificState

    def to_mapping(self) -> dict[str, str]:
        return {
            "carrier": self.carrier.value,
            "execution": self.execution.value,
            "numerical": self.numerical.value,
            "scientific": self.scientific.value,
        }

    def constrained_by(
        self, upstream: tuple["EvidenceState", ...]
    ) -> "EvidenceState":
        """Prevent a downstream result from outranking its direct inputs.

        Rejection and contradiction are substantive adverse outcomes, so they
        propagate rather than being treated as missing evidence.  The remaining
        numerical and scientific states form conservative evidence ceilings.
        """

        if not upstream:
            return self

        carrier = self.carrier
        if self.carrier is CarrierState.INVALID or any(
            item.carrier is CarrierState.INVALID for item in upstream
        ):
            carrier = CarrierState.INVALID
        elif self.carrier is CarrierState.NOT_APPLICABLE or any(
            item.carrier is CarrierState.NOT_APPLICABLE for item in upstream
        ):
            carrier = CarrierState.NOT_APPLICABLE

        execution = self.execution
        execution_states = {self.execution, *(item.execution for item in upstream)}
        if ExecutionState.FAILED in execution_states:
            execution = ExecutionState.FAILED
        elif ExecutionState.NOT_RUN in execution_states:
            execution = ExecutionState.NOT_RUN
        elif ExecutionState.RUNNING in execution_states:
            execution = ExecutionState.RUNNING

        numerical = self.numerical
        numerical_states = {self.numerical, *(item.numerical for item in upstream)}
        if NumericalState.REJECTED in numerical_states:
            numerical = NumericalState.REJECTED
        elif NumericalState.NOT_EVALUATED in numerical_states:
            numerical = NumericalState.NOT_EVALUATED
        elif NumericalState.UNRESOLVED in numerical_states:
            numerical = NumericalState.UNRESOLVED
        elif (
            NumericalState.CONVERGED in numerical_states
            and numerical is NumericalState.ACCEPTED
        ):
            numerical = NumericalState.CONVERGED

        scientific = self.scientific
        scientific_states = {
            self.scientific,
            *(item.scientific for item in upstream),
        }
        if ScientificState.CONTRADICTED in scientific_states:
            scientific = ScientificState.CONTRADICTED
        else:
            scientific_rank = {
                ScientificState.NOT_EVALUATED: 0,
                ScientificState.UNRESOLVED: 1,
                ScientificState.FRAGILE: 2,
                ScientificState.CONDITIONALLY_SUPPORTED: 3,
                ScientificState.SUPPORTED: 4,
            }
            ceiling = min(
                scientific_states,
                key=scientific_rank.__getitem__,
            )
            scientific = ceiling

        return EvidenceState(
            carrier=carrier,
            execution=execution,
            numerical=numerical,
            scientific=scientific,
        )


def canonical_json_bytes(value: object) -> bytes:
    """Return the one canonical UTF-8 representation used for identities."""

    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _exact_fields(
    mapping: Mapping[str, Any], expected: frozenset[str], subject: str
) -> None:
    unknown = sorted(set(mapping) - expected)
    if unknown:
        raise ValueError(f"unknown {subject} fields: {', '.join(unknown)}")
    missing = sorted(expected - set(mapping))
    if missing:
        raise ValueError(f"missing {subject} fields: {', '.join(missing)}")


def _integer(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an integer")
    return value


def _nonempty_string(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _validate_json_depth(value: object) -> None:
    pending = [(value, 0)]
    while pending:
        item, depth = pending.pop()
        if depth > _MAX_JSON_DEPTH:
            raise ValueError(
                f"study JSON nesting must not exceed {_MAX_JSON_DEPTH} levels"
            )
        if isinstance(item, Mapping):
            pending.extend((child, depth + 1) for child in item.values())
        elif isinstance(item, list):
            pending.extend((child, depth + 1) for child in item)


def _reject_study_duplicate_keys(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"duplicate study JSON key: {key}")
        value[key] = item
    return value


def _reject_study_nonfinite(value: str) -> object:
    raise ValueError(f"non-finite study JSON number: {value}")


@dataclass(frozen=True, slots=True)
class ModeKey:
    s: int
    ell: int
    m: int
    n: int
    branch: str
    polarization: str

    @classmethod
    def from_mapping(cls, mapping: Mapping[str, Any]) -> "ModeKey":
        if not isinstance(mapping, Mapping):
            raise ValueError("mode must be an object")
        expected = frozenset({"s", "ell", "m", "n", "branch", "polarization"})
        _exact_fields(mapping, expected, "mode")
        s = _integer(mapping["s"], "s")
        ell = _integer(mapping["ell"], "ell")
        m = _integer(mapping["m"], "m")
        n = _integer(mapping["n"], "n")
        if ell < abs(s):
            raise ValueError("ell must be at least absolute s")
        if abs(m) > ell:
            raise ValueError("absolute m must not exceed ell")
        if n < 0:
            raise ValueError("n must be non-negative")
        return cls(
            s=s,
            ell=ell,
            m=m,
            n=n,
            branch=_nonempty_string(mapping["branch"], "branch"),
            polarization=_nonempty_string(
                mapping["polarization"], "polarization"
            ),
        )

    def to_mapping(self) -> dict[str, object]:
        return {
            "s": self.s,
            "ell": self.ell,
            "m": self.m,
            "n": self.n,
            "branch": self.branch,
            "polarization": self.polarization,
        }


@dataclass(frozen=True, slots=True)
class StudyRequest:
    schema_version: int
    target: Capability
    theory_id: str
    convention_id: str
    modes: tuple[ModeKey, ...]
    spins: tuple[float, ...]
    evidence_profile: str
    _numerical_policy_json: str

    @classmethod
    def from_mapping(cls, mapping: Mapping[str, Any]) -> "StudyRequest":
        if not isinstance(mapping, Mapping):
            raise ValueError("study must be an object")
        expected = frozenset(
            {
                "schema_version",
                "target",
                "theory_id",
                "convention_id",
                "modes",
                "spins",
                "evidence_profile",
                "numerical_policy",
            }
        )
        _exact_fields(mapping, expected, "study")
        schema_version = _integer(mapping["schema_version"], "schema_version")
        if schema_version != 1:
            raise ValueError("schema_version must be 1")
        try:
            target = Capability(mapping["target"])
        except (TypeError, ValueError) as error:
            raise ValueError(f"unknown target capability: {mapping['target']!r}") from error
        raw_modes = mapping["modes"]
        if not isinstance(raw_modes, list) or not raw_modes:
            raise ValueError("modes must be a non-empty array")
        modes = tuple(ModeKey.from_mapping(mode) for mode in raw_modes)
        raw_spins = mapping["spins"]
        if not isinstance(raw_spins, list) or not raw_spins:
            raise ValueError("spins must be a non-empty array")
        spins: list[float] = []
        for spin in raw_spins:
            if isinstance(spin, bool) or not isinstance(spin, (int, float)):
                raise ValueError("spins must be finite and satisfy -1 < a_over_m < 1")
            converted = float(spin)
            if not math.isfinite(converted) or not -1.0 < converted < 1.0:
                raise ValueError("spins must be finite and satisfy -1 < a_over_m < 1")
            spins.append(converted)
        policy = mapping["numerical_policy"]
        if not isinstance(policy, Mapping):
            raise ValueError("numerical_policy must be an object")
        policy_json = canonical_json_bytes(dict(policy)).decode("utf-8")
        return cls(
            schema_version=schema_version,
            target=target,
            theory_id=_nonempty_string(mapping["theory_id"], "theory_id"),
            convention_id=_nonempty_string(
                mapping["convention_id"], "convention_id"
            ),
            modes=modes,
            spins=tuple(spins),
            evidence_profile=_nonempty_string(
                mapping["evidence_profile"], "evidence_profile"
            ),
            _numerical_policy_json=policy_json,
        )

    @property
    def numerical_policy(self) -> dict[str, object]:
        return json.loads(self._numerical_policy_json)

    def to_mapping(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "target": self.target.value,
            "theory_id": self.theory_id,
            "convention_id": self.convention_id,
            "modes": [mode.to_mapping() for mode in self.modes],
            "spins": list(self.spins),
            "evidence_profile": self.evidence_profile,
            "numerical_policy": self.numerical_policy,
        }

    def for_capability(self, capability: Capability) -> "StudyRequest":
        """Return the canonical request material relevant to one DAG node.

        Top-level numerical-policy keys named for capabilities are local to
        those capabilities.  Every other policy key is global.  Replacing the
        user-facing target with the executing capability makes upstream cache
        identities independent of which downstream result was requested.
        """

        capability_names = {item.value for item in Capability}
        scoped_policy = {
            key: value
            for key, value in self.numerical_policy.items()
            if key not in capability_names or key == capability.value
        }
        if capability is Capability.SPECTRAL_CORE:
            linear_policy = self.numerical_policy.get(
                Capability.LINEAR_RESPONSE.value
            )
            if isinstance(linear_policy, Mapping) and (
                "role_scoped_leaves" in linear_policy
            ):
                raw_leaves = linear_policy["role_scoped_leaves"]
                if not isinstance(raw_leaves, list) or not raw_leaves:
                    raise ValueError(
                        "role-scoped linear response requires spectral selections"
                    )
                pairs: list[dict[str, object]] = []
                seen: set[bytes] = set()
                for leaf in raw_leaves:
                    if not isinstance(leaf, Mapping):
                        raise ValueError("role-scoped leaf must be an object")
                    mode = leaf.get("mode")
                    coordinate = leaf.get("sampling_coordinate")
                    if not isinstance(mode, Mapping) or not isinstance(
                        coordinate, Mapping
                    ):
                        raise ValueError(
                            "role-scoped leaf lacks a spectral selection"
                        )
                    spin_hex = coordinate.get("spin_binary64_hex")
                    if not isinstance(spin_hex, str):
                        raise ValueError(
                            "role-scoped leaf spin identity is invalid"
                        )
                    pair = {
                        "mode": dict(mode),
                        "spin_binary64_hex": spin_hex,
                    }
                    identity = canonical_json_bytes(pair)
                    if identity not in seen:
                        seen.add(identity)
                        pairs.append(pair)
                scoped_policy["exact-spectral-selection"] = {"pairs": pairs}
        mapping = self.to_mapping()
        mapping["target"] = capability.value
        mapping["numerical_policy"] = scoped_policy
        return StudyRequest.from_mapping(mapping)


def load_study(path: str | Path) -> StudyRequest:
    study_path = Path(path)
    if study_path.stat().st_size > _MAX_STUDY_BYTES:
        raise ValueError(
            f"study file must not exceed {_MAX_STUDY_BYTES} bytes"
        )
    try:
        with study_path.open("r", encoding="utf-8") as handle:
            value = json.load(
                handle,
                object_pairs_hook=_reject_study_duplicate_keys,
                parse_constant=_reject_study_nonfinite,
            )
    except RecursionError as error:
        raise ValueError("study JSON nesting is too deep") from error
    if not isinstance(value, Mapping):
        raise ValueError("study document must contain one JSON object")
    _validate_json_depth(value)
    return StudyRequest.from_mapping(value)
