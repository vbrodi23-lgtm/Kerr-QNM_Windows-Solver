from __future__ import annotations

import re
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SOLUTIONS_SOURCE = REPO_ROOT / (
    "src/windows_solver/data/julia/GeneralizedSasakiNakamura.jl/src/"
    "Homogeneous/Solutions.jl"
)
JULIA_SPEC = REPO_ROOT / (
    "src/windows_solver/data/julia/GeneralizedSasakiNakamura.jl/test/"
    "scaled_scattering_spec.jl"
)


class RegularisedGsnScatteringSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = SOLUTIONS_SOURCE.read_text(encoding="utf-8")
        cls.spec = JULIA_SPEC.read_text(encoding="utf-8")

    def test_exact_representation_and_convention_identities_are_present(self) -> None:
        for identity in (
            "factored-plane-wave-gsn/v1",
            "scaled-factored-horizon-basis/v1",
            "cinc-over-cref-minus-reflectivity/v1",
            "scaled-basis-frobenius-condition/not-a-bound/v1",
            "empirical-cref-error/not-a-bound/v1",
        ):
            self.assertIn(identity, self.source)
        self.assertIn("scattering_column_convention", self.source)
        self.assertIn("determinant_convention", self.source)
        self.assertRegex(
            self.source, r"SCATTERING_CHART_SAFETY_FACTOR\s*=\s*64\b"
        )

    def test_common_basis_consumes_coordinate_bound_endpoints(self) -> None:
        section = self._function("build_common_horizon_basis")
        self.assertIn("FactoredInitialCondition{T}", section)
        self.assertIn("ingoing.regularity.rho_endpoint", section)
        self.assertIn("ingoing.regularity.r_endpoint", section)
        self.assertIn("HORIZON_INGOING", section)
        self.assertIn("HORIZON_OUTGOING", section)
        self.assertIn("change_carrier(", section)
        self.assertIn("carrier_change_diagnostics(", section)
        carrier_validation = self._function("_assert_scattering_carrier")
        self.assertIn("assert_wave_number_matches_leg(", carrier_validation)
        self.assertIn("INVALID_SCATTERING_INPUT", carrier_validation)
        self.assertIn("_same_remainder_contract(", section)
        self.assertIn("_canonical_remainder_contract(ingoing.contract)", section)
        self.assertIn("ingoing.evaluation.order == outgoing.evaluation.order", section)
        for evidence_field in (
            "remainder_norm",
            "remainder_derivative_norm",
            "carrier_magnitude",
            "relative_X_reconstruction_error",
            "relative_Xrho_reconstruction_error",
            "Xrho_backward_residual",
            "carrier_operation_scale",
            "reconstruction_tolerance",
        ):
            self.assertIn(evidence_field, section)
        reconstruction_gate = re.search(
            r"maximum_reconstruction_error\s*=\s*max\((?P<body>.*?)\)",
            section,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(reconstruction_gate)
        gate_body = reconstruction_gate.group("body")
        self.assertIn("relative_X_reconstruction_error", gate_body)
        self.assertIn("Xrho_backward_residual", gate_body)
        self.assertNotIn("relative_Xrho_reconstruction_error", gate_body)
        for forbidden in (
            "gsn_branch_convention(",
            "determine_sign(",
            "contour_angle(",
            "angle(",
            "cis(",
            "r_from_rho(",
        ):
            self.assertNotIn(forbidden, section)

    def test_scaled_solve_scales_columns_independently_and_undoes_exactly(self) -> None:
        section = self._function("_solve_scaled_factored_scattering_unchecked")
        for contract in (
            "column_norm_1 = _state_norm",
            "column_norm_2 = _state_norm",
            "scaled_a = basis.column_1.Y / column_norm_1",
            "scaled_c = basis.column_1.Yrho / column_norm_1",
            "scaled_b = basis.column_2.Y / column_norm_2",
            "scaled_d = basis.column_2.Yrho / column_norm_2",
            "Cref = z1 / column_norm_1",
            "Cinc = z2 / column_norm_2",
        ):
            self.assertIn(contract, section)
        self.assertNotRegex(section, r"(?:target|state)\s*/=" )
        self.assertRegex(
            self.source,
            r"function solve_scaled_factored_scattering\(\s*"
            r"target::FactoredEndpointState\{T\},\s*"
            r"target_carrier::PlaneWaveCarrier\{T\}",
        )
        self.assertIn("_same_carrier(target_carrier, basis.common_carrier)", self.source)
        self.assertNotRegex(
            self.source,
            r"function solve_scaled_factored_scattering\(\s*"
            r"target::FactoredEndpointState(?:\{T\})?\s*,\s*"
            r"basis::CommonCarrierHorizonBasis",
        )

    def test_matching_reconstruction_residual_is_first_class(self) -> None:
        self.assertIn("matching_reconstruction_residual::T", self.source)
        solve = self._function("_solve_scaled_factored_scattering_unchecked")
        self.assertIn("reconstructed_endpoint = FactoredEndpointState{T}", solve)
        self.assertIn("matching_reconstruction_residual =", solve)
        estimate = self._function("estimate_cref_error")
        self.assertIn(
            "coefficients.diagnostics.matching_reconstruction_residual",
            estimate,
        )

    def test_condition_backward_error_and_cramer_bridge_are_explicit(self) -> None:
        self.assertIn("function unscaled_cramer_scattering_coefficients", self.source)
        self.assertIn("condition_frobenius::T", self.source)
        self.assertIn("backward_error::T", self.source)
        solve = self._function("_solve_scaled_factored_scattering_unchecked")
        self.assertIn("scaled_basis_determinant", solve)
        self.assertIn("_stable_matrix_two_norm", solve)
        self.assertIn("legacy_relative_disagreement_cref", solve)
        self.assertIn("legacy_relative_disagreement_cinc", solve)

    def test_cramer_disagreement_is_scale_normalised_before_subtraction(self) -> None:
        disagreement = self._function("_relative_scattering_disagreement")
        self.assertIn("left / scale", disagreement)
        self.assertIn("right / scale", disagreement)
        self.assertNotIn("abs(left - right)", disagreement)

    def test_legacy_cramer_comparator_is_optional_to_the_scaled_solve(self) -> None:
        diagnostics = self.source[
            self.source.index("struct BasisSolveDiagnostics") :
            self.source.index("struct ScatteringCoefficients")
        ]
        for contract in (
            "legacy_comparator_available::Bool",
            "legacy_comparator_failure_reason::Union{Nothing,ScatteringFailureReason}",
            "legacy_Cref::Union{Nothing,Complex{T}}",
            "legacy_Cinc::Union{Nothing,Complex{T}}",
            "legacy_relative_disagreement_cref::Union{Nothing,T}",
            "legacy_relative_disagreement_cinc::Union{Nothing,T}",
        ):
            self.assertIn(contract, diagnostics)
        solve = self._function("_solve_scaled_factored_scattering_unchecked")
        self.assertRegex(solve, r"legacy_diagnostics\s*=\s*try")
        self.assertIn("NONFINITE_SCATTERING_DATA", solve)
        self.assertIn("SCATTERING_BASIS_ILL_CONDITIONED", solve)
        self.assertIn("rethrow()", solve)
        self.assertIn("legacy_diagnostics === nothing", solve)
        comparator_try = solve[
            solve.index("legacy_diagnostics = try") : solve.index("catch error")
        ]
        self.assertIn("_relative_scattering_disagreement", comparator_try)
        self.assertIn("_assert_scattering_real", comparator_try)

    def test_chart_is_strict_and_has_no_raw_fallback(self) -> None:
        assess = self._function("assess_horizon_determinant_chart")
        self.assertIn("margin > one(T)", assess)
        self.assertIn("Cinc / Cref - typed_reflectivity", assess)
        production = self._function("evaluate_normalised_horizon_determinant")
        self.assertIn("SCATTERING_CHART_ILL_CONDITIONED", production)
        self.assertIn("assessment.normalised_determinant", production)
        self.assertNotIn("raw_scattering_determinant", production)
        self.assertNotRegex(production, r"(?:fallback|catch|else).*raw")

    def test_exact_root_cancellation_diagnostic_saturates_explicitly(self) -> None:
        assessment = self.source[
            self.source.index("struct DeterminantChartAssessment") :
            self.source.index("struct DeterminantChartEvaluation")
        ]
        self.assertIn("raw_cancellation_ratio_saturated::Bool", assessment)
        self.assertIn("function _finite_scattering_ratio", self.source)
        chart = self._function("assess_horizon_determinant_chart")
        self.assertIn("_finite_scattering_ratio(", chart)
        self.assertIn("(cinc_abs, reflected_cref_abs)", chart)
        self.assertNotIn("cinc_abs + abs(typed_reflectivity * Cref)", chart)
        self.assertIn("raw_cancellation_ratio_saturated", chart)
        self.assertIn("exact-root cancellation saturation", self.spec)

    def test_typed_failure_taxonomy_and_bigfloat_scope_are_present(self) -> None:
        for reason in (
            "INVALID_SCATTERING_INPUT",
            "SCATTERING_PRECISION_MISMATCH",
            "NONFINITE_SCATTERING_DATA",
            "SCATTERING_BASIS_ILL_CONDITIONED",
            "SCATTERING_CHART_ILL_CONDITIONED",
        ):
            self.assertIn(reason, self.source)
        self.assertIn("struct ScatteringExtractionError", self.source)
        self.assertIn("setprecision(BigFloat, precision_bits)", self.source)
        self.assertIn("precision_bits::Int", self.source)
        self.assertIn(
            "horizon initial conditions do not share one exact real component type",
            self.source,
        )
        self.assertIn(
            "determinant-chart inputs do not share one exact real component type",
            self.source,
        )
        self.assertNotIn('big"', self.spec)
        self.assertIn('parse(BigFloat, "1e60")', self.spec)

    def test_carrier_validation_authenticates_q_and_match_log(self) -> None:
        carrier_validation = self._function("_assert_scattering_carrier")
        self.assertIn("canonical_carrier =", carrier_validation)
        self.assertIn("_same_carrier(carrier, canonical_carrier)", carrier_validation)
        self.assertIn("forged carrier q and match log rejection", self.spec)

    def test_backward_error_and_reconstruction_preserve_scaled_arithmetic(self) -> None:
        self.assertIn("function _scale_normalised_backward_error", self.source)
        solve = self._function("_solve_scaled_factored_scattering_unchecked")
        self.assertIn("z1 * scaled_a + z2 * scaled_b", solve)
        self.assertIn("z1 * scaled_c + z2 * scaled_d", solve)
        self.assertIn("hypot(abs(z1), abs(z2))", solve)
        self.assertIn(
            "scaled_a, scaled_b, scaled_c, scaled_d", solve
        )
        self.assertIn("_scale_normalised_backward_error(", solve)
        self.assertNotIn("hypot(abs(Cref), abs(Cinc))", solve)
        self.assertNotIn("basis_two_norm * coefficient_norm", solve)

    def test_source_has_no_known_duplicate_parse_patterns(self) -> None:
        self.assertNotRegex(
            self.source,
            r"throw\s*\(\s*_scattering_error\s*\(\s*throw\s*\(\s*"
            r"_scattering_error",
        )
        self.assertNotRegex(
            self.source,
            r"positive\s*=\s*true\s*,\s*positive\s*=\s*true",
        )
        self.assertNotRegex(
            self.source,
            r"inputs\.series_disagreement\s*,\s*"
            r"inputs\.series_disagreement\s*,",
        )

    def test_new_path_contains_no_propagated_state_normalisation(self) -> None:
        start = self.source.index("const HOMOGENEOUS_REPRESENTATION_ID")
        end = self.source.index("# First-order non-linear ODE form", start)
        section = self.source[start:end]
        self.assertNotRegex(section, r"maximum\s*\(\s*abs\.\(")
        self.assertNotRegex(section, r"(?:target|propagated|state)\s*\./?=")
        self.assertNotIn("solve(", section)

    def test_julia_spec_covers_required_equivalence_matrix(self) -> None:
        for contract in (
            "widely separated column norms",
            "BigFloat origin precision",
            "unscaled Cramer comparator",
            "matching reconstruction residual",
            "strict chart safety boundary",
            "raw and normalised determinant equivalence",
            "near-dependent basis rejection",
            "forged target carrier rejection",
            "common-carrier horizon basis",
            "non-diagonal analytic condition estimate",
            "scaled solve survives unavailable legacy comparator",
            "table-driven coefficient-scale and phase recovery",
        ):
            self.assertIn(contract, self.spec)
        common_basis_start = self.spec.index(
            '@testset "common-carrier horizon basis"'
        )
        common_basis = self.spec[common_basis_start:]
        self.assertIn("stable_horizon_geometry", common_basis)
        self.assertIn("geometry.omega_horizon", common_basis)
        self.assertNotIn("KERR_SCATTERING.omega_horizon", common_basis)

    def _function(self, name: str) -> str:
        match = re.search(
            rf"function {re.escape(name)}\b(?P<body>.*?)(?=\nfunction |\nend\n\n# First-order)",
            self.source,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(match, f"missing function {name}")
        return match.group(0)


if __name__ == "__main__":
    unittest.main()
