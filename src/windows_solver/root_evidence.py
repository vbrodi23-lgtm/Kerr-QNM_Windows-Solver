"""Authenticated background-root evidence, independent of response results."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
import re
from typing import Mapping

from .contracts import canonical_json_bytes
from .response_uncertainty import ComplexDisk


# Version 3 adds an explicit admissibility level to the authenticated complex
# disk.  A radius without the receipt level that authorised it is not current
# v3 evidence.  Version 2 centre-only receipts remain readable as seeds.
ROOT_EVIDENCE_SCHEMA = "windows-solver.authenticated-root-evidence/3"
_LEGACY_ROOT_EVIDENCE_SCHEMA = "windows-solver.authenticated-root-evidence/2"
ROOT_DEPENDENCY_KEY_SCHEMA = "windows-solver.root-dependency-key/2"
_HEX_64 = re.compile(r"[0-9a-f]{64}")


def _sha256(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _copy(value: object) -> object:
    return json.loads(canonical_json_bytes(value).decode("utf-8"))


def _digest(value: object, subject: str) -> str:
    if not isinstance(value, str) or _HEX_64.fullmatch(value) is None:
        raise ValueError(f"{subject} SHA-256 is invalid")
    return value


def _finite_optional(value: object, subject: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{subject} is invalid")
    converted = float(value)
    if not math.isfinite(converted) or converted < 0.0:
        raise ValueError(f"{subject} is invalid")
    return converted


def _finite(value: object, subject: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{subject} is invalid")
    converted = float(value)
    if not math.isfinite(converted):
        raise ValueError(f"{subject} is invalid")
    return converted


def _complex_mapping(value: complex) -> dict[str, float]:
    converted = complex(value)
    if not math.isfinite(converted.real) or not math.isfinite(converted.imag):
        raise ValueError("authenticated root is not finite")
    return {"real": converted.real, "imaginary": converted.imag}


def _complex_from_mapping(value: object) -> complex:
    if not isinstance(value, Mapping) or set(value) != {"real", "imaginary"}:
        raise ValueError("authenticated root mapping is invalid")
    real = value["real"]
    imaginary = value["imaginary"]
    if any(
        isinstance(item, bool) or not isinstance(item, (int, float))
        for item in (real, imaginary)
    ):
        raise ValueError("authenticated root mapping is invalid")
    root = complex(float(real), float(imaginary))
    if not math.isfinite(root.real) or not math.isfinite(root.imag):
        raise ValueError("authenticated root mapping is invalid")
    return root


@dataclass(frozen=True, slots=True)
class RootDependencyKey:
    """Exact root-sharing identity; it deliberately excludes mechanism output."""

    root_reference_id: str
    root_identity_sha256: str
    mode: Mapping[str, object]
    sampling_coordinate: Mapping[str, object]
    spin: float
    branch_identity: str
    equation_id: str
    backend_identity: str
    root_acceptance_policy_identity: str
    arithmetic_tier: str

    def __post_init__(self) -> None:
        for name in (
            "root_reference_id",
            "branch_identity",
            "equation_id",
            "arithmetic_tier",
        ):
            value = getattr(self, name)
            if not isinstance(value, str) or not value:
                raise ValueError(f"root dependency {name} is invalid")
        for name in (
            "root_identity_sha256",
            "backend_identity",
            "root_acceptance_policy_identity",
        ):
            _digest(getattr(self, name), f"root dependency {name}")
        for name in ("mode", "sampling_coordinate"):
            value = getattr(self, name)
            if not isinstance(value, Mapping):
                raise ValueError(f"root dependency {name} is invalid")
            object.__setattr__(self, name, _copy(dict(value)))
        object.__setattr__(self, "spin", _finite(self.spin, "root dependency spin"))

    @classmethod
    def from_leaf(
        cls, leaf: object, *, arithmetic_tier: str = "catalog-bound"
    ) -> "RootDependencyKey":
        mode = getattr(leaf, "leaf").mode
        if (
            not isinstance(mode, tuple)
            or len(mode) != 3
            or any(isinstance(item, bool) or not isinstance(item, int) for item in mode)
        ):
            raise ValueError("root dependency leaf mode is invalid")
        job = getattr(leaf, "job")
        return cls(
            root_reference_id=job.root.root_reference_id,
            root_identity_sha256=job.root.identity_sha256,
            mode={"ell": mode[0], "m": mode[1], "n": mode[2]},
            sampling_coordinate=job.sampling_coordinate.to_mapping(),
            spin=job.spin,
            branch_identity=job.root.branch_id,
            equation_id=job.equation_id,
            backend_identity=job.backend_identity.identity_sha256,
            root_acceptance_policy_identity=job.policy.identity_sha256,
            arithmetic_tier=arithmetic_tier,
        )

    def to_mapping(self) -> dict[str, object]:
        return {
            "schema": ROOT_DEPENDENCY_KEY_SCHEMA,
            "root_reference_id": self.root_reference_id,
            "root_identity_sha256": self.root_identity_sha256,
            "mode": _copy(self.mode),
            "sampling_coordinate": _copy(self.sampling_coordinate),
            "spin": self.spin,
            "branch_identity": self.branch_identity,
            "equation_id": self.equation_id,
            "backend_identity": self.backend_identity,
            "root_acceptance_policy_identity": self.root_acceptance_policy_identity,
            "arithmetic_tier": self.arithmetic_tier,
        }

    @property
    def sha256(self) -> str:
        return _sha256(self.to_mapping())


@dataclass(frozen=True, slots=True)
class AuthenticatedRootEvidence:
    """A root receipt that never depends on a mechanism response succeeding."""

    root_dependency_key: RootDependencyKey
    root_reference_id: str
    root_identity_sha256: str
    fixed_root: complex
    branch_identity: str
    equation_id: str
    source_root_mapping: Mapping[str, object] | None
    root_correction_upper_bound: float | None
    root_uncertainty_radius: float | None
    root_acceptance_policy_identity: str
    backend_identity: str
    source_receipt_sha256: str
    root_seal_sha256: str
    root_evidence_level: str | None = None
    root_evidence_schema: str = ROOT_EVIDENCE_SCHEMA

    def __post_init__(self) -> None:
        if not isinstance(self.root_dependency_key, RootDependencyKey):
            raise ValueError("root evidence dependency key is invalid")
        for name in ("root_reference_id", "branch_identity", "equation_id"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value:
                raise ValueError(f"root evidence {name} is invalid")
        for name in (
            "root_identity_sha256",
            "root_acceptance_policy_identity",
            "backend_identity",
            "source_receipt_sha256",
            "root_seal_sha256",
        ):
            _digest(getattr(self, name), f"root evidence {name}")
        if self.root_evidence_schema not in {
            ROOT_EVIDENCE_SCHEMA,
            _LEGACY_ROOT_EVIDENCE_SCHEMA,
        }:
            raise ValueError("root evidence schema is invalid")
        _complex_mapping(self.fixed_root)
        if self.source_root_mapping is not None:
            if not isinstance(self.source_root_mapping, Mapping):
                raise ValueError("root evidence source mapping is invalid")
            object.__setattr__(
                self, "source_root_mapping", _copy(dict(self.source_root_mapping))
            )
        for name in ("root_correction_upper_bound", "root_uncertainty_radius"):
            object.__setattr__(self, name, _finite_optional(getattr(self, name), name))
        if (
            self.root_uncertainty_radius is not None
            and self.root_uncertainty_radius <= 0.0
        ):
            raise ValueError("root uncertainty radius must be strictly positive")
        level = self.root_evidence_level
        if self.root_uncertainty_radius is None:
            if level not in {None, "SEED_ONLY"}:
                raise ValueError("centre-only root evidence must be a seed")
            level = "SEED_ONLY"
        elif level not in {"SCREENED", "CERTIFIED"}:
            raise ValueError(
                "bounded root evidence requires an explicit admissibility level"
            )
        if (
            self.root_evidence_schema == _LEGACY_ROOT_EVIDENCE_SCHEMA
            and (self.root_uncertainty_radius is not None or level != "SEED_ONLY")
        ):
            raise ValueError("legacy root evidence cannot authenticate a root disk")
        object.__setattr__(self, "root_evidence_level", level)
        if self.root_dependency_key.root_reference_id != self.root_reference_id:
            raise ValueError("root evidence reference disagrees with dependency key")
        if self.root_dependency_key.root_identity_sha256 != self.root_identity_sha256:
            raise ValueError("root evidence identity disagrees with dependency key")
        if self.root_dependency_key.branch_identity != self.branch_identity:
            raise ValueError("root evidence branch disagrees with dependency key")
        if self.root_dependency_key.equation_id != self.equation_id:
            raise ValueError("root evidence equation disagrees with dependency key")
        if self.root_dependency_key.backend_identity != self.backend_identity:
            raise ValueError("root evidence backend disagrees with dependency key")
        if (
            self.root_dependency_key.root_acceptance_policy_identity
            != self.root_acceptance_policy_identity
        ):
            raise ValueError("root evidence policy disagrees with dependency key")
        if self.root_seal_sha256 != _sha256(self._content()):
            raise ValueError("root evidence seal authentication failed")

    @classmethod
    def from_bound_leaf(cls, leaf: object) -> "AuthenticatedRootEvidence":
        job = getattr(leaf, "job")
        key = RootDependencyKey.from_leaf(leaf)
        content = {
            "schema": ROOT_EVIDENCE_SCHEMA,
            "root_dependency_key": key.to_mapping(),
            "root_dependency_key_sha256": key.sha256,
            "root_reference_id": job.root.root_reference_id,
            "root_identity_sha256": job.root.identity_sha256,
            "fixed_root": _complex_mapping(job.root.omega),
            "branch_identity": job.root.branch_id,
            "equation_id": job.equation_id,
            "source_root_mapping": (
                None
                if job.source_root_mapping is None
                else _copy(dict(job.source_root_mapping))
            ),
            # No reviewed root-uncertainty disk is inferred from catalogue
            # provenance.  The unavailable values remain explicit evidence.
            "root_correction_upper_bound": None,
            "root_uncertainty_radius": None,
            "root_evidence_level": "SEED_ONLY",
            "root_acceptance_policy_identity": job.policy.identity_sha256,
            "backend_identity": job.backend_identity.identity_sha256,
            "source_receipt_sha256": job.root.owner_data_sha256,
        }
        return cls(
            root_dependency_key=key,
            root_reference_id=str(content["root_reference_id"]),
            root_identity_sha256=str(content["root_identity_sha256"]),
            fixed_root=_complex_from_mapping(content["fixed_root"]),
            branch_identity=str(content["branch_identity"]),
            equation_id=str(content["equation_id"]),
            source_root_mapping=content["source_root_mapping"],
            root_correction_upper_bound=None,
            root_uncertainty_radius=None,
            root_acceptance_policy_identity=str(
                content["root_acceptance_policy_identity"]
            ),
            backend_identity=str(content["backend_identity"]),
            source_receipt_sha256=str(content["source_receipt_sha256"]),
            root_seal_sha256=_sha256(content),
            root_evidence_level="SEED_ONLY",
        )

    @classmethod
    def from_seal(
        cls,
        leaf: object,
        *,
        fixed_root: complex,
        branch_identity: str,
        source_receipt_sha256: str,
    ) -> "AuthenticatedRootEvidence":
        """Reissue old sealed evidence under the root-only receipt contract."""

        job = getattr(leaf, "job")
        key = RootDependencyKey.from_leaf(leaf)
        content = {
            "schema": ROOT_EVIDENCE_SCHEMA,
            "root_dependency_key": key.to_mapping(),
            "root_dependency_key_sha256": key.sha256,
            "root_reference_id": job.root.root_reference_id,
            "root_identity_sha256": job.root.identity_sha256,
            "fixed_root": _complex_mapping(fixed_root),
            "branch_identity": branch_identity,
            "equation_id": job.equation_id,
            "source_root_mapping": (
                None
                if job.source_root_mapping is None
                else _copy(dict(job.source_root_mapping))
            ),
            "root_correction_upper_bound": None,
            "root_uncertainty_radius": None,
            "root_evidence_level": "SEED_ONLY",
            "root_acceptance_policy_identity": job.policy.identity_sha256,
            "backend_identity": job.backend_identity.identity_sha256,
            "source_receipt_sha256": source_receipt_sha256,
        }
        return cls(
            root_dependency_key=key,
            root_reference_id=str(content["root_reference_id"]),
            root_identity_sha256=str(content["root_identity_sha256"]),
            fixed_root=_complex_from_mapping(content["fixed_root"]),
            branch_identity=str(content["branch_identity"]),
            equation_id=str(content["equation_id"]),
            source_root_mapping=content["source_root_mapping"],
            root_correction_upper_bound=None,
            root_uncertainty_radius=None,
            root_acceptance_policy_identity=str(
                content["root_acceptance_policy_identity"]
            ),
            backend_identity=str(content["backend_identity"]),
            source_receipt_sha256=str(content["source_receipt_sha256"]),
            root_seal_sha256=_sha256(content),
            root_evidence_level="SEED_ONLY",
        )

    @classmethod
    def from_authenticated_disk(
        cls,
        leaf: object,
        *,
        fixed_root: complex,
        root_uncertainty_radius: float,
        source_receipt_sha256: str,
        evidence_level: str,
    ) -> "AuthenticatedRootEvidence":
        """Issue current root evidence only from an explicit nonzero disk.

        Catalogue and adapter centre values remain seeds.  A caller may invoke
        this constructor only after it holds the separate authenticated root
        receipt that supplied the disk radius.
        """

        if evidence_level not in {"SCREENED", "CERTIFIED"}:
            raise ValueError("root evidence level is invalid")
        if float(root_uncertainty_radius) <= 0.0:
            raise ValueError("root uncertainty radius must be strictly positive")
        job = getattr(leaf, "job")
        key = RootDependencyKey.from_leaf(leaf)
        content = {
            "schema": ROOT_EVIDENCE_SCHEMA,
            "root_dependency_key": key.to_mapping(),
            "root_dependency_key_sha256": key.sha256,
            "root_reference_id": job.root.root_reference_id,
            "root_identity_sha256": job.root.identity_sha256,
            "fixed_root": _complex_mapping(fixed_root),
            "branch_identity": job.root.branch_id,
            "equation_id": job.equation_id,
            "source_root_mapping": (
                None
                if job.source_root_mapping is None
                else _copy(dict(job.source_root_mapping))
            ),
            "root_correction_upper_bound": None,
            "root_uncertainty_radius": float(root_uncertainty_radius),
            "root_evidence_level": evidence_level,
            "root_acceptance_policy_identity": job.policy.identity_sha256,
            "backend_identity": job.backend_identity.identity_sha256,
            "source_receipt_sha256": source_receipt_sha256,
        }
        return cls(
            root_dependency_key=key,
            root_reference_id=str(content["root_reference_id"]),
            root_identity_sha256=str(content["root_identity_sha256"]),
            fixed_root=_complex_from_mapping(content["fixed_root"]),
            branch_identity=str(content["branch_identity"]),
            equation_id=str(content["equation_id"]),
            source_root_mapping=content["source_root_mapping"],
            root_correction_upper_bound=None,
            root_uncertainty_radius=float(content["root_uncertainty_radius"]),
            root_acceptance_policy_identity=str(
                content["root_acceptance_policy_identity"]
            ),
            backend_identity=str(content["backend_identity"]),
            source_receipt_sha256=str(content["source_receipt_sha256"]),
            root_seal_sha256=_sha256(content),
            root_evidence_level=str(content["root_evidence_level"]),
        )

    @property
    def evidence_level(self) -> str:
        """Return the current admissibility level, never inferred from a seed."""

        assert self.root_evidence_level is not None
        return self.root_evidence_level

    @property
    def root_disk(self) -> ComplexDisk | None:
        """Return the authenticated disk, or ``None`` for a centre-only seed."""

        if self.root_uncertainty_radius is None:
            return None
        return ComplexDisk(self.fixed_root, self.root_uncertainty_radius)

    def _content(self) -> dict[str, object]:
        return {
            "schema": self.root_evidence_schema,
            "root_dependency_key": self.root_dependency_key.to_mapping(),
            "root_dependency_key_sha256": self.root_dependency_key.sha256,
            "root_reference_id": self.root_reference_id,
            "root_identity_sha256": self.root_identity_sha256,
            "fixed_root": _complex_mapping(self.fixed_root),
            "branch_identity": self.branch_identity,
            "equation_id": self.equation_id,
            "source_root_mapping": (
                None
                if self.source_root_mapping is None
                else _copy(self.source_root_mapping)
            ),
            "root_correction_upper_bound": self.root_correction_upper_bound,
            "root_uncertainty_radius": self.root_uncertainty_radius,
            **(
                {"root_evidence_level": self.evidence_level}
                if self.root_evidence_schema == ROOT_EVIDENCE_SCHEMA
                else {}
            ),
            "root_acceptance_policy_identity": self.root_acceptance_policy_identity,
            "backend_identity": self.backend_identity,
            "source_receipt_sha256": self.source_receipt_sha256,
        }

    def to_mapping(self) -> dict[str, object]:
        return {**self._content(), "root_seal_sha256": self.root_seal_sha256}

    @classmethod
    def from_mapping(cls, value: object) -> "AuthenticatedRootEvidence":
        v3_fields = {
            "schema",
            "root_dependency_key",
            "root_dependency_key_sha256",
            "root_reference_id",
            "root_identity_sha256",
            "fixed_root",
            "branch_identity",
            "equation_id",
            "source_root_mapping",
            "root_correction_upper_bound",
            "root_uncertainty_radius",
            "root_evidence_level",
            "root_acceptance_policy_identity",
            "backend_identity",
            "source_receipt_sha256",
            "root_seal_sha256",
        }
        legacy_fields = v3_fields - {"root_evidence_level"}
        if not isinstance(value, Mapping) or frozenset(value) not in {
            frozenset(v3_fields), frozenset(legacy_fields)
        }:
            raise ValueError("root evidence schema is invalid")
        schema = value["schema"]
        if schema not in {ROOT_EVIDENCE_SCHEMA, _LEGACY_ROOT_EVIDENCE_SCHEMA}:
            raise ValueError("root evidence schema is invalid")
        if schema == ROOT_EVIDENCE_SCHEMA and set(value) != v3_fields:
            raise ValueError("root evidence schema is invalid")
        if schema == _LEGACY_ROOT_EVIDENCE_SCHEMA and set(value) != legacy_fields:
            raise ValueError("root evidence schema is invalid")
        raw_key = value["root_dependency_key"]
        key_fields = {
            "schema",
            "root_reference_id",
            "root_identity_sha256",
            "mode",
            "sampling_coordinate",
            "spin",
            "branch_identity",
            "equation_id",
            "backend_identity",
            "root_acceptance_policy_identity",
            "arithmetic_tier",
        }
        if (
            not isinstance(raw_key, Mapping)
            or set(raw_key) != key_fields
            or raw_key.get("schema") != ROOT_DEPENDENCY_KEY_SCHEMA
        ):
            raise ValueError("root evidence dependency key is invalid")
        key = RootDependencyKey(
            root_reference_id=str(raw_key.get("root_reference_id")),
            root_identity_sha256=str(raw_key.get("root_identity_sha256")),
            mode=raw_key.get("mode"),  # type: ignore[arg-type]
            sampling_coordinate=raw_key.get("sampling_coordinate"),  # type: ignore[arg-type]
            spin=raw_key.get("spin"),  # type: ignore[arg-type]
            branch_identity=str(raw_key.get("branch_identity")),
            equation_id=str(raw_key.get("equation_id")),
            backend_identity=str(raw_key.get("backend_identity")),
            root_acceptance_policy_identity=str(
                raw_key.get("root_acceptance_policy_identity")
            ),
            arithmetic_tier=str(raw_key.get("arithmetic_tier")),
        )
        if value["root_dependency_key_sha256"] != key.sha256:
            raise ValueError("root evidence dependency digest is invalid")
        return cls(
            root_dependency_key=key,
            root_reference_id=str(value["root_reference_id"]),
            root_identity_sha256=str(value["root_identity_sha256"]),
            fixed_root=_complex_from_mapping(value["fixed_root"]),
            branch_identity=str(value["branch_identity"]),
            equation_id=str(value["equation_id"]),
            source_root_mapping=value["source_root_mapping"],  # type: ignore[arg-type]
            root_correction_upper_bound=value["root_correction_upper_bound"],
            root_uncertainty_radius=value["root_uncertainty_radius"],
            root_acceptance_policy_identity=str(
                value["root_acceptance_policy_identity"]
            ),
            backend_identity=str(value["backend_identity"]),
            source_receipt_sha256=str(value["source_receipt_sha256"]),
            root_seal_sha256=str(value["root_seal_sha256"]),
            root_evidence_level=(
                str(value["root_evidence_level"])
                if schema == ROOT_EVIDENCE_SCHEMA else "SEED_ONLY"
            ),
            root_evidence_schema=str(schema),
        )

    def validate_for(self, leaf: object) -> None:
        expected = RootDependencyKey.from_leaf(leaf)
        if self.root_dependency_key != expected:
            raise ValueError("root evidence exact dependency key is incompatible")
        job = getattr(leaf, "job")
        if self.source_root_mapping != job.source_root_mapping:
            raise ValueError("root evidence source mapping is incompatible")


__all__ = [
    "AuthenticatedRootEvidence",
    "ROOT_DEPENDENCY_KEY_SCHEMA",
    "ROOT_EVIDENCE_SCHEMA",
    "RootDependencyKey",
]
