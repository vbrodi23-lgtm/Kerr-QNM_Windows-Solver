from pathlib import Path
import unittest


class M02RecoverScriptTests(unittest.TestCase):
    def test_recovery_and_cutover_are_explicit_separate_paths(self) -> None:
        script = Path("m02-recover.ps1").read_text(encoding="utf-8")

        self.assertIn('"campaign-recover"', script)
        self.assertIn("[switch]$CommitCutover", script)
        self.assertIn('"campaign-recovery-validate"', script)
        self.assertIn("pre-pr65-recovery", script)
        self.assertIn("[IO.File]::Replace", script)
        self.assertIn("Flush($true)", script)
        self.assertNotIn("campaign-run", script)
        self.assertNotIn("campaign-resume", script)


if __name__ == "__main__":
    unittest.main()
