"""Versioned scientific payload validation for admitted built-in providers."""

from __future__ import annotations

from typing import Mapping

from .artifacts import ArtifactVerificationError
from .contracts import Capability, StudyRequest
from .linear_response import (
    LINEAR_RESPONSE_OUTPUT_ARTIFACT_TYPE,
    LINEAR_RESPONSE_PROVIDER_ID,
    validate_linear_response_payload,
)
from .spectrum import (
    SPECTRAL_OUTPUT_ARTIFACT_TYPE,
    SPECTRAL_PROVIDER_ID,
    validate_spectral_payload,
)


def validate_provider_payload(
    capability: Capability,
    artifact_type: str,
    provider: Mapping[str, object],
    request: StudyRequest,
    payload: Mapping[str, object],
) -> None:
    """Validate the scientific meaning not covered by envelope hashing.

    Content addressing proves that stored bytes did not change.  This
    dispatcher additionally proves that an admitted provider's payload still
    satisfies its versioned scientific contract.
    """

    if capability is Capability.SPECTRAL_CORE:
        if provider.get("provider_id") != SPECTRAL_PROVIDER_ID:
            raise ArtifactVerificationError(
                "unsupported spectral provider contract"
            )
        if artifact_type != SPECTRAL_OUTPUT_ARTIFACT_TYPE:
            raise ArtifactVerificationError(
                "spectral artifact output type is invalid"
            )
        try:
            validate_spectral_payload(request, provider, payload)
        except (KeyError, RecursionError, TypeError, ValueError) as error:
            raise ArtifactVerificationError(str(error)) from error
    elif capability is Capability.LINEAR_RESPONSE:
        if provider.get("provider_id") != LINEAR_RESPONSE_PROVIDER_ID:
            raise ArtifactVerificationError(
                "unsupported linear-response provider contract"
            )
        if artifact_type != LINEAR_RESPONSE_OUTPUT_ARTIFACT_TYPE:
            raise ArtifactVerificationError(
                "linear-response artifact output type is invalid"
            )
        try:
            validate_linear_response_payload(request, provider, payload)
        except (KeyError, RecursionError, TypeError, ValueError) as error:
            raise ArtifactVerificationError(str(error)) from error
