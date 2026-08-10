from __future__ import annotations

import json
import hashlib
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from windows_solver.contracts import canonical_json_bytes
from windows_solver.response_engine import (
    ComponentStatus,
    NumericalPolicy,
    RECORDED_REPLAY_BACKEND_ID,
    RECORDED_SMOKE_CASES,
    RecordedReplayBackend,
    ResponseComponentJob,
    run_component,
    build_response_plan,
    run_response_plan,
    validate_response_checkpoint,
)
from windows_solver.response_batches import (
    PREDECLARED_CAMPAIGN_SMOKE_LEAF_IDS,
    run_predeclared_campaign_smoke,
)


ROOT = Path(__file__).resolve().parents[1]


EXPECTED_BUNDLE_HASHES = {
    "baselines": "b23966dca92d3ef4ecea9123e0ddef9eb70ee92ccd45acd8e0eab18f7924f5be",
    "components": "372f37cd8e69ab38fec577a4453a10c9a7972b52551d4f0acf96a85f3206bb19",
    "levels": "cef7635465a6ad91ed37be52099308db2099779e1b87b916e8e491ee94201ab9",
    "protocol": "25172794cd1b16e6589690a29fc3809453cf3a58d0f252dd5055906666708c99",
    "reduction": "5a9e658948100436de9e514615a9d68d86b7961ce27f31f981aec965deb9e780",
    "repeats": "21e3910b4caa4c3c50df4e5cb7f1bce29712907b794b77081bcffe578d6193bd",
    "signed-roots": "60ac24ef74010ad3b07acdc5d730872bce527e55d08e92b10b1bd8dbd826362e",
    "summary": "60d88305ce85e4182e69dda8f83b23f0be3a61d2773020d170f3ab15b3a08ba8",
}


EXPECTED_CASES = {
    "b-prime-leaf-9e5777728144433e089f9559b92b6e139e16115a5a53099f40403a45297aa3c3": (
        "a0.95-s-2-l2-m2-n0-unclassified-gravitational-horizon_admittance",
        ComponentStatus.CONVERGED,
        complex(-0.011769566778111728, -0.11580196973927197),
    ),
    "b-prime-leaf-7ef38d6f95c161d0b4c6650d470898c0742ad6ae8440e89956312344c0db6aac": (
        "a0.95-s-2-l3-m3-n0-unclassified-gravitational-fixed_r3",
        ComponentStatus.CONVERGED,
        complex(-0.009503017524481693, 0.005674069428375159),
    ),
    "b-prime-leaf-7f12759244119c8e819ef09cc5f3ec2e76054d77b6a1e0b12e3bb742397b635e": (
        "a0.95-s-2-l4-m4-n0-unclassified-gravitational-light_ring",
        ComponentStatus.CONVERGED,
        complex(-6.044879730914461e-05, 5.7308575126165565e-05),
    ),
    "b-prime-leaf-4c8594e4a59486a1c56206e41cd7f7f3ff1ab5193a5ff6b699cbe9492bc45355": (
        "a0.999-s-2-l2-m2-n0-unclassified-gravitational-horizon_admittance",
        ComponentStatus.CONVERGED,
        complex(0.08946828545200256, -0.09159745081794515),
    ),
    "b-prime-leaf-e0a48b72b4071c5c88c66955420dc2748cfeeac577b8fd1c399f171f5fa08475": (
        "a0.999-s-2-l4-m4-n0-unclassified-gravitational-light_ring",
        ComponentStatus.NOT_CONVERGED,
        None,
    ),
}


