from __future__ import annotations

import copy
from dataclasses import replace
from decimal import Decimal, localcontext
import hashlib
import math
import unittest

from tests.fixtures import (
    control_failure_stage,
    valid_control_failure_diagnostics,
    valid_numerical_conditioning,
    valid_julia_root_response,
)
from windows_solver.contracts import canonical_json_bytes
from windows_solver.julia_response_backend import (
    JuliaPrecisionRootBackend,
    JuliaResponseBackendError,
)
import windows_solver.julia_response_backend as julia_backend
from windows_solver.response_batches import (
    PrecisionCapabilities,
    build_campaign_plan,
)
import windows_solver.response_batches as response_batches
import windows_solver.response_engine as response_engine
from windows_solver.root_readout_cache import root_readout_identity_sha256


def historical_schema_two_conditioning(
    mechanism_id: str = "horizon-admittance",
) -> dict[str, object]:
    mapping = valid_numerical_conditioning(mechanism_id)
    mapping["schema"] = "windows-solver.m02-conditioning/2"
    for field in (
        "human_math_review_receipt_status",
        "human_math_review_receipt_sha256",
        "independent_reference_fixture_receipt_status",
        "independent_reference_fixture_receipt_sha256",
    ):
        mapping.pop(field)
    return mapping


class NumericalConditioningEvidenceTests(unittest.TestCase):
    def test_historical_schema_two_round_trips_without_inventing_gate_receipts(self):
        source = historical_schema_two_conditioning()

        evidence = response_engine.NumericalConditioningEvidence.from_mapping(
            source
        )

        self.assertEqual(evidence.to_mapping(), source)
        self.assertIsNone(evidence.human_math_review_receipt_status)
        self.assertIsNone(evidence.human_math_review_receipt_sha256)
        self.assertIsNone(
            evidence.independent_reference_fixture_receipt_status
        )
        self.assertIsNone(
            evidence.independent_reference_fixture_receipt_sha256
        )

    def test_schema_two_rejects_backfilled_gate_fields(self):
        stale = valid_numerical_conditioning()
        stale["schema"] = "windows-solver.m02-conditioning/2"

        with self.assertRaises(ValueError):
            response_engine.NumericalConditioningEvidence.from_mapping(stale)

    def test_current_evidence_binds_both_independent_activation_gates(self):
        evidence = response_engine.NumericalConditioningEvidence.from_mapping(
            valid_numerical_conditioning()
        )

        self.assertEqual(evidence.schema, "windows-solver.m02-conditioning/3")
        self.assertEqual(
            evidence.human_math_review_receipt_status,
            "absent-unapproved/v1",
        )
        self.assertIsNone(evidence.human_math_review_receipt_sha256)
        self.assertEqual(
            evidence.independent_reference_fixture_receipt_status,
            "absent-unreviewed/v1",
        )
        self.assertIsNone(
            evidence.independent_reference_fixture_receipt_sha256
        )

    def test_current_evidence_rejects_either_gate_identity_tamper(self):
        mutations = {
            "human_math_review_receipt_status": "approved/v1",
            "human_math_review_receipt_sha256": "0" * 64,
            "independent_reference_fixture_receipt_status": "reviewed/v1",
            "independent_reference_fixture_receipt_sha256": "1" * 64,
        }
        for field, invalid in mutations.items():
            with self.subTest(field=field):
                mapping = valid_numerical_conditioning()
                mapping[field] = invalid
                with self.assertRaises(ValueError):
                    response_engine.NumericalConditioningEvidence.from_mapping(
                        mapping
                    )

    def test_complete_evidence_round_trips_without_binary64_conversion(self):
        """Catches dropping precision or any required schema-2 evidence field."""

        self.assertTrue(
            hasattr(response_engine, "NumericalConditioningEvidence"),
            "response_engine must export NumericalConditioningEvidence",
        )
        evidence_type = response_engine.NumericalConditioningEvidence
        source = valid_numerical_conditioning()

        evidence = evidence_type.from_mapping(source)

        self.assertIsInstance(evidence.maximum_series_digits_lost, Decimal)
        self.assertEqual(evidence.maximum_series_digits_lost, Decimal("4.2500"))
        self.assertEqual(evidence.to_mapping(), source)

    def test_exterior_evidence_round_trips_explicit_non_applicability(self):
        """Catches horizon scattering sentinels leaking into a Wronskian result."""

        source = valid_numerical_conditioning("exterior-light-ring")
        evidence = response_engine.NumericalConditioningEvidence.from_mapping(
            source
        )

        self.assertEqual(evidence.determinant_family, "exterior-wronskian/v1")
        self.assertIs(evidence.scattering_diagnostics_applicable, False)
        self.assertEqual(
            evidence.determinant_convention,
            "wronskian-perturbed-Xin-with-Xup/v1",
        )
        self.assertEqual(
            evidence.determinant_normalisation,
            "unit-asymptotic-branch-wronskian/v1",
        )
        for field in (
            "maximum_basis_condition",
            "maximum_basis_backward_error",
            "maximum_matching_reconstruction_residual",
            "minimum_cref_chart_margin",
            "maximum_carrier_change_error",
            "scattering_column_convention",
        ):
            self.assertIsNone(getattr(evidence, field), field)
            self.assertIsNone(evidence.to_mapping()[field], field)
        self.assertEqual(evidence.to_mapping(), source)

    def test_applicability_rejects_cross_family_fields_and_numeric_sentinels(self):
        """Catches finite-looking basis/chart claims on an exterior determinant."""

        mutations = {
            "true_applicability": ("scattering_diagnostics_applicable", True),
            "horizon_family": ("determinant_family", "horizon-scattering/v1"),
            "horizon_columns": (
                "scattering_column_convention",
                "column1=horizon-ingoing-Cref;"
                "column2=horizon-outgoing-Cinc/v1",
            ),
            "numeric_sentinel": ("maximum_basis_condition", "0"),
            "wrong_normalisation": (
                "determinant_normalisation",
                "cinc-over-cref-minus-reflectivity/v1",
            ),
        }
        for label, (field, invalid) in mutations.items():
            with self.subTest(label=label):
                mapping = valid_numerical_conditioning("exterior-fixed-r3")
                mapping[field] = invalid
                with self.assertRaises(ValueError):
                    response_engine.NumericalConditioningEvidence.from_mapping(
                        mapping
                    )

        horizon = valid_numerical_conditioning()
        horizon["maximum_basis_condition"] = None
        with self.assertRaises(ValueError):
            response_engine.NumericalConditioningEvidence.from_mapping(horizon)

    def test_evidence_rejects_non_string_nonfinite_negative_and_identity_drift(self):
        """Catches permissive parsing of malformed or convention-mixed evidence."""

        evidence_type = response_engine.NumericalConditioningEvidence
        mutations = {
            "binary64": ("maximum_basis_condition", 8.0e12),
            "nonfinite": ("maximum_basis_condition", "NaN"),
            "negative_error": (
                "maximum_matching_reconstruction_residual",
                "-1E-40",
            ),
            "non_boolean": ("precision_limited", 0),
            "identity_drift": ("branch_convention", "another-branch/v1"),
        }
        for label, (field, invalid) in mutations.items():
            with self.subTest(label=label):
                mapping = valid_numerical_conditioning()
                mapping[field] = invalid
                with self.assertRaises(ValueError):
                    evidence_type.from_mapping(mapping)

    def test_predicted_reliable_digits_may_be_negative(self):
        """Catches incorrectly rejecting a valid precision-insufficiency signal."""

        evidence_type = response_engine.NumericalConditioningEvidence
        mapping = valid_numerical_conditioning()
        mapping["minimum_asymptotic_predicted_reliable_digits"] = "-9.25"
        mapping["predicted_reliable_digits"] = "-3.50"
        mapping["precision_limited"] = True

        evidence = evidence_type.from_mapping(mapping)

        self.assertEqual(evidence.predicted_reliable_digits, Decimal("-3.50"))
        self.assertEqual(evidence.to_mapping(), mapping)

    def test_precision_limited_must_equal_the_reliable_digit_comparison(self):
        """Catches contradictory promotion evidence in either Boolean direction."""

        evidence_type = response_engine.NumericalConditioningEvidence
        contradictions = (
            ("11.25", "24", False),
            ("52.25", "24", True),
        )
        for predicted, required, precision_limited in contradictions:
            with self.subTest(
                predicted=predicted,
                required=required,
                precision_limited=precision_limited,
            ):
                mapping = valid_numerical_conditioning()
                mapping["predicted_reliable_digits"] = predicted
                mapping["required_reliable_digits"] = required
                mapping["precision_limited"] = precision_limited
                with self.assertRaisesRegex(
                    ValueError, "precision_limited must equal"
                ):
                    evidence_type.from_mapping(mapping)

    def test_evidence_requires_the_exact_closed_field_set(self):
        """Catches accepting partial or extension fields in the strict schema."""

        evidence_type = response_engine.NumericalConditioningEvidence
        missing = valid_numerical_conditioning()
        missing.pop("maximum_last_term_ratio")
        added = valid_numerical_conditioning()
        added["unreviewed_metric"] = "0"

        for mapping in (missing, added):
            with self.assertRaises(ValueError):
                evidence_type.from_mapping(mapping)

    def test_schema_one_conditioning_is_not_silently_upgraded(self):
        """Catches inventing determinant applicability while reading old evidence."""

        stale = valid_numerical_conditioning()
        stale["schema"] = "windows-solver.m02-conditioning/1"

        with self.assertRaisesRegex(ValueError, "schema is invalid"):
            response_engine.NumericalConditioningEvidence.from_mapping(stale)

    def test_conditioning_fixture_rejects_unknown_exterior_mechanisms(self):
        """Catches test data authenticating a misspelled exterior mechanism."""

        with self.assertRaisesRegex(ValueError, "mechanism is invalid"):
            valid_numerical_conditioning("exterior-not-a-supported-mechanism")


