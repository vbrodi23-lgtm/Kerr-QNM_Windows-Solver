"""Mechanism and promoted-readout policy identities retire stale receipts.

Receipt reuse is decided by exact equality against
``regularised_gsn_precision_policy(mechanism_id)``. That makes the policy
mapping load-bearing in both directions at once:

* A horizon receipt written before the rewrite describes a different
  calculation -- one solution propagated through a mixed match-to-inner leg,
  not a basis built from three independent legs on a verified real-inner
  contour. It must not be reusable.
* The binary64-parity promoted acceptance policy changes both determinant
  families' readout semantics, so a pre-policy exterior receipt is stale too.

Nothing about the second property is automatic. Adding a horizon-only field to
the shared policy as ``None`` is enough to break it, silently, with no failing
assertion anywhere else -- which is what these tests exist to prevent.
"""

from __future__ import annotations

from decimal import Decimal
import hashlib
import math
import unittest

from windows_solver import response_batches, response_engine
from windows_solver.contracts import canonical_json_bytes
from windows_solver.julia_response_backend import JuliaPrecisionRootBackend
from windows_solver.response_batches import (
    PrecisionCapabilities,
    build_campaign_plan,
)
from tests.fixtures import (
    synthetic_ode_error_budget,
    valid_horizon_endpoint_search_evidence,
    valid_numerical_conditioning,
)


# The pre-policy exterior identity from ``main``. The determinant mathematics
# is unchanged, but the promoted root acceptance/readout policy is not.
MAIN_EXTERIOR_PRECISION_POLICY = {
    "asymptotic_series_evaluation": "typed-batch-horner-compensated/v1",
    "branch_convention": "gsn-complex-rho/v1",
    "conditioning_diagnostics": "series-recurrence-basis-fd/v1",
    "determinant_convention": "wronskian-perturbed-Xin-with-Xup/v1",
    "determinant_family": "exterior-wronskian/v1",
    "determinant_normalisation": "unit-asymptotic-branch-wronskian/v1",
    "factored_remainder_state_convention": "state1=Y;state2=dY/drho/v1",
    "homogeneous_representation": "factored-plane-wave-gsn/v1",
    "horizon_determinant_chart": None,
    "human_math_review_receipt_sha256": None,
    "human_math_review_receipt_status": "absent-unapproved/v1",
    "independent_reference_fixture_receipt_sha256": None,
    "independent_reference_fixture_receipt_status": "absent-unreviewed/v1",
    "radial_derivative_convention": "state2=dX/drho/v1",
    "regular_remainder_contract": "known-carrier-times-regular-remainder/v1",
    "reliable_digit_safety_margin": "8",
    "required_digit_guard": "6",
    "scattering_chart_safety_factor": None,
    "scattering_coefficient_extraction": None,
    "scattering_column_convention": None,
    "scattering_diagnostics_applicable": False,
}

# Likewise for the horizon mechanism on `main`: the calculation this branch
# replaced.
PRE_REWRITE_HORIZON_PRECISION_POLICY = {
    "asymptotic_series_evaluation": "typed-batch-horner-compensated/v1",
    "branch_convention": "gsn-complex-rho/v1",
    "conditioning_diagnostics": "series-recurrence-basis-fd/v1",
    "determinant_convention": "cinc-over-cref-minus-R/v1",
    "determinant_family": "horizon-scattering/v1",
    "determinant_normalisation": "cinc-over-cref-minus-reflectivity/v1",
    "factored_remainder_state_convention": "state1=Y;state2=dY/drho/v1",
    "homogeneous_representation": "factored-plane-wave-gsn/v1",
    "horizon_determinant_chart": "cinc-over-cref-minus-reflectivity/v1",
    "human_math_review_receipt_sha256": None,
    "human_math_review_receipt_status": "absent-unapproved/v1",
    "independent_reference_fixture_receipt_sha256": None,
    "independent_reference_fixture_receipt_status": "absent-unreviewed/v1",
    "radial_derivative_convention": "state2=dX/drho/v1",
    "regular_remainder_contract": "known-carrier-times-regular-remainder/v1",
    "reliable_digit_safety_margin": "8",
    "required_digit_guard": "6",
    "scattering_chart_safety_factor": "64",
    "scattering_coefficient_extraction": "scaled-factored-horizon-basis/v1",
    "scattering_column_convention": (
        "column1=horizon-ingoing-Cref;column2=horizon-outgoing-Cinc/v1"
    ),
    "scattering_diagnostics_applicable": True,
}

# The calculation identities changed by the rewrite plus the two horizon-only
# controls that explicitly keep the unmeasured profile out of release.
REWRITTEN_HORIZON_IDENTITY_FIELDS = {
    "promoted_root_readout_policy",
    "homogeneous_representation",
    "scattering_coefficient_extraction",
    "horizon_contour",
    "determinant_error_model",
    "control_profile_label",
    "calibration_status",
}


