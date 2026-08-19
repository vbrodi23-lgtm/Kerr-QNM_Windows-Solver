from __future__ import annotations

from pathlib import Path
import unittest


class Production222EndpointRecoveryScriptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = (
            Path(__file__).resolve().parents[1]
            / "M02_Production_222_A9999_Endpoint_Recovery_v1.ps1"
        ).read_text(encoding="utf-8")

    def test_selects_exactly_the_primary_222_a09999_horizon_leaf(self) -> None:
        for required in (
            '"campaign-plan"',
            '$_.role -eq "primary"',
            '$_.mode_label -eq "222"',
            '$_.mechanism_id -eq "horizon-admittance"',
            '$_.coordinate_exact.numerator -eq 9999',
            '$_.coordinate_exact.denominator -eq 10000',
            '$Targets.Count -eq 1',
        ):
            self.assertIn(required, self.source)

    def test_is_cold_isolated_validates_and_preserves_stopped_checkpoint(self) -> None:
        for required in (
            '"campaign-run"',
            '"campaign-validate"',
            "$env:KERR_QNM_ROOT_READOUT_CACHE_ROOT",
            "$env:KERR_QNM_PARTIAL_COMPONENT_JOURNAL_ROOT",
            "$StoppedCheckpointSha256Before",
            "$StoppedCheckpointSha256After",
            "$StoppedCheckpointSha256After -eq $StoppedCheckpointSha256Before",
            'throw "Cold endpoint recovery refuses existing output',
        ):
            self.assertIn(required, self.source)

    def test_report_distinguishes_diagnostic_from_success_and_carries_full_endpoint_evidence(self) -> None:
        for required in (
            "endpoint_candidates",
            "endpoint_order",
            "ingoing_best_prefix_order",
            "outgoing_best_prefix_order",
            "predicted_reliable_digits",
            "selected_pair",
            "homogeneous_rhs_evaluations_before_pair",
            "final_typed_outcome",
            '$Record.state -eq "PRODUCED"',
            "diagnostic_only",
        ):
            self.assertIn(required, self.source)


if __name__ == "__main__":
    unittest.main()
