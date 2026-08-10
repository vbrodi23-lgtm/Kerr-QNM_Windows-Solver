"""Disposable human- and machine-readable views of authenticated M02 state.

This module only projects an already committed campaign checkpoint.  It does
not own campaign execution, acceptance, uncertainty construction, or
projective classification.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile
from typing import Mapping, Sequence

from .response_batches import (
    CampaignLeafRecord,
    CampaignPlan,
    STAGE_SIGNED_ERROR_FAMILIES,
    validate_campaign_checkpoint,
)
from .response_engine import ComponentResult, ERROR_CHANNELS
from .response_reduction import (
    ComputedUnresolvedComponentEvidence,
    ResolvedComponentEvidence,
    SignedErrorContribution,
    build_projective_row_plans,
    reduce_projective_rows,
)


LEAF_COLUMNS = (
    "leaf_ordinal",
    "leaf_id",
    "role",
    "mode",
    "ell",
    "m",
    "n",
    "coordinate_role",
    "coordinate_exact",
    "spin_or_Mkappa",
    "spin_binary64_hex",
    "mechanism",
    "terminal_state",
    "component_status",
    "precision_digits",
    "convergence_basis",
    "response_real",
    "response_imaginary",
    "response_magnitude",
    "local_disk_radius",
    "relative_disk_radius",
    "relative_disk_state",
    "baseline_omega_real",
    "baseline_omega_imaginary",
    "baseline_determinant_residual",
    "baseline_newton_correction",
    "signed_root_crosscheck_real",
    "signed_root_crosscheck_imaginary",
    "signed_root_crosscheck_magnitude",
    "signed_root_error",
    "truncation_error",
    "resolution_error",
    "seed_path_error",
    "axis_error",
    "amplitude_error",
    "run_provenance",
    "record_sha256",
    "stage_sha256",
    "root_reference_id",
    "root_identity_sha256",
    "policy_sha256",
    "backend_identity_sha256",
    "checkpoint_source_receipt",
)

ERROR_CHANNEL_COLUMNS = (
    "component_id",
    "leaf_ordinal",
    "precision_digits",
    "channel_index",
    "channel_id",
    "family",
    "shared_group",
    "scope",
    "signed_delta_real",
    "signed_delta_imaginary",
    "signed_delta_magnitude",
    "units",
    "source_kind",
    "source_id",
    "source_sha256",
    "derivation",
    "source_receipt",
    "record_sha256",
    "stage_sha256",
)

PROJECTIVE_COLUMNS = (
    "row_id",
    "role",
    "support",
    "mode_order",
    "coordinate_role",
    "coordinate_exact",
    "spin_binary64_hex",
    "left_mechanism",
    "right_mechanism",
    "left_component_ids",
    "right_component_ids",
    "present_component_ids",
    "missing_component_ids",
    "produced_unresolved_component_ids",
    "left_vector",
    "right_vector",
    "calibration_mode",
    "calibration_component_ids",
    "nominal_angle",
    "angle_lower_bound",
    "angle_upper_bound",
    "separation_threshold",
    "equivalence_threshold",
    "calibration_disk_contains_zero",
    "projective_outcome",
    "scientific_state",
    "empirical_gram_id",
    "empirical_gram",
    "linearized_input_basis",
    "linearized_step_policy",
    "linearized_angle_jacobian",
    "linearized_angle_gram",
    "linearized_angle_columns",
    "reducer_state",
    "reason",
    "evidence_ceiling",
    "reduction_id",
    "checkpoint_source_receipt",
)


@dataclass(frozen=True, slots=True)
class CampaignReportModel:
    """One normalized projection shared by CSV and terminal renderers."""

    leaf_rows: tuple[Mapping[str, object], ...]
    error_channel_rows: tuple[Mapping[str, object], ...]
    projective_rows: tuple[Mapping[str, object], ...]
    checkpoint_source_receipt: str


def report_directory_for_checkpoint(checkpoint_path: str | os.PathLike[str]) -> Path:
    checkpoint = Path(checkpoint_path)
    return checkpoint.with_name(f"{checkpoint.stem}.reports")


def _json_cell(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _csv_cell(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("campaign report contains a non-finite number")
        return format(value, ".17g")
    return str(value)


def _component_result(record: CampaignLeafRecord) -> ComponentResult | None:
    if not record.stages:
        return None
    raw = record.stages[-1].outcome.component_result.get("result")
    if not isinstance(raw, Mapping):
        return None
    return ComponentResult.from_mapping(raw)


def _leaf_row(
    ordinal: int,
    leaf: object,
    record: CampaignLeafRecord | None,
    *,
    provenance: str,
    source_receipt: str,
) -> dict[str, object]:
    domain_leaf = leaf.leaf
    job = leaf.job
    row = {name: None for name in LEAF_COLUMNS}
    row.update({
        "leaf_ordinal": ordinal,
        "leaf_id": leaf.leaf_id,
        "role": leaf.role,
        "mode": domain_leaf.mode_label,
        "ell": domain_leaf.mode[0],
        "m": domain_leaf.mode[1],
        "n": domain_leaf.mode[2],
        "coordinate_role": domain_leaf.spin_role,
        "coordinate_exact": (
            f"{domain_leaf.coordinate.numerator}/"
            f"{domain_leaf.coordinate.denominator}"
        ),
        "spin_or_Mkappa": format(float(domain_leaf.coordinate), ".17g"),
        "spin_binary64_hex": domain_leaf.spin.hex(),
        "mechanism": leaf.mechanism_id,
        "terminal_state": "PENDING" if record is None else record.state,
        "run_provenance": provenance if record is not None else "",
        "root_reference_id": job.root.root_reference_id,
        "root_identity_sha256": job.root.identity_sha256,
        "policy_sha256": job.policy.identity_sha256,
        "backend_identity_sha256": job.backend_identity.identity_sha256,
        "checkpoint_source_receipt": source_receipt,
    })
    if record is None or not record.stages:
        return row

    stage = record.stages[-1]
    outcome = stage.outcome
    result = _component_result(record)
    row.update({
        "component_status": (
            outcome.numerical_state if result is None else result.status.value
        ),
        "precision_digits": outcome.digits,
        "convergence_basis": (
            "" if result is None else result.convergence_basis
        ),
        "local_disk_radius": outcome.local_disk_radius_abs,
        "record_sha256": record.record_sha256,
        "stage_sha256": stage.stage_sha256,
    })
    if result is None:
        return row

    row.update({
        "baseline_omega_real": result.baseline.omega.real,
        "baseline_omega_imaginary": result.baseline.omega.imag,
        "baseline_determinant_residual": (
            result.baseline.determinant_residual_abs
        ),
        "baseline_newton_correction": (
            result.baseline.newton_correction_estimate
        ),
        **{
            f"{name.replace('-', '_')}_error": result.error_channels[name]
            for name in ERROR_CHANNELS
        },
    })
    if record.state != "PRODUCED" or result.response is None:
        row["relative_disk_state"] = "UNRESOLVED"
        return row

    magnitude = abs(result.response)
    row.update({
        "response_real": result.response.real,
        "response_imaginary": result.response.imag,
        "response_magnitude": magnitude,
    })
    if result.signed_root_crosscheck is not None:
        row.update({
            "signed_root_crosscheck_real": result.signed_root_crosscheck.real,
            "signed_root_crosscheck_imaginary": (
                result.signed_root_crosscheck.imag
            ),
            "signed_root_crosscheck_magnitude": abs(
                result.signed_root_crosscheck
            ),
        })
    if magnitude == 0.0:
        row["relative_disk_state"] = "ZERO_RESPONSE"
    else:
        row["relative_disk_radius"] = outcome.local_disk_radius_abs / magnitude
        row["relative_disk_state"] = "FINITE"
    return row


def _normalized_channel(
    component_id: str,
    raw_channel: Mapping[str, object],
    source_receipt: str,
) -> SignedErrorContribution:
    delta = raw_channel["signed_delta"]
    if not isinstance(delta, Mapping):
        raise ValueError("campaign report signed channel delta is invalid")
    if raw_channel["scope"] == "local":
        channel_id = f"local:{component_id}:{raw_channel['family']}"
        shared_group = component_id
    else:
        channel_id = str(raw_channel["channel_id"])
        shared_group = str(raw_channel["shared_group"])
    return SignedErrorContribution(
        channel_id=channel_id,
        family=str(raw_channel["family"]),
        shared_group=shared_group,
        delta=complex(float(delta["real"]), float(delta["imaginary"])),
        units=str(raw_channel["units"]),
        source_receipt=source_receipt,
        scope=str(raw_channel["scope"]),
    )


def _error_channel_rows(
    ordinal: int,
    record: CampaignLeafRecord,
    *,
    source_receipt: str,
) -> tuple[dict[str, object], ...]:
    if not record.stages:
        return ()
    stage = record.stages[-1]
    output: list[dict[str, object]] = []
    for index, raw_channel in enumerate(stage.outcome.signed_error_channels, start=1):
        normalized = _normalized_channel(record.leaf_id, raw_channel, source_receipt)
        provenance = raw_channel["provenance"]
        if not isinstance(provenance, Mapping):
            raise ValueError("campaign report signed channel provenance is invalid")
        output.append({
            "component_id": record.leaf_id,
            "leaf_ordinal": ordinal,
            "precision_digits": stage.outcome.digits,
            "channel_index": index,
            "channel_id": normalized.channel_id,
            "family": normalized.family,
            "shared_group": normalized.shared_group,
            "scope": normalized.scope,
            "signed_delta_real": normalized.delta.real,
            "signed_delta_imaginary": normalized.delta.imag,
            "signed_delta_magnitude": abs(normalized.delta),
            "units": normalized.units,
            "source_kind": provenance["source_kind"],
            "source_id": provenance["source_id"],
            "source_sha256": provenance["source_sha256"],
            "derivation": provenance["derivation"],
            "source_receipt": source_receipt,
            "record_sha256": record.record_sha256,
            "stage_sha256": stage.stage_sha256,
        })
    return tuple(output)


def _reduction_component(
    record: CampaignLeafRecord,
    *,
    source_receipt: str,
) -> ResolvedComponentEvidence | ComputedUnresolvedComponentEvidence | None:
    if record.state not in {"PRODUCED", "UNRESOLVED"} or not record.stages:
        return None
    result = _component_result(record)
    if result is None:
        return None
    stage = record.stages[-1]
    contributions = tuple(
        _normalized_channel(record.leaf_id, item, source_receipt)
        for item in stage.outcome.signed_error_channels
    )
    if record.state == "PRODUCED" and result.response is not None:
        discrepancies = tuple(
            item.outcome.discrepancy_from_previous_abs
            for item in record.stages
            if item.outcome.discrepancy_from_previous_abs is not None
        )
        return ResolvedComponentEvidence(
            component_id=record.leaf_id,
            centre=result.response,
            units=contributions[0].units,
            contributions=contributions,
            recorded_discrepancies=discrepancies,
            required_families=STAGE_SIGNED_ERROR_FAMILIES,
            evidence_kind="authenticated-campaign",
        )
    return ComputedUnresolvedComponentEvidence(
        component_id=record.leaf_id,
        units=contributions[0].units,
        contributions=contributions,
        reason=(
            f"{stage.outcome.numerical_state}: "
            f"{result.status.value} / {result.convergence_basis}"
        ),
        source_receipt=source_receipt,
        evidence_kind="authenticated-campaign",
    )


def _vector_cell(
    component_ids: Sequence[str],
    leaf_rows_by_id: Mapping[str, Mapping[str, object]],
) -> str:
    values = []
    for component_id in component_ids:
        row = leaf_rows_by_id[component_id]
        values.append({
            "component_id": component_id,
            "mode": row["mode"],
            "response_real": row["response_real"],
            "response_imaginary": row["response_imaginary"],
            "local_disk_radius": row["local_disk_radius"],
            "terminal_state": row["terminal_state"],
        })
    return _json_cell(values)


def project_campaign_reports(
    plan: CampaignPlan,
    checkpoint_path: str | os.PathLike[str],
    *,
    run_provenance: Mapping[str, str] | None = None,
) -> CampaignReportModel:
    """Authenticate and normalize one committed checkpoint without changing it."""

    checkpoint = Path(checkpoint_path)
    checkpoint_bytes = checkpoint.read_bytes()
    source_receipt = "sha256:" + hashlib.sha256(checkpoint_bytes).hexdigest()
    summary = validate_campaign_checkpoint(plan, checkpoint)
    records_by_id = {record.leaf_id: record for record in summary.records}
    provenance = dict(run_provenance or {})
    allowed_ids = {leaf.leaf_id for leaf in plan.leaves}
    if set(provenance) - allowed_ids or any(
        value not in {"EXECUTED", "REUSED"} for value in provenance.values()
    ):
        raise ValueError("campaign report run provenance is invalid")

    leaf_rows = tuple(
        _leaf_row(
            ordinal,
            leaf,
            records_by_id.get(leaf.leaf_id),
            provenance=provenance.get(leaf.leaf_id, "REUSED"),
            source_receipt=source_receipt,
        )
        for ordinal, leaf in enumerate(plan.leaves, start=1)
    )
    ordinal_by_id = {
        leaf.leaf_id: ordinal
        for ordinal, leaf in enumerate(plan.leaves, start=1)
    }
    error_rows = tuple(
        row
        for record in summary.records
        for row in _error_channel_rows(
            ordinal_by_id[record.leaf_id],
            record,
            source_receipt=source_receipt,
        )
    )

    row_plans = build_projective_row_plans()
    projective_component_ids = {
        component_id
        for row_plan in row_plans
        for component_id in (
            *row_plan.left_component_ids,
            *row_plan.right_component_ids,
        )
    }
    components = {
        record.leaf_id: component
        for record in summary.records
        if record.leaf_id in projective_component_ids
        for component in (
            _reduction_component(record, source_receipt=source_receipt),
        )
        if component is not None
    }
    reduction = reduce_projective_rows(
        plan.campaign_id,
        tuple(item.row_id for item in row_plans),
        components,
        source_hashes=(source_receipt,),
    )
    grams_by_id = {
        item.construction_id: item.to_mapping()
        for item in reduction.empirical_grams
    }
    leaf_rows_by_id = {str(row["leaf_id"]): row for row in leaf_rows}
    projective_rows = tuple(
        {
            "row_id": row_plan.row_id,
            "role": row_plan.role,
            "support": row_plan.support_id,
            "mode_order": _json_cell(row_plan.mode_labels),
            "coordinate_role": row_plan.coordinate_role,
            "coordinate_exact": (
                f"{row_plan.coordinate.numerator}/"
                f"{row_plan.coordinate.denominator}"
            ),
            "spin_binary64_hex": row_plan.spin_binary64_hex,
            "left_mechanism": row_plan.left_mechanism_id,
            "right_mechanism": row_plan.right_mechanism_id,
            "left_component_ids": _json_cell(row_plan.left_component_ids),
            "right_component_ids": _json_cell(row_plan.right_component_ids),
            "present_component_ids": _json_cell(result.present_component_ids),
            "missing_component_ids": _json_cell(result.missing_component_ids),
            "produced_unresolved_component_ids": _json_cell(
                result.produced_unresolved_component_ids
            ),
            "left_vector": _vector_cell(
                row_plan.left_component_ids, leaf_rows_by_id
            ),
            "right_vector": _vector_cell(
                row_plan.right_component_ids, leaf_rows_by_id
            ),
            "calibration_mode": row_plan.calibration_mode_label,
            "calibration_component_ids": _json_cell(
                row_plan.calibration_component_ids
            ),
            "nominal_angle": result.nominal_angle_radians,
            "angle_lower_bound": (
                None
                if result.bounded_angle_interval_radians is None
                else result.bounded_angle_interval_radians[0]
            ),
            "angle_upper_bound": (
                None
                if result.bounded_angle_interval_radians is None
                else result.bounded_angle_interval_radians[1]
            ),
            "separation_threshold": row_plan.separation_lower_radians,
            "equivalence_threshold": row_plan.equivalence_upper_radians,
            "calibration_disk_contains_zero": (
                result.calibration_disk_contains_zero
            ),
            "projective_outcome": result.projective_outcome,
            "scientific_state": result.scientific_state,
            "empirical_gram_id": result.empirical_gram_id,
            "empirical_gram": (
                ""
                if result.empirical_gram_id is None
                else _json_cell(grams_by_id[result.empirical_gram_id])
            ),
            "linearized_input_basis": _json_cell(
                result.linearized_input_basis
            ),
            "linearized_step_policy": (
                ""
                if result.linearized_step_policy is None
                else _json_cell(result.linearized_step_policy)
            ),
            "linearized_angle_jacobian": _json_cell(
                result.linearized_angle_jacobian
            ),
            "linearized_angle_gram": result.linearized_angle_gram,
            "linearized_angle_columns": _json_cell(
                [
                    {"channel_id": channel_id, "signed_angle_delta": value}
                    for channel_id, value in result.linearized_angle_columns
                ]
            ),
            "reducer_state": result.reducer_state,
            "reason": result.reason,
            "evidence_ceiling": row_plan.evidence_ceiling,
            "reduction_id": reduction.reduction_id,
            "checkpoint_source_receipt": source_receipt,
        }
        for row_plan, result in zip(reduction.plans, reduction.results)
    )
    return CampaignReportModel(
        leaf_rows=leaf_rows,
        error_channel_rows=error_rows,
        projective_rows=projective_rows,
        checkpoint_source_receipt=source_receipt,
    )


def _atomic_csv(
    path: Path,
    columns: Sequence[str],
    rows: Sequence[Mapping[str, object]],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        text=True,
    )
    try:
        with os.fdopen(
            descriptor, "w", encoding="utf-8", newline=""
        ) as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=columns,
                extrasaction="raise",
                lineterminator="\n",
            )
            writer.writeheader()
            writer.writerows(
                {
                    column: _csv_cell(row.get(column))
                    for column in columns
                }
                for row in rows
            )
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    except BaseException:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def refresh_campaign_reports(
    plan: CampaignPlan,
    checkpoint_path: str | os.PathLike[str],
    *,
    run_provenance: Mapping[str, str] | None = None,
) -> CampaignReportModel:
    """Atomically refresh all disposable CSV views beside a checkpoint."""

    model = project_campaign_reports(
        plan,
        checkpoint_path,
        run_provenance=run_provenance,
    )
    directory = report_directory_for_checkpoint(checkpoint_path)
    _atomic_csv(directory / "m02-leaves.csv", LEAF_COLUMNS, model.leaf_rows)
    _atomic_csv(
        directory / "m02-error-channels.csv",
        ERROR_CHANNEL_COLUMNS,
        model.error_channel_rows,
    )
    _atomic_csv(
        directory / "m02-projective.csv",
        PROJECTIVE_COLUMNS,
        model.projective_rows,
    )
    return model