class RecordedResponseSmokeTests(unittest.TestCase):
    def test_campaign_smoke_is_exactly_ten_predeclared_replay_and_contract_cases(self) -> None:
        expected = (
            "b-prime-leaf-9e5777728144433e089f9559b92b6e139e16115a5a53099f40403a45297aa3c3",
            "b-prime-leaf-7ef38d6f95c161d0b4c6650d470898c0742ad6ae8440e89956312344c0db6aac",
            "b-prime-leaf-4eb508d767bea5cddc3f7c0eb120c1a9cc184122900f4d7ec86b56c98ddab596",
            "b-prime-leaf-3ee2b2dcdc5276cbcd51264f1210002314acd3ff845bb7a464f1e9333e9115c5",
            "b-prime-leaf-e0a48b72b4071c5c88c66955420dc2748cfeeac577b8fd1c399f171f5fa08475",
            "b-prime-leaf-fc5998bf989465575d276b6a1ad4758dbb1cdacc25e1c7554185f0c38e170332",
            "b-prime-leaf-29476bee7eab938f57ee149c682a367cd3e65f2b3337e90aeae91009998d08a2",
            "b-prime-leaf-bef33f29593b50014490d255e06e90e6e0fb4b94868a7906d7d10db62522cbbd",
            "b-prime-leaf-0784febf73878ce64ed23c8284325d2dc5ca30ce97cdccb543c0250371d39d7a",
            "b-prime-leaf-05897ef7c7de073f4ae158d8ebce3da469eaebb0985a54bf30e8ed102c533d5f",
        )
        self.assertEqual(PREDECLARED_CAMPAIGN_SMOKE_LEAF_IDS, expected)
        summary = run_predeclared_campaign_smoke()
        self.assertEqual(tuple(item.leaf_id for item in summary.records), expected)
        self.assertEqual(
            [item.evidence_kind for item in summary.records].count(
                "authenticated-recorded-replay"
            ),
            3,
        )
        self.assertEqual(
            [item.evidence_kind for item in summary.records].count(
                "synthetic-orchestration-contract"
            ),
            7,
        )
        by_id = {item.leaf_id: item.record for item in summary.records}
        self.assertEqual(by_id[expected[4]].state, "UNRESOLVED")
        self.assertEqual(
            tuple(stage.outcome.digits for stage in by_id[expected[7]].stages),
            (64, 80),
        )
        self.assertEqual(
            tuple(stage.outcome.digits for stage in by_id[expected[8]].stages),
            (64, 80, 120),
        )
        self.assertEqual(by_id[expected[9]].state, "MISSING_PRECISION")
    def test_resealed_checkpoint_rejects_raw_identity_and_baseline_omega_tampering(self) -> None:
        """Catches receipt-preserving changes to installed readout identity/root bytes."""

        backend = RecordedReplayBackend.load()
        case = RECORDED_SMOKE_CASES[0]
        plan = build_response_plan(
            (case.leaf_id,),
            policy=NumericalPolicy(),
            backend_identity=backend.identity,
            job_binder=backend.bind_job,
        )
        mutations = (
            ("root-reference", lambda result: result["baseline"].__setitem__(
                "root_reference_id", "forged-installed-root"
            )),
            ("branch", lambda result: result["levels"][0]["real_plus"].__setitem__(
                "branch_id", "forged-installed-branch"
            )),
            ("equation", lambda result: result["levels"][-1]["imaginary_minus"].__setitem__(
                "equation_id", "forged-installed-equation"
            )),
            ("baseline-omega", lambda result: result["baseline"]["omega"].__setitem__(
                "real", result["baseline"]["omega"]["real"] + 1.0e-9
            )),
        )
        for label, mutate in mutations:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temporary:
                checkpoint = Path(temporary) / "cohort.json"
                run_response_plan(plan, backend, checkpoint, resume=False)
                forged = json.loads(checkpoint.read_text(encoding="utf-8"))
                mutate(forged["results"][0])
                forged["results_sha256"] = hashlib.sha256(
                    canonical_json_bytes(forged["results"])
                ).hexdigest()
                checkpoint.write_bytes(canonical_json_bytes(forged))
                with self.assertRaisesRegex(ValueError, "checkpoint raw readout"):
                    validate_response_checkpoint(plan, checkpoint)

    def test_replay_source_to_installed_root_mapping_is_checkpoint_bound(self) -> None:
        """Catches relabeling source roots or resealing a forged mapping receipt."""

        backend = RecordedReplayBackend.load()
        case = RECORDED_SMOKE_CASES[0]
        plan = build_response_plan(
            (case.leaf_id,),
            policy=NumericalPolicy(),
            backend_identity=backend.identity,
            job_binder=backend.bind_job,
        )
        receipt = plan.jobs[0].source_root_mapping
        self.assertNotEqual(
            receipt["source_root_reference_id"],
            receipt["installed_root_reference_id"],
        )
        self.assertNotEqual(
            receipt["source_branch_id"], receipt["installed_branch_id"]
        )
        self.assertLessEqual(
            receipt["measured_delta_abs"], receipt["mapping_tolerance_abs"]
        )
        self.assertEqual(len(receipt["mapping_receipt_sha256"]), 64)

        with tempfile.TemporaryDirectory() as temporary:
            checkpoint = Path(temporary) / "cohort.json"
            summary = run_response_plan(
                plan, backend, checkpoint, resume=False
            )
            self.assertEqual(summary.results[0].lineage["source_root_mapping"], receipt)
            self.assertEqual(summary.results[0].baseline.source_root_mapping, receipt)

            forged = json.loads(checkpoint.read_text(encoding="utf-8"))
            forged["results"][0]["lineage"]["source_root_mapping"][
                "measured_delta_abs"
            ] += 1.0e-9
            forged["results_sha256"] = hashlib.sha256(
                canonical_json_bytes(forged["results"])
            ).hexdigest()
            checkpoint.write_bytes(canonical_json_bytes(forged))
            with self.assertRaisesRegex(ValueError, "source root mapping"):
                validate_response_checkpoint(plan, checkpoint)

    def test_replay_binds_identity_diagnostics_and_complete_component_outcome(self) -> None:
        """Catches replay relabeling rows or discarding repeat-derived channels."""

        backend = RecordedReplayBackend.load()
        for case in RECORDED_SMOKE_CASES[:-1]:
            job = ResponseComponentJob.from_leaf_id(
                case.leaf_id,
                policy=NumericalPolicy(),
                backend_identity=backend.identity,
            )
            result = run_component(job, backend)
            recorded = backend.recorded_component(case.component_id)
            backend.validate_reconstructed_result(job, result)
            self.assertEqual(result.convergence_basis, recorded["convergence_basis"])
            self.assertGreater(result.error_channels["truncation"], 0.0)
            self.assertGreater(result.error_channels["resolution"], 0.0)
            self.assertGreater(result.error_channels["seed-path"], 0.0)

    def test_pinned_bundle_hashes_and_predeclared_cases_are_exact(self) -> None:
        """Catches fixture drift or post-hoc replacement of the smoke selection."""

        backend = RecordedReplayBackend.load()
        self.assertEqual(backend.bundle_sha256s, EXPECTED_BUNDLE_HASHES)
        self.assertEqual(backend.identity.backend_id, RECORDED_REPLAY_BACKEND_ID)
        self.assertEqual(
            backend.identity.source_commit,
            "0c1e8a3d3bca6e608c34e111476a4f6dcb73e86e",
        )
        self.assertEqual(
            {case.leaf_id: case.component_id for case in RECORDED_SMOKE_CASES},
            {leaf_id: expected[0] for leaf_id, expected in EXPECTED_CASES.items()},
        )

    def test_raw_signed_roots_reconstruct_recorded_head_tail_and_risk_outcomes(self) -> None:
        """Catches replay trusting component centres instead of reducing raw signed roots."""

        backend = RecordedReplayBackend.load()
        for case in RECORDED_SMOKE_CASES:
            component_id, expected_status, expected_response = EXPECTED_CASES[case.leaf_id]
            with self.subTest(component_id=component_id):
                job = ResponseComponentJob.from_leaf_id(
                    case.leaf_id,
                    policy=NumericalPolicy(),
                    backend_identity=backend.identity,
                )
                result = run_component(job, backend)
                self.assertEqual(result.status, expected_status)
                self.assertEqual(case.component_id, component_id)
                recorded = backend.recorded_component(component_id)
                self.assertEqual(recorded["status"], expected_status.value)
                if expected_response is None:
                    self.assertIsNone(result.response)
                    self.assertGreaterEqual(len(result.levels), 4)
                else:
                    self.assertIsNotNone(result.response)
                    self.assertAlmostEqual(result.response.real, expected_response.real, places=13)
                    self.assertAlmostEqual(result.response.imag, expected_response.imag, places=13)
                    self.assertAlmostEqual(result.response.real, float(recorded["response_re"]), places=13)
                    self.assertAlmostEqual(result.response.imag, float(recorded["response_im"]), places=13)
                    self.assertGreaterEqual(len(result.raw_readouts), 17)

    def test_powershell_friendly_plan_run_resume_validate_are_deterministic(self) -> None:
        """Catches selected replay commands emitting multiple objects or repeating warm work."""

        selected = [RECORDED_SMOKE_CASES[0].leaf_id, RECORDED_SMOKE_CASES[-1].leaf_id]
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            selection = directory / "selection.json"
            checkpoint = directory / "checkpoint.json"
            selection.write_bytes(canonical_json_bytes({
                "schema_version": 1,
                "backend_id": RECORDED_REPLAY_BACKEND_ID,
                "leaf_ids": selected,
            }))

            def invoke(command: str) -> subprocess.CompletedProcess[str]:
                return subprocess.run(
                    [
                        sys.executable,
                        "-m",
                        "windows_solver",
                        command,
                        str(selection),
                        "--checkpoint",
                        str(checkpoint),
                    ],
                    cwd=ROOT,
                    env={"PYTHONPATH": str(ROOT / "src")},
                    text=True,
                    capture_output=True,
                )

            planned = invoke("response-plan")
            self.assertEqual(planned.returncode, 0, planned.stderr)
            self.assertEqual(len(planned.stdout.splitlines()), 1)
            self.assertEqual(json.loads(planned.stdout)["job_count"], 2)

            cold = invoke("response-run")
            self.assertEqual(cold.returncode, 0, cold.stderr)
            self.assertEqual(json.loads(cold.stdout)["executed_count"], 2)
            warm = invoke("response-resume")
            self.assertEqual(warm.returncode, 0, warm.stderr)
            self.assertEqual(json.loads(warm.stdout)["reused_count"], 2)
            validated = invoke("response-validate")
            self.assertEqual(validated.returncode, 0, validated.stderr)
            self.assertEqual(json.loads(validated.stdout)["state"], "COMPLETE")

    def test_selection_rejects_nonrecorded_leaf_before_checkpoint_creation(self) -> None:
        """Catches a five-row replay backend planning an unsupported B-prime leaf."""

        unsupported = (
            "b-prime-leaf-fc945cdbf25233004c8c36973c3ce1d1fd824c524b2e3cf36f7962dbe12c7e16"
        )
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            selection = directory / "selection.json"
            checkpoint = directory / "checkpoint.json"
            selection.write_bytes(canonical_json_bytes({
                "schema_version": 1,
                "backend_id": RECORDED_REPLAY_BACKEND_ID,
                "leaf_ids": [unsupported],
            }))
            planned = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "windows_solver",
                    "response-plan",
                    str(selection),
                    "--checkpoint",
                    str(checkpoint),
                ],
                cwd=ROOT,
                env={"PYTHONPATH": str(ROOT / "src")},
                text=True,
                capture_output=True,
            )
            self.assertEqual(planned.returncode, 2)
            self.assertFalse(checkpoint.exists())


if __name__ == "__main__":
    unittest.main()
