"""Built-in public providers that do not assert numerical science."""

from __future__ import annotations

import hashlib
import platform
from typing import Mapping

from .contracts import (
    Capability,
    CarrierState,
    EvidenceState,
    ExecutionState,
    NumericalState,
    ScientificState,
    StudyRequest,
    canonical_json_bytes,
)
from .providers import ProviderDescriptor, ProviderRegistry, ProviderResult


class ProblemContractProvider:
    descriptor = ProviderDescriptor(
        capability=Capability.PROBLEM_CONTRACT,
        provider_id="public-problem-contract",
        implementation_version="1",
        equations_id="request-bound",
        conventions_id="request-bound",
        runtime_fingerprint=f"cpython-{platform.python_version()}",
        numerical_policy_fingerprint="request-bound",
        upstream_artifact_types=(),
        output_artifact_type="problem-contract",
        available=True,
        evidence_level="schema-validated",
    )

    def execute(
        self, request: StudyRequest, upstream: Mapping[Capability, object]
    ) -> ProviderResult:
        if upstream:
            raise ValueError("problem contract cannot have upstream artifacts")
        request_mapping = request.to_mapping()
        return ProviderResult(
            payload={
                "request": request_mapping,
                "request_sha256": hashlib.sha256(
                    canonical_json_bytes(request_mapping)
                ).hexdigest(),
            },
            evidence=EvidenceState(
                carrier=CarrierState.VALID,
                execution=ExecutionState.SUCCEEDED,
                numerical=NumericalState.ACCEPTED,
                scientific=ScientificState.NOT_EVALUATED,
            ),
        )


def default_registry() -> ProviderRegistry:
    return ProviderRegistry((ProblemContractProvider(),))
