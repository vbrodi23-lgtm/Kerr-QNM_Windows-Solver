"""Dependency-closure planning for public scientific capabilities."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from .contracts import Capability


CAPABILITY_DEPENDENCIES: Mapping[Capability, tuple[Capability, ...]] = (
    MappingProxyType(
        {
            Capability.PROBLEM_CONTRACT: (),
            Capability.SPECTRAL_CORE: (Capability.PROBLEM_CONTRACT,),
            Capability.LINEAR_RESPONSE: (Capability.SPECTRAL_CORE,),
            Capability.OPERATOR_STABILITY: (Capability.SPECTRAL_CORE,),
            Capability.QUADRATIC_RINGDOWN: (Capability.SPECTRAL_CORE,),
            Capability.RESPONSE_MATRIX: (
                Capability.LINEAR_RESPONSE,
                Capability.QUADRATIC_RINGDOWN,
            ),
            Capability.INVERSE_INFERENCE: (Capability.RESPONSE_MATRIX,),
            Capability.SIGNALS: (Capability.RESPONSE_MATRIX,),
            Capability.DETECTOR_INFERENCE: (Capability.SIGNALS,),
            Capability.EVIDENCE_PACKAGE: (
                Capability.OPERATOR_STABILITY,
                Capability.INVERSE_INFERENCE,
                Capability.DETECTOR_INFERENCE,
            ),
        }
    )
)


def _validate_graph() -> None:
    if set(CAPABILITY_DEPENDENCIES) != set(Capability):
        raise RuntimeError("capability dependency graph is incomplete")
    visiting: set[Capability] = set()
    visited: set[Capability] = set()

    def visit(capability: Capability) -> None:
        if capability in visiting:
            raise RuntimeError(f"capability dependency cycle at {capability.value}")
        if capability in visited:
            return
        visiting.add(capability)
        for dependency in CAPABILITY_DEPENDENCIES[capability]:
            visit(dependency)
        visiting.remove(capability)
        visited.add(capability)

    for capability in Capability:
        visit(capability)


_validate_graph()


@dataclass(frozen=True, slots=True)
class ExecutionPlan:
    target: Capability
    capabilities: tuple[Capability, ...]
    dependencies: Mapping[Capability, tuple[Capability, ...]]

    def to_mapping(self) -> dict[str, object]:
        return {
            "target": self.target.value,
            "capabilities": [item.value for item in self.capabilities],
            "dependencies": {
                capability.value: [dependency.value for dependency in dependencies]
                for capability, dependencies in self.dependencies.items()
            },
        }


def build_plan(target: Capability) -> ExecutionPlan:
    closure: set[Capability] = set()

    def include(capability: Capability) -> None:
        if capability in closure:
            return
        for dependency in CAPABILITY_DEPENDENCIES[capability]:
            include(dependency)
        closure.add(capability)

    include(target)
    declaration_order = {capability: index for index, capability in enumerate(Capability)}
    indegree = {
        capability: sum(
            dependency in closure
            for dependency in CAPABILITY_DEPENDENCIES[capability]
        )
        for capability in closure
    }
    dependents: dict[Capability, list[Capability]] = {
        capability: [] for capability in closure
    }
    for capability in closure:
        for dependency in CAPABILITY_DEPENDENCIES[capability]:
            if dependency in closure:
                dependents[dependency].append(capability)

    ready = sorted(
        (capability for capability, degree in indegree.items() if degree == 0),
        key=declaration_order.__getitem__,
    )
    ordered: list[Capability] = []
    while ready:
        capability = ready.pop(0)
        ordered.append(capability)
        for dependent in sorted(
            dependents[capability], key=declaration_order.__getitem__
        ):
            indegree[dependent] -= 1
            if indegree[dependent] == 0:
                ready.append(dependent)
                ready.sort(key=declaration_order.__getitem__)
    if len(ordered) != len(closure):
        raise RuntimeError(f"capability dependency cycle at {target.value}")

    capabilities = tuple(ordered)
    dependencies = MappingProxyType(
        {
            capability: tuple(
                dependency
                for dependency in CAPABILITY_DEPENDENCIES[capability]
                if dependency in closure
            )
            for capability in capabilities
        }
    )
    return ExecutionPlan(
        target=target,
        capabilities=capabilities,
        dependencies=dependencies,
    )