class MechanismScopedPolicyTests(unittest.TestCase):
    def test_every_exterior_policy_changes_only_for_promoted_root_acceptance(self):
        """The exterior determinant is stable while its root policy is revised."""

        for mechanism in response_engine._EXTERIOR_PROFILE_IDS:
            with self.subTest(mechanism=mechanism):
                policy = dict(
                    response_engine.regularised_gsn_precision_policy(mechanism)
                )
                expected = {
                    **MAIN_EXTERIOR_PRECISION_POLICY,
                    "promoted_root_readout_policy": (
                        response_engine.PROMOTED_ROOT_READOUT_POLICY
                    ),
                }
                self.assertEqual(policy, expected)
                self.assertEqual(
                    set(policy) - set(MAIN_EXTERIOR_PRECISION_POLICY),
                    {"promoted_root_readout_policy"},
                )

    def test_horizon_policy_differs_in_exactly_the_rewritten_identities(self):
        """Catches both an unretired horizon receipt and collateral churn.

        Too few differences and a pre-rewrite horizon receipt stays reusable
        while describing a calculation that no longer exists. Too many, and the
        rewrite is claiming to have changed something it did not.
        """

        policy = dict(
            response_engine.regularised_gsn_precision_policy(
                "horizon-admittance"
            )
        )
        changed = {
            field
            for field in set(policy) | set(PRE_REWRITE_HORIZON_PRECISION_POLICY)
            if policy.get(field, object())
            != PRE_REWRITE_HORIZON_PRECISION_POLICY.get(field, object())
        }
        self.assertEqual(changed, REWRITTEN_HORIZON_IDENTITY_FIELDS)
        self.assertNotEqual(policy, PRE_REWRITE_HORIZON_PRECISION_POLICY)

    def test_horizon_only_identities_are_absent_not_null_on_the_exterior(self):
        """Catches the category error that caused the compatibility break.

        ``horizon_contour: None`` on an exterior policy asserts that the
        exterior mechanism has a horizon contour whose value happens to be
        nothing. It does not have one. The field does not apply, and a field
        that does not apply is absent.
        """

        horizon = response_engine.regularised_gsn_precision_policy(
            "horizon-admittance"
        )
        exterior = response_engine.regularised_gsn_precision_policy(
            "exterior-fixed-r3"
        )
        for field in (
            "horizon_contour",
            "determinant_error_model",
            "control_profile_label",
            "calibration_status",
        ):
            with self.subTest(field=field):
                self.assertIn(field, horizon)
                self.assertNotIn(field, exterior)


