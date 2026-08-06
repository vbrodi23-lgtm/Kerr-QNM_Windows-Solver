"""Content-addressed artifacts, cache bindings, and run storage."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from types import MappingProxyType
from typing import Mapping

from .contracts import (
    Capability,
    CarrierState,
    EvidenceState,
    ExecutionState,
    NumericalState,
    ScientificState,
    canonical_json_bytes,
)


class ArtifactVerificationError(ValueError):
    pass


_ARTIFACT_ID = re.compile(r"[0-9a-f]{64}")
_RUN_ID = re.compile(r"[0-9a-f]{32}")


def _validate_artifact_identity(value: object) -> str:
    if not isinstance(value, str) or _ARTIFACT_ID.fullmatch(value) is None:
        raise ArtifactVerificationError("artifact identity is invalid")
    return value


def _validate_cache_identity(value: object) -> str:
    if not isinstance(value, str) or _ARTIFACT_ID.fullmatch(value) is None:
        raise ArtifactVerificationError("cache identity is invalid")
    return value


def _validate_run_identity(value: object) -> str:
    if not isinstance(value, str) or _RUN_ID.fullmatch(value) is None:
        raise ArtifactVerificationError("run identity is invalid")
    return value


def _freeze_json(value: object) -> object:
    """Return a deeply immutable snapshot of a JSON-compatible value."""

    if isinstance(value, Mapping):
        if not all(isinstance(key, str) for key in value):
            raise TypeError("JSON object keys must be strings")
        return MappingProxyType(
            {key: _freeze_json(item) for key, item in value.items()}
        )
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_json(item) for item in value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(f"value is not JSON-compatible: {type(value).__name__}")


def _thaw_json(value: object) -> object:
    """Return ordinary dictionaries and lists for hashing and JSON output."""

    if isinstance(value, Mapping):
        return {key: _thaw_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_thaw_json(item) for item in value]
    return value


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"duplicate JSON key: {key}")
        value[key] = item
    return value


def _reject_nonfinite_constant(value: str) -> object:
    raise ValueError(f"non-finite JSON number: {value}")


def _load_canonical_json(path: Path, subject: str) -> object:
    try:
        content = path.read_bytes()
        value = json.loads(
            content.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_nonfinite_constant,
        )
        canonical = canonical_json_bytes(value)
    except (
        OSError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        RecursionError,
        TypeError,
        ValueError,
    ) as error:
        raise ArtifactVerificationError(f"{subject} is unreadable") from error
    if content != canonical:
        raise ArtifactVerificationError(f"{subject} JSON is not canonical")
    return value


@dataclass(frozen=True, slots=True)
class ArtifactEnvelope:
    schema_version: int
    artifact_type: str
    capability: Capability
    provider: Mapping[str, object]
    request: Mapping[str, object]
    upstream_artifact_ids: tuple[str, ...]
    payload: Mapping[str, object]
    evidence: EvidenceState

    def __post_init__(self) -> None:
        for name in ("provider", "request", "payload"):
            frozen = _freeze_json(getattr(self, name))
            if not isinstance(frozen, Mapping):
                raise TypeError(f"{name} must be an object")
            object.__setattr__(self, name, frozen)
        object.__setattr__(self, "upstream_artifact_ids", tuple(self.upstream_artifact_ids))

    def identity_mapping(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "artifact_type": self.artifact_type,
            "capability": self.capability.value,
            "provider": _thaw_json(self.provider),
            "request": _thaw_json(self.request),
            "upstream_artifact_ids": list(self.upstream_artifact_ids),
            "payload": _thaw_json(self.payload),
            "evidence": self.evidence.to_mapping(),
        }

    @property
    def artifact_id(self) -> str:
        return hashlib.sha256(canonical_json_bytes(self.identity_mapping())).hexdigest()

    def to_mapping(self) -> dict[str, object]:
        return {"artifact_id": self.artifact_id, **self.identity_mapping()}

    @classmethod
    def from_mapping(cls, mapping: Mapping[str, object]) -> "ArtifactEnvelope":
        expected = {
            "artifact_id",
            "schema_version",
            "artifact_type",
            "capability",
            "provider",
            "request",
            "upstream_artifact_ids",
            "payload",
            "evidence",
        }
        if set(mapping) != expected:
            raise ArtifactVerificationError("artifact envelope fields are invalid")
        try:
            evidence_mapping = mapping["evidence"]
            if not isinstance(evidence_mapping, Mapping):
                raise TypeError
            if set(evidence_mapping) != {
                "carrier",
                "execution",
                "numerical",
                "scientific",
            }:
                raise ArtifactVerificationError(
                    "artifact evidence fields are invalid"
                )
            evidence = EvidenceState(
                carrier=CarrierState(evidence_mapping["carrier"]),
                execution=ExecutionState(evidence_mapping["execution"]),
                numerical=NumericalState(evidence_mapping["numerical"]),
                scientific=ScientificState(evidence_mapping["scientific"]),
            )
            provider = mapping["provider"]
            request = mapping["request"]
            payload = mapping["payload"]
            upstream = mapping["upstream_artifact_ids"]
            if not all(isinstance(item, Mapping) for item in (provider, request, payload)):
                raise TypeError
            if not isinstance(upstream, list) or not all(
                isinstance(item, str) for item in upstream
            ):
                raise TypeError
            if any(_ARTIFACT_ID.fullmatch(item) is None for item in upstream):
                raise TypeError
            schema_version = mapping["schema_version"]
            artifact_type = mapping["artifact_type"]
            if (
                isinstance(schema_version, bool)
                or not isinstance(schema_version, int)
                or schema_version != 1
            ):
                raise TypeError
            if not isinstance(artifact_type, str) or not artifact_type.strip():
                raise TypeError
            envelope = cls(
                schema_version=schema_version,
                artifact_type=artifact_type,
                capability=Capability(mapping["capability"]),
                provider=dict(provider),
                request=dict(request),
                upstream_artifact_ids=tuple(upstream),
                payload=dict(payload),
                evidence=evidence,
            )
        except ArtifactVerificationError:
            raise
        except (KeyError, RecursionError, TypeError, ValueError) as error:
            raise ArtifactVerificationError("artifact envelope values are invalid") from error
        embedded_id = mapping["artifact_id"]
        _validate_artifact_identity(embedded_id)
        try:
            computed_id = envelope.artifact_id
        except (RecursionError, TypeError, ValueError) as error:
            raise ArtifactVerificationError(
                "artifact content cannot be canonicalized"
            ) from error
        if embedded_id != computed_id:
            raise ArtifactVerificationError("artifact content hash mismatch")
        return envelope


def computation_cache_key(
    capability: Capability,
    provider: Mapping[str, object],
    request: Mapping[str, object],
    upstream_artifact_ids: tuple[str, ...],
) -> str:
    material = {
        "capability": capability.value,
        "provider": _thaw_json(provider),
        "request": _thaw_json(request),
        "upstream_artifact_ids": list(upstream_artifact_ids),
    }
    return hashlib.sha256(canonical_json_bytes(material)).hexdigest()


def _atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    except BaseException:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


class ArtifactStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()
        self.artifacts_directory = self.root / "artifacts"
        self.cache_directory = self.root / "cache"
        self.runs_directory = self.root / "runs"

    def _contained_path(
        self, directory: Path, filename: str, subject: str
    ) -> Path:
        resolved_directory = directory.resolve()
        if (
            directory.is_symlink()
            or not resolved_directory.is_relative_to(self.root)
        ):
            raise ArtifactVerificationError(f"{subject} storage path is invalid")
        path = directory / filename
        if path.is_symlink() or not path.resolve().is_relative_to(resolved_directory):
            raise ArtifactVerificationError(f"{subject} storage path is invalid")
        return path

    def put_artifact(self, envelope: ArtifactEnvelope) -> str:
        artifact_id = envelope.artifact_id
        path = self._contained_path(
            self.artifacts_directory, f"{artifact_id}.json", "artifact"
        )
        if path.exists():
            self.verify_artifact(artifact_id)
        else:
            _atomic_write(path, canonical_json_bytes(envelope.to_mapping()))
        return artifact_id

    def load_artifact(self, artifact_id: str) -> ArtifactEnvelope:
        artifact_id = _validate_artifact_identity(artifact_id)
        path = self._contained_path(
            self.artifacts_directory, f"{artifact_id}.json", "artifact"
        )
        raw = _load_canonical_json(path, f"artifact {artifact_id}")
        if not isinstance(raw, Mapping):
            raise ArtifactVerificationError("artifact envelope must be an object")
        envelope = ArtifactEnvelope.from_mapping(raw)
        if envelope.artifact_id != artifact_id:
            raise ArtifactVerificationError("artifact filename hash mismatch")
        return envelope

    def verify_artifact(self, artifact_id: str) -> bool:
        self.load_artifact(artifact_id)
        return True

    def lookup_cache(self, cache_key: str) -> ArtifactEnvelope | None:
        cache_key = _validate_cache_identity(cache_key)
        path = self._contained_path(
            self.cache_directory, f"{cache_key}.json", "cache"
        )
        if not path.exists():
            return None
        try:
            value = _load_canonical_json(path, f"cache binding {cache_key}")
            if not isinstance(value, Mapping) or set(value) != {
                "cache_key",
                "artifact_id",
            }:
                raise TypeError
            embedded_cache_key = value["cache_key"]
            artifact_id = value["artifact_id"]
        except (ArtifactVerificationError, KeyError, TypeError) as error:
            raise ArtifactVerificationError("cache binding is invalid") from error
        if embedded_cache_key != cache_key:
            raise ArtifactVerificationError("cache binding identity mismatch")
        artifact_id = _validate_artifact_identity(artifact_id)
        envelope = self.load_artifact(artifact_id)
        material_key = computation_cache_key(
            envelope.capability,
            envelope.provider,
            envelope.request,
            envelope.upstream_artifact_ids,
        )
        if material_key != cache_key:
            raise ArtifactVerificationError(
                "cache binding does not match artifact"
            )
        return envelope

    def bind_cache(self, cache_key: str, artifact_id: str) -> None:
        cache_key = _validate_cache_identity(cache_key)
        artifact_id = _validate_artifact_identity(artifact_id)
        envelope = self.load_artifact(artifact_id)
        material_key = computation_cache_key(
            envelope.capability,
            envelope.provider,
            envelope.request,
            envelope.upstream_artifact_ids,
        )
        if material_key != cache_key:
            raise ArtifactVerificationError(
                "cache binding does not match artifact"
            )
        path = self._contained_path(
            self.cache_directory, f"{cache_key}.json", "cache"
        )
        _atomic_write(
            path,
            canonical_json_bytes(
                {"cache_key": cache_key, "artifact_id": artifact_id}
            ),
        )

    def put_run_mapping(self, run_id: str, mapping: Mapping[str, object]) -> None:
        run_id = _validate_run_identity(run_id)
        if mapping.get("run_id") != run_id:
            raise ArtifactVerificationError("run record identity mismatch")
        path = self._contained_path(
            self.runs_directory, f"{run_id}.json", "run"
        )
        _atomic_write(
            path,
            canonical_json_bytes(dict(mapping)),
        )

    def load_run_mapping(self, run_id: str) -> dict[str, object]:
        run_id = _validate_run_identity(run_id)
        path = self._contained_path(
            self.runs_directory, f"{run_id}.json", "run"
        )
        value = _load_canonical_json(path, f"run {run_id}")
        if not isinstance(value, dict):
            raise ArtifactVerificationError("run record must be an object")
        return value
