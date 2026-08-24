"""Private, per-user reuse of completed promoted root readouts.

A promoted precision stage issues many Julia root readouts before the component
it belongs to becomes committable evidence.  The campaign checkpoint records a
stage only once that whole component is assembled and validated, so an
interrupted stage previously discarded every readout it had already finished.

This store keeps those finished readouts as a work cache.  A readout is
addressed by the digest of the exact worker request together with the identity
of the runtime that answered it, so an entry is reusable only for a byte
identical request under a byte identical worker.  Reuse therefore returns the
response the worker would have recomputed, and never widens what the campaign
is willing to treat as evidence: stage assembly, component validation, and
branch authentication are unchanged and still run over the reused response.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Mapping

from .contracts import canonical_json_bytes
from .root_evidence import AuthenticatedRootEvidence, RootDependencyKey


ROOT_READOUT_CACHE_SCHEMA_VERSION = 2
ROOT_READOUT_STORE_DIRECTORY_NAME = "root-readouts-" + "v" + str(
    ROOT_READOUT_CACHE_SCHEMA_VERSION
)
ROOT_EVIDENCE_STORE_DIRECTORY_NAME = "authenticated-root-evidence-v1"
_HEX_64 = re.compile(r"[0-9a-f]{64}")
_ENTRY_FIELDS = frozenset({
    "schema_version",
    "readout_identity_sha256",
    "request_sha256",
    "runtime_identity_sha256",
    "created_utc",
    "response",
    "worker_response_receipt",
})


def _sha256(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    output: dict[str, object] = {}
    for key, value in pairs:
        if key in output:
            raise ValueError(f"duplicate root-readout cache JSON key: {key}")
        output[key] = value
    return output


def _load_json(path: Path) -> object:
    try:
        return json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=lambda item: (_ for _ in ()).throw(
                ValueError(f"root-readout cache contains non-finite constant {item}")
            ),
        )
    except json.JSONDecodeError as error:
        raise ValueError("root-readout cache entry is not valid JSON") from error


def _atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(canonical_json_bytes(value))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    except BaseException:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def runtime_identity_sha256(runtime_provenance: Mapping[str, object]) -> str:
    """Bind a cached readout to the exact runtime that produced it."""

    if not isinstance(runtime_provenance, Mapping):
        raise ValueError("root-readout runtime provenance must be a mapping")
    return _sha256({
        "schema_version": ROOT_READOUT_CACHE_SCHEMA_VERSION,
        "runtime_provenance": dict(runtime_provenance),
    })


def root_readout_identity_sha256(
    *, request_sha256: str, runtime_identity: str
) -> str:
    """Address one readout by its request bytes and its answering runtime."""

    for name, value in (
        ("request", request_sha256),
        ("runtime identity", runtime_identity),
    ):
        if not isinstance(value, str) or _HEX_64.fullmatch(value) is None:
            raise ValueError(f"root-readout {name} SHA-256 is invalid")
    return _sha256({
        "schema_version": ROOT_READOUT_CACHE_SCHEMA_VERSION,
        "request_sha256": request_sha256,
        "runtime_identity_sha256": runtime_identity,
    })


class RootReadoutLookupStatus(StrEnum):
    MISSING = "missing"
    HIT = "hit"
    CORRUPT = "corrupt"


@dataclass(frozen=True, slots=True)
class RootReadoutLookup:
    status: RootReadoutLookupStatus
    path: Path | None = None
    response: Mapping[str, object] | None = None
    worker_response_receipt: Mapping[str, object] | None = None
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class RootReadoutStoredEntry:
    """One self-addressed immutable root-readout cache entry.

    This is intentionally a transport object rather than a root seal.  A
    caller must still authenticate its worker receipt and bind the readout to
    the current campaign/root before it may authorize fixed-root work.
    """

    path: Path
    readout_identity_sha256: str
    request_sha256: str
    runtime_identity_sha256: str
    response: Mapping[str, object]
    worker_response_receipt: Mapping[str, object] | None


class RootReadoutStore:
    """One immutable entry per (request, runtime) readout identity."""

    def __init__(self, root: str | os.PathLike[str] | Path) -> None:
        self.root = Path(root)

    @property
    def stored_count(self) -> int:
        if not self.root.is_dir():
            return 0
        return sum(path.is_file() for path in self.root.glob("*.json"))

    def _entry_path(self, readout_identity_sha256: str) -> Path:
        if _HEX_64.fullmatch(readout_identity_sha256) is None:
            raise ValueError("root-readout identity SHA-256 is invalid")
        return self.root / f"{readout_identity_sha256}.json"

    @staticmethod
    def _entry_from_mapping(
        value: object, *, path: Path
    ) -> RootReadoutStoredEntry:
        if not isinstance(value, Mapping) or set(value) != _ENTRY_FIELDS:
            raise ValueError("root-readout cache entry fields are invalid")
        if value["schema_version"] != ROOT_READOUT_CACHE_SCHEMA_VERSION:
            raise ValueError("root-readout cache schema is invalid")
        for name in (
            "readout_identity_sha256",
            "request_sha256",
            "runtime_identity_sha256",
        ):
            digest = value[name]
            if not isinstance(digest, str) or _HEX_64.fullmatch(digest) is None:
                raise ValueError(f"root-readout cache {name} is invalid")
        if not isinstance(value["created_utc"], str) or not value["created_utc"]:
            raise ValueError("root-readout cache creation stamp is invalid")
        request_sha256 = value["request_sha256"]
        runtime_identity = value["runtime_identity_sha256"]
        expected_identity = root_readout_identity_sha256(
            request_sha256=request_sha256, runtime_identity=runtime_identity
        )
        if value["readout_identity_sha256"] != expected_identity:
            raise ValueError("root-readout cache identity is not self-consistent")
        if path.name != f"{expected_identity}.json" or path.is_symlink():
            raise ValueError("root-readout cache filename does not match identity")
        response = value["response"]
        if not isinstance(response, Mapping):
            raise ValueError("root-readout cache response is invalid")
        if response.get("status") != "ok":
            raise ValueError("root-readout cache response is not a successful readout")
        if response.get("request_sha256") != request_sha256:
            raise ValueError("root-readout cache response request digest is invalid")
        receipt = value["worker_response_receipt"]
        if receipt is not None and not isinstance(receipt, Mapping):
            raise ValueError("root-readout cache worker response receipt is invalid")
        return RootReadoutStoredEntry(
            path=path,
            readout_identity_sha256=expected_identity,
            request_sha256=request_sha256,
            runtime_identity_sha256=runtime_identity,
            response=dict(response),
            worker_response_receipt=(
                None if receipt is None else dict(receipt)
            ),
        )

    @classmethod
    def _validate_entry(
        cls, value: object, *, request_sha256: str, runtime_identity: str, path: Path
    ) -> RootReadoutStoredEntry:
        entry = cls._entry_from_mapping(value, path=path)
        # An entry is only reusable for the exact request and runtime it was
        # recorded against; a mismatch here means the file does not describe the
        # readout its own filename claims.
        if entry.request_sha256 != request_sha256:
            raise ValueError("root-readout cache request digest does not match")
        if entry.runtime_identity_sha256 != runtime_identity:
            raise ValueError("root-readout cache runtime identity does not match")
        return entry

    @classmethod
    def default(cls) -> "RootReadoutStore":
        """Return the same cache location used by the promoted worker adapter."""

        override = os.environ.get("KERR_QNM_ROOT_READOUT_CACHE_ROOT")
        if override:
            return cls(Path(override))
        runtime_root = os.environ.get("KERR_QNM_RUNTIME_ROOT")
        if runtime_root:
            return cls(Path(runtime_root) / ROOT_READOUT_STORE_DIRECTORY_NAME)
        local_app_data = os.environ.get("LOCALAPPDATA")
        if os.name == "nt" and local_app_data:
            return cls(
                Path(local_app_data)
                / "Kerr-QNM_Windows-Solver"
                / "runtime-1"
                / ROOT_READOUT_STORE_DIRECTORY_NAME
            )
        return cls(Path.cwd() / ".runtime" / ROOT_READOUT_STORE_DIRECTORY_NAME)

    def entries(self) -> tuple[RootReadoutStoredEntry, ...]:
        """Read every trusted entry, rejecting a corrupt cache instead of guessing."""

        if not self.root.exists():
            return ()
        if not self.root.is_dir():
            raise ValueError("root-readout cache store is not a directory")
        result: list[RootReadoutStoredEntry] = []
        for path in sorted(self.root.glob("*.json"), key=lambda item: item.name):
            try:
                result.append(self._entry_from_mapping(_load_json(path), path=path))
            except (OSError, ValueError, UnicodeDecodeError) as error:
                raise ValueError(
                    f"root-readout cache entry is corrupt: {path}: {error}"
                ) from error
        return tuple(result)

    def lookup(
        self, *, request_sha256: str, runtime_identity: str
    ) -> RootReadoutLookup:
        """Return a reusable readout, or report why one is unavailable."""

        identity = root_readout_identity_sha256(
            request_sha256=request_sha256, runtime_identity=runtime_identity
        )
        path = self._entry_path(identity)
        if not path.is_file() or path.is_symlink():
            return RootReadoutLookup(RootReadoutLookupStatus.MISSING, path=path)
        try:
            entry = self._validate_entry(
                _load_json(path),
                request_sha256=request_sha256,
                runtime_identity=runtime_identity,
                path=path,
            )
        except (OSError, ValueError, UnicodeDecodeError) as error:
            return RootReadoutLookup(
                RootReadoutLookupStatus.CORRUPT, path=path, reason=str(error)
            )
        return RootReadoutLookup(
            RootReadoutLookupStatus.HIT,
            path=path,
            response=dict(entry.response),
            worker_response_receipt=(
                None
                if entry.worker_response_receipt is None
                else dict(entry.worker_response_receipt)
            ),
        )

    def publish(
        self,
        *,
        request_sha256: str,
        runtime_identity: str,
        response: Mapping[str, object],
        worker_response_receipt: Mapping[str, object] | None = None,
    ) -> Path:
        """Retain one successful readout for reuse after an interruption."""

        if not isinstance(response, Mapping) or response.get("status") != "ok":
            raise ValueError("root-readout cache retains successful readouts only")
        if response.get("request_sha256") != request_sha256:
            raise ValueError("root-readout response request digest is invalid")
        identity = root_readout_identity_sha256(
            request_sha256=request_sha256, runtime_identity=runtime_identity
        )
        path = self._entry_path(identity)
        _atomic_json(path, {
            "schema_version": ROOT_READOUT_CACHE_SCHEMA_VERSION,
            "readout_identity_sha256": identity,
            "request_sha256": request_sha256,
            "runtime_identity_sha256": runtime_identity,
            "created_utc": datetime.now(timezone.utc)
            .isoformat()
            .replace("+00:00", "Z"),
            "response": dict(response),
            "worker_response_receipt": (
                None
                if worker_response_receipt is None
                else dict(worker_response_receipt)
            ),
        })
        return path

    def invalidate(
        self, *, request_sha256: str, runtime_identity: str
    ) -> bool:
        """Remove only the exact entry rejected by post-worker validation."""

        identity = root_readout_identity_sha256(
            request_sha256=request_sha256, runtime_identity=runtime_identity
        )
        path = self._entry_path(identity)
        if not path.is_file() or path.is_symlink():
            return False
        path.unlink()
        return True


class RootEvidenceStore:
    """Durable immutable root receipts, separate from worker readout reuse."""

    def __init__(self, root: str | os.PathLike[str] | Path) -> None:
        self.root = Path(root)

    @property
    def stored_count(self) -> int:
        if not self.root.is_dir():
            return 0
        return sum(path.is_file() for path in self.root.glob("*.json"))

    @classmethod
    def for_checkpoint(cls, checkpoint_path: str | os.PathLike[str] | Path) -> "RootEvidenceStore":
        checkpoint = Path(checkpoint_path)
        return cls(checkpoint.parent / f"{checkpoint.name}.root-evidence")

    @classmethod
    def default(cls) -> "RootEvidenceStore":
        return cls(RootReadoutStore.default().root.parent / ROOT_EVIDENCE_STORE_DIRECTORY_NAME)

    @staticmethod
    def _path(root: Path, key_sha256: str) -> Path:
        if _HEX_64.fullmatch(key_sha256) is None:
            raise ValueError("root evidence dependency SHA-256 is invalid")
        return root / f"{key_sha256}.json"

    def lookup(self, key: RootDependencyKey) -> AuthenticatedRootEvidence | None:
        if not isinstance(key, RootDependencyKey):
            raise ValueError("root evidence lookup key is invalid")
        path = self._path(self.root, key.sha256)
        if not path.exists():
            return None
        if not path.is_file() or path.is_symlink():
            raise ValueError("trusted root evidence entry is invalid")
        try:
            evidence = AuthenticatedRootEvidence.from_mapping(_load_json(path))
        except (OSError, ValueError, UnicodeDecodeError) as error:
            raise ValueError(
                f"trusted root evidence entry is corrupt: {path}: {error}"
            ) from error
        if evidence.root_dependency_key != key:
            raise ValueError("trusted root evidence dependency key is incompatible")
        return evidence

    def publish(self, evidence: AuthenticatedRootEvidence) -> Path:
        if not isinstance(evidence, AuthenticatedRootEvidence):
            raise ValueError("root evidence publication is invalid")
        path = self._path(self.root, evidence.root_dependency_key.sha256)
        if path.exists():
            existing = self.lookup(evidence.root_dependency_key)
            if (
                existing is None
                or existing.fixed_root != evidence.fixed_root
                or existing.branch_identity != evidence.branch_identity
            ):
                raise ValueError("SYSTEM_FAILURE ROOT_SEAL_CONFLICT")
            return path
        _atomic_json(path, evidence.to_mapping())
        return path
