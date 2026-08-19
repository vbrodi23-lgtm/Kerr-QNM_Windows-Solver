from __future__ import annotations

from pathlib import Path
import unittest


class ProductionLightRingResponseRecoveryScriptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = (
            Path(__file__).resolve().parents[1]
            / "M02_Production_LightRing_A9999_Response_Recovery_v1.ps1"
        ).read_text(encoding="utf-8")

    def test_selects_only_the_three_exact_leaf_ids(self) -> None:
        for leaf_id in (
            "b-prime-leaf-7a86c1116062be2b0b9f06493cc5b3bec77cc7202b4f924531c4d965db4b539c",
            "b-prime-leaf-7d002095206ac650d4b8eca866ce403983284f47615943f819c3611f101bd4d5",
            "b-prime-leaf-3897345b92e3a31b02d9551b40e31efc70156c532526a7c2dfe79ec8bdad2d8c",
        ):
            self.assertIn(leaf_id, self.source)
        self.assertIn("$Targets.Count -eq 3", self.source)

    def test_exposes_deliberate_one_readout_stop_and_exact_resume_proof(self) -> None:
        for required in (
            "[switch]$ExerciseInterruptionResume",
            "Start-Process",
            "$CompletedReadoutCount -ge 1",
            "Stop-ProductionProcessTree -Process $CampaignProcess",
            "taskkill.exe /PID $Process.Id /T /F",
            "Wait-Process -Id $Process.Id",
            "$Process.WaitForExit()",
            '"campaign-resume"',
            "$FirstCompletedWorkUnitId",
            "$ReusedWorkUnitIds -contains $FirstCompletedWorkUnitId",
            "$ExecutedWorkUnitIds -notcontains $FirstCompletedWorkUnitId",
        ):
            self.assertIn(required, self.source)

    def test_interruption_launches_current_powershell_with_quoted_file_arguments(self):
        self.assertIn("$CurrentPowerShellExecutable = (Get-Process -Id $PID).Path", self.source)
        self.assertIn("$SolverPath = Join-Path $PackageRoot \"solver.ps1\"", self.source)
        self.assertIn("-FilePath $CurrentPowerShellExecutable", self.source)
        self.assertIn('"-File"', self.source)
        self.assertIn('("`\"{0}`\"" -f $SolverPath)', self.source)
        self.assertIn('("`\"{0}`\"" -f $SelectionPath)', self.source)
        self.assertIn('("`\"{0}`\"" -f $CheckpointPath)', self.source)
        self.assertNotIn(
            "Start-Process -FilePath (Join-Path $PackageRoot \"solver.ps1\")",
            self.source,
        )

    def test_resume_requires_a_checkpoint_and_cold_run_reuses_journal_without_one(self):
        checkpoint_branch = self.source.index(
            "if (Test-Path -LiteralPath $CheckpointPath -PathType Leaf)"
        )
        validation = self.source.index('"campaign-validate"', checkpoint_branch)
        resume = self.source.index('"campaign-resume"', checkpoint_branch)
        cold = self.source.index('"campaign-run"', resume)
        self.assertLess(validation, resume)
        self.assertLess(resume, cold)
        self.assertIn("journal reuses that exact work", self.source)

    def test_isolated_report_carries_every_recovery_and_precision_field(self) -> None:
        for required in (
            "$env:KERR_QNM_ROOT_READOUT_CACHE_ROOT",
            "$env:KERR_QNM_PARTIAL_COMPONENT_JOURNAL_ROOT",
            "old_and_added_epsilons",
            "signed_roots_by_precision_tier",
            "signal_noise_ratios",
            "safe_windows_considered",
            "selected_window",
            "excluded_fine_levels",
            "axis_and_order_diagnostics",
            "promoted_readout_count_by_tier",
            "branch_margins",
            "response_disk",
            "finite_amplitude_validation_status",
            "durable_resume_evidence",
        ):
            self.assertIn(required, self.source)

    def test_report_uses_real_optional_resolved_window_fields_under_strict_mode(self) -> None:
        self.assertIn("function Get-OptionalProperty", self.source)
        for field in (
            '"signal_noise_ratios"',
            '"candidate_windows"',
            '"selected_window"',
            '"excluded_fine_levels"',
            '"window_diagnostics"',
            '"promoted_readout_count_by_tier"',
            '"branch_margins"',
            '"exact_added_epsilons"',
            '"readout_specific_promotion_plan"',
        ):
            self.assertIn(field, self.source)
        self.assertNotIn("$Result.resolved_window.included_epsilons", self.source)
        self.assertNotIn("$Result.derivative_evidence.response_disk", self.source)
        self.assertNotIn("$Result.response_uncertainty_status", self.source)
        self.assertIn(
            'Get-OptionalProperty $Result "response_uncertainty_status"',
            self.source,
        )

    def test_calibration_override_is_path_and_sha_pinned(self) -> None:
        for required in (
            "[string]$CalibrationReceiptPath",
            "[string]$CalibrationReceiptSha256",
            "calibration receipt path and SHA-256 must be supplied together",
            '"--calibration-receipt-path"',
            '"--calibration-receipt-sha256"',
        ):
            self.assertIn(required, self.source)


if __name__ == "__main__":
    unittest.main()
