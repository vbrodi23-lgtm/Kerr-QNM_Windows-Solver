Warning: truncated output (original token count: 116785)
Total output lines: 11524

"""Selected linear-response execution behind the unavailable provider.

The engine owns identities, same-equation signed-amplitude refinement, and
authenticated resumability.  Numerical determinant evaluation is injected at
one typed boundary; importing this module cannot start a numerical solve.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal, InvalidOperation, ROUND_FLOOR, localcontext
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
from .promoted_control_calibration import (
    DEFAULT_CALIBRATION_RECEIPT_SHA256,
    EXTERIOR_DETERMINANT_ABSOLUTE_ERROR_CERTIFICATE,
    EXTERIOR_DETERMINANT_CERTIFICATE_UNAVAILABLE,
    load_default_calibration_receipt,
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
EXTERIOR_SUPPORT_POLICY_ID = "adaptive-exterior-gap-standoff/v2"
BINARY64_FIXED_ROOT_SURVEY_IDENTITY = "exterior-fixed-root-survey-raw/v1"
CANONICAL_EXTERIOR_BACKGROUND_IDENTITY = (
    "canonical-exterior-background-wronskian/v1"
)
BACKGROUND_EQUIVALENCE_IDENTITY = "background-equivalence/v1"
_BACKGROUND_REUSE_KEY_SCHEMA = "windows-solver.exterior-background-reuse-key/1"
_BACKGROUND_EQUIVALENCE_SCHEMA = "windows-solver.background-equivalence/1"
_FREQUENCY_STEP_POLICY = "relative-1e-5-times-one-plus-abs-omega/v1"
_BINARY64_FREQUENCY_STEP_SCALE = 1.0e-5
_MATCH_READOUT_CONVENTION = "real-axis-wronskian-at-readout/v1"
BINARY64_FIXED_ROOT_SAMPLE_ROLES = (
    "D0",
    "DOMEGA_REAL_PLUS_H",
    "DOMEGA_REAL_MINUS_H",
    "DOMEGA_REAL_PLUS_HALF_H",
    "DOMEGA_REAL_MINUS_HALF_H",
    "DC_PLUS_EPSILON",
    "DC_MINUS_EPSILON",
    "DC_PLUS_HALF_EPSILON",
    "DC_MINUS_HALF_EPSILON",
)
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
PROMOTED_HORIZON_COMPONENT_V3_IDENTITY = (
    "root-sealed-horizon-fixed-frequency-derivative-component/v3"
)
PROMOTED_HORIZON_RESPONSE_METHOD_V3 = (
    "bounded-analytic-horizon-from-sealed-frequency-derivative/v3"
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
FIXED_ROOT_FREQUENCY_DERIVATIVE_METHOD = (
    "fixed-root-frequency-h-h2-stencil/v1"
)
PROMOTED_ROOT_SEAL_SCHEMA = "windows-solver.promoted-root-seal/1"
PROMOTED_ROOT_SEAL_IDENTITY = "authenticated-promoted-root-seal/v1"
ROOT_SEALED_RESPONSE_REPAIR_IDENTITY = (
    "root-sealed-fixed-root-response-repair/v1"
)
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
# Version 10 separates one logical authenticated fixed-root determinant from
# the raw determinant evaluations required to construct its certificate.
# Error responses remain independently versioned at 1.
WORKER_RESPONSE_WIRE_SCHEMA = 10
HISTORICAL_WORKER_RESPONSE_WIRE_SCHEMAS = frozenset({3, 4, 5, 6, 7, 8, 9})
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
_HORIZON_ENDPOINT_ORDER_LIMITED = "insufficient-series-order/v1"
_HORIZON_ENDPOINT_PRECISION_LIMITED = "insufficient-arithmetic-precision/v1"
_HORIZON_ENDPOINT_GEOMETRY_LIMITED = "insufficient-geometric-depth/v1"


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
    def endpoint_order_ladder(
        candidate_base_order: int,
    ) -> list[int]:
        values: list[int] = []
        order = candidate_base_order
        while order < maximum_order:
            values.append(order)
            order += order
        values.append(maximum_order)
        return values

    allowed_base_orders = {base_order}
    if (
        not allow_historical_schema7_policy
        and request_binding.get("operation") == "root-readout"
        and policy.get("promoted_root_readout_policy")
        == PROMOTED_ROOT_READOUT_POLICY
        and base_order + 8 <= maximum_order
    ):
        # Schema v9 accumulates PRIMARY, TRUNCATION, and RESOLUTION
        # endpoint searches in one response. TRUNCATION alone raises
        # the endpoint base order by exactly eight.
        allowed_base_orders.add(base_order + 8)
    expected_order_ladders = {
        tuple(endpoint_order_ladder(candidate_base_order))
        for candidate_base_order in sorted(allowed_base_orders)
    }
    expected_orders: list[int] = []
    observed_order_ladders: set[tuple[int, ...]] = set()

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
            not isinstance(orders, list)
            or not orders
            or any(
                isinstance(order, bool)
                or not isinstance(order, int)
                or order < 1
                for order in orders
            )
        ):
            raise ValueError("horizon endpoint search evidence is invalid")
        order_ladder = tuple(orders)
        if (
            order_ladder not in expected_order_ladders
            or item["outcome"] != expected_outcome
            or item["policy_identity"] != policy_identity
            or not isinstance(selected_pair, list)
            or len(selected_pair) != required_selected_count
            or not isinstance(rejected, list)
            or item["homogeneous_rhs_evaluations_before_pair"] != 0
        ):
            raise ValueError("horizon endpoint search evidence is invalid")
        expected_orders = list(order_ladder)
        observed_order_ladders.add(order_ladder)
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
    primary_order_ladder = tuple(
        endpoint_order_ladder(base_order)
    )
    if primary_order_ladder not in observed_order_ladders:
        raise ValueError("horizon endpoint PRIMARY evidence is missing")
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
        # Receipt schema 3 predates wire 10.  Sealed wire-9 checkpoints stay
        # readable, while new live responses must satisfy the wire-10 parser.
        {9, WORKER_RESPONSE_WIRE_SCHEMA}
        if current
        else (
            {8}
            if previous
            else HISTORICAL_WORKER_RESPONSE_WIRE_SCHEMAS - {8, 9}
        )
    )
    if type(wire_schema) is not int or wire_schema not in allowed_wire_schemas:
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
        if wire_schema == WORKER_RESPONSE_WIRE_SCHEMA:
            _current_authenticated_determinant_raw_count(request_binding)
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


def _current_authenticated_determinant_raw_count(
    request_binding: Mapping[str, object],
) -> int:
    """Return the raw count bound to one current authenticated determinant.

    Wire 10 records the implementation work behind one logical determinant.
    Its count is a mechanism contract, not something an absent optional policy
    field may silently downgrade.  Validate the determinant-family join before
    interpreting the count so resealed hybrid requests fail closed.
    """

    mechanism_id = request_binding.get("mechanism_id")
    policy = request_binding.get("policy")
    if not isinstance(policy, Mapping):
        raise ValueError(
            "worker response receipt determinant policy is invalid"
        )
    try:
        mechanism_contract = regularised_gsn_mechanism_contract(
            mechanism_id
        )
    except (TypeError, ValueError) as error:
        raise ValueError(
            "worker response receipt determinant policy is invalid"
        ) from error
    if any(
        policy.get(field) != expected
        for field, expected in mechanism_contract.items()
    ):
        raise ValueError(
            "worker response receipt determinant policy is invalid"
        )
    if mechanism_id == "horizon-admittance":
        expected_error_model = VERIFIED_ENDPOINT_ERROR_MODEL
        raw_count = 1
    elif mechanism_id in _EXTERIOR_PROFILE_IDS:
        expected_error_model = (
            EXTERIOR_DETERMINANT_ABSOLUTE_ERROR_CERTIFICATE
        )
        raw_count = 3
    else:  # guarded by regularised_gsn_mechanism_contract; kept fail-closed.
        raise ValueError(
            "worker response receipt determinant policy is invalid"
        )
    if policy.get("determinant_error_model") != expected_error_model:
        raise ValueError(
            "worker response receipt determinant certificate policy is invalid"
        )
    if raw_count == 3:
        digits = request_binding.get("precision_digits")
        preceding_tier = {
            40: "binary64",
            80: "bigfloat-40",
            120: "bigfloat-80",
        }.get(digits) if type(digits) is int else None
        required_terms = policy.get(
            "determinant_error_required_term_classes"
        )
        if (
            type(required_terms) is not list
            or required_terms != [
                "delta_same_point",
                "delta_cross_precision",
                "delta_endpoint_series",
            ]
            or policy.get("determinant_error_missing_evidence_outcome")
            != EXTERIOR_DETERMINANT_CERTIFICATE_UNAVAILABLE
            or policy.get("determinant_error_certificate_statement")
            != (
                "conservative empirical certificate; not a formal interval "
                "enclosure"
            )
            or policy.get("determinant_error_preceding_precision_tier")
            != preceding_tier
            or type(policy.get("determinant_error_safety_factor")) is not int
            or policy.get("determinant_error_safety_factor") != 64
            or policy.get("promoted_control_calibration_receipt_sha256")
            != DEFAULT_CALIBRATION_RECEIPT_SHA256
            or policy.get("empirical_control_profile_sha256")
            != _current_empirical_control_profile_sha256(
                "exterior-wronskian/v1", digits
            )
        ):
            raise ValueError(
                "worker response receipt determinant certificate policy is invalid"
            )
    return raw_count


@lru_cache(maxsize=None)
def _current_empirical_control_profile_sha256(
    determinant_family: str,
    digits: int,
) -> str:
    receipt = load_default_calibration_receipt()
    try:
        profile = receipt.budget_for(determinant_family, digits)
    except (KeyError, ValueError) as error:
        raise ValueError(
            "worker response receipt determinant certificate policy is invalid"
        ) from error
    return _sha256(profile.to_mapping())


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


@dataclass(frozen=True, slots=True)
class Binary64FixedRootSample:
    role: str
    omega: complex
    amplitude: complex
    determinant: complex

    def __post_init__(self) -> None:
        if self.role not in BINARY64_FIXED_ROOT_SAMPLE_ROLES:
            raise ValueError("binary64 fixed-root sample role is invalid")
        object.__setattr__(self, "omega", _finite_complex(self.omega, "sample omega"))
        object.__setattr__(
            self, "amplitude", _finite_complex(self.amplitude, "sample amplitude")
        )
        object.__setattr__(
            self,
            "determinant",
            _finite_complex(self.determinant, "sample determinant"),
        )

    def to_mapping(self) -> dict[str, object]:
        return {
            "role": self.role,
            "omega": _complex_mapping(self.omega),
            "amplitude": _complex_mapping(self.amplitude),
            "determinant": _complex_mapping(self.determinant),
        }


@dataclass(frozen=True, slots=True)
class Binary64FixedRootBatch:
    leaf_id: str
    job_id: str
    mechanism_id: str
    fixed_root: complex
    branch_identity: str
    frequency_step: float
    coordinate_step: float
    support: ExteriorSupport
    samples: tuple[Binary64FixedRootSample, ...]
    operation_identity: str = BINARY64_FIXED_ROOT_SURVEY_IDENTITY
    sample_limit: int = 9
    root_read_count: int = 0
    julia_launch_count: int = 0

    def __post_init__(self) -> None:
        if self.operation_identity != BINARY64_FIXED_ROOT_SURVEY_IDENTITY:
            raise ValueError("binary64 fixed-root operation identity is invalid")
        for name in ("leaf_id", "job_id", "mechanism_id", "branch_identity"):
            if not isinstance(getattr(self, name), str) or not getattr(self, name):
                raise ValueError(f"binary64 fixed-root {name} is invalid")
        object.__setattr__(
            self, "fixed_root", _finite_complex(self.fixed_root, "fixed root")
        )
        if self.mechanism_id not in _EXTERIOR_PROFILE_IDS:
            raise ValueError("binary64 fixed-root mechanism is not exterior")
        if not isinstance(self.support, ExteriorSupport):
            raise ValueError("binary64 fixed-root support is invalid")
        for name in ("frequency_step", "coordinate_step"):
            value = float(getattr(self, name))
            if not math.isfinite(value) or value <= 0.0:
                raise ValueError(f"binary64 fixed-root {name} is invalid")
            object.__setattr__(self, name, value)
        if (
            self.sample_limit != 9
            or self.root_read_count != 0
            or self.julia_launch_count != 0
        ):
            raise ValueError("binary64 fixed-root work budget is invalid")
        if self.sample_roles != BINARY64_FIXED_ROOT_SAMPLE_ROLES:
            raise ValueError("binary64 fixed-root sample plan is invalid")
        if len(self.samples) > self.sample_limit:
            raise ValueError("binary64 fixed-root sample budget exceeded")
        expected_points = (
            (self.fixed_root, 0.0j),
            (self.fixed_root + self.frequency_step, 0.0j),
            (self.fixed_root - self.frequency_step, 0.0j),
            (self.fixed_root + self.frequency_step / 2.0, 0.0j),
            (self.fixed_root - self.frequency_step / 2.0, 0.0j),
            (self.fixed_root, complex(self.coordinate_step, 0.0)),
            (self.fixed_root, complex(-self.coordinate_step, 0.0)),
            (self.fixed_root, complex(self.coordinate_step / 2.0, 0.0)),
            (self.fixed_root, complex(-self.coordinate_step / 2.0, 0.0)),
        )
        if any(
            sample.omega != omega or sample.amplitude != amplitude
            for sample, (omega, amplitude) in zip(self.samples, expected_points)
        ):
            raise ValueError("binary64 fixed-root sample point is invalid")

    @property
    def sample_roles(self) -> tuple[str, ...]:
        return tuple(sample.role for sample in self.samples)

    @property
    def sample_count(self) -> int:
        return len(self.samples)

    def to_mapping(self) -> dict[str, object]:
        return {
            "schema": "windows-solver.binary64-fixed-root-batch/1",
            "operation_identity": self.operation_identity,
            "leaf_id": self.leaf_id,
            "job_id": self.job_id,
            "mechanism_id": self.mechanism_id,
            "fixed_root": _complex_mapping(self.fixed_root),
            "branch_identity": self.branch_identity,
            "frequency_step": self.frequency_step,
            "coordinate_step": self.coordinate_step,
            "support": self.support.to_mapping(),
            "samples": [sample.to_mapping() for sample in self.samples],
            "sample_count": self.sample_count,
            "sample_limit": self.sample_limit,
            "root_read_count": self.root_read_count,
            "julia_launch_count": self.julia_launch_count,
        }


@dataclass(frozen=True, slots=True)
class ExteriorBackgroundReuseKey:
    root_seal_sha256: str
    root_identity: str
    branch_identity: str
    angular_identity: str
    background_operation_identity: str
    determinant_family: str
    determinant_convention: str
    determinant_normalisation: str
    match_readout_convention: str
    backend_identity: str
    numerical_controls_sha256: str
    arithmetic_tier: str
    working_precision: int
    frequency_step_policy: str

    def __post_init__(self) -> None:
        for name in (
            "root_seal_sha256",
            "root_identity",
            "angular_identity",
            "backend_identity",
            "numerical_controls_sha256",
        ):
            if _HEX_64.fullmatch(getattr(self, name)) is None:
                raise ValueError(f"exterior background {name} is invalid")
        for name in (
            "branch_identity",
            "determinant_family",
            "determinant_convention",
            "determinant_normalisation",
            "match_readout_convention",
            "frequency_step_policy",
        ):
            if not isinstance(getattr(self, name), str) or not getattr(self, name):
                raise ValueError(f"exterior background {name} is invalid")
        if self.background_operation_identity != CANONICAL_EXTERIOR_BACKGROUND_IDENTITY:
            raise ValueError("exterior background operation identity is invalid")
        if self.arithmetic_tier != "binary64" or self.working_precision != 53:
            raise ValueError("exterior background arithmetic contract is invalid")

    def to_mapping(self) -> dict[str, object]:
        return {
            "schema": _BACKGROUND_REUSE_KEY_SCHEMA,
            "root_seal_sha256": self.root_seal_sha256,
            "root_identity": self.root_identity,
            "branch_identity": self.branch_identity,
            "angular_identity": self.angular_identity,
            "background_operation_identity": self.background_operation_identity,
            "determinant_family": self.determinant_family,
            "determinant_convention": self.determinant_convention,
            "determinant_normalisation": self.determinant_normalisation,
            "match_readout_convention": self.match_readout_convention,
            "backend_identity": self.backend_identity,
            "numerical_controls_sha256": self.numerical_controls_sha256,
            "arithmetic_tier": self.arithmetic_tier,
            "working_precision": self.working_precision,
            "frequency_step_policy": self.frequency_step_policy,
        }

    @classmethod
    def from_mapping(cls, value: object) -> "ExteriorBackgroundReuseKey":
        expected = {
            "schema",
            "root_seal_sha256",
            "root_identity",
            "branch_identity",
            "angular_identity",
            "background_operation_identity",
            "determinant_family",
            "determinant_convention",
            "determinant_normalisation",
            "match_readout_convention",
            "backend_identity",
            "numerical_controls_sha256",
            "arithmetic_tier",
            "working_precision",
            "frequency_step_policy",
        }
        if not isinstance(value, Mapping) or set(value) != expected:
            raise ValueError("exterior background reuse key fields are invalid")
        if value["schema"] != _BACKGROUND_REUSE_KEY_SCHEMA:
            raise ValueError("exterior background reuse key schema is invalid")
        return cls(**{name: value[name] for name in expected - {"schema"}})


def build_exterior_background_reuse_key(
    job: ResponseComponentJob,
    *,
    root_seal_sha256: str,
    fixed_root: complex | None = None,
) -> ExteriorBackgroundReuseKey:
    if job.mechanism_id not in _EXTERIOR_PROFILE_IDS:
        raise ValueError("exterior background reuse requires an exterior job")
    contract = regularised_gsn_mechanism_contract(job.mechanism_id)
    root = job.root.omega if fixed_root is None else _finite_complex(
        fixed_root, "fixed root"
    )
    frequency_step = _BINARY64_FREQUENCY_STEP_SCALE * (1.0 + abs(root))
    return ExteriorBackgroundReuseKey(
        root_seal_sha256=root_seal_sha256,
        root_identity=job.root.identity_sha256,
        branch_identity=job.root.branch_id,
        angular_identity=_sha256({
            "angular_separation_constant": _complex_mapping(
                job.root.angular_separation_constant
            ),
            "angular_owner": job.root.owner_data_sha256,
        }),
        background_operation_identity=CANONICAL_EXTERIOR_BACKGROUND_IDENTITY,
        determinant_family=str(contract["determinant_family"]),
        determinant_convention=str(contract["determinant_convention"]),
        determinant_normalisation=str(contract["determinant_normalisation"]),
        match_readout_convention=_sha256({
            "identity": _MATCH_READOUT_CONVENTION,
            "readout_radius_binary64_hex": job.policy.readout_radius.hex(),
        }),
        backend_identity=job.backend_identity.identity_sha256,
        numerical_controls_sha256=job.policy.identity_sha256,
        arithmetic_tier="binary64",
        working_precision=53,
        frequency_step_policy=_sha256({
            "identity": _FREQUENCY_STEP_POLICY,
            "step_binary64_hex": frequency_step.hex(),
        }),
    )


_CANONICAL_BACKGROUND_SAMPLE_ROLES = BINARY64_FIXED_ROOT_SAMPLE_ROLES[:5]
_MECHANISM_DERIVATIVE_SAMPLE_ROLES = BINARY64_FIXED_ROOT_SAMPLE_ROLES[5:]


@dataclass(frozen=True, slots=True)
class CanonicalExteriorBackground:
    reuse_key: ExteriorBackgroundReuseKey
    fixed_root: complex
    frequency_step: float
    samples: tuple[Binary64FixedRootSample, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.reuse_key, ExteriorBackgroundReuseKey):
            raise ValueError("canonical exterior background reuse key is invalid")
        object.__setattr__(
            self, "fixed_root", _finite_complex(self.fixed_root, "fixed root")
        )
        if not math.isfinite(self.frequency_step) or self.frequency_step <= 0.0:
            raise ValueError("canonical exterior background step is invalid")
        if tuple(sample.role for sample in self.samples) != (
            _CANONICAL_BACKGROUND_SAMPLE_ROLES
        ):
            raise ValueError("canonical exterior background sample plan is invalid")
        expected_points = (
            self.fixed_root,
            self.fixed_root + self.frequency_step,
            self.fixed_root - self.frequency_step,
            self.fixed_root + self.frequency_step / 2.0,
            self.fixed_root - self.frequency_step / 2.0,
        )
        if any(
            sample.omega != omega or sample.amplitude != 0.0j
            for sample, omega in zip(self.samples, expected_points)
        ):
            raise ValueError("canonical exterior background sample point is invalid")

    @property
    def sha256(self) -> str:
        return _sha256(self.to_mapping())

    def to_mapping(self) -> dict[str, object]:
        return {
            "schema": "windows-solver.canonical-exterior-background/1",
            "operation_identity": CANONICAL_EXTERIOR_BACKGROUND_IDENTITY,
            "reuse_key": self.reuse_key.to_mapping(),
            "fixed_root": _complex_mapping(self.fixed_root),
            "frequency_step": self.frequency_step,
            "samples": [sample.to_mapping() for sample in self.samples],
        }


def canonical_background_from_binary64_batch(
    batch: Binary64FixedRootBatch,
    reuse_key: ExteriorBackgroundReuseKey,
) -> CanonicalExteriorBackground:
    if batch.branch_identity != reuse_key.branch_identity:
        raise ValueError("canonical exterior background branch identity mismatch")
    return CanonicalExteriorBackground(
        reuse_key=reuse_key,
        fixed_root=batch.fixed_root,
        frequency_step=batch.frequency_step,
        samples=batch.samples[:5],
    )


@dataclass(frozen=True, slots=True)
class BackgroundEquivalenceReceipt:
    mechanism_id: str
    reuse_key: ExteriorBackgroundReuseKey
    canonical_background_sha256: str
    proof: Mapping[str, object]
    identity: str = BACKGROUND_EQUIVALENCE_IDENTITY

    def __post_init__(self) -> None:
        if self.identity != BACKGROUND_EQUIVALENCE_IDENTITY:
            raise ValueError("background equivalence identity is invalid")
        if self.mechanism_id not in _EXTERIOR_PROFILE_IDS:
            raise ValueError("background equivalence mechanism is invalid")
        if not isinstance(self.reuse_key, ExteriorBackgroundReuseKey):
            raise ValueError("background equivalence reuse key is invalid")
        if _HEX_64.fullmatch(self.canonical_background_sha256) is None:
            raise ValueError("background equivalence background digest is invalid")
        if not isinstance(self.proof, Mapping):
            raise ValueError("background equivalence proof is invalid")
        proof_fields = {
            "proof_identity",
            "root_seal_sha256",
            "canonical_operation_identity",
            "mechanism_operation_identity",
            "realised_support",
            "determinant_contract",
            "zero_coupling_amplitude",
            "reuse_key_sha256",
        }
        if set(self.proof) != proof_fields:
            raise ValueError("background equivalence proof fields are invalid")
        expected_contract = {
            "determinant_family": self.reuse_key.determinant_family,
            "determinant_convention": self.reuse_key.determinant_convention,
            "determinant_normalisation": self.reuse_key.determinant_normalisation,
        }
        if (
            self.proof["proof_identity"] != "zero-coupling-profile-elision/v1"
            or self.proof["root_seal_sha256"] != self.reuse_key.root_seal_sha256
            or self.proof["canonical_operation_identity"]
            != CANONICAL_EXTERIOR_BACKGROUND_IDENTITY
            or self.proof["mechanism_operation_identity"]
            != BINARY64_FIXED_ROOT_SURVEY_IDENTITY
            or self.proof["determinant_contract"] != expected_contract
            or self.proof["zero_coupling_amplitude"] != _complex_mapping(0.0j)
            or self.proof["reuse_key_sha256"]
            != _sha256(self.reuse_key.to_mapping())
        ):
            raise ValueError("background equivalence proof is inconsistent")
        support = self.proof["realised_support"]
        if (
            not isinstance(support, Mapping)
            or set(support) != {"lower", "upper", "centre", "half_width"}
        ):
            raise ValueError("background equivalence support proof is invalid")

    def _material_mapping(self) -> dict[str, object]:
        return {
            "schema": _BACKGROUND_EQUIVALENCE_SCHEMA,
            "identity": self.identity,
            "mechanism_id": self.mechanism_id,
            "reuse_key": self.reuse_key.to_mapping(),
            "canonical_background_sha256": self.canonical_background_sha256,
            "proof": dict(self.proof),
        }

    @property
    def sha256(self) -> str:
        return _sha256(self._material_mapping())

    def to_mapping(self) -> dict[str, object]:
        return {**self._material_mapping(), "receipt_sha256": self.sha256}

    @classmethod
    def issue(
        cls,
        *,
        reuse_key: ExteriorBackgroundReuseKey,
        job: ResponseComponentJob,
        canonical_background_sha256: str,
        fixed_root: complex | None = None,
    ) -> "BackgroundEquivalenceReceipt":
        if job.mechanism_id not in _EXTERIOR_PROFILE_IDS:
            raise ValueError("background equivalence requires an exterior job")
        expected_key = build_exterior_background_reuse_key(
            job,
            root_seal_sha256=reuse_key.root_seal_sha256,
            fixed_root=fixed_root,
        )
        if reuse_key != expected_key:
            raise ValueError("background equivalence reuse key mismatch")
        contract = regularised_gsn_mechanism_contract(job.mechanism_id)
        proof = {
            "proof_identity": "zero-coupling-profile-elision/v1",
            "root_seal_sha256": reuse_key.root_seal_sha256,
            "canonical_operation_identity": (
                CANONICAL_EXTERIOR_BACKGROUND_IDENTITY
            ),
            "mechanism_operation_identity": BINARY64_FIXED_ROOT_SURVEY_IDENTITY,
            "realised_support": _exterior_support(
                job.spin, job.mechanism_id
            ).to_mapping(),
            "determinant_contract": {
                name: contract[name]
                for name in (
                    "determinant_family",
                    "determinant_convention",
                    "determinant_normalisation",
                )
            },
            "zero_coupling_amplitude": _complex_mapping(0.0j),
            "reuse_key_sha256": _sha256(reuse_key.to_mapping()),
        }
        return cls(
            mechanism_id=job.mechanism_id,
            reuse_key=reuse_key,
            canonical_background_sha256=canonical_background_sha256,
            proof=proof,
        )

    @classmethod
    def from_mapping(cls, value: object) -> "BackgroundEquivalenceReceipt":
        fields = {
            "schema",
            "identity",
            "mechanism_id",
            "reuse_key",
            "canonical_background_sha256",
            "proof",
            "receipt_sha256",
        }
        if not isinstance(value, Mapping) or set(value) != fields:
            raise ValueError("background equivalence receipt fields are invalid")
        receipt = cls(
            identity=value["identity"],
            mechanism_id=value["mechanism_id"],
            reuse_key=ExteriorBackgroundReuseKey.from_mapping(value["reuse_key"]),
            canonical_background_sha256=value["canonical_background_sha256"],
            proof=value["proof"],
        )
        if value["schema"] != _BACKGROUND_EQUIVALENCE_SCHEMA:
            raise ValueError("background equivalence receipt schema is invalid")
        if value["receipt_sha256"] != receipt.sha256:
            raise ValueError("background equivalence receipt digest mismatch")
        return receipt


@dataclass(frozen=True, slots=True)
class Binary64ReusedBackgroundBatch:
    leaf_id: str
    job_id: str
    mechanism_id: str
    fixed_root: complex
    branch_identity: str
    coordinate_step: float
    support: ExteriorSupport
    background_sha256: str
    equivalence_receipt_sha256: str
    samples: tuple[Binary64FixedRootSample, ...]
    sample_limit: int = 4
    root_read_count: int = 0
    julia_launch_count: int = 0

    def __post_init__(self) -> None:
        for name in ("leaf_id", "job_id", "branch_identity"):
            if not isinstance(getattr(self, name), str) or not getattr(self, name):
                raise ValueError(f"reused background {name} is invalid")
        object.__setattr__(
            self, "fixed_root", _finite_complex(self.fixed_root, "fixed root")
        )
        if self.mechanism_id not in _EXTERIOR_PROFILE_IDS:
            raise ValueError("reused background mechanism is invalid")
        if not isinstance(self.support, ExteriorSupport):
            raise ValueError("reused background support is invalid")
        if not math.isfinite(self.coordinate_step) or self.coordinate_step <= 0.0:
            raise ValueError("reused background coordinate step is invalid")
        if tuple(sample.role for sample in self.samples) != (
            _MECHANISM_DERIVATIVE_SAMPLE_ROLES
        ):
            raise ValueError("reused background mechanism sample plan is invalid")
        if self.sample_limit != 4 or len(self.samples) != 4:
            raise ValueError("reused background mechanism sample budget is invalid")
        if self.root_read_count != 0 or self.julia_launch_count != 0:
            raise ValueError("reused background execution budget is invalid")
        for digest in (
            self.background_sha256,
            self.equivalence_receipt_sha256,
        ):
            if _HEX_64.fullmatch(digest) is None:
                raise ValueError("reused background digest is invalid")
        expected_amplitudes = (
            complex(self.coordinate_step, 0.0),
            complex(-self.coordinate_step, 0.0),
            complex(self.coordinate_step / 2.0, 0.0),
            complex(-self.coordinate_step / 2.0, 0.0),
        )
        if any(
            sample.omega != self.fixed_root or sample.amplitude != amplitude
            for sample, amplitude in zip(self.samples, expected_amplitudes)
        ):
            raise ValueError("reused background mechanism sample point is invalid")

    @property
    def sample_count(self) -> int:
        return len(self.samples)

    def to_mapping(self) -> dict[str, object]:
        return {
            "schema": "windows-solver.binary64-reused-background-batch/1",
            "operation_identity": BINARY64_FIXED_ROOT_SURVEY_IDENTITY,
            "leaf_id": self.leaf_id,
            "job_id": self.job_id,
            "mechanism_id": self.mechanism_id,
            "fixed_root": _complex_mapping(self.fixed_root),
            "branch_identity": self.branch_identity,
            "coordinate_step": self.coordinate_step,
            "support": self.support.to_mapping(),
            "background_sha256": self.background_sha256,
            "equivalence_receipt_sha256": self.equivalence_receipt_sha256,
            "samples": [sample.to_mapping() for sample in self.samples],
            "sample_count": self.sample_count,
            "sample_limit": self.sample_limit,
            "root_read_count": self.root_read_count,
            "julia_launch_count": self.julia_launch_count,
        }


def exterior_background_reuse_admitted(
    job: ResponseComponentJob,
    background: CanonicalExteriorBackground | None,
    receipt: BackgroundEquivalenceReceipt | None,
) -> bool:
    """Return true only for the exact key plus its canonical proof receipt."""

    if background is None or receipt is None:
        return False
    if not isinstance(background, CanonicalExteriorBackground) or not isinstance(
        receipt, BackgroundEquivalenceReceipt
    ):
        raise ValueError("background reuse evidence is invalid")
    expected_key = build_exterior_background_reuse_key(
        job,
        root_seal_sha256=background.reuse_key.root_seal_sha256,
        fixed_root=background.fixed_root,
    )
    if (
        background.reuse_key != expected_key
        or receipt.reuse_key != expected_key
        or receipt.mechanism_id != job.mechanism_id
        or receipt.canonical_background_sha256 != background.sha256
    ):
        return False
    expected_receipt = BackgroundEquivalenceReceipt.issue(
        reuse_key=expected_key,
        job=job,
        canonical_background_sha256=background.sha256,
        fixed_root=background.fixed_root,
    )
    return receipt.to_mapping() == expected_receipt.to_mapping()


def screen_binary64_reused_background_batch(
    background: CanonicalExteriorBackground,
    batch: Binary64ReusedBackgroundBatch,
) -> Binary64FixedRootScreening:
    if batch.background_sha256 != background.sha256:
        raise ValueError("reused background digest mismatch")
    combined = Binary64FixedRootBatch(
        leaf_id=batch.leaf_id,
        job_id=batch.job_id,
        mechanism_id=batch.mechanism_id,
        fixed_root=batch.fixed_root,
        branch_identity=batch.branch_identity,
        frequency_step=background.frequency_step,
        coordinate_step=batch.coordinate_step,
        support=batch.support,
        samples=background.samples + batch.samples,
    )
    return screen_binary64_fixed_root_batch(combined)


class Binary64SurveyDisposition(str, Enum):
    PRODUCED = "PRODUCED"
    PROMOTION_PENDING_RESPONSE = "PROMOTION_PENDING_RESPONSE"


@dataclass(frozen=True, slots=True)
class Binary64FixedRootScreening:
    disposition: Binary64SurveyDisposition
    response_disk: ComplexDisk | None
    frequency_derivative_disk: ComplexDisk | None
    coordinate_derivative_disk: ComplexDisk | None
    root_correction_upper_bound: float | None
    reason_code: str | None
    determinant_certificate_status: str = "not-claimed"


def _binary64_stencil_disk(
    plus_h: complex,
    minus_h: complex,
    plus_half: complex,
    minus_half: complex,
    *,
    coarse_denominator: float,
    fine_denominator: float,
) -> ComplexDisk:
    coarse = (plus_h - minus_h) / coarse_denominator
    fine = (plus_half - minus_half) / fine_denominator
    arithmetic_radius = sum(
        math.ulp(abs(value.real)) + math.ulp(abs(value.imag))
        for value in (plus_h, minus_h, plus_half, minus_half, coarse, fine)
    )
    radius = abs(fine - coarse) + arithmetic_radius
    if not math.isfinite(radius) or radius <= 0.0:
        raise ValueError("binary64 derivative disk is not bounded")
    return ComplexDisk(fine, radius)


def screen_binary64_fixed_root_batch(
    batch: Binary64FixedRootBatch,
) -> Binary64FixedRootScreening:
    """Retain raw binary64 survey data without inventing a disk certificate."""

    if not isinstance(batch, Binary64FixedRootBatch):
        raise ValueError("binary64 fixed-root batch is invalid")
    return Binary64FixedRootScreening(
        disposition=Binary64SurveyDisposition.PROMOTION_PENDING_RESPONSE,
        response_disk=None,
        frequency_derivative_disk=None,
        coordinate_derivative_disk=None,
        root_correction_upper_bound=None,
        reason_code="DETERMINANT_ERROR_EVIDENCE_UNAVAILABLE",
        determinant_certificate_status="unavailable",
    )


def screen_promoted_fixed_root_samples(
    samples: Sequence[object],
    *,
    frequency_step: Decimal,
    coordinate_step: Decimal,
) -> Binary64FixedRootScreening:
    """Retain BF40/BF80 raw samples without deriving an unreviewed error model."""

    sample_tuple = tuple(samples)
    if tuple(getattr(sample, "role", None) for sample in sample_tuple) != (
        BINARY64_FIXED_ROOT_SAMPLE_ROLES
    ):
        raise ValueError("promoted fixed-root sample plan is invalid")
    if (
        type(frequency_step) is not Decimal
        or type(coordinate_step) is not Decimal
        or not frequency_step.is_finite()
        or not coordinate_step.is_finite()
        or frequency_step <= 0
        or coordinate_step <= 0
    ):
        raise ValueError("promoted fixed-root steps are invalid")

    for sample in sample_tuple:
        determinant = getattr(sample, "determinant", None)
        conditioning = getattr(sample, "numerical_conditioning", None)
        mapping = getattr(conditioning, "mapping", None)
        if not isinstance(determinant, DecimalComplex) or not isinstance(
            mapping, Mapping
        ):
            raise ValueError("promoted fixed-root sample evidence is invalid")
    return Binary64FixedRootScreening(
        disposition=Binary64SurveyDisposition.PROMOTION_PENDING_RESPONSE,
        response_disk=None,
        frequency_derivative_disk=None,
        coordinate_derivative_disk=None,
        root_correction_upper_bound=None,
        reason_code="DETERMINANT_ERROR_EVIDENCE_UNAVAILABLE",
        determinant_certificate_status="unavailable",
    )


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
  …66785 tokens truncated…eason": validation_reason,
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


def run_promoted_exterior_component(
    job: ResponseComponentJob,
    backend: RootReadoutBackend,
    primary_predictor: complex,
    *,
    derivative_step: float,
    validation_reason: str | None = None,
) -> ComponentResult:
    """Seal one promoted root, then run only fixed-root response work."""

    if job.mechanism_id not in _EXTERIOR_PROFILE_IDS:
        raise ValueError("promoted exterior runner requires an exterior job")
    if (
        validation_reason is not None
        and validation_reason not in FULL_LADDER_VALIDATION_REASONS
    ):
        raise ValueError("promoted exterior validation reason is invalid")
    if not math.isfinite(float(derivative_step)) or float(derivative_step) <= 0.0:
        raise ValueError("exterior derivative step must be finite and positive")
    if backend.identity != job.backend_identity:
        raise ValueError("response backend identity does not match job")
    predictor = _finite_complex(primary_predictor, "PRIMARY root predictor")
    binder = getattr(backend, "bind_job", None)
    if binder is not None:
        job = binder(job)
    root_backend = _journaled_promoted_exterior_backend(
        job,
        backend,
        predictor=predictor,
        derivative_step=float(derivative_step),
        validation_reason=validation_reason,
    )
    baseline = root_backend.read_root(job, 0.0j, primary_predictor=predictor)
    initial_status = _identity_status(job, baseline)
    if initial_status is not None:
        return _validated_result(
            root_backend, job, _unresolved_result(job, initial_status, baseline, ())
        )
    if not root_readout_preserves_authenticated_branch(
        baseline,
        job.root,
        equation_id=job.equation_id,
        source_root_mapping=job.source_root_mapping,
    ):
        return _validated_result(
            root_backend,
            job,
            _unresolved_result(job, ComponentStatus.BRANCH_LOSS, baseline, ()),
        )
    conditioning = baseline.numerical_conditioning
    if conditioning is not None and conditioning.precision_limited:
        # This is root-specific telemetry.  Do not attempt fixed-root response
        # work or fabricate a seal when the root itself explicitly needs more
        # arithmetic.
        return _validated_result(
            root_backend,
            job,
            _unresolved_result(job, ComponentStatus.NOT_CONVERGED, baseline, ()),
        )
    seal = PromotedRootSeal.derive(job, baseline)
    response_backend = _journaled_promoted_exterior_response_backend(
        job,
        backend,
        seal=seal,
        derivative_step=float(derivative_step),
        validation_reason=validation_reason,
    )
    return run_promoted_exterior_response_from_seal(
        job,
        response_backend,
        seal,
        derivative_step=derivative_step,
        validation_reason=validation_reason,
    )


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


def _root_sealed_horizon_result(
    job: ResponseComponentJob,
    *,
    status: ComponentStatus,
    baseline: RootReadout,
    response_disk: ComplexDisk | None,
    evidence: Mapping[str, object],
) -> ComponentResult:
    """Build the versioned horizon result produced without another root read."""

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
                PROMOTED_HORIZON_COMPONENT_V3_IDENTITY
            ),
        },
        component_scientific_identity=PROMOTED_HORIZON_COMPONENT_V3_IDENTITY,
        response_method=PROMOTED_HORIZON_RESPONSE_METHOD_V3,
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


def _sealed_horizon_frequency_evidence(
    job: ResponseComponentJob,
    seal: PromotedRootSeal,
) -> tuple[ComplexDisk, dict[str, object]]:
    """Derive the horizon numerator disk exclusively from root-seal evidence."""

    baseline = seal.root_readout
    corrections = _promoted_horizon_root_correction_evidence(baseline)
    horizon_radius = 1.0 + math.sqrt(max(0.0, 1.0 - job.spin * job.spin))
    omega_h = job.spin / (2.0 * horizon_radius)
    arithmetic_radius = (
        math.ulp(baseline.omega.real)
        + math.ulp(baseline.omega.imag)
        + abs(job.mode.m) * math.ulp(omega_h)
    )
    frequency = ComplexDisk(
        baseline.omega - job.mode.m * omega_h,
        max(float(value) for value in corrections.values()) + arithmetic_radius,
    )
    return frequency, {
        "arithmetic_radius_abs": arithmetic_radius,
        "correction_abs": {
            name: str(value) for name, value in corrections.items()
        },
        "union_rule": "max-accepted-correction-plus-arithmetic/v1",
    }


def run_promoted_horizon_response_from_seal(
    job: ResponseComponentJob,
    backend: RootReadoutBackend,
    seal: PromotedRootSeal,
    *,
    derivative_step: float,
) -> ComponentResult:
    """Rebuild horizon Dω at a sealed root without invoking root solving."""

    if job.mechanism_id != "horizon-admittance":
        raise ValueError("root-sealed horizon repair requires a horizon job")
    if not math.isfinite(job.spin) or abs(job.spin) >= 1.0:
        raise ValueError("promoted horizon Kerr spin must be finite and subextremal")
    step = float(derivative_step)
    if not math.isfinite(step) or step <= 0.0:
        raise ValueError("root-sealed horizon derivative step is invalid")
    if backend.identity != job.backend_identity:
        raise ValueError("response backend identity does not match job")
    binder = getattr(backend, "bind_job", None)
    if binder is not None:
        job = binder(job)
    if backend.identity != job.backend_identity:
        raise ValueError("bound response backend identity does not match job")
    seal.validate_for(job)
    baseline = seal.root_readout
    sample_operation = getattr(backend, "sample_fixed_root_determinant", None)
    if not callable(sample_operation):
        raise ValueError("fixed-root determinant sample boundary is unavailable")
    samples = tuple(
        sample_operation(job, baseline.omega + offset, 0.0j, readout_role=role)
        for offset, role in (
            (complex(step, 0.0), "frequency-real-plus-h"),
            (complex(-step, 0.0), "frequency-real-minus-h"),
            (complex(step / 2.0, 0.0), "frequency-real-plus-h2"),
            (complex(-step / 2.0, 0.0), "frequency-real-minus-h2"),
        )
    )
    contract = regularised_gsn_mechanism_contract(job.mechanism_id)
    conditioning = baseline.numerical_conditioning
    assert conditioning is not None
    for sample, (offset, role) in zip(samples, (
        (complex(step, 0.0), "frequency-real-plus-h"),
        (complex(-step, 0.0), "frequency-real-minus-h"),
        (complex(step / 2.0, 0.0), "frequency-real-plus-h2"),
        (complex(-step / 2.0, 0.0), "frequency-real-minus-h2"),
    )):
        if (
            not isinstance(sample, FixedRootDeterminantSample)
            or sample.omega != baseline.omega + offset
            or sample.amplitude != 0.0j
            or sample.readout_role != role
            or sample.determinant_family != contract["determinant_family"]
            or sample.determinant_normalisation
            != contract["determinant_normalisation"]
            or sample.branch_identity != conditioning.branch_convention
            or sample.branch_authenticated is not True
        ):
            raise ValueError("root-sealed horizon sample binding is invalid")
    frequency, root_provenance = _sealed_horizon_frequency_evidence(job, seal)
    base_evidence = {
        "derivative_source": FIXED_ROOT_FREQUENCY_DERIVATIVE_METHOD,
        "fixed_root_samples": [sample.to_mapping() for sample in samples],
        "horizon_frequency_disk": frequency.to_mapping(),
        "response_disk": None,
        "response_repair_identity": ROOT_SEALED_RESPONSE_REPAIR_IDENTITY,
        "root_radius_provenance": root_provenance,
        "root_seal": seal.to_mapping(),
        "root_seal_sha256": seal.sha256,
        "uncertainty_derivation_identity": (
            PROMOTED_HORIZON_UNCERTAINTY_DERIVATION_IDENTITY
        ),
        "zero_containing_disk": None,
    }
    unavailable = any(
        sample.determinant_error_status != DETERMINANT_ERROR_AVAILABLE
        or sample.determinant_error_model_id is None
        for sample in samples
    )
    if unavailable:
        evidence = {
            **base_evidence,
            "derivative_disk": None,
            "derivative_radius_provenance": {
                "identity": FIXED_ROOT_FREQUENCY_DERIVATIVE_METHOD,
                "failure_code": "DETERMINANT_ERROR_MODEL_UNAVAILABLE",
            },
            "zero_containing_disk": "DETERMINANT_ERROR_MODEL_UNAVAILABLE",
        }
        return _validated_result(
            backend,
            job,
            _root_sealed_horizon_result(
                job,
                status=ComponentStatus.DERIVATIVE_UNRESOLVED,
                baseline=baseline,
                response_disk=None,
                evidence=evidence,
            ),
        )
    derivative, _coarse, _fine, propagated_error, disagreement = (
        _fixed_root_frequency_derivative(samples)
    )
    sampled_step = (samples[0].omega.real - samples[1].omega.real) / 2.0
    evidence = {
        **base_evidence,
        "derivative_disk": derivative.to_mapping(),
        "derivative_radius_provenance": {
            "identity": FIXED_ROOT_FREQUENCY_DERIVATIVE_METHOD,
            "propagated_determinant_error_abs": propagated_error,
            "raw_step_disagreement_abs": disagreement,
            "selected_step": sampled_step / 2.0,
        },
    }
    try:
        response_disk = horizon_response_disk(
            horizon_frequency=frequency,
            determinant_derivative=derivative,
        )
    except ZeroContainingDiskError as error:
        evidence["zero_containing_disk"] = error.disk_name
        return _validated_result(
            backend,
            job,
            _root_sealed_horizon_result(
                job,
                status=ComponentStatus.DERIVATIVE_UNRESOLVED,
                baseline=baseline,
                response_disk=None,
                evidence=evidence,
            ),
        )
    evidence["response_disk"] = response_disk.to_mapping()
    return _validated_result(
        backend,
        job,
        _root_sealed_horizon_result(
            job,
            status=ComponentStatus.CONVERGED,
            baseline=baseline,
            response_disk=response_disk,
            evidence=evidence,
        ),
    )


def _validate_promoted_horizon_baseline(
    job: ResponseComponentJob,
    baseline: RootReadout,
) -> DerivativeAuthenticationEvidence | None:
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

    conditioning = baseline.numerical_conditioning
    if conditioning is not None and conditioning.precision_limited:
        # Precision-limited conditioning is root evidence, so report a typed
        # root outcome.  It must remain distinct from every response failure.
        return _validated_result(
            backend,
            job,
            _unresolved_result(job, ComponentStatus.NOT_CONVERGED, baseline, ()),
        )
    root_seal = PromotedRootSeal.derive(job, baseline)
    if _requires_fixed_root_frequency_stencil(baseline):
        # Production Julia backends expose the fixed-root sampling boundary.
        # Keep old test/replay adapters (which predate that boundary) readable
        # without pretending that they performed a new derivative stencil.
        if callable(getattr(backend, "sample_fixed_root_determinant", None)):
            return run_promoted_horizon_response_from_seal(
                job,
                backend,
                root_seal,
                derivative_step=job.policy.epsilons[0],
            )
    assert derivative_authentication is not None
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
        "root_seal": root_seal.to_mapping(),
        "root_seal_sha256": root_seal.sha256,
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
    empirical_calibration = (
        scientific_runtime.get("promoted_control_calibration")
        if isinstance(scientific_runtime, Mapping)
        else None
    )
    empirical_profile = (
        scientific_runtime.get("empirical_control_profile")
        if isinstance(scientific_runtime, Mapping)
        else None
    )
    empirical_profile_sha256 = (
        scientific_runtime.get("empirical_control_profile_sha256")
        if isinstance(scientific_runtime, Mapping)
        else None
    )
    empirical_journal = (
        isinstance(empirical_calibration, Mapping)
        and isinstance(empirical_profile, Mapping)
        and isinstance(empirical_profile_sha256, str)
    )
    journal_evidence: dict[str, object] = {
        "schema": (
            "windows-solver.selective-tier-journal-evidence/2"
            if empirical_journal
            else "windows-solver.selective-tier-journal-evidence/1"
        ),
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
        common_journal_evidence = {
            "journal": journal_mapping,
            "journal_sha256": journal_mapping["journal_sha256"],
            "promoted_work_unit_ids": list(promoted_work_unit_ids),
            "scientific_runtime": scientific_runtime,
            "scientific_runtime_sha256": (
                None
                if not isinstance(scientific_runtime, Mapping)
                else _sha256(dict(scientific_runtime))
            ),
        }
        if empirical_journal:
            common_journal_evidence.update({
                "promoted_control_calibration": dict(empirical_calibration),
                "empirical_control_profile": dict(empirical_profile),
                "empirical_control_profile_sha256": (
                    empirical_profile_sha256
                ),
            })
        else:
            common_journal_evidence.update({
                "ode_error_budget": ode_error_budget,
                "ode_error_budget_sha256": (
                    None
                    if ode_error_budget is None
                    else _sha256(ode_error_budget)
                ),
            })
        journal_evidence.update(common_journal_evidence)
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
