"""Non-physical precision-backend fixture for authenticated loader tests."""

import os
from pathlib import Path

from windows_solver.response_batches import PrecisionCapabilities, StageOutcome
from windows_solver.response_engine import VettedNativeDeterminantKernel


FIXTURE_VARIANT = "verified"
marker = os.environ.get("CAMPAIGN_PRECISION_FIXTURE_MARKER")
if marker:
    Path(marker).write_text(FIXTURE_VARIANT, encoding="utf-8")


class ContractBackend:
    identity = VettedNativeDeterminantKernel.identity
    precision_capabilities = PrecisionCapabilities((64,))

    def execute_stage(self, leaf, digits):
        return StageOutcome(
            digits=64,
            numerical_state="CONVERGED",
            component_result={
                "evidence_kind": "synthetic-orchestration-contract",
                "leaf_id": leaf.leaf_id,
                "role": leaf.role,
                "mechanism_id": leaf.mechanism_id,
                "digits": 64,
            },
            local_disk_radius_abs=1.0e-8,
        )


def create_backend():
    return ContractBackend()
