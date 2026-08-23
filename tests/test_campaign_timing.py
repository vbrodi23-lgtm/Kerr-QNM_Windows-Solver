from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from windows_solver.campaign_timing import (
    CampaignTimingLog,
    TimingFragment,
    TimingSessionRecorder,
    fold_timing_fragments,
)
from windows_solver.campaign_policy import (
    SurveyDisposition,
    SurveyPass,
    empty_schema11_checkpoint,
    record_survey_disposition,
)
from windows_solver.progress import ProgressContext, ProgressEventKind


class _Clock:
    def __init__(self):
        self.value = 100.0

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += seconds


class CampaignTimingTests(unittest.TestCase):
    def test_fixed_root_tier_records_direct_completed_time(self):
        clock = _Clock()
        with tempfile.TemporaryDirectory() as temporary:
            log = CampaignTimingLog(Path(temporary) / "timing.jsonl")
            recorder = TimingSessionRecorder(
                log=log,
                session_id="session-1",
                leaf_id="leaf-1",
                execution_profile="SURVEY",
                survey_pass="promoted",
                clock=clock,
            )
            recorder.start_tier("BF40")
            clock.advance(3.25)
            recorder.complete_tier()
            fragments = log.read()

        summary = fold_timing_fragments(fragments)
        self.assertEqual(3.25, summary.tier_seconds["BF40"])
        self.assertEqual(3.25, summary.total_leaf_seconds)
        self.assertEqual((), summary.reconstructed_tiers)

    def test_interrupted_sessions_sum_and_open_heartbeat_is_reconstructed(self):
        fragments = (
            TimingFragment.create(
                session_id="s1", sequence=0, leaf_id="leaf-1",
                execution_profile="SURVEY", survey_pass="promoted", tier="BF40",
                state="INTERRUPTED", elapsed_tier_seconds=4.0,
                elapsed_leaf_seconds=4.0, source="direct",
            ),
            TimingFragment.create(
                session_id="s2", sequence=0, leaf_id="leaf-1",
                execution_profile="SURVEY", survey_pass="promoted", tier="BF40",
                state="COMPLETED", elapsed_tier_seconds=2.0,
                elapsed_leaf_seconds=2.0, source="direct",
            ),
            TimingFragment.create(
                session_id="s3", sequence=0, leaf_id="leaf-1",
                execution_profile="SURVEY", survey_pass="promoted", tier="BF80",
                state="HEARTBEAT", elapsed_tier_seconds=1.5,
                elapsed_leaf_seconds=1.5, source="direct",
            ),
        )

        summary = fold_timing_fragments(fragments)

        self.assertEqual(6.0, summary.tier_seconds["BF40"])
        self.assertEqual(1.5, summary.tier_seconds["BF80"])
        self.assertEqual(7.5, summary.total_leaf_seconds)
        self.assertEqual(("BF80",), summary.reconstructed_tiers)

    def test_timing_log_rejects_digest_tampering(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "timing.jsonl"
            log = CampaignTimingLog(path)
            fragment = TimingFragment.create(
                session_id="s1", sequence=0, leaf_id="leaf-1",
                execution_profile="SURVEY", survey_pass="binary64", tier="binary64",
                state="COMPLETED", elapsed_tier_seconds=1.0,
                elapsed_leaf_seconds=1.0, source="direct",
            )
            log.append(fragment)
            value = json.loads(path.read_text(encoding="utf-8"))
            value["elapsed_tier_seconds"] = 0.9
            path.write_text(json.dumps(value) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "authentication"):
                log.read()

    def test_progress_contract_has_pass_sample_queue_report_and_timing_fields(self):
        context = ProgressContext.from_mapping({
            "execution_profile": "SURVEY",
            "survey_pass": "promoted",
            "pass_disposition": "COMPLETED",
            "evidence_level": "SCREENED",
            "promotion_reason": "FINITE_DIFFERENCE_NOISE_LIMIT",
            "promotion_queue_count": 3,
            "sample_count_used": 9,
            "sample_count_limit": 18,
            "root_read_count": 0,
            "root_read_limit": 0,
            "worker_launch_count": 1,
            "worker_launch_limit": 2,
            "report_state": "REPORTS_DEGRADED",
            "system_failure_fingerprint": "a" * 64,
            "binary64_seconds": 1.0,
            "bf40_seconds": 2.0,
            "bf80_seconds": 0.0,
            "bf120_seconds": 0.0,
            "total_leaf_seconds": 3.0,
        })
        self.assertEqual("SURVEY", context.execution_profile)
        for kind in (
            "CAMPAIGN_PASS_STARTED",
            "CAMPAIGN_PASS_COMPLETED",
            "LEAF_PASS_STARTED",
            "LEAF_PASS_DISPOSITION_RECORDED",
            "PROMOTION_QUEUED",
            "SURVEY_SAMPLE_STARTED",
            "SURVEY_SAMPLE_COMPLETED",
            "SYSTEM_FAILURE_RECORDED",
            "REPORT_STATUS_CHANGED",
        ):
            self.assertTrue(hasattr(ProgressEventKind, kind))

    def test_pass_ledger_rejects_timing_that_disagrees_with_fragments(self):
        fragment = TimingFragment.create(
            session_id="s1", sequence=0, leaf_id="leaf-1",
            execution_profile="SURVEY", survey_pass="promoted", tier="BF40",
            state="COMPLETED", elapsed_tier_seconds=2.0,
            elapsed_leaf_seconds=2.0, source="direct",
        )
        with self.assertRaisesRegex(ValueError, "disagrees"):
            record_survey_disposition(
                empty_schema11_checkpoint("campaign-1", "selection-1"),
                survey_pass=SurveyPass.PROMOTED,
                leaf_id="leaf-1",
                disposition=SurveyDisposition.UNRESOLVED,
                operation_identity="fixed-root/v1",
                precision_tiers=("BF40",),
                reason_code="FINITE_DIFFERENCE_NOISE_LIMIT",
                sample_count=9,
                sample_limit=18,
                root_read_count=0,
                root_read_limit=0,
                worker_launch_count=1,
                worker_launch_limit=2,
                tier_timing=({
                    "tier": "BF40", "elapsed_seconds": 9.0, "source": "direct"
                },),
                session_fragments=(fragment.to_mapping(),),
            )


if __name__ == "__main__":
    unittest.main()
