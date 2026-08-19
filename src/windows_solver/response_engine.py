"""Selected linear-response execution behind the unavailable provider.

The engine owns identities, same-equation signed-amplitude refinement, and
authenticated resumability.  Numerical determinant evaluation is injected at
one typed boundary; importing this module cannot start a numerical solve.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal, InvalidOperation, localcontext
from enum import Enum
from fractions import Fraction
from functools import lru_cache
import csv
import hashlib
from importlib import resources
import io
import json
import math
import os
from pathlib import Path
import platform
import re
import sys
import tempfile
import time
from types import MappingProxyType
from typing import Any, Callable, Mapping, Protocol, Sequence

from .contracts import (
    Capability,
    ModeKey,
    StudyRequest,
    canonical_json_bytes,
    canonical_text_sha256,
)
from .linear_response import (
    B_PRIME_RELEASE_DOMAIN,
    BPrimeLeaf,
    baseline_root_reference_id,
)
from .spectrum import (
    PUBLIC_BRANCH_ID,
    PUBLIC_CONVENTION_ID,
    PUBLIC_POLARIZATION_ID,
    PUBLIC_THEORY_ID,
    SpectralCatalogProvider,
    load_spectrum_catalog,
)
from .progress import ProgressEventKind, emit_progress, progress_scope
from .precision_tiers import PrecisionTier, precision_tier, working_precision_bits
from .partial_component_checkpoint import (
    PartialComponentJournal,
    PartialComponentWorkUnit,
)
from .response_uncertainty import (
    ComplexDisk,
    ZeroContainingDiskError,
    exterior_response_disk,
    horizon_response_disk,
)
from .response_ladder_recovery import (
    LadderLevel as RecoveryLadderLevel,
    LadderPolicy as RecoveryLadderPolicy,
    LadderReadout as RecoveryLadderReadout,
    LadderRecoveryResult,
    RecoveryDisposition,
    WindowEvidence,
    WindowLevelEvidence,
    consecutive_windows,
    recover_response_ladder,
)


ENGINE_SCHEMA_VERSION = 1
ENGINE_EQUATION_ID = "same-equation-complex-amplitude-root-readout-" + "v" + str(1)
ROOT_BRANCH_CONTINUATION_TOLERANCE_ABS = 5.0e-3
_HEX_40 = re.compile(r"[0-9a-f]{40}")
_EXTERIOR_PROFILE_IDS: Mapping[str, str] = {
    "exterior-fixed-r3": "fixed-r3",
    "exterior-light-ring": "light-ring",
    "exterior-throat-kappa": "throat-kappa",
    "exterior-alpha-zero": "alpha-zero",
    "exterior-alpha-half": "alpha-half",
    "exterior-alpha-one": "alpha-one",
}
ERROR_CHANNELS = (
    "signed-root",
    "truncation",
    "resolution",
    "seed-path",
    "axis",
    "amplitude",
)
_RECORDED_ROOT_MAPPING_TOLERANCE_ABS = 5.0e-9
_DIAGNOSTIC_ROOT_FAMILIES = ("truncation", "resolution", "seed-path")
_PROMOTED_FIXED_ROOT_DIAGNOSTIC_FAMILIES = ("truncation", "resolution")
# Four levels are the fewest the Richardson/holdout estimate and the observed
# order ratios can be built from, so they are also the fewest a recovered
# window may contain.
LADDER_WINDOW_MINIMUM_LEVELS = 4
RESOLVED_WINDOW_RECOVERY_POLICY = (
    "finest-resolved-consecutive-epsilon-window/v1"
)
RESOLVED_WINDOW_EXCLUSION_REASON = "SIGNAL_BELOW_ROOT_NOISE_FLOOR"
AMPLITUDE_EXPANSION_RECOVERY_POLICY = (
    "coarser-amplitude-expansion-with-resolved-window/v1"
)
AMPLITUDE_EXPANSION_GROWTH = 2.0
AMPLITUDE_EXPANSION_MAXIMUM_LEVELS = 3
NUMERICAL_CONDITIONING_SCHEMA = "windows-solver.m02-conditioning/3"
HISTORICAL_NUMERICAL_CONDITIONING_SCHEMA = (
    "windows-solver.m02-conditioning/2"
)
PROMOTED_ROOT_READOUT_POLICY = (
    "binary64-parity-primary-fixed-root-diagnostics-frequency-disk/v2"
)
HISTORICAL_PROMOTED_ROOT_READOUT_POLICY = (
    "binary64-parity-primary-fixed-root-diagnostics/v1"
)
PROMOTED_ROOT_ACCEPTANCE_METRIC = (
    "abs-determinant-over-abs-complex-derivative/v1"
)
PROMOTED_HORIZON_COMPONENT_IDENTITY = (
    "single-promoted-root-analytic-horizon-component/v1"
)
PROMOTED_HORIZON_RESPONSE_METHOD = (
    "analytic-horizon-from-promoted-primary-derivative/v1"
)
PROMOTED_HORIZON_COMPONENT_V2_IDENTITY = (
    "single-promoted-root-bounded-analytic-horizon-component/v2"
)
PROMOTED_HORIZON_RESPONSE_METHOD_V2 = (
    "bounded-analytic-horizon-from-promoted-primary-derivative/v2"
)
PROMOTED_HORIZON_UNCERTAINTY_DERIVATION_IDENTITY = (
    "primary-root-controls-and-derivative-disk/v1"
)
UNCALIBRATED_ANALYTIC_RESPONSE = "UNCALIBRATED_ANALYTIC_RESPONSE"
BOUNDED_ANALYTIC_RESPONSE = "BOUNDED_ANALYTIC_RESPONSE"
UNBOUNDED_ANALYTIC_RESPONSE = "UNBOUNDED_ANALYTIC_RESPONSE"
BOUNDED_DERIVATIVE_RESPONSE = "BOUNDED_DERIVATIVE_RESPONSE"
UNBOUNDED_DERIVATIVE_RESPONSE = "UNBOUNDED_DERIVATIVE_RESPONSE"
FIXED_ROOT_DERIVATIVE_CONDITIONING_IDENTITY = (
    "fixed-root-h-h2-conditioning/v1"
)
EXTERIOR_DERIVATIVE_COMPONENT_IDENTITY = (
    "fixed-root-exterior-derivative-component/v1"
)
EXTERIOR_DERIVATIVE_RESPONSE_DISK_IDENTITY = (
    "exterior-derivative-response-disk/v1"
)
EXTERIOR_DERIVATIVE_METHOD = "direct-fixed-root-determinant-derivative/v1"
FIXED_ROOT_AXIS_VALIDATION_IDENTITY = "fixed-root-holomorphic-axis-validation/v1"
FULL_COMPLEX_LADDER_VALIDATION_IDENTITY = "full-complex-ladder-validation/v1"
FULL_LADDER_VALIDATION_REASONS = frozenset({
    "RISK_SELECTED_SENTINEL",
    "DERIVATIVE_DISAGREEMENT",
    "PUBLICATION_VALIDATION",
})
DETERMINANT_ERROR_AVAILABLE = "available/v1"
DETERMINANT_ERROR_UNAVAILABLE = "unavailable/v1"
EXTERIOR_DETERMINANT_ERROR_MATH_REVIEW_BLOCKER = (
    "TODO: [HUMAN MATH REVIEW REQUIRED - fixed-root exterior determinant "
    "error model is unavailable]"
)
WORKER_RESPONSE_RECEIPT_SCHEMA = "windows-solver.worker-response-receipt/3"
PREVIOUS_WORKER_RESPONSE_RECEIPT_SCHEMA = (
    "windows-solver.worker-response-receipt/2"
)
HISTORICAL_WORKER_RESPONSE_RECEIPT_SCHEMA = (
    "windows-solver.worker-response-receipt/1"
)
# The promoted worker's root-readout wire schema. Version 4 added the
# root_authentication record. Version 5 records each diagnostic phase's
# correction/error evidence and workflow role. Version 6 identifies staged
# versus escalated authentication and represents unexecuted 2h/ih derivative
# directions explicitly as absent. Version 7 replaces promoted acceptance with
# binary64-parity PRIMARY Newton and fixed-root TRUNCATION/RESOLUTION evidence.
# Version 8 added frequency-disk derivative authentication. Version 9 persists
# every successful adaptive horizon endpoint search in the sealed response.
# Error responses remain independently versioned at 1.
WORKER_RESPONSE_WIRE_SCHEMA = 9
HISTORICAL_WORKER_RESPONSE_WIRE_SCHEMAS = frozenset({3, 4, 5, 6, 7, 8})
_ROOT_AUTHENTICATION_WIRE_SCHEMAS = frozenset({4, 5, 6})
_HISTORICAL_WORKER_RESPONSE_RECEIPT_FIELDS = frozenset({
    "schema",
    "request_binding",
    "request_sha256",
    "scientific_runtime_sha256",
    "worker_response_schema_version",
    "root_residual_abs_text",
    "raw_determinant_abs_text",
    "raw_determinant_evidence_status",
    "receipt_sha256",
})
_PREVIOUS_WORKER_RESPONSE_RECEIPT_FIELDS = (
    _HISTORICAL_WORKER_RESPONSE_RECEIPT_FIELDS | {
        "promoted_root_readout_policy",
        "primary_acceptance_sha256",
    }
)
_WORKER_RESPONSE_RECEIPT_FIELDS = _PREVIOUS_WORKER_RESPONSE_RECEIPT_FIELDS | {
    "horizon_endpoint_search_evidence",
}
_HEX_64 = re.compile(r"[0-9a-f]{64}")
HORIZON_DETERMINANT_FAMILY = "horizon-scattering/v1"
EXTERIOR_DETERMINANT_FAMILY = "exterior-wronskian/v1"
HORIZON_SCATTERING_COLUMN_CONVENTION = (
    "column1=horizon-ingoing-Cref;column2=horizon-outgoing-Cinc/v1"
)
HORIZON_DETERMINANT_CONVENTION = "cinc-over-cref-minus-R/v1"
EXTERIOR_DETERMINANT_CONVENTION = (
    "wronskian-perturbed-Xin-with-Xup/v1"
)
HORIZON_DETERMINANT_NORMALISATION = (
    "cinc-over-cref-minus-reflectivity/v1"
)
EXTERIOR_DETERMINANT_NORMALISATION = (
    "unit-asymptotic-branch-wronskian/v1"
)

# Horizon-side identities for the verified three-leg basis. These are new
# identities rather than revisions of the old ones because the calculation they
# describe is different: three independent legs on a contour that provably
# approaches r_plus, versus one propagated solution carried down a contour that
# does not.
HORIZON_HOMOGENEOUS_REPRESENTATION = (
    "factored-three-leg-horizon-basis-at-match-gsn/v1"
)
REAL_INNER_HORIZON_CONTOUR = "real-inner-tortoise-contour/v1"
HORIZON_BASIS_AT_MATCH_EXTRACTION = "scaled-horizon-basis-at-match/v1"
VERIFIED_ENDPOINT_ERROR_MODEL = (
    "verified-endpoint-control-equivalence-absolute-error/v2"
)
PROMOTED_CONTROL_PROFILE_LABEL = "provisional promoted control profile"
PROMOTED_CONTROL_PROFILE_CALIBRATION_STATUS = "UNMEASURED"

_REGULARISED_GSN_COMMON_IDENTITIES: Mapping[str, str] = MappingProxyType({
    "homogeneous_representation": "factored-plane-wave-gsn/v1",
    "branch_convention": "gsn-complex-rho/v1",
    "radial_derivative_convention": "state2=dX/drho/v1",
    "regular_remainder_contract": "known-carrier-times-regular-remainder/v1",
    "factored_remainder_state_convention": "state1=Y;state2=dY/drho/v1",
})
REGULARISED_GSN_CONDITIONING_IDENTITIES: Mapping[str, object] = MappingProxyType({
    **_REGULARISED_GSN_COMMON_IDENTITIES,
    "homogeneous_representation": HORIZON_HOMOGENEOUS_REPRESENTATION,
    "determinant_family": HORIZON_DETERMINANT_FAMILY,
    "scattering_diagnostics_applicable": True,
    "scattering_column_convention": HORIZON_SCATTERING_COLUMN_CONVENTION,
    "determinant_convention": HORIZON_DETERMINANT_CONVENTION,
    "determinant_normalisation": HORIZON_DETERMINANT_NORMALISATION,
})
_REGULARISED_GSN_COMMON_PRECISION_POLICY: Mapping[str, object] = MappingProxyType({
    "promoted_root_readout_policy": PROMOTED_ROOT_READOUT_POLICY,
    "homogeneous_representation": "factored-plane-wave-gsn/v1",
    "asymptotic_series_evaluation": "typed-batch-horner-compensated/v1",
    "conditioning_diagnostics": "series-recurrence-basis-fd/v1",
    "branch_convention": "gsn-complex-rho/v1",
    "radial_derivative_convention": "state2=dX/drho/v1",
    "regular_remainder_contract": "known-carrier-times-regular-remainder/v1",
    "factored_remainder_state_convention": "state1=Y;state2=dY/drho/v1",
    "reliable_digit_safety_margin": "8",
    "required_digit_guard": "6",
    "human_math_review_receipt_status": "absent-unapproved/v1",
    "human_math_review_receipt_sha256": None,
    "independent_reference_fixture_receipt_status": "absent-unreviewed/v1",
    "independent_reference_fixture_receipt_sha256": None,
})
REGULARISED_GSN_PRECISION_POLICY: Mapping[str, object] = MappingProxyType({
    **_REGULARISED_GSN_COMMON_PRECISION_POLICY,
    "homogeneous_representation": HORIZON_HOMOGENEOUS_REPRESENTATION,
    "determinant_family": HORIZON_DETERMINANT_FAMILY,
    "scattering_diagnostics_applicable": True,
    "scattering_coefficient_extraction": HORIZON_BASIS_AT_MATCH_EXTRACTION,
    "horizon_determinant_chart": "cinc-over-cref-minus-reflectivity/v1",
    "scattering_chart_safety_factor": "64",
    "scattering_column_convention": HORIZON_SCATTERING_COLUMN_CONVENTION,
    "determinant_convention": HORIZON_DETERMINANT_CONVENTION,
    "determinant_normalisation": HORIZON_DETERMINANT_NORMALISATION,
    "horizon_contour": REAL_INNER_HORIZON_CONTOUR,
    "determinant_error_model": VERIFIED_ENDPOINT_ERROR_MODEL,
    "control_profile_label": PROMOTED_CONTROL_PROFILE_LABEL,
    "calibration_status": PROMOTED_CONTROL_PROFILE_CALIBRATION_STATUS,
})


def regularised_gsn_mechanism_contract(
    mechanism_id: str,
) -> Mapping[str, object]:
    """Return the determinant identities applicable to one physical mechanism."""

    if mechanism_id == "horizon-admittance":
        return MappingProxyType({
            "determinant_family": HORIZON_DETERMINANT_FAMILY,
            "scattering_diagnostics_applicable": True,
            "scattering_column_convention": HORIZON_SCATTERING_COLUMN_CONVENTION,
            "determinant_convention": HORIZON_DETERMINANT_CONVENTION,
            "determinant_normalisation": HORIZON_DETERMINANT_NORMALISATION,
        })
    if mechanism_id in _EXTERIOR_PROFILE_IDS:
        return MappingProxyType({
            "determinant_family": EXTERIOR_DETERMINANT_FAMILY,
            "scattering_diagnostics_applicable": False,
            "scattering_column_convention": None,
            "determinant_convention": EXTERIOR_DETERMINANT_CONVENTION,
            "determinant_normalisation": EXTERIOR_DETERMINANT_NORMALISATION,
        })
    raise ValueError(f"unsupported response mechanism: {mechanism_id}")


def regularised_gsn_precision_policy(
    mechanism_id: str,
) -> Mapping[str, object]:
    """Bind precision controls to the determinant family actually evaluated.

    The horizon family carries its own homogeneous-representation identity: it
    no longer propagates one solution through a mixed match-to-inner leg, but
    builds a genuine solution basis from three independent legs seeded on a
    verified real-inner contour. Receipts written under the previous horizon
    identities describe a different calculation and are correctly treated as
    stale.

    The determinant-family identities remain mechanism-scoped. The promoted
    root-readout identity is intentionally common to both families, because
    binary64-parity PRIMARY acceptance and fixed-root diagnostics change how
    every promoted result is accepted and recorded even when the underlying
    exterior determinant mathematics is unchanged. Pre-policy receipts for
    both families are therefore stale by construction.

    Hence ``horizon_contour`` and ``determinant_error_model``, both introduced
    by this rewrite, appear only under the mechanism they describe. Adding them
    as ``None`` to the exterior policy would be the same category error stated
    twice: it claims the exterior mechanism has a horizon contour whose value
    happens to be nothing, and it invalidates receipts to say so.

    The older mechanism-specific keys (``scattering_coefficient_extraction``,
    ``horizon_determinant_chart``, ``scattering_chart_safety_factor``) do carry
    an explicit ``None`` on the exterior side. They are kept exactly as they
    are for the same reason the new ones are omitted: they are already part of
    ``main``'s exterior policy, and normalising them now would break the very
    compatibility this function exists to preserve.
    """

    contract = regularised_gsn_mechanism_contract(mechanism_id)
    horizon = contract["scattering_diagnostics_applicable"] is True
    horizon_only: dict[str, object] = (
        {
            "horizon_contour": REAL_INNER_HORIZON_CONTOUR,
            "determinant_error_model": VERIFIED_ENDPOINT_ERROR_MODEL,
            "control_profile_label": PROMOTED_CONTROL_PROFILE_LABEL,
            "calibration_status": PROMOTED_CONTROL_PROFILE_CALIBRATION_STATUS,
        }
        if horizon
        else {}
    )
    return MappingProxyType({
        **_REGULARISED_GSN_COMMON_PRECISION_POLICY,
        **contract,
        "homogeneous_representation": (
            HORIZON_HOMOGENEOUS_REPRESENTATION
            if horizon
            else _REGULARISED_GSN_COMMON_PRECISION_POLICY[
                "homogeneous_representation"
            ]
        ),
        "scattering_coefficient_extraction": (
            HORIZON_BASIS_AT_MATCH_EXTRACTION if horizon else None
        ),
        "horizon_determinant_chart": (
            "cinc-over-cref-minus-reflectivity/v1" if horizon else None
        ),
        "scattering_chart_safety_factor": "64" if horizon else None,
        **horizon_only,
    })

_NUMERICAL_CONDITIONING_DECIMAL_FIELDS = (
    "maximum_series_digits_lost",
    "maximum_recurrence_digits_lost",
    "maximum_series_evaluation_spread",
    "maximum_last_term_ratio",
    "minimum_asymptotic_predicted_reliable_digits",
    "maximum_basis_condition",
    "maximum_basis_backward_error",
    "maximum_matching_reconstruction_residual",
    "maximum_endpoint_reconstruction_error",
    "maximum_fd_digits_lost",
    "predicted_reliable_digits",
    "required_reliable_digits",
    "minimum_cref_chart_margin",
    "maximum_carrier_change_error",
    "maximum_contour_angle_deformation",
)
_HORIZON_SCATTERING_DECIMAL_FIELDS = frozenset({
    "maximum_basis_condition",
    "maximum_basis_backward_error",
    "maximum_matching_reconstruction_residual",
    "minimum_cref_chart_margin",
    "maximum_carrier_change_error",
})
_NUMERICAL_CONDITIONING_IDENTITY_FIELDS = (
    "determinant_family",
    "homogeneous_representation",
    "branch_convention",
    "scattering_column_convention",
    "radial_derivative_convention",
    "determinant_convention",
    "determinant_normalisation",
    "regular_remainder_contract",
    "factored_remainder_state_convention",
)
_NUMERICAL_CONDITIONING_GATE_FIELDS = (
    "human_math_review_receipt_status",
    "human_math_review_receipt_sha256",
    "independent_reference_fixture_receipt_status",
    "independent_reference_fixture_receipt_sha256",
)
_NUMERICAL_CONDITIONING_SIGNED_DECIMAL_FIELDS = frozenset({
    "minimum_asymptotic_predicted_reliable_digits",
    "predicted_reliable_digits",
})
_NUMERICAL_CONDITIONING_BOOLEAN_FIELDS = (
    "endpoint_remainders_regular",
    "precision_limited",
    "asymptotic_preflight_avoided_ode",
)
_HORIZON_ENDPOINT_ORDER_LIMITED = "insufficient-series-order/" + "v" + "1"
_HORIZON_ENDPOINT_PRECISION_LIMITED = (
    "insufficient-arithmetic-precision/" + "v" + "1"
)
_HORIZON_ENDPOINT_GEOMETRY_LIMITED = (
    "insufficient-geometric-depth/" + "v" + "1"
)


def _conditioning_decimal_from_text(value: object, subject: str) -> Decimal:
    if not isinstance(value, str) or not value or value.strip() != value:
        raise ValueError(f"{subject} must be precision-preserving decimal text")
    try:
        converted = Decimal(value)
    except InvalidOperation as error:
        raise ValueError(f"{subject} must be decimal text") from error
    if not converted.is_finite():
        raise ValueError(f"{subject} must be finite")
    return converted


def _sha256(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _validated_successful_horizon_endpoint_search_evidence(
    value: object,
    request_binding: Mapping[str, object],
    *,
    expected_outcome: str = "adequate/v1",
    required_selected_count: int = 2,
    allow_historical_schema7_policy: bool = False,
    require_complete_candidate_schedule: bool = True,
) -> list[dict[str, object]]:
    """Authenticate persisted successful adaptive endpoint selections."""

    if not isinstance(value, list) or not value:
        raise ValueError("horizon endpoint search evidence is missing")
    canonical = json.loads(canonical_json_bytes(value))
    if not isinstance(canonical, list):
        raise ValueError("horizon endpoint search evidence is invalid")
    evidence_fields = {
        "outcome",
        "policy_identity",
        "selected_pair",
        "rejected_candidates",
        "endpoint_orders",
        "homogeneous_rhs_evaluations_before_pair",
    }
    historical_candidate_fields = {
        "rho",
        "endpoint_order",
        "ingoing_best_prefix_order",
        "outgoing_best_prefix_order",
        "ingoing_adequate",
        "outgoing_adequate",
    }
    candidate_fields = historical_candidate_fields | {
        "attempted_endpoint_order",
        "limitation",
        "limitation_conditioning",
        "precision_limited",
    }
    limitation_conditioning_fields = {
        "binding_predicted_reliable_digits",
        "maximum_last_term_ratio",
        "maximum_recurrence_digits_lost",
        "maximum_series_evaluation_digits_lost",
        "maximum_truncation_digits_lost",
    }

    policy = request_binding.get("policy")
    if not isinstance(policy, Mapping):
        raise ValueError("horizon endpoint request policy is missing")
    try:
        base_order = policy["endpoint_series_order"]
        if allow_historical_schema7_policy:
            policy_identity = policy.get(
                "horizon_endpoint_recovery_policy_identity",
                "adaptive-horizon-endpoint-recovery/v1",
            )
            maximum_order = policy.get(
                "horizon_endpoint_maximum_order", 4 * base_order
            )
            prefix_minimum = policy.get(
                "horizon_endpoint_prefix_minimum_order", 4
            )
            prefix_step = policy.get("horizon_endpoint_prefix_order_step", 4)
        else:
            policy_identity = policy[
                "horizon_endpoint_recovery_policy_identity"
            ]
            maximum_order = policy["horizon_endpoint_maximum_order"]
            prefix_minimum = policy["horizon_endpoint_prefix_minimum_order"]
            prefix_step = policy["horizon_endpoint_prefix_order_step"]
        rho_floor = _conditioning_decimal_from_text(
            policy["horizon_endpoint_rho_floor"], "horizon endpoint rho floor"
        )
        contour_floor = _conditioning_decimal_from_text(
            policy["horizon_rho_inner_min"], "horizon inner contour floor"
        )
        rho_schedule = [
            _conditioning_decimal_from_text(item, "horizon endpoint rho candidate")
            for item in policy["horizon_endpoint_rho_candidates"]
        ]
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("horizon endpoint request policy is invalid") from error
    if (
        not isinstance(policy_identity, str)
        or not policy_identity
        or any(
            isinstance(item, bool) or not isinstance(item, int) or item < 1
            for item in (base_order, maximum_order, prefix_minimum, prefix_step)
        )
        or maximum_order < base_order
        or rho_floor >= 0
        or contour_floor != rho_floor
        or not rho_schedule
        or any(rho >= 0 or rho < rho_floor for rho in rho_schedule)
        or len(rho_schedule) != len(set(rho_schedule))
    ):
        raise ValueError("horizon endpoint request policy is invalid")
    while min(rho_schedule) > rho_floor:
        current = min(rho_schedule)
        for _ in range(2):
            current *= Decimal(3) / Decimal(2)
            if current < rho_floor:
                current = rho_floor
            if current not in rho_schedule:
                rho_schedule.append(current)
            if current == rho_floor:
                break
    expected_rho_schedule = tuple(rho_schedule)
    expected_rhos = frozenset(expected_rho_schedule)
    expected_orders: list[int] = []
    order = base_order
    while order < maximum_order:
        expected_orders.append(order)
        order += order
    expected_orders.append(maximum_order)

    def allowed_prefix_orders(maximum: int) -> frozenset[int]:
        values = list(range(prefix_minimum, maximum + 1, prefix_step))
        if not values or values[-1] != maximum:
            values.append(maximum)
        return frozenset(values)

    def candidate(
        item: object, *, selected: bool
    ) -> tuple[Decimal, int | None]:
        expected_fields = (
            historical_candidate_fields
            if allow_historical_schema7_policy
            else candidate_fields
        )
        if not isinstance(item, dict) or set(item) != expected_fields:
            raise ValueError("horizon endpoint candidate evidence is invalid")
        try:
            rho = _conditioning_decimal_from_text(
                item["rho"], "horizon endpoint candidate rho"
            )
        except ValueError as error:
            raise ValueError(
                "horizon endpoint candidate evidence is invalid"
            ) from error
        best_order = item["endpoint_order"]
        attempted_order = (
            best_order
            if allow_historical_schema7_policy
            else item["attempted_endpoint_order"]
        )
        candidate_prefix_orders = (
            item["ingoing_best_prefix_order"],
            item["outgoing_best_prefix_order"],
        )
        if (
            rho not in expected_rhos
            or (
                attempted_order is not None
                and (
                    isinstance(attempted_order, bool)
                    or not isinstance(attempted_order, int)
                    or attempted_order not in expected_orders
                )
            )
            or (selected and attempted_order is None)
            or (
                best_order is not None
                and (
                    isinstance(best_order, bool)
                    or not isinstance(best_order, int)
                    or attempted_order is None
                    or best_order not in allowed_prefix_orders(
                        attempted_order
                    )
                )
            )
            or any(
                value is not None
                and (
                    isinstance(value, bool)
                    or not isinstance(value, int)
                    or attempted_order is None
                    or value not in allowed_prefix_orders(attempted_order)
                )
                for value in candidate_prefix_orders
            )
            or (
                attempted_order is None
                and any(value is not None for value in candidate_prefix_orders)
            )
            or (
                best_order is None
                and any(value is not None for value in candidate_prefix_orders)
            )
            or (
                not allow_historical_schema7_policy
                and best_order is not None
                and (
                    any(value is None for value in candidate_prefix_orders)
                    or best_order != max(candidate_prefix_orders)
                )
            )
            or type(item["ingoing_adequate"]) is not bool
            or type(item["outgoing_adequate"]) is not bool
            or (
                selected
                and (
                    item["ingoing_adequate"] is not True
                    or item["outgoing_adequate"] is not True
                    or any(value is None for value in candidate_prefix_orders)
                )
            )
        ):
            raise ValueError("horizon endpoint candidate evidence is invalid")
        if not allow_historical_schema7_policy:
            limitation = item["limitation"]
            precision_limited = item["precision_limited"]
            limitation_conditioning = item["limitation_conditioning"]
            allowed_limitations = {
                "adequate/v1",
                _HORIZON_ENDPOINT_ORDER_LIMITED,
                _HORIZON_ENDPOINT_PRECISION_LIMITED,
                _HORIZON_ENDPOINT_GEOMETRY_LIMITED,
            }
            both_adequate = (
                item["ingoing_adequate"] is True
                and item["outgoing_adequate"] is True
            )
            if (
                not isinstance(limitation_conditioning, dict)
                or set(limitation_conditioning)
                != limitation_conditioning_fields
            ):
                raise ValueError(
                    "horizon endpoint limitation conditioning is invalid"
                )
            raw_conditioning = tuple(limitation_conditioning.values())
            if both_adequate or attempted_order is None:
                if any(value is not None for value in raw_conditioning):
                    raise ValueError(
                        "horizon endpoint limitation conditioning is invalid"
                    )
                recomputed_limitation = (
                    "adequate/v1" if both_adequate
                    else _HORIZON_ENDPOINT_GEOMETRY_LIMITED
                )
            elif all(value is None for value in raw_conditioning):
                recomputed_limitation = _HORIZON_ENDPOINT_GEOMETRY_LIMITED
            elif any(value is None for value in raw_conditioning):
                raise ValueError(
                    "horizon endpoint limitation conditioning is incomplete"
                )
            else:
                try:
                    predicted = _conditioning_decimal_from_text(
                        limitation_conditioning[
                            "binding_predicted_reliable_digits"
                        ],
                        "horizon endpoint binding reliable digits",
                    )
                    last_term_ratio = _conditioning_decimal_from_text(
                        limitation_conditioning[
                            "maximum_last_term_ratio"
                        ],
                        "horizon endpoint maximum last-term ratio",
                    )
                    recurrence_loss = _conditioning_decimal_from_text(
                        limitation_conditioning[
                            "maximum_recurrence_digits_lost"
                        ],
                        "horizon endpoint recurrence digits lost",
                    )
                    evaluation_loss = _conditioning_decimal_from_text(
                        limitation_conditioning[
                            "maximum_series_evaluation_digits_lost"
                        ],
                        "horizon endpoint evaluation digits lost",
                    )
                    truncation_loss = _conditioning_decimal_from_text(
                        limitation_conditioning[
                            "maximum_truncation_digits_lost"
                        ],
                        "horizon endpoint truncation digits lost",
                    )
                except ValueError as error:
                    raise ValueError(
                        "horizon endpoint limitation conditioning is invalid"
                    ) from error
                if (
                    not predicted.is_finite()
                    or any(value < 0 for value in (
                        last_term_ratio,
                        recurrence_loss,
                        evaluation_loss,
                        truncation_loss,
                    ))
                ):
                    raise ValueError(
                        "horizon endpoint limitation conditioning is invalid"
                    )
                if last_term_ratio >= 1:
                    recomputed_limitation = _HORIZON_ENDPOINT_GEOMETRY_LIMITED
                elif recurrence_loss + evaluation_loss >= truncation_loss:
                    recomputed_limitation = _HORIZON_ENDPOINT_PRECISION_LIMITED
                else:
                    recomputed_limitation = _HORIZON_ENDPOINT_ORDER_LIMITED
            if (
                limitation not in allowed_limitations
                or type(precision_limited) is not bool
                or limitation != recomputed_limitation
                or precision_limited
                is not (
                    recomputed_limitation
                    == _HORIZON_ENDPOINT_PRECISION_LIMITED
                )
                or (
                    attempted_order is None
                    and (
                        limitation != _HORIZON_ENDPOINT_GEOMETRY_LIMITED
                        or precision_limited is not False
                        or best_order is not None
                        or item["ingoing_adequate"] is not False
                        or item["outgoing_adequate"] is not False
                    )
                )
            ):
                raise ValueError(
                    "horizon endpoint candidate limitation is invalid"
                )
        return rho, attempted_order

    for item in canonical:
        if not isinstance(item, dict) or set(item) != evidence_fields:
            raise ValueError("horizon endpoint search evidence is invalid")
        selected_pair = item["selected_pair"]
        rejected = item["rejected_candidates"]
        orders = item["endpoint_orders"]
        if (
            item["outcome"] != expected_outcome
            or item["policy_identity"] != policy_identity
            or not isinstance(selected_pair, list)
            or len(selected_pair) != required_selected_count
            or not isinstance(rejected, list)
            or not isinstance(orders, list)
            or not orders
            or any(
                isinstance(order, bool)
                or not isinstance(order, int)
                or order < 1
                for order in orders
            )
            or orders != expected_orders
            or item["homogeneous_rhs_evaluations_before_pair"] != 0
        ):
            raise ValueError("horizon endpoint search evidence is invalid")
        selected_identities = [
            candidate(raw, selected=True) for raw in selected_pair
        ]
        rejected_identities = [
            candidate(raw, selected=False) for raw in rejected
        ]
        identities = selected_identities + rejected_identities
        if len(identities) != len(set(identities)):
            raise ValueError("horizon endpoint candidates are not unique")
        if allow_historical_schema7_policy:
            continue
        if not require_complete_candidate_schedule:
            if selected_pair or rejected:
                raise ValueError(
                    "horizon coordinate failure carries endpoint trials"
                )
            continue

        candidate_by_identity = {
            identity: raw
            for identity, raw in zip(
                identities, (*selected_pair, *rejected), strict=True
            )
        }
        observed_rhos = {rho for rho, _ in identities}
        if observed_rhos != expected_rhos:
            raise ValueError("horizon endpoint candidate schedule is incomplete")

        invalid_rhos: set[Decimal] = set()
        verified_by_rho: dict[Decimal, dict[str, object]] = {}
        last_order_by_rho: dict[Decimal, int] = {}
        for rho in expected_rho_schedule:
            rho_trials = [
                (order, candidate_by_identity[(candidate_rho, order)])
                for candidate_rho, order in identities
                if candidate_rho == rho
            ]
            invalid = [trial for order, trial in rho_trials if order is None]
            ordered = [
                trial for order, trial in sorted(
                    (
                        (order, trial) for order, trial in rho_trials
                        if order is not None
                    ),
                    key=lambda pair: expected_orders.index(pair[0]),
                )
            ]
            if invalid:
                invalid_trial = invalid[0]
                if (
                    len(invalid) != 1
                    or ordered
                    or invalid_trial["ingoing_best_prefix_order"] is not None
                    or invalid_trial["outgoing_best_prefix_order"] is not None
                    or invalid_trial["ingoing_adequate"] is not False
                    or invalid_trial["outgoing_adequate"] is not False
                ):
                    raise ValueError(
                        "horizon endpoint invalid geometry was retried"
                    )
                invalid_rhos.add(rho)
                continue
            observed_orders = [
                trial["attempted_endpoint_order"] for trial in ordered
            ]
            if (
                not observed_orders
                or observed_orders
                != expected_orders[:len(observed_orders)]
            ):
                raise ValueError(
                    "horizon endpoint trial order progression is incomplete"
                )
            adequate_trials = [
                trial for trial in ordered
                if trial["ingoing_adequate"] is True
                and trial["outgoing_adequate"] is True
            ]
            if len(adequate_trials) > 1 or (
                adequate_trials and adequate_trials[0] is not ordered[-1]
            ):
                raise ValueError(
                    "horizon endpoint verified geometry was retried"
                )
            if adequate_trials:
                verified_by_rho[rho] = adequate_trials[0]
            last_order_by_rho[rho] = observed_orders[-1]

        selected_expected = [
            trial for rho, trial in sorted(
                verified_by_rho.items(), key=lambda pair: pair[0], reverse=True
            )[:required_selected_count]
        ]
        if required_selected_count:
            if len(verified_by_rho) < required_selected_count:
                raise ValueError("horizon endpoint selected pair is incomplete")
            stop_order = min(
                order for order in expected_orders
                if sum(
                    trial["attempted_endpoint_order"] <= order
                    for trial in verified_by_rho.values()
                ) >= required_selected_count
            )
            if selected_pair != selected_expected:
                raise ValueError(
                    "horizon endpoint selected pair is not the nearest "
                    "adequate pair"
                )
            if any(
                last_order_by_rho[rho] != (
                    verified_by_rho[rho]["attempted_endpoint_order"]
                    if rho in verified_by_rho
                    else stop_order
                )
                for rho in expected_rho_schedule
                if rho not in invalid_rhos
            ):
                raise ValueError(
                    "horizon endpoint success trial schedule is incomplete"
                )
        else:
            adequate_count = len(verified_by_rho)
            if expected_outcome == "fewer-than-two-verified-endpoints/v1":
                expected_adequate_count = 1
            else:
                expected_adequate_count = 0
            if adequate_count != expected_adequate_count:
                raise ValueError("horizon endpoint failure outcome is invalid")
            if expected_outcome == "no-geometry-valid-candidate/v1":
                if invalid_rhos != expected_rhos:
                    raise ValueError(
                        "horizon endpoint geometry exhaustion is incomplete"
                    )
            elif any(
                last_order_by_rho[rho] != (
                    verified_by_rho[rho]["attempted_endpoint_order"]
                    if rho in verified_by_rho
                    else expected_orders[-1]
                )
                for rho in expected_rho_schedule
                if rho not in invalid_rhos
            ):
                raise ValueError(
                    "horizon endpoint failure trial schedule is incomplete"
                )

        expected_trials: list[dict[str, object]] = []
        for rho in expected_rho_schedule:
            if rho in invalid_rhos:
                expected_trials.append(candidate_by_identity[(rho, None)])
        verified_rhos: set[Decimal] = set()
        terminal_order = (
            max(last_order_by_rho.values()) if last_order_by_rho else None
        )
        for order in expected_orders:
            if terminal_order is not None and order > terminal_order:
                break
            for rho in expected_rho_schedule:
                if rho in invalid_rhos or rho in verified_rhos:
                    continue
                trial = candidate_by_identity.get((rho, order))
                if trial is None:
                    raise ValueError(
                        "horizon endpoint depth-before-order trial is missing"
                    )
                expected_trials.append(trial)
                if (
                    trial["ingoing_adequate"] is True
                    and trial["outgoing_adequate"] is True
                ):
                    verified_rhos.add(rho)
        selected_identity_set = set(selected_identities)
        expected_rejected = [
            trial for trial in expected_trials
            if (
                _conditioning_decimal_from_text(
                    trial["rho"], "horizon endpoint candidate rho"
                ),
                trial["attempted_endpoint_order"],
            ) not in selected_identity_set
        ]
        if rejected != expected_rejected:
            raise ValueError(
                "horizon endpoint rejected trial sequence is not canonical"
            )
        if required_selected_count:
            recomputed_outcome = "adequate/v1"
        elif not last_order_by_rho:
            recomputed_outcome = "no-geometry-valid-candidate/v1"
        elif len(verified_by_rho) == 1:
            recomputed_outcome = "fewer-than-two-verified-endpoints/v1"
        elif any(
            trial["limitation"] == _HORIZON_ENDPOINT_PRECISION_LIMITED
            for trial in (*selected_pair, *rejected)
            if trial["attempted_endpoint_order"] is not None
        ):
            recomputed_outcome = "arithmetic-precision-inadequate/v1"
        else:
            recomputed_outcome = "maximum-series-order-inadequate/v1"
        if item["outcome"] != recomputed_outcome:
            raise ValueError("horizon endpoint recovery outcome is invalid")
    return canonical


def _validated_worker_response_receipt(
    value: object,
) -> Mapping[str, object] | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise ValueError("worker response receipt fields are invalid")
    fields = set(value)
    current = fields == _WORKER_RESPONSE_RECEIPT_FIELDS
    previous = fields == _PREVIOUS_WORKER_RESPONSE_RECEIPT_FIELDS
    historical = fields == _HISTORICAL_WORKER_RESPONSE_RECEIPT_FIELDS
    if not (current or previous or historical):
        raise ValueError("worker response receipt fields are invalid")
    expected_schema = (
        WORKER_RESPONSE_RECEIPT_SCHEMA
        if current
        else (
            PREVIOUS_WORKER_RESPONSE_RECEIPT_SCHEMA
            if previous
            else HISTORICAL_WORKER_RESPONSE_RECEIPT_SCHEMA
        )
    )
    if value["schema"] != expected_schema:
        raise ValueError("worker response receipt schema is invalid")
    request_binding = value["request_binding"]
    if not isinstance(request_binding, Mapping):
        raise ValueError("worker response receipt request binding is invalid")
    for field in (
        "request_sha256",
        "scientific_runtime_sha256",
        "receipt_sha256",
    ):
        if not isinstance(value[field], str) or _HEX_64.fullmatch(value[field]) is None:
            raise ValueError(f"worker response receipt {field} is invalid")
    if value["request_sha256"] != _sha256(dict(request_binding)):
        raise ValueError("worker response receipt request digest is invalid")
    wire_schema = value["worker_response_schema_version"]
    allowed_wire_schemas = (
        {WORKER_RESPONSE_WIRE_SCHEMA}
        if current
        else (
            {8} if previous else HISTORICAL_WORKER_RESPONSE_WIRE_SCHEMAS - {8}
        )
    )
    if wire_schema not in allowed_wire_schemas:
        raise ValueError("worker response receipt wire schema is invalid")
    if current or previous:
        if (
            value["promoted_root_readout_policy"]
            != PROMOTED_ROOT_READOUT_POLICY
            or not isinstance(value["primary_acceptance_sha256"], str)
            or _HEX_64.fullmatch(value["primary_acceptance_sha256"]) is None
        ):
            raise ValueError(
                "worker response receipt promoted policy identity is invalid"
            )
    if current:
        mechanism_id = request_binding.get("mechanism_id")
        endpoint_evidence = value["horizon_endpoint_search_evidence"]
        if mechanism_id == "horizon-admittance":
            _validated_successful_horizon_endpoint_search_evidence(
                endpoint_evidence, request_binding
            )
        elif endpoint_evidence is not None:
            raise ValueError(
                "exterior worker response carries horizon endpoint evidence"
            )
    residual = _conditioning_decimal_from_text(
        value["root_residual_abs_text"],
        "worker response receipt root residual",
    )
    if residual < 0:
        raise ValueError("worker response receipt root residual is negative")
    raw_text = value["raw_determinant_abs_text"]
    if raw_text is not None:
        raw = _conditioning_decimal_from_text(
            raw_text, "worker response receipt raw determinant"
        )
        if raw < 0:
            raise ValueError("worker response receipt raw determinant is negative")
    status = value["raw_determinant_evidence_status"]
    if status not in {
        "available/v1",
        "unavailable-overflow/v1",
        "not-applicable/v1",
    }:
        raise ValueError("worker response receipt determinant status is invalid")
    if (status == "available/v1") != (raw_text is not None):
        raise ValueError("worker response receipt determinant evidence is inconsistent")
    material = {key: value[key] for key in value if key != "receipt_sha256"}
    material["request_binding"] = dict(request_binding)
    if value["receipt_sha256"] != _sha256(material):
        raise ValueError("worker response receipt digest is invalid")
    return {
        **material,
        "request_binding": dict(request_binding),
        "receipt_sha256": value["receipt_sha256"],
    }


def _finite_complex(value: complex, subject: str) -> complex:
    converted = complex(value)
    if not (math.isfinite(converted.real) and math.isfinite(converted.imag)):
        raise ValueError(f"{subject} must be finite")
    return converted


def _complex_mapping(value: complex) -> dict[str, float]:
    return {"real": value.real, "imaginary": value.imag}


def _complex_from_mapping(value: object, subject: str) -> complex:
    if not isinstance(value, Mapping) or set(value) != {"real", "imaginary"}:
        raise ValueError(f"{subject} must be a complex-number object")
    real = value["real"]
    imaginary = value["imaginary"]
    if (
        isinstance(real, bool)
        or isinstance(imaginary, bool)
        or not isinstance(real, (int, float))
        or not isinstance(imaginary, (int, float))
    ):
        raise ValueError(f"{subject} components must be numbers")
    return _finite_complex(complex(float(real), float(imaginary)), subject)


def _validated_source_root_mapping(value: object) -> dict[str, object] | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise ValueError("source root mapping must be an object")
    expected_fields = {
        "schema_version",
        "mapping_protocol",
        "source_bundle_baselines_sha256",
        "source_root_reference_id",
        "source_root_identity_sha256",
        "source_branch_id",
        "source_omega",
        "installed_root_reference_id",
        "installed_root_identity_sha256",
        "installed_branch_id",
        "installed_omega",
        "mapping_tolerance_abs",
        "measured_delta_abs",
        "mapping_receipt_sha256",
    }
    if set(value) != expected_fields:
        raise ValueError("source root mapping fields are invalid")
    receipt = dict(value)
    digest = receipt.pop("mapping_receipt_sha256")
    if not isinstance(digest, str) or digest != _sha256(receipt):
        raise ValueError("source root mapping receipt SHA-256 is invalid")
    if (
        receipt["schema_version"] != 1
        or receipt["mapping_protocol"]
        != "authenticated-recorded-source-to-installed-spectral-root"
    ):
        raise ValueError("source root mapping protocol is invalid")
    tolerance = receipt["mapping_tolerance_abs"]
    measured = receipt["measured_delta_abs"]
    if (
        isinstance(tolerance, bool)
        or isinstance(measured, bool)
        or not isinstance(tolerance, (int, float))
        or not isinstance(measured, (int, float))
        or float(tolerance) != _RECORDED_ROOT_MAPPING_TOLERANCE_ABS
        or not math.isfinite(float(measured))
        or float(measured) < 0.0
        or float(measured) > float(tolerance)
    ):
        raise ValueError("source root mapping tolerance or delta is invalid")
    source = _complex_from_mapping(receipt["source_omega"], "source root mapping omega")
    installed = _complex_from_mapping(
        receipt["installed_omega"], "installed root mapping omega"
    )
    if float(measured) != abs(source - installed):
        raise ValueError("source root mapping measured delta is invalid")
    for key in (
        "source_bundle_baselines_sha256",
        "source_root_identity_sha256",
        "installed_root_identity_sha256",
    ):
        field = receipt[key]
        if not isinstance(field, str) or re.fullmatch(r"[0-9a-f]{64}", field) is None:
            raise ValueError("source root mapping digest field is invalid")
    for key in (
        "source_root_reference_id",
        "source_branch_id",
        "installed_root_reference_id",
        "installed_branch_id",
    ):
        if not isinstance(receipt[key], str) or not receipt[key]:
            raise ValueError("source root mapping identity field is invalid")
    receipt["mapping_receipt_sha256"] = digest
    return receipt


@dataclass(frozen=True, slots=True)
class BackendIdentity:
    backend_id: str
    implementation_version: str
    source_commit: str
    source_blobs: tuple[tuple[str, str], ...]
    runtime_fingerprint: str

    def __post_init__(self) -> None:
        if not self.backend_id or not self.implementation_version:
            raise ValueError("backend identity fields must be nonempty")
        if _HEX_40.fullmatch(self.source_commit) is None:
            raise ValueError("backend source_commit must be a Git SHA")
        if not self.source_blobs or len({name for name, _ in self.source_blobs}) != len(
            self.source_blobs
        ):
            raise ValueError("backend source blobs must be nonempty and unique")
        for name, digest in self.source_blobs:
            if not name or _HEX_40.fullmatch(digest) is None:
                raise ValueError("backend source blob identity is invalid")
        if not self.runtime_fingerprint:
            raise ValueError("backend runtime_fingerprint must be nonempty")

    def to_mapping(self) -> dict[str, object]:
        return {
            "backend_id": self.backend_id,
            "implementation_version": self.implementation_version,
            "source_commit": self.source_commit,
            "source_blobs": [
                {"path": name, "git_blob_sha": digest}
                for name, digest in self.source_blobs
            ],
            "runtime_fingerprint": self.runtime_fingerprint,
        }

    @property
    def identity_sha256(self) -> str:
        return _sha256(self.to_mapping())


@dataclass(frozen=True, slots=True)
class NumericalPolicy:
    epsilons: tuple[float, ...] = (
        4.0e-3,
        2.0e-3,
        1.0e-3,
        5.0e-4,
        2.5e-4,
        1.25e-4,
    )
    ode_relative_tolerance: float = 2.0e-10
    ode_absolute_tolerance: float = 2.0e-12
    endpoint_series_order: int = 28
    readout_radius: float = 6.0
    support_subinterval_count: int = 256
    order_tolerance: float = 0.45
    even_order_tolerance: float = 0.75
    signal_to_root_factor: float = 8.0
    axis_tolerance_factor: float = 2.0
    absolute_axis_floor: float = 1.0e-12

    def __post_init__(self) -> None:
        epsilons = tuple(float(value) for value in self.epsilons)
        if len(epsilons) < 4:
            raise ValueError("response refinement requires at least four amplitude levels")
        if any(not math.isfinite(value) or value <= 0.0 for value in epsilons):
            raise ValueError("response amplitudes must be finite and positive")
        if any(left <= right for left, right in zip(epsilons, epsilons[1:])):
            raise ValueError("response amplitudes must be strictly coarse-to-fine")
        for name in (
            "ode_relative_tolerance",
            "ode_absolute_tolerance",
            "order_tolerance",
            "even_order_tolerance",
            "absolute_axis_floor",
        ):
            value = float(getattr(self, name))
            if not math.isfinite(value) or value <= 0.0:
                raise ValueError(f"{name} must be finite and positive")
        if self.endpoint_series_order < 1 or self.support_subinterval_count < 32:
            raise ValueError("native numerical resolution is invalid")
        if not math.isfinite(self.readout_radius) or self.readout_radius <= 0.0:
            raise ValueError("readout_radius must be finite and positive")
        if self.signal_to_root_factor <= 1.0 or self.axis_tolerance_factor <= 0.0:
            raise ValueError("response refinement factors are invalid")
        object.__setattr__(self, "epsilons", epsilons)

    def to_mapping(self) -> dict[str, object]:
        return {
            "epsilons": list(self.epsilons),
            "ode_relative_tolerance": self.ode_relative_tolerance,
            "ode_absolute_tolerance": self.ode_absolute_tolerance,
            "endpoint_series_order": self.endpoint_series_order,
            "readout_radius": self.readout_radius,
            "support_subinterval_count": self.support_subinterval_count,
            "order_tolerance": self.order_tolerance,
            "even_order_tolerance": self.even_order_tolerance,
            "signal_to_root_factor": self.signal_to_root_factor,
            "axis_tolerance_factor": self.axis_tolerance_factor,
            "absolute_axis_floor": self.absolute_axis_floor,
        }

    @property
    def identity_sha256(self) -> str:
        return _sha256(self.to_mapping())


@dataclass(frozen=True, slots=True)
class SamplingCoordinate:
    coordinate_id: str
    exact: tuple[int, int]
    value: float
    transformation_id: str

    def to_mapping(self) -> dict[str, object]:
        return {
            "coordinate_id": self.coordinate_id,
            "exact": {"numerator": self.exact[0], "denominator": self.exact[1]},
            "value": self.value,
            "transformation_id": self.transformation_id,
        }


@dataclass(frozen=True, slots=True)
class BoundSpectralRoot:
    selector_id: str
    availability: str
    root_reference_id: str
    branch_id: str
    spin_binary64_hex: str
    omega: complex
    angular_separation_constant: complex
    owner_id: str
    owner_data_sha256: str
    owner_record: Mapping[str, object]

    def to_mapping(self) -> dict[str, object]:
        return {
            "selector_id": self.selector_id,
            "availability": self.availability,
            "root_reference_id": self.root_reference_id,
            "branch_id": self.branch_id,
            "spin_binary64_hex": self.spin_binary64_hex,
            "omega": _complex_mapping(self.omega),
            "angular_separation_constant": _complex_mapping(
                self.angular_separation_constant
            ),
            "owner_id": self.owner_id,
            "owner_data_sha256": self.owner_data_sha256,
            "owner_record": dict(self.owner_record),
        }

    @property
    def identity_sha256(self) -> str:
        return _sha256(self.to_mapping())


def mode_specific_branch_enclosure_radius(
    authenticated_root: BoundSpectralRoot,
) -> float:
    """Return a radius strictly below half the nearest authenticated overtone."""

    mode = authenticated_root.owner_record.get("mode")
    evidence = authenticated_root.owner_record.get("numerical_evidence")
    if not isinstance(mode, Mapping) or not isinstance(evidence, Mapping):
        raise ValueError("authenticated root branch evidence is incomplete")
    ell = mode.get("ell")
    m = mode.get("m")
    n = mode.get("n")
    if any(isinstance(value, bool) or not isinstance(value, int) for value in (ell, m, n)):
        raise ValueError("authenticated root mode identity is invalid")

    separations: list[float] = []
    for field in (
        "assigned_separation_abs",
        "nearest_overtone_separation_abs",
    ):
        value = evidence.get(field)
        if (
            not isinstance(value, bool)
            and isinstance(value, (int, float))
            and math.isfinite(float(value))
            and float(value) > 0.0
        ):
            separations.append(float(value))

    catalog = load_spectrum_catalog()
    for candidate in (*catalog.base.roots, *catalog.overlay.roots):
        if (
            candidate.ell == ell
            and candidate.m == m
            and candidate.n != n
            and candidate.spin_hex == authenticated_root.spin_binary64_hex
        ):
            separation = abs(
                complex(candidate.omega_re, candidate.omega_im)
                - authenticated_root.omega
            )
            if math.isfinite(separation) and separation > 0.0:
                separations.append(separation)

    if not separations:
        raise ValueError(
            "authenticated root has no mode-specific overtone separation"
        )
    radius = min(
        ROOT_BRANCH_CONTINUATION_TOLERANCE_ABS,
        0.45 * min(separations),
    )
    if not math.isfinite(radius) or radius <= 0.0:
        raise ValueError("mode-specific branch enclosure radius is invalid")
    return radius


def _mode_for_leaf(leaf: BPrimeLeaf) -> ModeKey:
    return ModeKey(
        s=-2,
        ell=leaf.mode[0],
        m=leaf.mode[1],
        n=leaf.mode[2],
        branch=PUBLIC_BRANCH_ID,
        polarization=PUBLIC_POLARIZATION_ID,
    )


def _resolve_root(leaf: BPrimeLeaf, mode: ModeKey) -> BoundSpectralRoot:
    selector = next(
        (
            item
            for item in B_PRIME_RELEASE_DOMAIN.root_selectors
            if item.mode == leaf.mode and item.spin.hex() == leaf.spin.hex()
        ),
        None,
    )
    if selector is None:
        raise ValueError("B-prime leaf has no exact root selector")
    request = StudyRequest.from_mapping(
        {
            "schema_version": 1,
            "target": Capability.SPECTRAL_CORE.value,
            "theory_id": PUBLIC_THEORY_ID,
            "convention_id": PUBLIC_CONVENTION_ID,
            "modes": [mode.to_mapping()],
            "spins": [leaf.spin],
            "evidence_profile": "research",
            "numerical_policy": {},
        }
    )
    catalog = load_spectrum_catalog()
    root = catalog.select(request)[0]
    record = root.to_mapping()
    owner_id = type(root).__name__
    owner_sha = (
        catalog.overlay.data_sha256
        if owner_id == "SpectralOverlayRoot"
        else catalog.data_sha256
    )
    return BoundSpectralRoot(
        selector_id=selector.selector_id,
        availability=selector.availability,
        root_reference_id=baseline_root_reference_id(mode, leaf.spin),
        branch_id=root.branch_id,
        spin_binary64_hex=root.spin_hex,
        omega=complex(root.omega_re, root.omega_im),
        angular_separation_constant=complex(root.angular_A_re, root.angular_A_im),
        owner_id=owner_id,
        owner_data_sha256=owner_sha,
        owner_record=record,
    )


@lru_cache(maxsize=None)
def _bound_spectral_root_bytes(leaf_id: str) -> bytes:
    leaf = next(
        (
            item for item in B_PRIME_RELEASE_DOMAIN.production_leaves
            if item.leaf_id == leaf_id
        ),
        None,
    )
    if leaf is None:
        raise ValueError("spectral root leaf_id is outside frozen B-prime")
    return canonical_json_bytes(_resolve_root(leaf, _mode_for_leaf(leaf)).to_mapping())


def bound_spectral_root_mapping_for_leaf(leaf_id: str) -> dict[str, object]:
    value = json.loads(_bound_spectral_root_bytes(leaf_id))
    if not isinstance(value, dict):
        raise ValueError("bound spectral root must be an object")
    return value


@lru_cache(maxsize=1)
def _campaign_spectral_receipt_bytes() -> bytes:
    roots: dict[str, Mapping[str, object]] = {}
    for leaf in B_PRIME_RELEASE_DOMAIN.production_leaves:
        root = bound_spectral_root_mapping_for_leaf(leaf.leaf_id)
        roots.setdefault(_sha256(root), root)
    return canonical_json_bytes({
        "provider": SpectralCatalogProvider.descriptor.to_mapping(),
        "root_count": len(roots),
        "root_set_sha256": _sha256(list(roots.values())),
    })


def campaign_spectral_receipt() -> dict[str, object]:
    value = json.loads(_campaign_spectral_receipt_bytes())
    if not isinstance(value, dict):
        raise ValueError("campaign spectral receipt must be an object")
    return value


@dataclass(frozen=True, slots=True)
class ResponseComponentJob:
    leaf_id: str
    role: str
    mode_label: str
    mode: ModeKey
    spin: float
    mechanism_id: str
    sampling_coordinate: SamplingCoordinate
    root: BoundSpectralRoot
    policy: NumericalPolicy
    backend_identity: BackendIdentity
    source_root_mapping: Mapping[str, object] | None = None
    equation_id: str = ENGINE_EQUATION_ID

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "source_root_mapping",
            _validated_source_root_mapping(self.source_root_mapping),
        )

    @classmethod
    def from_leaf_id(
        cls,
        leaf_id: str,
        *,
        policy: NumericalPolicy,
        backend_identity: BackendIdentity,
    ) -> "ResponseComponentJob":
        leaf = next(
            (
                item
                for item in B_PRIME_RELEASE_DOMAIN.production_leaves
                if item.leaf_id == leaf_id
            ),
            None,
        )
        if leaf is None:
            raise ValueError("response job leaf_id is outside frozen B-prime")
        mode = _mode_for_leaf(leaf)
        if leaf.spin_role == "direct":
            coordinate = SamplingCoordinate(
                "a_over_M",
                (leaf.coordinate.numerator, leaf.coordinate.denominator),
                float(leaf.coordinate),
                "identity-a-over-M",
            )
        else:
            coordinate = SamplingCoordinate(
                "M-kappa",
                (leaf.coordinate.numerator, leaf.coordinate.denominator),
                float(leaf.coordinate),
                "kerr-prograde-spin-from-dimensionless-surface-gravity",
            )
        return cls(
            leaf_id=leaf.leaf_id,
            role=leaf.role,
            mode_label=leaf.mode_label,
            mode=mode,
            spin=leaf.spin,
            mechanism_id=leaf.mechanism_id,
            sampling_coordinate=coordinate,
            root=_resolve_root(leaf, mode),
            policy=policy,
            backend_identity=backend_identity,
        )

    def to_mapping(self) -> dict[str, object]:
        return {
            "leaf_id": self.leaf_id,
            "role": self.role,
            "mode_label": self.mode_label,
            "mode": self.mode.to_mapping(),
            "spin": self.spin,
            "spin_binary64_hex": self.spin.hex(),
            "mechanism_id": self.mechanism_id,
            "sampling_coordinate": self.sampling_coordinate.to_mapping(),
            "root": self.root.to_mapping(),
            "policy": self.policy.to_mapping(),
            "backend_identity": self.backend_identity.to_mapping(),
            "source_root_mapping": (
                None
                if self.source_root_mapping is None
                else dict(self.source_root_mapping)
            ),
            "equation_id": self.equation_id,
        }

    @property
    def job_id(self) -> str:
        return f"response-job-{_sha256(self.to_mapping())}"


@dataclass(frozen=True, slots=True)
class ExteriorSupport:
    lower: float
    upper: float
    centre: float
    half_width: float

    def to_mapping(self) -> dict[str, float]:
        return {
            "lower": self.lower,
            "upper": self.upper,
            "centre": self.centre,
            "half_width": self.half_width,
        }


def _exterior_support(spin: float, mechanism_id: str) -> ExteriorSupport:
    profile = _EXTERIOR_PROFILE_IDS.get(mechanism_id)
    if profile is None:
        raise ValueError(f"unsupported exterior mechanism: {mechanism_id}")
    horizon = 1.0 + math.sqrt(max(0.0, 1.0 - spin * spin))
    kappa = math.sqrt(max(0.0, 1.0 - spin * spin)) / (2.0 * horizon)
    if profile == "fixed-r3":
        centre, width = 3.0, 0.45
    elif profile == "light-ring":
        centre = 2.0 * (1.0 + math.cos((2.0 / 3.0) * math.acos(-spin)))
        width = max(0.012, 0.25 * max(centre - horizon, 1.0e-8))
    elif profile == "throat-kappa":
        centre, width = horizon + 3.0 * kappa, max(0.012, 0.6 * kappa)
    elif profile == "alpha-zero":
        centre, width = horizon + 2.0, 0.5
    elif profile == "alpha-half":
        scale = math.sqrt(max(kappa, 1.0e-300))
        centre, width = horizon + 2.0 * scale, max(0.012, 0.5 * scale)
    else:
        centre, width = horizon + 4.0 * kappa, max(0.012, kappa)
    width = min(width, centre - (horizon + 5.0e-4))
    if width <= 0.0:
        raise ValueError("exterior profile has no smooth support outside horizon")
    return ExteriorSupport(centre - width, centre + width, centre, width)


@dataclass(frozen=True, slots=True)
class HorizonPerturbation:
    amplitude: complex
    spin: float
    azimuthal_index: int
    coordinate_id: str = "unit-complex-deltaB"

    def reflectivity(self, trial_omega: complex) -> complex:
        horizon = 1.0 + math.sqrt(max(0.0, 1.0 - self.spin * self.spin))
        omega_h = self.spin / (2.0 * horizon)
        p_h = complex(trial_omega) - self.azimuthal_index * omega_h
        denominator = 2.0j * p_h - self.amplitude
        if denominator == 0.0j:
            raise ValueError("zero horizon chart denominator")
        return self.amplitude / denominator


@dataclass(frozen=True, slots=True)
class ExteriorPerturbation:
    amplitude: complex
    profile_id: str
    support: ExteriorSupport
    coordinate_id: str = "unit-complex-profile-amplitude"

    def profile_value(self, radius: float) -> complex:
        """Return the migrated L-infinity-normalized compact C-infinity bump."""

        value = float(radius)
        if not math.isfinite(value):
            raise ValueError("exterior profile radius must be finite")
        scaled = (value - self.support.centre) / self.support.half_width
        if abs(scaled) >= 1.0:
            return 0.0j
        return self.amplitude * math.exp(1.0 - 1.0 / (1.0 - scaled * scaled))


@dataclass(frozen=True, slots=True)
class DeterminantPartials:
    frequency_derivative: complex
    coordinate_derivative: complex
    simple_root_valid: bool

    def __post_init__(self) -> None:
        _finite_complex(self.frequency_derivative, "frequency derivative")
        _finite_complex(self.coordinate_derivative, "coordinate derivative")


@dataclass(frozen=True, slots=True)
class DiagnosticRootReadout:
    """One non-primary diagnostic retained for response-space reduction."""

    omega_delta_from_primary: complex
    determinant_residual_abs: float
    determinant_derivative_abs: float
    converged: bool
    correction_upper_bound: float | None = None
    determinant_error_abs: float | None = None
    error_model_id: str | None = None
    derivative_lower_bound_abs: float | None = None
    root_correction_tolerance: float | None = None
    displacement_from_primary_abs: float | None = None
    branch_identity: str | None = None
    branch_authenticated: bool | None = None
    control_identity: str | None = None
    solve_role: str | None = None
    full_authentication_escalated: bool | None = None
    escalation_reason: str | None = None
    authenticated_evidence_reused: bool | None = None
    determinant_count: int | None = None
    root_phase: str | None = None
    authentication_mode: str | None = None
    authoritative: bool | None = None
    residual_upper_bound_abs: float | None = None
    required_derivative_lower_bound_abs: float | None = None
    raw_step_disagreement_abs: float | None = None
    guarded_step_disagreement_abs: float | None = None
    propagated_derivative_error_abs: float | None = None
    determinant_count_phase: int | None = None
    fixed_root_evidence: FixedRootDiagnosticEvidence | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "omega_delta_from_primary",
            _finite_complex(
                self.omega_delta_from_primary,
                "diagnostic root delta from primary",
            ),
        )
        for name in ("determinant_residual_abs", "determinant_derivative_abs"):
            value = float(getattr(self, name))
            if not math.isfinite(value) or value < 0.0:
                raise ValueError(f"{name} must be finite and nonnegative")
            object.__setattr__(self, name, value)
        if self.determinant_derivative_abs <= 0.0:
            raise ValueError("diagnostic determinant derivative must be positive")
        if type(self.converged) is not bool:
            raise ValueError("converged must be a built-in bool")

        if self.fixed_root_evidence is not None:
            if not isinstance(
                self.fixed_root_evidence, FixedRootDiagnosticEvidence
            ):
                raise ValueError("fixed-root diagnostic evidence has invalid type")
            legacy_workflow_evidence = (
                self.correction_upper_bound,
                self.determinant_error_abs,
                self.error_model_id,
                self.derivative_lower_bound_abs,
                self.root_correction_tolerance,
                self.displacement_from_primary_abs,
                self.branch_identity,
                self.branch_authenticated,
                self.control_identity,
                self.solve_role,
                self.full_authentication_escalated,
                self.escalation_reason,
                self.authenticated_evidence_reused,
                self.determinant_count,
                self.root_phase,
                self.authentication_mode,
                self.authoritative,
                self.residual_upper_bound_abs,
                self.required_derivative_lower_bound_abs,
                self.raw_step_disagreement_abs,
                self.guarded_step_disagreement_abs,
                self.propagated_derivative_error_abs,
                self.determinant_count_phase,
            )
            if any(item is not None for item in legacy_workflow_evidence):
                raise ValueError(
                    "fixed-root evidence cannot carry legacy diagnostic workflow"
                )
            if self.omega_delta_from_primary != 0.0j:
                raise ValueError("fixed-root diagnostic moved the PRIMARY root")
            with localcontext() as context:
                context.prec = _ROOT_AUTHENTICATION_CHECK_DIGITS
                residual = float(self.fixed_root_evidence.determinant.magnitude())
                derivative = float(
                    self.fixed_root_evidence.primary_derivative.magnitude()
                )
            if not math.isclose(
                self.determinant_residual_abs,
                residual,
                rel_tol=1.0e-15,
                abs_tol=0.0,
            ) or not math.isclose(
                self.determinant_derivative_abs,
                derivative,
                rel_tol=1.0e-15,
                abs_tol=0.0,
            ):
                raise ValueError(
                    "fixed-root diagnostic scalars disagree with exact evidence"
                )
            if self.converged != self.fixed_root_evidence.accepted:
                raise ValueError(
                    "fixed-root diagnostic convergence is inconsistent"
                )
            return

        if self.solve_role is None:
            optional_evidence = (
                self.correction_upper_bound,
                self.determinant_error_abs,
                self.error_model_id,
                self.derivative_lower_bound_abs,
                self.root_correction_tolerance,
                self.displacement_from_primary_abs,
                self.branch_identity,
                self.branch_authenticated,
                self.control_identity,
                self.full_authentication_escalated,
                self.escalation_reason,
                self.authenticated_evidence_reused,
                self.determinant_count,
                self.root_phase,
                self.authentication_mode,
                self.authoritative,
                self.residual_upper_bound_abs,
                self.required_derivative_lower_bound_abs,
                self.raw_step_disagreement_abs,
                self.guarded_step_disagreement_abs,
                self.propagated_derivative_error_abs,
                self.determinant_count_phase,
            )
            if any(item is not None for item in optional_evidence):
                raise ValueError(
                    "diagnostic workflow evidence must be complete or absent"
                )
            return

        if self.solve_role != "DIAGNOSTIC_CONSISTENCY":
            raise ValueError("diagnostic solve role is invalid")
        numeric_fields = (
            "correction_upper_bound",
            "determinant_error_abs",
            "derivative_lower_bound_abs",
            "root_correction_tolerance",
            "displacement_from_primary_abs",
        )
        for name in numeric_fields:
            raw = getattr(self, name)
            if raw is None:
                raise ValueError(f"{name} is required")
            value = float(raw)
            if not math.isfinite(value) or value < 0.0:
                raise ValueError(f"{name} must be finite and nonnegative")
            object.__setattr__(self, name, value)
        if self.derivative_lower_bound_abs <= 0.0:
            raise ValueError("diagnostic derivative lower bound must be positive")
        if self.root_correction_tolerance <= 0.0:
            raise ValueError("diagnostic root correction tolerance must be positive")
        if not math.isclose(
            self.determinant_derivative_abs,
            self.derivative_lower_bound_abs,
            rel_tol=1.0e-15,
            abs_tol=0.0,
        ):
            raise ValueError(
                "diagnostic derivative magnitude and lower bound disagree"
            )
        if self.error_model_id is None:
            if self.determinant_error_abs != 0.0:
                raise ValueError(
                    "diagnostic determinant error requires its model identity"
                )
        elif (
            not isinstance(self.error_model_id, str)
            or not self.error_model_id
        ):
            raise ValueError("diagnostic error model identity is invalid")
        for name in ("branch_identity", "control_identity"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value:
                raise ValueError(f"{name} must be a nonempty string")
        for name in (
            "branch_authenticated",
            "full_authentication_escalated",
            "authenticated_evidence_reused",
        ):
            if type(getattr(self, name)) is not bool:
                raise ValueError(f"{name} must be a built-in bool")
        if (
            type(self.determinant_count) is not int
            or self.determinant_count < 0
        ):
            raise ValueError("determinant_count must be a nonnegative integer")
        staged_evidence = (
            self.root_phase,
            self.authoritative,
            self.residual_upper_bound_abs,
            self.required_derivative_lower_bound_abs,
            self.raw_step_disagreement_abs,
            self.guarded_step_disagreement_abs,
            self.propagated_derivative_error_abs,
            self.determinant_count_phase,
        )
        if self.authentication_mode is None:
            if any(value is not None for value in staged_evidence):
                raise ValueError(
                    "diagnostic staged workflow evidence is incomplete"
                )
        else:
            if self.authentication_mode not in {
                "DIAGNOSTIC_CONSISTENCY",
                "FULL_AUTHENTICATION_ESCALATION",
            }:
                raise ValueError(
                    "diagnostic authentication mode is invalid"
                )
            if self.root_phase not in {
                "TRUNCATION",
                "RESOLUTION",
                "SEED-PATH",
            }:
                raise ValueError("diagnostic root phase is invalid")
            if self.authoritative is not False:
                raise ValueError(
                    "diagnostic phase cannot be authoritative"
                )
            for name in (
                "residual_upper_bound_abs",
                "required_derivative_lower_bound_abs",
                "propagated_derivative_error_abs",
            ):
                value = getattr(self, name)
                if (
                    value is None
                    or not math.isfinite(float(value))
                    or float(value) < 0.0
                ):
                    raise ValueError(
                        f"diagnostic {name} must be finite and nonnegative"
                    )
                object.__setattr__(self, name, float(value))
            for name in (
                "raw_step_disagreement_abs",
                "guarded_step_disagreement_abs",
            ):
                value = getattr(self, name)
                if value is None:
                    continue
                if not math.isfinite(float(value)) or float(value) < 0.0:
                    raise ValueError(
                        f"diagnostic {name} must be finite and nonnegative"
                    )
                object.__setattr__(self, name, float(value))
            if (
                type(self.determinant_count_phase) is not int
                or self.determinant_count_phase != self.determinant_count
            ):
                raise ValueError(
                    "diagnostic phase determinant count is inconsistent"
                )
            if self.full_authentication_escalated != (
                self.authentication_mode
                == "FULL_AUTHENTICATION_ESCALATION"
            ):
                raise ValueError(
                    "diagnostic authentication mode disagrees with escalation"
                )
            expected_required = (
                self.residual_upper_bound_abs
                / self.root_correction_tolerance
            )
            expected_correction = (
                self.residual_upper_bound_abs
                / self.derivative_lower_bound_abs
            )
            if not math.isclose(
                self.required_derivative_lower_bound_abs,
                expected_required,
                rel_tol=1.0e-12,
                abs_tol=0.0,
            ):
                raise ValueError(
                    "diagnostic required derivative bound is inconsistent"
                )
            if not math.isclose(
                self.correction_upper_bound,
                expected_correction,
                rel_tol=1.0e-12,
                abs_tol=0.0,
            ):
                raise ValueError(
                    "diagnostic correction bound is inconsistent"
                )
        if self.full_authentication_escalated != (
            self.escalation_reason is not None
        ):
            raise ValueError(
                "diagnostic escalation reason is inconsistent"
            )
        if self.escalation_reason is not None and (
            not isinstance(self.escalation_reason, str)
            or not self.escalation_reason
        ):
            raise ValueError(
                "diagnostic escalation reason must be nonempty"
            )
        derived_displacement = abs(self.omega_delta_from_primary)
        binary64_resolution = 2.0 * max(
            math.ulp(self.omega_delta_from_primary.real),
            math.ulp(self.omega_delta_from_primary.imag),
            math.ulp(self.displacement_from_primary_abs),
            1.0e-300,
        )
        if not math.isclose(
            self.displacement_from_primary_abs,
            derived_displacement,
            rel_tol=1.0e-12,
            abs_tol=binary64_resolution,
        ):
            raise ValueError(
                "diagnostic displacement evidence is inconsistent"
            )
        if self.converged and (
            not self.branch_authenticated
            or self.correction_upper_bound > self.root_correction_tolerance
        ):
            raise ValueError(
                "diagnostic convergence exceeds its authenticated bounds"
            )

    @property
    def newton_correction_estimate(self) -> float:
        # Retain the historical signed-root uncertainty propagation. The new
        # error-aware correction is additional diagnostic evidence, not a
        # replacement for this response-space reduction quantity.
        return self.determinant_residual_abs / self.determinant_derivative_abs

    def to_mapping(self) -> dict[str, object]:
        output: dict[str, object] = {
            "omega_delta_from_primary": _complex_mapping(
                self.omega_delta_from_primary
            ),
            "determinant_residual_abs": self.determinant_residual_abs,
            "determinant_derivative_abs": self.determinant_derivative_abs,
            "newton_correction_estimate": self.newton_correction_estimate,
            "converged": self.converged,
        }
        if self.solve_role is not None:
            output.update({
                "correction_upper_bound": self.correction_upper_bound,
                "determinant_error_abs": self.determinant_error_abs,
                "error_model_id": self.error_model_id,
                "derivative_lower_bound_abs": self.derivative_lower_bound_abs,
                "root_correction_tolerance": self.root_correction_tolerance,
                "displacement_from_primary_abs": (
                    self.displacement_from_primary_abs
                ),
                "branch_identity": self.branch_identity,
                "branch_authenticated": self.branch_authenticated,
                "control_identity": self.control_identity,
                "solve_role": self.solve_role,
                "full_authentication_escalated": (
                    self.full_authentication_escalated
                ),
                "escalation_reason": self.escalation_reason,
                "authenticated_evidence_reused": (
                    self.authenticated_evidence_reused
                ),
                "determinant_count": self.determinant_count,
            })
            if self.authentication_mode is not None:
                output.update({
                    "root_phase": self.root_phase,
                    "authentication_mode": self.authentication_mode,
                    "authoritative": self.authoritative,
                    "residual_upper_bound_abs": (
                        self.residual_upper_bound_abs
                    ),
                    "required_derivative_lower_bound_abs": (
                        self.required_derivative_lower_bound_abs
                    ),
                    "raw_step_disagreement_abs": (
                        self.raw_step_disagreement_abs
                    ),
                    "guarded_step_disagreement_abs": (
                        self.guarded_step_disagreement_abs
                    ),
                    "propagated_derivative_error_abs": (
                        self.propagated_derivative_error_abs
                    ),
                    "determinant_count_phase": (
                        self.determinant_count_phase
                    ),
                })
        if self.fixed_root_evidence is not None:
            output["fixed_root_evidence"] = (
                self.fixed_root_evidence.to_mapping()
            )
        return output

    @classmethod
    def from_mapping(cls, value: object) -> "DiagnosticRootReadout":
        if not isinstance(value, Mapping):
            raise ValueError("diagnostic root readout must be an object")
        has_workflow_evidence = "solve_role" in value
        return cls(
            omega_delta_from_primary=_complex_from_mapping(
                value.get("omega_delta_from_primary"),
                "diagnostic root delta from primary",
            ),
            determinant_residual_abs=float(value["determinant_residual_abs"]),
            determinant_derivative_abs=float(value["determinant_derivative_abs"]),
            converged=value["converged"],
            correction_upper_bound=(
                float(value["correction_upper_bound"])
                if has_workflow_evidence
                else None
            ),
            determinant_error_abs=(
                float(value["determinant_error_abs"])
                if has_workflow_evidence
                else None
            ),
            error_model_id=(
                value.get("error_model_id")
                if has_workflow_evidence
                else None
            ),
            derivative_lower_bound_abs=(
                float(value["derivative_lower_bound_abs"])
                if has_workflow_evidence
                else None
            ),
            root_correction_tolerance=(
                float(value["root_correction_tolerance"])
                if has_workflow_evidence
                else None
            ),
            displacement_from_primary_abs=(
                float(value["displacement_from_primary_abs"])
                if has_workflow_evidence
                else None
            ),
            branch_identity=(
                value.get("branch_identity")
                if has_workflow_evidence
                else None
            ),
            branch_authenticated=(
                value.get("branch_authenticated")
                if has_workflow_evidence
                else None
            ),
            control_identity=(
                value.get("control_identity")
                if has_workflow_evidence
                else None
            ),
            solve_role=(
                value.get("solve_role")
                if has_workflow_evidence
                else None
            ),
            full_authentication_escalated=(
                value.get("full_authentication_escalated")
                if has_workflow_evidence
                else None
            ),
            escalation_reason=(
                value.get("escalation_reason")
                if has_workflow_evidence
                else None
            ),
            authenticated_evidence_reused=(
                value.get("authenticated_evidence_reused")
                if has_workflow_evidence
                else None
            ),
            determinant_count=(
                value.get("determinant_count")
                if has_workflow_evidence
                else None
            ),
            root_phase=(
                value.get("root_phase")
                if "authentication_mode" in value
                else None
            ),
            authentication_mode=value.get("authentication_mode"),
            authoritative=(
                value.get("authoritative")
                if "authentication_mode" in value
                else None
            ),
            residual_upper_bound_abs=(
                float(value["residual_upper_bound_abs"])
                if "authentication_mode" in value
                else None
            ),
            required_derivative_lower_bound_abs=(
                float(value["required_derivative_lower_bound_abs"])
                if "authentication_mode" in value
                else None
            ),
            raw_step_disagreement_abs=(
                None
                if (
                    "authentication_mode" not in value
                    or value.get("raw_step_disagreement_abs") is None
                )
                else float(value["raw_step_disagreement_abs"])
            ),
            guarded_step_disagreement_abs=(
                None
                if (
                    "authentication_mode" not in value
                    or value.get("guarded_step_disagreement_abs") is None
                )
                else float(value["guarded_step_disagreement_abs"])
            ),
            propagated_derivative_error_abs=(
                float(value["propagated_derivative_error_abs"])
                if "authentication_mode" in value
                else None
            ),
            determinant_count_phase=(
                value.get("determinant_count_phase")
                if "authentication_mode" in value
                else None
            ),
            fixed_root_evidence=(
                None
                if "fixed_root_evidence" not in value
                else FixedRootDiagnosticEvidence.from_mapping(
                    value["fixed_root_evidence"]
                )
            ),
        )

# Wide enough that re-forming the worker's product in decimal is exact well
# past the tolerance below, cheap enough to run on every parsed receipt.
_ERROR_BUDGET_CHECK_DIGITS = 60
_ERROR_BUDGET_AGGREGATE_TOLERANCE = Decimal("1e-40")
_ROOT_AUTHENTICATION_CHECK_DIGITS = 180
_ROOT_AUTHENTICATION_RELATIVE_TOLERANCE = Decimal("1e-50")

_DETERMINANT_ERROR_EVIDENCE_FIELDS = frozenset({
    "endpoint_disagreement_abs",
    "control_disagreement_abs",
    "equivalence_disagreement_abs",
    "precision_disagreement_abs",
    "safety_factor",
    "numerical_error_abs",
    "error_model_id",
})
_DERIVATIVE_AUTHENTICATION_FIELDS = frozenset({
    "derivative_re",
    "derivative_im",
    "propagated_error_abs",
    "step_disagreement_abs",
    "lower_bound_abs",
    "selected_step",
    "axis",
})
_ROOT_AUTHENTICATION_FIELDS = frozenset({
    "central_determinant_re",
    "central_determinant_im",
    "determinant_error",
    "residual_upper_bound_abs",
    "derivative_authentication",
    "correction_upper_bound",
    "root_correction_tolerance",
    "accepted",
})
_ROOT_AUTHENTICATION_FIELDS_V6 = _ROOT_AUTHENTICATION_FIELDS | {
    "authentication_strategy",
    "derivative_evidence",
}
_ROOT_DERIVATIVE_EVIDENCE_FIELDS = frozenset({
    "real_base",
    "real_half",
    "real_double",
    "imaginary",
})
STAGED_REAL_AXIS_AUTHENTICATION_STRATEGY = "staged-real-axis-h-h2/v1"
FULL_DERIVATIVE_LADDER_AUTHENTICATION_STRATEGY = (
    "full-h-h2-2h-ih-ladder/v1"
)


@dataclass(frozen=True, slots=True)
class DecimalComplex:
    """A complex value whose components keep the worker's exact decimal text.

    Collapsing these to binary64 would discard most of the precision the
    promoted worker was run at, which is the opposite of what a 120-digit
    pipeline needs from its evidence records.
    """

    real: Decimal
    imaginary: Decimal

    def magnitude(self) -> Decimal:
        """Return |z| at the current decimal context precision."""

        return (self.real * self.real + self.imaginary * self.imaginary).sqrt()

    def to_mapping(self) -> dict[str, str]:
        """Return the worker's wire form, digit for digit.

        ``str`` on a ``Decimal`` is exact, so a readout that is written and
        read back carries the same digits the worker produced rather than a
        binary64 shadow of them.
        """

        return {"real": str(self.real), "imaginary": str(self.imaginary)}


def _bounded_binary64_disk_from_decimal(
    centre: DecimalComplex,
    radius: Decimal,
    *,
    subject: str,
) -> ComplexDisk:
    """Round an exact decimal disk to binary64 without losing containment."""

    if (
        not isinstance(centre, DecimalComplex)
        or type(radius) is not Decimal
        or not centre.real.is_finite()
        or not centre.imaginary.is_finite()
        or not radius.is_finite()
        or radius <= 0
    ):
        raise ValueError(f"{subject} decimal disk is invalid")
    precision = max(
        50,
        len(centre.real.as_tuple().digits) + 16,
        len(centre.imaginary.as_tuple().digits) + 16,
        len(radius.as_tuple().digits) + 16,
    )
    with localcontext() as context:
        context.prec = precision
        converted = complex(float(centre.real), float(centre.imaginary))
        if not (
            math.isfinite(converted.real) and math.isfinite(converted.imag)
        ):
            raise ValueError(f"{subject} centre is not binary64-representable")
        rounding = DecimalComplex(
            centre.real - Decimal.from_float(converted.real),
            centre.imaginary - Decimal.from_float(converted.imag),
        ).magnitude()
        required_radius = radius + rounding
        converted_radius = float(required_radius)
        if not math.isfinite(converted_radius):
            raise ValueError(f"{subject} radius is not binary64-representable")
        if Decimal.from_float(converted_radius) < required_radius:
            converted_radius = math.nextafter(converted_radius, math.inf)
        if converted_radius == 0.0:
            converted_radius = math.nextafter(0.0, math.inf)
    return ComplexDisk(converted, converted_radius)


def _authentication_complex_from_mapping(
    value: object, subject: str
) -> DecimalComplex:
    """Parse a worker complex value, preserving its decimal text exactly."""

    if not isinstance(value, Mapping) or set(value) != {"real", "imaginary"}:
        raise ValueError(f"{subject} must carry real and imaginary text")
    return DecimalComplex(
        real=_conditioning_decimal_from_text(value["real"], f"{subject} real"),
        imaginary=_conditioning_decimal_from_text(
            value["imaginary"], f"{subject} imaginary"
        ),
    )


@dataclass(frozen=True, slots=True)
class PrimaryRootAcceptanceEvidence:
    """Exact evidence for the promoted binary64-parity PRIMARY decision."""

    policy_id: str
    acceptance_metric: str
    determinant: DecimalComplex
    derivative: DecimalComplex
    correction_abs: Decimal
    root_correction_tolerance: Decimal
    accepted: bool
    newton_determinant_count: int
    post_newton_determinant_count: int
    determinant_error_abs: Decimal
    error_model_id: str | None
    derivative_authentication: DerivativeAuthenticationEvidence | None = None

    def __post_init__(self) -> None:
        if self.policy_id not in {
            PROMOTED_ROOT_READOUT_POLICY,
            HISTORICAL_PROMOTED_ROOT_READOUT_POLICY,
        }:
            raise ValueError("PRIMARY promoted policy identity is invalid")
        if self.acceptance_metric != PROMOTED_ROOT_ACCEPTANCE_METRIC:
            raise ValueError("PRIMARY acceptance metric identity is invalid")
        if not isinstance(self.determinant, DecimalComplex):
            raise ValueError("PRIMARY determinant evidence is invalid")
        if not isinstance(self.derivative, DecimalComplex):
            raise ValueError("PRIMARY derivative evidence is invalid")
        for name in (
            "correction_abs",
            "root_correction_tolerance",
            "determinant_error_abs",
        ):
            value = getattr(self, name)
            if type(value) is not Decimal or not value.is_finite() or value < 0:
                raise ValueError(f"PRIMARY {name} must be finite and nonnegative")
        if self.root_correction_tolerance <= 0:
            raise ValueError("PRIMARY correction tolerance must be positive")
        if type(self.accepted) is not bool:
            raise ValueError("PRIMARY accepted flag is invalid")
        if (
            type(self.newton_determinant_count) is not int
            or self.newton_determinant_count < 1
        ):
            raise ValueError("PRIMARY Newton determinant count is invalid")
        if (
            type(self.post_newton_determinant_count) is not int
            or self.post_newton_determinant_count != 0
        ):
            raise ValueError("PRIMARY performed post-Newton determinant work")
        if self.error_model_id is None:
            if self.determinant_error_abs != 0:
                raise ValueError(
                    "PRIMARY determinant telemetry lacks its error-model identity"
                )
        elif not isinstance(self.error_model_id, str) or not self.error_model_id:
            raise ValueError("PRIMARY error-model identity is invalid")
        if (
            self.derivative_authentication is not None
            and not isinstance(
                self.derivative_authentication,
                DerivativeAuthenticationEvidence,
            )
        ):
            raise ValueError("PRIMARY derivative authentication is invalid")
        if (
            self.derivative_authentication is not None
            and self.derivative_authentication.derivative_estimate != self.derivative
        ):
            raise ValueError(
                "PRIMARY derivative authentication disagrees with derivative"
            )
        with localcontext() as context:
            context.prec = _ROOT_AUTHENTICATION_CHECK_DIGITS
            derivative_abs = self.derivative.magnitude()
            if derivative_abs <= 0:
                raise ValueError("PRIMARY derivative magnitude must be positive")
            expected_correction = self.determinant.magnitude() / derivative_abs
            if not _authentication_relation_matches(
                self.correction_abs, expected_correction
            ):
                raise ValueError("PRIMARY raw correction is inconsistent")
            if self.accepted != (
                self.correction_abs <= self.root_correction_tolerance
            ):
                raise ValueError("PRIMARY acceptance decision is inconsistent")

    def to_mapping(self) -> dict[str, object]:
        output = {
            "policy_id": self.policy_id,
            "acceptance_metric": self.acceptance_metric,
            "determinant_re": str(self.determinant.real),
            "determinant_im": str(self.determinant.imaginary),
            "derivative_re": str(self.derivative.real),
            "derivative_im": str(self.derivative.imaginary),
            "correction_abs": str(self.correction_abs),
            "root_correction_tolerance": str(self.root_correction_tolerance),
            "accepted": self.accepted,
            "newton_determinant_count": self.newton_determinant_count,
            "post_newton_determinant_count": (
                self.post_newton_determinant_count
            ),
            "determinant_error_abs": str(self.determinant_error_abs),
            "error_model_id": self.error_model_id,
        }
        if self.derivative_authentication is not None:
            output["derivative_authentication"] = (
                self.derivative_authentication.to_mapping()
            )
        return output

    @classmethod
    def from_mapping(cls, value: object) -> "PrimaryRootAcceptanceEvidence":
        fields = {
            "policy_id",
            "acceptance_metric",
            "determinant_re",
            "determinant_im",
            "derivative_re",
            "derivative_im",
            "correction_abs",
            "root_correction_tolerance",
            "accepted",
            "newton_determinant_count",
            "post_newton_determinant_count",
            "determinant_error_abs",
            "error_model_id",
        }
        if (
            not isinstance(value, Mapping)
            or set(value) not in (fields, fields | {"derivative_authentication"})
        ):
            raise ValueError("PRIMARY acceptance evidence fields are invalid")
        if type(value["accepted"]) is not bool:
            raise ValueError("PRIMARY accepted flag is invalid")
        return cls(
            policy_id=str(value["policy_id"]),
            acceptance_metric=str(value["acceptance_metric"]),
            determinant=DecimalComplex(
                _conditioning_decimal_from_text(
                    value["determinant_re"], "PRIMARY determinant real"
                ),
                _conditioning_decimal_from_text(
                    value["determinant_im"], "PRIMARY determinant imaginary"
                ),
            ),
            derivative=DecimalComplex(
                _conditioning_decimal_from_text(
                    value["derivative_re"], "PRIMARY derivative real"
                ),
                _conditioning_decimal_from_text(
                    value["derivative_im"], "PRIMARY derivative imaginary"
                ),
            ),
            correction_abs=_conditioning_decimal_from_text(
                value["correction_abs"], "PRIMARY correction"
            ),
            root_correction_tolerance=_conditioning_decimal_from_text(
                value["root_correction_tolerance"], "PRIMARY tolerance"
            ),
            accepted=value["accepted"],
            newton_determinant_count=value["newton_determinant_count"],
            post_newton_determinant_count=(
                value["post_newton_determinant_count"]
            ),
            determinant_error_abs=_conditioning_decimal_from_text(
                value["determinant_error_abs"],
                "PRIMARY determinant error telemetry",
            ),
            error_model_id=value["error_model_id"],
            derivative_authentication=(
                None
                if value.get("derivative_authentication") is None
                else DerivativeAuthenticationEvidence.from_mapping(
                    value["derivative_authentication"]
                )
            ),
        )


@dataclass(frozen=True, slots=True)
class FixedRootDiagnosticEvidence:
    """One fixed-frequency determinant checked with the complex PRIMARY D′."""

    policy_id: str
    acceptance_metric: str
    root_phase: str
    determinant: DecimalComplex
    primary_derivative: DecimalComplex
    correction_abs: Decimal
    root_correction_tolerance: Decimal
    determinant_error_abs: Decimal
    error_model_id: str | None
    control_identity: str
    branch_identity: str
    branch_authenticated: bool
    determinant_count: int
    accepted: bool
    fixed_root: bool
    derivative_source: str

    def __post_init__(self) -> None:
        if self.policy_id not in {
            PROMOTED_ROOT_READOUT_POLICY,
            HISTORICAL_PROMOTED_ROOT_READOUT_POLICY,
        }:
            raise ValueError("fixed-root promoted policy identity is invalid")
        if self.acceptance_metric != PROMOTED_ROOT_ACCEPTANCE_METRIC:
            raise ValueError("fixed-root acceptance metric is invalid")
        if self.root_phase not in {"TRUNCATION", "RESOLUTION"}:
            raise ValueError("fixed-root diagnostic phase is invalid")
        if not isinstance(self.determinant, DecimalComplex):
            raise ValueError("fixed-root determinant evidence is invalid")
        if not isinstance(self.primary_derivative, DecimalComplex):
            raise ValueError("fixed-root PRIMARY derivative evidence is invalid")
        if self.fixed_root is not True:
            raise ValueError("fixed-root diagnostic moved the PRIMARY frequency")
        if self.derivative_source != "PRIMARY_COMPLEX":
            raise ValueError("fixed-root derivative source is invalid")
        if type(self.determinant_count) is not int or self.determinant_count != 1:
            raise ValueError("fixed-root diagnostic determinant count is not one")
        if type(self.branch_authenticated) is not bool or type(self.accepted) is not bool:
            raise ValueError("fixed-root boolean evidence is invalid")
        for name in ("control_identity", "branch_identity"):
            if not isinstance(getattr(self, name), str) or not getattr(self, name):
                raise ValueError(f"fixed-root {name} is invalid")
        for name in (
            "correction_abs",
            "root_correction_tolerance",
            "determinant_error_abs",
        ):
            item = getattr(self, name)
            if type(item) is not Decimal or not item.is_finite() or item < 0:
                raise ValueError(f"fixed-root {name} is invalid")
        if self.root_correction_tolerance <= 0:
            raise ValueError("fixed-root correction tolerance must be positive")
        if self.error_model_id is None:
            if self.determinant_error_abs != 0:
                raise ValueError("fixed-root error telemetry lacks its model")
        elif not isinstance(self.error_model_id, str) or not self.error_model_id:
            raise ValueError("fixed-root error-model identity is invalid")
        with localcontext() as context:
            context.prec = _ROOT_AUTHENTICATION_CHECK_DIGITS
            derivative_abs = self.primary_derivative.magnitude()
            if derivative_abs <= 0:
                raise ValueError("fixed-root PRIMARY derivative is zero")
            expected = self.determinant.magnitude() / derivative_abs
            if not _authentication_relation_matches(self.correction_abs, expected):
                raise ValueError("fixed-root raw correction is inconsistent")
            expected_accepted = (
                self.branch_authenticated
                and self.correction_abs <= self.root_correction_tolerance
            )
            if self.accepted != expected_accepted:
                raise ValueError("fixed-root acceptance decision is inconsistent")

    def to_mapping(self) -> dict[str, object]:
        return {
            "policy_id": self.policy_id,
            "acceptance_metric": self.acceptance_metric,
            "root_phase": self.root_phase,
            "determinant_re": str(self.determinant.real),
            "determinant_im": str(self.determinant.imaginary),
            "primary_derivative_re": str(self.primary_derivative.real),
            "primary_derivative_im": str(self.primary_derivative.imaginary),
            "correction_abs": str(self.correction_abs),
            "root_correction_tolerance": str(self.root_correction_tolerance),
            "determinant_error_abs": str(self.determinant_error_abs),
            "error_model_id": self.error_model_id,
            "control_identity": self.control_identity,
            "branch_identity": self.branch_identity,
            "branch_authenticated": self.branch_authenticated,
            "determinant_count": self.determinant_count,
            "accepted": self.accepted,
            "fixed_root": self.fixed_root,
            "derivative_source": self.derivative_source,
        }

    @classmethod
    def from_mapping(cls, value: object) -> "FixedRootDiagnosticEvidence":
        fields = {
            "policy_id",
            "acceptance_metric",
            "root_phase",
            "determinant_re",
            "determinant_im",
            "primary_derivative_re",
            "primary_derivative_im",
            "correction_abs",
            "root_correction_tolerance",
            "determinant_error_abs",
            "error_model_id",
            "control_identity",
            "branch_identity",
            "branch_authenticated",
            "determinant_count",
            "accepted",
            "fixed_root",
            "derivative_source",
        }
        if not isinstance(value, Mapping) or set(value) != fields:
            raise ValueError("fixed-root diagnostic evidence fields are invalid")
        return cls(
            policy_id=str(value["policy_id"]),
            acceptance_metric=str(value["acceptance_metric"]),
            root_phase=str(value["root_phase"]),
            determinant=DecimalComplex(
                _conditioning_decimal_from_text(
                    value["determinant_re"], "fixed-root determinant real"
                ),
                _conditioning_decimal_from_text(
                    value["determinant_im"], "fixed-root determinant imaginary"
                ),
            ),
            primary_derivative=DecimalComplex(
                _conditioning_decimal_from_text(
                    value["primary_derivative_re"],
                    "fixed-root PRIMARY derivative real",
                ),
                _conditioning_decimal_from_text(
                    value["primary_derivative_im"],
                    "fixed-root PRIMARY derivative imaginary",
                ),
            ),
            correction_abs=_conditioning_decimal_from_text(
                value["correction_abs"], "fixed-root correction"
            ),
            root_correction_tolerance=_conditioning_decimal_from_text(
                value["root_correction_tolerance"], "fixed-root tolerance"
            ),
            determinant_error_abs=_conditioning_decimal_from_text(
                value["determinant_error_abs"],
                "fixed-root determinant error telemetry",
            ),
            error_model_id=value["error_model_id"],
            control_identity=str(value["control_identity"]),
            branch_identity=str(value["branch_identity"]),
            branch_authenticated=value["branch_authenticated"],
            determinant_count=value["determinant_count"],
            accepted=value["accepted"],
            fixed_root=value["fixed_root"],
            derivative_source=str(value["derivative_source"]),
        )


@dataclass(frozen=True, slots=True)
class DeterminantErrorEvidence:
    """The absolute components aggregated into one determinant error bound.

    Every component is absolute. None is divided by ``|D|``: near a QNM the
    determinant is small by construction, so a relative measure would report
    catastrophic error exactly where the answer is best.

    ``control``, ``equivalence`` and ``precision`` are optional because they
    require a second evaluation that a given call may not have performed. The
    endpoint term is always present for a horizon determinant -- it comes from
    the reference/verification endpoint pair the geometry gate guarantees.
    """

    endpoint_disagreement_abs: Decimal
    control_disagreement_abs: Decimal | None
    equivalence_disagreement_abs: Decimal | None
    precision_disagreement_abs: Decimal | None
    safety_factor: Decimal
    numerical_error_abs: Decimal
    error_model_id: str

    def __post_init__(self) -> None:
        required = ("endpoint_disagreement_abs", "safety_factor",
                    "numerical_error_abs")
        for name in required:
            value = getattr(self, name)
            if type(value) is not Decimal or not value.is_finite() or value < 0:
                raise ValueError(
                    f"determinant error breakdown {name} must be a finite "
                    "nonnegative decimal"
                )
        if self.safety_factor <= 0:
            raise ValueError(
                "determinant error breakdown safety factor must be positive"
            )
        for name in ("control_disagreement_abs", "equivalence_disagreement_abs",
                     "precision_disagreement_abs"):
            value = getattr(self, name)
            if value is None:
                continue
            if type(value) is not Decimal or not value.is_finite() or value < 0:
                raise ValueError(
                    f"determinant error breakdown {name} must be a finite "
                    "nonnegative decimal"
                )
        if not isinstance(self.error_model_id, str) or not self.error_model_id:
            raise ValueError(
                "determinant error evidence error_model_id must be nonempty"
            )
        self._check_aggregate()

    def components(self) -> tuple[Decimal, ...]:
        """Return the components the reported bound is the maximum over."""

        optional = (
            self.control_disagreement_abs,
            self.equivalence_disagreement_abs,
            self.precision_disagreement_abs,
        )
        return (self.endpoint_disagreement_abs,) + tuple(
            value for value in optional if value is not None
        )

    def _check_aggregate(self) -> None:
        """Reject a bound that does not follow from the components beside it.

        The breakdown exists so an acceptance decision can be re-derived rather
        than trusted. A record whose ``numerical_error_abs`` does not follow
        from its own parts defeats that entirely, and it is the one corruption
        a downstream reader cannot notice: the aggregate looks like a perfectly
        ordinary number on its own.

        The comparison is relative, not exact. The worker forms the product in
        binary floating point and serialises the result; re-forming it in
        decimal cannot reproduce those bits. The tolerance is far wider than
        that round trip and far narrower than any corruption that would matter.
        """

        with localcontext() as context:
            context.prec = _ERROR_BUDGET_CHECK_DIGITS
            expected = self.safety_factor * max(self.components())
            if expected == 0:
                if self.numerical_error_abs != 0:
                    raise ValueError(
                        "determinant error breakdown reports a positive bound "
                        "over components that are all zero"
                    )
                return
            if abs(self.numerical_error_abs - expected) > (
                _ERROR_BUDGET_AGGREGATE_TOLERANCE * expected
            ):
                raise ValueError(
                    "determinant error breakdown numerical_error_abs does not "
                    "match its component maximum times the safety factor"
                )

    @classmethod
    def from_mapping(cls, value: object) -> "DeterminantErrorEvidence":
        if not isinstance(value, Mapping) or set(value) != (
            _DETERMINANT_ERROR_EVIDENCE_FIELDS
        ):
            raise ValueError("determinant error evidence fields are invalid")
        optional = {
            "control_disagreement_abs",
            "equivalence_disagreement_abs",
            "precision_disagreement_abs",
        }
        parsed: dict[str, Decimal | None] = {}
        for field in sorted(
            _DETERMINANT_ERROR_EVIDENCE_FIELDS - {"error_model_id"}
        ):
            raw = value[field]
            if field in optional and raw is None:
                parsed[field] = None
                continue
            parsed[field] = _conditioning_decimal_from_text(
                raw, f"determinant error breakdown {field}"
            )
        model = value["error_model_id"]
        if not isinstance(model, str):
            raise ValueError(
                "determinant error evidence error_model_id is invalid"
            )
        return cls(error_model_id=model, **parsed)

    def to_mapping(self) -> dict[str, str | None]:
        """Return the wire form ``from_mapping`` accepts, unchanged."""

        return {
            field: (
                None
                if (value := getattr(self, field)) is None
                else str(value)
            )
            for field in sorted(
                _DETERMINANT_ERROR_EVIDENCE_FIELDS - {"error_model_id"}
            )
        } | {
            "error_model_id": self.error_model_id,
        }


DeterminantErrorBreakdown = DeterminantErrorEvidence


def _authentication_relation_matches(
    actual: Decimal,
    expected: Decimal,
    *source_terms: Decimal,
) -> bool:
    """Compare a serialized bound with its worker-precision derivation."""

    scale = max((abs(actual), abs(expected), *(abs(v) for v in source_terms)))
    if scale == 0:
        return actual == expected
    return abs(actual - expected) <= (
        _ROOT_AUTHENTICATION_RELATIVE_TOLERANCE * scale
    )


@dataclass(frozen=True, slots=True)
class DerivativeAuthenticationEvidence:
    """The accepted derivative and every subtraction in its lower bound."""

    derivative_re: Decimal
    derivative_im: Decimal
    propagated_error_abs: Decimal
    step_disagreement_abs: Decimal
    lower_bound_abs: Decimal
    selected_step: Decimal
    axis: str
    determinant_error_status: str = DETERMINANT_ERROR_UNAVAILABLE
    determinant_error_model_id: str | None = None

    def __post_init__(self) -> None:
        for name in (
            "derivative_re",
            "derivative_im",
            "propagated_error_abs",
            "step_disagreement_abs",
            "lower_bound_abs",
            "selected_step",
        ):
            value = getattr(self, name)
            if type(value) is not Decimal or not value.is_finite():
                raise ValueError(
                    f"derivative authentication {name} must be finite"
                )
        for name in (
            "propagated_error_abs",
            "step_disagreement_abs",
            "lower_bound_abs",
            "selected_step",
        ):
            if getattr(self, name) < 0:
                raise ValueError(
                    f"derivative authentication {name} must be nonnegative"
                )
        if self.lower_bound_abs <= 0:
            raise ValueError(
                "derivative authentication lower bound must be positive"
            )
        if self.selected_step <= 0:
            raise ValueError(
                "derivative authentication selected step must be positive"
            )
        if self.axis not in {"real", "imaginary"}:
            raise ValueError("derivative authentication axis is invalid")
        if self.determinant_error_status not in {
            DETERMINANT_ERROR_AVAILABLE,
            DETERMINANT_ERROR_UNAVAILABLE,
        }:
            raise ValueError("derivative determinant-error status is invalid")
        if self.determinant_error_status == DETERMINANT_ERROR_AVAILABLE:
            if (
                not isinstance(self.determinant_error_model_id, str)
                or not self.determinant_error_model_id
                or self.propagated_error_abs <= 0
            ):
                raise ValueError("available derivative determinant error is invalid")
        elif self.determinant_error_model_id is not None:
            raise ValueError("unavailable derivative determinant error has a model")
        with localcontext() as context:
            context.prec = _ROOT_AUTHENTICATION_CHECK_DIGITS
            derivative_abs = self.derivative_estimate.magnitude()
            expected = (
                derivative_abs
                - self.step_disagreement_abs
                - self.propagated_error_abs
            )
            if not _authentication_relation_matches(
                self.lower_bound_abs,
                expected,
                derivative_abs,
                self.step_disagreement_abs,
                self.propagated_error_abs,
            ):
                raise ValueError(
                    "derivative authentication lower bound is inconsistent"
                )

    @property
    def derivative_estimate(self) -> DecimalComplex:
        return DecimalComplex(self.derivative_re, self.derivative_im)

    @classmethod
    def from_mapping(cls, value: object) -> "DerivativeAuthenticationEvidence":
        admitted_fields = _DERIVATIVE_AUTHENTICATION_FIELDS | {
            "determinant_error_status", "determinant_error_model_id"
        }
        if not isinstance(value, Mapping) or set(value) not in {
            _DERIVATIVE_AUTHENTICATION_FIELDS, admitted_fields
        }:
            raise ValueError("derivative authentication fields are invalid")
        axis = value["axis"]
        if not isinstance(axis, str):
            raise ValueError("derivative authentication axis is invalid")
        return cls(
            axis=axis,
            determinant_error_status=value.get(
                "determinant_error_status", DETERMINANT_ERROR_UNAVAILABLE
            ),
            determinant_error_model_id=value.get("determinant_error_model_id"),
            **{
                field: _conditioning_decimal_from_text(
                    value[field], f"derivative authentication {field}"
                )
                for field in sorted(
                    _DERIVATIVE_AUTHENTICATION_FIELDS - {"axis"}
                )
            },
        )

    def to_mapping(self) -> dict[str, str]:
        return {
            "derivative_re": str(self.derivative_re),
            "derivative_im": str(self.derivative_im),
            "propagated_error_abs": str(self.propagated_error_abs),
            "step_disagreement_abs": str(self.step_disagreement_abs),
            "lower_bound_abs": str(self.lower_bound_abs),
            "selected_step": str(self.selected_step),
            "axis": self.axis,
            "determinant_error_status": self.determinant_error_status,
            "determinant_error_model_id": self.determinant_error_model_id,
        }


@dataclass(frozen=True, slots=True)
class RootAuthenticationEvidence:
    """Closed certificate for the error-aware root-acceptance decision."""

    central_determinant_re: Decimal
    central_determinant_im: Decimal
    determinant_error: DeterminantErrorEvidence | None
    residual_upper_bound_abs: Decimal
    derivative_authentication: DerivativeAuthenticationEvidence
    correction_upper_bound: Decimal
    root_correction_tolerance: Decimal
    accepted: bool
    authentication_strategy: str | None = None
    derivative_real_base: DecimalComplex | None = None
    derivative_real_half: DecimalComplex | None = None
    derivative_real_double: DecimalComplex | None = None
    derivative_imaginary: DecimalComplex | None = None

    def __post_init__(self) -> None:
        for name in (
            "central_determinant_re",
            "central_determinant_im",
            "residual_upper_bound_abs",
            "correction_upper_bound",
            "root_correction_tolerance",
        ):
            value = getattr(self, name)
            if type(value) is not Decimal or not value.is_finite():
                raise ValueError(f"root authentication {name} must be finite")
        for name in (
            "residual_upper_bound_abs",
            "correction_upper_bound",
            "root_correction_tolerance",
        ):
            if getattr(self, name) < 0:
                raise ValueError(
                    f"root authentication {name} must be nonnegative"
                )
        if self.root_correction_tolerance <= 0:
            raise ValueError(
                "root authentication correction tolerance must be positive"
            )
        if self.determinant_error is not None and not isinstance(
            self.determinant_error, DeterminantErrorEvidence
        ):
            raise ValueError("root authentication determinant error is invalid")
        if not isinstance(
            self.derivative_authentication, DerivativeAuthenticationEvidence
        ):
            raise ValueError(
                "root authentication derivative authentication is invalid"
            )
        if type(self.accepted) is not bool:
            raise ValueError("root authentication accepted flag is invalid")
        derivative_evidence = (
            self.derivative_real_base,
            self.derivative_real_half,
            self.derivative_real_double,
            self.derivative_imaginary,
        )
        if self.authentication_strategy is None:
            if any(value is not None for value in derivative_evidence):
                raise ValueError(
                    "legacy root authentication cannot carry staged evidence"
                )
        else:
            if self.authentication_strategy not in {
                STAGED_REAL_AXIS_AUTHENTICATION_STRATEGY,
                FULL_DERIVATIVE_LADDER_AUTHENTICATION_STRATEGY,
            }:
                raise ValueError(
                    "root authentication strategy is invalid"
                )
            if not isinstance(self.derivative_real_base, DecimalComplex):
                raise ValueError(
                    "root authentication real-base derivative is missing"
                )
            if not isinstance(self.derivative_real_half, DecimalComplex):
                raise ValueError(
                    "root authentication real-half derivative is missing"
                )
            for name in ("derivative_real_double", "derivative_imaginary"):
                value = getattr(self, name)
                if value is not None and not isinstance(value, DecimalComplex):
                    raise ValueError(
                        f"root authentication {name} has invalid type"
                    )
            if (
                self.authentication_strategy
                == STAGED_REAL_AXIS_AUTHENTICATION_STRATEGY
            ):
                if (
                    self.derivative_real_double is not None
                    or self.derivative_imaginary is not None
                ):
                    raise ValueError(
                        "staged root authentication fabricated 2h/ih evidence"
                    )
            elif (
                self.derivative_real_double is None
                or self.derivative_imaginary is None
            ):
                raise ValueError(
                    "full root authentication omitted 2h/ih evidence"
                )
            if self.derivative_real_half != self.derivative_estimate:
                raise ValueError(
                    "root authentication selected derivative disagrees "
                    "with h/2 evidence"
                )
        self._check_decision_arithmetic()

    @property
    def central_determinant(self) -> DecimalComplex:
        return DecimalComplex(
            self.central_determinant_re,
            self.central_determinant_im,
        )

    @property
    def error_breakdown(self) -> DeterminantErrorEvidence | None:
        return self.determinant_error

    @property
    def error_model_id(self) -> str | None:
        return (
            None
            if self.determinant_error is None
            else self.determinant_error.error_model_id
        )

    @property
    def derivative_estimate(self) -> DecimalComplex:
        return self.derivative_authentication.derivative_estimate

    @property
    def derivative_propagated_error_abs(self) -> Decimal:
        return self.derivative_authentication.propagated_error_abs

    @property
    def derivative_step_disagreement_abs(self) -> Decimal:
        return self.derivative_authentication.step_disagreement_abs

    @property
    def derivative_lower_bound_abs(self) -> Decimal:
        return self.derivative_authentication.lower_bound_abs

    @property
    def selected_step(self) -> Decimal:
        return self.derivative_authentication.selected_step

    @property
    def derivative_axis(self) -> str:
        return self.derivative_authentication.axis

    def _check_decision_arithmetic(self) -> None:
        with localcontext() as context:
            context.prec = _ROOT_AUTHENTICATION_CHECK_DIGITS
            determinant_abs = self.central_determinant.magnitude()
            determinant_error_abs = (
                Decimal(0)
                if self.determinant_error is None
                else self.determinant_error.numerical_error_abs
            )
            expected_residual = determinant_abs + determinant_error_abs
            if not _authentication_relation_matches(
                self.residual_upper_bound_abs,
                expected_residual,
                determinant_abs,
                determinant_error_abs,
            ):
                raise ValueError(
                    "root authentication residual upper bound is inconsistent"
                )
            expected_correction = (
                self.residual_upper_bound_abs
                / self.derivative_authentication.lower_bound_abs
            )
            if not _authentication_relation_matches(
                self.correction_upper_bound,
                expected_correction,
            ):
                raise ValueError(
                    "root authentication correction upper bound is inconsistent"
                )
            if (
                self.accepted
                and self.correction_upper_bound
                > self.root_correction_tolerance
            ):
                raise ValueError(
                    "root authentication accepted flag is inconsistent"
                )

    def validate_binding(
        self,
        *,
        determinant_abs: Decimal,
        derivative_abs: Decimal,
        expected_error_model_id: str | None,
        root_correction_tolerance: Decimal | None = None,
        accepted: bool | None = None,
    ) -> None:
        """Bind this certificate to result scalars and mechanism policy."""

        if type(determinant_abs) is not Decimal or not determinant_abs.is_finite():
            raise ValueError("root authentication determinant binding is invalid")
        if type(derivative_abs) is not Decimal or not derivative_abs.is_finite():
            raise ValueError("root authentication derivative binding is invalid")
        if determinant_abs < 0 or derivative_abs <= 0:
            raise ValueError("root authentication scalar binding is invalid")
        if self.error_model_id != expected_error_model_id:
            raise ValueError("root authentication error model identity is inconsistent")
        with localcontext() as context:
            context.prec = _ROOT_AUTHENTICATION_CHECK_DIGITS
            certificate_determinant_abs = self.central_determinant.magnitude()
            if not _authentication_relation_matches(
                certificate_determinant_abs,
                determinant_abs,
                determinant_abs,
            ):
                raise ValueError(
                    "root authentication central determinant is inconsistent"
                )
            certificate_derivative_abs = self.derivative_estimate.magnitude()
            if not _authentication_relation_matches(
                certificate_derivative_abs,
                derivative_abs,
                derivative_abs,
            ):
                raise ValueError(
                    "root authentication derivative estimate is inconsistent"
                )
            if root_correction_tolerance is not None and not (
                type(root_correction_tolerance) is Decimal
                and root_correction_tolerance.is_finite()
                and _authentication_relation_matches(
                    self.root_correction_tolerance,
                    root_correction_tolerance,
                    root_correction_tolerance,
                )
            ):
                raise ValueError(
                    "root authentication correction tolerance is inconsistent"
                )
            if accepted is True and not self.accepted:
                raise ValueError(
                    "root authentication acceptance binding is inconsistent"
                )

    @classmethod
    def from_mapping(cls, value: object) -> "RootAuthenticationEvidence":
        if not isinstance(value, Mapping):
            raise ValueError("root authentication fields are invalid")
        field_set = set(value)
        legacy = field_set == _ROOT_AUTHENTICATION_FIELDS
        current = field_set == _ROOT_AUTHENTICATION_FIELDS_V6
        if not (legacy or current):
            raise ValueError("root authentication fields are invalid")
        accepted = value["accepted"]
        if type(accepted) is not bool:
            raise ValueError("root authentication accepted flag is invalid")
        determinant_error_value = value["determinant_error"]

        authentication_strategy: str | None = None
        derivative_real_base: DecimalComplex | None = None
        derivative_real_half: DecimalComplex | None = None
        derivative_real_double: DecimalComplex | None = None
        derivative_imaginary: DecimalComplex | None = None
        if current:
            authentication_strategy_value = value["authentication_strategy"]
            if not isinstance(authentication_strategy_value, str):
                raise ValueError(
                    "root authentication strategy is invalid"
                )
            authentication_strategy = authentication_strategy_value
            derivative_evidence = value["derivative_evidence"]
            if (
                not isinstance(derivative_evidence, Mapping)
                or set(derivative_evidence)
                != _ROOT_DERIVATIVE_EVIDENCE_FIELDS
            ):
                raise ValueError(
                    "root derivative evidence fields are invalid"
                )

            def parsed_derivative(
                name: str, *, required: bool
            ) -> DecimalComplex | None:
                raw = derivative_evidence[name]
                if raw is None:
                    if required:
                        raise ValueError(
                            f"root derivative evidence {name} is missing"
                        )
                    return None
                return _authentication_complex_from_mapping(
                    raw, f"root derivative evidence {name}"
                )

            derivative_real_base = parsed_derivative(
                "real_base", required=True
            )
            derivative_real_half = parsed_derivative(
                "real_half", required=True
            )
            derivative_real_double = parsed_derivative(
                "real_double", required=False
            )
            derivative_imaginary = parsed_derivative(
                "imaginary", required=False
            )

        return cls(
            central_determinant_re=_conditioning_decimal_from_text(
                value["central_determinant_re"],
                "root authentication central determinant real",
            ),
            central_determinant_im=_conditioning_decimal_from_text(
                value["central_determinant_im"],
                "root authentication central determinant imaginary",
            ),
            determinant_error=(
                None
                if determinant_error_value is None
                else DeterminantErrorEvidence.from_mapping(
                    determinant_error_value
                )
            ),
            residual_upper_bound_abs=_conditioning_decimal_from_text(
                value["residual_upper_bound_abs"],
                "root authentication residual upper bound",
            ),
            derivative_authentication=(
                DerivativeAuthenticationEvidence.from_mapping(
                    value["derivative_authentication"]
                )
            ),
            correction_upper_bound=_conditioning_decimal_from_text(
                value["correction_upper_bound"],
                "root authentication correction upper bound",
            ),
            root_correction_tolerance=_conditioning_decimal_from_text(
                value["root_correction_tolerance"],
                "root authentication correction tolerance",
            ),
            accepted=accepted,
            authentication_strategy=authentication_strategy,
            derivative_real_base=derivative_real_base,
            derivative_real_half=derivative_real_half,
            derivative_real_double=derivative_real_double,
            derivative_imaginary=derivative_imaginary,
        )

    def to_mapping(self) -> dict[str, object]:
        output: dict[str, object] = {
            "central_determinant_re": str(self.central_determinant_re),
            "central_determinant_im": str(self.central_determinant_im),
            "determinant_error": (
                None
                if self.determinant_error is None
                else self.determinant_error.to_mapping()
            ),
            "residual_upper_bound_abs": str(self.residual_upper_bound_abs),
            "derivative_authentication": (
                self.derivative_authentication.to_mapping()
            ),
            "correction_upper_bound": str(self.correction_upper_bound),
            "root_correction_tolerance": str(
                self.root_correction_tolerance
            ),
            "accepted": self.accepted,
        }
        if self.authentication_strategy is not None:
            output["authentication_strategy"] = (
                self.authentication_strategy
            )
            output["derivative_evidence"] = {
                "real_base": self.derivative_real_base.to_mapping(),
                "real_half": self.derivative_real_half.to_mapping(),
                "real_double": (
                    None
                    if self.derivative_real_double is None
                    else self.derivative_real_double.to_mapping()
                ),
                "imaginary": (
                    None
                    if self.derivative_imaginary is None
                    else self.derivative_imaginary.to_mapping()
                ),
            }
        return output


@dataclass(frozen=True, slots=True)
class NumericalConditioningEvidence:
    schema: str
    determinant_family: str
    scattering_diagnostics_applicable: bool
    homogeneous_representation: str
    branch_convention: str
    scattering_column_convention: str | None
    radial_derivative_convention: str
    determinant_convention: str
    determinant_normalisation: str
    regular_remainder_contract: str
    factored_remainder_state_convention: str
    maximum_series_digits_lost: Decimal
    maximum_recurrence_digits_lost: Decimal
    maximum_series_evaluation_spread: Decimal
    maximum_last_term_ratio: Decimal
    minimum_asymptotic_predicted_reliable_digits: Decimal
    maximum_basis_condition: Decimal | None
    maximum_basis_backward_error: Decimal | None
    maximum_matching_reconstruction_residual: Decimal | None
    endpoint_remainders_regular: bool
    maximum_endpoint_reconstruction_error: Decimal
    maximum_fd_digits_lost: Decimal
    predicted_reliable_digits: Decimal
    required_reliable_digits: Decimal
    precision_limited: bool
    asymptotic_preflight_avoided_ode: bool
    minimum_cref_chart_margin: Decimal | None
    maximum_carrier_change_error: Decimal | None
    maximum_contour_angle_deformation: Decimal
    human_math_review_receipt_status: str | None = None
    human_math_review_receipt_sha256: str | None = None
    independent_reference_fixture_receipt_status: str | None = None
    independent_reference_fixture_receipt_sha256: str | None = None

    def __post_init__(self) -> None:
        if self.schema not in {
            NUMERICAL_CONDITIONING_SCHEMA,
            HISTORICAL_NUMERICAL_CONDITIONING_SCHEMA,
        }:
            raise ValueError("numerical conditioning schema is invalid")
        for field, expected in _REGULARISED_GSN_COMMON_IDENTITIES.items():
            if field == "homogeneous_representation":
                # Family-dependent: the horizon determinant builds a three-leg
                # solution basis on a verified real-inner contour, which is a
                # different calculation from the exterior Wronskian's single
                # factored representation.
                continue
            if getattr(self, field) != expected:
                raise ValueError(
                    f"numerical conditioning {field} identity is invalid"
                )
        expected_representation = (
            HORIZON_HOMOGENEOUS_REPRESENTATION
            if self.determinant_family == HORIZON_DETERMINANT_FAMILY
            else _REGULARISED_GSN_COMMON_IDENTITIES[
                "homogeneous_representation"
            ]
        )
        if self.homogeneous_representation != expected_representation:
            raise ValueError(
                "numerical conditioning homogeneous_representation identity "
                "is invalid"
            )
        if self.schema == NUMERICAL_CONDITIONING_SCHEMA:
            for field in _NUMERICAL_CONDITIONING_GATE_FIELDS:
                expected = _REGULARISED_GSN_COMMON_PRECISION_POLICY[field]
                if getattr(self, field) != expected:
                    raise ValueError(
                        f"numerical conditioning {field} identity is invalid"
                    )
        elif any(
            getattr(self, field) is not None
            for field in _NUMERICAL_CONDITIONING_GATE_FIELDS
        ):
            raise ValueError(
                "historical numerical conditioning cannot contain gate identities"
            )
        if type(self.scattering_diagnostics_applicable) is not bool:
            raise ValueError(
                "numerical conditioning scattering_diagnostics_applicable "
                "must be a built-in bool"
            )
        if self.scattering_diagnostics_applicable:
            expected_contract = regularised_gsn_mechanism_contract(
                "horizon-admittance"
            )
        else:
            expected_contract = regularised_gsn_mechanism_contract(
                "exterior-fixed-r3"
            )
        for field, expected in expected_contract.items():
            if getattr(self, field) != expected:
                raise ValueError(
                    f"numerical conditioning {field} is inconsistent with "
                    "scattering_diagnostics_applicable"
                )
        for field in _NUMERICAL_CONDITIONING_DECIMAL_FIELDS:
            value = getattr(self, field)
            if field in _HORIZON_SCATTERING_DECIMAL_FIELDS:
                if not self.scattering_diagnostics_applicable:
                    if value is not None:
                        raise ValueError(
                            f"numerical conditioning {field} must be null "
                            "when scattering diagnostics are not applicable"
                        )
                    continue
                if value is None:
                    raise ValueError(
                        f"numerical conditioning {field} is required when "
                        "scattering diagnostics are applicable"
                    )
            if type(value) is not Decimal or not value.is_finite():
                raise ValueError(
                    f"numerical conditioning {field} must be a finite Decimal"
                )
            if (
                field not in _NUMERICAL_CONDITIONING_SIGNED_DECIMAL_FIELDS
                and value < 0
            ):
                raise ValueError(
                    f"numerical conditioning {field} must be nonnegative"
                )
        for field in _NUMERICAL_CONDITIONING_BOOLEAN_FIELDS:
            if type(getattr(self, field)) is not bool:
                raise ValueError(
                    f"numerical conditioning {field} must be a built-in bool"
                )
        expected_precision_limited = (
            self.predicted_reliable_digits < self.required_reliable_digits
        )
        if self.precision_limited != expected_precision_limited:
            raise ValueError(
                "numerical conditioning precision_limited must equal "
                "predicted_reliable_digits < required_reliable_digits"
            )

    def to_mapping(self) -> dict[str, object]:
        output: dict[str, object] = {
            "schema": self.schema,
            "scattering_diagnostics_applicable": (
                self.scattering_diagnostics_applicable
            ),
            **{
                field: getattr(self, field)
                for field in _NUMERICAL_CONDITIONING_IDENTITY_FIELDS
            },
        }
        if self.schema == NUMERICAL_CONDITIONING_SCHEMA:
            output.update({
                field: getattr(self, field)
                for field in _NUMERICAL_CONDITIONING_GATE_FIELDS
            })
        for field in _NUMERICAL_CONDITIONING_DECIMAL_FIELDS:
            value = getattr(self, field)
            output[field] = None if value is None else str(value)
        for field in _NUMERICAL_CONDITIONING_BOOLEAN_FIELDS:
            output[field] = getattr(self, field)
        return output

    @classmethod
    def from_mapping(cls, value: object) -> "NumericalConditioningEvidence":
        if not isinstance(value, Mapping):
            raise ValueError("numerical conditioning evidence fields are invalid")
        schema = value.get("schema")
        if schema not in {
            NUMERICAL_CONDITIONING_SCHEMA,
            HISTORICAL_NUMERICAL_CONDITIONING_SCHEMA,
        }:
            raise ValueError("numerical conditioning schema is invalid")
        gate_fields = (
            _NUMERICAL_CONDITIONING_GATE_FIELDS
            if schema == NUMERICAL_CONDITIONING_SCHEMA
            else ()
        )
        expected_fields = {
            "schema",
            "scattering_diagnostics_applicable",
            *_NUMERICAL_CONDITIONING_IDENTITY_FIELDS,
            *gate_fields,
            *_NUMERICAL_CONDITIONING_DECIMAL_FIELDS,
            *_NUMERICAL_CONDITIONING_BOOLEAN_FIELDS,
        }
        if set(value) != expected_fields:
            raise ValueError("numerical conditioning evidence fields are invalid")
        applicability = value["scattering_diagnostics_applicable"]
        if type(applicability) is not bool:
            raise ValueError(
                "numerical conditioning scattering_diagnostics_applicable "
                "must be a built-in bool"
            )
        decimal_values: dict[str, Decimal | None] = {}
        for field in _NUMERICAL_CONDITIONING_DECIMAL_FIELDS:
            raw = value[field]
            if field in _HORIZON_SCATTERING_DECIMAL_FIELDS and raw is None:
                decimal_values[field] = None
            else:
                decimal_values[field] = _conditioning_decimal_from_text(
                    raw, f"numerical conditioning {field}"
                )
        boolean_values: dict[str, bool] = {}
        for field in _NUMERICAL_CONDITIONING_BOOLEAN_FIELDS:
            raw = value[field]
            if type(raw) is not bool:
                raise ValueError(
                    f"numerical conditioning {field} must be a built-in bool"
                )
            boolean_values[field] = raw
        return cls(
            schema=value["schema"],
            scattering_diagnostics_applicable=applicability,
            **{
                field: value[field]
                for field in _NUMERICAL_CONDITIONING_IDENTITY_FIELDS
            },
            **{field: value[field] for field in gate_fields},
            **decimal_values,
            **boolean_values,
        )


@dataclass(frozen=True, slots=True)
class RootReadout:
    omega: complex
    determinant_residual_abs: float
    determinant_derivative_abs: float
    converged: bool
    root_reference_id: str
    branch_id: str
    equation_id: str
    truncation_radius: float | None = 0.0
    resolution_radius: float | None = 0.0
    seed_path_radius: float | None = 0.0
    diagnostic_readouts: Mapping[str, DiagnosticRootReadout] | None = None
    source_root_mapping: Mapping[str, object] | None = None
    diagnostics_skipped_reason: str | None = None
    numerical_conditioning: NumericalConditioningEvidence | None = None
    normalised_determinant_abs: Decimal | None = None
    raw_determinant_abs: Decimal | None = None
    raw_determinant_evidence_status: str | None = None
    worker_response_receipt: Mapping[str, object] | None = None
    # Historical error-aware acceptance terms. Current promoted readouts carry
    # their raw binary64-parity decision in ``primary_acceptance`` below. Both
    # forms survive the backend so persisted convergence can be re-checked.
    root_authentication: RootAuthenticationEvidence | None = None
    promoted_root_readout_policy: str | None = None
    primary_acceptance: PrimaryRootAcceptanceEvidence | None = None
    seed_path_required: bool | None = None
    seed_path_executed: bool | None = None
    seed_path_determinant_count: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "omega", _finite_complex(self.omega, "root omega"))
        for name in ("determinant_residual_abs", "determinant_derivative_abs"):
            value = float(getattr(self, name))
            if not math.isfinite(value) or value < 0.0:
                raise ValueError(f"{name} must be finite and nonnegative")
            object.__setattr__(self, name, value)
        for name in ("truncation_radius", "resolution_radius", "seed_path_radius"):
            raw = getattr(self, name)
            if raw is None:
                continue
            value = float(raw)
            if not math.isfinite(value) or value < 0.0:
                raise ValueError(f"{name} must be finite and nonnegative")
            object.__setattr__(self, name, value)
        if self.determinant_derivative_abs <= 0.0:
            raise ValueError("determinant derivative must be positive")
        if type(self.converged) is not bool:
            raise ValueError("converged must be a built-in bool")
        if not self.root_reference_id or not self.branch_id or not self.equation_id:
            raise ValueError("root readout identity fields must be nonempty")
        if (
            self.numerical_conditioning is not None
            and not isinstance(
                self.numerical_conditioning, NumericalConditioningEvidence
            )
        ):
            raise ValueError("root readout numerical conditioning has invalid type")
        if self.root_authentication is not None and not isinstance(
            self.root_authentication, RootAuthenticationEvidence
        ):
            raise ValueError("root readout root authentication has invalid type")
        promoted = self.promoted_root_readout_policy is not None
        if promoted:
            if self.promoted_root_readout_policy not in {
                PROMOTED_ROOT_READOUT_POLICY,
                HISTORICAL_PROMOTED_ROOT_READOUT_POLICY,
            }:
                raise ValueError("root readout promoted policy identity is invalid")
            if not isinstance(
                self.primary_acceptance, PrimaryRootAcceptanceEvidence
            ):
                raise ValueError("root readout PRIMARY acceptance is missing")
            if self.root_authentication is not None:
                raise ValueError(
                    "binary64-parity readout cannot carry legacy authentication"
                )
            if (
                self.seed_path_required is not False
                or self.seed_path_executed is not False
                or self.seed_path_determinant_count != 0
                or self.seed_path_radius is not None
            ):
                raise ValueError("root readout SEED-PATH omission is inconsistent")
            with localcontext() as context:
                context.prec = _ROOT_AUTHENTICATION_CHECK_DIGITS
                primary_residual = self.primary_acceptance.determinant.magnitude()
                primary_derivative = self.primary_acceptance.derivative.magnitude()
            if (
                self.normalised_determinant_abs is None
                or not _authentication_relation_matches(
                    self.normalised_determinant_abs,
                    primary_residual,
                    primary_residual,
                )
                or not math.isclose(
                    self.determinant_derivative_abs,
                    float(primary_derivative),
                    rel_tol=1.0e-15,
                    abs_tol=0.0,
                )
            ):
                raise ValueError(
                    "root readout scalars disagree with PRIMARY acceptance"
                )
            if self.converged and not self.primary_acceptance.accepted:
                raise ValueError(
                    "converged root readout has rejected PRIMARY acceptance"
                )
        elif any(
            value is not None
            for value in (
                self.primary_acceptance,
                self.seed_path_required,
                self.seed_path_executed,
                self.seed_path_determinant_count,
            )
        ):
            raise ValueError(
                "promoted root evidence requires its policy identity"
            )
        for name in ("normalised_determinant_abs", "raw_determinant_abs"):
            value = getattr(self, name)
            if value is None:
                continue
            if type(value) is not Decimal or not value.is_finite() or value < 0:
                raise ValueError(
                    f"{name} must be a finite nonnegative Decimal or None"
                )
        if (
            self.raw_determinant_evidence_status is not None
            and not isinstance(self.raw_determinant_evidence_status, str)
        ):
            raise ValueError("raw determinant evidence status has invalid type")
        if self.numerical_conditioning is not None:
            if self.numerical_conditioning.scattering_diagnostics_applicable:
                if self.raw_determinant_evidence_status is None:
                    if self.raw_determinant_abs is None:
                        raise ValueError(
                            "raw_determinant_abs is required for horizon scattering"
                        )
                elif self.raw_determinant_evidence_status == "available/v1":
                    if self.raw_determinant_abs is None:
                        raise ValueError(
                            "available raw_determinant_abs is required for "
                            "horizon scattering"
                        )
                elif self.raw_determinant_evidence_status == "unavailable-overflow/v1":
                    if self.raw_determinant_abs is not None:
                        raise ValueError(
                            "unavailable raw determinant evidence must not "
                            "carry raw_determinant_abs"
                        )
                else:
                    raise ValueError(
                        "raw_determinant_evidence_status is required for "
                        "horizon scattering"
                    )
            elif self.raw_determinant_evidence_status is None:
                if self.raw_determinant_abs is not None:
                    raise ValueError(
                        "raw_determinant_abs must be null for an exterior "
                        "Wronskian"
                    )
            elif (
                self.raw_determinant_evidence_status != "not-applicable/v1"
                or self.raw_determinant_abs is not None
            ):
                raise ValueError(
                    "exterior Wronskians require not-applicable raw determinant "
                    "evidence"
                )
        elif self.raw_determinant_evidence_status is not None:
            raise ValueError(
                "raw determinant evidence status requires numerical conditioning"
            )
        receipt = _validated_worker_response_receipt(
            self.worker_response_receipt
        )
        if receipt is not None:
            authentication_wire = (
                receipt["worker_response_schema_version"]
                in _ROOT_AUTHENTICATION_WIRE_SCHEMAS
            )
            if authentication_wire != (self.root_authentication is not None):
                raise ValueError(
                    "worker response receipt authentication schema is "
                    "inconsistent"
                )
            if (
                self.normalised_determinant_abs is None
                or Decimal(receipt["root_residual_abs_text"])
                != self.normalised_determinant_abs
                or (
                    None
                    if receipt["raw_determinant_abs_text"] is None
                    else Decimal(receipt["raw_determinant_abs_text"])
                )
                != self.raw_determinant_abs
                or receipt["raw_determinant_evidence_status"]
                != self.raw_determinant_evidence_status
            ):
                raise ValueError(
                    "worker response receipt disagrees with root readout evidence"
                )
            if receipt["schema"] == WORKER_RESPONSE_RECEIPT_SCHEMA:
                if (
                    not promoted
                    or receipt["promoted_root_readout_policy"]
                    != self.promoted_root_readout_policy
                    or receipt["primary_acceptance_sha256"]
                    != _sha256(self.primary_acceptance.to_mapping())
                ):
                    raise ValueError(
                        "worker response receipt disagrees with promoted acceptance"
                    )
            copied_receipt = dict(receipt)
            copied_receipt["request_binding"] = MappingProxyType(
                dict(receipt["request_binding"])
            )
            object.__setattr__(
                self,
                "worker_response_receipt",
                MappingProxyType(copied_receipt),
            )
        if (
            self.normalised_determinant_abs is not None
            and float(self.normalised_determinant_abs)
            != self.determinant_residual_abs
        ):
            raise ValueError(
                "normalised_determinant_abs disagrees with "
                "determinant_residual_abs"
            )
        authentication = self.root_authentication
        if authentication is not None:
            if (
                self.numerical_conditioning is None
                or self.normalised_determinant_abs is None
            ):
                raise ValueError(
                    "root authentication requires a conditioned root readout"
                )
            expected_error_model_id = (
                VERIFIED_ENDPOINT_ERROR_MODEL
                if self.numerical_conditioning.scattering_diagnostics_applicable
                else None
            )
            if authentication.error_model_id != expected_error_model_id:
                raise ValueError(
                    "root authentication model disagrees with root readout"
                )
            if self.converged and not authentication.accepted:
                raise ValueError(
                    "root authentication acceptance disagrees with root readout"
                )
            with localcontext() as context:
                context.prec = _ROOT_AUTHENTICATION_CHECK_DIGITS
                if not _authentication_relation_matches(
                    authentication.central_determinant.magnitude(),
                    self.normalised_determinant_abs,
                    self.normalised_determinant_abs,
                ):
                    raise ValueError(
                        "root authentication determinant disagrees with root "
                        "readout"
                    )
                derivative_abs = float(
                    authentication.derivative_estimate.magnitude()
                )
            if not math.isclose(
                derivative_abs,
                self.determinant_derivative_abs,
                rel_tol=1.0e-15,
                abs_tol=0.0,
            ):
                raise ValueError(
                    "root authentication derivative disagrees with root readout"
                )
            if receipt is not None:
                request_policy = receipt["request_binding"].get("policy")
                if not isinstance(request_policy, Mapping):
                    raise ValueError(
                        "root authentication receipt policy is invalid"
                    )
                correction_tolerance = _conditioning_decimal_from_text(
                    request_policy.get("root_correction_tolerance"),
                    "root authentication receipt correction tolerance",
                )
                if (
                    correction_tolerance <= 0
                    or not _authentication_relation_matches(
                        authentication.root_correction_tolerance,
                        correction_tolerance,
                        correction_tolerance,
                    )
                ):
                    raise ValueError(
                        "root authentication correction target disagrees with "
                        "the root readout receipt"
                    )
        object.__setattr__(
            self,
            "source_root_mapping",
            _validated_source_root_mapping(self.source_root_mapping),
        )
        diagnostics = self.diagnostic_readouts
        diagnostics_were_skipped = (
            isinstance(diagnostics, Mapping)
            and not diagnostics
            and self.diagnostics_skipped_reason == "PRIMARY_NOT_CONVERGED"
            and not self.converged
        )
        if diagnostics is None or diagnostics_were_skipped:
            object.__setattr__(self, "diagnostic_readouts", MappingProxyType({}))
        else:
            expected_diagnostic_families = (
                _PROMOTED_FIXED_ROOT_DIAGNOSTIC_FAMILIES
                if promoted
                else _DIAGNOSTIC_ROOT_FAMILIES
            )
            if not isinstance(diagnostics, Mapping) or set(diagnostics) != set(
                expected_diagnostic_families
            ):
                raise ValueError("diagnostic root readouts are incomplete")
            copied: dict[str, DiagnosticRootReadout] = {}
            for family in expected_diagnostic_families:
                readout = diagnostics[family]
                if not isinstance(readout, DiagnosticRootReadout):
                    raise ValueError("diagnostic root readout has invalid type")
                if promoted:
                    evidence = readout.fixed_root_evidence
                    if (
                        evidence is None
                        or evidence.root_phase
                        != {
                            "truncation": "TRUNCATION",
                            "resolution": "RESOLUTION",
                        }[family]
                        or evidence.primary_derivative
                        != self.primary_acceptance.derivative
                    ):
                        raise ValueError(
                            "fixed-root diagnostic did not reuse PRIMARY derivative"
                        )
                copied[family] = readout
            if self.converged and not all(item.converged for item in copied.values()):
                raise ValueError("converged primary readout has failed diagnostics")
            object.__setattr__(
                self, "diagnostic_readouts", MappingProxyType(copied)
            )
            scalar_radii = {
                "truncation": self.truncation_radius,
                "resolution": self.resolution_radius,
                "seed-path": self.seed_path_radius,
            }
            for family, readout in copied.items():
                if scalar_radii[family] is None:
                    raise ValueError("diagnostic root radius is missing")
                derived = abs(readout.omega_delta_from_primary)
                binary64_resolution = 2.0 * max(
                    math.ulp(readout.omega_delta_from_primary.real),
                    math.ulp(readout.omega_delta_from_primary.imag),
                    math.ulp(scalar_radii[family]),
                    1.0e-300,
                )
                if not math.isclose(
                    scalar_radii[family],
                    derived,
                    rel_tol=1.0e-12,
                    abs_tol=binary64_resolution,
                ):
                    raise ValueError(
                        f"{family} diagnostic root displacement is inconsistent"
                    )
        skipped = self.diagnostics_skipped_reason
        diagnostic_radii = (
            (self.truncation_radius, self.resolution_radius)
            if promoted
            else (
                self.truncation_radius,
                self.resolution_radius,
                self.seed_path_radius,
            )
        )
        if skipped is not None:
            if (
                skipped != "PRIMARY_NOT_CONVERGED"
                or self.converged
                or self.diagnostic_readouts
                or any(value is not None for value in diagnostic_radii)
                or (promoted and self.primary_acceptance.accepted)
            ):
                raise ValueError("root diagnostic skip evidence is inconsistent")
        elif any(value is None for value in diagnostic_radii):
            raise ValueError("root diagnostic radii are missing without a reason")
        if (
            promoted
            and skipped is None
            and set(self.diagnostic_readouts)
            != set(_PROMOTED_FIXED_ROOT_DIAGNOSTIC_FAMILIES)
        ):
            raise ValueError("promoted fixed-root diagnostics are incomplete")

    @property
    def newton_correction_estimate(self) -> float:
        return self.determinant_residual_abs / self.determinant_derivative_abs

    def to_mapping(self) -> dict[str, object]:
        output = {
            "omega": _complex_mapping(self.omega),
            "determinant_residual_abs": self.determinant_residual_abs,
            "determinant_derivative_abs": self.determinant_derivative_abs,
            "newton_correction_estimate": self.newton_correction_estimate,
            "converged": self.converged,
            "root_reference_id": self.root_reference_id,
            "branch_id": self.branch_id,
            "equation_id": self.equation_id,
            "truncation_radius": self.truncation_radius,
            "resolution_radius": self.resolution_radius,
            "seed_path_radius": self.seed_path_radius,
            "source_root_mapping": (
                None
                if self.source_root_mapping is None
                else dict(self.source_root_mapping)
            ),
        }
        if self.diagnostic_readouts:
            output["diagnostic_readouts"] = {
                family: self.diagnostic_readouts[family].to_mapping()
                for family in self.diagnostic_readouts
            }
        if self.diagnostics_skipped_reason is not None:
            output["diagnostics_skipped_reason"] = self.diagnostics_skipped_reason
        if self.numerical_conditioning is not None:
            output["numerical_conditioning"] = (
                self.numerical_conditioning.to_mapping()
            )
        for name in ("normalised_determinant_abs", "raw_determinant_abs"):
            item = getattr(self, name)
            if item is not None:
                output[name] = str(item)
        if self.raw_determinant_evidence_status is not None:
            output["raw_determinant_evidence_status"] = (
                self.raw_determinant_evidence_status
            )
        if self.root_authentication is not None:
            output["root_authentication"] = (
                self.root_authentication.to_mapping()
            )
        if self.promoted_root_readout_policy is not None:
            output.update({
                "promoted_root_readout_policy": (
                    self.promoted_root_readout_policy
                ),
                "primary_acceptance": self.primary_acceptance.to_mapping(),
                "seed_path_required": self.seed_path_required,
                "seed_path_executed": self.seed_path_executed,
                "seed_path_determinant_count": (
                    self.seed_path_determinant_count
                ),
            })
        if self.worker_response_receipt is not None:
            output["worker_response_receipt"] = {
                **dict(self.worker_response_receipt),
                "request_binding": dict(
                    self.worker_response_receipt["request_binding"]
                ),
            }
        return output

    @classmethod
    def from_mapping(cls, value: object) -> "RootReadout":
        if not isinstance(value, Mapping):
            raise ValueError("root readout must be an object")
        return cls(
            omega=_complex_from_mapping(value.get("omega"), "root omega"),
            determinant_residual_abs=float(value["determinant_residual_abs"]),
            determinant_derivative_abs=float(value["determinant_derivative_abs"]),
            converged=value["converged"],
            root_reference_id=str(value["root_reference_id"]),
            branch_id=str(value["branch_id"]),
            equation_id=str(value["equation_id"]),
            truncation_radius=(
                None
                if value.get("truncation_radius", 0.0) is None
                else float(value.get("truncation_radius", 0.0))
            ),
            resolution_radius=(
                None
                if value.get("resolution_radius", 0.0) is None
                else float(value.get("resolution_radius", 0.0))
            ),
            seed_path_radius=(
                None
                if value.get("seed_path_radius", 0.0) is None
                else float(value.get("seed_path_radius", 0.0))
            ),
            diagnostic_readouts=(
                None
                if "diagnostic_readouts" not in value
                else {
                    family: DiagnosticRootReadout.from_mapping(
                        diagnostic
                    )
                    for family, diagnostic in value[
                        "diagnostic_readouts"
                    ].items()
                }
            ),
            source_root_mapping=_validated_source_root_mapping(
                value.get("source_root_mapping")
            ),
            diagnostics_skipped_reason=(
                None
                if value.get("diagnostics_skipped_reason") is None
                else str(value["diagnostics_skipped_reason"])
            ),
            numerical_conditioning=(
                None
                if "numerical_conditioning" not in value
                else NumericalConditioningEvidence.from_mapping(
                    value["numerical_conditioning"]
                )
            ),
            normalised_determinant_abs=(
                None
                if "normalised_determinant_abs" not in value
                else _conditioning_decimal_from_text(
                    value["normalised_determinant_abs"],
                    "root readout normalised_determinant_abs",
                )
            ),
            raw_determinant_abs=(
                None
                if (
                    "raw_determinant_abs" not in value
                    or value["raw_determinant_abs"] is None
                )
                else _conditioning_decimal_from_text(
                    value["raw_determinant_abs"],
                    "root readout raw_determinant_abs",
                )
            ),
            raw_determinant_evidence_status=(
                None
                if "raw_determinant_evidence_status" not in value
                else value["raw_determinant_evidence_status"]
            ),
            worker_response_receipt=value.get("worker_response_receipt"),
            root_authentication=(
                None
                if value.get("root_authentication") is None
                else RootAuthenticationEvidence.from_mapping(
                    value["root_authentication"]
                )
            ),
            promoted_root_readout_policy=value.get(
                "promoted_root_readout_policy"
            ),
            primary_acceptance=(
                None
                if value.get("primary_acceptance") is None
                else PrimaryRootAcceptanceEvidence.from_mapping(
                    value["primary_acceptance"]
                )
            ),
            seed_path_required=value.get("seed_path_required"),
            seed_path_executed=value.get("seed_path_executed"),
            seed_path_determinant_count=value.get(
                "seed_path_determinant_count"
            ),
        )


def root_readout_preserves_authenticated_branch(
    readout: RootReadout,
    authenticated_root: BoundSpectralRoot,
    *,
    equation_id: str,
    source_root_mapping: Mapping[str, object] | None,
) -> bool:
    """Replay the production root-readout branch contract for persisted evidence.

    The authenticated catalog root establishes identity and branch provenance;
    ``readout.omega`` is the numerical root returned after polishing.  The
    native production kernel preserves that identity when the polished root
    and each diagnostic root remain inside the existing branch-continuation
    radius.  Numerical convergence is a separate status and is deliberately
    not required by this authentication predicate.  The Newton-correction
    bound below is an additional persistence-quality gate; it does not rewrite
    the kernel's geometric branch identity.
    """

    expected_source = _validated_source_root_mapping(source_root_mapping)
    branch_radius = mode_specific_branch_enclosure_radius(authenticated_root)
    diagnostic_radii_preserve_branch = (
        readout.truncation_radius is not None
        and readout.resolution_radius is not None
        and readout.truncation_radius <= branch_radius
        and readout.resolution_radius <= branch_radius
        and (
            readout.promoted_root_readout_policy
            == PROMOTED_ROOT_READOUT_POLICY
            or (
                readout.seed_path_radius is not None
                and readout.seed_path_radius <= branch_radius
            )
        )
    )
    return (
        readout.root_reference_id == authenticated_root.root_reference_id
        and readout.branch_id == authenticated_root.branch_id
        and readout.equation_id == equation_id
        and readout.source_root_mapping == expected_source
        and abs(readout.omega - authenticated_root.omega)
        <= branch_radius
        and readout.newton_correction_estimate
        <= ROOT_BRANCH_CONTINUATION_TOLERANCE_ABS
        and (
            readout.diagnostics_skipped_reason == "PRIMARY_NOT_CONVERGED"
            or diagnostic_radii_preserve_branch
        )
    )


class NativeDeterminantKernel(Protocol):
    def evaluate_root(
        self,
        *,
        job: ResponseComponentJob,
        background_root: BoundSpectralRoot,
        perturbation: HorizonPerturbation | ExteriorPerturbation,
        policy: NumericalPolicy,
        primary_predictor: complex | None = None,
    ) -> RootReadout: ...

    def horizon_partials(
        self,
        *,
        job: ResponseComponentJob,
        background_root: BoundSpectralRoot,
        policy: NumericalPolicy,
    ) -> DeterminantPartials: ...


class RootReadoutBackend(Protocol):
    identity: BackendIdentity

    def read_root(
        self,
        job: ResponseComponentJob,
        amplitude: complex,
        primary_predictor: complex | None = None,
    ) -> RootReadout: ...

    def closed_form_horizon_response(
        self, job: ResponseComponentJob
    ) -> complex | None: ...


@dataclass(frozen=True, slots=True)
class FixedRootDeterminantSample:
    """One determinant value evaluated at a fixed authenticated root."""

    omega: complex
    amplitude: complex
    determinant: complex
    determinant_error_abs: float
    determinant_error_status: str
    determinant_error_model_id: str | None
    determinant_family: str
    determinant_normalisation: str
    branch_identity: str
    branch_authenticated: bool
    request_sha256: str
    worker_response_receipt: Mapping[str, object]
    worker_response_receipt_sha256: str
    precision_tier: PrecisionTier
    working_precision_bits: int
    readout_role: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "omega", _finite_complex(self.omega, "sample omega"))
        object.__setattr__(
            self,
            "amplitude",
            _finite_complex(self.amplitude, "sample amplitude"),
        )
        object.__setattr__(
            self,
            "determinant",
            _finite_complex(self.determinant, "sample determinant"),
        )
        error = float(self.determinant_error_abs)
        if not math.isfinite(error) or error < 0.0:
            raise ValueError("fixed-root determinant error must be nonnegative")
        object.__setattr__(self, "determinant_error_abs", error)
        if self.determinant_error_status not in {
            DETERMINANT_ERROR_AVAILABLE,
            DETERMINANT_ERROR_UNAVAILABLE,
        }:
            raise ValueError("fixed-root determinant error status is invalid")
        if self.determinant_error_status == DETERMINANT_ERROR_AVAILABLE:
            if (
                not isinstance(self.determinant_error_model_id, str)
                or not self.determinant_error_model_id
                or error <= 0.0
            ):
                raise ValueError("available fixed-root determinant error is invalid")
        elif self.determinant_error_model_id is not None or error != 0.0:
            raise ValueError("unavailable fixed-root determinant error is invalid")
        for name in (
            "determinant_family",
            "determinant_normalisation",
            "branch_identity",
            "readout_role",
        ):
            if not isinstance(getattr(self, name), str) or not getattr(self, name):
                raise ValueError(f"fixed-root sample {name} is invalid")
        if type(self.branch_authenticated) is not bool:
            raise ValueError("fixed-root sample branch evidence is invalid")
        if not _HEX_64.fullmatch(self.request_sha256):
            raise ValueError("fixed-root sample request digest is invalid")
        if not _HEX_64.fullmatch(self.worker_response_receipt_sha256):
            raise ValueError("fixed-root sample worker receipt digest is invalid")
        receipt = json.loads(canonical_json_bytes(dict(self.worker_response_receipt)))
        if not isinstance(receipt, dict) or _sha256(receipt) != (
            self.worker_response_receipt_sha256
        ):
            raise ValueError("fixed-root sample worker receipt digest mismatch")
        receipt_fields = {
            "schema", "request_binding", "request_sha256",
            "response_binding", "response_sha256", "runtime_identity_sha256",
            "scientific_runtime_sha256",
        }
        request_binding = receipt.get("request_binding")
        response_binding = receipt.get("response_binding")
        if (
            set(receipt) != receipt_fields
            or receipt.get("schema")
            != "windows-solver.fixed-root-determinant-sample-receipt/1"
            or not isinstance(request_binding, dict)
            or _sha256(request_binding) != self.request_sha256
            or receipt.get("request_sha256") != self.request_sha256
            or not isinstance(response_binding, dict)
            or _sha256(response_binding) != receipt.get("response_sha256")
            or response_binding.get("request_sha256") != self.request_sha256
            or response_binding.get("status") != "ok"
            or response_binding.get("operation")
            != "fixed-root-determinant-sample"
            or response_binding.get("determinant_family")
            != self.determinant_family
            or response_binding.get("determinant_normalisation")
            != self.determinant_normalisation
            or response_binding.get("branch_identity") != self.branch_identity
            or response_binding.get("branch_authenticated")
            is not self.branch_authenticated
            or response_binding.get("semantic_precision_tier")
            != self.precision_tier.value
            or response_binding.get("working_precision_bits")
            != self.working_precision_bits
            or response_binding.get("readout_role") != self.readout_role
            or response_binding.get("determinant_error_status")
            != self.determinant_error_status
            or response_binding.get("determinant_error_model_id")
            != self.determinant_error_model_id
            or not isinstance(receipt.get("scientific_runtime_sha256"), str)
            or not _HEX_64.fullmatch(receipt["scientific_runtime_sha256"])
        ):
            raise ValueError("fixed-root sample receipt identity mismatch")
        try:
            receipt_omega = complex(
                float(response_binding["omega_re"]),
                float(response_binding["omega_im"]),
            )
            receipt_amplitude = complex(
                float(response_binding["amplitude_re"]),
                float(response_binding["amplitude_im"]),
            )
            receipt_determinant = complex(
                float(response_binding["determinant_re"]),
                float(response_binding["determinant_im"]),
            )
            raw_receipt_error = response_binding["determinant_error_abs"]
            receipt_error_decimal = Decimal(str(raw_receipt_error))
            receipt_error = float(receipt_error_decimal)
            if Decimal.from_float(receipt_error) < receipt_error_decimal:
                receipt_error = math.nextafter(receipt_error, math.inf)
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError("fixed-root sample receipt material mismatch") from error
        if (
            receipt_omega != self.omega
            or receipt_amplitude != self.amplitude
            or receipt_determinant != self.determinant
            or receipt_error != self.determinant_error_abs
        ):
            raise ValueError("fixed-root sample receipt material mismatch")
        object.__setattr__(self, "worker_response_receipt", MappingProxyType(receipt))
        object.__setattr__(self, "precision_tier", precision_tier(self.precision_tier))
        if (
            isinstance(self.working_precision_bits, bool)
            or not isinstance(self.working_precision_bits, int)
            or self.working_precision_bits < 1
        ):
            raise ValueError("fixed-root sample working precision bits are invalid")

    def _response_decimal(self, field: str, subject: str) -> Decimal:
        response = self.worker_response_receipt["response_binding"]
        value = response[field]
        if isinstance(value, str):
            return _conditioning_decimal_from_text(value, subject)
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
        ):
            raise ValueError(f"{subject} must be finite decimal evidence")
        return Decimal(str(value))

    @property
    def exact_amplitude(self) -> DecimalComplex:
        return DecimalComplex(
            self._response_decimal(
                "amplitude_re", "fixed-root sample amplitude real"
            ),
            self._response_decimal(
                "amplitude_im", "fixed-root sample amplitude imaginary"
            ),
        )

    @property
    def exact_determinant(self) -> DecimalComplex:
        return DecimalComplex(
            self._response_decimal(
                "determinant_re", "fixed-root sample determinant real"
            ),
            self._response_decimal(
                "determinant_im", "fixed-root sample determinant imaginary"
            ),
        )

    @property
    def exact_determinant_error_abs(self) -> Decimal:
        return self._response_decimal(
            "determinant_error_abs", "fixed-root sample determinant error"
        )

    def to_mapping(self) -> dict[str, object]:
        return {
            "amplitude": _complex_mapping(self.amplitude),
            "branch_authenticated": self.branch_authenticated,
            "branch_identity": self.branch_identity,
            "determinant": _complex_mapping(self.determinant),
            "determinant_error_abs": self.determinant_error_abs,
            "determinant_error_status": self.determinant_error_status,
            "determinant_error_model_id": self.determinant_error_model_id,
            "determinant_family": self.determinant_family,
            "determinant_normalisation": self.determinant_normalisation,
            "omega": _complex_mapping(self.omega),
            "precision_tier": self.precision_tier.value,
            "readout_role": self.readout_role,
            "request_sha256": self.request_sha256,
            "worker_response_receipt": dict(self.worker_response_receipt),
            "worker_response_receipt_sha256": self.worker_response_receipt_sha256,
            "working_precision_bits": self.working_precision_bits,
        }

    @classmethod
    def from_mapping(cls, value: object) -> "FixedRootDeterminantSample":
        fields = {
            "amplitude", "branch_authenticated", "branch_identity",
            "determinant", "determinant_error_abs", "determinant_error_status",
            "determinant_error_model_id", "determinant_family",
            "determinant_normalisation", "omega", "precision_tier",
            "readout_role", "request_sha256", "worker_response_receipt",
            "worker_response_receipt_sha256", "working_precision_bits",
        }
        if not isinstance(value, Mapping) or set(value) != fields:
            raise ValueError("fixed-root determinant sample fields are invalid")
        return cls(
            omega=_complex_from_mapping(value["omega"], "sample omega"),
            amplitude=_complex_from_mapping(value["amplitude"], "sample amplitude"),
            determinant=_complex_from_mapping(value["determinant"], "sample determinant"),
            determinant_error_abs=float(value["determinant_error_abs"]),
            determinant_error_status=str(value["determinant_error_status"]),
            determinant_error_model_id=value["determinant_error_model_id"],
            determinant_family=str(value["determinant_family"]),
            determinant_normalisation=str(value["determinant_normalisation"]),
            branch_identity=str(value["branch_identity"]),
            branch_authenticated=value["branch_authenticated"],
            request_sha256=str(value["request_sha256"]),
            worker_response_receipt=value["worker_response_receipt"],
            worker_response_receipt_sha256=str(
                value["worker_response_receipt_sha256"]
            ),
            precision_tier=precision_tier(value["precision_tier"]),
            working_precision_bits=value["working_precision_bits"],
            readout_role=str(value["readout_role"]),
        )


def _validate_exterior_derivative_checkpoint_evidence(
    *,
    evidence: dict[str, object],
    samples: Sequence[FixedRootDeterminantSample],
    baseline: RootReadout,
    mechanism_id: str,
    job_id: str,
    leaf_id: str,
    status: ComponentStatus,
    response: complex | None,
    error_channels: Mapping[str, float],
) -> None:
    """Recompute a persisted fixed-root derivative certificate from samples."""

    if not samples:
        if status is not ComponentStatus.DERIVATIVE_UNRESOLVED:
            raise ValueError("bounded derivative evidence lacks fixed-root samples")
        return
    if len(samples) not in {4, 6}:
        raise ValueError("component fixed-root determinant sample count is invalid")
    validation_reason = evidence.get("validation_reason")
    validation_identity = evidence.get("validation_policy_identity")
    if len(samples) == 4:
        if validation_reason is not None or validation_identity is not None:
            raise ValueError("four-sample derivative evidence claims validation")
    elif (
        validation_reason not in FULL_LADDER_VALIDATION_REASONS
        or validation_identity != FIXED_ROOT_AXIS_VALIDATION_IDENTITY
    ):
        raise ValueError("six-sample derivative validation policy is invalid")

    h = samples[0].amplitude.real
    if not math.isfinite(h) or h <= 0.0:
        raise ValueError("component fixed-root derivative step is invalid")
    expected = [
        ("coordinate-real-plus-h", complex(h, 0.0)),
        ("coordinate-real-minus-h", complex(-h, 0.0)),
        ("coordinate-real-plus-h2", complex(h / 2.0, 0.0)),
        ("coordinate-real-minus-h2", complex(-h / 2.0, 0.0)),
    ]
    if len(samples) == 6:
        expected.extend([
            ("coordinate-imaginary-plus-h2", complex(0.0, h / 2.0)),
            ("coordinate-imaginary-minus-h2", complex(0.0, -h / 2.0)),
        ])
    conditioning = baseline.numerical_conditioning
    contract = regularised_gsn_mechanism_contract(mechanism_id)
    if conditioning is None:
        raise ValueError("component derivative baseline conditioning is missing")
    baseline_receipt = baseline.worker_response_receipt
    baseline_runtime_sha256 = (
        None
        if not isinstance(baseline_receipt, Mapping)
        else baseline_receipt.get("scientific_runtime_sha256")
    )
    if not isinstance(baseline_runtime_sha256, str):
        raise ValueError("component derivative baseline runtime receipt is missing")
    for sample, (role, amplitude) in zip(samples, expected):
        request = sample.worker_response_receipt["request_binding"]
        if (
            sample.readout_role != role
            or sample.amplitude != amplitude
            or sample.omega != baseline.omega
            or sample.determinant_family != contract["determinant_family"]
            or sample.determinant_normalisation
            != contract["determinant_normalisation"]
            or sample.branch_identity != conditioning.branch_convention
            or sample.branch_authenticated is not True
            or request.get("job_id") != job_id
            or request.get("leaf_id") != leaf_id
            or sample.worker_response_receipt.get("scientific_runtime_sha256")
            != baseline_runtime_sha256
        ):
            raise ValueError(
                "component fixed-root sample baseline omega, job, or runtime binding is invalid"
            )

    coordinate, coarse, fine, propagated, disagreement = (
        _fixed_root_coordinate_derivative(samples[:4], h)
    )
    expected_decision = {
        "accepted": abs(fine) > coordinate.radius,
        "identity": FIXED_ROOT_DERIVATIVE_CONDITIONING_IDENTITY,
        "rejection_reason": None,
        "selected_candidate": "h/2",
    }
    if not expected_decision["accepted"]:
        expected_decision.update({
            "rejection_reason": "DERIVATIVE_DISK_CONTAINS_ZERO",
            "selected_candidate": None,
        })
    required_coordinate = {
        "coordinate_derivative_disk": coordinate.to_mapping(),
        "conditioning_decision": expected_decision,
        "propagated_determinant_error_abs": propagated,
        "raw_step_disagreement_abs": disagreement,
    }
    if status is ComponentStatus.CONVERGED:
        required_coordinate.update({
            "fine_derivative": _complex_mapping(fine),
            "real_h_derivative": _complex_mapping(coarse),
            "selected_step": h / 2.0,
        })
    for name, expected_value in required_coordinate.items():
        if evidence.get(name) != expected_value:
            raise ValueError(
                f"component derivative evidence {name} is not sample-derived"
            )
    if not expected_decision["accepted"]:
        if status is not ComponentStatus.DERIVATIVE_UNRESOLVED:
            raise ValueError("rejected derivative disk was persisted as usable")
        return

    primary = baseline.primary_acceptance
    authentication = None if primary is None else primary.derivative_authentication
    if authentication is None:
        raise ValueError("component frequency derivative authentication is missing")
    frequency_radius = float(
        authentication.propagated_error_abs
        + authentication.step_disagreement_abs
    )
    frequency = ComplexDisk(
        complex(float(authentication.derivative_re), float(authentication.derivative_im)),
        frequency_radius,
    )
    if evidence.get("frequency_derivative_disk") != frequency.to_mapping():
        raise ValueError("component frequency derivative disk is not PRIMARY-derived")
    expected_frequency_provenance = {
        "axis": authentication.axis,
        "propagated_error_abs": str(authentication.propagated_error_abs),
        "selected_step": str(authentication.selected_step),
        "step_disagreement_abs": str(authentication.step_disagreement_abs),
    }
    if evidence.get("frequency_derivative_radius_provenance") != (
        expected_frequency_provenance
    ):
        raise ValueError("component frequency derivative provenance is invalid")
    expected_response = exterior_response_disk(
        coordinate_derivative=coordinate,
        frequency_derivative=frequency,
    )
    if (
        evidence.get("response_disk") != expected_response.to_mapping()
        or response != expected_response.centre
        or error_channels.get("resolution") != expected_response.radius
    ):
        raise ValueError("component exterior response disk is not derivative-derived")

    if len(samples) == 6:
        imaginary = (
            samples[4].determinant - samples[5].determinant
        ) / (1.0j * h)
        imaginary_error = (
            samples[4].determinant_error_abs
            + samples[5].determinant_error_abs
        ) / h
        difference = abs(imaginary - fine)
        expected_validation = {
            "agrees": difference <= imaginary_error + coordinate.radius,
            "axis_difference_abs": difference,
            "derivative": _complex_mapping(imaginary),
            "propagated_error_abs": imaginary_error,
        }
        if evidence.get("imaginary_axis_validation") != expected_validation:
            raise ValueError("component imaginary-axis validation is not sample-derived")


@dataclass(slots=True)
class NativeDeterminantAdapter:
    identity: BackendIdentity
    kernel: NativeDeterminantKernel

    def _check_job(self, job: ResponseComponentJob) -> None:
        if job.backend_identity != self.identity:
            raise ValueError("response job backend identity does not match adapter")

    def preview_root_request(
        self,
        job: ResponseComponentJob,
        amplitude: complex,
        primary_predictor: complex | None = None,
        primary_predictor_kind: str | None = None,
        readout_role: str | None = None,
    ) -> dict[str, object]:
        """Bind binary64 work to a canonical pseudo-request identity."""

        self._check_job(job)
        return {
            "schema": "windows-solver.native-root-readout-request/1",
            "job": job.to_mapping(),
            "policy_sha256": job.policy.identity_sha256,
            "backend_identity_sha256": self.identity.identity_sha256,
            "readout_role": readout_role,
            "amplitude": _complex_mapping(complex(amplitude)),
        }

    def read_root(
        self,
        job: ResponseComponentJob,
        amplitude: complex,
        primary_predictor: complex | None = None,
    ) -> RootReadout:
        return self._read_root(
            job, amplitude, primary_predictor, primary_predictor_kind=None
        )

    def read_root_with_predictor_kind(
        self,
        job: ResponseComponentJob,
        amplitude: complex,
        primary_predictor: complex,
        primary_predictor_kind: str,
    ) -> RootReadout:
        return self._read_root(
            job,
            amplitude,
            primary_predictor,
            primary_predictor_kind=primary_predictor_kind,
        )

    def _read_root(
        self,
        job: ResponseComponentJob,
        amplitude: complex,
        primary_predictor: complex | None,
        *,
        primary_predictor_kind: str | None,
    ) -> RootReadout:
        self._check_job(job)
        value = _finite_complex(amplitude, "perturbation amplitude")
        if job.mechanism_id == "horizon-admittance":
            perturbation: HorizonPerturbation | ExteriorPerturbation = HorizonPerturbation(
                value, job.spin, job.mode.m
            )
        else:
            perturbation = ExteriorPerturbation(
                value,
                _EXTERIOR_PROFILE_IDS[job.mechanism_id],
                _exterior_support(job.spin, job.mechanism_id),
            )
        evaluate_with_kind = getattr(
            self.kernel, "evaluate_root_with_predictor_kind", None
        )
        if primary_predictor_kind is not None and callable(evaluate_with_kind):
            return evaluate_with_kind(
                job=job,
                background_root=job.root,
                perturbation=perturbation,
                policy=job.policy,
                primary_predictor=primary_predictor,
                primary_predictor_kind=primary_predictor_kind,
            )
        return self.kernel.evaluate_root(
            job=job,
            background_root=job.root,
            perturbation=perturbation,
            policy=job.policy,
            primary_predictor=primary_predictor,
        )

    def closed_form_horizon_response(
        self, job: ResponseComponentJob
    ) -> complex | None:
        self._check_job(job)
        if job.mechanism_id != "horizon-admittance":
            return None
        partials = self.kernel.horizon_partials(
            job=job,
            background_root=job.root,
            policy=job.policy,
        )
        frequency = _finite_complex(
            partials.frequency_derivative, "frequency derivative"
        )
        if not partials.simple_root_valid or frequency == 0.0j:
            return None
        return -partials.coordinate_derivative / frequency


@dataclass(frozen=True, slots=True)
class LadderLevel:
    epsilon: float
    real_plus: RootReadout
    real_minus: RootReadout
    imaginary_plus: RootReadout
    imaginary_minus: RootReadout

    @property
    def real_secant(self) -> complex:
        return (self.real_plus.omega - self.real_minus.omega) / (2.0 * self.epsilon)

    @property
    def imaginary_secant(self) -> complex:
        return (self.imaginary_plus.omega - self.imaginary_minus.omega) / (
            2.0j * self.epsilon
        )

    @property
    def combined_secant(self) -> complex:
        return 0.5 * (self.real_secant + self.imaginary_secant)

    @property
    def real_radius(self) -> float:
        return (
            self.real_plus.newton_correction_estimate
            + self.real_minus.newton_correction_estimate
        ) / (2.0 * self.epsilon)

    @property
    def imaginary_radius(self) -> float:
        return (
            self.imaginary_plus.newton_correction_estimate
            + self.imaginary_minus.newton_correction_estimate
        ) / (2.0 * self.epsilon)

    @property
    def even_remainder_abs(self) -> float:
        real = 0.5 * (self.real_plus.omega + self.real_minus.omega)
        imaginary = 0.5 * (
            self.imaginary_plus.omega + self.imaginary_minus.omega
        )
        return abs(real - imaginary)

    @property
    def even_remainder_noise(self) -> float:
        return 0.5 * sum(
            item.newton_correction_estimate
            for item in (
                self.real_plus,
                self.real_minus,
                self.imaginary_plus,
                self.imaginary_minus,
            )
        )

    def signal_resolved(self, factor: float) -> bool:
        real_signal = 0.5 * abs(self.real_plus.omega - self.real_minus.omega)
        imaginary_signal = 0.5 * abs(
            self.imaginary_plus.omega - self.imaginary_minus.omega
        )
        real_noise = factor * (
            self.real_plus.newton_correction_estimate
            + self.real_minus.newton_correction_estimate
        )
        imaginary_noise = factor * (
            self.imaginary_plus.newton_correction_estimate
            + self.imaginary_minus.newton_correction_estimate
        )
        return real_signal > real_noise and imaginary_signal > imaginary_noise

    def to_mapping(self) -> dict[str, object]:
        return {
            "epsilon": self.epsilon,
            "real_plus": self.real_plus.to_mapping(),
            "real_minus": self.real_minus.to_mapping(),
            "imaginary_plus": self.imaginary_plus.to_mapping(),
            "imaginary_minus": self.imaginary_minus.to_mapping(),
            "real_secant": _complex_mapping(self.real_secant),
            "imaginary_secant": _complex_mapping(self.imaginary_secant),
        }

    @classmethod
    def from_mapping(cls, value: object) -> "LadderLevel":
        if not isinstance(value, Mapping):
            raise ValueError("response level must be an object")
        return cls(
            epsilon=float(value["epsilon"]),
            real_plus=RootReadout.from_mapping(value["real_plus"]),
            real_minus=RootReadout.from_mapping(value["real_minus"]),
            imaginary_plus=RootReadout.from_mapping(value["imaginary_plus"]),
            imaginary_minus=RootReadout.from_mapping(value["imaginary_minus"]),
        )


class ComponentStatus(str, Enum):
    CONVERGED = "CONVERGED"
    NOISE_FLOOR = "NOISE_FLOOR"
    AXIS_MISMATCH = "AXIS_MISMATCH"
    BRANCH_LOSS = "BRANCH_LOSS"
    NOT_CONVERGED = "NOT_CONVERGED"
    DERIVATIVE_UNRESOLVED = "DERIVATIVE_UNRESOLVED"


@dataclass(frozen=True, slots=True)
class _AxisEstimate:
    center: complex
    coefficient_c2: complex
    root_radius: float
    richardson_radius: float
    holdout_radius: float
    regression_radius: float

    @property
    def amplitude_radius(self) -> float:
        return max(
            self.richardson_radius,
            self.holdout_radius,
            self.regression_radius,
        )


def _richardson(
    coarse_epsilon: float,
    coarse_value: complex,
    coarse_radius: float,
    fine_epsilon: float,
    fine_value: complex,
    fine_radius: float,
) -> tuple[complex, complex, float]:
    denominator = coarse_epsilon**2 - fine_epsilon**2
    coefficient = (coarse_value - fine_value) / denominator
    center = fine_value - coefficient * fine_epsilon**2
    radius = (
        coarse_epsilon**2 * fine_radius
        + fine_epsilon**2 * coarse_radius
    ) / denominator
    return center, coefficient, radius


def _linear_even_fit(epsilons: Sequence[float], values: Sequence[complex]) -> tuple[complex, float]:
    x = [value * value for value in epsilons]
    mean_x = sum(x) / len(x)
    mean_y = sum(values) / len(values)
    denominator = sum((item - mean_x) ** 2 for item in x)
    if denominator == 0.0:
        raise ValueError("amplitude fit is singular")
    slope = sum(
        (item - mean_x) * (value - mean_y)
        for item, value in zip(x, values)
    ) / denominator
    intercept = mean_y - slope * mean_x
    residual = max(
        abs(value - (intercept + slope * item))
        for item, value in zip(x, values)
    )
    return intercept, residual


def _axis_estimate(levels: Sequence[LadderLevel], axis: str) -> _AxisEstimate:
    if len(levels) < 4:
        raise ValueError("axis estimate requires at least four levels")
    if axis == "real":
        values = [level.real_secant for level in levels]
        radii = [level.real_radius for level in levels]
    elif axis == "imaginary":
        values = [level.imaginary_secant for level in levels]
        radii = [level.imaginary_radius for level in levels]
    else:
        values = [level.combined_secant for level in levels]
        radii = [0.5 * (level.real_radius + level.imaginary_radius) for level in levels]
    epsilons = [level.epsilon for level in levels]
    center, coefficient, root_radius = _richardson(
        epsilons[-2], values[-2], radii[-2], epsilons[-1], values[-1], radii[-1]
    )
    coarse_center, _, _ = _richardson(
        epsilons[-4], values[-4], radii[-4], epsilons[-3], values[-3], radii[-3]
    )
    holdout = abs(values[-3] - (center + coefficient * epsilons[-3] ** 2))
    fit_center, fit_residual = _linear_even_fit(epsilons, values)
    return _AxisEstimate(
        center=center,
        coefficient_c2=coefficient,
        root_radius=root_radius,
        richardson_radius=abs(center - coarse_center),
        holdout_radius=holdout,
        regression_radius=max(fit_residual, abs(center - fit_center)),
    )


def _diagnostic_response_channel(
    levels: Sequence[LadderLevel],
    family: str,
    *,
    primary_center: complex,
    primary_radius: float,
) -> float:
    """Reduce signed diagnostic roots into the same units as the response."""

    def value_and_radius(level: LadderLevel, axis: str) -> tuple[complex, float]:
        if axis == "real":
            plus_readout, minus_readout, denominator = (
                level.real_plus,
                level.real_minus,
                complex(2.0 * level.epsilon, 0.0),
            )
        elif axis == "imaginary":
            plus_readout, minus_readout, denominator = (
                level.imaginary_plus,
                level.imaginary_minus,
                complex(0.0, 2.0 * level.epsilon),
            )
        else:
            real_value, real_radius = value_and_radius(level, "real")
            imaginary_value, imaginary_radius = value_and_radius(level, "imaginary")
            return (
                0.5 * (real_value + imaginary_value),
                0.5 * (real_radius + imaginary_radius),
            )
        plus = plus_readout.diagnostic_readouts[family]
        minus = minus_readout.diagnostic_readouts[family]
        return (
            (
                (plus_readout.omega - minus_readout.omega)
                + (
                    plus.omega_delta_from_primary
                    - minus.omega_delta_from_primary
                )
            )
            / denominator,
            (
                plus.newton_correction_estimate
                + minus.newton_correction_estimate
            )
            / (2.0 * level.epsilon),
        )

    if len(levels) < 2:
        raise ValueError("diagnostic response reduction requires two levels")
    coarse, fine = levels[-2:]
    increments: list[float] = []
    for axis in ("real", "imaginary", "combined"):
        coarse_value, coarse_radius = value_and_radius(coarse, axis)
        fine_value, fine_radius = value_and_radius(fine, axis)
        center, _, radius = _richardson(
            coarse.epsilon,
            coarse_value,
            coarse_radius,
            fine.epsilon,
            fine_value,
            fine_radius,
        )
        increments.append(
            max(0.0, abs(center - primary_center) + radius - primary_radius)
        )
    return max(increments)


def _observed_orders(epsilons: Sequence[float], values: Sequence[complex]) -> tuple[float, ...]:
    output: list[float] = []
    differences = [abs(left - right) for left, right in zip(values, values[1:])]
    for index in range(len(differences) - 1):
        coarse, fine = differences[index], differences[index + 1]
        ratio = epsilons[index] / epsilons[index + 1]
        if coarse > 0.0 and fine > 0.0 and ratio > 1.0:
            output.append(math.log(coarse / fine) / math.log(ratio))
    return tuple(output)


def _positive_orders(epsilons: Sequence[float], values: Sequence[float]) -> tuple[float, ...]:
    output: list[float] = []
    for index in range(len(values) - 1):
        coarse, fine = values[index], values[index + 1]
        ratio = epsilons[index] / epsilons[index + 1]
        if coarse > 0.0 and fine > 0.0 and ratio > 1.0:
            output.append(math.log(coarse / fine) / math.log(ratio))
    return tuple(output)


_PROMOTED_HORIZON_EVIDENCE_FIELDS = frozenset({
    "derivative_disk",
    "derivative_radius_provenance",
    "horizon_frequency_disk",
    "response_disk",
    "root_radius_provenance",
    "uncertainty_derivation_identity",
    "zero_containing_disk",
})


def _complex_disk_from_mapping(value: object, subject: str) -> ComplexDisk:
    if not isinstance(value, Mapping) or set(value) != {
        "centre", "exact_zero_radius", "radius"
    }:
        raise ValueError(f"{subject} fields are invalid")
    exact = value["exact_zero_radius"]
    if type(exact) is not bool:
        raise ValueError(f"{subject} exact-zero provenance is invalid")
    return ComplexDisk(
        _complex_from_mapping(value["centre"], f"{subject} centre"),
        value["radius"],
        exact_zero_radius=exact,
    )


def _promoted_horizon_correction_evidence(
    baseline: RootReadout,
) -> tuple[dict[str, Decimal], DerivativeAuthenticationEvidence]:
    primary = baseline.primary_acceptance
    authentication = (
        None if primary is None else primary.derivative_authentication
    )
    diagnostics = baseline.diagnostic_readouts
    if primary is None or authentication is None or not isinstance(
        diagnostics, Mapping
    ):
        raise ValueError(
            "promoted horizon checkpoint lacks PRIMARY derivative evidence"
        )
    corrections = {"PRIMARY": primary.correction_abs}
    for family, phase in (
        ("truncation", "TRUNCATION"),
        ("resolution", "RESOLUTION"),
    ):
        diagnostic = diagnostics.get(family)
        fixed = None if diagnostic is None else diagnostic.fixed_root_evidence
        if fixed is None:
            raise ValueError(
                f"promoted horizon checkpoint lacks {phase} correction evidence"
            )
        corrections[phase] = fixed.correction_abs
    return corrections, authentication


def _validate_promoted_horizon_checkpoint_evidence(
    *,
    evidence: Mapping[str, object],
    baseline: RootReadout,
    status: ComponentStatus,
    response: complex | None,
    closed_form_response: complex | None,
    error_channels: Mapping[str, float],
) -> None:
    """Recompute a persisted bounded-horizon certificate from stored inputs."""

    if set(evidence) != _PROMOTED_HORIZON_EVIDENCE_FIELDS:
        raise ValueError("component analytic horizon evidence fields are invalid")
    if (
        evidence.get("uncertainty_derivation_identity")
        != PROMOTED_HORIZON_UNCERTAINTY_DERIVATION_IDENTITY
    ):
        raise ValueError("component horizon uncertainty derivation is invalid")

    corrections, authentication = _promoted_horizon_correction_evidence(
        baseline
    )
    expected_derivative = _bounded_binary64_disk_from_decimal(
        authentication.derivative_estimate,
        authentication.propagated_error_abs
        + authentication.step_disagreement_abs,
        subject="component horizon derivative",
    )
    derivative_centre = expected_derivative.centre
    derivative_provenance = evidence.get("derivative_radius_provenance")
    if not isinstance(derivative_provenance, Mapping) or set(
        derivative_provenance
    ) != {
        "axis",
        "independent_comparison",
        "independent_comparison_omitted_reason",
        "propagated_error_abs",
        "selected_step",
        "step_disagreement_abs",
    }:
        raise ValueError("component horizon derivative provenance is invalid")
    comparison_mapping = derivative_provenance["independent_comparison"]
    comparison_omission = derivative_provenance[
        "independent_comparison_omitted_reason"
    ]
    derivative_radius = expected_derivative.radius
    if comparison_mapping is None:
        if comparison_omission != "NOT_SELECTED_BY_RISK_POLICY":
            raise ValueError(
                "component horizon derivative comparison omission is invalid"
            )
    else:
        if comparison_omission is not None:
            raise ValueError(
                "component horizon derivative comparison provenance is invalid"
            )
        comparison = _complex_disk_from_mapping(
            comparison_mapping, "component horizon derivative comparison disk"
        )
        derivative_radius = max(
            derivative_radius,
            abs(comparison.centre - derivative_centre) + comparison.radius,
        )
    expected_derivative_provenance = {
        "axis": authentication.axis,
        "independent_comparison": comparison_mapping,
        "independent_comparison_omitted_reason": comparison_omission,
        "propagated_error_abs": str(authentication.propagated_error_abs),
        "selected_step": str(authentication.selected_step),
        "step_disagreement_abs": str(
            authentication.step_disagreement_abs
        ),
    }
    if dict(derivative_provenance) != expected_derivative_provenance:
        raise ValueError(
            "component horizon derivative provenance is not PRIMARY-derived"
        )
    expected_derivative = ComplexDisk(derivative_centre, derivative_radius)
    if evidence.get("derivative_disk") != expected_derivative.to_mapping():
        raise ValueError("component horizon derivative disk is not PRIMARY-derived")

    root_provenance = evidence.get("root_radius_provenance")
    if not isinstance(root_provenance, Mapping) or set(root_provenance) != {
        "arithmetic_radius_abs", "correction_abs", "union_rule"
    }:
        raise ValueError("component horizon root-radius provenance is invalid")
    arithmetic_radius = root_provenance["arithmetic_radius_abs"]
    if (
        isinstance(arithmetic_radius, bool)
        or not isinstance(arithmetic_radius, (int, float))
        or not math.isfinite(float(arithmetic_radius))
        or float(arithmetic_radius) < 0.0
    ):
        raise ValueError("component horizon arithmetic radius is invalid")
    expected_corrections = {
        name: str(value) for name, value in corrections.items()
    }
    if (
        root_provenance.get("correction_abs") != expected_corrections
        or root_provenance.get("union_rule")
        != "max-accepted-correction-plus-arithmetic/v1"
    ):
        raise ValueError(
            "component horizon root-radius provenance is not readout-derived"
        )
    expected_frequency_radius = max(
        float(value) for value in corrections.values()
    ) + float(arithmetic_radius)
    frequency = _complex_disk_from_mapping(
        evidence.get("horizon_frequency_disk"),
        "component horizon frequency disk",
    )
    if frequency.radius != expected_frequency_radius:
        raise ValueError("component horizon frequency disk radius is understated")

    expected_response: ComplexDisk | None
    expected_zero: str | None
    try:
        expected_response = horizon_response_disk(
            horizon_frequency=frequency,
            determinant_derivative=expected_derivative,
        )
        expected_zero = None
    except ZeroContainingDiskError as error:
        expected_response = None
        expected_zero = error.disk_name
    if evidence.get("zero_containing_disk") != expected_zero:
        raise ValueError("component horizon zero-containing decision is invalid")
    if expected_response is None:
        if (
            evidence.get("response_disk") is not None
            or status is not ComponentStatus.DERIVATIVE_UNRESOLVED
            or response is not None
            or closed_form_response is not None
            or any(float(value) != 0.0 for value in error_channels.values())
        ):
            raise ValueError("component unbounded horizon response is inconsistent")
        return
    if (
        evidence.get("response_disk") != expected_response.to_mapping()
        or status is not ComponentStatus.CONVERGED
        or response != expected_response.centre
        or closed_form_response != expected_response.centre
        or error_channels.get("resolution") != expected_response.radius
        or any(
            float(value) != 0.0
            for name, value in error_channels.items()
            if name != "resolution"
        )
    ):
        raise ValueError("component horizon response disk is not input-derived")


def _validate_promoted_horizon_checkpoint_evidence_for_job(
    result: "ComponentResult", job: ResponseComponentJob
) -> None:
    """Bind a structurally valid horizon certificate to the selected Kerr job."""

    if result.component_scientific_identity != (
        PROMOTED_HORIZON_COMPONENT_V2_IDENTITY
    ):
        return
    if not math.isfinite(job.spin) or abs(job.spin) >= 1.0:
        raise ValueError("component horizon job spin is invalid")
    evidence = result.analytic_horizon_evidence
    if not isinstance(evidence, Mapping):
        raise ValueError("component analytic horizon evidence is missing")
    horizon_radius = 1.0 + math.sqrt(
        max(0.0, 1.0 - job.spin * job.spin)
    )
    omega_h = job.spin / (2.0 * horizon_radius)
    expected_centre = result.baseline.omega - job.mode.m * omega_h
    expected_arithmetic_radius = (
        math.ulp(result.baseline.omega.real)
        + math.ulp(result.baseline.omega.imag)
        + abs(job.mode.m) * math.ulp(omega_h)
    )
    corrections, _ = _promoted_horizon_correction_evidence(result.baseline)
    expected_frequency = ComplexDisk(
        expected_centre,
        max(float(value) for value in corrections.values())
        + expected_arithmetic_radius,
    )
    root_provenance = evidence.get("root_radius_provenance")
    if (
        not isinstance(root_provenance, Mapping)
        or root_provenance.get("arithmetic_radius_abs")
        != expected_arithmetic_radius
        or evidence.get("horizon_frequency_disk")
        != expected_frequency.to_mapping()
    ):
        raise ValueError("component horizon frequency disk is not job-derived")


@dataclass(frozen=True, slots=True)
class ComponentResult:
    job_id: str
    leaf_id: str
    mechanism_id: str
    status: ComponentStatus
    convergence_basis: str
    response: complex | None
    signed_root_crosscheck: complex | None
    closed_form_response: complex | None
    error_channels: Mapping[str, float]
    baseline: RootReadout
    levels: tuple[LadderLevel, ...]
    lineage: Mapping[str, object]
    component_scientific_identity: str | None = None
    response_method: str | None = None
    finite_amplitude_ladder_required: bool = True
    finite_amplitude_ladder_executed: bool = True
    finite_amplitude_readout_count: int | None = None
    response_uncertainty_status: str | None = None
    error_channel_applicability: Mapping[str, bool] | None = None
    resolved_window: Mapping[str, object] | None = None
    derivative_evidence: Mapping[str, object] | None = None
    analytic_horizon_evidence: Mapping[str, object] | None = None

    def __post_init__(self) -> None:
        if self.finite_amplitude_readout_count is None:
            object.__setattr__(
                self,
                "finite_amplitude_readout_count",
                4 * len(self.levels),
            )
        elif (
            type(self.finite_amplitude_readout_count) is not int
            or self.finite_amplitude_readout_count < 0
        ):
            raise ValueError(
                "finite-amplitude readout count must be a nonnegative integer"
            )
        for name in (
            "finite_amplitude_ladder_required",
            "finite_amplitude_ladder_executed",
        ):
            if type(getattr(self, name)) is not bool:
                raise ValueError(f"{name} must be a built-in bool")
        applicability = self.error_channel_applicability
        if applicability is None:
            applicability = {name: True for name in ERROR_CHANNELS}
        elif (
            not isinstance(applicability, Mapping)
            or set(applicability) != set(ERROR_CHANNELS)
            or any(type(value) is not bool for value in applicability.values())
        ):
            raise ValueError("component error-channel applicability is invalid")
        object.__setattr__(
            self,
            "error_channel_applicability",
            MappingProxyType(dict(applicability)),
        )
        if set(self.error_channels) != set(ERROR_CHANNELS):
            raise ValueError("component error channels are invalid")
        for name, value in self.error_channels.items():
            converted = float(value)
            if not math.isfinite(converted) or converted < 0.0:
                raise ValueError(
                    f"component error channel {name} must be finite and nonnegative"
                )
        if self.derivative_evidence is not None:
            normalized_derivative_evidence = json.loads(
                canonical_json_bytes(dict(self.derivative_evidence))
            )
            if not isinstance(normalized_derivative_evidence, dict):
                raise ValueError("component derivative evidence is invalid")
            raw_samples = normalized_derivative_evidence.get(
                "fixed_root_samples"
            )
            if not isinstance(raw_samples, list):
                raise ValueError(
                    "component fixed-root determinant samples are invalid"
                )
            samples: list[FixedRootDeterminantSample] = []
            for raw_sample in raw_samples:
                sample = FixedRootDeterminantSample.from_mapping(raw_sample)
                if sample.to_mapping() != raw_sample:
                    raise ValueError(
                        "component fixed-root determinant sample is not canonical"
                    )
                samples.append(sample)
            if normalized_derivative_evidence.get("determinant_count") != len(
                samples
            ):
                raise ValueError(
                    "component fixed-root determinant count is inconsistent"
                )
            sample_identities = {
                (
                    sample.determinant_family,
                    sample.determinant_normalisation,
                    sample.branch_identity,
                    sample.precision_tier,
                    sample.working_precision_bits,
                )
                for sample in samples
            }
            if len(sample_identities) > 1:
                raise ValueError(
                    "component fixed-root determinant sample identities disagree"
                )
            normalized_derivative_evidence["fixed_root_samples"] = [
                sample.to_mapping() for sample in samples
            ]
            object.__setattr__(
                self,
                "derivative_evidence",
                MappingProxyType(normalized_derivative_evidence),
            )
        if self.analytic_horizon_evidence is not None:
            normalized_horizon_evidence = json.loads(
                canonical_json_bytes(dict(self.analytic_horizon_evidence))
            )
            if not isinstance(normalized_horizon_evidence, dict):
                raise ValueError("component analytic horizon evidence is invalid")
            object.__setattr__(
                self,
                "analytic_horizon_evidence",
                MappingProxyType(normalized_horizon_evidence),
            )
        if self.component_scientific_identity == EXTERIOR_DERIVATIVE_COMPONENT_IDENTITY:
            bounded = self.response_uncertainty_status == BOUNDED_DERIVATIVE_RESPONSE
            unbounded = self.response_uncertainty_status == UNBOUNDED_DERIVATIVE_RESPONSE
            if (
                self.mechanism_id not in _EXTERIOR_PROFILE_IDS
                or self.response_method != EXTERIOR_DERIVATIVE_METHOD
                or self.finite_amplitude_ladder_required
                or self.finite_amplitude_ladder_executed
                or self.levels
                or self.derivative_evidence is None
                or not (bounded or unbounded)
                or (bounded and (self.response is None or self.status is not ComponentStatus.CONVERGED))
                or (unbounded and (self.response is not None or self.status is not ComponentStatus.DERIVATIVE_UNRESOLVED))
            ):
                raise ValueError(
                    "promoted exterior derivative evidence is inconsistent"
                )
            assert self.derivative_evidence is not None
            _validate_exterior_derivative_checkpoint_evidence(
                evidence=dict(self.derivative_evidence),
                samples=samples,
                baseline=self.baseline,
                mechanism_id=self.mechanism_id,
                job_id=self.job_id,
                leaf_id=self.leaf_id,
                status=self.status,
                response=self.response,
                error_channels=self.error_channels,
            )
        if self.component_scientific_identity == PROMOTED_HORIZON_COMPONENT_IDENTITY:
            if (
                self.mechanism_id != "horizon-admittance"
                or self.response_method != PROMOTED_HORIZON_RESPONSE_METHOD
                or self.finite_amplitude_ladder_required
                or self.finite_amplitude_ladder_executed
                or self.finite_amplitude_readout_count != 0
                or self.levels
                or self.signed_root_crosscheck is not None
                or self.response_uncertainty_status
                != UNCALIBRATED_ANALYTIC_RESPONSE
                or any(self.error_channel_applicability.values())
            ):
                raise ValueError(
                    "promoted analytic horizon component evidence is inconsistent"
                )
        if self.component_scientific_identity == (
            PROMOTED_HORIZON_COMPONENT_V2_IDENTITY
        ):
            bounded = self.response_uncertainty_status == BOUNDED_ANALYTIC_RESPONSE
            unbounded = self.response_uncertainty_status == UNBOUNDED_ANALYTIC_RESPONSE
            if (
                self.mechanism_id != "horizon-admittance"
                or self.response_method != PROMOTED_HORIZON_RESPONSE_METHOD_V2
                or self.finite_amplitude_ladder_required
                or self.finite_amplitude_ladder_executed
                or self.finite_amplitude_readout_count != 0
                or self.levels
                or self.signed_root_crosscheck is not None
                or self.analytic_horizon_evidence is None
                or not (bounded or unbounded)
                or (bounded and (self.response is None or self.status is not ComponentStatus.CONVERGED))
                or (unbounded and (self.response is not None or self.status is not ComponentStatus.DERIVATIVE_UNRESOLVED))
            ):
                raise ValueError(
                    "bounded promoted analytic horizon evidence is inconsistent"
                )
            assert self.analytic_horizon_evidence is not None
            _validate_promoted_horizon_checkpoint_evidence(
                evidence=self.analytic_horizon_evidence,
                baseline=self.baseline,
                status=self.status,
                response=self.response,
                closed_form_response=self.closed_form_response,
                error_channels=self.error_channels,
            )
        conditioned_readouts = tuple(
            readout
            for readout in self.raw_readouts
            if readout.numerical_conditioning is not None
        )
        if not conditioned_readouts:
            return
        expected = regularised_gsn_mechanism_contract(self.mechanism_id)
        for readout in conditioned_readouts:
            evidence = readout.numerical_conditioning
            assert evidence is not None
            if any(
                getattr(evidence, field) != value
                for field, value in expected.items()
            ):
                raise ValueError(
                    "component readout determinant family disagrees with mechanism"
                )

    @property
    def usable(self) -> bool:
        return self.status is ComponentStatus.CONVERGED and self.response is not None

    @property
    def response_uncertainty_calibrated(self) -> bool:
        return self.response_uncertainty_status in {
            None,
            BOUNDED_DERIVATIVE_RESPONSE,
            BOUNDED_ANALYTIC_RESPONSE,
        }

    @property
    def raw_readouts(self) -> tuple[RootReadout, ...]:
        return (
            self.baseline,
            *(
                item
                for level in self.levels
                for item in (
                    level.real_plus,
                    level.real_minus,
                    level.imaginary_plus,
                    level.imaginary_minus,
                )
            ),
        )

    def to_mapping(self) -> dict[str, object]:
        output = {
            "job_id": self.job_id,
            "leaf_id": self.leaf_id,
            "mechanism_id": self.mechanism_id,
            "status": self.status.value,
            "convergence_basis": self.convergence_basis,
            "usable": self.usable,
            "response": None if self.response is None else _complex_mapping(self.response),
            "signed_root_crosscheck": (
                None
                if self.signed_root_crosscheck is None
                else _complex_mapping(self.signed_root_crosscheck)
            ),
            "closed_form_response": (
                None
                if self.closed_form_response is None
                else _complex_mapping(self.closed_form_response)
            ),
            "error_channels": dict(self.error_channels),
            "baseline": self.baseline.to_mapping(),
            "levels": [level.to_mapping() for level in self.levels],
            "lineage": dict(self.lineage),
        }
        if self.component_scientific_identity is not None:
            output.update({
                "error_channel_applicability": dict(
                    self.error_channel_applicability
                ),
                "component_scientific_identity": (
                    self.component_scientific_identity
                ),
                "response_method": self.response_method,
                "finite_amplitude_ladder_required": (
                    self.finite_amplitude_ladder_required
                ),
                "finite_amplitude_ladder_executed": (
                    self.finite_amplitude_ladder_executed
                ),
                "finite_amplitude_readout_count": (
                    self.finite_amplitude_readout_count
                ),
                "response_uncertainty_status": (
                    self.response_uncertainty_status
                ),
            })
        if self.resolved_window is not None:
            output["resolved_window"] = dict(self.resolved_window)
        if self.derivative_evidence is not None:
            output["derivative_evidence"] = json.loads(
                canonical_json_bytes(dict(self.derivative_evidence))
            )
        if self.analytic_horizon_evidence is not None:
            output["analytic_horizon_evidence"] = json.loads(
                canonical_json_bytes(dict(self.analytic_horizon_evidence))
            )
        return output

    @classmethod
    def from_mapping(cls, value: object) -> "ComponentResult":
        if not isinstance(value, Mapping):
            raise ValueError("component result must be an object")
        response = value.get("response")
        signed = value.get("signed_root_crosscheck")
        closed = value.get("closed_form_response")
        channels = value.get("error_channels")
        if not isinstance(channels, Mapping) or set(channels) != set(ERROR_CHANNELS):
            raise ValueError("component error channels are invalid")
        return cls(
            job_id=str(value["job_id"]),
            leaf_id=str(value["leaf_id"]),
            mechanism_id=str(value["mechanism_id"]),
            status=ComponentStatus(str(value["status"])),
            convergence_basis=str(value["convergence_basis"]),
            response=None if response is None else _complex_from_mapping(response, "response"),
            signed_root_crosscheck=(
                None if signed is None else _complex_from_mapping(signed, "signed root")
            ),
            closed_form_response=(
                None if closed is None else _complex_from_mapping(closed, "closed form")
            ),
            error_channels={key: float(channels[key]) for key in ERROR_CHANNELS},
            baseline=RootReadout.from_mapping(value["baseline"]),
            levels=tuple(LadderLevel.from_mapping(item) for item in value["levels"]),
            lineage=dict(value["lineage"]),
            component_scientific_identity=value.get(
                "component_scientific_identity"
            ),
            response_method=value.get("response_method"),
            finite_amplitude_ladder_required=value.get(
                "finite_amplitude_ladder_required", True
            ),
            finite_amplitude_ladder_executed=value.get(
                "finite_amplitude_ladder_executed", True
            ),
            finite_amplitude_readout_count=value.get(
                "finite_amplitude_readout_count"
            ),
            response_uncertainty_status=value.get(
                "response_uncertainty_status"
            ),
            error_channel_applicability=value.get(
                "error_channel_applicability"
            ),
            resolved_window=value.get("resolved_window"),
            derivative_evidence=value.get("derivative_evidence"),
            analytic_horizon_evidence=value.get("analytic_horizon_evidence"),
        )


def _unresolved_result(
    job: ResponseComponentJob,
    status: ComponentStatus,
    baseline: RootReadout,
    levels: Sequence[LadderLevel],
) -> ComponentResult:
    return ComponentResult(
        job_id=job.job_id,
        leaf_id=job.leaf_id,
        mechanism_id=job.mechanism_id,
        status=status,
        convergence_basis="UNRESOLVED",
        response=None,
        signed_root_crosscheck=None,
        closed_form_response=None,
        error_channels={name: 0.0 for name in ERROR_CHANNELS},
        baseline=baseline,
        levels=tuple(levels),
        lineage=_result_lineage(job),
    )


def _result_lineage(job: ResponseComponentJob) -> dict[str, object]:
    return {
        "leaf_id": job.leaf_id,
        "root_reference_id": job.root.root_reference_id,
        "root_identity_sha256": job.root.identity_sha256,
        "policy_sha256": job.policy.identity_sha256,
        "backend_identity_sha256": job.backend_identity.identity_sha256,
        "equation_id": job.equation_id,
        "sampling_coordinate": job.sampling_coordinate.to_mapping(),
        "source_root_mapping": (
            None
            if job.source_root_mapping is None
            else dict(job.source_root_mapping)
        ),
    }


def _identity_status(job: ResponseComponentJob, readout: RootReadout) -> ComponentStatus | None:
    if (
        readout.root_reference_id != job.root.root_reference_id
        or readout.branch_id != job.root.branch_id
        or readout.equation_id != job.equation_id
    ):
        return ComponentStatus.BRANCH_LOSS
    if not readout.converged:
        return ComponentStatus.NOT_CONVERGED
    return None


def _validated_result(
    backend: RootReadoutBackend, job: ResponseComponentJob, result: ComponentResult
) -> ComponentResult:
    validator = getattr(backend, "validate_reconstructed_result", None)
    if validator is not None:
        validator(job, result)
    return result


def _validate_promoted_exterior_baseline(
    job: ResponseComponentJob,
    baseline: RootReadout,
) -> DerivativeAuthenticationEvidence:
    if baseline.promoted_root_readout_policy != PROMOTED_ROOT_READOUT_POLICY:
        raise ValueError("promoted root-readout policy identity is invalid")
    primary = baseline.primary_acceptance
    if primary is None or not primary.accepted:
        raise ValueError("promoted baseline PRIMARY evidence is not accepted")
    if primary.post_newton_determinant_count != 0:
        raise ValueError("promoted PRIMARY performed post-Newton determinants")
    authentication = primary.derivative_authentication
    if authentication is None:
        raise ValueError(
            "promoted PRIMARY derivative-specific uncertainty evidence is missing"
        )
    if baseline.branch_id != job.root.branch_id:
        raise ValueError("promoted baseline branch identity is invalid")
    conditioning = baseline.numerical_conditioning
    expected = regularised_gsn_mechanism_contract(job.mechanism_id)
    if conditioning is None or any(
        getattr(conditioning, field) != value
        for field, value in expected.items()
    ):
        raise ValueError("promoted exterior determinant convention is invalid")
    return authentication


def _fixed_root_coordinate_derivative(
    samples: Sequence[FixedRootDeterminantSample],
    step: float,
) -> tuple[ComplexDisk, complex, complex, float, float]:
    plus_h, minus_h, plus_half, minus_half = samples
    decimal_digits = max(
        50,
        math.ceil(
            max(sample.working_precision_bits for sample in samples)
            * math.log10(2.0)
        ) + 16,
    )

    def subtract(
        left: DecimalComplex, right: DecimalComplex
    ) -> DecimalComplex:
        return DecimalComplex(
            left.real - right.real,
            left.imaginary - right.imaginary,
        )

    def divide(value: DecimalComplex, denominator: Decimal) -> DecimalComplex:
        return DecimalComplex(
            value.real / denominator,
            value.imaginary / denominator,
        )

    def outward_nonnegative(value: Decimal) -> float:
        converted = float(value)
        if not math.isfinite(converted):
            raise ValueError(
                "fixed-root derivative uncertainty is not representable"
            )
        if Decimal.from_float(converted) < value:
            converted = math.nextafter(converted, math.inf)
        return converted

    with localcontext() as context:
        context.prec = decimal_digits
        coarse_denominator = (
            plus_h.exact_amplitude.real - minus_h.exact_amplitude.real
        )
        fine_denominator = (
            plus_half.exact_amplitude.real
            - minus_half.exact_amplitude.real
        )
        if coarse_denominator <= 0 or fine_denominator <= 0:
            raise ValueError("fixed-root coordinate derivative step is invalid")
        coarse_exact = divide(
            subtract(plus_h.exact_determinant, minus_h.exact_determinant),
            coarse_denominator,
        )
        fine_exact = divide(
            subtract(
                plus_half.exact_determinant,
                minus_half.exact_determinant,
            ),
            fine_denominator,
        )
        fine_error_exact = (
            plus_half.exact_determinant_error_abs
            + minus_half.exact_determinant_error_abs
        ) / fine_denominator
        disagreement_exact = subtract(
            fine_exact, coarse_exact
        ).magnitude()
        radius_exact = fine_error_exact + disagreement_exact
        if radius_exact <= 0:
            raise ValueError(
                "fixed-root coordinate derivative lacks non-exact uncertainty"
            )

        coordinate_disk = _bounded_binary64_disk_from_decimal(
            fine_exact,
            radius_exact,
            subject="fixed-root coordinate derivative",
        )
        coarse = complex(float(coarse_exact.real), float(coarse_exact.imaginary))
        fine = coordinate_disk.centre
        radius = coordinate_disk.radius
        fine_error = outward_nonnegative(fine_error_exact)
        disagreement = outward_nonnegative(disagreement_exact)
    if radius <= 0.0:
        raise ValueError(
            "fixed-root coordinate derivative lacks non-exact uncertainty"
        )
    return coordinate_disk, coarse, fine, fine_error, disagreement


def full_ladder_validation_policy(reason: str) -> dict[str, str]:
    """Bind the expensive legacy ladder to one explicit validation reason."""

    if reason not in FULL_LADDER_VALIDATION_REASONS:
        raise ValueError("full ladder validation reason is invalid")
    return {
        "identity": FULL_COMPLEX_LADDER_VALIDATION_IDENTITY,
        "reason": reason,
    }


def run_promoted_full_ladder_validation(
    job: ResponseComponentJob,
    backend: RootReadoutBackend,
    primary_predictor: complex,
    *,
    reason: str,
) -> dict[str, object]:
    """Execute the legacy ladder only behind an explicit validation policy."""

    validation_policy = full_ladder_validation_policy(reason)
    predictor = _finite_complex(primary_predictor, "PRIMARY root predictor")
    result = run_component(
        job,
        backend,
        response_predictor=predictor,
        _promoted_validation_policy=validation_policy,
    )
    return {
        "validation_policy": validation_policy,
        "result": result,
    }


def _unresolved_promoted_exterior_derivative(
    job: ResponseComponentJob,
    baseline: RootReadout,
    evidence: Mapping[str, object],
) -> ComponentResult:
    return ComponentResult(
        job_id=job.job_id,
        leaf_id=job.leaf_id,
        mechanism_id=job.mechanism_id,
        status=ComponentStatus.DERIVATIVE_UNRESOLVED,
        convergence_basis="UNRESOLVED_FIXED_ROOT_DERIVATIVE",
        response=None,
        signed_root_crosscheck=None,
        closed_form_response=None,
        error_channels={name: 0.0 for name in ERROR_CHANNELS},
        baseline=baseline,
        levels=(),
        lineage={
            **_result_lineage(job),
            "component_scientific_identity": EXTERIOR_DERIVATIVE_COMPONENT_IDENTITY,
        },
        component_scientific_identity=EXTERIOR_DERIVATIVE_COMPONENT_IDENTITY,
        response_method=EXTERIOR_DERIVATIVE_METHOD,
        finite_amplitude_ladder_required=False,
        finite_amplitude_ladder_executed=False,
        finite_amplitude_readout_count=0,
        response_uncertainty_status=UNBOUNDED_DERIVATIVE_RESPONSE,
        error_channel_applicability={name: False for name in ERROR_CHANNELS},
        derivative_evidence=evidence,
    )


_PROMOTED_COMPONENT_JOURNAL_SCHEMA = (
    "windows-solver.promoted-component-journal-receipt/1"
)
_GENERIC_COMPONENT_JOURNAL_IDENTITY = (
    "same-equation-signed-root-component-journal/v1"
)


def _journal_json_value(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _journal_json_value(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_journal_json_value(item) for item in value]
    return value


class _JournaledPromotedExteriorBackend:
    """Persist each expensive promoted readout before the next one begins."""

    def __init__(
        self,
        backend: RootReadoutBackend,
        journal: PartialComponentJournal,
        units_by_role: Mapping[str, PartialComponentWorkUnit],
        *,
        exact_request_binding: bool = False,
    ) -> None:
        self._backend = backend
        self._journal = journal
        self._units_by_role = dict(units_by_role)
        self._exact_request_binding = exact_request_binding
        self.identity = backend.identity

    def _reuse(self, role: str, kind: str) -> RootReadout | FixedRootDeterminantSample | None:
        unit = self._units_by_role[role]
        existing = self._journal.entries.get(unit.work_unit_id)
        if existing is None:
            return None
        if PartialComponentWorkUnit.from_entry(existing) != unit:
            raise ValueError("partial component journal entry identity mismatch")
        receipt = existing.worker_response_receipt
        if (
            receipt.get("schema") != _PROMOTED_COMPONENT_JOURNAL_SCHEMA
            or receipt.get("kind") != kind
            or not isinstance(receipt.get("output"), Mapping)
        ):
            raise ValueError("partial component journal output wrapper is invalid")
        if kind == "root-readout":
            output: RootReadout | FixedRootDeterminantSample = (
                RootReadout.from_mapping(
                    _journal_json_value(receipt["output"])
                )
            )
        else:
            output = FixedRootDeterminantSample.from_mapping(
                _journal_json_value(receipt["output"])
            )
        if self._exact_request_binding:
            output_request_sha256 = (
                output.request_sha256
                if isinstance(output, FixedRootDeterminantSample)
                else (
                    None
                    if output.worker_response_receipt is None
                    else output.worker_response_receipt.get("request_sha256")
                )
            )
            if output_request_sha256 != unit.request_sha256:
                raise ValueError(
                    "partial component reused output request identity mismatch"
                )
        return output

    def _record(
        self,
        role: str,
        kind: str,
        output: RootReadout | FixedRootDeterminantSample,
    ) -> None:
        unit = self._units_by_role[role]
        if self._exact_request_binding:
            output_request_sha256 = (
                output.request_sha256
                if isinstance(output, FixedRootDeterminantSample)
                else (
                    None
                    if output.worker_response_receipt is None
                    else output.worker_response_receipt.get("request_sha256")
                )
            )
            if output_request_sha256 != unit.request_sha256:
                raise ValueError(
                    "partial component output request identity mismatch"
                )
        self._journal.record(unit.to_entry({
            "schema": _PROMOTED_COMPONENT_JOURNAL_SCHEMA,
            "kind": kind,
            "output": output.to_mapping(),
        }))

    def read_root(
        self,
        job: ResponseComponentJob,
        amplitude: complex,
        primary_predictor: complex | None = None,
    ) -> RootReadout:
        if complex(amplitude) != 0.0j:
            raise ValueError("journaled promoted baseline amplitude is invalid")
        reused = self._reuse("baseline-root", "root-readout")
        if reused is not None:
            assert isinstance(reused, RootReadout)
            return reused
        output = self._backend.read_root(
            job, amplitude, primary_predictor=primary_predictor
        )
        self._record("baseline-root", "root-readout", output)
        return output

    def sample_fixed_root_determinant(
        self,
        job: ResponseComponentJob,
        omega: complex,
        amplitude: complex,
        *,
        readout_role: str,
    ) -> FixedRootDeterminantSample:
        unit = self._units_by_role.get(readout_role)
        if unit is None or unit.amplitude != complex(amplitude):
            raise ValueError("fixed-root readout is outside the journal plan")
        reused = self._reuse(readout_role, "fixed-root-determinant-sample")
        if reused is not None:
            assert isinstance(reused, FixedRootDeterminantSample)
            return reused
        output = self._backend.sample_fixed_root_determinant(
            job,
            omega,
            amplitude,
            readout_role=readout_role,
        )
        self._record(readout_role, "fixed-root-determinant-sample", output)
        return output

    def validate_component_result(
        self, job: ResponseComponentJob, result: ComponentResult
    ) -> None:
        validator = getattr(self._backend, "validate_component_result", None)
        if validator is not None:
            validator(job, result)


class _JournaledComponentReads:
    """Journal ordinary component root reads at the engine call boundary."""

    def __init__(
        self,
        backend: RootReadoutBackend,
        journal: PartialComponentJournal,
        units: Mapping[tuple[str, complex], PartialComponentWorkUnit],
    ) -> None:
        self.backend = backend
        self.journal = journal
        self.units = dict(units)

    def read_root(
        self,
        job: ResponseComponentJob,
        role: str,
        amplitude: complex,
        primary_predictor: complex | None,
        primary_predictor_kind: str | None,
    ) -> RootReadout:
        key = (role, complex(amplitude))
        unit = self.units.get(key)
        if unit is None:
            raise ValueError("component root readout is outside the journal plan")
        existing = self.journal.entries.get(unit.work_unit_id)
        if existing is not None:
            if PartialComponentWorkUnit.from_entry(existing) != unit:
                raise ValueError("partial component journal entry identity mismatch")
            receipt = existing.worker_response_receipt
            if (
                receipt.get("schema") != _PROMOTED_COMPONENT_JOURNAL_SCHEMA
                or receipt.get("kind") != "root-readout"
                or not isinstance(receipt.get("output"), Mapping)
            ):
                raise ValueError("partial component journal output wrapper is invalid")
            output = RootReadout.from_mapping(
                _journal_json_value(receipt["output"])
            )
            if output.worker_response_receipt is not None and (
                output.worker_response_receipt.get("request_sha256")
                != unit.request_sha256
            ):
                raise ValueError(
                    "partial component reused output request identity mismatch"
                )
            return output
        read_with_kind = getattr(
            self.backend, "read_root_with_predictor_kind", None
        )
        if (
            primary_predictor is not None
            and primary_predictor_kind is not None
            and callable(read_with_kind)
        ):
            output = read_with_kind(
                job,
                amplitude,
                primary_predictor,
                primary_predictor_kind,
            )
        else:
            output = self.backend.read_root(
                job,
                amplitude,
                primary_predictor=primary_predictor,
            )
        if output.worker_response_receipt is not None and (
            output.worker_response_receipt.get("request_sha256")
            != unit.request_sha256
        ):
            raise ValueError("partial component output request identity mismatch")
        self.journal.record(unit.to_entry({
            "schema": _PROMOTED_COMPONENT_JOURNAL_SCHEMA,
            "kind": "root-readout",
            "output": output.to_mapping(),
        }))
        return output


def _generic_component_journal(
    job: ResponseComponentJob,
    backend: RootReadoutBackend,
) -> _JournaledComponentReads | None:
    existing_controller = getattr(backend, "_component_journal", None)
    if isinstance(existing_controller, _JournaledComponentReads):
        return existing_controller
    root_text = os.environ.get("KERR_QNM_PARTIAL_COMPONENT_JOURNAL_ROOT", "")
    if not root_text.strip():
        return None
    if getattr(backend, "promoted_precision_backend", False):
        # Promoted runners own exact Julia request binding separately.
        return None
    contract = regularised_gsn_mechanism_contract(job.mechanism_id)
    component_identity = str(getattr(
        backend, "journal_component_identity", _GENERIC_COMPONENT_JOURNAL_IDENTITY
    ))
    planned: list[tuple[str, complex]] = [("baseline", 0.0j)]
    for epsilon in (*job.policy.epsilons, *_expansion_epsilons(job)):
        planned.extend((
            ("real-plus", complex(epsilon, 0.0)),
            ("real-minus", complex(-epsilon, 0.0)),
            ("imaginary-plus", complex(0.0, epsilon)),
            ("imaginary-minus", complex(0.0, -epsilon)),
        ))
    units: dict[tuple[str, complex], PartialComponentWorkUnit] = {}
    for role, amplitude in planned:
        epsilon = abs(amplitude)
        recorded_role = (
            role if epsilon == 0.0 else f"{role}@{epsilon}"
        )
        preview = getattr(backend, "preview_root_request", None)
        request_binding = (
            preview(job, amplitude, None, None, recorded_role)
            if callable(preview)
            else {
                "schema": "windows-solver.native-root-readout-request/1",
                "job": job.to_mapping(),
                "policy_sha256": job.policy.identity_sha256,
                "backend_identity_sha256": backend.identity.identity_sha256,
                "readout_role": recorded_role,
                "amplitude": _complex_mapping(amplitude),
            }
        )
        tier_provider = getattr(backend, "precision_tier_for_request", None)
        tier = (
            precision_tier(tier_provider(role, amplitude))
            if callable(tier_provider)
            else PrecisionTier.BINARY64
        )
        units[(role, amplitude)] = PartialComponentWorkUnit(
            component_scientific_identity=component_identity,
            leaf_id=job.leaf_id,
            job_id=job.job_id,
            policy_sha256=job.policy.identity_sha256,
            backend_identity=backend.identity.identity_sha256,
            determinant_family=str(contract["determinant_family"]),
            determinant_normalisation=str(contract["determinant_normalisation"]),
            precision_tier=tier,
            mpfr_bits=working_precision_bits(tier),
            amplitude=amplitude,
            epsilon=epsilon,
            readout_role=recorded_role,
            refinement_level=0,
            request_sha256=_sha256(request_binding),
        )
    expected = tuple(unit.work_unit_id for unit in units.values())
    journal_path = Path(root_text) / (
        _sha256({
            "job_id": job.job_id,
            "component_scientific_identity": component_identity,
        }) + ".json"
    )
    journal = (
        PartialComponentJournal.load(journal_path)
        if journal_path.exists()
        else PartialComponentJournal.create(
            journal_path, expected_work_unit_ids=expected
        )
    )
    if journal.expected_work_unit_ids != expected:
        raise ValueError("partial component journal plan identity mismatch")
    return _JournaledComponentReads(backend, journal, units)


def _journaled_promoted_exterior_backend(
    job: ResponseComponentJob,
    backend: RootReadoutBackend,
    *,
    predictor: complex,
    derivative_step: float,
    validation_reason: str | None,
) -> RootReadoutBackend:
    root_text = os.environ.get("KERR_QNM_PARTIAL_COMPONENT_JOURNAL_ROOT", "")
    if not root_text.strip():
        return backend
    raw_tier = getattr(backend, "sample_tier", None)
    if raw_tier is None:
        digits = getattr(backend, "digits", None)
        raw_tier = {
            40: PrecisionTier.BIGFLOAT_40,
            80: PrecisionTier.BIGFLOAT_80,
            120: PrecisionTier.BIGFLOAT_120,
        }.get(digits)
    if raw_tier is None:
        raise ValueError("journaled promoted backend lacks a semantic precision tier")
    tier = precision_tier(raw_tier)
    contract = regularised_gsn_mechanism_contract(job.mechanism_id)
    planned = [
        (0.0j, "baseline-root"),
        (complex(derivative_step, 0.0), "coordinate-real-plus-h"),
        (complex(-derivative_step, 0.0), "coordinate-real-minus-h"),
        (complex(derivative_step / 2.0, 0.0), "coordinate-real-plus-h2"),
        (complex(-derivative_step / 2.0, 0.0), "coordinate-real-minus-h2"),
    ]
    if validation_reason is not None:
        planned.extend((
            (complex(0.0, derivative_step / 2.0), "coordinate-imaginary-plus-h2"),
            (complex(0.0, -derivative_step / 2.0), "coordinate-imaginary-minus-h2"),
        ))
    units: dict[str, PartialComponentWorkUnit] = {}
    preview_root = getattr(backend, "preview_root_request", None)
    preview_fixed = getattr(backend, "preview_fixed_root_request", None)
    exact_request_binding = callable(preview_root) and callable(preview_fixed)
    for amplitude, role in planned:
        if role == "baseline-root" and callable(preview_root):
            request_binding = preview_root(
                job, amplitude, predictor, None, role
            )
        elif role != "baseline-root" and callable(preview_fixed):
            request_binding = preview_fixed(
                job, predictor, amplitude, role
            )
        else:
            request_binding = {
                "amplitude": _complex_mapping(amplitude),
                "component_scientific_identity": EXTERIOR_DERIVATIVE_COMPONENT_IDENTITY,
                "job_id": job.job_id,
                "leaf_id": job.leaf_id,
                "policy_sha256": job.policy.identity_sha256,
                "precision_tier": tier.value,
                "primary_predictor": _complex_mapping(predictor),
                "readout_role": role,
                "validation_reason": validation_reason,
            }
        request_sha256 = _sha256(request_binding)
        units[role] = PartialComponentWorkUnit(
            component_scientific_identity=EXTERIOR_DERIVATIVE_COMPONENT_IDENTITY,
            leaf_id=job.leaf_id,
            job_id=job.job_id,
            policy_sha256=job.policy.identity_sha256,
            backend_identity=job.backend_identity.identity_sha256,
            determinant_family=str(contract["determinant_family"]),
            determinant_normalisation=str(contract["determinant_normalisation"]),
            precision_tier=tier,
            mpfr_bits=working_precision_bits(tier),
            amplitude=amplitude,
            epsilon=abs(amplitude),
            readout_role=role,
            refinement_level=int(getattr(backend, "refinement", 0)),
            request_sha256=request_sha256,
        )
    expected = tuple(unit.work_unit_id for unit in units.values())
    journal_name = _sha256({
        "job_id": job.job_id,
        "component_scientific_identity": EXTERIOR_DERIVATIVE_COMPONENT_IDENTITY,
    }) + ".json"
    journal_path = Path(root_text) / journal_name
    journal = (
        PartialComponentJournal.load(journal_path)
        if journal_path.exists()
        else PartialComponentJournal.create(
            journal_path, expected_work_unit_ids=expected
        )
    )
    if journal.expected_work_unit_ids != expected:
        raise ValueError("partial component journal plan identity mismatch")
    return _JournaledPromotedExteriorBackend(
        backend,
        journal,
        units,
        exact_request_binding=exact_request_binding,
    )


def run_promoted_exterior_component(
    job: ResponseComponentJob,
    backend: RootReadoutBackend,
    primary_predictor: complex,
    *,
    derivative_step: float,
    validation_reason: str | None = None,
) -> ComponentResult:
    """Compute ``-D_c/D_omega`` without solving a perturbed root."""

    if job.mechanism_id not in _EXTERIOR_PROFILE_IDS:
        raise ValueError("promoted exterior runner requires an exterior job")
    if (
        validation_reason is not None
        and validation_reason not in FULL_LADDER_VALIDATION_REASONS
    ):
        raise ValueError("promoted exterior validation reason is invalid")
    step = float(derivative_step)
    if not math.isfinite(step) or step <= 0.0:
        raise ValueError("exterior derivative step must be finite and positive")
    if backend.identity != job.backend_identity:
        raise ValueError("response backend identity does not match job")
    predictor = _finite_complex(primary_predictor, "PRIMARY root predictor")
    binder = getattr(backend, "bind_job", None)
    if binder is not None:
        job = binder(job)
    backend = _journaled_promoted_exterior_backend(
        job,
        backend,
        predictor=predictor,
        derivative_step=step,
        validation_reason=validation_reason,
    )
    baseline = backend.read_root(job, 0.0j, primary_predictor=predictor)
    initial_status = _identity_status(job, baseline)
    if initial_status is not None:
        return _validated_result(
            backend, job, _unresolved_result(job, initial_status, baseline, ())
        )
    primary = baseline.primary_acceptance
    if (
        primary is not None
        and primary.accepted
        and primary.derivative_authentication is None
    ):
        result = _unresolved_promoted_exterior_derivative(
            job,
            baseline,
            {
                "conditioning_decision": {
                    "accepted": False,
                    "identity": FIXED_ROOT_DERIVATIVE_CONDITIONING_IDENTITY,
                    "rejection_reason": (
                        "MISSING_FREQUENCY_DERIVATIVE_AUTHENTICATION"
                    ),
                    "selected_candidate": None,
                },
                "determinant_count": 0,
                "failure_code": (
                    "MISSING_FREQUENCY_DERIVATIVE_AUTHENTICATION"
                ),
                "fixed_root_samples": [],
                "response_disk_identity": (
                    EXTERIOR_DERIVATIVE_RESPONSE_DISK_IDENTITY
                ),
            },
        )
        return _validated_result(backend, job, result)
    frequency_authentication = _validate_promoted_exterior_baseline(job, baseline)
    assert primary is not None
    if (
        frequency_authentication.determinant_error_status
        != DETERMINANT_ERROR_AVAILABLE
        or primary.error_model_id is None
        or frequency_authentication.determinant_error_model_id
        != primary.error_model_id
    ):
        result = _unresolved_promoted_exterior_derivative(
            job,
            baseline,
            {
                "conditioning_decision": {
                    "accepted": False,
                    "identity": FIXED_ROOT_DERIVATIVE_CONDITIONING_IDENTITY,
                    "rejection_reason": "DETERMINANT_ERROR_MODEL_UNAVAILABLE",
                    "selected_candidate": None,
                },
                "determinant_count": 0,
                "determinant_error_provenance": {
                    "derivative_status": (
                        frequency_authentication.determinant_error_status
                    ),
                    "derivative_model_id": (
                        frequency_authentication.determinant_error_model_id
                    ),
                    "primary_model_id": primary.error_model_id,
                },
                "failure_code": "DETERMINANT_ERROR_MODEL_UNAVAILABLE",
                "fixed_root_samples": [],
                "math_review_blocker": (
                    EXTERIOR_DETERMINANT_ERROR_MATH_REVIEW_BLOCKER
                ),
                "response_disk_identity": (
                    EXTERIOR_DERIVATIVE_RESPONSE_DISK_IDENTITY
                ),
            },
        )
        return _validated_result(backend, job, result)
    sample_operation = getattr(backend, "sample_fixed_root_determinant", None)
    if not callable(sample_operation):
        raise ValueError("fixed-root determinant sample boundary is unavailable")

    amplitudes_and_roles = (
        (complex(step, 0.0), "coordinate-real-plus-h"),
        (complex(-step, 0.0), "coordinate-real-minus-h"),
        (complex(step / 2.0, 0.0), "coordinate-real-plus-h2"),
        (complex(-step / 2.0, 0.0), "coordinate-real-minus-h2"),
    )
    samples = tuple(
        sample_operation(
            job,
            baseline.omega,
            amplitude,
            readout_role=role,
        )
        for amplitude, role in amplitudes_and_roles
    )
    imaginary_axis_validation = None
    if validation_reason is not None:
        imaginary_step = step / 2.0
        imaginary_samples = tuple(
            sample_operation(
                job,
                baseline.omega,
                amplitude,
                readout_role=role,
            )
            for amplitude, role in (
                (complex(0.0, imaginary_step), "coordinate-imaginary-plus-h2"),
                (complex(0.0, -imaginary_step), "coordinate-imaginary-minus-h2"),
            )
        )
        samples = (*samples, *imaginary_samples)
    expected_contract = regularised_gsn_mechanism_contract(job.mechanism_id)
    assert baseline.numerical_conditioning is not None
    expected_branch_identity = baseline.numerical_conditioning.branch_convention
    first = samples[0]
    expected_samples = (*amplitudes_and_roles, *((
        (complex(0.0, step / 2.0), "coordinate-imaginary-plus-h2"),
        (complex(0.0, -step / 2.0), "coordinate-imaginary-minus-h2"),
    ) if validation_reason is not None else ()))
    for sample, (amplitude, role) in zip(samples, expected_samples):
        if (
            not isinstance(sample, FixedRootDeterminantSample)
            or sample.omega != baseline.omega
            or sample.amplitude != amplitude
            or sample.readout_role != role
            or not sample.branch_authenticated
            or sample.branch_identity != expected_branch_identity
            or sample.determinant_family != expected_contract["determinant_family"]
            or sample.determinant_normalisation
            != expected_contract["determinant_normalisation"]
            or sample.precision_tier != first.precision_tier
            or sample.working_precision_bits != first.working_precision_bits
        ):
            raise ValueError("fixed-root determinant sample binding is invalid")
    unavailable_samples = tuple(
        sample
        for sample in samples
        if sample.determinant_error_status != DETERMINANT_ERROR_AVAILABLE
        or sample.determinant_error_model_id is None
    )
    if unavailable_samples:
        return _validated_result(
            backend,
            job,
            _unresolved_promoted_exterior_derivative(
                job,
                baseline,
                {
                    "conditioning_decision": {
                        "accepted": False,
                        "identity": FIXED_ROOT_DERIVATIVE_CONDITIONING_IDENTITY,
                        "rejection_reason": "DETERMINANT_ERROR_MODEL_UNAVAILABLE",
                        "selected_candidate": None,
                    },
                    "determinant_count": len(samples),
                    "failure_code": "DETERMINANT_ERROR_MODEL_UNAVAILABLE",
                    "fixed_root_samples": [
                        sample.to_mapping() for sample in samples
                    ],
                    "math_review_blocker": (
                        EXTERIOR_DETERMINANT_ERROR_MATH_REVIEW_BLOCKER
                    ),
                    "response_disk_identity": (
                        EXTERIOR_DERIVATIVE_RESPONSE_DISK_IDENTITY
                    ),
                },
            ),
        )

    coordinate_disk, coarse, fine, propagated_error, disagreement = (
        _fixed_root_coordinate_derivative(samples[:4], step)
    )
    conditioning_decision = {
        "accepted": abs(fine) > coordinate_disk.radius,
        "identity": FIXED_ROOT_DERIVATIVE_CONDITIONING_IDENTITY,
        "rejection_reason": None,
        "selected_candidate": "h/2",
    }
    if not conditioning_decision["accepted"]:
        conditioning_decision.update({
            "rejection_reason": "DERIVATIVE_DISK_CONTAINS_ZERO",
            "selected_candidate": None,
        })
        result = _unresolved_promoted_exterior_derivative(
            job,
            baseline,
            {
                "conditioning_decision": conditioning_decision,
                "coordinate_derivative_disk": coordinate_disk.to_mapping(),
                "determinant_count": len(samples),
                "failure_code": "NO_ADMISSIBLE_FIXED_ROOT_DERIVATIVE_STEP",
                "fixed_root_samples": [sample.to_mapping() for sample in samples],
                "propagated_determinant_error_abs": propagated_error,
                "raw_step_disagreement_abs": disagreement,
                "response_disk_identity": EXTERIOR_DERIVATIVE_RESPONSE_DISK_IDENTITY,
            },
        )
        return _validated_result(backend, job, result)
    if validation_reason is not None:
        imaginary_plus, imaginary_minus = samples[4:]
        imaginary_step = step / 2.0
        imaginary_derivative = (
            imaginary_plus.determinant - imaginary_minus.determinant
        ) / (2.0j * imaginary_step)
        imaginary_error = (
            imaginary_plus.determinant_error_abs
            + imaginary_minus.determinant_error_abs
        ) / (2.0 * imaginary_step)
        axis_difference = abs(imaginary_derivative - fine)
        agreement_radius = imaginary_error + coordinate_disk.radius
        imaginary_axis_validation = {
            "agrees": axis_difference <= agreement_radius,
            "axis_difference_abs": axis_difference,
            "derivative": _complex_mapping(imaginary_derivative),
            "propagated_error_abs": imaginary_error,
        }
        if not imaginary_axis_validation["agrees"]:
            raise ValueError("fixed-root derivative axes disagree")
    frequency_radius = float(
        frequency_authentication.propagated_error_abs
        + frequency_authentication.step_disagreement_abs
    )
    if frequency_radius <= 0.0:
        raise ValueError(
            "promoted PRIMARY derivative lacks non-exact uncertainty"
        )
    frequency_disk = ComplexDisk(
        complex(
            float(frequency_authentication.derivative_re),
            float(frequency_authentication.derivative_im),
        ),
        frequency_radius,
    )
    try:
        response_disk = exterior_response_disk(
            coordinate_derivative=coordinate_disk,
            frequency_derivative=frequency_disk,
        )
    except ZeroContainingDiskError as error:
        result = _unresolved_promoted_exterior_derivative(
            job,
            baseline,
            {
                "conditioning_decision": conditioning_decision,
                "coordinate_derivative_disk": coordinate_disk.to_mapping(),
                "determinant_count": len(samples),
                "failure_code": "FREQUENCY_DERIVATIVE_DISK_CONTAINS_ZERO",
                "fixed_root_samples": [sample.to_mapping() for sample in samples],
                "response_disk_identity": EXTERIOR_DERIVATIVE_RESPONSE_DISK_IDENTITY,
                "zero_containing_disk": error.disk_name,
            },
        )
        return _validated_result(backend, job, result)
    frequency_radius_provenance = {
        "axis": frequency_authentication.axis,
        "propagated_error_abs": str(
            frequency_authentication.propagated_error_abs
        ),
        "selected_step": str(frequency_authentication.selected_step),
        "step_disagreement_abs": str(
            frequency_authentication.step_disagreement_abs
        ),
    }
    derivative_evidence = {
        "coordinate_derivative_disk": coordinate_disk.to_mapping(),
        "conditioning_decision": conditioning_decision,
        "coordinate_derivative_source": EXTERIOR_DERIVATIVE_METHOD,
        "determinant_count": len(samples),
        "fine_derivative": _complex_mapping(fine),
        "fixed_root_samples": [sample.to_mapping() for sample in samples],
        "frequency_derivative_disk": frequency_disk.to_mapping(),
        "frequency_derivative_radius_provenance": frequency_radius_provenance,
        "propagated_determinant_error_abs": propagated_error,
        "raw_step_disagreement_abs": disagreement,
        "real_h_derivative": _complex_mapping(coarse),
        "response_disk": response_disk.to_mapping(),
        "response_disk_identity": EXTERIOR_DERIVATIVE_RESPONSE_DISK_IDENTITY,
        "selected_step": step / 2.0,
        "shared_equation_source": True,
        "imaginary_axis_validation": imaginary_axis_validation,
        "validation_policy_identity": (
            None
            if validation_reason is None
            else FIXED_ROOT_AXIS_VALIDATION_IDENTITY
        ),
        "validation_reason": validation_reason,
    }
    result = ComponentResult(
        job_id=job.job_id,
        leaf_id=job.leaf_id,
        mechanism_id=job.mechanism_id,
        status=ComponentStatus.CONVERGED,
        convergence_basis="FIXED_ROOT_REAL_H_H2_DERIVATIVE_DISK",
        response=response_disk.centre,
        signed_root_crosscheck=None,
        closed_form_response=None,
        error_channels={
            **{name: 0.0 for name in ERROR_CHANNELS},
            "resolution": response_disk.radius,
        },
        baseline=baseline,
        levels=(),
        lineage={
            **_result_lineage(job),
            "component_scientific_identity": EXTERIOR_DERIVATIVE_COMPONENT_IDENTITY,
        },
        component_scientific_identity=EXTERIOR_DERIVATIVE_COMPONENT_IDENTITY,
        response_method=EXTERIOR_DERIVATIVE_METHOD,
        finite_amplitude_ladder_required=False,
        finite_amplitude_ladder_executed=False,
        finite_amplitude_readout_count=0,
        response_uncertainty_status=BOUNDED_DERIVATIVE_RESPONSE,
        error_channel_applicability={
            name: name == "resolution" for name in ERROR_CHANNELS
        },
        derivative_evidence=derivative_evidence,
    )
    return _validated_result(backend, job, result)


def _promoted_horizon_result(
    job: ResponseComponentJob,
    *,
    status: ComponentStatus,
    baseline: RootReadout,
    response_disk: ComplexDisk | None,
    evidence: Mapping[str, object],
) -> ComponentResult:
    """Build bounded or explicitly unusable promoted horizon evidence."""

    bounded = response_disk is not None

    return ComponentResult(
        job_id=job.job_id,
        leaf_id=job.leaf_id,
        mechanism_id=job.mechanism_id,
        status=status,
        convergence_basis=(
            "PRIMARY_TRUNCATION_RESOLUTION_FIXED_ROOT"
            if status is ComponentStatus.CONVERGED
            else "UNRESOLVED"
        ),
        response=None if response_disk is None else response_disk.centre,
        signed_root_crosscheck=None,
        closed_form_response=(
            None if response_disk is None else response_disk.centre
        ),
        error_channels={
            **{name: 0.0 for name in ERROR_CHANNELS},
            "resolution": 0.0 if response_disk is None else response_disk.radius,
        },
        baseline=baseline,
        levels=(),
        lineage={
            **_result_lineage(job),
            "component_scientific_identity": (
                PROMOTED_HORIZON_COMPONENT_V2_IDENTITY
            ),
        },
        component_scientific_identity=(
            PROMOTED_HORIZON_COMPONENT_V2_IDENTITY
        ),
        response_method=(
            PROMOTED_HORIZON_RESPONSE_METHOD_V2
        ),
        finite_amplitude_ladder_required=False,
        finite_amplitude_ladder_executed=False,
        finite_amplitude_readout_count=0,
        response_uncertainty_status=(
            BOUNDED_ANALYTIC_RESPONSE
            if bounded
            else UNBOUNDED_ANALYTIC_RESPONSE
        ),
        error_channel_applicability={
            name: bounded and name == "resolution" for name in ERROR_CHANNELS
        },
        analytic_horizon_evidence=evidence,
    )


def _validate_promoted_horizon_baseline(
    job: ResponseComponentJob,
    baseline: RootReadout,
) -> DerivativeAuthenticationEvidence:
    """Re-check operator-validated single-readout evidence before using it."""

    if baseline.promoted_root_readout_policy != PROMOTED_ROOT_READOUT_POLICY:
        raise ValueError("promoted root-readout policy identity is invalid")
    primary = baseline.primary_acceptance
    if primary is None:
        raise ValueError("promoted baseline PRIMARY evidence is missing")
    if not primary.accepted:
        raise ValueError("promoted baseline PRIMARY evidence was rejected")
    if primary.post_newton_determinant_count != 0:
        raise ValueError("promoted PRIMARY performed post-Newton determinants")
    derivative_authentication = primary.derivative_authentication
    if derivative_authentication is None:
        raise ValueError(
            "promoted PRIMARY derivative-specific uncertainty evidence is missing"
        )
    if baseline.seed_path_required is not False:
        raise ValueError("promoted SEED-PATH must not be required")
    if baseline.seed_path_executed is not False:
        raise ValueError("promoted SEED-PATH must not be executed")
    if baseline.seed_path_determinant_count != 0:
        raise ValueError("promoted SEED-PATH determinant budget is not zero")

    for family, phase in (
        ("truncation", "TRUNCATION"),
        ("resolution", "RESOLUTION"),
    ):
        diagnostic = baseline.diagnostic_readouts.get(family)
        evidence = (
            None if diagnostic is None else diagnostic.fixed_root_evidence
        )
        if evidence is None:
            raise ValueError(f"promoted {phase} fixed-root evidence is missing")
        if not evidence.accepted:
            raise ValueError(f"promoted {phase} fixed-root evidence was rejected")
        if evidence.determinant_count != 1:
            raise ValueError(f"promoted {phase} determinant budget is not one")
        if not evidence.fixed_root:
            raise ValueError(f"promoted {phase} moved the PRIMARY root")
        if evidence.derivative_source != "PRIMARY_COMPLEX":
            raise ValueError(f"promoted {phase} did not reuse PRIMARY derivative")
        if evidence.primary_derivative != primary.derivative:
            raise ValueError(f"promoted {phase} PRIMARY derivative is inconsistent")

    conditioning = baseline.numerical_conditioning
    if (
        conditioning is None
        or conditioning.determinant_convention
        != HORIZON_DETERMINANT_CONVENTION
    ):
        raise ValueError("promoted horizon determinant convention is invalid")
    if baseline.branch_id != job.root.branch_id:
        raise ValueError("promoted baseline branch identity is invalid")
    return derivative_authentication


def run_promoted_horizon_component(
    job: ResponseComponentJob,
    backend: RootReadoutBackend,
    primary_predictor: complex,
) -> ComponentResult:
    """Run one promoted baseline and derive the horizon response algebraically.

    This is deliberately not a finite-amplitude component runner.  The Julia
    root readout already performs PRIMARY plus the two fixed-root diagnostics;
    its retained complex PRIMARY derivative supplies the implicit response.
    """

    if (
        job.role not in {"primary", "deep"}
        or job.mechanism_id != "horizon-admittance"
    ):
        raise ValueError(
            "promoted component runner requires a promoted horizon job"
        )
    if not math.isfinite(job.spin) or abs(job.spin) >= 1.0:
        raise ValueError(
            "promoted horizon Kerr spin must be finite and subextremal"
        )
    if backend.identity != job.backend_identity:
        raise ValueError("response backend identity does not match job")
    predictor = _finite_complex(primary_predictor, "PRIMARY root predictor")
    binder = getattr(backend, "bind_job", None)
    if binder is not None:
        job = binder(job)
    if backend.identity != job.backend_identity:
        raise ValueError("bound response backend identity does not match job")

    amplitude = 0.0j
    with progress_scope(
        readout_index=1,
        readout_role="baseline",
        epsilon=None,
        amplitude={"real": 0.0, "imaginary": 0.0},
    ):
        started = time.monotonic()
        emit_progress(ProgressEventKind.AMPLITUDE_READOUT_STARTED)
        baseline = backend.read_root(
            job,
            amplitude,
            primary_predictor=predictor,
        )
        emit_progress(
            ProgressEventKind.AMPLITUDE_READOUT_COMPLETED,
            current_omega={
                "real": baseline.omega.real,
                "imaginary": baseline.omega.imag,
            },
            determinant_abs=baseline.determinant_residual_abs,
            derivative_abs=baseline.determinant_derivative_abs,
            converged=baseline.converged,
            elapsed_seconds=time.monotonic() - started,
        )

    initial_status = _identity_status(job, baseline)
    if initial_status is not None:
        return _validated_result(
            backend,
            job,
            _unresolved_result(job, initial_status, baseline, ()),
        )

    derivative_authentication = _validate_promoted_horizon_baseline(job, baseline)
    primary = baseline.primary_acceptance
    assert primary is not None
    if derivative_authentication.derivative_estimate.magnitude() <= 0:
        raise ValueError("promoted PRIMARY derivative must be finite and nonzero")
    derivative_disk = _bounded_binary64_disk_from_decimal(
        derivative_authentication.derivative_estimate,
        derivative_authentication.propagated_error_abs
        + derivative_authentication.step_disagreement_abs,
        subject="promoted PRIMARY derivative",
    )
    derivative_complex = derivative_disk.centre

    horizon_radius = 1.0 + math.sqrt(
        max(0.0, 1.0 - job.spin * job.spin)
    )
    omega_h = job.spin / (2.0 * horizon_radius)
    horizon_frequency = baseline.omega - job.mode.m * omega_h
    correction_evidence = {
        "PRIMARY": primary.correction_abs,
        **{
            phase.upper(): baseline.diagnostic_readouts[phase]
            .fixed_root_evidence.correction_abs
            for phase in ("truncation", "resolution")
        },
    }
    arithmetic_radius = (
        math.ulp(baseline.omega.real)
        + math.ulp(baseline.omega.imag)
        + abs(job.mode.m) * math.ulp(omega_h)
    )
    root_radius = max(float(value) for value in correction_evidence.values())
    horizon_frequency_disk = ComplexDisk(
        horizon_frequency,
        root_radius + arithmetic_radius,
    )
    derivative_radius = derivative_disk.radius
    comparison_mapping = None
    comparison_operation = getattr(
        backend, "promoted_derivative_comparison", None
    )
    if callable(comparison_operation):
        comparison = comparison_operation(job, baseline)
        if not isinstance(comparison, ComplexDisk):
            raise ValueError("promoted derivative comparison is invalid")
        derivative_radius = max(
            derivative_radius,
            abs(comparison.centre - derivative_complex) + comparison.radius,
        )
        comparison_mapping = comparison.to_mapping()
    derivative_disk = ComplexDisk(derivative_complex, derivative_radius)
    evidence = {
        "derivative_disk": derivative_disk.to_mapping(),
        "derivative_radius_provenance": {
            "axis": derivative_authentication.axis,
            "independent_comparison": comparison_mapping,
            "independent_comparison_omitted_reason": (
                None
                if comparison_mapping is not None
                else "NOT_SELECTED_BY_RISK_POLICY"
            ),
            "propagated_error_abs": str(
                derivative_authentication.propagated_error_abs
            ),
            "selected_step": str(derivative_authentication.selected_step),
            "step_disagreement_abs": str(
                derivative_authentication.step_disagreement_abs
            ),
        },
        "horizon_frequency_disk": horizon_frequency_disk.to_mapping(),
        "response_disk": None,
        "root_radius_provenance": {
            "arithmetic_radius_abs": arithmetic_radius,
            "correction_abs": {
                key: str(value) for key, value in correction_evidence.items()
            },
            "union_rule": "max-accepted-correction-plus-arithmetic/v1",
        },
        "uncertainty_derivation_identity": (
            PROMOTED_HORIZON_UNCERTAINTY_DERIVATION_IDENTITY
        ),
        "zero_containing_disk": None,
    }
    try:
        response_disk = horizon_response_disk(
            horizon_frequency=horizon_frequency_disk,
            determinant_derivative=derivative_disk,
        )
    except ZeroContainingDiskError as error:
        evidence["zero_containing_disk"] = error.disk_name
        result = _promoted_horizon_result(
            job,
            status=ComponentStatus.DERIVATIVE_UNRESOLVED,
            baseline=baseline,
            response_disk=None,
            evidence=evidence,
        )
        return _validated_result(backend, job, result)
    evidence["response_disk"] = response_disk.to_mapping()

    return _validated_result(
        backend,
        job,
        _promoted_horizon_result(
            job,
            status=ComponentStatus.CONVERGED,
            baseline=baseline,
            response_disk=response_disk,
            evidence=evidence,
        ),
    )


@dataclass(frozen=True, slots=True)
class _LadderVerdict:
    """What one consecutive epsilon window establishes on its own evidence."""

    outcome: str
    convergence_basis: str | None = None
    status: ComponentStatus | None = None
    real_estimate: _AxisEstimate | None = None
    imaginary_estimate: _AxisEstimate | None = None
    combined_estimate: _AxisEstimate | None = None


def _evaluate_ladder_window(
    job: ResponseComponentJob, window: Sequence[LadderLevel]
) -> _LadderVerdict:
    """Decide whether one consecutive epsilon window resolves the response."""

    if len(window) < LADDER_WINDOW_MINIMUM_LEVELS:
        return _LadderVerdict("continue")
    finest = window[-1]
    real_estimate = _axis_estimate(window, "real")
    imaginary_estimate = _axis_estimate(window, "imaginary")
    combined_estimate = _axis_estimate(window, "combined")
    estimates: dict[str, _AxisEstimate] = {
        "real_estimate": real_estimate,
        "imaginary_estimate": imaginary_estimate,
        "combined_estimate": combined_estimate,
    }
    axis_difference = abs(real_estimate.center - imaginary_estimate.center)
    axis_allowance = job.policy.axis_tolerance_factor * max(
        real_estimate.root_radius
        + imaginary_estimate.root_radius
        + real_estimate.amplitude_radius
        + imaginary_estimate.amplitude_radius,
        job.policy.absolute_axis_floor,
    )
    if axis_difference > axis_allowance:
        return _LadderVerdict(
            "unresolved", status=ComponentStatus.AXIS_MISMATCH, **estimates
        )
    if not finest.signal_resolved(job.policy.signal_to_root_factor):
        return _LadderVerdict(
            "unresolved", status=ComponentStatus.NOISE_FLOOR, **estimates
        )

    epsilons = [item.epsilon for item in window]
    real_values = [item.real_secant for item in window]
    imaginary_values = [item.imaginary_secant for item in window]
    real_orders = _observed_orders(epsilons, real_values)
    imaginary_orders = _observed_orders(epsilons, imaginary_values)
    even_orders = _positive_orders(
        epsilons, [item.even_remainder_abs for item in window]
    )
    real_order_ok = (
        bool(real_orders)
        and real_orders[-1] >= 2.0 - job.policy.order_tolerance
    )
    imaginary_order_ok = (
        bool(imaginary_orders)
        and imaginary_orders[-1] >= 2.0 - job.policy.order_tolerance
    )
    even_order_ok = (
        not even_orders
        or even_orders[-1] >= 2.0 - job.policy.even_order_tolerance
    )
    root_limited = (
        abs(real_values[-1] - real_values[-2])
        <= window[-1].real_radius + window[-2].real_radius + 1.0e-15
        and abs(imaginary_values[-1] - imaginary_values[-2])
        <= window[-1].imaginary_radius + window[-2].imaginary_radius + 1.0e-15
    )
    even_resolved = (
        finest.even_remainder_abs <= finest.even_remainder_noise + 1.0e-15
    )
    if root_limited and (even_resolved or even_order_ok):
        return _LadderVerdict(
            "converged",
            convergence_basis="TRUNCATION_BELOW_ROOT_RESOLUTION",
            **estimates,
        )
    if real_order_ok and imaginary_order_ok and even_order_ok:
        return _LadderVerdict(
            "converged", convergence_basis="ORDER_RESOLVED", **estimates
        )
    return _LadderVerdict("continue", **estimates)


def _resolved_level_runs(
    job: ResponseComponentJob, levels: Sequence[LadderLevel]
) -> list[list[LadderLevel]]:
    """Split the ladder into maximal runs of signal-resolved levels."""

    factor = job.policy.signal_to_root_factor
    runs: list[list[LadderLevel]] = []
    current: list[LadderLevel] = []
    for level in levels:
        if level.signal_resolved(factor):
            current.append(level)
            continue
        if current:
            runs.append(current)
        current = []
    if current:
        runs.append(current)
    return runs


def _recover_resolved_window(
    job: ResponseComponentJob, levels: Sequence[LadderLevel]
) -> tuple[list[LadderLevel], _LadderVerdict] | None:
    """Fall back to the finest resolved window that still converges.

    The ladder walks from coarse to fine, so a collapsing physical response
    crosses the root noise floor at the fine end while the coarse levels stay
    resolved.  Discarding the whole component there throws away evidence it has
    already paid for.  Widening epsilon is also the cheaper recovery than
    promoting arithmetic precision, so windows shrink from the fine end first
    and precision promotion is left to the signed roots that remain root
    limited.
    """

    ordered = tuple(sorted(levels, key=lambda level: level.epsilon, reverse=True))
    candidates: list[tuple[list[LadderLevel], _LadderVerdict]] = []
    for raw_window in consecutive_windows(
        ordered, LADDER_WINDOW_MINIMUM_LEVELS
    ):
        window = list(raw_window)
        if not all(
            level.signal_resolved(job.policy.signal_to_root_factor)
            for level in window
        ):
            continue
        verdict = _evaluate_ladder_window(job, window)
        if verdict.outcome == "converged":
            candidates.append((window, verdict))
    if not candidates:
        return None
    # Finest admissible window first; equal fine endpoints prefer the shorter
    # certificate and then the coarser start. Every window reached the existing
    # signal, branch, axis, order, even-remainder, and diagnostic gates above.
    return min(
        candidates,
        key=lambda item: (
            item[0][-1].epsilon,
            len(item[0]),
            -item[0][0].epsilon,
        ),
    )


def _resolved_window_record(
    job: ResponseComponentJob,
    levels: Sequence[LadderLevel],
    window: Sequence[LadderLevel],
    policy: str = RESOLVED_WINDOW_RECOVERY_POLICY,
) -> dict[str, object]:
    included = {level.epsilon for level in window}
    recovery = _response_ladder_recovery(job, levels)
    runtime_epsilons = tuple(level.epsilon for level in window)
    if (
        recovery.disposition is not RecoveryDisposition.RECOVERED
        or recovery.selected_epsilons != runtime_epsilons
    ):
        raise RuntimeError(
            "serialized ladder recovery disagrees with the runtime window"
        )
    record = _response_ladder_recovery_record(job, levels, recovery)
    return {
        **record,
        "policy": policy,
        "included_epsilons": [level.epsilon for level in window],
        "excluded_epsilons": [
            level.epsilon for level in levels if level.epsilon not in included
        ],
        "exclusion_reason": RESOLVED_WINDOW_EXCLUSION_REASON,
    }


def _recovery_precision_tier(readout: RootReadout) -> PrecisionTier:
    receipt = readout.worker_response_receipt
    request = None if receipt is None else receipt.get("request_binding")
    if isinstance(request, Mapping):
        raw = request.get("semantic_precision_tier")
        if isinstance(raw, str):
            return precision_tier(raw)
    return PrecisionTier.BINARY64


def _runtime_ladder_window_evidence(
    job: ResponseComponentJob,
    window: Sequence[RecoveryLadderLevel],
    policy: RecoveryLadderPolicy,
    original_by_epsilon: Mapping[float, LadderLevel],
) -> WindowEvidence:
    """Serialize the exact gate decision used by ``_evaluate_ladder_window``."""

    originals = tuple(original_by_epsilon[level.epsilon] for level in window)
    level_evidence: list[WindowLevelEvidence] = []
    for level in window:
        real_ratio, imaginary_ratio = level.signal_ratios(
            policy.signal_factor
        )
        level_evidence.append(WindowLevelEvidence(
            epsilon=level.epsilon,
            real_signal_ratio=real_ratio,
            imaginary_signal_ratio=imaginary_ratio,
            signal_ok=real_ratio > 1.0 and imaginary_ratio > 1.0,
        ))
    epsilons = tuple(level.epsilon for level in originals)
    real_values = tuple(level.real_secant for level in originals)
    imaginary_values = tuple(level.imaginary_secant for level in originals)
    real_orders = _observed_orders(epsilons, real_values)
    imaginary_orders = _observed_orders(epsilons, imaginary_values)
    even_orders = _positive_orders(
        epsilons,
        tuple(level.even_remainder_abs for level in originals),
    )
    minimum_order = policy.required_order - policy.order_tolerance
    real_order = None if not real_orders else real_orders[-1]
    imaginary_order = None if not imaginary_orders else imaginary_orders[-1]
    real_order_ok = real_order is not None and real_order >= minimum_order
    imaginary_order_ok = (
        imaginary_order is not None and imaginary_order >= minimum_order
    )
    even_order_ok = (
        not even_orders
        or even_orders[-1]
        >= policy.required_order - job.policy.even_order_tolerance
    )
    finest = originals[-1]
    root_limited = (
        abs(real_values[-1] - real_values[-2])
        <= originals[-1].real_radius + originals[-2].real_radius + 1.0e-15
        and abs(imaginary_values[-1] - imaginary_values[-2])
        <= (
            originals[-1].imaginary_radius
            + originals[-2].imaginary_radius
            + 1.0e-15
        )
    )
    even_resolved = (
        finest.even_remainder_abs
        <= finest.even_remainder_noise + 1.0e-15
    )
    even_remainder_ok = even_resolved or even_order_ok
    real_estimate = _axis_estimate(originals, "real")
    imaginary_estimate = _axis_estimate(originals, "imaginary")
    axis_allowance = job.policy.axis_tolerance_factor * max(
        real_estimate.root_radius
        + imaginary_estimate.root_radius
        + real_estimate.amplitude_radius
        + imaginary_estimate.amplitude_radius,
        job.policy.absolute_axis_floor,
    )
    axis_ok = (
        abs(real_estimate.center - imaginary_estimate.center)
        <= axis_allowance
    )
    branch_ok = all(
        readout.branch_ok for level in window for readout in level.readouts
    )
    diagnostic_ok = all(
        readout.diagnostic_ok
        for level in window
        for readout in level.readouts
    )
    signal_ok = all(item.signal_ok for item in level_evidence)
    verdict = _evaluate_ladder_window(job, originals)
    converged = verdict.outcome == "converged"
    reasons: list[str] = []

    def add(reason: str) -> None:
        if reason not in reasons:
            reasons.append(reason)

    if not signal_ok:
        add("SIGNAL_GATE")
    if not axis_ok:
        add("AXIS_GATE")
    if not branch_ok:
        add("BRANCH_GATE")
    if not diagnostic_ok:
        add("DIAGNOSTIC_GATE")
    if not converged:
        if not root_limited and not (real_order_ok and imaginary_order_ok):
            add("ORDER_GATE")
        if not even_remainder_ok:
            add("EVEN_REMAINDER_GATE")
        if not reasons:
            add("RUNTIME_WINDOW_GATE")
    return WindowEvidence(
        epsilons=epsilons,
        levels=tuple(level_evidence),
        real_order=real_order,
        imaginary_order=imaginary_order,
        real_order_ok=real_order_ok,
        imaginary_order_ok=imaginary_order_ok,
        axis_ok=axis_ok,
        even_remainder_ok=even_remainder_ok,
        branch_ok=branch_ok,
        diagnostic_ok=diagnostic_ok,
        reasons=tuple(reasons),
    )


def _response_ladder_recovery(
    job: ResponseComponentJob,
    levels: Sequence[LadderLevel],
) -> LadderRecoveryResult:
    converted = tuple(
        RecoveryLadderLevel.from_signed_readouts(
            epsilon=level.epsilon,
            real_plus=RecoveryLadderReadout(
                level.real_plus.omega,
                level.real_plus.newton_correction_estimate,
                _identity_status(job, level.real_plus) is None,
                level.real_plus.converged,
                _recovery_precision_tier(level.real_plus),
            ),
            real_minus=RecoveryLadderReadout(
                level.real_minus.omega,
                level.real_minus.newton_correction_estimate,
                _identity_status(job, level.real_minus) is None,
                level.real_minus.converged,
                _recovery_precision_tier(level.real_minus),
            ),
            imaginary_plus=RecoveryLadderReadout(
                level.imaginary_plus.omega,
                level.imaginary_plus.newton_correction_estimate,
                _identity_status(job, level.imaginary_plus) is None,
                level.imaginary_plus.converged,
                _recovery_precision_tier(level.imaginary_plus),
            ),
            imaginary_minus=RecoveryLadderReadout(
                level.imaginary_minus.omega,
                level.imaginary_minus.newton_correction_estimate,
                _identity_status(job, level.imaginary_minus) is None,
                level.imaginary_minus.converged,
                _recovery_precision_tier(level.imaginary_minus),
            ),
        )
        for level in levels
    )
    original_by_epsilon = {level.epsilon: level for level in levels}
    return recover_response_ladder(
        converted,
        policy=RecoveryLadderPolicy(
            signal_factor=job.policy.signal_to_root_factor,
            minimum_window=LADDER_WINDOW_MINIMUM_LEVELS,
            maximum_epsilon=0.032 if job.mode.ell == 4 else 0.016,
            required_order=2.0,
            order_tolerance=job.policy.order_tolerance,
            axis_tolerance_factor=job.policy.axis_tolerance_factor,
            even_remainder_factor=job.policy.even_order_tolerance,
        ),
        window_assessor=lambda window, policy: (
            _runtime_ladder_window_evidence(
                job, window, policy, original_by_epsilon
            )
        ),
    )


def _response_ladder_recovery_record(
    job: ResponseComponentJob,
    levels: Sequence[LadderLevel],
    recovery: LadderRecoveryResult,
) -> dict[str, object]:
    candidate_windows = [
        {
            "epsilons": list(window.epsilons),
            "signal_noise_ratios": [
                {
                    "epsilon": item.epsilon,
                    "real": item.real_signal_ratio,
                    "imaginary": item.imaginary_signal_ratio,
                    "signal_ok": item.signal_ok,
                }
                for item in window.levels
            ],
            "real_order": window.real_order,
            "imaginary_order": window.imaginary_order,
            "real_order_ok": window.real_order_ok,
            "imaginary_order_ok": window.imaginary_order_ok,
            "axis_ok": window.axis_ok,
            "even_remainder_ok": window.even_remainder_ok,
            "branch_ok": window.branch_ok,
            "diagnostic_ok": window.diagnostic_ok,
            "reasons": list(window.reasons),
        }
        for window in recovery.candidate_windows
    ]
    branch_radius = mode_specific_branch_enclosure_radius(job.root)
    branch_margins = []
    for level in levels:
        for role, readout in (
            ("real_plus", level.real_plus),
            ("real_minus", level.real_minus),
            ("imaginary_plus", level.imaginary_plus),
            ("imaginary_minus", level.imaginary_minus),
        ):
            branch_margins.append({
                "epsilon": level.epsilon,
                "readout_role": role,
                "margin_abs": branch_radius - abs(readout.omega - job.root.omega),
            })
    promotion_plan = [
        {"epsilon": epsilon, "readout_role": role}
        for epsilon, role in recovery.readouts_to_promote
    ]
    return {
        "recovery_disposition": recovery.disposition.value,
        "candidate_windows": candidate_windows,
        "signal_noise_ratios": [
            item for window in candidate_windows
            for item in window["signal_noise_ratios"]
        ],
        "selected_window": (
            None
            if recovery.selected_window is None
            else list(recovery.selected_window.epsilons)
        ),
        "excluded_fine_levels": [
            {"epsilon": item.epsilon, "reasons": list(item.reasons)}
            for item in recovery.excluded_fine_levels
        ],
        "window_diagnostics": candidate_windows,
        "branch_margins": branch_margins,
        "exact_added_epsilons": sorted(
            level.epsilon
            for level in levels
            if level.epsilon not in job.policy.epsilons
        ),
        "amplitudes_to_add": list(recovery.amplitudes_to_add),
        "readout_specific_promotion_plan": promotion_plan,
        "next_precision_tier": (
            None
            if recovery.next_precision_tier is None
            else recovery.next_precision_tier.value
        ),
        "promoted_readout_count_by_tier": (
            {}
            if recovery.next_precision_tier is None
            else {recovery.next_precision_tier.value: len(promotion_plan)}
        ),
    }


def _expansion_epsilons(job: ResponseComponentJob) -> tuple[float, ...]:
    """Amplitudes coarser than any the policy declares, coarsest last."""

    coarsest = job.policy.epsilons[0]
    maximum = 0.032 if job.mode.ell == 4 else 0.016
    return tuple(
        coarsest * (AMPLITUDE_EXPANSION_GROWTH ** (index + 1))
        for index in range(AMPLITUDE_EXPANSION_MAXIMUM_LEVELS)
        if coarsest * (AMPLITUDE_EXPANSION_GROWTH ** (index + 1))
        <= maximum * (1.0 + 1.0e-12)
    )


def _expand_amplitude_ladder(
    job: ResponseComponentJob,
    levels: Sequence[LadderLevel],
    build_level: Callable[[float], LadderLevel],
    record_rays: Callable[[LadderLevel], None],
) -> tuple[list[LadderLevel], list[LadderLevel], _LadderVerdict] | None:
    """Widen the amplitude until the signed displacements clear root noise.

    A response that has physically collapsed leaves a signal proportional to
    epsilon sitting under a root error that does not shrink with it, so every
    level the policy declares can be noise while the same component at a wider
    amplitude is perfectly resolvable.  The ladder cannot reach there on its
    own because it only ever walks finer.
    """

    if not levels:
        return None
    runs = _resolved_level_runs(job, levels)
    retained = list(runs[0]) if runs else []
    # The predictors finished on the fine end of the ladder; re-seed them from
    # the coarsest level actually read, which is the nearest evidence to where
    # the expansion is going.
    record_rays(levels[0])
    factor = job.policy.signal_to_root_factor
    expansion: list[LadderLevel] = []
    for epsilon in _expansion_epsilons(job):
        level = build_level(epsilon)
        for readout in (
            level.real_plus,
            level.real_minus,
            level.imaginary_plus,
            level.imaginary_minus,
        ):
            if _identity_status(job, readout) is not None:
                return None
        record_rays(level)
        expansion.append(level)
        if not level.signal_resolved(factor):
            continue
        window = sorted(
            [item for item in expansion if item.signal_resolved(factor)]
            + retained,
            key=lambda item: item.epsilon,
            reverse=True,
        )
        verdict = _evaluate_ladder_window(job, window)
        if verdict.outcome == "converged":
            combined = sorted(
                list(levels) + expansion,
                key=lambda item: item.epsilon,
                reverse=True,
            )
            return combined, window, verdict
    if isinstance(levels, list):
        levels.extend(expansion)
        levels.sort(key=lambda item: item.epsilon, reverse=True)
    return None


def run_component(
    job: ResponseComponentJob,
    backend: RootReadoutBackend,
    response_predictor: complex | None = None,
    *,
    _promoted_validation_policy: Mapping[str, str] | None = None,
) -> ComponentResult:
    """Run one job through same-equation zero and complex signed amplitudes."""

    if getattr(backend, "promoted_precision_backend", False):
        if (
            _promoted_validation_policy is None
            or dict(_promoted_validation_policy)
            != full_ladder_validation_policy(
                _promoted_validation_policy.get("reason", "")
            )
        ):
            raise ValueError(
                "promoted backend requires explicit full-ladder validation"
            )
    elif _promoted_validation_policy is not None:
        raise ValueError("full-ladder validation token requires promoted backend")
    if backend.identity != job.backend_identity:
        raise ValueError("response backend identity does not match job")
    if response_predictor is not None:
        response_predictor = complex(response_predictor)
        if not (
            math.isfinite(response_predictor.real)
            and math.isfinite(response_predictor.imag)
        ):
            raise ValueError("response predictor must be finite")
    binder = getattr(backend, "bind_job", None)
    if binder is not None:
        job = binder(job)
    journaled_reads = _generic_component_journal(job, backend)
    readout_index = 0

    def read_root(
        role: str,
        amplitude: complex,
        epsilon: float | None,
        primary_predictor: complex | None = None,
        primary_predictor_kind: str | None = None,
    ) -> RootReadout:
        nonlocal readout_index
        readout_index += 1
        converted = complex(amplitude)
        amplitude_mapping = {
            "real": converted.real,
            "imaginary": converted.imag,
        }
        with progress_scope(
            readout_index=readout_index,
            readout_role=role,
            epsilon=epsilon,
            amplitude=amplitude_mapping,
        ):
            started = time.monotonic()
            emit_progress(ProgressEventKind.AMPLITUDE_READOUT_STARTED)
            if journaled_reads is not None:
                result = journaled_reads.read_root(
                    job,
                    role,
                    converted,
                    primary_predictor,
                    primary_predictor_kind,
                )
            else:
                read_with_kind = getattr(
                    backend, "read_root_with_predictor_kind", None
                )
                if (
                    primary_predictor is not None
                    and primary_predictor_kind is not None
                    and callable(read_with_kind)
                ):
                    result = read_with_kind(
                        job,
                        converted,
                        primary_predictor,
                        primary_predictor_kind,
                    )
                else:
                    result = backend.read_root(
                        job,
                        converted,
                        primary_predictor=primary_predictor,
                    )
            emit_progress(
                ProgressEventKind.AMPLITUDE_READOUT_COMPLETED,
                current_omega={
                    "real": result.omega.real,
                    "imaginary": result.omega.imag,
                },
                determinant_abs=result.determinant_residual_abs,
                derivative_abs=result.determinant_derivative_abs,
                converged=result.converged,
                elapsed_seconds=time.monotonic() - started,
            )
            return result

    baseline = read_root("baseline", 0.0j, None)
    initial_status = _identity_status(job, baseline)
    if initial_status is not None:
        return _validated_result(
            backend, job, _unresolved_result(job, initial_status, baseline, ())
        )

    levels: list[LadderLevel] = []
    window: list[LadderLevel] = []
    resolved_window: dict[str, object] | None = None
    pending_status: ComponentStatus | None = None
    convergence_basis = "UNRESOLVED"
    real_estimate: _AxisEstimate | None = None
    imaginary_estimate: _AxisEstimate | None = None
    combined_estimate: _AxisEstimate | None = None
    ray_states: dict[str, tuple[float, RootReadout]] = {}

    def ray_predictor(
        ray: str, amplitude: complex, epsilon: float
    ) -> tuple[complex | None, str | None]:
        previous = ray_states.get(ray)
        if previous is None:
            if response_predictor is None:
                return None, None
            return (
                job.root.omega + amplitude * response_predictor,
                "SPIN_CONTINUATION",
            )
        previous_epsilon, previous_root = previous
        return (
            job.root.omega + (epsilon / previous_epsilon) * (
                previous_root.omega - job.root.omega
            ),
            "EPSILON_CONTINUATION",
        )

    def build_level(epsilon: float) -> LadderLevel:
        return LadderLevel(
            epsilon=epsilon,
            real_plus=read_root(
                "real-plus",
                complex(epsilon, 0.0),
                epsilon,
                *ray_predictor("real-plus", complex(epsilon, 0.0), epsilon),
            ),
            real_minus=read_root(
                "real-minus",
                complex(-epsilon, 0.0),
                epsilon,
                *ray_predictor("real-minus", complex(-epsilon, 0.0), epsilon),
            ),
            imaginary_plus=read_root(
                "imaginary-plus",
                complex(0.0, epsilon),
                epsilon,
                *ray_predictor(
                    "imaginary-plus", complex(0.0, epsilon), epsilon
                ),
            ),
            imaginary_minus=read_root(
                "imaginary-minus",
                complex(0.0, -epsilon),
                epsilon,
                *ray_predictor(
                    "imaginary-minus", complex(0.0, -epsilon), epsilon
                ),
            ),
        )

    def record_rays(level: LadderLevel) -> None:
        ray_states.update({
            "real-plus": (level.epsilon, level.real_plus),
            "real-minus": (level.epsilon, level.real_minus),
            "imaginary-plus": (level.epsilon, level.imaginary_plus),
            "imaginary-minus": (level.epsilon, level.imaginary_minus),
        })

    for epsilon in job.policy.epsilons:
        level = build_level(epsilon)
        levels.append(level)
        for readout in (
            level.real_plus,
            level.real_minus,
            level.imaginary_plus,
            level.imaginary_minus,
        ):
            status = _identity_status(job, readout)
            if status is not None:
                return _validated_result(
                    backend,
                    job,
                    _unresolved_result(job, status, baseline, levels),
                )
        record_rays(level)
        verdict = _evaluate_ladder_window(job, levels)
        if verdict.outcome == "continue":
            continue
        if verdict.outcome == "unresolved":
            assert verdict.status is not None
            if verdict.status is not ComponentStatus.NOISE_FLOOR:
                preliminary_recovery = _response_ladder_recovery(job, levels)
                if preliminary_recovery.disposition not in {
                    RecoveryDisposition.EXPAND_AMPLITUDE,
                    RecoveryDisposition.PROMOTE_READOUTS,
                }:
                    return _validated_result(
                        backend,
                        job,
                        _unresolved_result(job, verdict.status, baseline, levels),
                    )
                pending_status = verdict.status
                break
            recovery = _recover_resolved_window(job, levels)
            if recovery is None:
                pending_status = ComponentStatus.NOISE_FLOOR
                break
            window, verdict = recovery
            resolved_window = _resolved_window_record(job, levels, window)
        else:
            window = list(levels)
        real_estimate = verdict.real_estimate
        imaginary_estimate = verdict.imaginary_estimate
        combined_estimate = verdict.combined_estimate
        assert verdict.convergence_basis is not None
        convergence_basis = verdict.convergence_basis
        break
    else:
        pending_status = ComponentStatus.NOT_CONVERGED

    if pending_status is not None:
        # The ladder only ever walks finer, so once it is exhausted or has sunk
        # into the root noise there is no coarser evidence left inside it to
        # fall back on. Widening the amplitude is the move that recovers a
        # physically collapsed response, and it is cheaper than promoting the
        # arithmetic tier, so it is tried first and precision promotion is left
        # to the signed roots that stay root limited afterwards.
        expansion = _expand_amplitude_ladder(
            job, levels, build_level, record_rays
        )
        if expansion is None:
            recovery = _response_ladder_recovery(job, levels)
            recovery_record = _response_ladder_recovery_record(
                job, levels, recovery
            )
            unresolved = _unresolved_result(
                job, pending_status, baseline, levels
            )
            return _validated_result(
                backend,
                job,
                replace(unresolved, resolved_window=recovery_record),
            )
        levels, window, verdict = expansion
        resolved_window = _resolved_window_record(
            job, levels, window, AMPLITUDE_EXPANSION_RECOVERY_POLICY
        )
        real_estimate = verdict.real_estimate
        imaginary_estimate = verdict.imaginary_estimate
        combined_estimate = verdict.combined_estimate
        assert verdict.convergence_basis is not None
        convergence_basis = verdict.convergence_basis

    if real_estimate is None or imaginary_estimate is None or combined_estimate is None:
        return _validated_result(
            backend,
            job,
            _unresolved_result(
                job, ComponentStatus.NOT_CONVERGED, baseline, levels
            ),
        )
    signed_center = 0.5 * (real_estimate.center + imaginary_estimate.center)
    closed_form = backend.closed_form_horizon_response(job)
    response = signed_center if closed_form is None else closed_form
    axis_radius = abs(real_estimate.center - imaginary_estimate.center)
    amplitude_radius = max(
        real_estimate.amplitude_radius,
        imaginary_estimate.amplitude_radius,
        combined_estimate.amplitude_radius,
        0.0 if closed_form is None else abs(closed_form - signed_center),
    )
    raw = (baseline, *(item for level in window for item in (
        level.real_plus,
        level.real_minus,
        level.imaginary_plus,
        level.imaginary_minus,
    )))
    signed_readouts = tuple(
        item
        for level in levels
        for item in (
            level.real_plus,
            level.real_minus,
            level.imaginary_plus,
            level.imaginary_minus,
        )
    )
    live_diagnostics = all(item.diagnostic_readouts for item in signed_readouts)
    if not live_diagnostics and any(item.diagnostic_readouts for item in signed_readouts):
        raise ValueError("signed diagnostic root evidence is incomplete")
    if live_diagnostics:
        family_sets = tuple(
            frozenset(item.diagnostic_readouts) for item in signed_readouts
        )
        allowed_family_sets = {
            frozenset(_DIAGNOSTIC_ROOT_FAMILIES),
            frozenset(_PROMOTED_FIXED_ROOT_DIAGNOSTIC_FAMILIES),
        }
        if (
            any(families not in allowed_family_sets for families in family_sets)
            or (
                len(set(family_sets)) > 1
                and not getattr(
                    backend, "selective_readout_promotion_backend", False
                )
            )
        ):
            raise ValueError("signed diagnostic root families are inconsistent")
        diagnostic_families = tuple(
            family for family in _DIAGNOSTIC_ROOT_FAMILIES
            if all(family in families for families in family_sets)
        )
        diagnostic_channels = {
            family: _diagnostic_response_channel(
                window,
                family,
                primary_center=combined_estimate.center,
                primary_radius=combined_estimate.root_radius,
            )
            for family in diagnostic_families
        }
        if "seed-path" not in diagnostic_channels:
            diagnostic_channels["seed-path"] = 0.0
    else:
        diagnostic_channels = {
            "truncation": max(item.truncation_radius for item in raw),
            "resolution": max(item.resolution_radius for item in raw),
            "seed-path": max(item.seed_path_radius for item in raw),
        }
    channels = {
        "signed-root": combined_estimate.root_radius,
        **diagnostic_channels,
        "axis": axis_radius,
        "amplitude": amplitude_radius,
    }
    return _validated_result(
        backend,
        job,
        ComponentResult(
            job_id=job.job_id,
            leaf_id=job.leaf_id,
            mechanism_id=job.mechanism_id,
            status=ComponentStatus.CONVERGED,
            convergence_basis=convergence_basis,
            response=response,
            signed_root_crosscheck=signed_center,
            closed_form_response=closed_form,
            error_channels=channels,
            baseline=baseline,
            levels=tuple(levels),
            lineage=_result_lineage(job),
            resolved_window=resolved_window,
        ),
    )


class _SelectiveReadoutPromotionBackend:
    """Replay retained roots and execute only explicitly promoted readouts."""

    selective_readout_promotion_backend = True

    def __init__(
        self,
        previous: ComponentResult,
        promoted_backend: RootReadoutBackend,
        planned: frozenset[complex],
    ) -> None:
        self.identity = promoted_backend.identity
        self._promoted_backend = promoted_backend
        self._planned = planned
        self._executed: set[complex] = set()
        retained: dict[complex, RootReadout] = {0.0j: previous.baseline}
        for level in previous.levels:
            retained.update({
                complex(level.epsilon, 0.0): level.real_plus,
                complex(-level.epsilon, 0.0): level.real_minus,
                complex(0.0, level.epsilon): level.imaginary_plus,
                complex(0.0, -level.epsilon): level.imaginary_minus,
            })
        self._retained = retained
        self._promotion_predictors = {
            value: readout.omega for value, readout in retained.items()
        }
        self.executed_precision_tier = precision_tier(
            f"bigfloat-{getattr(promoted_backend, 'digits')}"
        )
        self.journal_component_identity = (
            "selective-signed-root-promotion-component/v1/"
            f"{self.executed_precision_tier.value}"
        )

    @staticmethod
    def _role(value: complex) -> str:
        if value.real > 0.0:
            return "real-plus"
        if value.real < 0.0:
            return "real-minus"
        if value.imag > 0.0:
            return "imaginary-plus"
        if value.imag < 0.0:
            return "imaginary-minus"
        return "baseline"

    def execute_all(
        self,
        job: ResponseComponentJob,
        journaled: _JournaledComponentReads | None = None,
    ) -> None:
        for value in sorted(
            self._planned, key=lambda item: (-abs(item), item.real, item.imag)
        ):
            retained = self._retained.get(value)
            if retained is None:
                raise ValueError("selective promotion requested an unknown retained readout")
            if journaled is None:
                output = self.read_root(job, value)
            else:
                output = journaled.read_root(
                    job,
                    self._role(value),
                    value,
                    retained.omega,
                    None,
                )
            self._retained[value] = output
            self._executed.add(value)

    def read_root(self, job, amplitude, primary_predictor=None) -> RootReadout:
        value = complex(amplitude)
        retained = self._retained.get(value)
        if retained is None:
            raise ValueError("selective promotion requested an unplanned amplitude")
        if value not in self._planned or value in self._executed:
            return retained
        return self._promoted_backend.read_root(
            job, value, primary_predictor=retained.omega
        )

    def read_root_with_predictor_kind(
        self, job, amplitude, primary_predictor, primary_predictor_kind
    ) -> RootReadout:
        return self.read_root(job, amplitude)

    def preview_root_request(
        self, job, amplitude, primary_predictor=None,
        primary_predictor_kind=None, readout_role=None,
    ) -> dict[str, object]:
        value = complex(amplitude)
        retained = self._retained.get(value)
        if value in self._planned and retained is not None:
            preview = getattr(self._promoted_backend, "preview_root_request", None)
            if callable(preview):
                return preview(
                    job,
                    value,
                    self._promotion_predictors[value],
                    None,
                    readout_role,
                )
        return {
            "schema": "windows-solver.retained-root-readout-request/1",
            "job": job.to_mapping(),
            "backend_identity_sha256": self.identity.identity_sha256,
            "policy_sha256": job.policy.identity_sha256,
            "readout_role": readout_role,
            "amplitude": _complex_mapping(value),
            "retained_root": None if retained is None else retained.to_mapping(),
        }

    def precision_tier_for_request(self, role, amplitude) -> PrecisionTier:
        return (
            self.executed_precision_tier
            if complex(amplitude) in self._planned
            else PrecisionTier.BINARY64
        )

    def closed_form_horizon_response(self, job) -> complex | None:
        return None


def run_selective_readout_promotion(
    job: ResponseComponentJob,
    previous: ComponentResult,
    promoted_backend: RootReadoutBackend,
    response_predictor: complex | None = None,
) -> ComponentResult:
    """Promote only recovery-plan roots, retaining all other ladder evidence."""

    recovery = previous.resolved_window
    if not isinstance(recovery, Mapping):
        raise ValueError("selective promotion requires resolved-window evidence")
    plan = recovery.get("readout_specific_promotion_plan")
    next_tier = recovery.get("next_precision_tier")
    if not isinstance(plan, list) or not plan or not isinstance(next_tier, str):
        raise ValueError("selective promotion plan is invalid")
    expected_tier = precision_tier(next_tier)
    actual_tier = precision_tier(f"bigfloat-{getattr(promoted_backend, 'digits')}")
    if actual_tier is not expected_tier:
        raise ValueError("selective promotion precision tier is invalid")
    role_to_amplitude = {
        "real_plus": lambda epsilon: complex(epsilon, 0.0),
        "real_minus": lambda epsilon: complex(-epsilon, 0.0),
        "imaginary_plus": lambda epsilon: complex(0.0, epsilon),
        "imaginary_minus": lambda epsilon: complex(0.0, -epsilon),
    }
    amplitudes: set[complex] = set()
    for item in plan:
        if not isinstance(item, Mapping) or set(item) != {"epsilon", "readout_role"}:
            raise ValueError("selective promotion work item is invalid")
        role = item["readout_role"]
        if role not in role_to_amplitude:
            raise ValueError("selective promotion readout role is invalid")
        amplitudes.add(role_to_amplitude[role](float(item["epsilon"])))
    selective = _SelectiveReadoutPromotionBackend(
        previous, promoted_backend, frozenset(amplitudes)
    )
    journaled = _generic_component_journal(job, selective)
    selective._component_journal = journaled
    selective.execute_all(job, journaled)
    result = run_component(job, selective, response_predictor)
    terminal_levels = {level.epsilon: level for level in result.levels}
    for prior_level in previous.levels:
        if prior_level.epsilon in terminal_levels:
            continue
        epsilon = prior_level.epsilon
        terminal_levels[epsilon] = LadderLevel(
            epsilon=epsilon,
            real_plus=selective.read_root(job, complex(epsilon, 0.0)),
            real_minus=selective.read_root(job, complex(-epsilon, 0.0)),
            imaginary_plus=selective.read_root(job, complex(0.0, epsilon)),
            imaginary_minus=selective.read_root(job, complex(0.0, -epsilon)),
        )
    if len(terminal_levels) != len(result.levels):
        result = replace(
            result,
            levels=tuple(sorted(
                terminal_levels.values(),
                key=lambda level: level.epsilon,
                reverse=True,
            )),
        )
    scientific_runtime_provider = getattr(
        promoted_backend, "scientific_runtime_for", None
    )
    scientific_runtime = (
        scientific_runtime_provider(job)
        if callable(scientific_runtime_provider)
        else None
    )
    journal_evidence: dict[str, object] = {
        "schema": "windows-solver.selective-tier-journal-evidence/1",
        "configured": journaled is not None,
        "component_identity": selective.journal_component_identity,
        "precision_tier": actual_tier.value,
    }
    if journaled is not None:
        promoted_work_unit_ids = tuple(
            unit.work_unit_id
            for (_, amplitude), unit in journaled.units.items()
            if amplitude in amplitudes
        )
        promoted_entries = {
            work_unit_id: journaled.journal.entries[work_unit_id]
            for work_unit_id in promoted_work_unit_ids
        }
        journal_mapping = PartialComponentJournal(
            journaled.journal.path,
            promoted_work_unit_ids,
            promoted_entries,
        ).to_mapping()
        ode_error_budgets = []
        for work_unit_id in promoted_work_unit_ids:
            entry = journaled.journal.entries.get(work_unit_id)
            wrapper = None if entry is None else entry.worker_response_receipt
            output = None if wrapper is None else wrapper.get("output")
            root_receipt = (
                output.get("worker_response_receipt")
                if isinstance(output, Mapping)
                else None
            )
            request = (
                root_receipt.get("request_binding")
                if isinstance(root_receipt, Mapping)
                else None
            )
            policy = request.get("policy") if isinstance(request, Mapping) else None
            budget = (
                policy.get("ode_error_budget")
                if isinstance(policy, Mapping)
                else None
            )
            if isinstance(budget, Mapping):
                ode_error_budgets.append(_journal_json_value(budget))
        ode_error_budget = (
            ode_error_budgets[0]
            if ode_error_budgets
            and all(item == ode_error_budgets[0] for item in ode_error_budgets)
            else None
        )
        journal_evidence.update({
            "journal": journal_mapping,
            "journal_sha256": journal_mapping["journal_sha256"],
            "promoted_work_unit_ids": list(promoted_work_unit_ids),
            "scientific_runtime": scientific_runtime,
            "scientific_runtime_sha256": (
                None
                if not isinstance(scientific_runtime, Mapping)
                else _sha256(dict(scientific_runtime))
            ),
            "ode_error_budget": ode_error_budget,
            "ode_error_budget_sha256": (
                None if ode_error_budget is None else _sha256(ode_error_budget)
            ),
        })
    result_window = dict(result.resolved_window or {})
    terminal_recovery = _response_ladder_recovery(job, result.levels)
    result_window.update(
        _response_ladder_recovery_record(job, result.levels, terminal_recovery)
    )
    previous_window = dict(previous.resolved_window or {})
    promoted_counts = dict(
        previous_window.get("promoted_readout_count_by_tier", {})
    )
    promoted_counts[actual_tier.value] = len(amplitudes)
    retained_counts = {
        PrecisionTier.BINARY64.value: 1 + 4 * len(previous.levels)
    }
    retained_counts.update({
        tier: count
        for tier, count in promoted_counts.items()
        if tier != actual_tier.value
    })
    prior_evidence = list(
        previous_window.get("prior_tier_recovery_evidence", [])
    )
    if previous_window.get("executed_precision_tier") is not None:
        prior_evidence.append({
            "executed_precision_tier": previous_window["executed_precision_tier"],
            "executed_readout_specific_promotion_plan": [
                dict(item) for item in previous_window.get(
                    "executed_readout_specific_promotion_plan", []
                )
            ],
            "promoted_readout_count_by_tier": dict(
                previous_window.get("promoted_readout_count_by_tier", {})
            ),
            "journal_evidence": dict(
                previous_window.get("journal_evidence", {})
            ),
            "status": previous.status.value,
        })
    result_window.update({
        "selective_promotion_policy": "readout-specific-semantic-tier/v1",
        "executed_precision_tier": actual_tier.value,
        "executed_readout_specific_promotion_plan": [dict(item) for item in plan],
        "promoted_readout_count_by_tier": promoted_counts,
        "retained_readout_count_by_tier": retained_counts,
        "prior_tier_recovery_evidence": prior_evidence,
        "journal_evidence": journal_evidence,
    })
    if result.status is not ComponentStatus.CONVERGED:
        result_window["next_precision_tier"] = {
            PrecisionTier.BIGFLOAT_40: PrecisionTier.BIGFLOAT_80.value,
            PrecisionTier.BIGFLOAT_80: PrecisionTier.BIGFLOAT_120.value,
            PrecisionTier.BIGFLOAT_120: None,
        }[actual_tier]
        if not result_window.get("readout_specific_promotion_plan"):
            result_window["readout_specific_promotion_plan"] = [
                dict(item) for item in plan
            ]
    return replace(result, resolved_window=result_window)


def _runtime_fingerprint() -> str:
    return (
        f"cpython-{platform.python_version()}-"
        f"{platform.system().lower()}-{platform.machine().lower()}"
    )


def _engine_source_sha256() -> str:
    return canonical_text_sha256(Path(__file__).read_bytes())


@dataclass(frozen=True, slots=True)
class ResponsePlan:
    jobs: tuple[ResponseComponentJob, ...]
    policy: NumericalPolicy
    backend_identity: BackendIdentity

    @property
    def plan_id(self) -> str:
        return f"response-plan-{_sha256([job.job_id for job in self.jobs])}"

    @property
    def bindings(self) -> dict[str, object]:
        return {
            "plan_id": self.plan_id,
            "job_set_sha256": _sha256([job.to_mapping() for job in self.jobs]),
            "engine_source_sha256": _engine_source_sha256(),
            "backend_identity_sha256": self.backend_identity.identity_sha256,
            "policy_sha256": self.policy.identity_sha256,
            "roots_sha256": _sha256([job.root.to_mapping() for job in self.jobs]),
            "runtime_fingerprint": _runtime_fingerprint(),
        }

    def to_mapping(self) -> dict[str, object]:
        return {
            "schema_version": ENGINE_SCHEMA_VERSION,
            "plan_id": self.plan_id,
            "backend_identity": self.backend_identity.to_mapping(),
            "policy": self.policy.to_mapping(),
            "jobs": [job.to_mapping() for job in self.jobs],
            "bindings": self.bindings,
        }


def build_response_plan(
    leaf_ids: Sequence[str],
    *,
    policy: NumericalPolicy,
    backend_identity: BackendIdentity,
    job_binder: Callable[[ResponseComponentJob], ResponseComponentJob] | None = None,
) -> ResponsePlan:
    requested = tuple(leaf_ids)
    if not requested or len(requested) != len(set(requested)):
        raise ValueError("selected response leaf IDs must be nonempty and unique")
    requested_set = set(requested)
    ordered = [
        leaf.leaf_id
        for leaf in B_PRIME_RELEASE_DOMAIN.production_leaves
        if leaf.leaf_id in requested_set
    ]
    if set(ordered) != requested_set:
        raise ValueError("selected response leaf ID is outside frozen B-prime")
    jobs = tuple(
        ResponseComponentJob.from_leaf_id(
            leaf_id, policy=policy, backend_identity=backend_identity
        )
        for leaf_id in ordered
    )
    if job_binder is not None:
        jobs = tuple(job_binder(job) for job in jobs)
    return ResponsePlan(jobs=jobs, policy=policy, backend_identity=backend_identity)


@dataclass(frozen=True, slots=True)
class SelectedRunSummary:
    plan_id: str
    state: str
    executed_count: int
    reused_count: int
    results: tuple[ComponentResult, ...]
    checkpoint_path: str

    def to_mapping(self) -> dict[str, object]:
        return {
            "plan_id": self.plan_id,
            "state": self.state,
            "executed_count": self.executed_count,
            "reused_count": self.reused_count,
            "result_count": len(self.results),
            "results": [result.to_mapping() for result in self.results],
            "checkpoint_path": self.checkpoint_path,
            "release_admissible": False,
        }


def _atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
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


def _checkpoint_mapping(
    plan: ResponsePlan, results: Sequence[ComponentResult]
) -> dict[str, object]:
    records = [result.to_mapping() for result in results]
    return {
        "schema_version": ENGINE_SCHEMA_VERSION,
        "state": "COMPLETE" if len(results) == len(plan.jobs) else "PARTIAL",
        "bindings": plan.bindings,
        "results": records,
        "results_sha256": _sha256(records),
    }


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate checkpoint JSON key: {key}")
        result[key] = value
    return result


def _load_checkpoint(
    plan: ResponsePlan, path: Path
) -> tuple[ComponentResult, ...]:
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=lambda item: (_ for _ in ()).throw(
                ValueError(f"checkpoint contains non-finite constant {item}")
            ),
        )
    except json.JSONDecodeError as error:
        raise ValueError("checkpoint is not valid JSON") from error
    if not isinstance(value, Mapping) or set(value) != {
        "schema_version",
        "state",
        "bindings",
        "results",
        "results_sha256",
    }:
        raise ValueError("checkpoint envelope fields are invalid")
    if value["schema_version"] != ENGINE_SCHEMA_VERSION:
        raise ValueError("checkpoint schema version is invalid")
    if value["bindings"] != plan.bindings:
        raise ValueError("checkpoint bindings are stale or forged")
    records = value["results"]
    if not isinstance(records, list) or _sha256(records) != value["results_sha256"]:
        raise ValueError("checkpoint results digest is invalid")
    results = tuple(ComponentResult.from_mapping(item) for item in records)
    if len(results) > len(plan.jobs):
        raise ValueError("checkpoint has excess component results")
    for job, result in zip(plan.jobs, results):
        if result.job_id != job.job_id or result.leaf_id != job.leaf_id:
            raise ValueError("checkpoint result order or identity is invalid")
        expected_lineage = _result_lineage(job)
        if result.lineage != expected_lineage or any(
            readout.source_root_mapping != job.source_root_mapping
            for readout in result.raw_readouts
        ):
            raise ValueError("checkpoint source root mapping or lineage is invalid")
        mapping = job.source_root_mapping
        installed_identity_matches = mapping is None or (
            mapping["installed_root_reference_id"] == job.root.root_reference_id
            and mapping["installed_root_identity_sha256"] == job.root.identity_sha256
            and mapping["installed_branch_id"] == job.root.branch_id
        )
        if not installed_identity_matches or any(
            readout.root_reference_id != job.root.root_reference_id
            or readout.branch_id != job.root.branch_id
            or readout.equation_id != job.equation_id
            for readout in result.raw_readouts
        ):
            raise ValueError("checkpoint raw readout installed identity is invalid")
        if mapping is not None and result.baseline.omega != _complex_from_mapping(
            mapping["source_omega"], "checkpoint source root mapping omega"
        ):
            raise ValueError("checkpoint raw readout baseline omega is invalid")
    expected_state = "COMPLETE" if len(results) == len(plan.jobs) else "PARTIAL"
    if value["state"] != expected_state:
        raise ValueError("checkpoint state does not match result completeness")
    return results


def run_response_plan(
    plan: ResponsePlan,
    backend: RootReadoutBackend,
    checkpoint_path: str | os.PathLike[str] | Path,
    *,
    resume: bool,
) -> SelectedRunSummary:
    path = Path(checkpoint_path)
    if backend.identity != plan.backend_identity:
        raise ValueError("selected response backend identity does not match plan")
    if path.exists():
        if not resume:
            raise ValueError("cold selected response run refuses an existing checkpoint")
        existing = list(_load_checkpoint(plan, path))
    else:
        if resume:
            raise ValueError("resume requires an existing response checkpoint")
        existing = []
        _atomic_json(path, _checkpoint_mapping(plan, existing))
    reused = len(existing)
    for job in plan.jobs[reused:]:
        result = run_component(job, backend)
        existing.append(result)
        _atomic_json(path, _checkpoint_mapping(plan, existing))
    return SelectedRunSummary(
        plan_id=plan.plan_id,
        state="COMPLETE",
        executed_count=len(existing) - reused,
        reused_count=reused,
        results=tuple(existing),
        checkpoint_path=str(path),
    )


def validate_response_checkpoint(
    plan: ResponsePlan,
    checkpoint_path: str | os.PathLike[str] | Path,
) -> SelectedRunSummary:
    path = Path(checkpoint_path)
    results = _load_checkpoint(plan, path)
    return SelectedRunSummary(
        plan_id=plan.plan_id,
        state="COMPLETE" if len(results) == len(plan.jobs) else "PARTIAL",
        executed_count=0,
        reused_count=len(results),
        results=results,
        checkpoint_path=str(path),
    )


RECORDED_REPLAY_BACKEND_ID = "recorded-response-risk-replay"
_PINNED_SOURCE_COMMIT = "0c1e8a3d3bca6e608c34e111476a4f6dcb73e86e"
_REPLAY_RESOURCES: Mapping[str, tuple[str, str]] = {
    "baselines": (
        "baselines.fixture",
        "b23966dca92d3ef4ecea9123e0ddef9eb70ee92ccd45acd8e0eab18f7924f5be",
    ),
    "components": (
        "components.fixture",
        "372f37cd8e69ab38fec577a4453a10c9a7972b52551d4f0acf96a85f3206bb19",
    ),
    "levels": (
        "levels.fixture",
        "cef7635465a6ad91ed37be52099308db2099779e1b87b916e8e491ee94201ab9",
    ),
    "protocol": (
        "protocol.fixture",
        "25172794cd1b16e6589690a29fc3809453cf3a58d0f252dd5055906666708c99",
    ),
    "reduction": (
        "reduction.fixture",
        "5a9e658948100436de9e514615a9d68d86b7961ce27f31f981aec965deb9e780",
    ),
    "repeats": (
        "repeats.fixture",
        "21e3910b4caa4c3c50df4e5cb7f1bce29712907b794b77081bcffe578d6193bd",
    ),
    "signed-roots": (
        "signed-roots.fixture",
        "60ac24ef74010ad3b07acdc5d730872bce527e55d08e92b10b1bd8dbd826362e",
    ),
    "summary": (
        "summary.fixture",
        "60d88305ce85e4182e69dda8f83b23f0be3a61d2773020d170f3ab15b3a08ba8",
    ),
}


@dataclass(frozen=True, slots=True)
class RecordedSmokeCase:
    leaf_id: str
    component_id: str


RECORDED_SMOKE_CASES = (
    RecordedSmokeCase(
        "b-prime-leaf-9e5777728144433e089f9559b92b6e139e16115a5a53099f40403a45297aa3c3",
        "a0.95-s-2-l2-m2-n0-unclassified-gravitational-horizon_admittance",
    ),
    RecordedSmokeCase(
        "b-prime-leaf-7ef38d6f95c161d0b4c6650d470898c0742ad6ae8440e89956312344c0db6aac",
        "a0.95-s-2-l3-m3-n0-unclassified-gravitational-fixed_r3",
    ),
    RecordedSmokeCase(
        "b-prime-leaf-7f12759244119c8e819ef09cc5f3ec2e76054d77b6a1e0b12e3bb742397b635e",
        "a0.95-s-2-l4-m4-n0-unclassified-gravitational-light_ring",
    ),
    RecordedSmokeCase(
        "b-prime-leaf-4c8594e4a59486a1c56206e41cd7f7f3ff1ab5193a5ff6b699cbe9492bc45355",
        "a0.999-s-2-l2-m2-n0-unclassified-gravitational-horizon_admittance",
    ),
    RecordedSmokeCase(
        "b-prime-leaf-e0a48b72b4071c5c88c66955420dc2748cfeeac577b8fd1c399f171f5fa08475",
        "a0.999-s-2-l4-m4-n0-unclassified-gravitational-light_ring",
    ),
)
_RECORDED_CASE_BY_LEAF = {case.leaf_id: case for case in RECORDED_SMOKE_CASES}


def _fixture_rows(data: bytes, subject: str) -> list[dict[str, str]]:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValueError(f"recorded {subject} is not UTF-8") from error
    rows = list(csv.DictReader(io.StringIO(text, newline="")))
    if not rows:
        raise ValueError(f"recorded {subject} is empty")
    return rows


class RecordedReplayBackend:
    """Byte-authenticated root-readout replay; never a scientific producer."""

    identity = BackendIdentity(
        backend_id=RECORDED_REPLAY_BACKEND_ID,
        implementation_version="1",
        source_commit=_PINNED_SOURCE_COMMIT,
        source_blobs=(
            ("determinant-backend", "b65f2236f828204aa21dfa8d9bc79c8a1c66ca3b"),
            ("local-response", "341ce9db7dda8108a96e3f7536380b9b45bd6c3b"),
            ("refinement", "69733ac4d0a74696445ff683aaaaeb5fd64e44c1"),
        ),
        runtime_fingerprint="recorded-replay-no-solver",
    )

    def __init__(
        self,
        *,
        bundle_sha256s: Mapping[str, str],
        baselines: Mapping[str, Mapping[str, str]],
        components: Mapping[str, Mapping[str, str]],
        signed_roots: Mapping[tuple[str, str, str], Mapping[str, str]],
        channel_radii: Mapping[str, Mapping[str, float]],
        level_counts: Mapping[str, int],
    ) -> None:
        self.bundle_sha256s = dict(bundle_sha256s)
        self._baselines = dict(baselines)
        self._components = dict(components)
        self._signed_roots = dict(signed_roots)
        self._channel_radii = {
            component_id: dict(channels)
            for component_id, channels in channel_radii.items()
        }
        self._level_counts = dict(level_counts)

    @classmethod
    def load(cls) -> "RecordedReplayBackend":
        directory = resources.files("windows_solver").joinpath(
            "data", "response_replay"
        )
        files: dict[str, bytes] = {}
        hashes: dict[str, str] = {}
        for label, (filename, expected_sha256) in _REPLAY_RESOURCES.items():
            data = directory.joinpath(filename).read_bytes()
            actual = hashlib.sha256(data).hexdigest()
            if actual != expected_sha256:
                raise ValueError(f"recorded replay {label} SHA-256 mismatch")
            files[label] = data
            hashes[label] = actual
        baselines = {
            row["component_id"]: row
            for row in _fixture_rows(files["baselines"], "baselines")
        }
        components = {
            row["component_id"]: row
            for row in _fixture_rows(files["components"], "components")
        }
        levels_by_component: dict[str, set[str]] = {}
        for row in _fixture_rows(files["levels"], "levels"):
            levels_by_component.setdefault(row["component_id"], set()).add(
                float(row["epsilon"]).hex()
            )
        repeat_channels: dict[str, dict[str, list[float]]] = {}
        repeat_labels = {
            "truncation": "truncation",
            "resolution": "resolution",
            "root": "seed-path",
        }
        for row in _fixture_rows(files["repeats"], "repeats"):
            try:
                channel = repeat_labels[row["error_channel"]]
            except KeyError as error:
                raise ValueError("recorded repeat error channel is invalid") from error
            contribution = float(row["channel_radius_contribution_abs"])
            if not math.isfinite(contribution) or contribution < 0.0:
                raise ValueError("recorded repeat channel radius is invalid")
            repeat_channels.setdefault(row["component_id"], {}).setdefault(
                channel, []
            ).append(contribution)
        signed: dict[tuple[str, str, str], Mapping[str, str]] = {}
        for row in _fixture_rows(files["signed-roots"], "signed roots"):
            key = (
                row["component_id"],
                float(row["amplitude_re"]).hex(),
                float(row["amplitude_im"]).hex(),
            )
            if key in signed:
                raise ValueError("recorded signed roots contain duplicate amplitudes")
            signed[key] = row
        expected_ids = {case.component_id for case in RECORDED_SMOKE_CASES}
        if not expected_ids <= set(baselines) or not expected_ids <= set(components):
            raise ValueError("recorded smoke components are incomplete")
        channel_radii: dict[str, dict[str, float]] = {}
        level_counts: dict[str, int] = {}
        for component_id in expected_ids:
            component = components[component_id]
            try:
                level_count = int(component["ladder_level_count"])
            except ValueError as error:
                raise ValueError("recorded component ladder count is invalid") from error
            actual_level_count = len(levels_by_component.get(component_id, ()))
            if actual_level_count != level_count:
                raise ValueError("recorded component and level counts disagree")
            level_counts[component_id] = level_count
            if component["status"] == ComponentStatus.CONVERGED.value:
                channels = repeat_channels.get(component_id, {})
                if set(channels) != {"truncation", "resolution", "seed-path"}:
                    raise ValueError("recorded converged component error channels are incomplete")
                channel_radii[component_id] = {
                    name: max(values) for name, values in channels.items()
                }
            else:
                channel_radii[component_id] = {
                    name: max(repeat_channels.get(component_id, {}).get(name, (0.0,)))
                    for name in ("truncation", "resolution", "seed-path")
                }
        return cls(
            bundle_sha256s=hashes,
            baselines=baselines,
            components=components,
            signed_roots=signed,
            channel_radii=channel_radii,
            level_counts=level_counts,
        )

    def _case(self, job: ResponseComponentJob) -> RecordedSmokeCase:
        if job.backend_identity != self.identity:
            raise ValueError("recorded replay backend identity does not match job")
        case = _RECORDED_CASE_BY_LEAF.get(job.leaf_id)
        if case is None:
            raise ValueError("selected leaf has no authenticated recorded replay")
        baseline = self._baselines[case.component_id]
        component = self._components[case.component_id]
        expected_mechanism = {
            "horizon-admittance": "horizon_admittance",
            "exterior-fixed-r3": "fixed_r3",
            "exterior-light-ring": "light_ring",
        }[job.mechanism_id]
        expected_mode_label = (
            f"s{job.mode.s}-l{job.mode.ell}-m{job.mode.m}-n{job.mode.n}-"
            f"unclassified-{job.mode.polarization}"
        )
        for row in (baseline, component):
            if (
                int(row["s"]) != job.mode.s
                or int(row["ell"]) != job.mode.ell
                or int(row["m"]) != job.mode.m
                or int(row["n"]) != job.mode.n
                or float(row["spin"]).hex() != job.spin.hex()
                or row["mechanism_id"] != expected_mechanism
                or row["mode_label"] != expected_mode_label
                or row["branch"] != "unclassified"
                or row["polarization"] != job.mode.polarization
            ):
                raise ValueError("recorded replay mode/spin/mechanism identity mismatch")
        recorded_root = complex(
            float(baseline["omega_re"]), float(baseline["omega_im"])
        )
        if abs(recorded_root - job.root.omega) > 5.0e-9:
            raise ValueError("recorded replay baseline does not correspond to bound root")
        return case

    def source_root_mapping(
        self, job: ResponseComponentJob
    ) -> dict[str, object]:
        """Authenticate the recorded source root and its installed-root mapping."""

        case = self._case(job)
        baseline = self._baselines[case.component_id]
        source_omega = complex(
            float(baseline["omega_re"]), float(baseline["omega_im"])
        )
        source_identity = {
            "source_bundle_baselines_sha256": self.bundle_sha256s["baselines"],
            "component_id": case.component_id,
            "mode": job.mode.to_mapping(),
            "spin_binary64_hex": job.spin.hex(),
            "mechanism_id": baseline["mechanism_id"],
            "branch_id": baseline["branch"],
            "polarization": baseline["polarization"],
            "omega": _complex_mapping(source_omega),
        }
        source_identity_sha256 = _sha256(source_identity)
        receipt: dict[str, object] = {
            "schema_version": 1,
            "mapping_protocol": (
                "authenticated-recorded-source-to-installed-spectral-root"
            ),
            "source_bundle_baselines_sha256": self.bundle_sha256s["baselines"],
            "source_root_reference_id": (
                f"recorded-source-root-{source_identity_sha256}"
            ),
            "source_root_identity_sha256": source_identity_sha256,
            "source_branch_id": baseline["branch"],
            "source_omega": _complex_mapping(source_omega),
            "installed_root_reference_id": job.root.root_reference_id,
            "installed_root_identity_sha256": job.root.identity_sha256,
            "installed_branch_id": job.root.branch_id,
            "installed_omega": _complex_mapping(job.root.omega),
            "mapping_tolerance_abs": _RECORDED_ROOT_MAPPING_TOLERANCE_ABS,
            "measured_delta_abs": abs(source_omega - job.root.omega),
        }
        receipt["mapping_receipt_sha256"] = _sha256(receipt)
        return _validated_source_root_mapping(receipt)  # type: ignore[return-value]

    def bind_job(self, job: ResponseComponentJob) -> ResponseComponentJob:
        receipt = self.source_root_mapping(job)
        if job.source_root_mapping is not None:
            if job.source_root_mapping != receipt:
                raise ValueError("recorded replay source root mapping is invalid")
            return job
        return replace(job, source_root_mapping=receipt)

    def read_root(
        self,
        job: ResponseComponentJob,
        amplitude: complex,
        primary_predictor: complex | None = None,
    ) -> RootReadout:
        case = self._case(job)
        expected_mapping = self.source_root_mapping(job)
        if job.source_root_mapping != expected_mapping:
            raise ValueError("recorded replay source root mapping is missing or invalid")
        value = _finite_complex(amplitude, "recorded replay amplitude")
        if value == 0.0j:
            row = self._baselines[case.component_id]
        else:
            row = self._signed_roots.get(
                (case.component_id, value.real.hex(), value.imag.hex())
            )
            if row is None:
                raise ValueError("recorded replay has no exact signed amplitude")
        channels = self._channel_radii[case.component_id]
        return RootReadout(
            omega=complex(float(row["omega_re"]), float(row["omega_im"])),
            determinant_residual_abs=float(row["determinant_residual_abs"]),
            determinant_derivative_abs=float(row["determinant_derivative_abs"]),
            converged=row["converged"] == "True",
            root_reference_id=job.root.root_reference_id,
            branch_id=job.root.branch_id,
            equation_id=job.equation_id,
            truncation_radius=channels["truncation"],
            resolution_radius=channels["resolution"],
            seed_path_radius=channels["seed-path"],
            source_root_mapping=expected_mapping,
        )

    def closed_form_horizon_response(
        self, job: ResponseComponentJob
    ) -> complex | None:
        self._case(job)
        return None

    def recorded_component(self, component_id: str) -> Mapping[str, str]:
        try:
            return dict(self._components[component_id])
        except KeyError as error:
            raise ValueError("unknown recorded component_id") from error

    def validate_reconstructed_result(
        self, job: ResponseComponentJob, result: ComponentResult
    ) -> None:
        job = self.bind_job(job)
        case = self._case(job)
        recorded = self._components[case.component_id]
        if (
            result.job_id != job.job_id
            or result.leaf_id != job.leaf_id
            or result.mechanism_id != job.mechanism_id
            or result.status.value != recorded["status"]
            or result.convergence_basis != recorded["convergence_basis"]
            or len(result.levels) != self._level_counts[case.component_id]
            or result.lineage != _result_lineage(job)
            or any(
                readout.source_root_mapping != job.source_root_mapping
                for readout in result.raw_readouts
            )
        ):
            raise ValueError("reconstructed replay component identity/outcome mismatch")
        if result.status is not ComponentStatus.CONVERGED:
            if result.response is not None or recorded["response_available"] != "False":
                raise ValueError("unresolved replay component fabricated a response")
            return
        if result.response is None or recorded["response_available"] != "True":
            raise ValueError("converged replay component is missing its response")

        def close(actual: float, expected: str) -> bool:
            return math.isclose(actual, float(expected), rel_tol=5.0e-13, abs_tol=5.0e-15)

        channels = result.error_channels
        complete_matches = (
            close(result.response.real, recorded["response_re"])
            and close(result.response.imag, recorded["response_im"])
            and close(channels["axis"], recorded["axis_radius_abs"])
            and close(channels["truncation"], recorded["truncation_radius_abs"])
            and close(channels["resolution"], recorded["resolution_radius_abs"])
            and close(
                channels["signed-root"] + channels["seed-path"],
                recorded["root_radius_abs"],
            )
            and close(
                channels["amplitude"] + channels["axis"],
                recorded["amplitude_radius_abs"],
            )
            and close(
                channels["signed-root"]
                + channels["seed-path"]
                + channels["truncation"]
                + channels["resolution"]
                + channels["amplitude"]
                + channels["axis"],
                recorded["uncertainty_radius_abs"],
            )
        )
        if not complete_matches:
            raise ValueError("reconstructed replay component disagrees with recorded evidence")


from .native_response_kernel import (  # noqa: E402 - types above form the boundary
    NativeResourceUnavailableError,
    VettedNativeDeterminantKernel,
)
