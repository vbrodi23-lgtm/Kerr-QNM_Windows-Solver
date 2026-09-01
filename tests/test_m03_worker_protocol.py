from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest

from tests.test_m03_handoff import _terminal_fixture
from windows_solver.contracts import canonical_json_bytes
from windows_solver.m03_campaign import build_campaign_plan, run_campaign
from windows_solver.m03_handoff import build_handoff, validate_handoff
from windows_solver.m03_policy import (
    KERNEL_NUMERICAL_POLICY_FIELDS,
    production_blockers,
    validate_m03_selection,
)
from windows_solver.m03_worker import (
    M03IdentityRejection,
    M03SystemFailure,
    PersistentM03Worker,
    worker_from_runtime_receipt,
)


ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "src/windows_solver/data/julia/m03_core.jl"
WORKER = ROOT / "src/windows_solver/data/julia/m03_worker.jl"
SELECTION = ROOT / "examples/m03-spectral-fields.json"


def _sha(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _ready_handoff() -> dict[str, object]:
    plan, selection, checkpoint = _terminal_fixture()
    handoff = build_handoff(
        plan=plan,
        selection=selection,
        checkpoint=checkpoint,
        checkpoint_path="fixture.json",
        created_utc="2026-09-01T00:00:00Z",
    )
    for node_index, node in enumerate(handoff["nodes"]):
        root_identity = node["spectral_seed"]["root_authority"][
            "root_identity_sha256"
        ]
        material = {
            "schema": "windows-solver.m02-domega-stencil/1",
            "root_identity_sha256": root_identity,
            "determinant_family": "exterior-wronskian/v1",
            "determinant_convention": (
                "wronskian-perturbed-Xin-with-Xup/v1"
            ),
            "determinant_normalisation": (
                "unit-asymptotic-branch-wronskian/v1"
            ),
            "scientific_operation_identity": (
                "canonical-exterior-background-wronskian/v1"
            ),
            "source_precision_tier": "bigfloat-40",
            "source_precision_bits": 165,
            "h": "1",
            "D0": {"real": "0", "imaginary": "0"},
            "D_plus_h": {"real": "1", "imaginary": "0"},
            "D_minus_h": {"real": "-1", "imaginary": "0"},
            "D_plus_half_h": {"real": "0.5", "imaginary": "0"},
            "D_minus_half_h": {"real": "-0.5", "imaginary": "0"},
            "coarse_derivative": {"real": "1", "imaginary": "0"},
            "fine_derivative": {"real": "1", "imaginary": "0"},
            "disagreement_abs": "0",
            "source_leaf_id": f"synthetic-leaf-{node_index}",
            "source_stage_sha256": _sha(["stage", node_index]),
            "source_sample_receipt_sha256s": [
                _sha(["sample", node_index, sample_index])
                for sample_index in range(4)
            ],
        }
        node["m02_domega_evidence"] = {
            **material,
            "request_sha256": _sha(material),
        }
        node["background_identity_sha256"] = _sha(
            ["background", node_index]
        )
    handoff["inventory"]["authenticated_domega_count"] = 48
    handoff["inventory"]["authenticated_background_count"] = 48
    material = {
        key: value for key, value in handoff.items() if key != "handoff_sha256"
    }
    handoff["handoff_sha256"] = _sha(material)
    return validate_handoff(handoff)


def _frozen_selection() -> dict[str, object]:
    selection = json.loads(SELECTION.read_text(encoding="utf-8"))
    selection["validation_thresholds"]["review_state"] = "FROZEN"
    for category in ("right_state", "co_mode", "pairing", "residue_projector"):
        for name in selection["validation_thresholds"][category]:
            selection["validation_thresholds"][category][name] = "1"
    integers = {"endpoint_order", "angular_pad", "quadrature_panels"}
    policy: dict[str, object] = {
        name: (8 if name in integers else "1e-20")
        for name in KERNEL_NUMERICAL_POLICY_FIELDS
        if name != "retained_rho_grid"
    }
    policy.update(
        {
            "readout_radius": "10",
            "rho_inner": "-10",
            "rho_outer": "10",
            "retained_rho_grid": ["-1", "0", "1"],
        }
    )
    selection["kernel_numerical_policy"] = policy
    return validate_m03_selection(selection)


class _SyntheticWorker:
    def __init__(self, first_node_identity: str) -> None:
        self.first_node_identity = first_node_identity
        self.first_node_calls = 0
        self.solve_requests: list[dict[str, object]] = []
        self.branch_requests: list[dict[str, object]] = []
        self.restart_count = 0

    def start(self) -> None:
        return None

    def close(self) -> None:
        return None

    def restart(self) -> None:
        self.restart_count += 1

    @staticmethod
    def _publish_manifest(
        directory: Path, manifest: dict[str, object]
    ) -> tuple[str, str]:
        directory.mkdir(parents=True, exist_ok=False)
        path = directory / (
            "branch-manifest.json"
            if "branch_identity" in manifest
            and "node_identity_sha256" not in manifest
            else "node-manifest.json"
        )
        payload = canonical_json_bytes(manifest)
        path.write_bytes(payload)
        return str(directory), hashlib.sha256(payload).hexdigest()

    def call(
        self, method: str, params: dict[str, object]
    ) -> dict[str, object]:
        request_sha = _sha([method, params])
        response_sha = _sha(["response", method, params])
        if method == "solve_node":
            request = copy.deepcopy(params)
            self.solve_requests.append(request)
            if params["node_identity_sha256"] == self.first_node_identity:
                self.first_node_calls += 1
                if self.first_node_calls == 1:
                    raise M03SystemFailure("synthetic worker restart seam")
                disposition = (
                    "PROMOTION_REQUIRED"
                    if params["precision_tier"] == "bigfloat-40"
                    else "UNRESOLVED"
                )
            else:
                disposition = "PRODUCED"
            directory = (
                Path(params["output_root"])
                / "nodes"
                / str(params["node_identity_sha256"])
                / "attempts"
                / request_sha
            )
            artifact_path, artifact_sha = self._publish_manifest(
                directory,
                {
                    "schema": "windows-solver.m03-node-manifest/1",
                    "disposition": disposition,
                    "node_identity_sha256": params["node_identity_sha256"],
                    "request_identity_sha256": request_sha,
                    "root_identity_sha256": params["upstream_root_identity"],
                    "branch_identity": params["branch_identity"],
                    "chain_position": params["chain_position"],
                    "precision_tier": params["precision_tier"],
                    "handoff_identity_sha256": params["m02_handoff_sha256"],
                    "numerical_policy_identity": params[
                        "numerical_policy_identity"
                    ],
                    "payload_hashes": {},
                },
            )
            return {
                "disposition": disposition,
                "node_identity_sha256": params["node_identity_sha256"],
                "root_identity_sha256": params["upstream_root_identity"],
                "precision_tier": params["precision_tier"],
                "artifact_path": artifact_path,
                "artifact_sha256": artifact_sha,
                "reason": (
                    "synthetic evidence" if disposition != "PRODUCED" else None
                ),
                "summary": {},
                "spin_identity": params["spin_identity"],
                "frozen_omega": params["frozen_omega"],
                "frozen_A": params["frozen_A"],
                "handoff_identity_sha256": params["m02_handoff_sha256"],
                "numerical_policy_identity": params[
                    "numerical_policy_identity"
                ],
                "rpc_request_identity_sha256": request_sha,
                "rpc_response_identity_sha256": response_sha,
            }
        if method == "reduce_branch":
            request = copy.deepcopy(params)
            self.branch_requests.append(request)
            dispositions = []
            for reference in params["branch_nodes"]:
                manifest_path = (
                    Path(reference["artifact_path"]) / "node-manifest.json"
                )
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                dispositions.append(manifest["disposition"])
            disposition = (
                "PRODUCED"
                if all(item == "PRODUCED" for item in dispositions)
                else "UNRESOLVED"
            )
            directory = (
                Path(params["output_root"])
                / "branches"
                / str(params["branch_identity"])
            )
            artifact_path, artifact_sha = self._publish_manifest(
                directory,
                {
                    "schema": "windows-solver.m03-branch-manifest/1",
                    "disposition": disposition,
                    "branch_identity": params["branch_identity"],
                    "request_identity_sha256": request_sha,
                    "precision_tier": params["precision_tier"],
                    "numerical_policy_identity": params[
                        "numerical_policy_identity"
                    ],
                    "payload_hashes": {},
                },
            )
            return {
                "disposition": disposition,
                "branch_identity": params["branch_identity"],
                "artifact_path": artifact_path,
                "artifact_sha256": artifact_sha,
                "reason": None,
                "rpc_request_identity_sha256": request_sha,
                "rpc_response_identity_sha256": response_sha,
            }
        raise AssertionError(f"unexpected synthetic worker method: {method}")


class M03StaticContractTests(unittest.TestCase):
    def test_core_and_worker_have_disjoint_responsibilities(self) -> None:
        core = CORE.read_text(encoding="utf-8")
        worker = WORKER.read_text(encoding="utf-8")
        core_code = "\n".join(
            line.split("#", 1)[0] for line in core.splitlines()
        )

        self.assertEqual(
            worker.count('include(joinpath(@__DIR__, "m03_core.jl"))'), 1
        )
        self.assertIn(
            'const RPC_SCHEMA = "windows-solver.m03-json-rpc/2"', worker
        )
        self.assertIn(
            'const CORE_SCHEMA = "windows-solver.m03-core/1"', core
        )
        for forbidden in (
            "using JSON",
            "using SHA",
            "stdin",
            "stdout",
            "ARGS",
            "ENV",
        ):
            self.assertNotIn(forbidden, core_code)
        self.assertNotIn("dot(", core_code)
        for scientific_implementation in (
            "solve_Xin",
            "solve_Xup",
            "_angular_matrix_and_derivative",
            "_raw_denominator",
            "_residue_and_projector",
        ):
            self.assertNotIn(scientific_implementation, worker)

    def test_unreviewed_selection_stays_fail_closed(self) -> None:
        selection = json.loads(SELECTION.read_text(encoding="utf-8"))
        validated = validate_m03_selection(selection)
        self.assertIsNone(validated["kernel_numerical_policy"])
        self.assertTrue(production_blockers(validated))

    def test_runtime_receipt_authenticates_core_and_worker_together(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            executable = root / "julia.exe"
            executable.write_text("synthetic julia", encoding="utf-8")
            runtime = root / "m03"
            runtime.mkdir()
            worker_path = runtime / "m03_worker.jl"
            core_path = runtime / "m03_core.jl"
            worker_path.write_bytes(WORKER.read_bytes())
            core_path.write_bytes(CORE.read_bytes())
            project = runtime / "project"
            project.mkdir()
            project_file = project / "Project.toml"
            manifest = project / "Manifest.toml"
            project_file.write_text("[deps]\n", encoding="utf-8")
            manifest.write_text("manifest_format = \"2.0\"\n", encoding="utf-8")
            depot = runtime / "depot"
            depot.mkdir()

            file_sha = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
            dependency_sha = "d" * 64
            contract = {
                "schema": "windows-solver.m03-runtime-contract/2",
                "worker_sha256": file_sha(worker_path),
                "core_sha256": file_sha(core_path),
                "project_sha256": file_sha(project_file),
                "manifest_seed_sha256": "e" * 64,
                "julia_version": "1.10.11",
                "m02_dependency_contract_sha256": dependency_sha,
            }
            contract_sha = hashlib.sha256(
                json.dumps(
                    contract,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=False,
                ).encode("utf-8")
            ).hexdigest()
            m03 = {
                "schema": "windows-solver.m03-runtime-receipt/2",
                "contract": contract,
                "contract_sha256": contract_sha,
                "worker": str(worker_path),
                "worker_sha256": file_sha(worker_path),
                "core": str(core_path),
                "core_sha256": file_sha(core_path),
                "project": str(project),
                "project_sha256": file_sha(project_file),
                "manifest_sha256": file_sha(manifest),
                "depot": str(depot),
                "source_root": str(root / "sources"),
            }
            receipt = {
                "julia_runtime": {
                    "requested": True,
                    "version": "1.10.11",
                    "executable": str(executable),
                    "executable_sha256": file_sha(executable),
                    "arguments": [],
                    "dependency_contract_sha256": dependency_sha,
                    "m03": m03,
                }
            }
            receipt_path = root / "runtime.json"
            receipt_path.write_text(
                json.dumps(receipt, ensure_ascii=False, separators=(",", ":")),
                encoding="utf-8",
            )

            worker = worker_from_runtime_receipt(receipt_path)
            self.assertEqual(worker.launch_count, 0)
            core_path.write_text("tampered", encoding="utf-8")
            with self.assertRaisesRegex(
                M03IdentityRejection, "core_sha256 digest is stale"
            ):
                worker_from_runtime_receipt(receipt_path)


class M03SyntheticCampaignTests(unittest.TestCase):
    def test_restart_promotion_gap_and_branch_reduction_are_ordered(self) -> None:
        handoff = _ready_handoff()
        selection = _frozen_selection()
        plan = build_campaign_plan(handoff, selection)
        first_node = plan["nodes"][0]["node_identity_sha256"]
        worker = _SyntheticWorker(first_node)

        with tempfile.TemporaryDirectory() as directory:
            checkpoint = run_campaign(
                handoff=handoff,
                selection=selection,
                checkpoint_path=Path(directory) / "checkpoint.json",
                worker_factory=lambda: worker,
                source_revision="synthetic-contract-revision",
                new_campaign=True,
            )

        self.assertEqual(checkpoint["state"], "COMPLETE")
        self.assertEqual(checkpoint["nodes"][0]["status"], "UNRESOLVED")
        self.assertEqual(checkpoint["nodes"][1]["status"], "PRODUCED")
        self.assertEqual(worker.restart_count, 1)
        self.assertEqual(
            [request["precision_tier"] for request in worker.solve_requests[:3]],
            ["bigfloat-40", "bigfloat-40", "bigfloat-80"],
        )
        self.assertEqual(
            [
                request["node_identity_sha256"]
                for request in worker.solve_requests[:3]
            ],
            [first_node, first_node, first_node],
        )
        self.assertIsNone(
            worker.solve_requests[3]["predecessor_state_reference"]
        )
        self.assertIsNotNone(
            worker.solve_requests[4]["predecessor_state_reference"]
        )
        branch_sequence = [
            request["branch_identity"] for request in worker.solve_requests
        ]
        self.assertEqual(
            sum(
                left != right
                for left, right in zip(branch_sequence, branch_sequence[1:])
            ),
            10,
        )
        self.assertEqual(len(worker.branch_requests), 11)
        self.assertEqual(
            worker.branch_requests[0]["request_schema"],
            "windows-solver.m03-branch-request/2",
        )
        self.assertEqual(
            len(worker.branch_requests[0]["branch_nodes"]),
            len(plan["branches"][0]["ordered_node_ids"]),
        )
        self.assertEqual(checkpoint["branches"][0]["status"], "UNRESOLVED")


@unittest.skipUnless(
    os.environ.get("M03_REAL_WORKER_PROCESS") == "1",
    "requires the pinned Julia M03 environment",
)
class M03RealWorkerLoadTests(unittest.TestCase):
    def test_hello_probe_and_shutdown_load_the_core_without_numerics(self) -> None:
        julia = shutil.which("julia")
        self.assertIsNotNone(julia)
        project = os.environ["M03_JULIA_PROJECT"]
        with tempfile.TemporaryDirectory() as directory:
            worker = PersistentM03Worker(
                command=(
                    str(julia),
                    "--startup-file=no",
                    "--history-file=no",
                    f"--project={project}",
                    str(WORKER),
                ),
                cwd=directory,
            )
            worker.start()
            probe = worker.call("probe", {})
            self.assertEqual(
                probe["worker_kind"], "m03-julia-protocol-worker"
            )
            self.assertTrue(probe["core_loaded"])
            self.assertEqual(probe["core_version"], "m03-core-v1")
            worker.close()
            self.assertFalse(worker.alive)


if __name__ == "__main__":
    unittest.main()
