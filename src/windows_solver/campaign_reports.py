"""Disposable human- and machine-readable views of authenticated M02 state.

This module only projects an already committed campaign checkpoint.  It does
not own campaign execution, acceptance, uncertainty construction, or
projective classification.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from decimal import Decimal
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
from .julia_response_backend import promoted_precision_numerical_controls
from .precision_tiers import precision_tier_presentation
from .response_engine import ComponentResult, ERROR_CHANNELS
from .response_reduction import (
    ComputedUnresolvedComponentEvidence,
    ResolvedComponentEvidence,
    SignedErrorContribution,
    build_projective_row_plans,
    reduce_projective_rows,
)
from .campaign_triage import (
    CampaignTriageReport,
    build_campaign_triage,
    write_campaign_triage_report,
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
    "execution_profile",
    "evidence_level",
    "evidence_receipt_count",
    "evidence_discrepancy_codes",
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


@dataclass(frozen=True, slots=True)
class CampaignReportModel:
    """One normalized projection shared by CSV and terminal renderers."""

    leaf_rows: tuple[Mapping[str, object], ...]
    error_channel_rows: tuple[Mapping[str, object], ...]
    projective_rows: tuple[Mapping[str, object], ...]
    checkpoint_source_receipt: str
    precision_stage_rows: tuple[Mapping[str, object], ...] = ()
    resource_failure_rows: tuple[Mapping[str, object], ...] = ()
    triage_report: CampaignTriageReport | None = None


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
        "execution_profile": (
            ""
            if record is None or record.evidence is None
            else record.evidence.execution_profile.value
        ),
        "evidence_level": (
            ""
            if record is None or record.evidence is None
            else record.evidence.evidence_level.value
        ),
        "evidence_receipt_count": (
            0
            if record is None or record.evidence is None
            else len(record.evidence.receipts)
        ),
        "evidence_discrepancy_codes": (
            ""
            if record is None or record.evidence is None
            else _json_cell(record.evidence.discrepancy_codes)
        ),
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
    if not row["execution_profile"]:
        raw_profile = outcome.component_result.get("execution_profile")
        if isinstance(raw_profile, str):
            row["execution_profile"] = raw_profile
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
    semantic_trace = outcome.component_result.get(
        "semantic_precision_tier_trace"
    )
    if (
        isinstance(semantic_trace, list)
        and semantic_trace
        and semantic_trace[-1] in {
            "bigfloat-40", "bigfloat-80", "bigfloat-120"
        }
    ):
        row["precision_tier"] = semantic_trace[-1]
        row["precision_decimal_digits_nominal"] = semantic_trace[-1].rsplit(
            "-", 1
        )[-1]
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
    resource_failure_rows = _resource_failure_rows(
        plan, summary, source_receipt=source_receipt
    )
    triage_report = build_campaign_triage(
        plan,
        summary,
        leaf_rows,
        projective_rows,
        checkpoint_source_receipt=source_receipt,
    )
    return CampaignReportModel(
        leaf_rows=leaf_rows,
        precision_stage_rows=precision_stage_rows,
        error_channel_rows=error_rows,
        projective_rows=projective_rows,
        resource_failure_rows=resource_failure_rows,
        checkpoint_source_receipt=source_receipt,
        triage_report=triage_report,
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
    _atomic_csv(
        directory / "m02-resource-failures.csv",
        RESOURCE_FAILURE_COLUMNS,
        model.resource_failure_rows,
    )
    if model.triage_report is not None:
        write_campaign_triage_report(
            directory / "m02-triage.json", model.triage_report
        )
    return model
