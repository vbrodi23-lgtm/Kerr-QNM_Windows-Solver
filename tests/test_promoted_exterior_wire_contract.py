from __future__ import annotations

import hashlib
from pathlib import Path
import re
import unittest

from windows_solver.contracts import canonical_json_bytes
from windows_solver.response_engine import (
    EXTERIOR_DETERMINANT_ABSOLUTE_ERROR_CERTIFICATE,
    RawDeterminantContract,
    VERIFIED_ENDPOINT_ERROR_MODEL,
    raw_determinant_contract_from_request,
    raw_determinant_contract_golden_cases,
)


PROVISIONAL_MODEL = "exterior-determinant-additive-channels/provisional-v1"
REPO_ROOT = Path(__file__).resolve().parents[1]


def _request(model: str, roles: list[str], mechanism: str) -> dict[str, object]:
    return {
        "mechanism_id": mechanism,
        "diagnostic_model_identity": model,
        "required_raw_determinant_roles": roles,
        "required_raw_determinant_count": len(roles),
        "policy": {"determinant_error_model": model},
    }


class PromotedExteriorWireContractTests(unittest.TestCase):
    def test_three_modes_have_immutable_exact_role_contracts(self):
        for case in raw_determinant_contract_golden_cases():
            request = case["request"]
            response = case["response"]
            with self.subTest(model=request["diagnostic_model_identity"]):
                contract = raw_determinant_contract_from_request(request)
                self.assertIsInstance(contract, RawDeterminantContract)
                self.assertEqual(
                    contract.required_raw_determinant_roles,
                    tuple(request["required_raw_determinant_roles"]),
                )
                self.assertEqual(
                    contract.required_raw_determinant_count,
                    request["required_raw_determinant_count"],
                )
                self.assertEqual(
                    contract.empirical_certificate_required,
                    response["certificate_requirement"] == "required",
                )
                self.assertEqual(
                    contract.calibration_receipt_required,
                    request["diagnostic_model_identity"]
                    == EXTERIOR_DETERMINANT_ABSOLUTE_ERROR_CERTIFICATE,
                )
                self.assertEqual(
                    response["provisional_stage"],
                    (
                        "persisted-authenticated"
                        if request["diagnostic_model_identity"] == PROVISIONAL_MODEL
                        else "not-applicable"
                    ),
                )
                self.assertEqual(
                    response["diagnostic_model_identity"],
                    contract.diagnostic_model_identity,
                )
                self.assertEqual(
                    response["required_raw_determinant_roles"],
                    list(contract.required_raw_determinant_roles),
                )
                self.assertEqual(
                    response["required_raw_determinant_count"],
                    contract.required_raw_determinant_count,
                )
                with self.assertRaises(TypeError):
                    contract.required_raw_determinant_roles[0] = "FORGED"

    def test_contract_is_not_inferred_from_mechanism_or_raw_count(self):
        request = {
            "mechanism_id": "exterior-light-ring",
            "policy": {
                "determinant_error_model": PROVISIONAL_MODEL,
            },
        }
        with self.assertRaisesRegex(ValueError, "diagnostic model identity"):
            raw_determinant_contract_from_request(request)

    def test_unknown_identity_and_role_count_mismatch_fail_closed(self):
        unknown = _request(
            "exterior-determinant-guess/v1",
            ["PRIMARY"],
            "exterior-light-ring",
        )
        with self.assertRaisesRegex(ValueError, "unknown diagnostic model"):
            raw_determinant_contract_from_request(unknown)

        mismatched = _request(
            PROVISIONAL_MODEL,
            ["PRIMARY"],
            "exterior-light-ring",
        )
        mismatched["required_raw_determinant_count"] = 3
        with self.assertRaisesRegex(ValueError, "role/count"):
            raw_determinant_contract_from_request(mismatched)

    def test_model_identity_changes_authenticated_request_digest(self):
        provisional = _request(
            PROVISIONAL_MODEL,
            ["PRIMARY"],
            "exterior-light-ring",
        )
        empirical = _request(
            EXTERIOR_DETERMINANT_ABSOLUTE_ERROR_CERTIFICATE,
            ["PRIMARY", "TRUNCATION", "RESOLUTION"],
            "exterior-light-ring",
        )
        self.assertNotEqual(
            hashlib.sha256(canonical_json_bytes(provisional)).hexdigest(),
            hashlib.sha256(canonical_json_bytes(empirical)).hexdigest(),
        )

    def test_provisional_contract_rejects_each_empirical_only_field(self):
        for field in (
            "determinant_error_required_term_classes",
            "determinant_error_certificate_statement",
            "determinant_error_safety_factor",
            "promoted_control_calibration_receipt_sha256",
            "empirical_control_profile_sha256",
        ):
            with self.subTest(field=field):
                request = _request(
                    PROVISIONAL_MODEL,
                    ["PRIMARY"],
                    "exterior-light-ring",
                )
                request["policy"][field] = "forbidden"
                with self.assertRaisesRegex(ValueError, "provisional"):
                    raw_determinant_contract_from_request(request)

    def test_production_has_no_mechanism_only_raw_count_expression(self):
        backend = (
            REPO_ROOT / "src/windows_solver/julia_response_backend.py"
        ).read_text(encoding="utf-8")
        engine = (
            REPO_ROOT / "src/windows_solver/response_engine.py"
        ).read_text(encoding="utf-8")
        forbidden = re.compile(
            r"expected_raw_determinant_count\s*=\s*\(\s*1\s+if\s+"
            r"job\.mechanism_id\s*==.*?else\s+3\s*\)",
            re.DOTALL,
        )
        self.assertIsNone(forbidden.search(backend))
        self.assertIsNone(forbidden.search(engine))


if __name__ == "__main__":
    unittest.main()
