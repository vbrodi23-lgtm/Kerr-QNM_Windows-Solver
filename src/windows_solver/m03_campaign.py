"""Python control plane for the 48-node M03 spectral-state campaign."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Callable, Mapping, Sequence

from .contracts import canonical_json_bytes
from .m03_handoff import EXPECTED_BRANCH_COUNT, EXPECTED_NODE_COUNT, validate_handoff
from .m03_policy import (
    kernel_numerical_policy,
    kernel_numerical_policy_sha256,
    production_blockers,
    selection_sha256,
    validate_m03_selection,
)
from .m03_worker import (
    M03IdentityRejection,
    M03PolicyRejection,
    M03WorkerError,
    PersistentM03Worker,
)


CHECKPOINT_SCHEMA = "windows-solver.m03-spectral-state-checkpoint/1"
NODE_TERMINAL_STATES = frozenset({"PRODUCED", "UNRESOLVED"})
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _sha256(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _artifact_directory(output_root: Path, artifact_path: str) -> Path:
    candidate = Path(artifact_path)
    if not candidate.is_absolute():
        candidate = output_root / candidate
    root = output_root.resolve()
    resolved = candidate.resolve()
    if resolved != root and root not in resolved.parents:
        raise ValueError("M03 artifact path escapes the campaign output root")
    return resolved


def _artifact_manifest(
    output_root: Path, artifact_path: str, *, branch: bool = False
) -> Path:
    directory = _artifact_directory(output_root, artifact_path)
    return directory / ("branch-manifest.json" if branch else "node-manifest.json")


def _strict_json(path: Path, subject: str) -> dict[str, object]:
    def pairs(items: list[tuple[str, object]]) -> dict[str, object]:
        output: dict[str, object] = {}
        for key, value in items:
            if key in output:
                raise ValueError(f"{subject} contains duplicate key {key!r}")
            output[key] = value
        return output

    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=pairs,
            parse_constant=lambda item: (_ for _ in ()).throw(
                ValueError(f"{subject} contains non-finite constant {item}")
            ),
        )
    except json.JSONDecodeError as error:
        raise ValueError(f"{subject} is not valid JSON") from error
    if not isinstance(value, dict):
        raise ValueError(f"{subject} must be an object")
    return value


def _atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(canonical_json_bytes(value))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def build_campaign_plan(
    handoff: Mapping[str, object], selection: Mapping[str, object]
) -> dict[str, object]:
    handoff = validate_handoff(handoff)
    selection = validate_m03_selection(selection)
    nodes = []
    previous_by_branch: dict[str, str] = {}
    source_by_id = {
        source["node_identity_sha256"]: source for source in handoff["nodes"]
    }
    ordered_sources = [
        source_by_id[node_identity]
        for branch in handoff["branches"]
        for node_identity in branch["ordered_node_ids"]
    ]
    for source in ordered_sources:
        branch = source["branch_identity"]
        predecessor = previous_by_branch.get(branch)
        initial_precision = (
            selection["precision"]["deep_node"]
            if source["role"] == "deep"
            else selection["precision"]["direct_node"]
        )
        planned = {
            "node_identity_sha256": source["node_identity_sha256"],
            "branch_identity": branch,
            "chain_position": source["chain_position"],
            "role": source["role"],
            "initial_precision_tier": initial_precision,
            "predecessor_node_identity_sha256": predecessor,
            "spectral_seed": source["spectral_seed"],
            "background_identity_sha256": source["background_identity_sha256"],
            "m02_domega_evidence": source["m02_domega_evidence"],
            "m02_lineage_sha256": source["m02_lineage"][
                "reconciled_root_lineage_sha256"
            ],
        }
        planned["plan_record_sha256"] = _sha256(planned)
        nodes.append(planned)
        previous_by_branch[branch] = source["node_identity_sha256"]
    branches = [
        {
            "branch_identity": item["branch_identity"],
            "ordered_node_ids": item["ordered_node_ids"],
            "source_branch_record_sha256": item["branch_record_sha256"],
        }
        for item in handoff["branches"]
    ]
    material = {
        "schema": "windows-solver.m03-campaign-plan/1",
        "handoff_sha256": handoff["handoff_sha256"],
        "selection_sha256": selection_sha256(selection),
        "node_count": len(nodes),
        "branch_count": len(branches),
        "nodes": nodes,
        "branches": branches,
        "schedule": "one-worker-one-active-node-branch-contiguous-v1",
    }
    return {**material, "campaign_plan_sha256": _sha256(material)}


def new_checkpoint(plan: Mapping[str, object], output_root: Path) -> dict[str, object]:
    node_records = []
    for item in plan["nodes"]:
        node_records.append(
            {
                "node_identity_sha256": item["node_identity_sha256"],
                "branch_identity": item["branch_identity"],
                "chain_position": item["chain_position"],
                "role": item["role"],
                "precision_tier": item["initial_precision_tier"],
                "status": "PENDING",
                "attempt_count": 0,
                "artifact_path": None,
                "artifact_sha256": None,
                "julia_receipt_sha256": None,
                "predecessor_node_identity_sha256": item[
                    "predecessor_node_identity_sha256"
                ],
                "promotion_state": "NOT_PROMOTED",
                "reason": None,
                "last_update_utc": None,
            }
        )
    material = {
        "schema": CHECKPOINT_SCHEMA,
        "schema_version": 1,
        "campaign_id": f"m03-campaign-{plan['campaign_plan_sha256']}",
        "campaign_plan_sha256": plan["campaign_plan_sha256"],
        "handoff_sha256": plan["handoff_sha256"],
        "selection_sha256": plan["selection_sha256"],
        "state": "PARTIAL",
        "output_root": str(output_root.resolve()),
        "nodes": node_records,
        "branches": [
            {
                "branch_identity": item["branch_identity"],
                "status": "PENDING",
                "artifact_path": None,
                "artifact_sha256": None,
                "reason": None,
            }
            for item in plan["branches"]
        ],
        "attempts": [],
        "system_failures": [],
        "terminal_reduction": None,
        "admission": None,
        "created_utc": _now(),
        "updated_utc": _now(),
    }
    return {**material, "checkpoint_sha256": _sha256(material)}


def _reseal(checkpoint: dict[str, object]) -> dict[str, object]:
    checkpoint["updated_utc"] = _now()
    material = {key: item for key, item in checkpoint.items() if key != "checkpoint_sha256"}
    checkpoint["checkpoint_sha256"] = _sha256(material)
    return checkpoint


def validate_checkpoint(
    value: Mapping[str, object],
    *,
    plan: Mapping[str, object],
    authenticate_artifacts: bool = True,
) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError("M03 checkpoint must be an object")
    expected = {
        "schema", "schema_version", "campaign_id", "campaign_plan_sha256",
        "handoff_sha256", "selection_sha256", "state", "output_root", "nodes",
        "branches", "attempts", "system_failures", "terminal_reduction", "admission",
        "created_utc", "updated_utc", "checkpoint_sha256",
    }
    if set(value) != expected or value["schema"] != CHECKPOINT_SCHEMA or value["schema_version"] != 1:
        raise ValueError("M03 checkpoint envelope is invalid")
    material = {key: item for key, item in value.items() if key != "checkpoint_sha256"}
    if value["checkpoint_sha256"] != _sha256(material):
        raise ValueError("M03 checkpoint digest is invalid")
    if (
        value["campaign_plan_sha256"] != plan["campaign_plan_sha256"]
        or value["handoff_sha256"] != plan["handoff_sha256"]
        or value["selection_sha256"] != plan["selection_sha256"]
    ):
        raise ValueError("M03 checkpoint belongs to another campaign")
    if value["state"] not in {"PARTIAL", "COMPLETE", "ADMITTED"}:
        raise ValueError("M03 checkpoint state is invalid")
    nodes = value["nodes"]
    branches = value["branches"]
    if not isinstance(nodes, list) or len(nodes) != EXPECTED_NODE_COUNT:
        raise ValueError("M03 checkpoint does not contain 48 nodes")
    if not isinstance(branches, list) or len(branches) != EXPECTED_BRANCH_COUNT:
        raise ValueError("M03 checkpoint does not contain 11 branches")
    if [item.get("node_identity_sha256") for item in nodes] != [
        item["node_identity_sha256"] for item in plan["nodes"]
    ]:
        raise ValueError("M03 checkpoint node order or identity changed")
    output_root = Path(str(value["output_root"]))
    node_fields = {
        "node_identity_sha256",
        "branch_identity",
        "chain_position",
        "role",
        "precision_tier",
        "status",
        "attempt_count",
        "artifact_path",
        "artifact_sha256",
        "julia_receipt_sha256",
        "predecessor_node_identity_sha256",
        "promotion_state",
        "reason",
        "last_update_utc",
    }
    for node, planned in zip(nodes, plan["nodes"], strict=True):
        if not isinstance(node, Mapping) or set(node) != node_fields:
            raise ValueError("M03 checkpoint node fields are invalid")
        if any(
            node[field] != planned[field]
            for field in (
                "node_identity_sha256",
                "branch_identity",
                "chain_position",
                "role",
                "predecessor_node_identity_sha256",
            )
        ):
            raise ValueError("M03 checkpoint node changed its campaign plan binding")
        if (
            node["precision_tier"]
            not in {planned["initial_precision_tier"], "bigfloat-80"}
            or isinstance(node["attempt_count"], bool)
            or not isinstance(node["attempt_count"], int)
            or node["attempt_count"] < 0
            or node["promotion_state"]
            not in {"NOT_PROMOTED", "PROMOTED_BF40_TO_BF80"}
        ):
            raise ValueError("M03 checkpoint node execution state is invalid")
        promoted = node["promotion_state"] == "PROMOTED_BF40_TO_BF80"
        if promoted != (
            planned["initial_precision_tier"] == "bigfloat-40"
            and node["precision_tier"] == "bigfloat-80"
        ):
            raise ValueError("M03 checkpoint promotion state is inconsistent")
        status = node.get("status")
        if status not in {
            "PENDING", "RUNNING", "PROMOTION_PENDING", "PRODUCED", "UNRESOLVED", "SYSTEM_FAILURE"
        }:
            raise ValueError("M03 checkpoint node status is invalid")
        if status in NODE_TERMINAL_STATES:
            artifact_path = node.get("artifact_path")
            artifact_sha = node.get("artifact_sha256")
            receipt_sha = node.get("julia_receipt_sha256")
            if (
                not isinstance(artifact_path, str)
                or not isinstance(artifact_sha, str)
                or _SHA256.fullmatch(artifact_sha) is None
                or not isinstance(receipt_sha, str)
                or _SHA256.fullmatch(receipt_sha) is None
            ):
                raise ValueError("terminal M03 node lacks authenticated artifact identity")
            if authenticate_artifacts:
                manifest = _artifact_manifest(output_root, artifact_path)
                if not manifest.is_file() or _file_sha256(manifest) != artifact_sha:
                    raise ValueError(f"M03 node artifact is missing or corrupt: {artifact_path}")
                manifest_value = _strict_json(
                    manifest, "terminal M03 node manifest"
                )
                if any(
                    manifest_value.get(field) != expected_value
                    for field, expected_value in {
                        "node_identity_sha256": node[
                            "node_identity_sha256"
                        ],
                        "branch_identity": node["branch_identity"],
                        "chain_position": node["chain_position"],
                        "precision_tier": node["precision_tier"],
                        "disposition": status,
                    }.items()
                ):
                    raise ValueError("terminal M03 node manifest is inconsistent")
    branch_fields = {
        "branch_identity",
        "status",
        "artifact_path",
        "artifact_sha256",
        "reason",
    }
    for branch, planned in zip(branches, plan["branches"], strict=True):
        if not isinstance(branch, Mapping) or set(branch) != branch_fields:
            raise ValueError("M03 checkpoint branch fields are invalid")
        if branch["branch_identity"] != planned["branch_identity"]:
            raise ValueError("M03 checkpoint branch order or identity changed")
        status = branch.get("status")
        if status not in {"PENDING", "PRODUCED", "UNRESOLVED", "SYSTEM_FAILURE"}:
            raise ValueError("M03 checkpoint branch status is invalid")
        if status in NODE_TERMINAL_STATES:
            artifact_path = branch.get("artifact_path")
            artifact_sha = branch.get("artifact_sha256")
            if (
                not isinstance(artifact_path, str)
                or not isinstance(artifact_sha, str)
                or _SHA256.fullmatch(artifact_sha) is None
            ):
                raise ValueError("terminal M03 branch lacks authenticated artifact identity")
            if authenticate_artifacts:
                manifest = _artifact_manifest(
                    output_root, artifact_path, branch=True
                )
                if not manifest.is_file() or _file_sha256(manifest) != artifact_sha:
                    raise ValueError(
                        f"M03 branch artifact is missing or corrupt: {artifact_path}"
                    )
                manifest_value = _strict_json(
                    manifest, "terminal M03 branch manifest"
                )
                if (
                    manifest_value.get("branch_identity")
                    != branch["branch_identity"]
                    or manifest_value.get("disposition") != status
                ):
                    raise ValueError(
                        "terminal M03 branch manifest is inconsistent"
                    )
    return json.loads(canonical_json_bytes(value))


def load_or_create_checkpoint(
    *,
    path: Path,
    plan: Mapping[str, object],
    new_campaign: bool,
) -> dict[str, object]:
    if path.exists():
        if new_campaign:
            raise ValueError(f"-NewCampaign refuses an existing checkpoint: {path}")
        return validate_checkpoint(_strict_json(path, "M03 checkpoint"), plan=plan)
    checkpoint = new_checkpoint(plan, path.parent)
    _atomic_json(path, checkpoint)
    return checkpoint


def _status_projection(checkpoint: Mapping[str, object]) -> dict[str, object]:
    counts: dict[str, int] = {}
    for node in checkpoint["nodes"]:
        counts[node["status"]] = counts.get(node["status"], 0) + 1
    return {
        "schema": "windows-solver.m03-status/1",
        "campaign_id": checkpoint["campaign_id"],
        "state": checkpoint["state"],
        "node_counts": counts,
        "terminal_node_count": sum(counts.get(item, 0) for item in NODE_TERMINAL_STATES),
        "branch_terminal_count": sum(
            item["status"] in {"PRODUCED", "UNRESOLVED"}
            for item in checkpoint["branches"]
        ),
        "updated_utc": checkpoint["updated_utc"],
    }


def write_checkpoint(path: Path, checkpoint: dict[str, object]) -> None:
    _atomic_json(path, _reseal(checkpoint))
    _atomic_json(Path(str(path) + ".status.json"), _status_projection(checkpoint))


def _predecessor_artifact(
    checkpoint: Mapping[str, object], node: Mapping[str, object]
) -> dict[str, object] | None:
    predecessor = node["predecessor_node_identity_sha256"]
    if predecessor is None:
        return None
    match = next(
        item for item in checkpoint["nodes"] if item["node_identity_sha256"] == predecessor
    )
    if match["status"] != "PRODUCED":
        return None
    artifact_path = match["artifact_path"]
    if not isinstance(artifact_path, str):
        raise ValueError("produced predecessor lacks an artifact path")
    output_root = Path(str(checkpoint["output_root"]))
    manifest_path = _artifact_manifest(output_root, artifact_path)
    manifest = _strict_json(manifest_path, "M03 predecessor manifest")
    if (
        manifest.get("node_identity_sha256") != predecessor
        or manifest.get("disposition") != "PRODUCED"
        or _file_sha256(manifest_path) != match["artifact_sha256"]
    ):
        raise ValueError("produced predecessor manifest is stale")
    return {
        "artifact_path": str(manifest_path.parent),
        "node_identity_sha256": predecessor,
        "root_identity_sha256": manifest["root_identity_sha256"],
        "branch_identity": manifest["branch_identity"],
        "chain_position": manifest["chain_position"],
        "manifest_sha256": match["artifact_sha256"],
    }


def _request_for_node(
    *,
    node_plan: Mapping[str, object],
    node_record: Mapping[str, object],
    plan: Mapping[str, object],
    selection: Mapping[str, object],
    checkpoint: Mapping[str, object],
    source_revision: str,
) -> dict[str, object]:
    seed = node_plan["spectral_seed"]
    frozen = seed["frozen_eigenvalue"]
    root_authority = seed["root_authority"]
    background_identity = node_plan.get("background_identity_sha256")
    domega = node_plan.get("m02_domega_evidence")
    if (
        not isinstance(background_identity, str)
        or _SHA256.fullmatch(background_identity) is None
        or not isinstance(domega, Mapping)
        or domega.get("schema") != "windows-solver.m02-domega-stencil/1"
    ):
        raise ValueError(
            "M03 node lacks authenticated M02 exterior Domega/background evidence"
        )
    numerical_policy = kernel_numerical_policy(selection)
    return {
        "request_schema": "windows-solver.m03-node-request/2",
        "node_identity_sha256": node_plan["node_identity_sha256"],
        "mode": seed["mode"],
        "spin_identity": seed["coordinate"],
        "frozen_omega": frozen["omega"],
        "frozen_A": frozen["angular_separation_constant_A"],
        "upstream_root_identity": root_authority["root_identity_sha256"],
        "background_identity_sha256": background_identity,
        "m02_handoff_sha256": plan["handoff_sha256"],
        "branch_identity": node_plan["branch_identity"],
        "chain_position": node_plan["chain_position"],
        "predecessor_state_reference": _predecessor_artifact(checkpoint, node_plan),
        "precision_tier": node_record["precision_tier"],
        "m02_domega_evidence": dict(domega),
        "numerical_policy_identity": kernel_numerical_policy_sha256(selection),
        "numerical_policy": numerical_policy,
        "output_root": str(Path(str(checkpoint["output_root"])).resolve()),
        "source_revision": source_revision,
        "root_movement_permitted": False,
        "base_angular_eigenvalue_solve_permitted": False,
    }


def _verified_worker_artifact(
    *,
    output_root: Path,
    result: Mapping[str, object],
    expected_request_sha256: str,
    expected_disposition: str,
    expected_identity: str,
    expected_manifest_fields: Mapping[str, object],
    branch: bool = False,
) -> tuple[str, str]:
    artifact_path = result.get("artifact_path")
    artifact_sha = result.get("artifact_sha256")
    if (
        not isinstance(artifact_path, str)
        or not isinstance(artifact_sha, str)
        or _SHA256.fullmatch(artifact_sha) is None
    ):
        raise M03WorkerError("Julia result lacks artifact authentication")
    directory = _artifact_directory(output_root, artifact_path)
    manifest = directory / (
        "branch-manifest.json" if branch else "node-manifest.json"
    )
    if not manifest.is_file() or _file_sha256(manifest) != artifact_sha:
        raise M03WorkerError("Julia artifact was not atomically published")
    manifest_value = _strict_json(manifest, "M03 Julia artifact manifest")
    identity_field = "branch_identity" if branch else "node_identity_sha256"
    expected_schema = (
        "windows-solver.m03-branch-manifest/1"
        if branch
        else "windows-solver.m03-node-manifest/1"
    )
    if (
        manifest_value.get("schema") != expected_schema
        or manifest_value.get("request_identity_sha256")
        != expected_request_sha256
        or manifest_value.get("disposition") != expected_disposition
        or manifest_value.get(identity_field) != expected_identity
        or any(
            manifest_value.get(field) != expected
            for field, expected in expected_manifest_fields.items()
        )
    ):
        raise M03IdentityRejection(
            "Julia artifact manifest changed its authenticated request identity"
        )
    return str(directory.relative_to(output_root.resolve())), artifact_sha


def run_campaign(
    *,
    handoff: Mapping[str, object],
    selection: Mapping[str, object],
    checkpoint_path: Path,
    worker_factory: Callable[[], PersistentM03Worker],
    source_revision: str,
    new_campaign: bool = False,
) -> dict[str, object]:
    handoff = validate_handoff(handoff)
    selection = validate_m03_selection(selection)
    blockers = production_blockers(selection)
    if blockers:
        raise ValueError("M03 production is BLOCKED: " + "; ".join(blockers))
    inventory = handoff["inventory"]
    if (
        inventory["authenticated_domega_count"] != EXPECTED_NODE_COUNT
        or inventory["authenticated_background_count"] != EXPECTED_NODE_COUNT
    ):
        raise ValueError(
            "M03 production is BLOCKED: every node requires an authenticated "
            "M02 exterior Domega stencil and canonical background"
        )
    plan = build_campaign_plan(handoff, selection)
    checkpoint = load_or_create_checkpoint(
        path=checkpoint_path, plan=plan, new_campaign=new_campaign
    )
    node_plan_by_id = {item["node_identity_sha256"]: item for item in plan["nodes"]}
    restart_limit = int(selection["process_policy"]["restart_limit_per_node"])
    worker = worker_factory()
    try:
        worker.start()
        for node in checkpoint["nodes"]:
            if node["status"] in NODE_TERMINAL_STATES:
                continue
            planned = node_plan_by_id[node["node_identity_sha256"]]
            _solve_campaign_node(
                worker=worker,
                node=node,
                planned=planned,
                checkpoint=checkpoint,
                checkpoint_path=checkpoint_path,
                plan=plan,
                selection=selection,
                source_revision=source_revision,
                restart_limit=restart_limit,
            )
        _reduce_branches(worker, checkpoint, plan, selection, checkpoint_path)
        checkpoint["state"] = "COMPLETE"
        write_checkpoint(checkpoint_path, checkpoint)
    finally:
        worker.close()
    return checkpoint


def _solve_campaign_node(
    *,
    worker: PersistentM03Worker,
    node: dict[str, object],
    planned: Mapping[str, object],
    checkpoint: dict[str, object],
    checkpoint_path: Path,
    plan: Mapping[str, object],
    selection: Mapping[str, object],
    source_revision: str,
    restart_limit: int,
) -> None:
    system_failure_count = sum(
        failure.get("node_identity_sha256") == node["node_identity_sha256"]
        for failure in checkpoint["system_failures"]
    )
    if system_failure_count > restart_limit:
        raise M03WorkerError("M03 node restart budget was already exhausted")
    while node["status"] not in NODE_TERMINAL_STATES:
        node["status"] = "RUNNING"
        node["attempt_count"] += 1
        node["last_update_utc"] = _now()
        write_checkpoint(checkpoint_path, checkpoint)
        request = _request_for_node(
            node_plan=planned,
            node_record=node,
            plan=plan,
            selection=selection,
            checkpoint=checkpoint,
            source_revision=source_revision,
        )
        attempt = {
            "node_identity_sha256": node["node_identity_sha256"],
            "attempt": node["attempt_count"],
            "precision_tier": node["precision_tier"],
            "request_sha256": _sha256(request),
            "started_utc": _now(),
        }
        try:
            result = worker.call("solve_node", request)
        except (M03IdentityRejection, M03PolicyRejection):
            raise
        except M03WorkerError as error:
            failure = {
                **attempt,
                "class": "SYSTEM_FAILURE",
                "message": str(error),
                "created_utc": _now(),
            }
            failure["failure_receipt_sha256"] = _sha256(failure)
            checkpoint["system_failures"].append(failure)
            system_failure_count += 1
            node["status"] = "SYSTEM_FAILURE"
            node["reason"] = str(error)
            write_checkpoint(checkpoint_path, checkpoint)
            if system_failure_count > restart_limit:
                raise
            worker.restart()
            node["status"] = "PENDING"
            write_checkpoint(checkpoint_path, checkpoint)
            continue
        if result.get("node_identity_sha256") != node["node_identity_sha256"]:
            raise M03IdentityRejection(
                "Julia terminal receipt changed the node identity"
            )
        if (
            result.get("spin_identity") != request["spin_identity"]
            or result.get("frozen_omega") != request["frozen_omega"]
            or result.get("frozen_A") != request["frozen_A"]
            or result.get("root_identity_sha256")
            != request["upstream_root_identity"]
            or result.get("handoff_identity_sha256")
            != request["m02_handoff_sha256"]
            or result.get("numerical_policy_identity")
            != request["numerical_policy_identity"]
        ):
            raise M03IdentityRejection(
                "Julia terminal receipt changed an authoritative M03 identity"
            )
        disposition = result.get("disposition")
        if disposition == "REUSED":
            disposition = result.get("original_disposition")
            if disposition not in {
                "PRODUCED",
                "PROMOTION_REQUIRED",
                "UNRESOLVED",
            }:
                raise M03WorkerError(
                    "Julia reuse receipt has no original scientific disposition"
                )
        rpc_request_sha = result.get("rpc_request_identity_sha256")
        receipt_sha = result.get("rpc_response_identity_sha256")
        if (
            not isinstance(rpc_request_sha, str)
            or _SHA256.fullmatch(rpc_request_sha) is None
            or not isinstance(receipt_sha, str)
            or _SHA256.fullmatch(receipt_sha) is None
        ):
            raise M03WorkerError(
                "Julia node result lacks authenticated RPC identities"
            )
        output_root = Path(str(checkpoint["output_root"]))
        relative_path, artifact_sha = _verified_worker_artifact(
            output_root=output_root,
            result=result,
            expected_request_sha256=rpc_request_sha,
            expected_disposition=disposition,
            expected_identity=str(node["node_identity_sha256"]),
            expected_manifest_fields={
                "root_identity_sha256": request["upstream_root_identity"],
                "branch_identity": request["branch_identity"],
                "chain_position": request["chain_position"],
                "precision_tier": request["precision_tier"],
                "handoff_identity_sha256": request["m02_handoff_sha256"],
                "numerical_policy_identity": request[
                    "numerical_policy_identity"
                ],
            },
        )
        if (
            disposition == "PROMOTION_REQUIRED"
            and node["precision_tier"] == "bigfloat-40"
        ):
            node["precision_tier"] = "bigfloat-80"
            node["promotion_state"] = "PROMOTED_BF40_TO_BF80"
            node["status"] = "PENDING"
            node["reason"] = str(result.get("reason"))
            checkpoint["attempts"].append(
                {
                    **attempt,
                    "result": disposition,
                    "artifact_path": relative_path,
                    "artifact_sha256": artifact_sha,
                    "julia_receipt_sha256": receipt_sha,
                    "finished_utc": _now(),
                }
            )
            write_checkpoint(checkpoint_path, checkpoint)
            continue
        if disposition == "PROMOTION_REQUIRED":
            raise M03PolicyRejection(
                "Julia requested promotion after the BF80 production ceiling"
            )
        if disposition not in NODE_TERMINAL_STATES:
            raise M03WorkerError(
                "Julia node result has no terminal scientific disposition"
            )
        node.update(
            {
                "status": disposition,
                "artifact_path": relative_path,
                "artifact_sha256": artifact_sha,
                "julia_receipt_sha256": receipt_sha,
                "reason": result.get("reason"),
                "last_update_utc": _now(),
            }
        )
        checkpoint["attempts"].append(
            {
                **attempt,
                "result": disposition,
                "artifact_path": relative_path,
                "artifact_sha256": artifact_sha,
                "julia_receipt_sha256": receipt_sha,
                "finished_utc": _now(),
            }
        )
        write_checkpoint(checkpoint_path, checkpoint)


def _reduce_branches(
    worker: PersistentM03Worker,
    checkpoint: dict[str, object],
    plan: Mapping[str, object],
    selection: Mapping[str, object],
    checkpoint_path: Path,
) -> None:
    nodes = {item["node_identity_sha256"]: item for item in checkpoint["nodes"]}
    output_root = Path(str(checkpoint["output_root"])).resolve()
    numerical_policy = kernel_numerical_policy(selection)
    numerical_policy_identity = kernel_numerical_policy_sha256(selection)

    for branch_record, branch_plan in zip(
        checkpoint["branches"], plan["branches"], strict=True
    ):
        if branch_record["status"] in NODE_TERMINAL_STATES:
            continue
        ordered = [nodes[item] for item in branch_plan["ordered_node_ids"]]
        references = []
        for node in ordered:
            if node["status"] not in NODE_TERMINAL_STATES:
                raise ValueError("M03 branch reduction requires terminal node artifacts")
            artifact_path = node.get("artifact_path")
            if not isinstance(artifact_path, str):
                raise ValueError("terminal M03 node lacks an artifact path")
            manifest_path = _artifact_manifest(output_root, artifact_path)
            manifest = _strict_json(manifest_path, "M03 branch-node manifest")
            artifact_sha = node.get("artifact_sha256")
            if (
                manifest.get("node_identity_sha256")
                != node["node_identity_sha256"]
                or manifest.get("branch_identity")
                != branch_plan["branch_identity"]
                or manifest.get("chain_position") != node["chain_position"]
                or manifest.get("precision_tier") != node["precision_tier"]
                or manifest.get("disposition") != node["status"]
                or not isinstance(artifact_sha, str)
                or _file_sha256(manifest_path) != artifact_sha
            ):
                raise ValueError("M03 branch-node manifest is stale or inconsistent")
            references.append(
                {
                    "artifact_path": str(manifest_path.parent),
                    "node_identity_sha256": node["node_identity_sha256"],
                    "root_identity_sha256": manifest["root_identity_sha256"],
                    "branch_identity": node["branch_identity"],
                    "chain_position": node["chain_position"],
                    "precision_tier": node["precision_tier"],
                    "manifest_sha256": artifact_sha,
                }
            )

        precision_tier = (
            "bigfloat-80"
            if any(node["precision_tier"] == "bigfloat-80" for node in ordered)
            else "bigfloat-40"
        )
        request = {
            "request_schema": "windows-solver.m03-branch-request/2",
            "branch_identity": branch_plan["branch_identity"],
            "branch_nodes": references,
            "precision_tier": precision_tier,
            "numerical_policy": numerical_policy,
            "numerical_policy_identity": numerical_policy_identity,
            "output_root": str(output_root),
            "declared_unresolved_gaps": [],
        }
        try:
            result = worker.call("reduce_branch", request)
        except (M03IdentityRejection, M03PolicyRejection):
            raise
        except M03WorkerError as error:
            branch_record.update(
                {
                    "status": "SYSTEM_FAILURE",
                    "artifact_path": None,
                    "artifact_sha256": None,
                    "reason": str(error),
                }
            )
            write_checkpoint(checkpoint_path, checkpoint)
            raise
        if result.get("branch_identity") != branch_plan["branch_identity"]:
            raise M03IdentityRejection("Julia branch receipt changed branch identity")
        disposition = result.get("disposition")
        if disposition not in NODE_TERMINAL_STATES:
            raise M03WorkerError("Julia branch result is not terminal")
        receipt_sha = result.get("rpc_response_identity_sha256")
        request_sha = result.get("rpc_request_identity_sha256")
        if (
            not isinstance(request_sha, str)
            or _SHA256.fullmatch(request_sha) is None
            or not isinstance(receipt_sha, str)
            or _SHA256.fullmatch(receipt_sha) is None
        ):
            raise M03WorkerError(
                "Julia branch result lacks authenticated RPC identities"
            )
        relative, digest = _verified_worker_artifact(
            output_root=output_root,
            result=result,
            expected_request_sha256=request_sha,
            expected_disposition=disposition,
            expected_identity=str(branch_plan["branch_identity"]),
            expected_manifest_fields={
                "precision_tier": precision_tier,
                "numerical_policy_identity": numerical_policy_identity,
            },
            branch=True,
        )
        branch_record.update(
            {
                "status": disposition,
                "artifact_path": relative,
                "artifact_sha256": digest,
                "reason": result.get("reason"),
            }
        )
        write_checkpoint(checkpoint_path, checkpoint)


def terminal_reduce(
    *, checkpoint: Mapping[str, object], plan: Mapping[str, object]
) -> dict[str, object]:
    value = validate_checkpoint(checkpoint, plan=plan, authenticate_artifacts=True)
    if any(item["status"] not in NODE_TERMINAL_STATES for item in value["nodes"]):
        raise ValueError("M03 terminal reduction requires all 48 nodes terminal")
    if any(item["status"] not in NODE_TERMINAL_STATES for item in value["branches"]):
        raise ValueError("M03 terminal reduction requires all 11 branches terminal")
    reduction = {
        "schema": "windows-solver.m03-terminal-reduction/1",
        "campaign_id": value["campaign_id"],
        "node_count": EXPECTED_NODE_COUNT,
        "branch_count": EXPECTED_BRANCH_COUNT,
        "node_artifact_sha256": [item["artifact_sha256"] for item in value["nodes"]],
        "branch_artifact_sha256": [item["artifact_sha256"] for item in value["branches"]],
        "precision_distribution": {
            tier: sum(item["precision_tier"] == tier for item in value["nodes"])
            for tier in ("bigfloat-40", "bigfloat-80")
        },
        "unresolved_node_ids": [
            item["node_identity_sha256"] for item in value["nodes"] if item["status"] == "UNRESOLVED"
        ],
        "root_solves": 0,
        "angular_solves": 0,
        "radial_solves": 0,
        "co_mode_solves": 0,
        "julia_launches": 0,
    }
    return {**reduction, "terminal_reduction_sha256": _sha256(reduction)}


def admit_checkpoint(
    *, checkpoint: dict[str, object], plan: Mapping[str, object], checkpoint_path: Path
) -> dict[str, object]:
    reduction = terminal_reduce(checkpoint=checkpoint, plan=plan)
    admission = {
        "schema": "windows-solver.m03-provider-admission/1",
        "campaign_id": checkpoint["campaign_id"],
        "terminal_reduction_sha256": reduction["terminal_reduction_sha256"],
        "state": "ADMITTED",
        "admitted_utc": _now(),
    }
    admission["admission_sha256"] = _sha256(admission)
    checkpoint["terminal_reduction"] = reduction
    checkpoint["admission"] = admission
    checkpoint["state"] = "ADMITTED"
    write_checkpoint(checkpoint_path, checkpoint)
    return admission


__all__ = [
    "CHECKPOINT_SCHEMA",
    "NODE_TERMINAL_STATES",
    "admit_checkpoint",
    "build_campaign_plan",
    "load_or_create_checkpoint",
    "new_checkpoint",
    "run_campaign",
    "terminal_reduce",
    "validate_checkpoint",
    "write_checkpoint",
]
