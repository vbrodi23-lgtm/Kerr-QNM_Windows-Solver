from __future__ import annotations

import copy
from dataclasses import replace
from decimal import Decimal, localcontext
import math
import unittest

from tests.test_promoted_horizon_component import (
    FakePromotedBackend,
    _primary_horizon_leaf,
    _promoted_baseline,
)
from windows_solver.response_engine import (
    BOUNDED_ANALYTIC_RESPONSE,
    ComponentResult,
    DecimalComplex,
    DerivativeAuthenticationEvidence,
    PROMOTED_HORIZON_COMPONENT_V2_IDENTITY,
    _validate_promoted_horizon_checkpoint_evidence_for_job,
    run_promoted_horizon_component,
)
from windows_solver.response_uncertainty import (
    ComplexDisk,
    ZeroContainingDiskError,
    exterior_response_disk,
    horizon_response_disk,
)


class PromotedHorizonUncertaintyTests(unittest.TestCase):
    @staticmethod
    def _authenticated_derivative_baseline(job, *, omega=None):
        baseline = _promoted_baseline(
            job,
            **({} if omega is None else {"omega": omega}),
        )
        derivative = baseline.primary_acceptance.derivative
        with localcontext() as context:
            context.prec = 180
            propagated = Decimal("4e-7")
            disagreement = Decimal("6e-7")
            lower_bound = derivative.magnitude() - propagated - disagreement
        authentication = DerivativeAuthenticationEvidence(
            derivative_re=derivative.real,
            derivative_im=derivative.imaginary,
            propagated_error_abs=propagated,
            step_disagreement_abs=disagreement,
            lower_bound_abs=lower_bound,
            selected_step=Decimal("1e-5"),
            axis="real",
        )
        return replace(
            baseline,
            primary_acceptance=replace(
                baseline.primary_acceptance,
                derivative_authentication=authentication,
            ),
        )

    def test_disk_product_quotient_and_inversion_are_conservative(self) -> None:
        left = ComplexDisk(2.0 + 1.0j, 0.1)
        right = ComplexDisk(4.0 - 2.0j, 0.2)
        product = left * right
        quotient = left / right
        inverse = right.inverse()
        self.assertEqual(product.centre, left.centre * right.centre)
        self.assertAlmostEqual(product.radius, abs(left.centre) * 0.2 + abs(right.centre) * 0.1 + 0.02)
        self.assertEqual(quotient.centre, left.centre / right.centre)
        self.assertEqual(inverse.centre, 1.0 / right.centre)
        self.assertGreater(quotient.radius, 0.0)

    def test_non_exact_zero_radius_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "exact"):
            ComplexDisk(1.0 + 0.0j, 0.0)
        exact = ComplexDisk(1.0 + 0.0j, 0.0, exact_zero_radius=True)
        self.assertEqual(exact.radius, 0.0)

    def test_response_helpers_propagate_input_disks(self) -> None:
        exterior = exterior_response_disk(
            coordinate_derivative=ComplexDisk(2.0 + 3.0j, 1.0e-5),
            frequency_derivative=ComplexDisk(10.0 - 2.0j, 2.0e-5),
        )
        horizon = horizon_response_disk(
            horizon_frequency=ComplexDisk(0.1 - 0.02j, 2.0e-11),
            determinant_derivative=ComplexDisk(500.0 - 400.0j, 3.0e-7),
        )
        self.assertEqual(exterior.centre, -((2.0 + 3.0j) / (10.0 - 2.0j)))
        self.assertGreater(exterior.radius, 0.0)
        self.assertGreater(horizon.radius, 0.0)

    def test_zero_containing_denominators_have_typed_failures(self) -> None:
        with self.assertRaises(ZeroContainingDiskError) as caught:
            horizon_response_disk(
                horizon_frequency=ComplexDisk(1.0e-12 + 0.0j, 2.0e-12),
                determinant_derivative=ComplexDisk(1.0 + 0.0j, 1.0e-6),
            )
        self.assertEqual(caught.exception.disk_name, "horizon_frequency")

    def test_promoted_horizon_v2_serializes_a_bounded_positive_radius(self) -> None:
        leaf = _primary_horizon_leaf()
        baseline = self._authenticated_derivative_baseline(leaf.job)
        result = run_promoted_horizon_component(
            leaf.job,
            FakePromotedBackend(leaf.job, baseline),
            primary_predictor=baseline.omega,
        )
        mapping = result.to_mapping()

        self.assertEqual(
            mapping["component_scientific_identity"],
            PROMOTED_HORIZON_COMPONENT_V2_IDENTITY,
        )
        self.assertEqual(
            mapping["response_uncertainty_status"],
            BOUNDED_ANALYTIC_RESPONSE,
        )
        self.assertTrue(mapping["usable"])
        self.assertGreater(mapping["analytic_horizon_evidence"]["response_disk"]["radius"], 0.0)
        self.assertGreater(sum(mapping["error_channels"].values()), 0.0)
        self.assertEqual(
            mapping["analytic_horizon_evidence"]["derivative_radius_provenance"]["step_disagreement_abs"],
            "6E-7",
        )

    def test_promoted_horizon_disk_includes_decimal_to_binary64_rounding(self) -> None:
        leaf = _primary_horizon_leaf()
        derivative = DecimalComplex(
            Decimal("1.0000000000000000000000000000000001"),
            Decimal("0.1000000000000000000000000000000001"),
        )
        baseline = _promoted_baseline(leaf.job, derivative=derivative)
        with localcontext() as context:
            context.prec = 180
            tiny = Decimal("1e-80")
            lower_bound = derivative.magnitude() - tiny - tiny
        authentication = DerivativeAuthenticationEvidence(
            derivative_re=derivative.real,
            derivative_im=derivative.imaginary,
            propagated_error_abs=tiny,
            step_disagreement_abs=tiny,
            lower_bound_abs=lower_bound,
            selected_step=Decimal("1e-5"),
            axis="real",
        )
        baseline = replace(
            baseline,
            primary_acceptance=replace(
                baseline.primary_acceptance,
                derivative_authentication=authentication,
            ),
        )

        result = run_promoted_horizon_component(
            leaf.job,
            FakePromotedBackend(leaf.job, baseline),
            primary_predictor=baseline.omega,
        )
        radius = result.analytic_horizon_evidence[
            "derivative_disk"
        ]["radius"]

        self.assertGreater(radius, 1.0e-30)
        ComponentResult.from_mapping(result.to_mapping())

    def test_deserialization_recomputes_response_disk_and_rejects_understatement(self) -> None:
        leaf = _primary_horizon_leaf()
        baseline = self._authenticated_derivative_baseline(leaf.job)
        mapping = run_promoted_horizon_component(
            leaf.job,
            FakePromotedBackend(leaf.job, baseline),
            primary_predictor=baseline.omega,
        ).to_mapping()
        understated = (
            mapping["analytic_horizon_evidence"]["response_disk"]["radius"]
            * 1.0e-12
        )
        mapping["analytic_horizon_evidence"]["response_disk"]["radius"] = (
            understated
        )
        mapping["error_channels"]["resolution"] = understated

        with self.assertRaisesRegex(ValueError, "horizon response disk"):
            ComponentResult.from_mapping(mapping)

    def test_deserialization_allows_only_two_ulp_cross_platform_radius_replay(self) -> None:
        leaf = _primary_horizon_leaf()
        baseline = self._authenticated_derivative_baseline(leaf.job)
        mapping = run_promoted_horizon_component(
            leaf.job,
            FakePromotedBackend(leaf.job, baseline),
            primary_predictor=baseline.omega,
        ).to_mapping()
        radius = mapping["analytic_horizon_evidence"]["response_disk"][
            "radius"
        ]

        portable = copy.deepcopy(mapping)
        portable_radius = math.nextafter(
            math.nextafter(radius, 0.0), 0.0
        )
        portable["analytic_horizon_evidence"]["response_disk"][
            "radius"
        ] = portable_radius
        portable["error_channels"]["resolution"] = portable_radius
        ComponentResult.from_mapping(portable)

        forged = copy.deepcopy(mapping)
        forged_radius = math.nextafter(portable_radius, 0.0)
        forged["analytic_horizon_evidence"]["response_disk"][
            "radius"
        ] = forged_radius
        forged["error_channels"]["resolution"] = forged_radius
        with self.assertRaisesRegex(ValueError, "horizon response disk"):
            ComponentResult.from_mapping(forged)

    def test_job_validation_rejects_coherently_shifted_horizon_frequency(self) -> None:
        leaf = _primary_horizon_leaf()
        baseline = self._authenticated_derivative_baseline(leaf.job)
        mapping = run_promoted_horizon_component(
            leaf.job,
            FakePromotedBackend(leaf.job, baseline),
            primary_predictor=baseline.omega,
        ).to_mapping()
        evidence = mapping["analytic_horizon_evidence"]
        frequency_mapping = evidence["horizon_frequency_disk"]
        frequency = ComplexDisk(
            complex(
                frequency_mapping["centre"]["real"] + 1.0e-3,
                frequency_mapping["centre"]["imaginary"],
            ),
            frequency_mapping["radius"],
        )
        derivative_mapping = evidence["derivative_disk"]
        derivative = ComplexDisk(
            complex(
                derivative_mapping["centre"]["real"],
                derivative_mapping["centre"]["imaginary"],
            ),
            derivative_mapping["radius"],
        )
        response = horizon_response_disk(
            horizon_frequency=frequency,
            determinant_derivative=derivative,
        )
        evidence["horizon_frequency_disk"] = frequency.to_mapping()
        evidence["response_disk"] = response.to_mapping()
        mapping["response"] = response.to_mapping()["centre"]
        mapping["closed_form_response"] = response.to_mapping()["centre"]
        mapping["error_channels"]["resolution"] = response.radius
        restored = ComponentResult.from_mapping(mapping)

        with self.assertRaisesRegex(ValueError, "horizon frequency disk"):
            _validate_promoted_horizon_checkpoint_evidence_for_job(
                restored, leaf.job
            )

    def test_zero_containing_horizon_disk_is_typed_unusable(self) -> None:
        leaf = _primary_horizon_leaf()
        horizon_radius = 1.0 + math.sqrt(1.0 - leaf.job.spin * leaf.job.spin)
        omega_h = leaf.job.spin / (2.0 * horizon_radius)
        baseline = self._authenticated_derivative_baseline(
            leaf.job,
            omega=complex(leaf.job.mode.m * omega_h, 0.0),
        )
        result = run_promoted_horizon_component(
            leaf.job,
            FakePromotedBackend(leaf.job, baseline),
            primary_predictor=baseline.omega,
        )
        mapping = result.to_mapping()

        self.assertFalse(mapping["usable"])
        self.assertIsNone(mapping["response"])
        self.assertEqual(mapping["status"], "DERIVATIVE_UNRESOLVED")
        self.assertEqual(
            mapping["response_uncertainty_status"],
            "UNBOUNDED_ANALYTIC_RESPONSE",
        )


if __name__ == "__main__":
    unittest.main()