class ReceiptCompatibilityTests(unittest.TestCase):
    """Drive the gate that actually decides reuse, not a restatement of it.

    Only the stored policy is stale in these fixtures; the conditioning
    evidence is current. That makes the horizon case the harder one to reject
    -- a receipt that disagreed on everything would be caught by several gates
    at once, and would not show that this one works.
    """

    def _leaf(self, mechanism):
        plan = build_campaign_plan(
            policy=response_engine.NumericalPolicy(),
            backend_identity=(
                response_engine.VettedNativeDeterminantKernel.identity
            ),
            precision_capabilities=PrecisionCapabilities((64, 80, 120)),
        )
        return next(
            leaf for leaf in plan.leaves if leaf.job.mechanism_id == mechanism
        )

    def _runtime(self, job, policy):
        budget = synthetic_ode_error_budget(80).to_mapping()
        return {
            "julia_version": "1.10.11",
            "julia_executable_sha256": "a" * 64,
            "julia_manifest_sha256": "b" * 64,
            "worker_sha256": "c" * 64,
            "runtime_policy_sha256": "d" * 64,
            "scientific_sources": [],
            "precision_digits": 80,
            "working_precision_bits": math.ceil(80 * math.log2(10)) + 32,
            "refinement_level": 0,
            "regularised_gsn_precision_policy": dict(policy),
            "ode_error_budget": budget,
            "ode_error_budget_sha256": hashlib.sha256(
                canonical_json_bytes(budget)
            ).hexdigest(),
        }

    def _readout(self, job, runtime):
        horizon = job.mechanism_id == "horizon-admittance"
        request_binding = JuliaPrecisionRootBackend(
            job.backend_identity,
            object(),
            80,
            ode_error_budget=synthetic_ode_error_budget(80),
        )._request(job, 0.0j)
        determinant = Decimal("1E-10")
        derivative = Decimal("2")
        correction = determinant / derivative
        primary = response_engine.PrimaryRootAcceptanceEvidence(
            policy_id=response_engine.PROMOTED_ROOT_READOUT_POLICY,
            acceptance_metric=response_engine.PROMOTED_ROOT_ACCEPTANCE_METRIC,
            determinant=response_engine.DecimalComplex(determinant, Decimal(0)),
            derivative=response_engine.DecimalComplex(derivative, Decimal(0)),
            correction_abs=correction,
            root_correction_tolerance=Decimal("2E-11"),
            accepted=False,
            newton_determinant_count=3,
            post_newton_determinant_count=0,
            determinant_error_abs=Decimal(0),
            error_model_id=(
                response_engine.VERIFIED_ENDPOINT_ERROR_MODEL
                if horizon
                else None
            ),
        )
        material = {
            "schema": response_engine.WORKER_RESPONSE_RECEIPT_SCHEMA,
            "request_binding": request_binding,
            "request_sha256": hashlib.sha256(
                canonical_json_bytes(request_binding)
            ).hexdigest(),
            "scientific_runtime_sha256": hashlib.sha256(
                canonical_json_bytes(runtime)
            ).hexdigest(),
            "worker_response_schema_version": (
                response_engine.WORKER_RESPONSE_WIRE_SCHEMA
            ),
            "root_residual_abs_text": str(determinant),
            "raw_determinant_abs_text": str(determinant) if horizon else None,
            "raw_determinant_evidence_status": (
                "available/v1" if horizon else "not-applicable/v1"
            ),
            "promoted_root_readout_policy": (
                response_engine.PROMOTED_ROOT_READOUT_POLICY
            ),
            "primary_acceptance_sha256": hashlib.sha256(
                canonical_json_bytes(primary.to_mapping())
            ).hexdigest(),
            "horizon_endpoint_search_evidence": (
                valid_horizon_endpoint_search_evidence(request_binding)
                if horizon
                else None
            ),
        }
        return response_engine.RootReadout(
            omega=job.root.omega,
            determinant_residual_abs=float(determinant),
            determinant_derivative_abs=2.0,
            converged=False,
            root_reference_id=job.root.root_reference_id,
            branch_id=job.root.branch_id,
            equation_id=job.equation_id,
            truncation_radius=None,
            resolution_radius=None,
            seed_path_radius=None,
            diagnostics_skipped_reason="PRIMARY_NOT_CONVERGED",
            numerical_conditioning=(
                response_engine.NumericalConditioningEvidence.from_mapping(
                    valid_numerical_conditioning(job.mechanism_id)
                )
            ),
            normalised_determinant_abs=determinant,
            raw_determinant_abs=determinant if horizon else None,
            raw_determinant_evidence_status=(
                "available/v1" if horizon else "not-applicable/v1"
            ),
            worker_response_receipt={
                **material,
                "receipt_sha256": hashlib.sha256(
                    canonical_json_bytes(material)
                ).hexdigest(),
            },
            root_authentication=None,
            promoted_root_readout_policy=(
                response_engine.PROMOTED_ROOT_READOUT_POLICY
            ),
            primary_acceptance=primary,
            seed_path_required=False,
            seed_path_executed=False,
            seed_path_determinant_count=0,
        )

    def _validate(self, mechanism, policy):
        leaf = self._leaf(mechanism)
        job = leaf.job
        runtime = self._runtime(job, policy)
        baseline = self._readout(job, runtime)
        result = response_engine.ComponentResult(
            job_id=job.job_id,
            leaf_id=job.leaf_id,
            mechanism_id=job.mechanism_id,
            status=response_engine.ComponentStatus.NOT_CONVERGED,
            convergence_basis="UNRESOLVED",
            response=None,
            signed_root_crosscheck=None,
            closed_form_response=None,
            error_channels={
                name: 0.0 for name in response_engine.ERROR_CHANNELS
            },
            baseline=baseline,
            levels=(),
            lineage={
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
            },
        )
        component = {
            "evidence_kind": "package-owned-julia-promoted-component-engine",
            "result": result.to_mapping(),
            "self_refinement_result": None,
            "scientific_runtime": runtime,
            "self_refinement_skipped_reason": "PRIMARY_NOT_CONVERGED",
        }
        outcome = response_batches.StageOutcome(
            digits=80,
            numerical_state="NOT_CONVERGED",
            component_result=component,
            local_disk_radius_abs=0.0,
            signed_error_channels=(
                response_batches.synthetic_stage_signed_error_channels(
                    component, 0.0
                )
            ),
            self_refinement_enclosed=False,
            discrepancy_from_previous_abs=0.0,
            discrepancy_enclosed=True,
        )
        response_batches._validate_current_promoted_runtime(
            leaf, outcome, result
        )

    def test_a_pre_policy_exterior_receipt_is_rejected_as_stale(self):
        with self.assertRaises(
            response_batches._UnauthenticatedComponentEvidence
        ):
            self._validate(
                "exterior-light-ring", MAIN_EXTERIOR_PRECISION_POLICY
            )

    def test_the_current_exterior_policy_is_accepted(self):
        self._validate(
            "exterior-light-ring",
            response_engine.regularised_gsn_precision_policy(
                "exterior-light-ring"
            ),
        )

    def test_a_pre_rewrite_horizon_receipt_is_rejected_as_stale(self):
        """A receipt for a calculation this branch no longer performs."""

        with self.assertRaises(
            response_batches._UnauthenticatedComponentEvidence
        ) as caught:
            self._validate(
                "horizon-admittance", PRE_REWRITE_HORIZON_PRECISION_POLICY
            )
        self.assertIn("disagrees with mechanism", str(caught.exception))

    def test_the_current_horizon_policy_is_accepted(self):
        """Anchors the rejection above to staleness.

        Without this, a horizon path that could not validate under any policy
        would produce the same red-to-green transition and look like proof.
        """

        self._validate(
            "horizon-admittance",
            response_engine.regularised_gsn_precision_policy(
                "horizon-admittance"
            ),
        )


if __name__ == "__main__":
    unittest.main()
