from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from windows_solver.contracts import canonical_json_bytes
from windows_solver.promoted_control_calibration import (
    ARCHIVED_AUTHENTICATED_LOWER_BOUND_UNAVAILABLE,
    DERIVATIVE_AUTHENTICATION_UNAVAILABLE,
    EMPIRICAL_TEST_ONLY_NO_ARCHIVED_FLOOR,
    EXTERIOR_DETERMINANT_ABSOLUTE_ERROR_CERTIFICATE,
    CalibrationReceiptError,
    DerivativeAuthenticationUnavailable,
    PROMOTED_CONTROL_EMPIRICAL_CALIBRATION_IDENTITY,
    authenticated_derivative_lower_bound_abs,
    empirical_root_error_radius_abs,
    load_calibration_receipt,
    load_default_calibration_receipt,
)


class PromotedControlCalibrationTests(unittest.TestCase):
    """Breaks if default promoted execution can bypass the approved receipt."""

    def test_committed_receipt_is_sha_bound_and_covers_exactly_five_pairs(self) -> None:
        receipt = load_default_calibration_receipt()

        self.assertEqual(
            receipt.identity, PROMOTED_CONTROL_EMPIRICAL_CALIBRATION_IDENTITY
        )
        self.assertEqual(
            receipt.certificate_identity,
            EXTERIOR_DETERMINANT_ABSOLUTE_ERROR_CERTIFICATE,
        )
        self.assertEqual(receipt.certificate_safety_factor, 64)
        self.assertTrue(receipt.empirical)
        self.assertTrue(receipt.operator_approved)
        self.assertFalse(receipt.interval_arithmetic)
        self.assertFalse(receipt.independent_mathematical_proof)
        self.assertEqual(
            receipt.covered_pairs,
            frozenset({
                ("exterior-wronskian/v1", 40),
                ("exterior-wronskian/v1", 80),
                ("exterior-wronskian/v1", 120),
                ("horizon-scattering/v1", 80),
                ("horizon-scattering/v1", 120),
            }),
        )
        self.assertEqual(
            receipt.sha256,
            hashlib.sha256(canonical_json_bytes(receipt.to_mapping())).hexdigest(),
        )
        self.assertEqual(
            receipt.budget_for("exterior-wronskian/v1", 80).precision_tier.value,
            "bigfloat-80",
        )
        self.assertEqual(
            receipt.budget_for("horizon-scattering/v1", 120).precision_tier.value,
            "bigfloat-120",
        )
        self.assertEqual(
            receipt.source_audit_sha256,
            "a31a266c8488a7b19510a8d3fea4497cddcb2108eb9e424e27c396fa26ad6ae0",
        )
        for family in ("exterior-wronskian/v1", "horizon-scattering/v1"):
            self.assertIsNone(receipt.derivative_floor_for(family))
            self.assertEqual(
                receipt.derivative_floor_status_for(family),
                ARCHIVED_AUTHENTICATED_LOWER_BOUND_UNAVAILABLE,
            )
        exterior_40 = receipt.budget_for("exterior-wronskian/v1", 40)
        exterior_80 = receipt.budget_for("exterior-wronskian/v1", 80)
        self.assertEqual(
            exterior_40.base_ode_controls,
            exterior_80.base_ode_controls,
        )
        self.assertEqual(
            exterior_40.refinement_ode_controls,
            exterior_80.refinement_ode_controls,
        )

    def test_pinned_override_rejects_wrong_digest_and_noncanonical_bytes(self) -> None:
        receipt = load_default_calibration_receipt()
        canonical = canonical_json_bytes(receipt.to_mapping())
        expected_sha256 = hashlib.sha256(canonical).hexdigest()

        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "calibration.json"
            path.write_bytes(canonical)
            self.assertEqual(
                load_calibration_receipt(path, expected_sha256).sha256,
                expected_sha256,
            )
            with self.assertRaisesRegex(CalibrationReceiptError, "digest"):
                load_calibration_receipt(path, "0" * 64)

            noncanonical = canonical + b"\n"
            path.write_bytes(noncanonical)
            with self.assertRaisesRegex(CalibrationReceiptError, "canonical"):
                load_calibration_receipt(
                    path, hashlib.sha256(noncanonical).hexdigest()
                )

    def test_current_run_derivative_authentication_and_empirical_disk(self) -> None:
        receipt = load_default_calibration_receipt()
        self.assertEqual(
            receipt.execution_status,
            EMPIRICAL_TEST_ONLY_NO_ARCHIVED_FLOOR,
        )
        lower_bound = authenticated_derivative_lower_bound_abs(
            derivative_abs=12.0,
            step_disagreement_abs=0.5,
            propagated_error_abs=0.25,
        )
        self.assertEqual(lower_bound, 11.25)
        self.assertEqual(
            empirical_root_error_radius_abs(
                determinant_error_abs=2.25,
                derivative_lower_bound_abs=lower_bound,
            ),
            0.2,
        )
        for derivative_abs, step_error, propagated_error in (
            (1.0, 0.5, 0.5),
            (float("inf"), 0.5, 0.25),
            (1.0, float("nan"), 0.25),
        ):
            with self.assertRaises(DerivativeAuthenticationUnavailable) as caught:
                authenticated_derivative_lower_bound_abs(
                    derivative_abs=derivative_abs,
                    step_disagreement_abs=step_error,
                    propagated_error_abs=propagated_error,
                )
            self.assertEqual(
                caught.exception.code,
                DERIVATIVE_AUTHENTICATION_UNAVAILABLE,
            )

    def test_receipt_parser_rejects_implicit_operator_approval(self) -> None:
        receipt = load_default_calibration_receipt()
        forged = json.loads(canonical_json_bytes(receipt.to_mapping()))
        forged["operator_approval"]["status"] = "pending/v1"
        raw = canonical_json_bytes(forged)

        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "forged-calibration.json"
            path.write_bytes(raw)
            with self.assertRaisesRegex(CalibrationReceiptError, "operator"):
                load_calibration_receipt(
                    path, hashlib.sha256(raw).hexdigest()
                )

    def test_default_loader_rejects_altered_packaged_source_audit(self) -> None:
        class Resource:
            def __init__(self, raw: bytes) -> None:
                self.raw = raw

            def read_bytes(self) -> bytes:
                return self.raw

        class Root:
            def __init__(self, resources: dict[str, bytes]) -> None:
                self.resources = resources

            def joinpath(self, path: str) -> Resource:
                return Resource(self.resources[path])

        package_data = Path("src/windows_solver/data")
        root = Root({
            "data/promoted_control_empirical_calibration_v1.json": (
                package_data / "promoted_control_empirical_calibration_v1.json"
            ).read_bytes(),
            "data/promoted_control_derivative_lower_bound_source_audit_v1.json": b"{}",
        })
        with patch(
            "windows_solver.promoted_control_calibration.files",
            return_value=root,
        ):
            with self.assertRaisesRegex(
                CalibrationReceiptError, "source audit digest"
            ):
                load_default_calibration_receipt()


if __name__ == "__main__":
    unittest.main()
