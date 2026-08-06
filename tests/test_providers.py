from __future__ import annotations

import unittest

from windows_solver.contracts import Capability
from windows_solver.planner import build_plan
from windows_solver.providers import (
    DuplicateProviderError,
    ProviderDescriptor,
    ProviderRegistry,
    ProviderUnavailableError,
)


class ExampleProvider:
    def __init__(self, capability: Capability, *, available: bool = True) -> None:
        self.descriptor = ProviderDescriptor(
            capability=capability,
            provider_id=f"example-{capability.value}",
            implementation_version="1",
            equations_id="equations-1",
            conventions_id="conventions-1",
            runtime_fingerprint="cpython-3.12",
            numerical_policy_fingerprint="policy-1",
            upstream_artifact_types=(),
            output_artifact_type=f"{capability.value}-artifact",
            available=available,
            evidence_level="test",
        )

    def execute(self, request, upstream):
        return {"capability": self.descriptor.capability.value}


class ProviderRegistryTests(unittest.TestCase):
    def test_rejects_duplicate_capability_ownership(self) -> None:
        first = ExampleProvider(Capability.SPECTRAL_CORE)
        second = ExampleProvider(Capability.SPECTRAL_CORE)

        with self.assertRaisesRegex(
            DuplicateProviderError, "duplicate provider for spectral-core"
        ):
            ProviderRegistry((first, second))

    def test_unavailable_provider_names_exact_capability(self) -> None:
        registry = ProviderRegistry(
            (ExampleProvider(Capability.PROBLEM_CONTRACT, available=False),)
        )

        with self.assertRaisesRegex(
            ProviderUnavailableError, "provider unavailable for problem-contract"
        ):
            registry.resolve(Capability.PROBLEM_CONTRACT)

    def test_plan_resolution_stops_at_first_missing_provider(self) -> None:
        registry = ProviderRegistry(
            (ExampleProvider(Capability.PROBLEM_CONTRACT),)
        )
        plan = build_plan(Capability.QUADRATIC_RINGDOWN)

        with self.assertRaises(ProviderUnavailableError) as caught:
            registry.require_plan(plan)

        self.assertIs(caught.exception.capability, Capability.SPECTRAL_CORE)


if __name__ == "__main__":
    unittest.main()
