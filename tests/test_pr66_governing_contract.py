"""Static governance checks for the sole authoritative PR66 contract."""

from __future__ import annotations

import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = REPOSITORY_ROOT / "PR66_GOVERNING_COMPLETION_CONTRACT.md"
HISTORICAL_PLAN_PATH = (
    REPOSITORY_ROOT / "docs" / "engineering" / "pr66-completion-implementation-plan.md"
)


class Pr66GoverningContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.contract = CONTRACT_PATH.read_text(encoding="utf-8")

    def test_committed_contract_is_the_sole_authority_and_records_final_decisions(self) -> None:
        required = (
            "sole authoritative source for PR #66",
            "Root-seal reuse is exact-identity reuse, not leaf ownership.",
            "Background equivalence is an exact structural construction identity.",
            "The ordinary nine-sample fallback generates first-use evidence.",
            "Numerical reuse admission is exact-key scoped.",
            "tested_code_head_git_oid",
            "main_base_git_oid",
            "receipt_commit_git_oid",
            "Acceptance uses one metadata-only finalisation commit.",
            "Landing approval remains external.",
            "`landing_approval_status` equal to `PENDING`",
        )
        for statement in required:
            with self.subTest(statement=statement):
                self.assertIn(statement, self.contract)

    def test_committed_contract_contains_no_obsolete_competing_rules(self) -> None:
        obsolete = (
            "pr_head_sha256",
            "main_base_sha256",
            "first admitted reuse for each mechanism/contract version",
            "absolute discrepancy;",
            "optionally produce the equivalence proof as a distinct durable side effect",
        )
        for phrase in obsolete:
            with self.subTest(phrase=phrase):
                self.assertNotIn(phrase, self.contract)

    def test_metadata_only_finalisation_allowlist_is_exact(self) -> None:
        self.assertIn(
            "docs/engineering/pr66-native-acceptance.json\n"
            "docs/engineering/pr66-native-acceptance.md",
            self.contract,
        )
        self.assertIn("No other file may change in Y.", self.contract)

    def test_historical_plan_cannot_delete_or_compete_with_the_contract(self) -> None:
        plan = HISTORICAL_PLAN_PATH.read_text(encoding="utf-8")
        self.assertIn("non-normative historical planning record", plan)
        self.assertNotIn("git rm PR65_GOVERNING_PR_COMPLETION_RESTORED_ADDITIVE.md PR66_GOVERNING_COMPLETION_CONTRACT.md", plan)
        self.assertNotIn("- Delete: `PR66_GOVERNING_COMPLETION_CONTRACT.md`", plan)


if __name__ == "__main__":
    unittest.main()
