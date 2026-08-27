from __future__ import annotations

from pathlib import Path
import unittest

from windows_solver.cli import build_parser


class PR65LauncherTests(unittest.TestCase):
    def test_cli_has_four_explicit_non_chaining_pass_commands(self):
        parser = build_parser()
        common = ["examples/m02-campaign.json", "--checkpoint", "state.json"]
        for command in (
            "campaign-survey-binary64",
            "campaign-survey-promoted",
            "campaign-certify",
            "campaign-evidence-validate",
        ):
            arguments = parser.parse_args([
                command,
                *common,
                *(
                    (
                        "--binary64-lock",
                        "state.json.binary64-lock.json",
                        "--calibration-receipt-path",
                        "calibration.json",
                        "--calibration-receipt-sha256",
                        "a" * 64,
                    )
                    if command == "campaign-survey-promoted"
                    else ()
                ),
            ])
            self.assertEqual(command, arguments.command)

    def test_powershell_default_runs_the_locked_layer1_to_layer2_chain(self):
        launcher = Path("m02.ps1").read_text(encoding="utf-8")

        self.assertIn('[string]$Profile = "survey"', launcher)
        self.assertIn('[string]$SurveyPass = "full"', launcher)
        self.assertIn('[ValidateSet("binary64", "promoted", "full")]', launcher)
        self.assertIn("[switch]$NewCampaign", launcher)
        self.assertIn(
            "Resume requires an existing checkpoint. Use -NewCampaign",
            launcher,
        )
        self.assertIn("-NewCampaign refuses an existing checkpoint", launcher)
        self.assertIn("campaign-survey-binary64", launcher)
        self.assertIn("campaign-lock-binary64", launcher)
        self.assertIn("campaign-survey-promoted", launcher)
        self.assertIn("Ensure-Binary64Lock", launcher)
        self.assertNotIn("campaign-validate", launcher)
        self.assertNotIn("Clear-Host", launcher)

    def test_launcher_discloses_resolved_state_before_execution(self):
        launcher = Path("m02.ps1").read_text(encoding="utf-8")
        disclosure = launcher.index('Write-Host "M02 campaign startup"')
        execution = launcher.index("Invoke-M02Command -Arguments $RunArguments")
        self.assertLess(disclosure, execution)
        for label in (
            "Resolved checkpoint",
            "Selected command",
            "Execution profile",
            "Survey pass",
            "Selection ID",
            "Checkpoint schema",
            "Recovered terminal count",
            "Binary64 pass count",
            "Promotion queue count",
            "Evidence counts",
            "Basic report directory",
            "Status path",
        ):
            self.assertIn(label, launcher)


if __name__ == "__main__":
    unittest.main()