class RootReadoutConditioningPersistenceTests(unittest.TestCase):
    @staticmethod
    def _legacy_readout() -> response_engine.RootReadout:
        return response_engine.RootReadout(
            omega=0.5 - 0.1j,
            determinant_residual_abs=1.0e-12,
            determinant_derivative_abs=2.0,
            converged=True,
            root_reference_id="root-reference",
            branch_id="damped-branch",
            equation_id="equation/v1",
        )

    def test_root_readout_persists_exact_conditioning_evidence(self):
        """Catches checkpoint mappings dropping promoted conditioning evidence."""

        evidence = response_engine.NumericalConditioningEvidence.from_mapping(
            valid_numerical_conditioning()
        )
        readout = response_engine.RootReadout(
            omega=0.5 - 0.1j,
            determinant_residual_abs=1.0e-12,
            determinant_derivative_abs=2.0,
            converged=True,
            root_reference_id="root-reference",
            branch_id="damped-branch",
            equation_id="equation/v1",
            numerical_conditioning=evidence,
            raw_determinant_abs=Decimal("0"),
            raw_determinant_evidence_status="available/v1",
        )

        mapping = readout.to_mapping()
        restored = response_engine.RootReadout.from_mapping(mapping)

        self.assertEqual(
            mapping["numerical_conditioning"], valid_numerical_conditioning()
        )
        self.assertEqual(restored.numerical_conditioning, evidence)
        self.assertEqual(
            restored.raw_determinant_evidence_status,
            "available/v1",
        )
        self.assertEqual(restored.to_mapping(), mapping)

    def test_root_readout_round_trips_typed_unavailable_raw_evidence(self):
        """Catches persistence fabricating a magnitude for raw overflow."""

        evidence = response_engine.NumericalConditioningEvidence.from_mapping(
            valid_numerical_conditioning("horizon-admittance")
        )
        readout = response_engine.RootReadout(
            omega=0.5 - 0.1j,
            determinant_residual_abs=1.0e-12,
            determinant_derivative_abs=2.0,
            converged=True,
            root_reference_id="root-reference",
            branch_id="damped-branch",
            equation_id="equation/v1",
            numerical_conditioning=evidence,
            normalised_determinant_abs=Decimal("1E-12"),
            raw_determinant_abs=None,
            raw_determinant_evidence_status="unavailable-overflow/v1",
        )

        mapping = readout.to_mapping()
        restored = response_engine.RootReadout.from_mapping(mapping)

        self.assertNotIn("raw_determinant_abs", mapping)
        self.assertEqual(
            mapping["raw_determinant_evidence_status"],
            "unavailable-overflow/v1",
        )
        self.assertEqual(restored.to_mapping(), mapping)

    def test_root_readout_persists_exact_determinant_magnitudes(self):
        """Catches binary64 narrowing of promoted determinant evidence."""

        normalised = Decimal(
            "4.5000000000000000000000000000000000000000000000001E-120"
        )
        raw = Decimal("6.7500000000000000000000000000000000001E+220")
        readout = self._legacy_readout()
        readout = response_engine.RootReadout(
            omega=readout.omega,
            determinant_residual_abs=float(normalised),
            determinant_derivative_abs=readout.determinant_derivative_abs,
            converged=readout.converged,
            root_reference_id=readout.root_reference_id,
            branch_id=readout.branch_id,
            equation_id=readout.equation_id,
            normalised_determinant_abs=normalised,
            raw_determinant_abs=raw,
        )

        mapping = readout.to_mapping()
        restored = response_engine.RootReadout.from_mapping(mapping)

        self.assertEqual(mapping["normalised_determinant_abs"], str(normalised))
        self.assertEqual(mapping["raw_determinant_abs"], str(raw))
        self.assertEqual(restored.normalised_determinant_abs, normalised)
        self.assertEqual(restored.raw_determinant_abs, raw)
        self.assertEqual(restored.to_mapping(), mapping)

    def test_root_readout_rejects_contradictory_normalised_determinant(self):
        """Catches convergence and reporting consuming different residuals."""

        base = {
            "omega": 0.5 - 0.1j,
            "determinant_residual_abs": 1.0e-12,
            "determinant_derivative_abs": 2.0,
            "converged": True,
            "root_reference_id": "root-reference",
            "branch_id": "damped-branch",
            "equation_id": "equation/v1",
        }
        with self.assertRaisesRegex(ValueError, "disagrees"):
            response_engine.RootReadout(
                **base,
                normalised_determinant_abs=Decimal("1E-80"),
            )

        mapping = self._legacy_readout().to_mapping()
        mapping["normalised_determinant_abs"] = "1E-80"
        with self.assertRaisesRegex(ValueError, "disagrees"):
            response_engine.RootReadout.from_mapping(mapping)

    def test_root_readout_accepts_underflow_consistent_exact_determinant(self):
        """Catches rejecting exact evidence whose legacy projection is zero."""

        exact = Decimal("1.2500000000000000000000000000001E-1000")
        readout = response_engine.RootReadout(
            omega=0.5 - 0.1j,
            determinant_residual_abs=0.0,
            determinant_derivative_abs=2.0,
            converged=True,
            root_reference_id="root-reference",
            branch_id="damped-branch",
            equation_id="equation/v1",
            normalised_determinant_abs=exact,
        )

        restored = response_engine.RootReadout.from_mapping(
            readout.to_mapping()
        )

        self.assertEqual(float(exact), 0.0)
        self.assertEqual(restored.normalised_determinant_abs, exact)
        self.assertEqual(restored.determinant_residual_abs, 0.0)

    def test_root_readout_determinant_magnitudes_are_strict_decimals(self):
        """Catches non-finite, negative, or precision-losing determinant evidence."""

        base = {
            "omega": 0.5 - 0.1j,
            "determinant_residual_abs": 1.0e-12,
            "determinant_derivative_abs": 2.0,
            "converged": True,
            "root_reference_id": "root-reference",
            "branch_id": "damped-branch",
            "equation_id": "equation/v1",
        }
        invalid_values = (
            1.0,
            "1",
            Decimal("NaN"),
            Decimal("Infinity"),
            Decimal("-1"),
        )
        for field in ("normalised_determinant_abs", "raw_determinant_abs"):
            for invalid in invalid_values:
                with self.subTest(field=field, invalid=invalid):
                    with self.assertRaises(ValueError):
                        response_engine.RootReadout(**base, **{field: invalid})

            mapping = self._legacy_readout().to_mapping()
            mapping[field] = 1.0
            with self.subTest(field=field, invalid="binary64 mapping"):
                with self.assertRaises(ValueError):
                    response_engine.RootReadout.from_mapping(mapping)

    def test_exterior_root_readout_rejects_raw_horizon_determinant(self):
        """Catches raw Cramer evidence leaking into an exterior Wronskian."""

        evidence = response_engine.NumericalConditioningEvidence.from_mapping(
            valid_numerical_conditioning("exterior-light-ring")
        )

        with self.assertRaisesRegex(ValueError, "raw_determinant_abs"):
            response_engine.RootReadout(
                omega=0.5 - 0.1j,
                determinant_residual_abs=1.0e-12,
                determinant_derivative_abs=2.0,
                converged=True,
                root_reference_id="root-reference",
                branch_id="damped-branch",
                equation_id="equation/v1",
                numerical_conditioning=evidence,
                raw_determinant_abs=Decimal("0"),
            )

    def test_conditioned_horizon_root_requires_raw_determinant(self):
        """Catches dropping the raw Cinc−R·Cref equivalence comparator."""

        evidence = response_engine.NumericalConditioningEvidence.from_mapping(
            valid_numerical_conditioning("horizon-admittance")
        )

        with self.assertRaisesRegex(ValueError, "raw_determinant_abs"):
            response_engine.RootReadout(
                omega=0.5 - 0.1j,
                determinant_residual_abs=1.0e-12,
                determinant_derivative_abs=2.0,
                converged=True,
                root_reference_id="root-reference",
                branch_id="damped-branch",
                equation_id="equation/v1",
                numerical_conditioning=evidence,
                normalised_determinant_abs=Decimal("1E-12"),
                raw_determinant_abs=None,
            )

    def test_root_readout_rejects_invalid_raw_status_value_pairs(self):
        """Catches persistence accepting contradictory typed raw evidence."""

        horizon = response_engine.NumericalConditioningEvidence.from_mapping(
            valid_numerical_conditioning("horizon-admittance")
        )
        exterior = response_engine.NumericalConditioningEvidence.from_mapping(
            valid_numerical_conditioning("exterior-light-ring")
        )
        base = {
            "omega": 0.5 - 0.1j,
            "determinant_residual_abs": 1.0e-12,
            "determinant_derivative_abs": 2.0,
            "converged": True,
            "root_reference_id": "root-reference",
            "branch_id": "damped-branch",
            "equation_id": "equation/v1",
            "normalised_determinant_abs": Decimal("1E-12"),
        }
        cases = (
            (horizon, None, "available/v1"),
            (horizon, Decimal("1"), "unavailable-overflow/v1"),
            (horizon, None, "not-applicable/v1"),
            (horizon, None, "unavailable-overflow/v2"),
            (exterior, Decimal("1"), "available/v1"),
            (exterior, None, "unavailable-overflow/v1"),
        )
        for evidence, raw, status in cases:
            with self.subTest(status=status, raw=raw):
                with self.assertRaises(ValueError):
                    response_engine.RootReadout(
                        **base,
                        numerical_conditioning=evidence,
                        raw_determinant_abs=raw,
                        raw_determinant_evidence_status=status,
                    )

    def test_historical_conditioned_root_without_raw_status_remains_readable(self):
        """Catches retroactively requiring schema-3 status on old checkpoints."""

        evidence = response_engine.NumericalConditioningEvidence.from_mapping(
            valid_numerical_conditioning("horizon-admittance")
        )
        current = response_engine.RootReadout(
            omega=0.5 - 0.1j,
            determinant_residual_abs=1.0e-12,
            determinant_derivative_abs=2.0,
            converged=True,
            root_reference_id="root-reference",
            branch_id="damped-branch",
            equation_id="equation/v1",
            numerical_conditioning=evidence,
            normalised_determinant_abs=Decimal("1E-12"),
            raw_determinant_abs=Decimal("2E+100"),
            raw_determinant_evidence_status="available/v1",
        ).to_mapping()
        current.pop("raw_determinant_evidence_status")

        restored = response_engine.RootReadout.from_mapping(current)

        self.assertIsNone(restored.raw_determinant_evidence_status)
        self.assertEqual(restored.raw_determinant_abs, Decimal("2E+100"))
        self.assertEqual(restored.to_mapping(), current)

    def test_historical_root_without_conditioning_remains_readable(self):
        """Catches breaking completed schema-1 checkpoints during the migration."""

        historical = self._legacy_readout().to_mapping()
        self.assertNotIn("numerical_conditioning", historical)

        restored = response_engine.RootReadout.from_mapping(historical)

        self.assertIsNone(restored.numerical_conditioning)
        self.assertIsNone(restored.normalised_determinant_abs)
        self.assertIsNone(restored.raw_determinant_abs)
        self.assertEqual(restored.to_mapping(), historical)

    def test_present_malformed_conditioning_fails_closed(self):
        """Catches treating malformed present evidence like an absent legacy field."""

        malformed = self._legacy_readout().to_mapping()
        malformed["numerical_conditioning"] = valid_numerical_conditioning()
        malformed["numerical_conditioning"]["maximum_fd_digits_lost"] = 3.0

        with self.assertRaises(ValueError):
            response_engine.RootReadout.from_mapping(malformed)

    def test_component_result_round_trip_keeps_nested_conditioning(self):
        """Catches component/checkpoint persistence stripping root evidence."""

        evidence = response_engine.NumericalConditioningEvidence.from_mapping(
            valid_numerical_conditioning()
        )
        baseline = response_engine.RootReadout(
            omega=0.5 - 0.1j,
            determinant_residual_abs=1.0e-12,
            determinant_derivative_abs=2.0,
            converged=True,
            root_reference_id="root-reference",
            branch_id="damped-branch",
            equation_id="equation/v1",
            numerical_conditioning=evidence,
            raw_determinant_abs=Decimal("0"),
            raw_determinant_evidence_status="available/v1",
        )
        result = response_engine.ComponentResult(
            job_id="job",
            leaf_id="leaf",
            mechanism_id="horizon-admittance",
            status=response_engine.ComponentStatus.NOT_CONVERGED,
            convergence_basis="UNRESOLVED",
            response=None,
            signed_root_crosscheck=None,
            closed_form_response=None,
            error_channels={name: 0.0 for name in response_engine.ERROR_CHANNELS},
            baseline=baseline,
            levels=(),
            lineage={"identity": "synthetic"},
        )

        restored = response_engine.ComponentResult.from_mapping(
            result.to_mapping()
        )

        self.assertEqual(restored.baseline.numerical_conditioning, evidence)
        self.assertEqual(
            restored.baseline.raw_determinant_evidence_status,
            "available/v1",
        )
        self.assertEqual(restored.to_mapping(), result.to_mapping())

    def test_component_result_binds_every_conditioned_readout_to_mechanism(self):
        """Catches one baseline or ladder readout using the wrong determinant family."""

        def readout(mechanism_id: str) -> response_engine.RootReadout:
            evidence = response_engine.NumericalConditioningEvidence.from_mapping(
                valid_numerical_conditioning(mechanism_id)
            )
            return response_engine.RootReadout(
                omega=0.5 - 0.1j,
                determinant_residual_abs=1.0e-12,
                determinant_derivative_abs=2.0,
                converged=True,
                root_reference_id="root-reference",
                branch_id="damped-branch",
                equation_id="equation/v1",
                numerical_conditioning=evidence,
                raw_determinant_abs=(
                    Decimal("0")
                    if mechanism_id == "horizon-admittance"
                    else None
                ),
            )

        exterior = readout("exterior-fixed-r3")
        horizon = readout("horizon-admittance")
        locations = (
            "baseline",
            "real_plus",
            "real_minus",
            "imaginary_plus",
            "imaginary_minus",
        )
        for location in locations:
            with self.subTest(location=location):
                values = {
                    "real_plus": exterior,
                    "real_minus": exterior,
                    "imaginary_plus": exterior,
                    "imaginary_minus": exterior,
                }
                baseline = exterior
                if location == "baseline":
                    baseline = horizon
                else:
                    values[location] = horizon
                level = response_engine.LadderLevel(epsilon=0.125, **values)

                with self.assertRaisesRegex(
                    ValueError, "determinant family disagrees"
                ):
                    response_engine.ComponentResult(
                        job_id="job",
                        leaf_id="leaf",
                        mechanism_id="exterior-fixed-r3",
                        status=response_engine.ComponentStatus.NOT_CONVERGED,
                        convergence_basis="UNRESOLVED",
                        response=None,
                        signed_root_crosscheck=None,
                        closed_form_response=None,
                        error_channels={
                            name: 0.0 for name in response_engine.ERROR_CHANNELS
                        },
                        baseline=baseline,
                        levels=(level,),
                        lineage={"identity": "synthetic"},
                    )


