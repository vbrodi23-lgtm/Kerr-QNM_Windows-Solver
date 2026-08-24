"""Durable exact-key canonical background and equivalence evidence."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Mapping, Sequence

from .contracts import canonical_json_bytes
from .response_engine import (
    BackgroundEquivalenceReceipt,
    CanonicalExteriorBackground,
    ExteriorBackgroundReuseKey,
    ResponseComponentJob,
    exterior_background_reuse_admitted,
)


BACKGROUND_EVIDENCE_ENVELOPE_SCHEMA = (
    "windows-solver.canonical-background-evidence-envelope/1"
)


def _sha256(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate canonical background JSON key: {key}")
        result[key] = value
    return result


def _load(path: Path) -> object:
    return json.loads(
        path.read_text(encoding="utf-8"),
        object_pairs_hook=_reject_duplicate_keys,
        parse_constant=lambda value: (_ for _ in ()).throw(
            ValueError(f"non-finite canonical background constant: {value}")
        ),
    )


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


class BackgroundEvidenceStatus(StrEnum):
    EMPTY = "EMPTY"
    MISS = "MISS"
    HIT = "HIT"
    CORRUPT = "CORRUPT"
    CONFLICT = "CONFLICT"


class BackgroundEvidenceCorruption(ValueError):
    """Trusted exact-address evidence failed authentication."""


@dataclass(frozen=True, slots=True)
class BackgroundEvidenceLookup:
    status: BackgroundEvidenceStatus
    background: CanonicalExteriorBackground | None
    receipt: BackgroundEquivalenceReceipt | None
    discovered_count: int
    compatible_count: int
    reused_count: int
    rejected_count: int


class CanonicalBackgroundEvidenceStore:
    """One atomically replaced envelope per exact numerical Dω reuse key."""

    def __init__(self, root: str | os.PathLike[str] | Path) -> None:
        self.root = Path(root)

    def _path(self, reuse_key: ExteriorBackgroundReuseKey) -> Path:
        return self.root / f"{_sha256(reuse_key.to_mapping())}.json"

    @staticmethod
    def _envelope(
        background: CanonicalExteriorBackground,
        receipts: Mapping[str, BackgroundEquivalenceReceipt],
    ) -> dict[str, object]:
        content = {
            "schema": BACKGROUND_EVIDENCE_ENVELOPE_SCHEMA,
            "reuse_key_sha256": _sha256(background.reuse_key.to_mapping()),
            "canonical_background_sha256": background.sha256,
            "canonical_background": background.to_mapping(),
            "equivalence_receipts": {
                mechanism: receipt.to_mapping()
                for mechanism, receipt in sorted(receipts.items())
            },
        }
        return {**content, "envelope_sha256": _sha256(content)}

    @staticmethod
    def _parse(
        raw: object,
    ) -> tuple[
        CanonicalExteriorBackground,
        dict[str, BackgroundEquivalenceReceipt],
    ]:
        fields = {
            "schema",
            "reuse_key_sha256",
            "canonical_background_sha256",
            "canonical_background",
            "equivalence_receipts",
            "envelope_sha256",
        }
        if not isinstance(raw, Mapping) or set(raw) != fields:
            raise ValueError("canonical background envelope fields are invalid")
        if raw["schema"] != BACKGROUND_EVIDENCE_ENVELOPE_SCHEMA:
            raise ValueError("canonical background envelope schema is invalid")
        content = {name: raw[name] for name in fields - {"envelope_sha256"}}
        if raw["envelope_sha256"] != _sha256(content):
            raise ValueError("canonical background envelope digest mismatch")
        background = CanonicalExteriorBackground.from_mapping(
            raw["canonical_background"]
        )
        if (
            raw["reuse_key_sha256"]
            != _sha256(background.reuse_key.to_mapping())
            or raw["canonical_background_sha256"] != background.sha256
        ):
            raise ValueError("canonical background envelope binding mismatch")
        receipt_mappings = raw["equivalence_receipts"]
        if not isinstance(receipt_mappings, Mapping):
            raise ValueError("background equivalence receipt index is invalid")
        receipts: dict[str, BackgroundEquivalenceReceipt] = {}
        for mechanism, mapping in receipt_mappings.items():
            if not isinstance(mechanism, str):
                raise ValueError("background equivalence mechanism key is invalid")
            receipt = BackgroundEquivalenceReceipt.from_mapping(mapping)
            if (
                receipt.mechanism_id != mechanism
                or receipt.reuse_key != background.reuse_key
                or receipt.canonical_background_sha256 != background.sha256
            ):
                raise ValueError("background equivalence receipt binding mismatch")
            receipts[mechanism] = receipt
        return background, receipts

    def lookup(
        self,
        job: ResponseComponentJob,
        reuse_key: ExteriorBackgroundReuseKey,
    ) -> BackgroundEvidenceLookup:
        path = self._path(reuse_key)
        if not self.root.exists():
            return BackgroundEvidenceLookup(
                BackgroundEvidenceStatus.EMPTY, None, None, 0, 0, 0, 0
            )
        if not path.exists():
            return BackgroundEvidenceLookup(
                BackgroundEvidenceStatus.MISS, None, None, 0, 0, 0, 0
            )
        if not path.is_file() or path.is_symlink():
            raise BackgroundEvidenceCorruption(
                f"trusted canonical background address is invalid: {path}"
            )
        try:
            raw = _load(path)
            background, receipts = self._parse(raw)
            if background.reuse_key != reuse_key:
                raise ValueError("canonical background exact key mismatch")
            receipt = receipts.get(job.mechanism_id)
            if receipt is not None and not exterior_background_reuse_admitted(
                job, background, receipt
            ):
                raise ValueError("background equivalence admission is invalid")
        except (OSError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise BackgroundEvidenceCorruption(
                f"trusted canonical background evidence is corrupt: {path}: {error}"
            ) from error
        if receipt is None:
            return BackgroundEvidenceLookup(
                BackgroundEvidenceStatus.MISS,
                background,
                None,
                1,
                0,
                0,
                1,
            )
        return BackgroundEvidenceLookup(
            BackgroundEvidenceStatus.HIT,
            background,
            receipt,
            1,
            1,
            1,
            0,
        )

    def publish(
        self,
        background: CanonicalExteriorBackground,
        receipts: Sequence[BackgroundEquivalenceReceipt],
    ) -> Path:
        if not isinstance(background, CanonicalExteriorBackground):
            raise ValueError("canonical background publication is invalid")
        receipt_index: dict[str, BackgroundEquivalenceReceipt] = {}
        for receipt in receipts:
            if (
                not isinstance(receipt, BackgroundEquivalenceReceipt)
                or receipt.reuse_key != background.reuse_key
                or receipt.canonical_background_sha256 != background.sha256
            ):
                raise ValueError("background equivalence publication is invalid")
            prior = receipt_index.get(receipt.mechanism_id)
            if prior is not None and prior != receipt:
                raise ValueError("conflicting background equivalence receipts")
            receipt_index[receipt.mechanism_id] = receipt
        if not receipt_index:
            raise ValueError("canonical background publication lacks equivalence")

        path = self._path(background.reuse_key)
        if path.exists():
            if not path.is_file() or path.is_symlink():
                raise BackgroundEvidenceCorruption(
                    f"trusted canonical background address is invalid: {path}"
                )
            try:
                current, current_receipts = self._parse(
                    _load(path)
                )
            except (OSError, TypeError, ValueError, json.JSONDecodeError) as error:
                raise BackgroundEvidenceCorruption(
                    f"trusted canonical background evidence is corrupt: {path}: {error}"
                ) from error
            if current != background:
                raise ValueError("SYSTEM_FAILURE BACKGROUND_EVIDENCE_CONFLICT")
            for mechanism, receipt in receipt_index.items():
                prior = current_receipts.get(mechanism)
                if prior is not None and prior != receipt:
                    raise ValueError("SYSTEM_FAILURE BACKGROUND_EVIDENCE_CONFLICT")
                current_receipts[mechanism] = receipt
            receipt_index = current_receipts
        _atomic_json(path, self._envelope(background, receipt_index))
        return path


__all__ = [
    "BackgroundEvidenceCorruption",
    "BackgroundEvidenceLookup",
    "BackgroundEvidenceStatus",
    "CanonicalBackgroundEvidenceStore",
]
