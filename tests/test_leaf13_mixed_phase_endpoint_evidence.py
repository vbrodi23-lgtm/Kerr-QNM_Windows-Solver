from __future__ import annotations

from copy import deepcopy
import unittest

from tests.fixtures import valid_horizon_endpoint_search_evidence
from windows_solver.response_engine import (
    PROMOTED_ROOT_READOUT_POLICY,
    _validated_successful_horizon_endpoint_search_evidence,
)


class Leaf13MixedPhaseEndpointEvidenceTests(unittest.TestCase):
    @staticmethod
    def _request_binding() -> dict[str, object]:
        return {
            "operation": "root-readout",
            "mechanism_id": "horizon-admittance",
            "policy": {
                "promoted_root_readout_policy": PROMOTED_ROOT_READOUT_POLICY,
                "endpoint_series_order": 28,
                "horizon_endpoint_recovery_policy_identity": (
                    "adaptive-horizon-endpoint-recovery/v1"
                ),
                "horizon_endpoint_maximum_order": 112,
                "horizon_endpoint_prefix_minimum_order": 4,
                "horizon_endpoint_prefix_order_step": 4,
                "horizon_endpoint_rho_candidates": [
                    "-10",
                    "-25",
                    "-50",
                    "-75",
                    "-100",
                ],
                "horizon_endpoint_rho_floor": "-400",
                "horizon_rho_inner_min": "-400",
            },
        }

    def test_accepts_primary_truncation_resolution_endpoint_evidence(self):
        request = self._request_binding()
        primary = valid_horizon_endpoint_search_evidence(request)[0]

        truncation_request = deepcopy(request)
        truncation_request["policy"]["endpoint_series_order"] = 36
        truncation = valid_horizon_endpoint_search_evidence(
            truncation_request
        )[0]

        # The Julia worker accumulates all three successful phases in one
        # response. TRUNCATION alone uses PRIMARY order + 8; RESOLUTION returns
        # to the PRIMARY order while tightening the ODE controls.
        evidence = [primary, truncation, deepcopy(primary)]

        self.assertEqual(
            _validated_successful_horizon_endpoint_search_evidence(
                evidence, request
            ),
            evidence,
        )

    def test_rejects_endpoint_order_not_owned_by_a_promoted_phase(self):
        request = self._request_binding()
        primary = valid_horizon_endpoint_search_evidence(request)[0]

        forged_request = deepcopy(request)
        forged_request["policy"]["endpoint_series_order"] = 37
        forged = valid_horizon_endpoint_search_evidence(forged_request)[0]

        with self.assertRaisesRegex(
            ValueError, "horizon endpoint search evidence is invalid"
        ):
            _validated_successful_horizon_endpoint_search_evidence(
                [primary, forged], request
            )

    def test_nonpromoted_receipt_cannot_claim_truncation_refinement(self):
        request = self._request_binding()
        del request["policy"]["promoted_root_readout_policy"]
        primary = valid_horizon_endpoint_search_evidence(request)[0]

        truncation_request = deepcopy(request)
        truncation_request["policy"]["endpoint_series_order"] = 36
        truncation = valid_horizon_endpoint_search_evidence(
            truncation_request
        )[0]

        with self.assertRaisesRegex(
            ValueError, "horizon endpoint search evidence is invalid"
        ):
            _validated_successful_horizon_endpoint_search_evidence(
                [primary, truncation], request
            )

    def test_non_root_readout_cannot_claim_truncation_refinement(self):
        request = self._request_binding()
        request["operation"] = "fixed-root-determinant-sample"
        primary = valid_horizon_endpoint_search_evidence(request)[0]

        truncation_request = deepcopy(request)
        truncation_request["policy"]["endpoint_series_order"] = 36
        truncation = valid_horizon_endpoint_search_evidence(
            truncation_request
        )[0]

        with self.assertRaisesRegex(
            ValueError, "horizon endpoint search evidence is invalid"
        ):
            _validated_successful_horizon_endpoint_search_evidence(
                [primary, truncation], request
            )


if __name__ == "__main__":
    unittest.main()
