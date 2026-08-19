"""Atomic, canonical journal for completed promoted-component work units."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import re
import tempfile
from types import MappingProxyType
from typing import Callable, Mapping, Sequence

from .contracts import canonical_json_bytes
from .precision_tiers import PrecisionTier, nominal_decimal_digits, precision_tier


PARTIAL_COMPONENT_JOURNAL_SCHEMA = "windows-solver.partial-component-journal/1"
_HEX_64 = re.compile(r"[0-9a-f]{64}")


def _digest(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _freeze_json(value: object) -> object:
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze_json(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze_json(item) for item in value)
    return value


def _thaw_json(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json(item) for item in value]
    return value


def _complex_mapping(value: complex) -> dict[str, float]:
    return {"imaginary": value.imag, "real": value.real}


def _parse_complex(value: object) -> complex:
    if not isinstance(value, dict) or set(value) != {"imaginary", "real"}:
        raise ValueError("partial component amplitude is invalid")
    real = value["real"]
    imaginary = value["imaginary"]
    if isinstance(real, bool) or not isinstance(real, (int, float)):
        raise ValueError("partial component amplitude is invalid")
    if isinstance(imaginary, bool) or not isinstance(imaginary, (int, float)):
        raise ValueError("partial component amplitude is invalid")
    return complex(float(real), float(imaginary))


@dataclass(frozen=True, slots=True)
class PartialComponentEntry:
    component_scientific_identity: str
    leaf_id: str
    job_id: str
    policy_sha256: str
    backend_identity: str
    determinant_family: str
    determinant_normalisation: str
    precision_tier: PrecisionTier
    mpfr_bits: int
    amplitude: complex
    epsilon: float
    readout_role: str
    refinement_level: int
    request_sha256: str
    worker_response_receipt: Mapping[str, object]
    worker_response_receipt_sha256: str

    def __post_init__(self) -> None:
        tier = precision_tier(self.precision_tier)
        object.__setattr__(self, "precision_tier", tier)
        text_fields = (
            self.component_scientific_identity, self.leaf_id, self.job_id,
            self.backend_identity, self.determinant_family,
            self.determinant_normalisation, self.readout_role,
        )
        if any(not item for item in text_fields):
            raise ValueError("partial component entry identity is incomplete")
        if not _HEX_64.fullmatch(self.policy_sha256) or not _HEX_64.fullmatch(self.request_sha256):
            raise ValueError("partial component request digest is invalid")
        if not _HEX_64.fullmatch(self.worker_response_receipt_sha256):
            raise ValueError("partial component worker receipt digest is invalid")
        normalized_receipt = json.loads(
            canonical_json_bytes(dict(self.worker_response_receipt))
        )
        if not isinstance(normalized_receipt, dict):
            raise ValueError("partial component worker receipt must be a JSON object")
        if _digest(normalized_receipt) != self.worker_response_receipt_sha256:
            raise ValueError("partial component worker receipt digest mismatch")
        amplitude = complex(self.amplitude)
        if not math.isfinite(amplitude.real) or not math.isfinite(amplitude.imag):
            raise ValueError("partial component amplitude must be finite")
        if not math.isfinite(self.epsilon) or self.epsilon < 0.0:
            raise ValueError("partial component epsilon must be finite and nonnegative")
        if isinstance(self.mpfr_bits, bool) or not isinstance(self.mpfr_bits, int) or self.mpfr_bits < 1:
            raise ValueError("partial component MPFR bits must be a positive integer")
        if isinstance(self.refinement_level, bool) or not isinstance(self.refinement_level, int) or self.refinement_level < 0:
            raise ValueError("partial component refinement level must be nonnegative")
        object.__setattr__(self, "amplitude", amplitude)
        object.__setattr__(
            self,
            "worker_response_receipt",
            _freeze_json(normalized_receipt),
        )

    def work_unit_mapping(self) -> dict[str, object]:
        return {
            "amplitude": _complex_mapping(self.amplitude),
            "backend_identity": self.backend_identity,
            "component_scientific_identity": self.component_scientific_identity,
            "determinant_family": self.determinant_family,
            "determinant_normalisation": self.determinant_normalisation,
            "epsilon": self.epsilon,
            "job_id": self.job_id,
            "leaf_id": self.leaf_id,
            "mpfr_bits": self.mpfr_bits,
            "nominal_decimal_digits": nominal_decimal_digits(self.precision_tier),
            "policy_sha256": self.policy_sha256,
            "precision_tier": self.precision_tier.value,
            "readout_role": self.readout_role,
            "refinement_level": self.refinement_level,
            "request_sha256": self.request_sha256,
        }

    @property
    def work_unit_id(self) -> str:
        return _digest(self.work_unit_mapping())

    def to_mapping(self) -> dict[str, object]:
        receipt = _thaw_json(self.worker_response_receipt)
        if _digest(receipt) != self.worker_response_receipt_sha256:
            raise ValueError("partial component worker receipt digest mismatch")
        material = {
            **self.work_unit_mapping(),
            "worker_response_receipt": receipt,
            "worker_response_receipt_sha256": self.worker_response_receipt_sha256,
            "work_unit_id": self.work_unit_id,
        }
        return {**material, "entry_sha256": _digest(material)}

    @classmethod
    def from_mapping(cls, value: object) -> "PartialComponentEntry":
        if not isinstance(value, dict):
            raise ValueError("partial component journal entry is invalid")
        material = dict(value)
        entry_sha256 = material.pop("entry_sha256", None)
        work_unit_id = material.pop("work_unit_id", None)
        if not isinstance(entry_sha256, str) or _digest({**material, "work_unit_id": work_unit_id}) != entry_sha256:
            raise ValueError("partial component entry identity mismatch")
        try:
            result = cls(
                component_scientific_identity=material["component_scientific_identity"],
                leaf_id=material["leaf_id"], job_id=material["job_id"],
                policy_sha256=material["policy_sha256"],
                backend_identity=material["backend_identity"],
                determinant_family=material["determinant_family"],
                determinant_normalisation=material["determinant_normalisation"],
                precision_tier=precision_tier(material["precision_tier"]),
                mpfr_bits=material["mpfr_bits"],
                amplitude=_parse_complex(material["amplitude"]),
                epsilon=material["epsilon"], readout_role=material["readout_role"],
                refinement_level=material["refinement_level"],
                request_sha256=material["request_sha256"],
                worker_response_receipt=material["worker_response_receipt"],
                worker_response_receipt_sha256=material["worker_response_receipt_sha256"],
            )
        except (KeyError, TypeError) as error:
            raise ValueError("partial component journal entry fields are invalid") from error
        if material.get("nominal_decimal_digits") != nominal_decimal_digits(result.precision_tier):
            raise ValueError("partial component nominal decimal digits mismatch")
        if result.work_unit_id != work_unit_id:
            raise ValueError("partial component work-unit identity mismatch")
        if result.to_mapping() != value:
            raise ValueError("partial component journal entry has unknown fields")
        return result


@dataclass(frozen=True, slots=True)
class PartialComponentWorkUnit:
    component_scientific_identity: str
    leaf_id: str
    job_id: str
    policy_sha256: str
    backend_identity: str
    determinant_family: str
    determinant_normalisation: str
    precision_tier: PrecisionTier
    mpfr_bits: int
    amplitude: complex
    epsilon: float
    readout_role: str
    refinement_level: int
    request_sha256: str

    @classmethod
    def from_entry(cls, value: PartialComponentEntry) -> "PartialComponentWorkUnit":
        material = value.work_unit_mapping()
        return cls(
            component_scientific_identity=value.component_scientific_identity,
            leaf_id=value.leaf_id,
            job_id=value.job_id,
            policy_sha256=value.policy_sha256,
            backend_identity=value.backend_identity,
            determinant_family=value.determinant_family,
            determinant_normalisation=value.determinant_normalisation,
            precision_tier=value.precision_tier,
            mpfr_bits=value.mpfr_bits,
            amplitude=value.amplitude,
            epsilon=value.epsilon,
            readout_role=value.readout_role,
            refinement_level=value.refinement_level,
            request_sha256=value.request_sha256,
        )

    def _identity_entry(self) -> PartialComponentEntry:
        receipt: dict[str, object] = {}
        return self.to_entry(receipt)

    @property
    def work_unit_id(self) -> str:
        return self._identity_entry().work_unit_id

    def to_entry(self, worker_response_receipt: Mapping[str, object]) -> PartialComponentEntry:
        receipt = dict(worker_response_receipt)
        return PartialComponentEntry(
            component_scientific_identity=self.component_scientific_identity,
            leaf_id=self.leaf_id,
            job_id=self.job_id,
            policy_sha256=self.policy_sha256,
            backend_identity=self.backend_identity,
            determinant_family=self.determinant_family,
            determinant_normalisation=self.determinant_normalisation,
            precision_tier=self.precision_tier,
            mpfr_bits=self.mpfr_bits,
            amplitude=self.amplitude,
            epsilon=self.epsilon,
            readout_role=self.readout_role,
            refinement_level=self.refinement_level,
            request_sha256=self.request_sha256,
            worker_response_receipt=receipt,
            worker_response_receipt_sha256=_digest(receipt),
        )


@dataclass(frozen=True, slots=True)
class PartialComponentResumeEvidence:
    reused_work_unit_ids: tuple[str, ...]
    executed_work_unit_ids: tuple[str, ...]


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
        if os.name != "nt":
            directory_descriptor = os.open(
                path.parent,
                os.O_RDONLY | getattr(os, "O_DIRECTORY", 0),
            )
            try:
                os.fsync(directory_descriptor)
            finally:
                os.close(directory_descriptor)
    except BaseException:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


@dataclass(slots=True)
class PartialComponentJournal:
    path: Path
    expected_work_unit_ids: tuple[str, ...]
    entries: dict[str, PartialComponentEntry]

    @classmethod
    def create(
        cls, path: str | os.PathLike[str], *, expected_work_unit_ids: Sequence[str]
    ) -> "PartialComponentJournal":
        expected = tuple(expected_work_unit_ids)
        if not expected or len(expected) != len(set(expected)) or any(not _HEX_64.fullmatch(item) for item in expected):
            raise ValueError("partial component expected work-unit identities are invalid")
        journal = cls(Path(path), expected, {})
        journal._write()
        return journal

    @classmethod
    def load(cls, path: str | os.PathLike[str]) -> "PartialComponentJournal":
        journal_path = Path(path)
        try:
            raw = json.loads(journal_path.read_bytes())
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise ValueError("partial component journal is not valid JSON") from error
        return cls.from_mapping(raw, path=journal_path)

    @classmethod
    def from_mapping(
        cls,
        raw: object,
        *,
        path: str | os.PathLike[str] = ".embedded-partial-component-journal",
    ) -> "PartialComponentJournal":
        """Authenticate a canonical journal projection without filesystem I/O."""

        if not isinstance(raw, dict) or set(raw) != {"complete", "entries", "expected_work_unit_ids", "journal_sha256", "schema"}:
            raise ValueError("partial component journal fields are invalid")
        journal_sha256 = raw["journal_sha256"]
        material = {key: value for key, value in raw.items() if key != "journal_sha256"}
        if raw["schema"] != PARTIAL_COMPONENT_JOURNAL_SCHEMA or journal_sha256 != _digest(material):
            raise ValueError("partial component journal identity mismatch")
        if not isinstance(raw["expected_work_unit_ids"], list):
            raise ValueError("partial component expected work-unit identities are invalid")
        expected = tuple(raw["expected_work_unit_ids"])
        if (
            not expected
            or len(expected) != len(set(expected))
            or any(
                not isinstance(item, str) or not _HEX_64.fullmatch(item)
                for item in expected
            )
        ):
            raise ValueError("partial component expected work-unit identities are invalid")
        entries_raw = raw["entries"]
        if not isinstance(entries_raw, dict):
            raise ValueError("partial component journal entries are invalid")
        entries = {key: PartialComponentEntry.from_mapping(value) for key, value in entries_raw.items()}
        if any(key != item.work_unit_id for key, item in entries.items()):
            raise ValueError("partial component journal entry key mismatch")
        if not set(entries).issubset(expected):
            raise ValueError("partial component journal entry is outside the plan")
        journal = cls(Path(path), expected, entries)
        if raw != journal._mapping():
            raise ValueError("partial component journal content is invalid")
        return journal

    def _mapping(self) -> dict[str, object]:
        material = {
            "complete": not self.missing_work_unit_ids(),
            "entries": {key: self.entries[key].to_mapping() for key in sorted(self.entries)},
            "expected_work_unit_ids": list(self.expected_work_unit_ids),
            "schema": PARTIAL_COMPONENT_JOURNAL_SCHEMA,
        }
        return {**material, "journal_sha256": _digest(material)}

    def to_mapping(self) -> dict[str, object]:
        """Return the canonical authenticated projection for embedding."""

        return self._mapping()

    def _write(self) -> None:
        _atomic_json(self.path, self._mapping())

    def record(self, entry: PartialComponentEntry) -> None:
        key = entry.work_unit_id
        if key not in self.expected_work_unit_ids:
            raise ValueError("partial component work unit is outside the journal plan")
        if key in self.entries:
            if self.entries[key].to_mapping() != entry.to_mapping():
                raise ValueError("partial component receipt conflicts with durable evidence")
            return
        self.entries[key] = entry
        try:
            self._write()
        except BaseException:
            del self.entries[key]
            raise

    def missing_work_unit_ids(self) -> tuple[str, ...]:
        return tuple(key for key in self.expected_work_unit_ids if key not in self.entries)

    @property
    def complete(self) -> bool:
        return not self.missing_work_unit_ids()


def run_partial_component_work(
    journal: PartialComponentJournal,
    work_units: Sequence[PartialComponentWorkUnit],
    execute: Callable[[PartialComponentWorkUnit], Mapping[str, object]],
) -> tuple[tuple[PartialComponentEntry, ...], PartialComponentResumeEvidence]:
    """Validate the whole journal, reuse exact entries, and run only missing work."""

    units = tuple(work_units)
    unit_ids = tuple(unit.work_unit_id for unit in units)
    if unit_ids != journal.expected_work_unit_ids:
        raise ValueError("partial component journal plan identity mismatch")
    reused: list[str] = []
    executed: list[str] = []
    completed: list[PartialComponentEntry] = []
    for unit in units:
        existing = journal.entries.get(unit.work_unit_id)
        if existing is not None:
            if PartialComponentWorkUnit.from_entry(existing) != unit:
                raise ValueError("partial component journal entry identity mismatch")
            reused.append(unit.work_unit_id)
            completed.append(existing)
            continue
        receipt = execute(unit)
        if not isinstance(receipt, Mapping):
            raise ValueError("partial component work unit receipt must be a mapping")
        entry = unit.to_entry(receipt)
        journal.record(entry)
        executed.append(unit.work_unit_id)
        completed.append(entry)
    return tuple(completed), PartialComponentResumeEvidence(
        tuple(reused), tuple(executed)
    )
