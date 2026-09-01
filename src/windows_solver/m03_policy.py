"""Selection and numerical-policy validation for M03."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
from typing import Mapping

from .contracts import canonical_json_bytes
from .m03_handoff import HANDOFF_SCHEMA, EXPECTED_BRANCH_COUNT, EXPECTED_NODE_COUNT
from .precision_tiers import PrecisionTier, precision_tier


M03_SELECTION_SCHEMA = "windows-solver.m03-selection/1"
_TOP_FIELDS = {
    "schema",
    "schema_version",
    "expected_handoff_schema",
    "expected_node_count",
    "expected_branch_count",
    "numerical_backend_id",
    "field_representations",
    "right_state_normalization_id",
    "co_mode_pairing_id",
    "precision",
    "radial_discretization",
    "angular_discretization",
    "validation_thresholds",
    "kernel_numerical_policy",
    "branch_overlap_policy",
    "storage_policy",
    "conventions",
    "process_policy",
}

KERNEL_NUMERICAL_POLICY_FIELDS = frozenset({
    "readout_radius",
    "rho_inner",
    "rho_outer",
    "endpoint_order",
    "angular_pad",
    "ode_reltol",
    "ode_abstol",
    "angular_derivative_step",
    "frequency_audit_step",
    "quadrature_panels",
    "angular_right_residual_max",
    "angular_transpose_residual_max",
    "angular_symmetry_residual_max",
    "angular_c_product_min",
    "lambda_derivative_disagreement_max",
    "radial_wronskian_max",
    "matching_right_null_max",
    "matching_left_null_max",
    "transpose_endpoint_residual_max",
    "transpose_readout_residual_max",
    "dual_projective_disagreement_max",
    "bilinear_conservation_max",
    "domega_stencil_relative_disagreement_max",
    "local_domega_to_m02_relative_max",
    "contour_to_readout_denominator_relative_max",
    "bridge_closure_relative_max",
    "residue_rescaling_relative_max",
    "projector_rescaling_relative_max",
    "projector_idempotence_relative_max",
    "projector_action_relative_max",
    "local_resolvent_residue_relative_max",
    "local_resolvent_projector_relative_max",
    "adjugate_residue_relative_max",
    "retained_rho_grid",
})

_KERNEL_INTEGER_FIELDS = frozenset({
    "endpoint_order",
    "angular_pad",
    "quadrature_panels",
})


def _strict_load(path: Path) -> dict[str, object]:
    def pairs(items: list[tuple[str, object]]) -> dict[str, object]:
        output: dict[str, object] = {}
        for key, value in items:
            if key in output:
                raise ValueError(f"M03 selection contains duplicate key {key!r}")
            output[key] = value
        return output

    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=pairs,
            parse_constant=lambda item: (_ for _ in ()).throw(
                ValueError(f"M03 selection contains non-finite constant {item}")
            ),
        )
    except json.JSONDecodeError as error:
        raise ValueError("M03 selection is not valid JSON") from error
    if not isinstance(value, dict):
        raise ValueError("M03 selection must be an object")
    return value


def _mapping(value: object, subject: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{subject} must be an object")
    return value


def _decimal_text(value: object, subject: str) -> Decimal:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{subject} must be canonical decimal text")
    try:
        parsed = Decimal(value)
    except InvalidOperation as error:
        raise ValueError(f"{subject} must be canonical decimal text") from error
    if not parsed.is_finite():
        raise ValueError(f"{subject} must be finite canonical decimal text")
    return parsed


def _positive_decimal_text(value: object, subject: str, *, allow_zero: bool = False) -> None:
    parsed = _decimal_text(value, subject)
    if parsed < 0 or (not allow_zero and parsed == 0):
        raise ValueError(f"{subject} must be positive finite decimal text")


def _validate_kernel_numerical_policy(value: object) -> dict[str, object]:
    policy = _mapping(value, "M03 kernel numerical policy")
    if set(policy) != KERNEL_NUMERICAL_POLICY_FIELDS:
        raise ValueError("M03 kernel numerical policy fields are invalid")
    for name in _KERNEL_INTEGER_FIELDS:
        item = policy[name]
        if isinstance(item, bool) or not isinstance(item, int) or item < 1:
            raise ValueError(f"M03 kernel numerical policy {name} must be positive")
    for name in KERNEL_NUMERICAL_POLICY_FIELDS - _KERNEL_INTEGER_FIELDS - {
        "retained_rho_grid"
    }:
        if name in {"rho_inner", "rho_outer"}:
            _decimal_text(policy[name], f"M03 kernel numerical policy {name}")
        else:
            _positive_decimal_text(
                policy[name], f"M03 kernel numerical policy {name}"
            )
    rho_inner = _decimal_text(
        policy["rho_inner"], "M03 kernel numerical policy rho_inner"
    )
    rho_outer = _decimal_text(
        policy["rho_outer"], "M03 kernel numerical policy rho_outer"
    )
    if not rho_inner < 0 < rho_outer:
        raise ValueError("M03 kernel contour must straddle the canonical readout")
    retained = policy["retained_rho_grid"]
    if not isinstance(retained, list) or len(retained) < 3:
        raise ValueError("M03 retained rho grid must contain at least three points")
    parsed_grid = [
        _decimal_text(item, "M03 retained rho-grid coordinate")
        for item in retained
    ]
    if (
        parsed_grid != sorted(parsed_grid)
        or len(set(parsed_grid)) != len(parsed_grid)
        or parsed_grid[0] < rho_inner
        or parsed_grid[-1] > rho_outer
        or Decimal(0) not in parsed_grid
    ):
        raise ValueError("M03 retained rho grid is not ordered inside the contour")
    return json.loads(canonical_json_bytes(policy))


def validate_m03_selection(value: Mapping[str, object]) -> dict[str, object]:
    if not isinstance(value, Mapping) or set(value) != _TOP_FIELDS:
        raise ValueError("M03 selection fields are invalid")
    if value["schema"] != M03_SELECTION_SCHEMA or value["schema_version"] != 1:
        raise ValueError("M03 selection schema is invalid")
    if value["expected_handoff_schema"] != HANDOFF_SCHEMA:
        raise ValueError("M03 selection expects the wrong handoff schema")
    if value["expected_node_count"] != EXPECTED_NODE_COUNT:
        raise ValueError("M03 selection node count is not the frozen domain")
    if value["expected_branch_count"] != EXPECTED_BRANCH_COUNT:
        raise ValueError("M03 selection branch count is not the frozen domain")
    precision = _mapping(value["precision"], "M03 precision policy")
    if set(precision) != {
        "direct_node",
        "deep_node",
        "promotion",
        "production_ceiling",
        "binary64_field_admissible",
        "automatic_bf120",
    }:
        raise ValueError("M03 precision policy fields are invalid")
    direct = precision_tier(precision["direct_node"])
    deep = precision_tier(precision["deep_node"])
    ceiling = precision_tier(precision["production_ceiling"])
    promotion = _mapping(precision["promotion"], "M03 promotion policy")
    if (
        direct is not PrecisionTier.BIGFLOAT_40
        or deep is not PrecisionTier.BIGFLOAT_80
        or ceiling is not PrecisionTier.BIGFLOAT_80
        or promotion
        != {
            "from": "bigfloat-40",
            "to": "bigfloat-80",
            "on_any_required_gate_failure": True,
        }
        or precision["binary64_field_admissible"] is not False
        or precision["automatic_bf120"] is not False
    ):
        raise ValueError("M03 precision policy violates the BF40/BF80 contract")
    thresholds = _mapping(value["validation_thresholds"], "M03 validation thresholds")
    if set(thresholds) != {
        "review_state",
        "required_decision",
        "right_state",
        "co_mode",
        "pairing",
        "residue_projector",
    }:
        raise ValueError("M03 validation threshold categories are invalid")
    threshold_reviewed = thresholds["review_state"] == "FROZEN"
    if thresholds["review_state"] not in {"FROZEN", "BLOCKED_HUMAN_NUMERICAL_REVIEW"}:
        raise ValueError("M03 validation threshold review state is invalid")
    if not isinstance(thresholds["required_decision"], str) or not thresholds["required_decision"]:
        raise ValueError("M03 validation threshold review decision is invalid")
    for category in ("right_state", "co_mode", "pairing", "residue_projector"):
        entries = thresholds[category]
        entries = _mapping(entries, f"M03 {category} thresholds")
        if not entries:
            raise ValueError(f"M03 {category} thresholds are empty")
        for name, threshold in entries.items():
            if threshold_reviewed:
                _positive_decimal_text(threshold, f"M03 threshold {category}.{name}")
            elif threshold is not None:
                raise ValueError(
                    f"unreviewed M03 threshold {category}.{name} must be null"
                )
    kernel_policy = value["kernel_numerical_policy"]
    if threshold_reviewed:
        _validate_kernel_numerical_policy(kernel_policy)
    elif kernel_policy is not None:
        raise ValueError(
            "unreviewed M03 kernel numerical policy must be null"
        )
    process = _mapping(value["process_policy"], "M03 process policy")
    if set(process) != {
        "worker_count",
        "active_node_count",
        "branch_contiguous",
        "restart_limit_per_node",
        "stdout_protocol_only",
    }:
        raise ValueError("M03 process policy fields are invalid")
    restart_limit = process["restart_limit_per_node"]
    if (
        process.get("worker_count") != 1
        or process.get("active_node_count") != 1
        or process.get("branch_contiguous") is not True
        or isinstance(restart_limit, bool)
        or not isinstance(restart_limit, int)
        or restart_limit < 0
        or process.get("stdout_protocol_only") is not True
    ):
        raise ValueError("M03 process policy must use one persistent worker")
    branch_policy = _mapping(
        value["branch_overlap_policy"], "M03 branch overlap policy"
    )
    if set(branch_policy) != {
        "policy_id",
        "minimum_overlap",
        "overlap_is_evidence_only",
        "unresolved_gap_blocks_continuation",
        "cold_start_across_gap_requires_review",
    } or branch_policy != {
        "policy_id": "m03-bilinear-normalized-field-overlap-v1",
        "minimum_overlap": None,
        "overlap_is_evidence_only": True,
        "unresolved_gap_blocks_continuation": True,
        "cold_start_across_gap_requires_review": True,
    }:
        raise ValueError(
            "M03 continuation overlap must remain evidence-only without a "
            "universal threshold"
        )
    conventions = _mapping(value["conventions"], "M03 conventions")
    if set(conventions) != {
        "version", "right_state", "co_mode", "residue", "branch_classification", "nhek_match"
    }:
        raise ValueError("M03 convention fields are invalid")
    return json.loads(canonical_json_bytes(value))


def load_m03_selection(path: str | Path) -> dict[str, object]:
    return validate_m03_selection(_strict_load(Path(path)))


def selection_sha256(value: Mapping[str, object]) -> str:
    return hashlib.sha256(canonical_json_bytes(validate_m03_selection(value))).hexdigest()


def kernel_numerical_policy(value: Mapping[str, object]) -> dict[str, object]:
    selection = validate_m03_selection(value)
    policy = selection["kernel_numerical_policy"]
    if policy is None:
        raise ValueError("M03 kernel numerical policy is not frozen")
    return _validate_kernel_numerical_policy(policy)


def kernel_numerical_policy_sha256(value: Mapping[str, object]) -> str:
    return hashlib.sha256(
        canonical_json_bytes(kernel_numerical_policy(value))
    ).hexdigest()


def production_blockers(value: Mapping[str, object]) -> tuple[str, ...]:
    selection = validate_m03_selection(value)
    conventions = selection["conventions"]
    blockers: list[str] = []
    thresholds = selection["validation_thresholds"]
    if thresholds["review_state"] != "FROZEN":
        blockers.append(f"validation_thresholds:{thresholds['required_decision']}")
    if selection["kernel_numerical_policy"] is None:
        blockers.append(
            f"kernel_numerical_policy:{thresholds['required_decision']}"
        )
    for name in ("right_state", "co_mode", "residue", "branch_classification"):
        item = conventions[name]
        if item["review_state"] != "FROZEN":
            blockers.append(f"{name}:{item['required_decision']}")
    return tuple(blockers)


__all__ = [
    "M03_SELECTION_SCHEMA",
    "load_m03_selection",
    "kernel_numerical_policy",
    "kernel_numerical_policy_sha256",
    "production_blockers",
    "selection_sha256",
    "validate_m03_selection",
]