class PromotedRuntimeProvenancePersistenceTests(unittest.TestCase):
    @staticmethod
    def _historical_policy(job):
        policy = dict(
            response_engine.regularised_gsn_precision_policy(
                job.mechanism_id
            )
        )
        for field in (
            "promoted_root_readout_policy",
            "human_math_review_receipt_status",
            "human_math_review_receipt_sha256",
            "independent_reference_fixture_receipt_status",
            "independent_reference_fixture_receipt_sha256",
        ):
            policy.pop(field)
        policy["regularised_gsn_activation_status"] = (
            "blocked-pending-human-math-review-and-independent-reference/v1"
        )
        return policy

    @staticmethod
    def _leaf():
        plan = build_campaign_plan(
            policy=response_engine.NumericalPolicy(),
            backend_identity=response_engine.VettedNativeDeterminantKernel.identity,
            precision_capabilities=PrecisionCapabilities((64, 80, 120)),
        )
        return next(
            leaf
            for leaf in plan.leaves
            if leaf.job.mechanism_id == "exterior-light-ring"
        )

    @staticmethod
    def _result(job, *, current_schema: bool):
        conditioning = (
            response_engine.NumericalConditioningEvidence.from_mapping(
                valid_numerical_conditioning(job.mechanism_id)
            )
            if current_schema
            else None
        )
        worker_response_receipt = None
        primary_acceptance = None
        determinant_abs = Decimal("1E-10")
        if current_schema:
            request_binding = JuliaPrecisionRootBackend(
                job.backend_identity, object(), 80
            )._request(job, 0.0j)
            primary_acceptance = response_engine.PrimaryRootAcceptanceEvidence(
                policy_id=response_engine.PROMOTED_ROOT_READOUT_POLICY,
                acceptance_metric=(
                    response_engine.PROMOTED_ROOT_ACCEPTANCE_METRIC
                ),
                determinant=response_engine.DecimalComplex(
                    determinant_abs, Decimal(0)
                ),
                derivative=response_engine.DecimalComplex(
                    Decimal(2), Decimal(0)
                ),
                correction_abs=Decimal("5E-11"),
                root_correction_tolerance=Decimal("2E-11"),
                accepted=False,
                newton_determinant_count=3,
                post_newton_determinant_count=0,
                determinant_error_abs=Decimal(0),
                error_model_id=None,
            )
            receipt_material = {
                "schema": response_engine.WORKER_RESPONSE_RECEIPT_SCHEMA,
                "request_binding": request_binding,
                "request_sha256": hashlib.sha256(
                    canonical_json_bytes(request_binding)
                ).hexdigest(),
                "scientific_runtime_sha256": hashlib.sha256(
                    canonical_json_bytes(
                        PromotedRuntimeProvenancePersistenceTests._current_runtime(
                            job
                        )
                    )
                ).hexdigest(),
                "worker_response_schema_version": (
                    response_engine.WORKER_RESPONSE_WIRE_SCHEMA
                ),
                "root_residual_abs_text": str(determinant_abs),
                "raw_determinant_abs_text": None,
                "raw_determinant_evidence_status": "not-applicable/v1",
                "promoted_root_readout_policy": (
                    response_engine.PROMOTED_ROOT_READOUT_POLICY
                ),
                "primary_acceptance_sha256": hashlib.sha256(
                    canonical_json_bytes(primary_acceptance.to_mapping())
                ).hexdigest(),
            }
            worker_response_receipt = {
                **receipt_material,
                "receipt_sha256": hashlib.sha256(
                    canonical_json_bytes(receipt_material)
                ).hexdigest(),
            }
        baseline = response_engine.RootReadout(
            omega=job.root.omega,
            determinant_residual_abs=(
                float(determinant_abs) if current_schema else 1.0e-12
            ),
            determinant_derivative_abs=2.0,
            converged=False,
            root_reference_id=job.root.root_reference_id,
            branch_id=job.root.branch_id,
            equation_id=job.equation_id,
            truncation_radius=None,
            resolution_radius=None,
            seed_path_radius=None,
            diagnostics_skipped_reason="PRIMARY_NOT_CONVERGED",
            numerical_conditioning=conditioning,
            normalised_determinant_abs=(
                determinant_abs if current_schema else None
            ),
            raw_determinant_abs=None,
            raw_determinant_evidence_status=(
                "not-applicable/v1" if current_schema else None
            ),
            worker_response_receipt=worker_response_receipt,
            root_authentication=None,
            promoted_root_readout_policy=(
                response_engine.PROMOTED_ROOT_READOUT_POLICY
                if current_schema
                else None
            ),
            primary_acceptance=primary_acceptance,
            seed_path_required=False if current_schema else None,
            seed_path_executed=False if current_schema else None,
            seed_path_determinant_count=0 if current_schema else None,
        )
        return response_engine.ComponentResult(
            job_id=job.job_id,
            leaf_id=job.leaf_id,
            mechanism_id=job.mechanism_id,
            status=response_engine.ComponentStatus.NOT_CONVERGED,
            convergence_basis="UNRESOLVED",
            response=None,
            signed_root_crosscheck=None,
            closed_form_response=None,
            error_channels={name: 0.0 for name in response_engine.ERROR_CHANNELS},
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

    @staticmethod
    def _stage_outcome(result, runtime):
        component = {
            "evidence_kind": "package-owned-julia-promoted-component-engine",
            "result": result.to_mapping(),
            "self_refinement_result": None,
            "scientific_runtime": runtime,
            "self_refinement_skipped_reason": "PRIMARY_NOT_CONVERGED",
        }
        return response_batches.StageOutcome(
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

    def test_skipped_promoted_diagnostics_survive_dataclass_replacement(self):
        """Catches immutable empty diagnostic evidence becoming unparsable."""

        leaf = self._leaf()
        result = self._result(
            leaf.job,
            current_schema=True,
        )

        replaced = replace(result.baseline, worker_response_receipt=None)

        self.assertFalse(replaced.converged)
        self.assertEqual(replaced.diagnostic_readouts, {})
        self.assertEqual(
            replaced.diagnostics_skipped_reason,
            "PRIMARY_NOT_CONVERGED",
        )

    @staticmethod
    def _current_runtime(job):
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
            "regularised_gsn_precision_policy": dict(
                response_engine.regularised_gsn_precision_policy(
                    job.mechanism_id
                )
            ),
        }

    def test_current_promoted_runtime_is_bound_to_job_and_precision(self):
        """Catches checkpoint provenance drifting from the computed result."""

        leaf = self._leaf()
        job = leaf.job
        result = self._result(job, current_schema=True)
        mutations = {
            "wrong_family": lambda runtime: runtime.__setitem__(
                "regularised_gsn_precision_policy",
                dict(response_engine.REGULARISED_GSN_PRECISION_POLICY),
            ),
            "missing_policy": lambda runtime: runtime.pop(
                "regularised_gsn_precision_policy"
            ),
            "wrong_digits": lambda runtime: runtime.__setitem__(
                "precision_digits", 120
            ),
            "wrong_bits": lambda runtime: runtime.__setitem__(
                "working_precision_bits", 1
            ),
            "wrong_refinement": lambda runtime: runtime.__setitem__(
                "refinement_level", 1
            ),
            "human_status": lambda runtime: runtime[
                "regularised_gsn_precision_policy"
            ].__setitem__("human_math_review_receipt_status", "approved/v1"),
            "human_digest": lambda runtime: runtime[
                "regularised_gsn_precision_policy"
            ].__setitem__("human_math_review_receipt_sha256", "0" * 64),
            "reference_status": lambda runtime: runtime[
                "regularised_gsn_precision_policy"
            ].__setitem__(
                "independent_reference_fixture_receipt_status", "reviewed/v1"
            ),
            "reference_digest": lambda runtime: runtime[
                "regularised_gsn_precision_policy"
            ].__setitem__(
                "independent_reference_fixture_receipt_sha256", "1" * 64
            ),
        }
        for label, mutate in mutations.items():
            with self.subTest(label=label):
                runtime = self._current_runtime(job)
                mutate(runtime)
                outcome = self._stage_outcome(result, runtime)
                with self.assertRaisesRegex(ValueError, "scientific runtime"):
                    response_batches._validate_component_result(leaf, outcome)

        valid = self._stage_outcome(result, self._current_runtime(job))
        self.assertTrue(response_batches._validate_component_result(leaf, valid))
        self.assertTrue(response_batches._validate_component_result(
            leaf,
            valid,
            allow_historical_conditioning_absence=False,
        ))

    def test_current_promoted_receipt_is_bound_to_scientific_runtime(self):
        """Catches replaying exact worker text under a different runtime."""

        leaf = self._leaf()
        result = self._result(leaf.job, current_schema=True)
        baseline_mapping = result.baseline.to_mapping()
        receipt = dict(baseline_mapping["worker_response_receipt"])
        receipt["scientific_runtime_sha256"] = "f" * 64
        material = {
            key: value
            for key, value in receipt.items()
            if key != "receipt_sha256"
        }
        receipt["receipt_sha256"] = hashlib.sha256(
            canonical_json_bytes(material)
        ).hexdigest()
        baseline_mapping["worker_response_receipt"] = receipt
        tampered = replace(
            result,
            baseline=response_engine.RootReadout.from_mapping(
                baseline_mapping
            ),
        )
        outcome = self._stage_outcome(
            tampered, self._current_runtime(leaf.job)
        )

        with self.assertRaisesRegex(ValueError, "worker response receipt"):
            response_batches._validate_component_result(
                leaf,
                outcome,
                allow_historical_conditioning_absence=False,
            )

    def test_historical_promoted_runtime_without_conditioning_remains_readable(self):
        """Catches retroactively applying schema-2 policy to historical evidence."""

        leaf = self._leaf()
        job = leaf.job
        result = self._result(job, current_schema=False)
        runtime = self._current_runtime(job)
        runtime.pop("regularised_gsn_precision_policy")
        outcome = self._stage_outcome(result, runtime)

        self.assertTrue(response_batches._validate_component_result(leaf, outcome))

    def test_historical_schema_two_is_bounded_to_exact_combined_policy(self):
        leaf = self._leaf()
        current = self._result(leaf.job, current_schema=True)
        baseline = current.baseline.to_mapping()
        baseline["numerical_conditioning"] = (
            historical_schema_two_conditioning(leaf.job.mechanism_id)
        )
        baseline.pop("worker_response_receipt")
        for field in (
            "promoted_root_readout_policy",
            "primary_acceptance",
            "seed_path_required",
            "seed_path_executed",
            "seed_path_determinant_count",
        ):
            baseline.pop(field)
        historical = replace(
            current,
            baseline=response_engine.RootReadout.from_mapping(baseline),
        )
        runtime = self._current_runtime(leaf.job)
        runtime["regularised_gsn_precision_policy"] = self._historical_policy(
            leaf.job
        )
        outcome = self._stage_outcome(historical, runtime)

        self.assertTrue(
            response_batches._validate_component_result(leaf, outcome)
        )
        with self.assertRaisesRegex(ValueError, "conditioning schema"):
            response_batches._validate_component_result(
                leaf,
                outcome,
                allow_historical_conditioning_absence=False,
            )

        runtime["regularised_gsn_precision_policy"] = {
            **self._historical_policy(leaf.job),
            "regularised_gsn_activation_status": "blocked-but-drifted/v1",
        }
        with self.assertRaisesRegex(ValueError, "runtime policy"):
            response_batches._validate_component_result(
                leaf,
                self._stage_outcome(historical, runtime),
            )

    def test_historical_promoted_runtime_must_still_identify_its_precision(self):
        """Catches malformed current packages masquerading as historical evidence."""

        leaf = self._leaf()
        job = leaf.job
        result = self._result(job, current_schema=False)
        mutations = {
            "missing_runtime": lambda runtime: None,
            "wrong_digits": lambda runtime: {
                **runtime,
                "precision_digits": 120,
            },
            "wrong_bits": lambda runtime: {
                **runtime,
                "working_precision_bits": 1,
            },
            "wrong_refinement": lambda runtime: {
                **runtime,
                "refinement_level": 1,
            },
        }
        for label, mutate in mutations.items():
            with self.subTest(label=label):
                runtime = self._current_runtime(job)
                runtime.pop("regularised_gsn_precision_policy")
                outcome = self._stage_outcome(result, mutate(runtime))
                with self.assertRaisesRegex(ValueError, "scientific runtime"):
                    response_batches._validate_component_result(leaf, outcome)


class JuliaSchemaThreeConditioningTests(unittest.TestCase):
    @staticmethod
    def _job(mechanism_id="horizon-admittance"):
        plan = build_campaign_plan(
            policy=response_engine.NumericalPolicy(),
            backend_identity=response_engine.VettedNativeDeterminantKernel.identity,
            precision_capabilities=PrecisionCapabilities((64, 80, 120)),
        )
        return next(
            leaf.job
            for leaf in plan.leaves
            if leaf.job.mechanism_id == mechanism_id
        )

    class Adapter:
        runtime_provenance = {
            "julia_version": "1.10.11",
            "julia_executable_sha256": "a" * 64,
            "julia_manifest_sha256": "b" * 64,
            "worker_sha256": "c" * 64,
            "runtime_policy_sha256": "d" * 64,
            "scientific_sources": [],
        }

        def __init__(self, mutate=None):
            self.requests: list[dict[str, object]] = []
            self.mutate = mutate

        def evaluate(self, request):
            self.requests.append(request)
            response = valid_julia_root_response(request)
            if self.mutate is not None:
                self.mutate(response)
            return response

    def _backend(self, adapter=None, *, digits=80):
        return JuliaPrecisionRootBackend(
            response_engine.VettedNativeDeterminantKernel.identity,
            self.Adapter() if adapter is None else adapter,
            digits,
        )

    def test_schema_three_success_requires_and_persists_conditioning(self):
        """Catches accepting current promoted success without evidence."""

        readout = self._backend().read_root(self._job(), 0.0j)

        self.assertIsNotNone(readout.numerical_conditioning)
        self.assertEqual(
            readout.numerical_conditioning.to_mapping(),
            valid_numerical_conditioning(),
        )

    def test_current_worker_rejects_historical_conditioning_schema_two(self):
        def downgrade(response):
            response["numerical_conditioning"] = (
                historical_schema_two_conditioning()
            )

        with self.assertRaisesRegex(
            JuliaResponseBackendError,
            "current conditioning schema is required",
        ):
            self._backend(self.Adapter(downgrade)).read_root(
                self._job(), 0.0j
            )

    def test_exterior_schema_three_persists_named_wronskian_and_no_raw_chart(self):
        """Catches presenting an exterior Wronskian as horizon scattering."""

        job = self._job("exterior-light-ring")
        readout = self._backend().read_root(job, 0.0j)

        self.assertEqual(
            readout.numerical_conditioning.to_mapping(),
            valid_numerical_conditioning("exterior-light-ring"),
        )
        self.assertEqual(
            readout.normalised_determinant_abs, Decimal("1E-12")
        )
        self.assertIsNone(readout.raw_determinant_abs)
        self.assertEqual(
            readout.raw_determinant_evidence_status,
            "not-applicable/v1",
        )

    def test_exterior_schema_three_rejects_raw_or_horizon_scattering_evidence(self):
        """Catches accepting internally inconsistent mechanism diagnostics."""

        job = self._job("exterior-fixed-r3")
        mutations = {
            "raw_chart": lambda response: response.__setitem__(
                "raw_determinant_abs", "2.5E+40"
            ),
            "available_status": lambda response: response.__setitem__(
                "raw_determinant_evidence_status", "available/v1"
            ),
            "unavailable_status": lambda response: response.__setitem__(
                "raw_determinant_evidence_status", "unavailable-overflow/v1"
            ),
            "horizon_family": lambda response: response[
                "numerical_conditioning"
            ].__setitem__("determinant_family", "horizon-scattering/v1"),
            "applicable": lambda response: response[
                "numerical_conditioning"
            ].__setitem__("scattering_diagnostics_applicable", True),
        }
        for label, mutate in mutations.items():
            with self.subTest(label=label):
                with self.assertRaises(JuliaResponseBackendError):
                    self._backend(self.Adapter(mutate)).read_root(job, 0.0j)

    def test_schema_three_preserves_exact_determinant_magnitudes(self):
        """Catches converting determinant evidence to binary64 before persistence."""

        normalised = (
            "4.5000000000000000000000000000000000000000000000001E-120"
        )
        raw = "6.7500000000000000000000000000000000001E+220"

        def exact_magnitudes(response):
            response["root_residual_abs"] = normalised
            response["raw_determinant_abs"] = raw
            primary = dict(response["primary_acceptance"])
            primary["determinant_re"] = normalised
            primary["determinant_im"] = "0"
            with localcontext() as context:
                context.prec = 180
                derivative_abs = (
                    Decimal(primary["derivative_re"]) ** 2
                    + Decimal(primary["derivative_im"]) ** 2
                ).sqrt()
                correction = Decimal(normalised) / derivative_abs
            primary["correction_abs"] = str(correction)
            response["primary_acceptance"] = primary

        readout = self._backend(self.Adapter(exact_magnitudes)).read_root(
            self._job(), 0.0j
        )

        self.assertEqual(readout.normalised_determinant_abs, Decimal(normalised))
        self.assertEqual(readout.raw_determinant_abs, Decimal(raw))
        self.assertEqual(
            readout.to_mapping()["normalised_determinant_abs"], normalised
        )
        self.assertEqual(readout.to_mapping()["raw_determinant_abs"], raw)

    def test_schema_three_rejects_invalid_raw_evidence_status_pairs(self):
        """Catches accepting a horizon result without its raw comparator."""

        mutations = {
            "available_without_value": lambda response: response.__setitem__(
                "raw_determinant_abs", None
            ),
            "unavailable_with_value": lambda response: response.__setitem__(
                "raw_determinant_evidence_status", "unavailable-overflow/v1"
            ),
            "horizon_not_applicable": lambda response: response.__setitem__(
                "raw_determinant_evidence_status", "not-applicable/v1"
            ),
            "unknown_status": lambda response: response.__setitem__(
                "raw_determinant_evidence_status", "available/v2"
            ),
        }
        for label, mutate in mutations.items():
            with self.subTest(label=label):
                with self.assertRaises(JuliaResponseBackendError):
                    self._backend(self.Adapter(mutate)).read_root(
                        self._job(), 0.0j
                    )

    def test_schema_three_accepts_typed_unavailable_raw_horizon_evidence(self):
        """Catches requiring an overflowing optional raw chart comparator."""

        def unavailable(response):
            response["raw_determinant_abs"] = None
            response["raw_determinant_evidence_status"] = (
                "unavailable-overflow/v1"
            )

        readout = self._backend(self.Adapter(unavailable)).read_root(
            self._job(), 0.0j
        )

        self.assertIsNone(readout.raw_determinant_abs)
        self.assertEqual(
            readout.raw_determinant_evidence_status,
            "unavailable-overflow/v1",
        )

    def test_malformed_current_raw_determinant_fails_closed(self):
        """Catches accepting precision-losing or invalid raw determinant evidence."""

        mutations = {
            "missing": lambda response: response.pop("raw_determinant_abs"),
            "binary64": lambda response: response.__setitem__(
                "raw_determinant_abs", 6.75e220
            ),
            "nonfinite": lambda response: response.__setitem__(
                "raw_determinant_abs", "NaN"
            ),
            "negative": lambda response: response.__setitem__(
                "raw_determinant_abs", "-1E-30"
            ),
        }
        for label, mutate in mutations.items():
            with self.subTest(label=label):
                with self.assertRaises(JuliaResponseBackendError):
                    self._backend(self.Adapter(mutate)).read_root(
                        self._job(), 0.0j
                    )

    def test_stale_success_wire_schemas_are_historical_only(self):
        """Catches a stale schema-1/2 success satisfying current work."""

        for schema_version in (1, 2):
            with self.subTest(schema_version=schema_version):
                adapter = self.Adapter(
                    lambda response, schema_version=schema_version: (
                        response.__setitem__("schema_version", schema_version)
                    )
                )
                with self.assertRaisesRegex(
                    JuliaResponseBackendError,
                    "response policy/wire schema is inconsistent",
                ):
                    self._backend(adapter).read_root(self._job(), 0.0j)

    def test_schema_three_control_integers_require_exact_builtin_ints(self):
        """Catches float/string drift passing equality-based schema checks."""

        request = self._backend()._request(self._job(), 0.0j)
        expected = valid_julia_root_response(request)
        fields = (
            "schema_version",
            "precision_digits",
            "working_precision_bits",
            "branch_authentication_contract_version",
        )
        for field in fields:
            for drift in (float(expected[field]), str(expected[field])):
                with self.subTest(field=field, drift=drift):
                    adapter = self.Adapter(
                        lambda response, field=field, drift=drift: (
                            response.__setitem__(field, drift)
                        )
                    )
                    with self.assertRaises(JuliaResponseBackendError):
                        self._backend(adapter).read_root(self._job(), 0.0j)

    def test_schema_three_success_status_must_be_exactly_ok(self):
        """Catches accepting an error-shaped response through the success parser."""

        adapter = self.Adapter(
            lambda response: response.__setitem__("status", "error")
        )

        with self.assertRaisesRegex(
            JuliaResponseBackendError, "response contract is invalid"
        ):
            self._backend(adapter).read_root(self._job(), 0.0j)

    def test_missing_or_malformed_current_evidence_fails_closed(self):
        """Catches weakening schema-3 parsing to accommodate stale fakes."""

        def remove(response):
            response.pop("numerical_conditioning")

        def corrupt(response):
            response["numerical_conditioning"][
                "maximum_series_digits_lost"
            ] = 4.25

        for label, mutation in (("missing", remove), ("malformed", corrupt)):
            with self.subTest(label=label):
                with self.assertRaises(JuliaResponseBackendError):
                    self._backend(self.Adapter(mutation)).read_root(
                        self._job(), 0.0j
                    )

    def test_response_convention_must_match_the_request_policy(self):
        """Catches mixing finite output from a different branch convention."""

        def drift(response):
            response["numerical_conditioning"]["branch_convention"] = (
                "forged-branch/v1"
            )

        with self.assertRaisesRegex(
            JuliaResponseBackendError, "numerical conditioning"
        ):
            self._backend(self.Adapter(drift)).read_root(self._job(), 0.0j)

    def test_precision_policy_binds_every_factored_identity_and_review_gate(self):
        """Catches omitted identity material allowing raw/factored cache aliasing."""

        backend = self._backend()
        request = backend._request(self._job(), 0.0j)
        expected = {
            "promoted_root_readout_policy": (
                "binary64-parity-primary-fixed-root-diagnostics/v1"
            ),
            "determinant_family": "horizon-scattering/v1",
            "scattering_diagnostics_applicable": True,
            # The horizon determinant is built from three independent legs on
            # a verified real-inner contour, so it carries its own
            # representation, contour, extraction, and error-model identities.
            "homogeneous_representation": (
                "factored-three-leg-horizon-basis-at-match-gsn/v1"
            ),
            "horizon_contour": "real-inner-tortoise-contour/v1",
            "determinant_error_model": (
                "verified-endpoint-control-equivalence-absolute-error/v2"
            ),
            "control_profile_label": "provisional promoted control profile",
            "calibration_status": "UNMEASURED",
            "asymptotic_series_evaluation": (
                "typed-batch-horner-compensated/v1"
            ),
            "scattering_coefficient_extraction": (
                "scaled-horizon-basis-at-match/v1"
            ),
            "horizon_determinant_chart": (
                "cinc-over-cref-minus-reflectivity/v1"
            ),
            "conditioning_diagnostics": "series-recurrence-basis-fd/v1",
            "scattering_chart_safety_factor": "64",
            "branch_convention": "gsn-complex-rho/v1",
            "scattering_column_convention": (
                "column1=horizon-ingoing-Cref;"
                "column2=horizon-outgoing-Cinc/v1"
            ),
            "radial_derivative_convention": "state2=dX/drho/v1",
            "determinant_convention": "cinc-over-cref-minus-R/v1",
            "determinant_normalisation": (
                "cinc-over-cref-minus-reflectivity/v1"
            ),
            "regular_remainder_contract": (
                "known-carrier-times-regular-remainder/v1"
            ),
            "factored_remainder_state_convention": (
                "state1=Y;state2=dY/drho/v1"
            ),
            "reliable_digit_safety_margin": "8",
            "required_digit_guard": "6",
            "human_math_review_receipt_status": "absent-unapproved/v1",
            "human_math_review_receipt_sha256": None,
            "independent_reference_fixture_receipt_status": (
                "absent-unreviewed/v1"
            ),
            "independent_reference_fixture_receipt_sha256": None,
        }

        for field, value in expected.items():
            self.assertEqual(request["policy"][field], value)
        self.assertEqual(
            backend.scientific_runtime_for(self._job())[
                "regularised_gsn_precision_policy"
            ],
            expected,
        )

    def test_exterior_precision_policy_is_wronskian_specific(self):
        """Catches a request authenticating horizon-only algebra for exterior work."""

        backend = self._backend()
        job = self._job("exterior-throat-kappa")
        policy = backend._request(job, 0.0j)["policy"]

        self.assertEqual(policy["determinant_family"], "exterior-wronskian/v1")
        self.assertIs(policy["scattering_diagnostics_applicable"], False)
        self.assertIsNone(policy["scattering_column_convention"])
        self.assertEqual(
            policy["determinant_convention"],
            "wronskian-perturbed-Xin-with-Xup/v1",
        )
        self.assertEqual(
            policy["determinant_normalisation"],
            "unit-asymptotic-branch-wronskian/v1",
        )
        self.assertIsNone(policy["scattering_coefficient_extraction"])
        self.assertIsNone(policy["horizon_determinant_chart"])
        self.assertIsNone(policy["scattering_chart_safety_factor"])
        # The exterior path is unchanged by the horizon rewrite: it keeps the
        # original representation, and the identities the rewrite introduced
        # are absent rather than null. A null would still change the policy
        # mapping, and receipt reuse is decided by exact equality against it --
        # so every exterior receipt main produced would go stale for a change
        # that never touched the exterior determinant.
        self.assertEqual(
            policy["homogeneous_representation"], "factored-plane-wave-gsn/v1"
        )
        self.assertNotIn("horizon_contour", policy)
        self.assertNotIn("determinant_error_model", policy)
        self.assertNotIn("control_profile_label", policy)
        self.assertNotIn("calibration_status", policy)
        runtime_policy = backend.scientific_runtime_for(job)[
            "regularised_gsn_precision_policy"
        ]
        self.assertEqual(
            set(runtime_policy),
            set(response_engine.REGULARISED_GSN_PRECISION_POLICY)
            - {
                "horizon_contour",
                "determinant_error_model",
                "control_profile_label",
                "calibration_status",
            },
        )
        self.assertEqual(
            runtime_policy,
            {field: policy[field] for field in runtime_policy},
        )
        self.assertNotIn(
            "regularised_gsn_precision_policy", backend.scientific_runtime
        )

    def test_backend_rejects_request_policy_drift_from_job_mechanism(self):
        """Catches policy/response agreement laundering the wrong determinant family."""

        backend = self._backend()
        job = self._job("exterior-alpha-half")
        request = backend._request(job, 0.0j)
        request["policy"]["determinant_family"] = "horizon-scattering/v1"

        with self.assertRaises(ValueError):
            julia_backend._validate_mechanism_precision_policy(
                job.mechanism_id, request["policy"]
            )

    def test_request_and_cache_identity_bind_each_activation_gate(self):
        baseline = self._backend()._request(self._job(), 0.0j)
        baseline_digest = hashlib.sha256(
            canonical_json_bytes(baseline)
        ).hexdigest()
        mutations = {
            "human_math_review_receipt_status": "approved/v1",
            "human_math_review_receipt_sha256": "0" * 64,
            "independent_reference_fixture_receipt_status": "reviewed/v1",
            "independent_reference_fixture_receipt_sha256": "1" * 64,
        }
        for field, invalid in mutations.items():
            with self.subTest(field=field):
                changed = copy.deepcopy(baseline)
                changed["policy"][field] = invalid
                changed_digest = hashlib.sha256(
                    canonical_json_bytes(changed)
                ).hexdigest()
                self.assertNotEqual(baseline_digest, changed_digest)
                self.assertNotEqual(
                    root_readout_identity_sha256(
                        request_sha256=baseline_digest,
                        runtime_identity="f" * 64,
                    ),
                    root_readout_identity_sha256(
                        request_sha256=changed_digest,
                        runtime_identity="f" * 64,
                    ),
                )
                with self.assertRaises(ValueError):
                    julia_backend._validate_mechanism_precision_policy(
                        self._job().mechanism_id,
                        changed["policy"],
                    )

    def test_precision_bits_change_request_and_cache_identity(self):
        """Catches BigFloat requests at different precisions sharing a cache key."""

        request = self._backend()._request(self._job(), 0.0j)
        changed = copy.deepcopy(request)
        changed["working_precision_bits"] += 1
        first_digest = hashlib.sha256(canonical_json_bytes(request)).hexdigest()
        changed_digest = hashlib.sha256(canonical_json_bytes(changed)).hexdigest()
        runtime = "f" * 64

        self.assertNotEqual(first_digest, changed_digest)
        self.assertNotEqual(
            root_readout_identity_sha256(
                request_sha256=first_digest, runtime_identity=runtime
            ),
            root_readout_identity_sha256(
                request_sha256=changed_digest, runtime_identity=runtime
            ),
        )


class JuliaNumericalControlFailureTests(unittest.TestCase):
    CODES = (
        "SCATTERING_BASIS_ILL_CONDITIONED",
        "SCATTERING_CHART_ILL_CONDITIONED",
        "ASYMPTOTIC_SERIES_INVALID",
        "INSUFFICIENT_ASYMPTOTIC_PRECISION",
        "PHYSICAL_SINGULAR_LIMIT",
        "ALGEBRAIC_REPRESENTATION_SINGULAR",
        "CARRIER_CHANGE_INCONSISTENT",
        "INVALID_FACTORED_PROPAGATION_INPUT",
        "FACTORED_PROPAGATION_PRECISION_MISMATCH",
        "NONFINITE_FACTORED_PROPAGATION_DATA",
        "FACTORED_ODE_FAILURE",
        "NO_VERIFIED_HORIZON_ENDPOINT",
        "COORDINATE_INVERSION_STALLED",
        "DETERMINANT_UNCERTAINTY_TOO_LARGE",
        "FINITE_DIFFERENCE_NOISE_LIMIT",
    )

    @staticmethod
    def _diagnostics(code: str) -> dict[str, object]:
        return valid_control_failure_diagnostics(code)

    @staticmethod
    def _details(code: str, *, include_identity: bool = True):
        policy = julia_backend._execution_resource_policy()
        failure = {
            "failure_code": code,
            "failure_class": "CONTROL",
            "retryable": code == "INSUFFICIENT_ASYMPTOTIC_PRECISION",
            "stage": control_failure_stage(code),
            "diagnostics": (
                JuliaNumericalControlFailureTests._diagnostics(code)
                if code in JuliaNumericalControlFailureTests.CODES
                else {"reason": code}
            ),
        }
        if include_identity:
            failure["execution_resource_policy"] = policy
        return policy, {
            "worker_exit_code": 21,
            "worker_timed_out": False,
            "worker_stderr_tail": "bounded numerical-control failure",
            "worker_error_type": "GSNNumericalControlFailure",
            "worker_error_message": code,
            "failure": failure,
        }

    def test_every_declared_numerical_control_code_is_typed_and_preserved(self):
        """Catches collapsing actionable conditioning failures into protocol errors."""

        self.assertTrue(hasattr(julia_backend, "JuliaNumericalControlError"))
        error_type = julia_backend.JuliaNumericalControlError
        self.assertEqual(
            julia_backend.NUMERICAL_CONTROL_FAILURE_CODES,
            frozenset(self.CODES),
        )
        for code in self.CODES:
            with self.subTest(code=code):
                policy, details = self._details(code)
                julia_backend._require_worker_resource_identity(details, policy)
                with self.assertRaises(error_type) as raised:
                    julia_backend._raise_worker_failure(details)
                self.assertEqual(raised.exception.failure_code, code)
                self.assertEqual(
                    raised.exception.worker_failure["failure"]["diagnostics"],
                    details["failure"]["diagnostics"],
                )
                self.assertEqual(
                    raised.exception.worker_failure["failure"][
                        "execution_resource_policy"
                    ],
                    policy,
                )

    def test_unknown_control_code_remains_a_generic_backend_failure(self):
        """Catches accidentally widening the typed numerical-control allowlist."""

        policy, details = self._details("UNREVIEWED_NUMERICAL_FAILURE")
        julia_backend._require_worker_resource_identity(details, policy)

        with self.assertRaises(JuliaResponseBackendError) as raised:
            julia_backend._raise_worker_failure(details)

        self.assertIs(type(raised.exception), JuliaResponseBackendError)

    def test_malformed_numerical_control_diagnostics_remain_generic(self):
        """Catches typing incomplete or precision-narrowed control receipts."""

        malformed = {
            "missing": None,
            "nonmapping": "not-an-object",
            "predicted_float": {
                "predicted_reliable_digits": 11.25,
                "required_reliable_digits": "24",
                "asymptotic_preflight_avoided_ode": True,
                "asymptotic_preflight_reason": (
                    "INSUFFICIENT_ASYMPTOTIC_PRECISION"
                ),
            },
            "required_float": {
                "predicted_reliable_digits": "11.25",
                "required_reliable_digits": 24.0,
                "asymptotic_preflight_avoided_ode": True,
                "asymptotic_preflight_reason": (
                    "INSUFFICIENT_ASYMPTOTIC_PRECISION"
                ),
            },
            "nonfinite": {
                "predicted_reliable_digits": "NaN",
                "required_reliable_digits": "24",
                "asymptotic_preflight_avoided_ode": True,
                "asymptotic_preflight_reason": (
                    "INSUFFICIENT_ASYMPTOTIC_PRECISION"
                ),
            },
            "negative_required": {
                "predicted_reliable_digits": "-11.25",
                "required_reliable_digits": "-1",
                "asymptotic_preflight_avoided_ode": True,
                "asymptotic_preflight_reason": (
                    "INSUFFICIENT_ASYMPTOTIC_PRECISION"
                ),
            },
            "digits_not_insufficient": {
                "predicted_reliable_digits": "24",
                "required_reliable_digits": "24",
                "asymptotic_preflight_avoided_ode": True,
                "asymptotic_preflight_reason": (
                    "INSUFFICIENT_ASYMPTOTIC_PRECISION"
                ),
            },
            "nonbool": {
                "predicted_reliable_digits": "11.25",
                "required_reliable_digits": "24",
                "asymptotic_preflight_avoided_ode": 1,
                "asymptotic_preflight_reason": (
                    "INSUFFICIENT_ASYMPTOTIC_PRECISION"
                ),
            },
            "ode_not_avoided": {
                "predicted_reliable_digits": "11.25",
                "required_reliable_digits": "24",
                "asymptotic_preflight_avoided_ode": False,
                "asymptotic_preflight_reason": (
                    "INSUFFICIENT_ASYMPTOTIC_PRECISION"
                ),
            },
            "wrong_reason": {
                "predicted_reliable_digits": "11.25",
                "required_reliable_digits": "24",
                "asymptotic_preflight_avoided_ode": True,
                "asymptotic_preflight_reason": "ADEQUATE",
            },
            "rhs_already_evaluated": {
                "predicted_reliable_digits": "11.25",
                "required_reliable_digits": "24",
                "asymptotic_preflight_avoided_ode": True,
                "asymptotic_preflight_reason": (
                    "INSUFFICIENT_ASYMPTOTIC_PRECISION"
                ),
                "factored_homogeneous_rhs_evaluations": 1,
                "avoided_ode_scope": "factored-homogeneous-gsn/v1",
            },
            "wrong_avoided_scope": {
                "predicted_reliable_digits": "11.25",
                "required_reliable_digits": "24",
                "asymptotic_preflight_avoided_ode": True,
                "asymptotic_preflight_reason": (
                    "INSUFFICIENT_ASYMPTOTIC_PRECISION"
                ),
                "factored_homogeneous_rhs_evaluations": 0,
                "avoided_ode_scope": "raw-homogeneous/v0",
            },
        }
        for label, diagnostics in malformed.items():
            with self.subTest(label=label):
                policy, details = self._details(
                    "INSUFFICIENT_ASYMPTOTIC_PRECISION"
                )
                if diagnostics is None:
                    details["failure"].pop("diagnostics")
                else:
                    details["failure"]["diagnostics"] = diagnostics
                julia_backend._require_worker_resource_identity(details, policy)
                with self.assertRaises(JuliaResponseBackendError) as raised:
                    julia_backend._raise_worker_failure(details)
                self.assertIs(type(raised.exception), JuliaResponseBackendError)

    def test_other_numerical_control_codes_require_nonempty_diagnostics(self):
        """Catches typing recognized controls with no diagnostic evidence."""

        for diagnostics in (None, {}, "not-an-object"):
            with self.subTest(diagnostics=diagnostics):
                policy, details = self._details(
                    "SCATTERING_BASIS_ILL_CONDITIONED"
                )
                if diagnostics is None:
                    details["failure"].pop("diagnostics")
                else:
                    details["failure"]["diagnostics"] = diagnostics
                julia_backend._require_worker_resource_identity(details, policy)
                with self.assertRaises(JuliaResponseBackendError) as raised:
                    julia_backend._raise_worker_failure(details)
                self.assertIs(type(raised.exception), JuliaResponseBackendError)

    def test_each_code_rejects_arbitrary_or_structurally_mutated_diagnostics(self):
        """Catches treating a code label as a substitute for its evidence."""

        for code in self.CODES:
            baseline = self._diagnostics(code)
            mutations = {
                "arbitrary": {"anything": "goes"},
                "missing_field": {
                    key: value
                    for index, (key, value) in enumerate(baseline.items())
                    if index != 0
                },
                "unexpected_field": {**baseline, "unreviewed": True},
            }
            for label, diagnostics in mutations.items():
                with self.subTest(code=code, mutation=label):
                    policy, details = self._details(code)
                    details["failure"]["diagnostics"] = diagnostics
                    julia_backend._require_worker_resource_identity(
                        details, policy
                    )
                    with self.assertRaises(
                        JuliaResponseBackendError
                    ) as raised:
                        julia_backend._raise_worker_failure(details)
                    self.assertIs(
                        type(raised.exception), JuliaResponseBackendError
                    )

    def test_coordinate_stall_receipt_requires_finite_state_evidence(self):
        """Catches a typed stall receipt that cannot locate the failed map."""

        baseline = self._diagnostics("COORDINATE_INVERSION_STALLED")
        mutations = {
            "missing_rejected_steps": "ode_rejected_steps",
            "missing_current_radius": "current_r_re",
            "missing_identity_residual": "coordinate_identity_residual_abs",
        }
        for label, field in mutations.items():
            with self.subTest(label=label):
                policy, details = self._details(
                    "COORDINATE_INVERSION_STALLED"
                )
                diagnostics = copy.deepcopy(baseline)
                diagnostics.pop(field)
                details["failure"]["diagnostics"] = diagnostics
                julia_backend._require_worker_resource_identity(
                    details, policy
                )
                with self.assertRaises(JuliaResponseBackendError):
                    julia_backend._raise_worker_failure(details)

        invalid_values = {
            "ode_rejected_steps": -1,
            "current_r_re": "NaN",
            "current_r_im": "Inf",
            "coordinate_identity_residual_abs": "-1e-25",
        }
        for field, value in invalid_values.items():
            with self.subTest(field=field, value=value):
                policy, details = self._details(
                    "COORDINATE_INVERSION_STALLED"
                )
                diagnostics = copy.deepcopy(baseline)
                diagnostics[field] = value
                details["failure"]["diagnostics"] = diagnostics
                julia_backend._require_worker_resource_identity(
                    details, policy
                )
                with self.assertRaises(JuliaResponseBackendError):
                    julia_backend._raise_worker_failure(details)

    def test_each_code_rejects_a_stage_it_cannot_emit_from(self):
        """Catches relabelling diagnostics as a different pipeline failure."""

        for code in self.CODES:
            with self.subTest(code=code):
                policy, details = self._details(code)
                current = details["failure"]["stage"]
                details["failure"]["stage"] = (
                    "coordinate-inversion"
                    if current != "coordinate-inversion"
                    else "finite-difference"
                )
                julia_backend._require_worker_resource_identity(details, policy)
                with self.assertRaises(JuliaResponseBackendError) as raised:
                    julia_backend._raise_worker_failure(details)
                self.assertIs(type(raised.exception), JuliaResponseBackendError)

    def test_typed_numerical_control_receipt_requires_current_resource_identity(self):
        """Catches trusting diagnostics from a different execution policy."""

        policy, details = self._details(
            "INSUFFICIENT_ASYMPTOTIC_PRECISION", include_identity=False
        )

        with self.assertRaisesRegex(
            JuliaResponseBackendError,
            "execution-resource policy identity mismatch",
        ):
            julia_backend._require_worker_resource_identity(details, policy)


if __name__ == "__main__":
    unittest.main()
