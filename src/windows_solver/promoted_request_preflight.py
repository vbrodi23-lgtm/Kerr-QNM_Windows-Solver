"""Cached no-solver validation of promoted Python-to-Julia request contracts."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Mapping

from .contracts import canonical_json_bytes


PROMOTED_REQUEST_PREFLIGHT_SCHEMA_VERSION = 1
PROMOTED_REQUEST_PREFLIGHT_CACHE_DIRECTORY_NAME = (
    "promoted-request-preflight-cache"
)
PROMOTED_REQUEST_PREFLIGHT_BINDING_SCHEMA = (
    "windows-solver.promoted-request-preflight-binding"
)
_HEX_64 = re.compile(r"[0-9a-f]{64}")
_BINDING_FIELDS = frozenset({
    "schema",
    "python_backend_source_sha256",
    "julia_worker_sha256",
    "calibration_receipt_sha256",
    "policy_sha256",
    "precision_capabilities_sha256",
    "request_set_sha256",
})
_ENTRY_FIELDS = frozenset({
    "schema_version",
    "binding_sha256",
    "binding",
    "response",
})


def _sha256(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate promoted-preflight cache field: {key}")
        result[key] = value
    return result


def _validated_binding(value: Mapping[str, object]) -> dict[str, object]:
    if not isinstance(value, Mapping) or set(value) != _BINDING_FIELDS:
        raise ValueError("promoted-request preflight binding fields are invalid")
    binding = dict(value)
    if binding["schema"] != PROMOTED_REQUEST_PREFLIGHT_BINDING_SCHEMA:
        raise ValueError("promoted-request preflight binding schema is invalid")
    for key in _BINDING_FIELDS - {"schema"}:
        digest = binding[key]
        if not isinstance(digest, str) or _HEX_64.fullmatch(digest) is None:
            raise ValueError(
                f"promoted-request preflight {key} is not a SHA-256 digest"
            )
    return binding


def promoted_request_preflight_binding(
    *,
    python_backend_source_sha256: str,
    julia_worker_sha256: str,
    calibration_receipt_sha256: str,
    policy_sha256: str,
    precision_capabilities_sha256: str,
    request_set_sha256: str,
) -> dict[str, object]:
    return _validated_binding({
        "schema": PROMOTED_REQUEST_PREFLIGHT_BINDING_SCHEMA,
        "python_backend_source_sha256": python_backend_source_sha256,
        "julia_worker_sha256": julia_worker_sha256,
        "calibration_receipt_sha256": calibration_receipt_sha256,
        "policy_sha256": policy_sha256,
        "precision_capabilities_sha256": precision_capabilities_sha256,
        "request_set_sha256": request_set_sha256,
    })


def promoted_request_preflight_binding_sha256(
    binding: Mapping[str, object],
) -> str:
    return _sha256(_validated_binding(binding))


class PromotedRequestPreflightStore:
    """One successful validation receipt per exact preflight binding."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def _path(self, binding: Mapping[str, object]) -> Path:
        return self.root / (
            promoted_request_preflight_binding_sha256(binding) + ".json"
        )

    def lookup(
        self, binding: Mapping[str, object]
    ) -> Mapping[str, object] | None:
        canonical_binding = _validated_binding(binding)
        path = self._path(canonical_binding)
        if not path.exists():
            return None
        if not path.is_file() or path.is_symlink():
            raise ValueError("promoted-request preflight cache entry is invalid")
        try:
            raw = path.read_bytes()
            entry = json.loads(
                raw,
                object_pairs_hook=_reject_duplicate_keys,
                parse_constant=lambda item: (_ for _ in ()).throw(
                    ValueError(
                        "promoted-request preflight cache contains "
                        f"non-finite constant {item}"
                    )
                ),
            )
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError(
                "promoted-request preflight cache entry is invalid JSON"
            ) from error
        if not isinstance(entry, Mapping) or set(entry) != _ENTRY_FIELDS:
            raise ValueError(
                "promoted-request preflight cache entry fields are invalid"
            )
        expected_digest = promoted_request_preflight_binding_sha256(
            canonical_binding
        )
        if (
            entry["schema_version"]
            != PROMOTED_REQUEST_PREFLIGHT_SCHEMA_VERSION
            or entry["binding_sha256"] != expected_digest
            or entry["binding"] != canonical_binding
            or canonical_json_bytes(entry) != raw
            or not isinstance(entry["response"], Mapping)
        ):
            raise ValueError(
                "promoted-request preflight cache entry authentication failed"
            )
        return dict(entry["response"])

    def publish(
        self,
        binding: Mapping[str, object],
        response: Mapping[str, object],
    ) -> Path:
        canonical_binding = _validated_binding(binding)
        if not isinstance(response, Mapping):
            raise ValueError("promoted-request preflight response is invalid")
        path = self._path(canonical_binding)
        entry = {
            "schema_version": PROMOTED_REQUEST_PREFLIGHT_SCHEMA_VERSION,
            "binding_sha256": promoted_request_preflight_binding_sha256(
                canonical_binding
            ),
            "binding": canonical_binding,
            "response": dict(response),
        }
        self.root.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            dir=self.root,
            prefix=f".{path.name}.",
            suffix=".tmp",
        )
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(canonical_json_bytes(entry))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_name, path)
        except BaseException:
            try:
                os.unlink(temporary_name)
            except FileNotFoundError:
                pass
            raise
        return path
