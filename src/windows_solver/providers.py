"""Provider ownership and availability contracts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Protocol, Sequence

from .contracts import Capability, EvidenceState, StudyRequest
from .planner import ExecutionPlan


@dataclass(frozen=True, slots=True)
class ProviderDescriptor:
    capability: Capability
    provider_id: str
    implementation_version: str
    equations_id: str
    conventions_id: str
    runtime_fingerprint: str
    numerical_policy_fingerprint: str
    upstream_artifact_types: tuple[str, ...]
    output_artifact_type: str
    available: bool
    evidence_level: str

    def __post_init__(self) -> None:
        if not isinstance(self.capability, Capability):
            raise ValueError("capability must be a Capability")
        for name in (
            "provider_id",
            "implementation_version",
            "equations_id",
            "conventions_id",
            "runtime_fingerprint",
            "numerical_policy_fingerprint",
            "output_artifact_type",
            "evidence_level",
        ):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be non-empty")
        if not isinstance(self.upstream_artifact_types, tuple) or not all(
            isinstance(value, str) and value.strip()
            for value in self.upstream_artifact_types
        ):
            raise ValueError("upstream_artifact_types must contain non-empty strings")
        if not isinstance(self.available, bool):
            raise ValueError("available must be boolean")

    def to_mapping(self) -> dict[str, object]:
        return {
            "capability": self.capability.value,
            "provider_id": self.provider_id,
            "implementation_version": self.implementation_version,
            "equations_id": self.equations_id,
            "conventions_id": self.conventions_id,
            "runtime_fingerprint": self.runtime_fingerprint,
            "numerical_policy_fingerprint": self.numerical_policy_fingerprint,
            "upstream_artifact_types": list(self.upstream_artifact_types),
            "output_artifact_type": self.output_artifact_type,
            "available": self.available,
            "evidence_level": self.evidence_level,
        }


class Provider(Protocol):
    descriptor: ProviderDescriptor

    def execute(
        self, request: StudyRequest, upstream: Mapping[Capability, object]
    ) -> "ProviderResult": ...


@dataclass(frozen=True, slots=True)
class ProviderResult:
    payload: Mapping[str, object]
    evidence: EvidenceState


class DuplicateProviderError(ValueError):
    pass


class ProviderUnavailableError(RuntimeError):
    def __init__(self, capability: Capability) -> None:
        self.capability = capability
        super().__init__(f"provider unavailable for {capability.value}")


class ProviderRegistry:
    def __init__(self, providers: Sequence[Provider]) -> None:
        by_capability: dict[Capability, Provider] = {}
        for provider in providers:
            capability = provider.descriptor.capability
            if capability in by_capability:
                raise DuplicateProviderError(
                    f"duplicate provider for {capability.value}"
                )
            by_capability[capability] = provider
        self._providers = by_capability

    def resolve(self, capability: Capability) -> Provider:
        provider = self._providers.get(capability)
        if provider is None or not provider.descriptor.available:
            raise ProviderUnavailableError(capability)
        return provider

    def require_plan(self, plan: ExecutionPlan) -> tuple[Provider, ...]:
        return tuple(self.resolve(capability) for capability in plan.capabilities)

    def descriptors(self) -> tuple[ProviderDescriptor, ...]:
        return tuple(
            self._providers[capability].descriptor
            for capability in Capability
            if capability in self._providers
        )
