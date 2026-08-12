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


ROOT_READOUT_CACHE_SCHEMA_VERSION = 1
ROOT_READOUT_STORE_DIRECTORY_NAME = "root-readouts-" + "v" + str(
    ROOT_READOUT_CACHE_SCHEMA_VERSION
)
_HEX_64 = re.compile(r"[0-9a-f]{64}")
_ENTRY_FIELDS = frozenset({
    "schema_version",
    "readout_identity_sha256",
    "request_sha256",
    "runtime_identity_sha256",
    "created_utc",
    "response",
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
    reason: str | None = None


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
    def _validate_entry(
        value: object, *, request_sha256: str, runtime_identity: str
    ) -> Mapping[str, object]:
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
        # An entry is only reusable for the exact request and runtime it was
        # recorded against; a mismatch here means the file does not describe the
        # readout its own filename claims.
        if value["request_sha256"] != request_sha256:
            raise ValueError("root-readout cache request digest does not match")
        if value["runtime_identity_sha256"] != runtime_identity:
            raise ValueError("root-readout cache runtime identity does not match")
        expected_identity = root_readout_identity_sha256(
            request_sha256=request_sha256, runtime_identity=runtime_identity
        )
        if value["readout_identity_sha256"] != expected_identity:
            raise ValueError("root-readout cache identity is not self-consistent")
        response = value["response"]
        if not isinstance(response, Mapping):
            raise ValueError("root-readout cache response is invalid")
        if response.get("status") != "ok":
            raise ValueError("root-readout cache response is not a successful readout")
        if response.get("request_sha256") != request_sha256:
            raise ValueError("root-readout cache response request digest is invalid")
        return response

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
            response = self._validate_entry(
                _load_json(path),
                request_sha256=request_sha256,
                runtime_identity=runtime_identity,
            )
        except (OSError, ValueError, UnicodeDecodeError) as error:
            return RootReadoutLookup(
                RootReadoutLookupStatus.CORRUPT, path=path, reason=str(error)
            )
        return RootReadoutLookup(
            RootReadoutLookupStatus.HIT, path=path, response=dict(response)
        )

    def publish(
        self,
        *,
        request_sha256: str,
        runtime_identity: str,
        response: Mapping[str, object],
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
        })
        return path
