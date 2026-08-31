"""Authenticated, zero-work M02 to M03 handoff construction.

The builder reduces terminal M02 evidence to one record per authenticated Kerr
root.  It never invokes a numerical backend and never copies mechanism response
values into the M03 spectral-state seed.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import tempfile
from typing import Mapping, Sequence

from .campaign_policy import (
    PromotionQueueDisposition,
    TERMINAL_PROMOTION_DISPOSITIONS,
    validate_schema11_checkpoint,
)
from .contracts import canonical_json_bytes
from .response_batches import (
    CampaignPlan,
    CampaignSelection,
    scientific_computation_identity_sha256,
)


HANDOFF_SCHEMA = "windows-solver.m02-m03-handoff/1"
HANDOFF_SCHEMA_VERSION = 1
EXPECTED_LEAF_COUNT = 212
EXPECTED_NODE_COUNT = 48
EXPECTED_BRANCH_COUNT = 11
EXPECTED_ROLE_COUNTS = {"primary": 28, "control": 8, "deep": 12}
EXPECTED_BRANCH_POPULATIONS = {
    "2,2,0": 7,
    "2,2,1": 7,
    "2,2,2": 7,
    "3,3,0": 4,
    "3,3,1": 4,
    "4,4,0": 4,
    "4,4,1": 4,
    "2,1,0": 5,
    "2,-2,0": 2,
    "3,2,0": 2,
    "3,-3,0": 2,
}
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_TERMINAL_RECORD_STATES = frozenset({"PRODUCED", "UNRESOLVED"})
_FORBIDDEN_SEED_TERMS = frozenset(
    {
        "response",
        "delta_omega",
        "mechanism_id",
        "support_centre",
        "support_width",
        "exterior_family_id",
        "sensitivity",
        "projective_row",
    }
)


def _sha256(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _strict_json(path: Path, subject: str) -> dict[str, object]:
    def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"{subject} contains duplicate key {key!r}")
            result[key] = value
        return result

    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=reject_duplicates,
            parse_constant=lambda item: (_ for _ in ()).throw(
                ValueError(f"{subject} contains non-finite constant {item}")
            ),
        )
    except json.JSONDecodeError as error:
        raise ValueError(f"{subject} is not valid JSON") from error
    if not isinstance(value, dict):
        raise ValueError(f"{subject} must be a JSON object")
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


def _text(value: float) -> str:
    if not math.isfinite(value):
        raise ValueError("M03 identity number is non-finite")
    return format(value, ".17g")


def _mode_key(mode: Mapping[str, object]) -> str:
    return f"{mode['ell']},{mode['m']},{mode['n']}"


def _branch_material(mode: Mapping[str, object]) -> dict[str, object]:
    return {
        "s": mode["s"],
        "ell": mode["ell"],
        "m": mode["m"],
        "n": mode["n"],
        "branch": mode["branch"],
        "polarization": mode["polarization"],
    }


def _nested_values(value: object, key: str) -> tuple[object, ...]:
    found: list[object] = []
    if isinstance(value, Mapping):
        for candidate, child in value.items():
            if candidate == key:
                found.append(child)
            found.extend(_nested_values(child, key))
    elif isinstance(value, list):
        for child in value:
            found.extend(_nested_values(child, key))
    return tuple(found)


def _assert_record_root_agreement(
    record: Mapping[str, object], *, root_identity: str, root_reference: str
) -> None:
    for supplied in _nested_values(record, "root_identity_sha256"):
        if supplied != root_identity:
            raise ValueError(
                "contributing M02 leaves disagree about their common root identity"
            )
    for supplied in _nested_values(record, "root_reference_id"):
        if supplied != root_reference:
            raise ValueError(
                "contributing M02 leaves disagree about their common root reference"
            )


def _validate_terminal_m02(
    plan: CampaignPlan,
    selection: CampaignSelection,
    checkpoint: Mapping[str, object],
) -> dict[str, object]:
    value = validate_schema11_checkpoint(checkpoint)
    if len(plan.leaves) != EXPECTED_LEAF_COUNT:
        raise ValueError("M02 plan does not contain the frozen 212-leaf domain")
    if selection.role != "all" or tuple(selection.leaf_ids) != tuple(
        leaf.leaf_id for leaf in plan.leaves
    ):
        raise ValueError("M02 to M03 handoff requires the full ordered M02 selection")
    if value["campaign_id"] != plan.campaign_id:
        raise ValueError("M02 checkpoint campaign identity is stale")
    if value["selection_id"] != selection.selection_id:
        raise ValueError("M02 checkpoint selection identity is stale")
    if value["state"] != "COMPLETE":
        raise ValueError("M02 terminal checkpoint is not COMPLETE")
    records = value["records"]
    assert isinstance(records, list)
    record_by_leaf = {str(item["leaf_id"]): item for item in records}
    if set(record_by_leaf) != set(selection.leaf_ids):
        missing = sorted(set(selection.leaf_ids) - set(record_by_leaf))
        extra = sorted(set(record_by_leaf) - set(selection.leaf_ids))
        raise ValueError(
            "M02 terminal checkpoint does not account for exactly 212 leaves "
            f"(missing={len(missing)}, extra={len(extra)})"
        )
    if any(
        record_by_leaf[leaf_id].get("state") not in _TERMINAL_RECORD_STATES
        for leaf_id in selection.leaf_ids
    ):
        raise ValueError("M02 checkpoint contains a non-handoff terminal leaf state")
    binary64 = value["survey_pass_ledger"]["binary64"]
    if set(binary64) != set(selection.leaf_ids):
        raise ValueError("M02 binary64 pass does not account for all 212 leaves")
    queue = value["promotion_queue"]["entries"]
    if any(
        entry["disposition"] not in TERMINAL_PROMOTION_DISPOSITIONS
        for entry in queue
    ):
        raise ValueError("M02 promotion admission/reduction is not terminal")
    return value


def _leaf_receipt(
    plan: CampaignPlan,
    leaf: object,
    checkpoint: Mapping[str, object],
    record: Mapping[str, object],
) -> dict[str, object]:
    leaf_id = leaf.leaf_id
    binary64 = checkpoint["survey_pass_ledger"]["binary64"][leaf_id]
    promoted = checkpoint["survey_pass_ledger"]["promoted"].get(leaf_id)
    queue_entries = [
        entry
        for entry in checkpoint["promotion_queue"]["entries"]
        if entry["leaf_id"] == leaf_id
    ]
    material = {
        "schema": "windows-solver.m02-root-lineage-leaf/1",
        "leaf_id": leaf_id,
        "terminal_state": record["state"],
        "canonical_leaf_record_sha256": record["record_sha256"],
        "scientific_computation_identity_sha256": (
            scientific_computation_identity_sha256(plan, leaf)
        ),
        "binary64_disposition_receipt_sha256": binary64[
            "disposition_receipt_sha256"
        ],
        "promoted_disposition_receipt_sha256": (
            None
            if promoted is None
            else promoted["disposition_receipt_sha256"]
        ),
        "promotion_terminal_receipt_sha256": (
            None
            if not queue_entries
            else queue_entries[-1]["disposition_receipt_sha256"]
        ),
        "precision_evidence": [
            stage.get("precision_tier", stage.get("digits"))
            for stage in record.get("stages", [])
            if isinstance(stage, Mapping)
        ],
    }
    return {**material, "leaf_receipt_sha256": _sha256(material)}


def _coordinate(leaf: object, owner_record: Mapping[str, object]) -> dict[str, object]:
    spin = float(leaf.job.spin)
    coordinate: dict[str, object] = {
        "physical_spin_text": _text(spin),
        "spin_binary64_hex": leaf.job.root.spin_binary64_hex,
        "spin_binary64_ratio": {
            "numerator": spin.as_integer_ratio()[0],
            "denominator": spin.as_integer_ratio()[1],
        },
        "sampling_coordinate": {
            "coordinate_id": (
                "a-over-M" if leaf.leaf.spin_role == "direct" else "M-kappa"
            ),
            "exact": {
                "numerator": leaf.leaf.coordinate.numerator,
                "denominator": leaf.leaf.coordinate.denominator,
            },
            "canonical_text": (
                f"{leaf.leaf.coordinate.numerator}/"
                f"{leaf.leaf.coordinate.denominator}"
            ),
            "transformation_id": (
                "identity-a-over-M"
                if leaf.leaf.spin_role == "direct"
                else "kerr-prograde-spin-from-M-kappa-v1"
            ),
        },
    }
    if "spin_exact" in owner_record:
        coordinate["source_realization"] = "base-catalogue"
        coordinate["source_spin_exact"] = owner_record["spin_exact"]
    else:
        coordinate["source_realization"] = "exact-selector-overlay"
        coordinate["source_coordinate"] = owner_record["source_coordinate"]
    return coordinate


def _seed(leaf: object) -> dict[str, object]:
    job = leaf.job
    root = job.root
    owner = root.owner_record
    mode = job.mode.to_mapping()
    seed = {
        "schema": "windows-solver.m03-spectral-state-seed/1",
        "mode": mode,
        "coordinate": _coordinate(leaf, owner),
        "frozen_eigenvalue": {
            "omega": {
                "real": _text(root.omega.real),
                "imaginary": _text(root.omega.imag),
                "units": "Momega",
            },
            "angular_separation_constant_A": {
                "real": _text(root.angular_separation_constant.real),
                "imaginary": _text(root.angular_separation_constant.imag),
            },
            "time_dependence": "exp(-i omega t)",
            "boundary_conditions": {
                "horizon": "ingoing",
                "infinity": "outgoing",
            },
            "root_movement_permitted": False,
        },
        "root_authority": {
            "root_reference_id": root.root_reference_id,
            "root_identity_sha256": root.identity_sha256,
            "selector_id": root.selector_id,
            "source_realization": root.owner_id,
            "catalogue_id": root.owner_id,
            "catalogue_sha256": root.owner_data_sha256,
            "source_record_sha256": _sha256(owner),
        },
    }
    forbidden = _FORBIDDEN_SEED_TERMS.intersection(seed)
    if forbidden:
        raise RuntimeError(f"mechanism response contaminated M03 seed: {forbidden}")
    return seed


def build_handoff(
    *,
    plan: CampaignPlan,
    selection: CampaignSelection,
    checkpoint: Mapping[str, object],
    checkpoint_path: str,
    created_utc: str | None = None,
) -> dict[str, object]:
    """Build the exact 48-root handoff without launching a scientific engine."""

    terminal = _validate_terminal_m02(plan, selection, checkpoint)
    checkpoint_sha = _sha256(terminal)
    records = {str(item["leaf_id"]): item for item in terminal["records"]}
    grouped: dict[str, list[object]] = defaultdict(list)
    ordered_roots: list[str] = []
    for leaf in plan.leaves:
        identity = leaf.job.root.identity_sha256
        if identity not in grouped:
            ordered_roots.append(identity)
        grouped[identity].append(leaf)
    if len(grouped) != EXPECTED_NODE_COUNT:
        raise ValueError(
            f"M02 handoff contains {len(grouped)} unique roots; expected 48"
        )

    branch_nodes: dict[str, list[dict[str, object]]] = defaultdict(list)
    nodes: list[dict[str, object]] = []
    for root_identity in ordered_roots:
        leaves = grouped[root_identity]
        first = leaves[0]
        common_root = first.job.root.to_mapping()
        common_role = first.role
        for leaf in leaves:
            if leaf.job.root.to_mapping() != common_root or leaf.role != common_role:
                raise ValueError(
                    "contributing M02 leaves disagree about their common root"
                )
            _assert_record_root_agreement(
                records[leaf.leaf_id],
                root_identity=root_identity,
                root_reference=first.job.root.root_reference_id,
            )
        receipts = [
            _leaf_receipt(plan, leaf, terminal, records[leaf.leaf_id])
            for leaf in leaves
        ]
        lineage_material = {
            "schema": "windows-solver.m02-reconciled-root-lineage/1",
            "root_identity_sha256": root_identity,
            "root_reference_id": first.job.root.root_reference_id,
            "m02_terminal_checkpoint_sha256": checkpoint_sha,
            "contributing_leaf_receipts": receipts,
            "equation_identities": sorted(
                {
                    str(value)
                    for leaf in leaves
                    for value in _nested_values(records[leaf.leaf_id], "equation_id")
                }
            ),
            "backend_identities": sorted(
                {
                    str(value)
                    for leaf in leaves
                    for value in _nested_values(
                        records[leaf.leaf_id], "backend_identity_sha256"
                    )
                }
            ),
            "policy_identities": sorted(
                {
                    str(value)
                    for leaf in leaves
                    for value in _nested_values(records[leaf.leaf_id], "policy_sha256")
                }
            ),
        }
        lineage = {
            **lineage_material,
            "reconciled_root_lineage_sha256": _sha256(lineage_material),
        }
        seed = _seed(first)
        mode = seed["mode"]
        assert isinstance(mode, Mapping)
        branch_material = _branch_material(mode)
        branch_identity = f"m03-branch-{_sha256(branch_material)}"
        chain_position = len(branch_nodes[branch_identity])
        identity_material = {
            "schema": "windows-solver.m03-node-identity/1",
            "spectral_seed_sha256": _sha256(seed),
            "reconciled_root_lineage_sha256": lineage[
                "reconciled_root_lineage_sha256"
            ],
            "branch_identity": branch_identity,
            "chain_position": chain_position,
        }
        node = {
            "node_identity_sha256": _sha256(identity_material),
            "role": common_role,
            "branch_identity": branch_identity,
            "chain_position": chain_position,
            "spectral_seed": seed,
            "m02_lineage": lineage,
            "optional_derivative_evidence": {
                "status": "UNREVIEWED_FOR_M03_REUSE",
                "references": [],
            },
        }
        branch_nodes[branch_identity].append(node)
        nodes.append(node)

    roles = Counter(str(node["role"]) for node in nodes)
    populations = Counter(
        _mode_key(node["spectral_seed"]["mode"]) for node in nodes
    )
    if dict(roles) != EXPECTED_ROLE_COUNTS:
        raise ValueError(f"M03 role inventory mismatch: {dict(roles)}")
    if dict(populations) != EXPECTED_BRANCH_POPULATIONS:
        raise ValueError(f"M03 branch population mismatch: {dict(populations)}")
    if len(branch_nodes) != EXPECTED_BRANCH_COUNT:
        raise ValueError(
            f"M02 handoff contains {len(branch_nodes)} branches; expected 11"
        )
    branches = []
    for branch_identity, members in branch_nodes.items():
        branch = {
            "branch_identity": branch_identity,
            "mode": members[0]["spectral_seed"]["mode"],
            "ordered_node_ids": [item["node_identity_sha256"] for item in members],
            "node_count": len(members),
            "continuation_order_authority": "m02-root-selector-order",
        }
        branch["branch_record_sha256"] = _sha256(branch)
        branches.append(branch)
    reduction = {
        "schema": "windows-solver.m02-m03-terminal-reduction/1",
        "m02_terminal_checkpoint_sha256": checkpoint_sha,
        "m02_campaign_id": plan.campaign_id,
        "m02_selection_id": selection.selection_id,
        "ordered_leaf_set_sha256": plan.ordered_leaf_set_sha256,
        "root_set_sha256": plan.root_set_sha256,
        "leaf_count": EXPECTED_LEAF_COUNT,
        "node_count": len(nodes),
        "branch_count": len(branches),
        "root_solves": 0,
        "response_solves": 0,
        "julia_launches": 0,
        "numerical_work": 0,
    }
    material = {
        "schema": HANDOFF_SCHEMA,
        "schema_version": HANDOFF_SCHEMA_VERSION,
        "created_utc": created_utc
        or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "m02_terminal": {
            "checkpoint_path": checkpoint_path,
            "checkpoint_sha256": checkpoint_sha,
            "campaign_id": plan.campaign_id,
            "selection_id": selection.selection_id,
            "terminal_reduction": {
                **reduction,
                "terminal_reduction_sha256": _sha256(reduction),
            },
        },
        "inventory": {
            "source_leaf_count": EXPECTED_LEAF_COUNT,
            "node_count": len(nodes),
            "branch_count": len(branches),
            "role_counts": EXPECTED_ROLE_COUNTS,
            "branch_populations": EXPECTED_BRANCH_POPULATIONS,
        },
        "nodes": nodes,
        "branches": branches,
    }
    return {**material, "handoff_sha256": _sha256(material)}


def validate_handoff(value: Mapping[str, object]) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError("M02 to M03 handoff must be an object")
    expected = {
        "schema",
        "schema_version",
        "created_utc",
        "m02_terminal",
        "inventory",
        "nodes",
        "branches",
        "handoff_sha256",
    }
    if set(value) != expected:
        raise ValueError("M02 to M03 handoff fields are invalid")
    if value["schema"] != HANDOFF_SCHEMA or value["schema_version"] != 1:
        raise ValueError("M02 to M03 handoff schema is invalid")
    material = {key: item for key, item in value.items() if key != "handoff_sha256"}
    if value["handoff_sha256"] != _sha256(material):
        raise ValueError("M02 to M03 handoff digest is invalid")
    nodes = value["nodes"]
    branches = value["branches"]
    inventory = value["inventory"]
    if not isinstance(nodes, list) or not isinstance(branches, list):
        raise ValueError("M02 to M03 handoff inventory arrays are invalid")
    if not isinstance(inventory, Mapping):
        raise ValueError("M02 to M03 handoff inventory is invalid")
    if (
        len(nodes) != EXPECTED_NODE_COUNT
        or len(branches) != EXPECTED_BRANCH_COUNT
        or inventory.get("source_leaf_count") != EXPECTED_LEAF_COUNT
        or inventory.get("node_count") != EXPECTED_NODE_COUNT
        or inventory.get("branch_count") != EXPECTED_BRANCH_COUNT
        or inventory.get("role_counts") != EXPECTED_ROLE_COUNTS
        or inventory.get("branch_populations") != EXPECTED_BRANCH_POPULATIONS
    ):
        raise ValueError("M02 to M03 handoff conservation check failed")
    node_ids = [node.get("node_identity_sha256") for node in nodes]
    if (
        any(not isinstance(item, str) or _SHA256.fullmatch(item) is None for item in node_ids)
        or len(node_ids) != len(set(node_ids))
    ):
        raise ValueError("M02 to M03 node identities are invalid")
    by_branch: dict[str, list[Mapping[str, object]]] = defaultdict(list)
    for node in nodes:
        if not isinstance(node, Mapping):
            raise ValueError("M02 to M03 node is invalid")
        by_branch[str(node.get("branch_identity"))].append(node)
        seed = node.get("spectral_seed")
        if not isinstance(seed, Mapping):
            raise ValueError("M02 to M03 spectral seed is invalid")
        encoded = json.dumps(seed, sort_keys=True).lower()
        if any(term in encoded for term in _FORBIDDEN_SEED_TERMS):
            raise ValueError("M02 mechanism response contaminated an M03 seed")
        mode = seed.get("mode")
        coordinate = seed.get("coordinate")
        frozen = seed.get("frozen_eigenvalue")
        lineage = node.get("m02_lineage")
        if not all(
            isinstance(item, Mapping)
            for item in (mode, coordinate, frozen, lineage)
        ):
            raise ValueError("M02 to M03 node identity material is incomplete")
        branch_identity = f"m03-branch-{_sha256(_branch_material(mode))}"
        if branch_identity != node.get("branch_identity"):
            raise ValueError("M03 branch identity is invalid")
        receipts = lineage.get("contributing_leaf_receipts")
        if not isinstance(receipts, list) or not receipts:
            raise ValueError("M03 root lineage has no contributing leaves")
        for receipt in receipts:
            if not isinstance(receipt, Mapping):
                raise ValueError("M03 contributing leaf receipt is invalid")
            receipt_content = {
                key: item for key, item in receipt.items()
                if key != "leaf_receipt_sha256"
            }
            if receipt.get("leaf_receipt_sha256") != _sha256(receipt_content):
                raise ValueError("M03 contributing leaf receipt digest is invalid")
        lineage_content = {
            key: item for key, item in lineage.items()
            if key != "reconciled_root_lineage_sha256"
        }
        if lineage.get("reconciled_root_lineage_sha256") != _sha256(lineage_content):
            raise ValueError("M03 reconciled root lineage digest is invalid")
        for identity_text in (
            coordinate.get("physical_spin_text"),
            frozen.get("omega", {}).get("real") if isinstance(frozen.get("omega"), Mapping) else None,
            frozen.get("omega", {}).get("imaginary") if isinstance(frozen.get("omega"), Mapping) else None,
            frozen.get("angular_separation_constant_A", {}).get("real")
            if isinstance(frozen.get("angular_separation_constant_A"), Mapping) else None,
            frozen.get("angular_separation_constant_A", {}).get("imaginary")
            if isinstance(frozen.get("angular_separation_constant_A"), Mapping) else None,
        ):
            if not isinstance(identity_text, str):
                raise ValueError("M03 canonical numerical identity is missing")
            try:
                canonical = _text(float(identity_text))
            except ValueError as error:
                raise ValueError("M03 canonical numerical identity is invalid") from error
            if identity_text != canonical:
                raise ValueError(
                    "numerically equal but textually different M03 identity"
                )
        node_material = {
            "schema": "windows-solver.m03-node-identity/1",
            "spectral_seed_sha256": _sha256(seed),
            "reconciled_root_lineage_sha256": lineage[
                "reconciled_root_lineage_sha256"
            ],
            "branch_identity": branch_identity,
            "chain_position": node.get("chain_position"),
        }
        if node.get("node_identity_sha256") != _sha256(node_material):
            raise ValueError("M03 node identity digest is invalid")
    for branch in branches:
        if not isinstance(branch, Mapping):
            raise ValueError("M02 to M03 branch record is invalid")
        identity = str(branch.get("branch_identity"))
        members = by_branch.get(identity, [])
        if [item.get("chain_position") for item in members] != list(range(len(members))):
            raise ValueError("M03 branch continuation order is invalid")
        if branch.get("ordered_node_ids") != [item["node_identity_sha256"] for item in members]:
            raise ValueError("M03 branch node inventory is invalid")
        content = {key: item for key, item in branch.items() if key != "branch_record_sha256"}
        if branch.get("branch_record_sha256") != _sha256(content):
            raise ValueError("M03 branch record digest is invalid")
    return json.loads(canonical_json_bytes(value))


def load_handoff(path: str | os.PathLike[str] | Path) -> dict[str, object]:
    return validate_handoff(_strict_json(Path(path), "M02 to M03 handoff"))


def write_handoff(path: str | os.PathLike[str] | Path, value: Mapping[str, object]) -> None:
    _atomic_json(Path(path), validate_handoff(value))


__all__ = [
    "EXPECTED_BRANCH_COUNT",
    "EXPECTED_BRANCH_POPULATIONS",
    "EXPECTED_LEAF_COUNT",
    "EXPECTED_NODE_COUNT",
    "EXPECTED_ROLE_COUNTS",
    "HANDOFF_SCHEMA",
    "build_handoff",
    "load_handoff",
    "validate_handoff",
    "write_handoff",
]
