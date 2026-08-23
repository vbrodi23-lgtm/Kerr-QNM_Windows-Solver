"""Append-only operational timing sessions for schema-11 campaign passes."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path
from types import MappingProxyType
from typing import Callable, Mapping, Sequence

from .contracts import canonical_json_bytes


TIMING_FRAGMENT_SCHEMA = "windows-solver.campaign-timing-fragment/1"
_PROFILES = frozenset({"SURVEY", "CERTIFY", "VALIDATE"})
_PASSES = frozenset({"binary64", "promoted", "certify", "validate"})
_TIERS = frozenset({"binary64", "BF40", "BF80", "BF120"})
_STATES = frozenset({"STARTED", "HEARTBEAT", "COMPLETED", "INTERRUPTED"})
_SOURCES = frozenset({"direct", "reconstructed"})


def _sha256(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _is_sha256(value: object) -> bool:
    if not isinstance(value, str) or len(value) != 64:
        return False
    try:
        int(value, 16)
    except ValueError:
        return False
    return True


def _elapsed(value: object, label: str) -> float:
    converted = float(value)
    if isinstance(value, bool) or not math.isfinite(converted) or converted < 0:
        raise ValueError(f"timing {label} is invalid")
    return converted


@dataclass(frozen=True, slots=True)
class TimingFragment:
    session_id: str
    sequence: int
    leaf_id: str
    execution_profile: str
    survey_pass: str
    tier: str
    state: str
    elapsed_tier_seconds: float
    elapsed_leaf_seconds: float
    source: str
    fragment_sha256: str

    def __post_init__(self) -> None:
        if not self.session_id or not self.leaf_id:
            raise ValueError("timing session or leaf identity is invalid")
        if (
            isinstance(self.sequence, bool)
            or not isinstance(self.sequence, int)
            or self.sequence < 0
        ):
            raise ValueError("timing sequence is invalid")
        if self.execution_profile not in _PROFILES:
            raise ValueError("timing execution profile is invalid")
        if self.survey_pass not in _PASSES:
            raise ValueError("timing pass is invalid")
        if self.tier not in _TIERS:
            raise ValueError("timing tier is invalid")
        if self.state not in _STATES:
            raise ValueError("timing state is invalid")
        if self.source not in _SOURCES:
            raise ValueError("timing source is invalid")
        object.__setattr__(
            self,
            "elapsed_tier_seconds",
            _elapsed(self.elapsed_tier_seconds, "tier elapsed seconds"),
        )
        object.__setattr__(
            self,
            "elapsed_leaf_seconds",
            _elapsed(self.elapsed_leaf_seconds, "leaf elapsed seconds"),
        )
        if self.elapsed_leaf_seconds < self.elapsed_tier_seconds:
            raise ValueError("timing leaf elapsed time is smaller than tier time")
        if not _is_sha256(self.fragment_sha256):
            raise ValueError("timing fragment digest is invalid")
        if self.fragment_sha256 != _sha256(self.content_mapping):
            raise ValueError("timing fragment authentication failed")

    @property
    def content_mapping(self) -> dict[str, object]:
        return {
            "schema": TIMING_FRAGMENT_SCHEMA,
            "session_id": self.session_id,
            "sequence": self.sequence,
            "leaf_id": self.leaf_id,
            "execution_profile": self.execution_profile,
            "survey_pass": self.survey_pass,
            "tier": self.tier,
            "state": self.state,
            "elapsed_tier_seconds": self.elapsed_tier_seconds,
            "elapsed_leaf_seconds": self.elapsed_leaf_seconds,
            "source": self.source,
        }

    def to_mapping(self) -> dict[str, object]:
        return {**self.content_mapping, "fragment_sha256": self.fragment_sha256}

    @classmethod
    def create(cls, **values: object) -> "TimingFragment":
        content = {"schema": TIMING_FRAGMENT_SCHEMA, **values}
        return cls(
            session_id=values["session_id"],
            sequence=values["sequence"],
            leaf_id=values["leaf_id"],
            execution_profile=values["execution_profile"],
            survey_pass=values["survey_pass"],
            tier=values["tier"],
            state=values["state"],
            elapsed_tier_seconds=values["elapsed_tier_seconds"],
            elapsed_leaf_seconds=values["elapsed_leaf_seconds"],
            source=values["source"],
            fragment_sha256=_sha256(content),
        )

    @classmethod
    def from_mapping(cls, value: object) -> "TimingFragment":
        fields = {
            "schema",
            "session_id",
            "sequence",
            "leaf_id",
            "execution_profile",
            "survey_pass",
            "tier",
            "state",
            "elapsed_tier_seconds",
            "elapsed_leaf_seconds",
            "source",
            "fragment_sha256",
        }
        if not isinstance(value, Mapping) or set(value) != fields:
            raise ValueError("timing fragment fields are invalid")
        if value["schema"] != TIMING_FRAGMENT_SCHEMA:
            raise ValueError("timing fragment schema is invalid")
        return cls(**{key: value[key] for key in fields if key != "schema"})


def _validate_sequence(fragments: Sequence[TimingFragment]) -> None:
    by_session: dict[str, list[TimingFragment]] = {}
    for fragment in fragments:
        if not isinstance(fragment, TimingFragment):
            raise ValueError("timing log contains an invalid fragment")
        by_session.setdefault(fragment.session_id, []).append(fragment)
    for session in by_session.values():
        binding = (
            session[0].leaf_id,
            session[0].execution_profile,
            session[0].survey_pass,
        )
        prior_sequence = -1
        prior_leaf_elapsed = -1.0
        terminal_tiers: set[str] = set()
        for fragment in session:
            if (
                fragment.leaf_id,
                fragment.execution_profile,
                fragment.survey_pass,
            ) != binding:
                raise ValueError("timing session binding changed")
            if fragment.sequence <= prior_sequence:
                raise ValueError("timing session sequence is not increasing")
            if fragment.elapsed_leaf_seconds < prior_leaf_elapsed:
                raise ValueError("timing session elapsed time moved backwards")
            if fragment.tier in terminal_tiers:
                raise ValueError("timing fragment follows a terminal tier state")
            if fragment.state in {"COMPLETED", "INTERRUPTED"}:
                terminal_tiers.add(fragment.tier)
            prior_sequence = fragment.sequence
            prior_leaf_elapsed = fragment.elapsed_leaf_seconds


class CampaignTimingLog:
    def __init__(self, path: str | os.PathLike[str] | Path) -> None:
        self.path = Path(path)

    def read(self) -> tuple[TimingFragment, ...]:
        if not self.path.exists():
            return ()
        fragments: list[TimingFragment] = []
        with self.path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, 1):
                try:
                    value = json.loads(line)
                except json.JSONDecodeError as error:
                    raise ValueError(
                        f"timing log line {line_number} is malformed"
                    ) from error
                fragments.append(TimingFragment.from_mapping(value))
        _validate_sequence(fragments)
        return tuple(fragments)

    def append(self, fragment: TimingFragment) -> None:
        if not isinstance(fragment, TimingFragment):
            raise ValueError("timing append requires a fragment")
        existing = self.read()
        _validate_sequence((*existing, fragment))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("ab") as handle:
            handle.write(canonical_json_bytes(fragment.to_mapping()) + b"\n")
            handle.flush()
            os.fsync(handle.fileno())


@dataclass(frozen=True, slots=True)
class TierTimingSummary:
    tier_seconds: Mapping[str, float]
    total_leaf_seconds: float
    reconstructed_tiers: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "tier_seconds", MappingProxyType(dict(self.tier_seconds))
        )

    def tier_timing_mappings(self) -> tuple[dict[str, object], ...]:
        return tuple(
            {
                "tier": tier,
                "elapsed_seconds": self.tier_seconds[tier],
                "source": (
                    "reconstructed"
                    if tier in self.reconstructed_tiers
                    else "direct"
                ),
            }
            for tier in ("binary64", "BF40", "BF80", "BF120")
            if tier in self.tier_seconds
        )


def fold_timing_fragments(
    fragments: Sequence[TimingFragment],
) -> TierTimingSummary:
    fragment_tuple = tuple(fragments)
    _validate_sequence(fragment_tuple)
    latest_by_session_tier: dict[tuple[str, str], TimingFragment] = {}
    latest_by_session: dict[str, TimingFragment] = {}
    for fragment in fragment_tuple:
        latest_by_session_tier[(fragment.session_id, fragment.tier)] = fragment
        latest_by_session[fragment.session_id] = fragment
    tier_seconds: dict[str, float] = {}
    reconstructed: set[str] = set()
    for fragment in latest_by_session_tier.values():
        tier_seconds[fragment.tier] = (
            tier_seconds.get(fragment.tier, 0.0)
            + fragment.elapsed_tier_seconds
        )
        if (
            fragment.state not in {"COMPLETED", "INTERRUPTED"}
            or fragment.source == "reconstructed"
        ):
            reconstructed.add(fragment.tier)
    total = sum(
        fragment.elapsed_leaf_seconds for fragment in latest_by_session.values()
    )
    return TierTimingSummary(
        tier_seconds=tier_seconds,
        total_leaf_seconds=total,
        reconstructed_tiers=tuple(
            tier for tier in ("binary64", "BF40", "BF80", "BF120")
            if tier in reconstructed
        ),
    )


class TimingSessionRecorder:
    def __init__(
        self,
        *,
        log: CampaignTimingLog | None,
        session_id: str,
        leaf_id: str,
        execution_profile: str,
        survey_pass: str,
        clock: Callable[[], float],
    ) -> None:
        if not session_id or not leaf_id:
            raise ValueError("timing recorder identity is invalid")
        if execution_profile not in _PROFILES or survey_pass not in _PASSES:
            raise ValueError("timing recorder pass binding is invalid")
        self.log = log
        self.session_id = session_id
        self.leaf_id = leaf_id
        self.execution_profile = execution_profile
        self.survey_pass = survey_pass
        self.clock = clock
        self._leaf_started = clock()
        self._tier_started: float | None = None
        self._tier: str | None = None
        self._sequence = 0
        self.fragments: list[TimingFragment] = []

    @property
    def active_tier(self) -> str | None:
        return self._tier

    def _append(self, state: str) -> TimingFragment:
        if self._tier is None or self._tier_started is None:
            raise ValueError("timing recorder has no active tier")
        now = self.clock()
        fragment = TimingFragment.create(
            session_id=self.session_id,
            sequence=self._sequence,
            leaf_id=self.leaf_id,
            execution_profile=self.execution_profile,
            survey_pass=self.survey_pass,
            tier=self._tier,
            state=state,
            elapsed_tier_seconds=now - self._tier_started,
            elapsed_leaf_seconds=now - self._leaf_started,
            source="direct",
        )
        self._sequence += 1
        if self.log is not None:
            self.log.append(fragment)
        self.fragments.append(fragment)
        return fragment

    def start_tier(self, tier: str) -> TimingFragment:
        if self._tier is not None or tier not in _TIERS:
            raise ValueError("timing recorder tier start is invalid")
        self._tier = tier
        self._tier_started = self.clock()
        return self._append("STARTED")

    def heartbeat(self) -> TimingFragment:
        return self._append("HEARTBEAT")

    def complete_tier(self) -> TimingFragment:
        fragment = self._append("COMPLETED")
        self._tier = None
        self._tier_started = None
        return fragment

    def interrupt_tier(self) -> TimingFragment:
        fragment = self._append("INTERRUPTED")
        self._tier = None
        self._tier_started = None
        return fragment


__all__ = [
    "CampaignTimingLog",
    "TIMING_FRAGMENT_SCHEMA",
    "TierTimingSummary",
    "TimingFragment",
    "TimingSessionRecorder",
    "fold_timing_fragments",
]
