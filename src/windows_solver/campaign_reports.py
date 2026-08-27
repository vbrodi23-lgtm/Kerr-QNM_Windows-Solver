"""Disposable human- and machine-readable views of authenticated M02 state.

This module only projects an already committed campaign checkpoint.  It does
not own campaign execution, acceptance, uncertainty construction, or
projective classification.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile
from typing import Callable, Mapping, Sequence

from .contracts import canonical_json_bytes
from .campaign_failures import system_failure_resolution_index
from .response_batches import (
    CampaignLeafRecord,
    CampaignPlan,
    STAGE_SIGNED_ERROR_FAMILIES,
    validate_campaign_checkpoint,
)
from .julia_response_backend import promoted_precision_numerical_controls
from .precision_tiers import precision_tier_presentation
from .response_engine import ComponentResult, ERROR_CHANNELS
from .response_reduction import (
    BoundedComponentEvidence,
    CampaignReductionSummary,
    ComputedUnresolvedComponentEvidence,
    ResolvedComponentEvidence,
    SignedErrorContribution,
    build_projective_row_plans,
    reduce_projective_rows,
)


SCHEMA11_LEAF_COLUMNS = (
    "leaf_ordinal",
    "leaf_id",
    "role",
    "mode",
    "spin_or_Mkappa",
    "mechanism",
    "numerical_state",
    "evidence_level",
    "binary64_pass_disposition",
    "promoted_pass_disposition",
    "promoted_route",
    "admission_state",
    "promotion_reason",
    "execution_profile",
    "survey_pass",
    "precision_tier",
    "precision_tiers",
    "sample_count",
    "root_read_count",
    "worker_launch_count",
    "binary64_seconds",
    "bf40_seconds",
    "bf80_seconds",
    "bf120_seconds",
    "total_seconds",
    "response_real",
    "response_imaginary",
    "response_magnitude",
    "response_disk_radius",
    "relative_disk_radius",
    "record_sha256",
    "stage_sha256",
    "retained_promoted_stage_sha256",
    "receipt_sha256",
)

SCHEMA11_PRECISION_STAGE_COLUMNS = (
    "leaf_ordinal",
    "leaf_id",
    "stage_index",
    "precision_tier",
    "stage_sha256",
    "record_sha256",
    "stage_source",
    "admission_state",
)

SCHEMA11_ERROR_CHANNEL_COLUMNS = (
    "leaf_ordinal",
    "leaf_id",
    "stage_index",
    "channel_index",
    "family",
    "signed_delta_real",
    "signed_delta_imaginary",
    "stage_sha256",
    "record_sha256",
    "stage_source",
    "admission_state",
    "disagreement_term_sha256",
)

SCHEMA11_RESOURCE_FAILURE_COLUMNS = (
    "failure_ordinal",
    "leaf_id",
    "failure_code",
    "cause_type",
    "fingerprint_sha256",
    "receipt_sha256",
    "resolution_state",
    "resolution_receipt_sha256",
    "resolution_repair_commit_sha",
    "resolution_reason",
)


# The terms of the acceptance comparison itself, so a reader can re-derive the
# decision from a report row instead of taking `converged` on faith. Absent for
# determinant families that publish no error model, which is why every column
# is nullable rather than defaulted.
#
# Deliberately a sibling of CONDITIONING_REPORT_COLUMNS rather than part of it.
# Conditioning describes how healthy the arithmetic of a solve was; this
# describes what the acceptance decision was made on. They answer different
# questions, they can be present independently, and the conditioning tuple is
# pinned by contract and mirrored into the live progress mapping -- widening it
# would put acceptance terms on a dashboard that reports solve health.
AUTHENTICATION_REPORT_COLUMNS = (
    "central_determinant_re",
    "central_determinant_im",
    "determinant_error_model",
    "determinant_error_abs",
    "determinant_error_safety_factor",
    "endpoint_disagreement_abs",
    "control_disagreement_abs",
    "equivalence_disagreement_abs",
    "precision_disagreement_abs",
    "residual_upper_bound_abs",
    "derivative_re",
    "derivative_im",
    "derivative_lower_bound_abs",
    "derivative_propagated_error_abs",
    "derivative_step_disagreement_abs",
    "derivative_selected_step",
    "derivative_axis",
    "correction_upper_bound",
    "root_correction_tolerance",
    "root_authentication_accepted",
)


CONDITIONING_REPORT_COLUMNS = (
    "homogeneous_representation",
    "determinant_family",
    "determinant_normalisation",
    "scattering_diagnostics_applicable",
    "scattering_column_convention",
    "determinant_convention",
    "series_digits_lost_max",
    "series_evaluation_spread_max",
    "last_term_ratio_max",
    "recurrence_digits_lost_max",
    "asymptotic_predicted_reliable_digits_min",
    "basis_condition_max",
    "basis_backward_error_max",
    "matching_reconstruction_residual_max",
    "endpoint_remainders_regular",
    "endpoint_reconstruction_error_max",
    "contour_angle_deformation_max",
    "fd_digits_lost_max",
    "predicted_reliable_digits",
    "required_reliable_digits",
    "precision_limited",
    "cref_chart_margin_min",
    "carrier_change_error_max",
    "normalised_determinant_abs",
    "raw_determinant_abs",
    "raw_determinant_evidence_status",
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
    "precision_tier",
    "precision_decimal_digits_nominal",
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
    *CONDITIONING_REPORT_COLUMNS,
    *AUTHENTICATION_REPORT_COLUMNS,
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
    "precision_tier",
    "precision_decimal_digits_nominal",
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

RESOURCE_FAILURE_COLUMNS = (
    "attempt_ordinal",
    "leaf_index",
    "leaf_id",
    "mode",
    "spin_or_Mkappa",
    "mechanism",
    "precision_digits",
    "readout_role",
    "phase",
    "newton_index",
    "determinant_count",
    "determinant_purpose",
    "elapsed_seconds",
    "elapsed_phase_seconds",
    "elapsed_leg_seconds",
    "failure_code",
    "limiting_resource",
    "ode_leg",
    "ode_accepted_steps",
    "ode_rejected_steps",
    "rhs_evaluations",
    "retry_status",
    "resource_policy_schema",
    "resource_policy_version",
    "resource_policy_sha256",
    "attempt_sha256",
    "created_at_utc",
    "checkpoint_source_receipt",
)

PRECISION_STAGE_COLUMNS = (
    "leaf_ordinal",
    "leaf_id",
    "stage_index",
    "root",
    "precision_digits",
    "numerical_state",
    "component_status",
    "converged",
    "branch_ok",
    "determinant_abs",
    "newton_correction",
    "newton_correction_over_tolerance",
    "root_displacement_abs",
)


@dataclass(frozen=True, slots=True)
class CampaignReportModel:
    """One normalized projection shared by CSV and terminal renderers."""

    leaf_rows: tuple[Mapping[str, object], ...]
    error_channel_rows: tuple[Mapping[str, object], ...]
    projective_rows: tuple[Mapping[str, object], ...]
    checkpoint_source_receipt: str
    precision_stage_rows: tuple[Mapping[str, object], ...] = ()
    resource_failure_rows: tuple[Mapping[str, object], ...] = ()


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


def _stage_component_result(stage: object) -> ComponentResult | None:
    outcome = getattr(stage, "outcome", None)
    component_result = getattr(outcome, "component_result", None)
    if not isinstance(component_result, Mapping):
        return None
    raw = component_result.get("result")
    if not isinstance(raw, Mapping):
        return None
    return ComponentResult.from_mapping(raw)


def _component_result(record: CampaignLeafRecord) -> ComponentResult | None:
    if not record.stages:
        return None
    return _stage_component_result(record.stages[-1])


def _optional_evidence_value(value: object, name: str) -> object:
    if isinstance(value, Mapping):
        return value.get(name)
    return getattr(value, name, None)


def _conditioning_report_fields(readout: object) -> dict[str, object]:
    """Project optional schema-2 evidence without synthesizing legacy values."""

    output = {name: None for name in CONDITIONING_REPORT_COLUMNS}
    conditioning = _optional_evidence_value(readout, "numerical_conditioning")
    evidence_fields = {
        "homogeneous_representation": "homogeneous_representation",
        "determinant_family": "determinant_family",
        "determinant_normalisation": "determinant_normalisation",
        "scattering_diagnostics_applicable": (
            "scattering_diagnostics_applicable"
        ),
        "scattering_column_convention": "scattering_column_convention",
        "determinant_convention": "determinant_convention",
        "series_digits_lost_max": "maximum_series_digits_lost",
        "series_evaluation_spread_max": "maximum_series_evaluation_spread",
        "last_term_ratio_max": "maximum_last_term_ratio",
        "recurrence_digits_lost_max": "maximum_recurrence_digits_lost",
        "asymptotic_predicted_reliable_digits_min": (
            "minimum_asymptotic_predicted_reliable_digits"
        ),
        "basis_condition_max": "maximum_basis_condition",
        "basis_backward_error_max": "maximum_basis_backward_error",
        "matching_reconstruction_residual_max": (
            "maximum_matching_reconstruction_residual"
        ),
        "endpoint_remainders_regular": "endpoint_remainders_regular",
        "endpoint_reconstruction_error_max": (
            "maximum_endpoint_reconstruction_error"
        ),
        "contour_angle_deformation_max": (
            "maximum_contour_angle_deformation"
        ),
        "fd_digits_lost_max": "maximum_fd_digits_lost",
        "predicted_reliable_digits": "predicted_reliable_digits",
        "required_reliable_digits": "required_reliable_digits",
        "precision_limited": "precision_limited",
        "cref_chart_margin_min": "minimum_cref_chart_margin",
        "carrier_change_error_max": "maximum_carrier_change_error",
    }
    if conditioning is not None:
        for report_name, evidence_name in evidence_fields.items():
            output[report_name] = _optional_evidence_value(
                conditioning, evidence_name
            )
    # Determinant magnitudes are precision-exact RootReadout evidence.  Never
    # synthesize them from binary64 compatibility fields or conditioning loss
    # estimates, including for historical records where they remain absent.
    for name in ("normalised_determinant_abs", "raw_determinant_abs"):
        output[name] = _optional_evidence_value(readout, name)
    output["raw_determinant_evidence_status"] = _optional_evidence_value(
        readout, "raw_determinant_evidence_status"
    )
    return output


def _authentication_report_fields(readout: object) -> dict[str, object]:
    """Project the acceptance comparison's own terms onto report columns.

    Reported as the worker's decimal text, not as floats. These numbers live at
    1e-60 and below; rendering them through binary64 would round several of
    them to the same value and quietly destroy the comparison the columns exist
    to expose.
    """

    output: dict[str, object] = {
        name: None for name in AUTHENTICATION_REPORT_COLUMNS
    }
    authentication = _optional_evidence_value(readout, "root_authentication")
    if authentication is None:
        return output
    for column, name in (
        ("central_determinant_re", "central_determinant_re"),
        ("central_determinant_im", "central_determinant_im"),
        ("residual_upper_bound_abs", "residual_upper_bound_abs"),
        ("derivative_lower_bound_abs", "derivative_lower_bound_abs"),
        ("derivative_propagated_error_abs", "derivative_propagated_error_abs"),
        (
            "derivative_step_disagreement_abs",
            "derivative_step_disagreement_abs",
        ),
        ("derivative_selected_step", "selected_step"),
        ("derivative_axis", "derivative_axis"),
        ("correction_upper_bound", "correction_upper_bound"),
        ("root_correction_tolerance", "root_correction_tolerance"),
        ("root_authentication_accepted", "accepted"),
        ("determinant_error_model", "error_model_id"),
    ):
        output[column] = _decimal_report_text(
            _optional_evidence_value(authentication, name)
        )
    derivative = _optional_evidence_value(
        authentication, "derivative_authentication"
    )
    if derivative is not None:
        for column, name in (
            ("derivative_re", "derivative_re"),
            ("derivative_im", "derivative_im"),
        ):
            output[column] = _decimal_report_text(
                _optional_evidence_value(derivative, name)
            )
    breakdown = _optional_evidence_value(authentication, "error_breakdown")
    if breakdown is None:
        return output
    for column, name in (
        ("determinant_error_abs", "numerical_error_abs"),
        ("determinant_error_safety_factor", "safety_factor"),
        ("endpoint_disagreement_abs", "endpoint_disagreement_abs"),
        ("control_disagreement_abs", "control_disagreement_abs"),
        ("equivalence_disagreement_abs", "equivalence_disagreement_abs"),
        ("precision_disagreement_abs", "precision_disagreement_abs"),
    ):
        output[column] = _decimal_report_text(
            _optional_evidence_value(breakdown, name)
        )
    return output


def _decimal_report_text(value: object) -> object:
    """Return a ``Decimal`` as exact text, leaving anything else alone."""

    return str(value) if isinstance(value, Decimal) else value


def _root_correction_tolerance_for_precision(digits: int) -> float:
    """Return the Newton-correction threshold governing one M02 stage.

    The promoted threshold is read from the policy the solver was actually
    given, not reconstructed from the stored digit count. Those two answers used
    to differ enormously: a 120-digit stage was reported against ``1e-102``
    while an earlier uncalibrated request carried ``1e-18``, so
    ``newton_correction_over_tolerance`` was wrong by some eighty orders of
    magnitude and a converged root read as hopelessly under-converged.

    The current policy uses the established binary64 threshold of ``2e-11``
    for every arithmetic tier. Working precision cannot determine or silently
    tighten this scientific acceptance criterion.
    """

    if digits == 64:
        # Binary64 is not a promoted tier and carries no policy entry.
        return 2.0e-11
    controls = promoted_precision_numerical_controls()
    tier = controls.get(str(digits))
    if not isinstance(tier, Mapping):
        raise ValueError("campaign report stage precision is invalid")
    base = tier["base"]
    assert isinstance(base, Mapping)
    return float(base["root_correction_tolerance"])


def _precision_stage_rows(
    plan: CampaignPlan,
    records_by_id: Mapping[str, CampaignLeafRecord],
) -> tuple[Mapping[str, object], ...]:
    """Project every committed precision stage for the terminal dashboard."""

    rows: list[Mapping[str, object]] = []
    for ordinal, leaf in enumerate(plan.leaves, start=1):
        record = records_by_id.get(leaf.leaf_id)
        if record is None:
            continue
        domain_leaf = leaf.leaf
        root_label = (
            f"{domain_leaf.mode_label} a/M="
            f"{format(float(domain_leaf.coordinate), '.6g')}"
        )
        for stage_index, stage in enumerate(record.stages, start=1):
            outcome = stage.outcome
            result = _stage_component_result(stage)
            row: dict[str, object] = {
                "leaf_ordinal": ordinal,
                "leaf_id": leaf.leaf_id,
                "stage_index": stage_index,
                "root": root_label,
                "precision_digits": outcome.digits,
                "numerical_state": outcome.numerical_state,
                "component_status": None,
                "converged": None,
                "branch_ok": None,
                "determinant_abs": None,
                "newton_correction": None,
                "newton_correction_over_tolerance": None,
                "root_displacement_abs": None,
            }
            if result is not None:
                baseline = result.baseline
                determinant_abs = baseline.determinant_residual_abs
                row.update({
                    "component_status": result.status.value,
                    "converged": baseline.converged,
                    "branch_ok": (
                        result.status.value != "BRANCH_LOSS"
                        and baseline.root_reference_id
                        == leaf.job.root.root_reference_id
                        and baseline.branch_id == leaf.job.root.branch_id
                        and baseline.equation_id == leaf.job.equation_id
                    ),
                    "determinant_abs": determinant_abs,
                    "newton_correction": baseline.newton_correction_estimate,
                    "newton_correction_over_tolerance": (
                        baseline.newton_correction_estimate
                        / _root_correction_tolerance_for_precision(outcome.digits)
                    ),
                    "root_displacement_abs": abs(
                        baseline.omega - leaf.job.root.omega
                    ),
                })
            rows.append(row)
    return tuple(rows)


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
    precision = precision_tier_presentation(outcome.digits)
    result = _component_result(record)
    row.update({
        "component_status": (
            outcome.numerical_state if result is None else result.status.value
        ),
        "precision_digits": outcome.digits,
        "precision_tier": precision.precision_tier,
        "precision_decimal_digits_nominal": (
            str(precision.nominal_decimal_digits)
        ),
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
        **_conditioning_report_fields(result.baseline),
        **_authentication_report_fields(result.baseline),
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
    precision = precision_tier_presentation(stage.outcome.digits)
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
            "precision_tier": precision.precision_tier,
            "precision_decimal_digits_nominal": (
                str(precision.nominal_decimal_digits)
            ),
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


def _resource_failure_rows(
    plan: CampaignPlan,
    summary: object,
    *,
    source_receipt: str,
) -> tuple[Mapping[str, object], ...]:
    attempts = tuple(getattr(summary, "attempts", ()))
    records = tuple(getattr(summary, "records", ()))
    terminal_ids = {
        record.leaf_id
        for record in records
        if record.state in {"PRODUCED", "UNRESOLVED"}
    }
    last_attempt_by_leaf = {
        attempt.leaf_id: attempt.attempt_ordinal for attempt in attempts
    }
    leaf_by_id = {leaf.leaf_id: leaf for leaf in plan.leaves}
    rows: list[Mapping[str, object]] = []
    for attempt in attempts:
        leaf = leaf_by_id[attempt.leaf_id]
        receipt = attempt.failure_receipt
        failure = receipt["failure"]
        if not isinstance(failure, Mapping):
            raise ValueError("campaign resource failure receipt is invalid")
        snapshot = failure.get("ode_snapshot")
        if not isinstance(snapshot, Mapping):
            snapshot = {}
        resource_policy = failure.get("execution_resource_policy")
        if not isinstance(resource_policy, Mapping):
            raise ValueError("campaign resource policy receipt is invalid")
        if attempt.leaf_id in terminal_ids:
            retry_status = "RETRIED_COMPLETED"
        elif last_attempt_by_leaf[attempt.leaf_id] != attempt.attempt_ordinal:
            retry_status = "RETRIED_FAILED"
        else:
            retry_status = "DEFERRED"
        rows.append({
            "attempt_ordinal": attempt.attempt_ordinal,
            "leaf_index": attempt.leaf_index,
            "leaf_id": attempt.leaf_id,
            "mode": leaf.leaf.mode_label,
            "spin_or_Mkappa": float(leaf.leaf.coordinate),
            "mechanism": leaf.mechanism_id,
            "precision_digits": attempt.precision_digits,
            "readout_role": failure.get("readout_role"),
            "phase": failure.get("root_phase"),
            "newton_index": failure.get("newton_index"),
            "determinant_count": (
                failure.get("phase_determinant_index")
                if failure.get("phase_determinant_index") is not None
                else failure.get("determinant_index")
            ),
            "determinant_purpose": failure.get("determinant_purpose"),
            "elapsed_seconds": failure.get("elapsed_request_seconds"),
            "elapsed_phase_seconds": failure.get("elapsed_phase_seconds"),
            "elapsed_leg_seconds": failure.get("elapsed_leg_seconds"),
            "failure_code": attempt.failure_code,
            "limiting_resource": failure.get("limiting_resource"),
            "ode_leg": failure.get("ode_leg") or snapshot.get("ode_leg"),
            "ode_accepted_steps": snapshot.get(
                "ode_accepted_steps", snapshot.get("accepted_steps")
            ),
            "ode_rejected_steps": snapshot.get(
                "ode_rejected_steps", snapshot.get("rejected_steps")
            ),
            "rhs_evaluations": snapshot.get(
                "ode_rhs_evaluations", snapshot.get("rhs_evaluations")
            ),
            "retry_status": retry_status,
            "resource_policy_schema": resource_policy.get("schema"),
            "resource_policy_version": resource_policy.get("version"),
            "resource_policy_sha256": resource_policy.get("sha256"),
            "attempt_sha256": attempt.attempt_sha256,
            "created_at_utc": attempt.created_at_utc,
            "checkpoint_source_receipt": source_receipt,
        })
    return tuple(rows)


def project_campaign_reports(
    plan: CampaignPlan,
    checkpoint_path: str | os.PathLike[str],
    *,
    run_provenance: Mapping[str, str] | None = None,
    include_advanced: bool = True,
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
    precision_stage_rows = _precision_stage_rows(plan, records_by_id)
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
    resource_failure_rows = _resource_failure_rows(
        plan, summary, source_receipt=source_receipt
    )
    if not include_advanced:
        return CampaignReportModel(
            leaf_rows=leaf_rows,
            precision_stage_rows=precision_stage_rows,
            error_channel_rows=error_rows,
            projective_rows=(),
            resource_failure_rows=resource_failure_rows,
            checkpoint_source_receipt=source_receipt,
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
        precision_stage_rows=precision_stage_rows,
        error_channel_rows=error_rows,
        projective_rows=projective_rows,
        resource_failure_rows=resource_failure_rows,
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


def _atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(canonical_json_bytes(value))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    except BaseException:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def _projection_status(
    status: str, error: Exception | None = None
) -> dict[str, object]:
    return {
        "status": status,
        "error_type": None if error is None else type(error).__name__,
        "message": None if error is None else str(error),
    }


def _write_report_status(
    directory: Path,
    checkpoint_source_receipt: str,
    *,
    basic: Mapping[str, object],
    projective: Mapping[str, object],
    triage: Mapping[str, object],
) -> None:
    content: dict[str, object] = {
        "schema": "windows-solver.m02-report-status/v1",
        "checkpoint_source_receipt": checkpoint_source_receipt,
        "basic": dict(basic),
        "projective": dict(projective),
        "triage": dict(triage),
    }
    receipt = {
        **content,
        "receipt_sha256": hashlib.sha256(canonical_json_bytes(content)).hexdigest(),
    }
    _atomic_json(directory / "m02-report-status.json", receipt)


def refresh_campaign_reports(
    plan: CampaignPlan,
    checkpoint_path: str | os.PathLike[str],
    *,
    run_provenance: Mapping[str, str] | None = None,
    advanced_triage: Callable[[CampaignReportModel, Path], None] | None = None,
) -> CampaignReportModel:
    """Refresh basic reports first; contain projective and triage failures."""

    directory = report_directory_for_checkpoint(checkpoint_path)
    try:
        basic_model = project_campaign_reports(
            plan,
            checkpoint_path,
            run_provenance=run_provenance,
            include_advanced=False,
        )
        _atomic_csv(
            directory / "m02-leaves.csv", LEAF_COLUMNS, basic_model.leaf_rows
        )
        _atomic_csv(
            directory / "m02-precision-stages.csv",
            PRECISION_STAGE_COLUMNS,
            basic_model.precision_stage_rows,
        )
        _atomic_csv(
            directory / "m02-error-channels.csv",
            ERROR_CHANNEL_COLUMNS,
            basic_model.error_channel_rows,
        )
        _atomic_csv(
            directory / "m02-resource-failures.csv",
            RESOURCE_FAILURE_COLUMNS,
            basic_model.resource_failure_rows,
        )
    except Exception as error:
        checkpoint_bytes = Path(checkpoint_path).read_bytes()
        source_receipt = "sha256:" + hashlib.sha256(checkpoint_bytes).hexdigest()
        _write_report_status(
            directory,
            source_receipt,
            basic=_projection_status("FAILED", error),
            projective=_projection_status("NOT_RUN"),
            triage=_projection_status("NOT_RUN"),
        )
        raise

    basic_status = _projection_status("COMPLETED")
    projective_status = _projection_status("NOT_RUN")
    triage_status = _projection_status(
        "NOT_CONFIGURED" if advanced_triage is None else "NOT_RUN"
    )
    model = basic_model
    try:
        advanced_model = project_campaign_reports(
            plan,
            checkpoint_path,
            run_provenance=run_provenance,
            include_advanced=True,
        )
        _atomic_csv(
            directory / "m02-projective.csv",
            PROJECTIVE_COLUMNS,
            advanced_model.projective_rows,
        )
        model = advanced_model
        projective_status = _projection_status("COMPLETED")
    except Exception as error:
        projective_status = _projection_status("FAILED", error)

    if advanced_triage is not None and projective_status["status"] == "COMPLETED":
        try:
            advanced_triage(model, directory)
            triage_status = _projection_status("COMPLETED")
        except Exception as error:
            triage_status = _projection_status("FAILED", error)
    elif advanced_triage is not None:
        triage_status = _projection_status("NOT_RUN")

    _write_report_status(
        directory,
        basic_model.checkpoint_source_receipt,
        basic=basic_status,
        projective=projective_status,
        triage=triage_status,
    )
    return model


def _schema11_checkpoint_receipt(checkpoint: Mapping[str, object]) -> str:
    scientific = dict(checkpoint)
    scientific["report_status_receipt"] = None
    return hashlib.sha256(canonical_json_bytes(scientific)).hexdigest()


def _schema11_complex(value: object) -> complex | None:
    if not isinstance(value, Mapping):
        return None
    imaginary = value.get("imaginary", value.get("imag"))
    try:
        result = complex(float(value["real"]), float(imaginary))
    except (KeyError, TypeError, ValueError, OverflowError):
        return None
    return result if math.isfinite(result.real) and math.isfinite(result.imag) else None


def _schema11_record_response(
    record: Mapping[str, object],
) -> tuple[complex | None, float | None]:
    centre = _schema11_complex(record.get("retained_centre"))
    stages = record.get("stages")
    if not isinstance(stages, list) or not stages:
        return centre, None
    stage = stages[-1]
    if not isinstance(stage, Mapping):
        return centre, None
    disk = stage.get("response_disk")
    if isinstance(disk, Mapping):
        centre = centre or _schema11_complex(disk.get("centre"))
        try:
            radius = float(disk["radius"])
        except (KeyError, TypeError, ValueError, OverflowError):
            radius = None
        if radius is not None and (not math.isfinite(radius) or radius < 0):
            radius = None
        return centre, radius
    try:
        parsed = CampaignLeafRecord.from_mapping(record)
        raw = parsed.stages[-1].outcome.component_result.get("result")
        result = ComponentResult.from_mapping(raw) if isinstance(raw, Mapping) else None
    except (TypeError, ValueError):
        result = None
    if result is None:
        return centre, None
    return result.response, sum(result.error_channels.values())


def _schema11_projective_component(
    record: Mapping[str, object],
) -> BoundedComponentEvidence | None:
    """Project one authenticated schema-11 response disk into reducer evidence."""

    if record.get("state") != "PRODUCED":
        return None
    leaf_id = record.get("leaf_id")
    record_sha256 = record.get("record_sha256")
    stages = record.get("stages")
    if (
        not isinstance(leaf_id, str)
        or not isinstance(record_sha256, str)
        or not isinstance(stages, list)
        or not stages
        or not isinstance(stages[-1], Mapping)
    ):
        return None
    centre, radius = _schema11_record_response(record)
    if centre is None or radius is None:
        return None
    stage_sha256 = stages[-1].get("stage_sha256")
    if not isinstance(stage_sha256, str):
        return None
    source_receipt = hashlib.sha256(canonical_json_bytes({
        "record_sha256": record_sha256,
        "stage_sha256": stage_sha256,
    })).hexdigest()
    return BoundedComponentEvidence(
        component_id=leaf_id,
        centre=centre,
        disk_radius=radius,
        units="dimensionless-response",
        source_receipt=source_receipt,
    )


def _schema11_selected_projective_plans(selection: object) -> tuple[object, ...]:
    selected = set(getattr(selection, "leaf_ids"))
    return tuple(
        row
        for row in build_projective_row_plans()
        if selected.intersection((*row.left_component_ids, *row.right_component_ids))
    )


def _schema11_projective_vector_cell(
    component_ids: Sequence[str],
    records: Mapping[str, Mapping[str, object]],
) -> str:
    values = []
    for component_id in component_ids:
        record = records.get(component_id)
        centre, radius = (
            (None, None)
            if record is None else _schema11_record_response(record)
        )
        values.append({
            "component_id": component_id,
            "response_real": None if centre is None else centre.real,
            "response_imaginary": None if centre is None else centre.imag,
            "local_disk_radius": radius,
            "terminal_state": None if record is None else record.get("state"),
        })
    return _json_cell(values)


def _schema11_projective_rows(
    reduction: CampaignReductionSummary,
    records: Mapping[str, Mapping[str, object]],
    *,
    checkpoint_source_receipt: str,
) -> tuple[Mapping[str, object], ...]:
    grams = {
        item.construction_id: item.to_mapping()
        for item in reduction.empirical_grams
    }
    return tuple({
        "row_id": row.row_id,
        "role": row.role,
        "support": row.support_id,
        "mode_order": _json_cell(row.mode_labels),
        "coordinate_role": row.coordinate_role,
        "coordinate_exact": f"{row.coordinate.numerator}/{row.coordinate.denominator}",
        "spin_binary64_hex": row.spin_binary64_hex,
        "left_mechanism": row.left_mechanism_id,
        "right_mechanism": row.right_mechanism_id,
        "left_component_ids": _json_cell(row.left_component_ids),
        "right_component_ids": _json_cell(row.right_component_ids),
        "present_component_ids": _json_cell(result.present_component_ids),
        "missing_component_ids": _json_cell(result.missing_component_ids),
        "produced_unresolved_component_ids": _json_cell(
            result.produced_unresolved_component_ids
        ),
        "left_vector": _schema11_projective_vector_cell(
            row.left_component_ids, records
        ),
        "right_vector": _schema11_projective_vector_cell(
            row.right_component_ids, records
        ),
        "calibration_mode": row.calibration_mode_label,
        "calibration_component_ids": _json_cell(row.calibration_component_ids),
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
        "separation_threshold": row.separation_lower_radians,
        "equivalence_threshold": row.equivalence_upper_radians,
        "calibration_disk_contains_zero": result.calibration_disk_contains_zero,
        "projective_outcome": result.projective_outcome,
        "scientific_state": result.scientific_state,
        "empirical_gram_id": result.empirical_gram_id,
        "empirical_gram": (
            "" if result.empirical_gram_id is None
            else _json_cell(grams[result.empirical_gram_id])
        ),
        "linearized_input_basis": _json_cell(result.linearized_input_basis),
        "linearized_step_policy": (
            "" if result.linearized_step_policy is None
            else _json_cell(result.linearized_step_policy)
        ),
        "linearized_angle_jacobian": _json_cell(
            result.linearized_angle_jacobian
        ),
        "linearized_angle_gram": result.linearized_angle_gram,
        "linearized_angle_columns": _json_cell([
            {"channel_id": channel_id, "signed_angle_delta": value}
            for channel_id, value in result.linearized_angle_columns
        ]),
        "reducer_state": result.reducer_state,
        "reason": result.reason,
        "evidence_ceiling": row.evidence_ceiling,
        "reduction_id": reduction.reduction_id,
        "checkpoint_source_receipt": checkpoint_source_receipt,
    } for row, result in zip(reduction.plans, reduction.results))


def _schema11_stage_tier(stage: Mapping[str, object]) -> str | None:
    tier = stage.get("precision_tier")
    if isinstance(tier, str):
        return tier
    outcome = stage.get("outcome")
    digits = outcome.get("digits") if isinstance(outcome, Mapping) else stage.get("digits")
    if isinstance(digits, int):
        return "binary64" if digits == 64 else f"BF{digits}"
    return None


def _schema11_timing(
    binary: Mapping[str, object] | None,
    promoted: Mapping[str, object] | None,
    retained_promoted_stage: Mapping[str, object] | None = None,
) -> dict[str, float]:
    totals = {"binary64": 0.0, "BF40": 0.0, "BF80": 0.0, "BF120": 0.0}
    for entry in (binary, promoted):
        if not isinstance(entry, Mapping):
            continue
        timing = entry.get("tier_timing")
        if not isinstance(timing, list):
            continue
        for item in timing:
            if not isinstance(item, Mapping) or item.get("tier") not in totals:
                continue
            totals[str(item["tier"])] += float(item["elapsed_seconds"])
    # CALCULATE_ONLY keeps its durable timings inside the retained stage as
    # well as the promoted pass ledger.  Use that authenticated copy only as
    # a fallback so a normal promoted ledger is never counted twice.
    if isinstance(retained_promoted_stage, Mapping):
        timing = retained_promoted_stage.get("tier_timing")
        if isinstance(timing, list):
            for item in timing:
                if (
                    not isinstance(item, Mapping)
                    or item.get("tier") not in totals
                    or totals[str(item["tier"])] != 0.0
                ):
                    continue
                totals[str(item["tier"])] = float(item["elapsed_seconds"])
    return totals


def _schema11_work_counts(
    binary: Mapping[str, object] | None,
    promoted: Mapping[str, object] | None,
    retained_promoted_stage: Mapping[str, object] | None = None,
) -> dict[str, int]:
    totals = {"sample_count": 0, "root_read_count": 0, "worker_launch_count": 0}
    for entry in (binary, promoted):
        if not isinstance(entry, Mapping):
            continue
        for name in totals:
            value = entry.get(name)
            if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                totals[name] += value
    # Admission records a zero-numerics disposition.  Preserve the actual
    # BF40/BF80 work from its retained stage instead of hiding it behind that
    # terminal administrative update.
    if isinstance(retained_promoted_stage, Mapping):
        for name in totals:
            promoted_value = (
                promoted.get(name) if isinstance(promoted, Mapping) else None
            )
            retained_value = retained_promoted_stage.get(name)
            if (
                (promoted_value is None or promoted_value == 0)
                and isinstance(retained_value, int)
                and not isinstance(retained_value, bool)
                and retained_value >= 0
            ):
                totals[name] += retained_value
    return totals


def _schema11_retained_promoted_stages(
    checkpoint: Mapping[str, object],
) -> dict[str, Mapping[str, object]]:
    """Index checkpoint-owned, unadmitted Layer-2 stages by leaf identity."""

    ledger = checkpoint.get("promoted_stage_ledger")
    if not isinstance(ledger, Mapping):
        return {}
    result: dict[str, Mapping[str, object]] = {}
    for bucket in ledger.values():
        if not isinstance(bucket, Mapping):
            continue
        for leaf_id, stage in bucket.items():
            if not isinstance(leaf_id, str) or not isinstance(stage, Mapping):
                continue
            existing = result.get(leaf_id)
            if existing is not None and existing != stage:
                raise ValueError("multiple retained promoted stages for one leaf")
            result[leaf_id] = stage
    return result


def _schema11_admission_state(
    queue_entry: Mapping[str, object] | None,
    retained_stage: Mapping[str, object] | None,
) -> str | None:
    """Project the current queue-owned admission state for retained work."""

    if isinstance(queue_entry, Mapping):
        disposition = queue_entry.get("disposition")
        if disposition == "AWAITING_ADMISSION":
            return "AWAITING_ADMISSION"
        if disposition == "ADMITTED_PENDING_PUBLICATION":
            return "ADMITTED_PENDING_PUBLICATION"
        if disposition == "COMPLETED" and isinstance(retained_stage, Mapping):
            return "ADMITTED"
    if isinstance(retained_stage, Mapping):
        value = retained_stage.get("admission_state")
        return value if isinstance(value, str) else None
    return None


def _schema11_queue_route(queue_entry: Mapping[str, object] | None) -> str | None:
    """Expose the locked route even before its first promoted artifact."""

    if not isinstance(queue_entry, Mapping):
        return None
    tier = queue_entry.get("minimum_requested_tier")
    if tier == "BF40":
        return "EXTERIOR_BF40"
    if tier == "BF80":
        return "HORIZON_BF80"
    return None


def _schema11_normalized_tier(value: object) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    if value == "binary64":
        return value
    normalized = value.upper().replace("BIGFLOAT-", "BF")
    return normalized


def _schema11_retained_precision_tiers(
    stage: Mapping[str, object] | None,
) -> tuple[str, ...]:
    if not isinstance(stage, Mapping):
        return ()
    values = stage.get("precision_tiers")
    if isinstance(values, list):
        tiers = tuple(
            tier
            for value in values
            if (tier := _schema11_normalized_tier(value)) is not None
        )
        if tiers:
            return tiers
    batches = stage.get("raw_promoted_batches")
    if not isinstance(batches, list):
        return ()
    return tuple(
        tier
        for batch in batches
        if isinstance(batch, Mapping)
        and (tier := _schema11_normalized_tier(batch.get("precision_tier")))
        is not None
    )


def _schema11_retained_term_delta(term: Mapping[str, object]) -> complex | None:
    for key in ("signed_delta", "delta", "difference"):
        delta = _schema11_complex(term.get(key))
        if delta is not None:
            return delta
    return None


def _schema11_digest(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _schema11_basic_rows(
    plan: object,
    selection: object,
    checkpoint: Mapping[str, object],
) -> tuple[
    tuple[Mapping[str, object], ...],
    tuple[Mapping[str, object], ...],
    tuple[Mapping[str, object], ...],
    tuple[Mapping[str, object], ...],
]:
    leaf_by_id = {leaf.leaf_id: leaf for leaf in getattr(plan, "leaves")}
    ordered = tuple(getattr(selection, "leaf_ids"))
    record_by_id = {record["leaf_id"]: record for record in checkpoint["records"]}
    evidence = checkpoint["evidence_ledger"]
    binary_ledger = checkpoint["survey_pass_ledger"]["binary64"]
    promoted_ledger = checkpoint["survey_pass_ledger"]["promoted"]
    queue_by_leaf = {
        item["leaf_id"]: item
        for item in checkpoint["promotion_queue"]["entries"]
    }
    retained_stage_by_leaf = _schema11_retained_promoted_stages(checkpoint)
    leaf_rows: list[Mapping[str, object]] = []
    stage_rows: list[Mapping[str, object]] = []
    channel_rows: list[Mapping[str, object]] = []
    for ordinal, leaf_id in enumerate(ordered, start=1):
        leaf = leaf_by_id[leaf_id]
        record = record_by_id.get(leaf_id)
        binary = binary_ledger.get(leaf_id)
        promoted = promoted_ledger.get(leaf_id)
        queue_entry = queue_by_leaf.get(leaf_id)
        retained_stage = retained_stage_by_leaf.get(leaf_id)
        admission_state = _schema11_admission_state(queue_entry, retained_stage)
        evidence_entry = evidence.get(leaf_id)
        centre, radius = (
            (None, None)
            if record is None
            else _schema11_record_response(record)
        )
        magnitude = None if centre is None else abs(centre)
        relative = (
            None
            if magnitude in (None, 0) or radius is None
            else radius / magnitude
        )
        timings = _schema11_timing(binary, promoted, retained_stage)
        work_counts = _schema11_work_counts(binary, promoted, retained_stage)
        stages = [] if record is None else record.get("stages", [])
        last_stage = stages[-1] if isinstance(stages, list) and stages else {}
        retained_tiers = _schema11_retained_precision_tiers(retained_stage)
        precision_tier = (
            _schema11_stage_tier(last_stage)
            if isinstance(last_stage, Mapping) and last_stage
            else (retained_tiers[-1] if retained_tiers else None)
        )
        receipts = (
            evidence_entry.get("receipts", [])
            if isinstance(evidence_entry, Mapping)
            else []
        )
        receipt_sha = None
        if isinstance(receipts, list) and receipts and isinstance(receipts[-1], Mapping):
            receipt_sha = receipts[-1].get("receipt_sha256")
        terminal_state = None if record is None else record["state"]
        if terminal_state is None and isinstance(promoted, Mapping):
            terminal_state = promoted["disposition"]
        if terminal_state is None and isinstance(binary, Mapping):
            terminal_state = binary["disposition"]
        leaf_rows.append({
            "leaf_ordinal": ordinal,
            "leaf_id": leaf_id,
            "role": leaf.role,
            "mode": leaf.leaf.mode_label,
            "spin_or_Mkappa": leaf.job.spin,
            "mechanism": leaf.mechanism_id,
            "numerical_state": terminal_state or "NOT_ATTEMPTED",
            "evidence_level": (
                None if not isinstance(evidence_entry, Mapping)
                else evidence_entry["evidence_level"]
            ),
            "binary64_pass_disposition": (
                None if not isinstance(binary, Mapping) else binary["disposition"]
            ),
            "promoted_pass_disposition": (
                None if not isinstance(promoted, Mapping) else promoted["disposition"]
            ),
            "promoted_route": (
                retained_stage.get("route")
                if isinstance(retained_stage, Mapping)
                else _schema11_queue_route(queue_entry)
            ),
            "admission_state": (
                admission_state
            ),
            "promotion_reason": (
                queue_entry.get("reason_code")
                if isinstance(queue_entry, Mapping)
                else None
            ),
            "execution_profile": (
                "VALIDATE" if isinstance(evidence_entry, Mapping)
                and evidence_entry["evidence_level"] == "VALIDATED"
                else "CERTIFY" if isinstance(evidence_entry, Mapping)
                and evidence_entry["evidence_level"] == "CERTIFIED"
                else "SURVEY"
            ),
            "survey_pass": (
                "promoted" if isinstance(promoted, Mapping)
                else "binary64" if isinstance(binary, Mapping) else None
            ),
            "precision_tier": precision_tier,
            "precision_tiers": (
                _json_cell(retained_tiers)
                if retained_tiers
                else None
            ),
            **work_counts,
            "binary64_seconds": timings["binary64"],
            "bf40_seconds": timings["BF40"],
            "bf80_seconds": timings["BF80"],
            "bf120_seconds": timings["BF120"],
            "total_seconds": sum(timings.values()),
            "response_real": None if centre is None else centre.real,
            "response_imaginary": None if centre is None else centre.imag,
            "response_magnitude": magnitude,
            "response_disk_radius": radius,
            "relative_disk_radius": relative,
            "record_sha256": None if record is None else record["record_sha256"],
            "stage_sha256": (
                last_stage.get("stage_sha256")
                if isinstance(last_stage, Mapping) and last_stage
                else (
                    retained_stage.get("stage_sha256")
                    if isinstance(retained_stage, Mapping)
                    else None
                )
            ),
            "retained_promoted_stage_sha256": (
                retained_stage.get("stage_sha256")
                if isinstance(retained_stage, Mapping)
                else None
            ),
            "receipt_sha256": receipt_sha,
        })
        if isinstance(stages, list):
            for stage_index, stage in enumerate(stages):
                if not isinstance(stage, Mapping):
                    continue
                stage_rows.append({
                    "leaf_ordinal": ordinal,
                    "leaf_id": leaf_id,
                    "stage_index": stage_index,
                    "precision_tier": _schema11_stage_tier(stage),
                    "stage_sha256": stage.get("stage_sha256"),
                    "record_sha256": None if record is None else record["record_sha256"],
                    "stage_source": "TERMINAL_RECORD",
                    "admission_state": "ADMITTED",
                })
                raw_channels = stage.get("signed_error_channels")
                if raw_channels is None and isinstance(stage.get("outcome"), Mapping):
                    raw_channels = stage["outcome"].get("signed_error_channels")
                if not isinstance(raw_channels, list):
                    continue
                for channel_index, channel in enumerate(raw_channels):
                    if not isinstance(channel, Mapping):
                        continue
                    delta = _schema11_complex(channel.get("signed_delta"))
                    channel_rows.append({
                        "leaf_ordinal": ordinal,
                        "leaf_id": leaf_id,
                        "stage_index": stage_index,
                        "channel_index": channel_index,
                        "family": channel.get("family"),
                        "signed_delta_real": None if delta is None else delta.real,
                        "signed_delta_imaginary": None if delta is None else delta.imag,
                        "stage_sha256": stage.get("stage_sha256"),
                        "record_sha256": None if record is None else record["record_sha256"],
                        "stage_source": "TERMINAL_RECORD",
                        "admission_state": "ADMITTED",
                        "disagreement_term_sha256": None,
                    })
        if not isinstance(retained_stage, Mapping):
            continue
        retained_stage_sha256 = retained_stage.get("stage_sha256")
        for stage_index, tier in enumerate(retained_tiers):
            stage_rows.append({
                "leaf_ordinal": ordinal,
                "leaf_id": leaf_id,
                "stage_index": stage_index,
                "precision_tier": tier,
                "stage_sha256": retained_stage_sha256,
                "record_sha256": None,
                "stage_source": "RETAINED_PROMOTED_STAGE",
                "admission_state": admission_state,
            })
        terms = retained_stage.get("current_run_disagreement_terms")
        if not isinstance(terms, list):
            continue
        for channel_index, term in enumerate(terms):
            if not isinstance(term, Mapping):
                continue
            delta = _schema11_retained_term_delta(term)
            channel_rows.append({
                "leaf_ordinal": ordinal,
                "leaf_id": leaf_id,
                "stage_index": 0,
                "channel_index": channel_index,
                "family": term.get("family", term.get("schema", "CURRENT_RUN_DISAGREEMENT")),
                "signed_delta_real": None if delta is None else delta.real,
                "signed_delta_imaginary": None if delta is None else delta.imag,
                "stage_sha256": retained_stage_sha256,
                "record_sha256": None,
                "stage_source": "RETAINED_PROMOTED_STAGE",
                "admission_state": admission_state,
                "disagreement_term_sha256": _schema11_digest(term),
            })
    resolutions = system_failure_resolution_index(checkpoint)
    failures = tuple(
        {
            "failure_ordinal": ordinal,
            "leaf_id": item.get("leaf_id"),
            "failure_code": item.get("failure_code"),
            "cause_type": item.get("cause_type"),
            "fingerprint_sha256": item.get("fingerprint_sha256"),
            "receipt_sha256": item.get("receipt_sha256"),
            "resolution_state": (
                "RESOLVED" if resolution is not None else "ACTIVE"
            ),
            "resolution_receipt_sha256": (
                None if resolution is None else resolution["receipt_sha256"]
            ),
            "resolution_repair_commit_sha": (
                None if resolution is None else resolution["repair_commit_sha"]
            ),
            "resolution_reason": (
                None if resolution is None else resolution["reason"]
            ),
        }
        for ordinal, item in enumerate(checkpoint["system_failures"], start=1)
        for resolution in (resolutions.get(item.get("receipt_sha256")),)
    )
    return tuple(leaf_rows), tuple(stage_rows), tuple(channel_rows), failures


def _schema11_projection_status(
    status: str,
    *,
    timestamp: str,
    paths: Sequence[Path] = (),
    error: Exception | None = None,
) -> dict[str, object]:
    outputs = [{
        "path": str(path),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    } for path in paths if path.is_file()]
    error_receipt = None
    if error is not None:
        error_content = {
            "error_type": type(error).__name__,
            "message": str(error),
        }
        error_receipt = {
            **error_content,
            "receipt_sha256": hashlib.sha256(
                canonical_json_bytes(error_content)
            ).hexdigest(),
        }
    return {
        "status": status,
        "updated_at_utc": timestamp,
        "outputs": outputs,
        "error_receipt": error_receipt,
    }


def write_schema11_projective(
    plan: object,
    selection: object,
    checkpoint: Mapping[str, object],
    directory: Path,
) -> CampaignReductionSummary:
    """Write the authenticated non-release projective reduction before triage."""

    row_plans = _schema11_selected_projective_plans(selection)
    if not row_plans:
        raise ValueError("selected atlas contains no projective row participation")
    records = {
        record["leaf_id"]: record
        for record in checkpoint["records"]
        if isinstance(record, Mapping) and isinstance(record.get("leaf_id"), str)
    }
    required_ids = {
        component_id
        for row in row_plans
        for component_id in (*row.left_component_ids, *row.right_component_ids)
    }
    components = {
        leaf_id: component
        for leaf_id, record in records.items()
        if leaf_id in required_ids
        for component in (_schema11_projective_component(record),)
        if component is not None
    }
    checkpoint_source_receipt = _schema11_checkpoint_receipt(checkpoint)
    reduction = reduce_projective_rows(
        getattr(plan, "campaign_id"),
        tuple(row.row_id for row in row_plans),
        components,
        source_hashes=(checkpoint_source_receipt,),
    )
    _atomic_json(directory / "m02-projective.json", reduction.to_mapping())
    _atomic_csv(
        directory / "m02-projective.csv",
        PROJECTIVE_COLUMNS,
        _schema11_projective_rows(
            reduction,
            records,
            checkpoint_source_receipt=checkpoint_source_receipt,
        ),
    )
    return reduction


def _derive_projective_triage_projection(
    reduction: CampaignReductionSummary,
    *,
    selected_leaf_ids: Sequence[str],
) -> Mapping[str, tuple[float | None, bool]]:
    """Deterministically project completed rows onto each participating leaf.

    Conservative row-minimum aggregation rule:

    - a leaf participates in a row when it is one of that row's left or
      right components;
    - ``projective_angle_lower_bound`` is the minimum
      ``bounded_angle_interval_radians[0]`` across the leaf's participating
      rows, considering only rows with a complete bounded interval; an
      incomplete or unresolvable row is never treated as zero angle and
      never treated as safe, so a leaf whose rows are all incomplete gets
      ``None`` rather than a fabricated bound;
    - ``controls_projective_classification`` is true when the leaf
      participates in any row whose reviewed reducer classification is
      ``SEPARATED`` (the row's conservative angle interval cleared the
      frozen separation threshold, so this leaf's evidence drove a
      scientifically consequential outcome).
    """

    row_by_id = {
        row.row_id: (row, result)
        for row, result in zip(reduction.plans, reduction.results)
    }
    selected = set(selected_leaf_ids)
    rows_by_leaf: dict[str, list[str]] = {}
    for row in reduction.plans:
        for component_id in (*row.left_component_ids, *row.right_component_ids):
            if component_id in selected:
                rows_by_leaf.setdefault(component_id, []).append(row.row_id)
    projections: dict[str, tuple[float | None, bool]] = {}
    for leaf_id, row_ids in rows_by_leaf.items():
        bounds: list[float] = []
        controls = False
        for row_id in row_ids:
            _row, result = row_by_id[row_id]
            interval = result.bounded_angle_interval_radians
            if interval is not None:
                bounds.append(interval[0])
            if result.projective_outcome == "SEPARATED":
                controls = True
        lower = min(bounds) if bounds else None
        projections[leaf_id] = (lower, controls)
    return projections


def refresh_schema11_reports(
    plan: object,
    selection: object,
    checkpoint: Mapping[str, object],
    checkpoint_path: str | os.PathLike[str],
    *,
    basic_writer: Callable[[Path, Mapping[str, object]], None] | None = None,
    advanced_projective: Callable[[Mapping[str, object], Path], None] | None = None,
    advanced_triage: Callable[[Mapping[str, object], Path], None] | None = None,
    persist_checkpoint: bool = True,
) -> dict[str, object]:
    """Atomically project schema-11 basics; contain advanced failures."""

    from .campaign_policy import validate_schema11_checkpoint

    path = Path(checkpoint_path)
    validated = validate_schema11_checkpoint(checkpoint)
    directory = report_directory_for_checkpoint(path)
    timestamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    source_receipt = _schema11_checkpoint_receipt(validated)
    basic_paths = tuple(directory / name for name in (
        "m02-leaves.csv",
        "m02-precision-stages.csv",
        "m02-error-channels.csv",
        "m02-resource-failures.csv",
    ))
    projections: dict[str, object] = {}
    try:
        leaf_rows, stage_rows, channel_rows, failure_rows = _schema11_basic_rows(
            plan, selection, validated
        )
        projections = {
            "leaves": leaf_rows,
            "precision_stages": stage_rows,
            "error_channels": channel_rows,
            "resource_failures": failure_rows,
        }
        if basic_writer is None:
            _atomic_csv(basic_paths[0], SCHEMA11_LEAF_COLUMNS, leaf_rows)
            _atomic_csv(
                basic_paths[1], SCHEMA11_PRECISION_STAGE_COLUMNS, stage_rows
            )
            _atomic_csv(
                basic_paths[2], SCHEMA11_ERROR_CHANNEL_COLUMNS, channel_rows
            )
            _atomic_csv(
                basic_paths[3], SCHEMA11_RESOURCE_FAILURE_COLUMNS, failure_rows
            )
        else:
            basic_writer(directory, projections)
        basic_status = _schema11_projection_status(
            "COMPLETED", timestamp=timestamp, paths=basic_paths
        )
    except Exception as error:
        basic_status = _schema11_projection_status(
            "FAILED", timestamp=timestamp, paths=basic_paths, error=error
        )
        status_content = {
            "schema": "windows-solver.m02-schema11-report-status/v1",
            "checkpoint_source_receipt": source_receipt,
            "basic": basic_status,
            "projective": _schema11_projection_status(
                "NOT_RUN", timestamp=timestamp
            ),
            "triage": _schema11_projection_status("NOT_RUN", timestamp=timestamp),
        }
        status = {
            **status_content,
            "receipt_sha256": hashlib.sha256(
                canonical_json_bytes(status_content)
            ).hexdigest(),
        }
        _atomic_json(directory / "m02-report-status.json", status)
        validated["report_status_receipt"] = status
        if persist_checkpoint:
            _atomic_json(path, validated)
        raise

    def run_advanced(
        callback: Callable[[Mapping[str, object], Path], None] | None,
        output_name: str,
    ) -> dict[str, object]:
        if callback is None:
            return _schema11_projection_status("NOT_CONFIGURED", timestamp=timestamp)
        output = directory / output_name
        try:
            callback(validated, directory)
            return _schema11_projection_status(
                "COMPLETED", timestamp=timestamp, paths=(output,)
            )
        except Exception as error:
            return _schema11_projection_status(
                "FAILED", timestamp=timestamp, paths=(output,), error=error
            )

    projective_status = run_advanced(advanced_projective, "m02-projective.csv")
    triage_status = (
        _schema11_projection_status("NOT_RUN", timestamp=timestamp)
        if advanced_triage is not None and projective_status["status"] == "FAILED"
        else run_advanced(advanced_triage, "m02-triage.json")
    )
    status_content = {
        "schema": "windows-solver.m02-schema11-report-status/v1",
        "checkpoint_source_receipt": source_receipt,
        "basic": basic_status,
        "projective": projective_status,
        "triage": triage_status,
    }
    status = {
        **status_content,
        "receipt_sha256": hashlib.sha256(
            canonical_json_bytes(status_content)
        ).hexdigest(),
    }
    _atomic_json(directory / "m02-report-status.json", status)
    validated["report_status_receipt"] = status
    if persist_checkpoint:
        _atomic_json(path, validated)
    return validate_schema11_checkpoint(validated)


def write_schema11_triage(
    plan: object,
    selection: object,
    checkpoint: Mapping[str, object],
    directory: Path,
) -> None:
    """Write the authenticated mixed-role certification queue after survey."""

    from .campaign_evidence import EvidenceStrengtheningPolicy
    from .campaign_policy import EvidenceLevel
    from .campaign_triage import (
        TriageLeaf,
        TriagePolicy,
        build_whole_atlas_triage,
    )

    leaf_by_id = {leaf.leaf_id: leaf for leaf in getattr(plan, "leaves")}
    records = {record["leaf_id"]: record for record in checkpoint["records"]}
    evidence = checkpoint["evidence_ledger"]
    binary = checkpoint["survey_pass_ledger"]["binary64"]
    promoted = checkpoint["survey_pass_ledger"]["promoted"]
    queue = {
        item["leaf_id"]: item for item in checkpoint["promotion_queue"]["entries"]
    }
    projective_path = directory / "m02-projective.json"
    if not projective_path.is_file():
        raise ValueError("authenticated projective reduction is required before triage")
    try:
        projective = CampaignReductionSummary.from_mapping(
            json.loads(projective_path.read_text(encoding="utf-8"))
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
        raise ValueError("authenticated projective reduction is invalid") from error
    checkpoint_source_receipt = _schema11_checkpoint_receipt(checkpoint)
    if (
        projective.campaign_id != getattr(plan, "campaign_id")
        or projective.source_hashes != (checkpoint_source_receipt,)
    ):
        raise ValueError("projective reduction and triage checkpoint binding differ")
    projective_by_leaf = _derive_projective_triage_projection(
        projective,
        selected_leaf_ids=tuple(getattr(selection, "leaf_ids")),
    )
    leaves = []
    for leaf_id in tuple(getattr(selection, "leaf_ids")):
        leaf = leaf_by_id[leaf_id]
        record = records.get(leaf_id)
        centre, radius = (
            (None, None) if record is None else _schema11_record_response(record)
        )
        ledger = evidence.get(leaf_id)
        binary_entry = binary.get(leaf_id)
        promoted_entry = promoted.get(leaf_id)
        state = None if record is None else record["state"]
        if state is None and isinstance(promoted_entry, Mapping):
            state = promoted_entry["disposition"]
        if state is None and isinstance(binary_entry, Mapping):
            state = binary_entry["disposition"]
        if state not in {"PRODUCED", "UNRESOLVED", "DEFERRED", "REJECTED"}:
            state = "DEFERRED"
        discrepancy_codes = (
            ledger.get("discrepancy_codes", [])
            if isinstance(ledger, Mapping) else []
        )
        queue_entry = queue.get(leaf_id)
        projective_lower, projective_controller = projective_by_leaf.get(
            leaf_id, (None, False)
        )
        leaves.append(TriageLeaf(
            leaf_id=leaf_id,
            role=leaf.role,
            mode_family=leaf.leaf.mode_label,
            mechanism_id=leaf.mechanism_id,
            numerical_state=state,
            evidence_level=(
                None if not isinstance(ledger, Mapping)
                else EvidenceLevel(ledger["evidence_level"])
            ),
            response_magnitude=None if centre is None else abs(centre),
            response_disk_radius=radius,
            binary64_promoted_disagreement=(
                isinstance(binary_entry, Mapping)
                and isinstance(promoted_entry, Mapping)
                and binary_entry.get("result_record_sha256") is not None
                and promoted_entry.get("result_record_sha256") is not None
                and binary_entry["result_record_sha256"]
                != promoted_entry["result_record_sha256"]
            ),
            derivative_disagreement=any(
                "DERIVATIVE" in str(code) for code in discrepancy_codes
            ),
            branch_risk=(
                isinstance(queue_entry, Mapping)
                and queue_entry.get("queue_kind") == "ROOT"
            ),
            near_extremal_support=abs(float(leaf.job.spin)) >= 0.99,
            projective_angle_lower_bound=projective_lower,
            controls_projective_classification=projective_controller,
        ))
    triage = build_whole_atlas_triage(
        checkpoint,
        tuple(leaves),
        triage_policy=TriagePolicy(),
        evidence_policy=EvidenceStrengtheningPolicy.certification(),
        survey_policy_identity=plan.policy.identity_sha256,
        engine_identity=plan.bindings["engine_source_sha256"],
    )
    mapping = triage.to_mapping()
    _atomic_json(directory / "m02-triage.json", mapping)
    _atomic_json(directory / "m02-certification-queue.json", mapping)
