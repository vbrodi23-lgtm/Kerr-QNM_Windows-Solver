"""Typed, cardinality-aware outcomes for durable evidence discovery."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class EvidenceDiscoveryStatus(StrEnum):
    """The closed outcome vocabulary for one configured evidence source."""

    EMPTY = "EMPTY"
    MISS = "MISS"
    HIT = "HIT"
    CORRUPT = "CORRUPT"
    CONFLICT = "CONFLICT"


@dataclass(frozen=True, slots=True)
class EvidenceDiscovery:
    """Exact source-cardinality accounting for one attempted lookup.

    ``reused_count`` is zero at a raw store lookup and is raised by the owning
    scheduler only after it has authenticated and consumed the candidate.
    """

    status: EvidenceDiscoveryStatus
    discovered_count: int
    compatible_count: int
    rejected_count: int
    reused_count: int = 0
    lookup_attempted: bool = True

    def __post_init__(self) -> None:
        for name in (
            "discovered_count",
            "compatible_count",
            "rejected_count",
            "reused_count",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"evidence discovery {name} is invalid")
        if not isinstance(self.lookup_attempted, bool):
            raise ValueError("evidence discovery lookup-attempted flag is invalid")
        if self.compatible_count > self.discovered_count:
            raise ValueError("compatible evidence exceeds discovered evidence")
        if self.rejected_count > self.discovered_count:
            raise ValueError("rejected evidence exceeds discovered evidence")
        if self.reused_count > self.compatible_count:
            raise ValueError("reused evidence exceeds compatible evidence")
        if self.status is EvidenceDiscoveryStatus.EMPTY and any(
            (
                self.discovered_count,
                self.compatible_count,
                self.rejected_count,
                self.reused_count,
            )
        ):
            raise ValueError("empty discovery cannot report evidence")
        if self.status is EvidenceDiscoveryStatus.MISS and self.compatible_count:
            raise ValueError("a discovery miss cannot contain compatible evidence")
        if self.status is EvidenceDiscoveryStatus.HIT and not self.compatible_count:
            raise ValueError("a discovery hit requires compatible evidence")

    @classmethod
    def not_attempted(cls) -> "EvidenceDiscovery":
        """Compatibility default for legacy wrappers which did not perform I/O."""

        return cls(
            status=EvidenceDiscoveryStatus.EMPTY,
            discovered_count=0,
            compatible_count=0,
            rejected_count=0,
            reused_count=0,
            lookup_attempted=False,
        )

    def with_reused(self, count: int = 1) -> "EvidenceDiscovery":
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise ValueError("evidence reuse count is invalid")
        return EvidenceDiscovery(
            status=self.status,
            discovered_count=self.discovered_count,
            compatible_count=self.compatible_count,
            rejected_count=self.rejected_count,
            reused_count=self.reused_count + count,
            lookup_attempted=self.lookup_attempted,
        )

    def to_mapping(self) -> dict[str, object]:
        return {
            "status": self.status.value,
            "lookup_attempted": self.lookup_attempted,
            "discovered_count": self.discovered_count,
            "compatible_count": self.compatible_count,
            "reused_count": self.reused_count,
            "rejected_count": self.rejected_count,
        }


@dataclass(frozen=True, slots=True)
class EvidenceDiscoveryTotals:
    """Aggregate the exact outcomes of every lookup in one pass."""

    lookup_count: int = 0
    empty_count: int = 0
    miss_count: int = 0
    hit_count: int = 0
    corrupt_count: int = 0
    conflict_count: int = 0
    discovered_count: int = 0
    compatible_count: int = 0
    reused_count: int = 0
    rejected_count: int = 0

    def add(self, discovery: EvidenceDiscovery) -> "EvidenceDiscoveryTotals":
        status_fields = {
            EvidenceDiscoveryStatus.EMPTY: "empty_count",
            EvidenceDiscoveryStatus.MISS: "miss_count",
            EvidenceDiscoveryStatus.HIT: "hit_count",
            EvidenceDiscoveryStatus.CORRUPT: "corrupt_count",
            EvidenceDiscoveryStatus.CONFLICT: "conflict_count",
        }
        values = self.to_mapping()
        values["lookup_count"] = self.lookup_count + int(
            discovery.lookup_attempted
        )
        field = status_fields[discovery.status]
        values[field] = int(values[field]) + 1
        for name in (
            "discovered_count",
            "compatible_count",
            "reused_count",
            "rejected_count",
        ):
            values[name] = int(values[name]) + getattr(discovery, name)
        return EvidenceDiscoveryTotals(**values)

    def to_mapping(self) -> dict[str, int]:
        return {
            "lookup_count": self.lookup_count,
            "empty_count": self.empty_count,
            "miss_count": self.miss_count,
            "hit_count": self.hit_count,
            "corrupt_count": self.corrupt_count,
            "conflict_count": self.conflict_count,
            "discovered_count": self.discovered_count,
            "compatible_count": self.compatible_count,
            "reused_count": self.reused_count,
            "rejected_count": self.rejected_count,
        }
