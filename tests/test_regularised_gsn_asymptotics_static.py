from __future__ import annotations

import re
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
COEFFICIENTS_SOURCE = REPO_ROOT / (
    "src/windows_solver/data/julia/GeneralizedSasakiNakamura.jl/src/"
    "Homogeneous/AsymptoticExpansionCoefficients.jl"
)
KERR_SOURCE = REPO_ROOT / (
    "src/windows_solver/data/julia/GeneralizedSasakiNakamura.jl/src/"
    "Homogeneous/Kerr.jl"
)
INITIAL_CONDITIONS_SOURCE = REPO_ROOT / (
    "src/windows_solver/data/julia/GeneralizedSasakiNakamura.jl/src/"
    "Homogeneous/InitialConditions.jl"
)
PACKAGE_ENTRYPOINT_SOURCE = REPO_ROOT / (
    "src/windows_solver/data/julia/GeneralizedSasakiNakamura.jl/src/"
    "GeneralizedSasakiNakamura.jl"
)
JULIA_TEST_SOURCE = REPO_ROOT / (
    "src/windows_solver/data/julia/GeneralizedSasakiNakamura.jl/test/"
    "runtests.jl"
)


class RegularisedGsnAsymptoticsSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = COEFFICIENTS_SOURCE.read_text(encoding="utf-8")
        cls.kerr_source = KERR_SOURCE.read_text(encoding="utf-8")
        cls.initial_conditions_source = INITIAL_CONDITIONS_SOURCE.read_text(
            encoding="utf-8"
        )
        cls.package_entrypoint_source = PACKAGE_ENTRYPOINT_SOURCE.read_text(
            encoding="utf-8"
        )
        cls.julia_test_source = JULIA_TEST_SOURCE.read_text(encoding="utf-8")

    def assert_source_contains(self, needle: str) -> None:
        self.assertTrue(needle in self.source, f"missing source contract: {needle}")

    def assert_source_omits(self, needle: str) -> None:
        self.assertFalse(needle in self.source, f"forbidden source contract remains: {needle}")

    def test_production_coefficient_state_is_request_local_and_typed(self) -> None:
        source = self.source
        self.assert_source_omits("_cached_")
        self.assert_source_omits("Vector{_DEFAULTDATATYPE}")
        self.assert_source_omits("Vector{ComplexF64}")
        self.assertNotRegex(source, r"\b(?:sum|ans)\s*=\s*0\.0\b")
        self.assert_source_contains("struct SeriesKey{T")
        self.assert_source_contains("precision_bits::Int")
        self.assert_source_contains("struct TypedTaylorWorkspace{T")
        self.assert_source_contains("Vector{Complex{T}}")
        self.assert_source_contains("struct RecurrenceEvidence{T")
        self.assert_source_contains("struct AsymptoticSeries{T")
        self.assert_source_contains("struct AsymptoticSeriesBundle{T")

    def test_infinity_recurrence_removes_explicit_omega_poles(self) -> None:
        source = self.source
        recurrence = re.search(
            r"function _infinity_recurrence_coefficient\b(?P<body>.*?)\nend",
            source,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(recurrence)
        body = recurrence.group("body")
        self.assertIn("omega_power", body)
        self.assertIn("Qcoeffs[k + 2]", body)
        self.assertIn("Pcoeffs[k + 1]", body)
        self.assertIn("2 * sigma", body)
        self.assertNotRegex(body, r"/\s*\(?\s*(?:key\.)?(?:omega|omega_power)")
        self.assert_source_contains("build_infinity_recurrence_from_zero")
        self.assert_source_contains("use_explicit_low_orders=false")

    def test_exact_singularity_guards_and_horizon_denominators_are_named(self) -> None:
        source = self.source
        self.assert_source_contains("PHYSICAL_SINGULAR_LIMIT")
        self.assert_source_contains("ALGEBRAIC_REPRESENTATION_SINGULAR")
        self.assertIn("function stable_horizon_geometry", self.kerr_source)
        self.assertIn(
            "delta_squared = (one(T) - a) * (one(T) + a)",
            self.kerr_source,
        )
        self.assertIn("delta = sqrt(delta_squared)", self.kerr_source)
        self.assert_source_contains("geometry = stable_horizon_geometry(key.a)")
        self.assert_source_contains("delta = geometry.delta")
        self.assert_source_contains("rplus = geometry.rplus")
        self.assert_source_contains("geometry.omega_horizon")
        self.assert_source_contains("nT + 2 * imaginary_unit * rplus * p_horizon / delta")
        self.assert_source_contains("nT - 2 * imaginary_unit * rplus * p_horizon / delta")
        self.assert_source_contains("lambda + typed_integer(T, 2)")
        self.assert_source_contains("Eplus")
        self.assert_source_contains("Eminus")

    def test_horizon_denominator_cancellation_feeds_recurrence_evidence(self) -> None:
        source = self.source
        denominator_start = source.index("function _horizon_denominator")
        denominator_end = source.index(
            "\nfunction _build_horizon_recurrence", denominator_start
        )
        denominator = source[denominator_start:denominator_end]
        recurrence_end = source.index(
            "\nfunction build_asymptotic_series", denominator_end
        )
        recurrence = source[denominator_end:recurrence_end]

        self.assertIn(
            "denominator_scale = abs(nT^2) + abs(carrier_coupling_term)",
            denominator,
        )
        self.assertIn("return denominator, denominator_scale", denominator)
        self.assertIn(
            "denominator, denominator_scale = _horizon_denominator",
            recurrence,
        )
        self.assertRegex(
            recurrence,
            r"_cancellation_metrics\(\s*T,\s*denominator_scale,\s*"
            r"abs\(denominator\),\s*key\.precision_bits\s*\)",
        )
        self.assertIn(
            "max(chart_digits_lost, denominator_cancellation_digits)",
            recurrence,
        )
        self.assertRegex(
            recurrence,
            r"_recurrence_evidence\([\s\S]*?denominator,\s*"
            r"denominator_scale,\s*value,",
        )

    def test_precision_contract_rejects_float64_upgrades(self) -> None:
        source = self.source
        self.assert_source_contains("PRECISION_MISMATCH")
        self.assert_source_contains("cannot be promoted into purported high-precision evidence")
        self.assert_source_contains("_with_request_precision")
        self.assertRegex(
            source,
            r"function build_asymptotic_series_bundle\b[\s\S]*?precision_bits::Int",
        )

    def test_three_way_series_evaluation_is_typed_and_independent(self) -> None:
        source = self.source
        self.assert_source_contains("struct SeriesEvaluation{T")
        self.assert_source_contains("key::SeriesKey{T}")
        for field in (
            "series_eval_horner::Complex{T}",
            "series_eval_compensated::Complex{T}",
            "series_eval_alternate::Complex{T}",
            "series_evaluation_spread::T",
            "series_evaluation_digits_lost::T",
            "last_term_magnitude::T",
            "last_term_total_ratio::T",
            "series_derivative_horner::Complex{T}",
            "series_derivative_compensated::Complex{T}",
            "series_derivative_alternate::Complex{T}",
            "derivative_evaluation_spread::T",
            "derivative_evaluation_digits_lost::T",
            "derivative_last_term_magnitude::T",
            "derivative_last_term_total_ratio::T",
            "maximum_recurrence_cancellation_factor::T",
            "recurrence_digits_lost::T",
            "estimate_kind::String",
        ):
            self.assert_source_contains(field)
        self.assert_source_contains("function evaluate_asymptotic_series(")
        self.assert_source_contains("function evaluate_infinity_asymptotic_series(")
        self.assert_source_contains("function evaluate_horizon_asymptotic_series(")
        self.assert_source_contains("function _horner_value_and_derivative(")
        self.assert_source_contains("function _componentwise_neumaier(")
        self.assert_source_contains("sort!(alternate_value_terms; by=abs)")
        self.assert_source_contains("sort!(alternate_derivative_terms; by=abs)")
        self.assert_source_contains("floatmin(T)")
        self.assert_source_contains("dz_dr")

    def test_maximum_recurrence_cancellation_factor_is_carried_and_validated(
        self,
    ) -> None:
        source = self.source
        self.assertGreaterEqual(
            source.count("maximum_recurrence_cancellation_factor::T"), 2
        )
        maximum_factor = re.search(
            r"function _maximum_recurrence_cancellation_factor\b"
            r"(?P<body>.*?)\nend",
            source,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(maximum_factor)
        body = maximum_factor.group("body")
        self.assertIn("for coefficient_order in 0:order", body)
        self.assertIn(".cancellation_factor", body)
        self.assert_source_contains(
            "expected_recurrence_factor = "
            "_maximum_recurrence_cancellation_factor("
        )
        self.assertRegex(
            source,
            r"evaluation\.maximum_recurrence_cancellation_factor\s*==\s*"
            r"expected_recurrence_factor",
        )
        self.assertRegex(
            source,
            r"maximum_recurrence_cancellation_factor\s*=\s*"
            r"evaluation\.maximum_recurrence_cancellation_factor",
        )

    def test_preflight_requires_the_exact_full_spectral_series_key(self) -> None:
        source = self.source
        key_match = re.search(
            r"function _series_keys_match_exactly\b(?P<body>.*?)\nend",
            source,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(key_match)
        body = key_match.group("body")
        for field in (
            "s",
            "m",
            "a",
            "omega",
            "lambda",
            "family",
            "max_order",
            "precision_bits",
        ):
            self.assertIn(f"left.{field}", body)
            self.assertIn(f"right.{field}", body)
        self.assert_source_contains(
            "_series_keys_match_exactly(evaluation.key, key)"
        )
        self.assert_source_contains(
            "evaluation spectral key differs from the requested series key"
        )

    def test_empirical_preflight_uses_exact_precision_and_margin_contract(self) -> None:
        source = self.source
        self.assert_source_contains("struct AsymptoticConditioningAssessment{T")
        for field in (
            "adequate::Bool",
            "precision_bits::Int",
            "arithmetic_decimal_digits::T",
            "required_digits::T",
            "safety_margin_digits::T",
            "maximum_recurrence_digits_lost::T",
            "maximum_recurrence_cancellation_factor::T",
            "maximum_series_evaluation_spread::T",
            "maximum_series_evaluation_digits_lost::T",
            "maximum_last_term_ratio::T",
            "maximum_truncation_digits_lost::T",
            "effective_digits_lost::T",
            "predicted_reliable_digits::T",
        ):
            self.assert_source_contains(field)
        self.assert_source_contains("function assess_asymptotic_preflight(")
        self.assert_source_contains(
            '"empirical-three-way-series-conditioning/not-a-bound/v1"'
        )
        self.assert_source_contains("typed_integer(T, series.key.precision_bits)")
        self.assert_source_contains("safety_margin_digits = typed_integer(T, 8)")
        self.assert_source_contains('"INSUFFICIENT_ASYMPTOTIC_PRECISION"')
        self.assert_source_contains("predicted_reliable_digits >= required_digits")

    def test_evaluation_guards_mixed_and_physical_singular_inputs(self) -> None:
        source = self.source
        self.assert_source_contains("function evaluate_infinity_asymptotic_series")
        self.assert_source_contains("function evaluate_horizon_asymptotic_series")
        infinity_start = source.index("function evaluate_infinity_asymptotic_series")
        infinity_end = source.index(
            "\nfunction evaluate_horizon_asymptotic_series", infinity_start
        )
        infinity = source[infinity_start:infinity_end]
        self.assertIn("iszero(series.key.omega)", infinity)
        self.assertIn("PHYSICAL_SINGULAR_LIMIT", infinity)
        self.assert_source_contains("evaluation family differs from the series key")
        self.assert_source_contains("evaluation precision differs from the series key")
        self.assert_source_contains("mixed-precision series evaluation inputs")
        self.assert_source_contains("mixed evaluation and series preflight inputs")

        self.assertIn("omega_r = _assert_value", infinity)
        self.assertIn("iszero(omega_r)", infinity)
        self.assertIn("inv(omega_r)", infinity)
        omega_r = source.index("omega_r = _assert_value", infinity_start)
        zero_guard = source.index("iszero(omega_r)", omega_r)
        inverse = source.index("inv(omega_r)", zero_guard)
        self.assertLess(omega_r, zero_guard)
        self.assertLess(zero_guard, inverse)
        self.assertNotIn("inv(key.omega * typed_r)", infinity)
        self.assertIn("ALGEBRAIC_REPRESENTATION_SINGULAR", infinity)
        self.assertIn("underflowed to zero before inversion", infinity)

    def test_legacy_initial_condition_accumulators_do_not_narrow(self) -> None:
        source = self.initial_conditions_source
        self.assertNotRegex(source, r"\bans\s*=\s*0\.0\b")
        self.assertGreaterEqual(source.count("ans = zero("), 4)

    def test_factored_endpoint_api_is_typed_and_complete_for_all_branches(
        self,
    ) -> None:
        source = self.initial_conditions_source
        for contract in (
            "struct RemainderRegularityEvidence{T",
            "branch::CarrierKind",
            "rho_endpoint::T",
            "r_endpoint::Complex{T}",
            "finite::Bool",
            "remainder_norm::T",
            "remainder_derivative_norm::T",
            "carrier_magnitude::T",
            "relative_X_reconstruction_error::T",
            "relative_Xrho_reconstruction_error::T",
            "Xrho_backward_residual::T",
            "carrier_operation_scale::T",
            "reconstruction_tolerance::T",
            "struct FactoredInitialCondition{T",
            "state::FactoredEndpointState{T}",
            "carrier::PlaneWaveCarrier{T}",
            "evaluation::SeriesEvaluation{T}",
            "regularity::RemainderRegularityEvidence{T}",
            "contract::RegularRemainderContract",
        ):
            self.assertIn(contract, source)

        for function_name in (
            "factored_infinity_outgoing_initialconditions",
            "factored_horizon_ingoing_initialconditions",
            "factored_horizon_outgoing_initialconditions",
            "legacy_raw_infinity_outgoing_rho_initialconditions",
            "legacy_raw_horizon_ingoing_rho_initialconditions",
            "legacy_raw_horizon_outgoing_rho_initialconditions",
        ):
            self.assertIn(f"function {function_name}(", source)
            self.assertIn(function_name, self.package_entrypoint_source)

    def test_factored_endpoint_state_is_the_batch_horner_remainder(self) -> None:
        source = self.initial_conditions_source
        builder = re.search(
            r"function _factored_endpoint_initialconditions\b"
            r"(?P<body>.*?)\nend",
            source,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(builder)
        body = builder.group("body")
        self.assertIn("evaluation.series_eval_horner", body)
        self.assertIn("evaluation.series_derivative_horner", body)
        self.assertIn("FactoredEndpointState{T}", body)
        self.assertIn("tangent * radial_factor", body)
        self.assertNotIn("fansatz(", body)
        self.assertNotIn("gansatz(", body)
        self.assertNotIn("coefficient_at_", body)
        self.assertNotRegex(body, r"state\s*=.*(?:phase|carrier_value)")
        self.assertNotRegex(body, r"(?:abs|maximum)\s*\(\s*state\.Y")

    def test_endpoint_precision_and_canonical_contour_ownership_are_explicit(
        self,
    ) -> None:
        source = self.initial_conditions_source
        self.assertIn("function _with_endpoint_precision(", source)
        self.assertIn("setprecision(BigFloat, precision_bits)", source)
        self.assertIn("series.key.precision_bits", source)
        self.assertIn("infinity_contour_tangent(convention)", source)
        self.assertIn("horizon_contour_tangent(convention)", source)
        self.assertNotIn("determine_sign", source)
        self.assertNotRegex(source, r"\bangle\s*\(")
        self.assertNotRegex(source, r"\bcis\s*\(")
        self.assertNotRegex(source, r"\bbeta\b")

    def test_endpoint_reconstruction_uses_independent_raw_rho_formulas(
        self,
    ) -> None:
        source = self.initial_conditions_source
        raw_builder = re.search(
            r"function _legacy_raw_rho_initialconditions\b"
            r"(?P<body>.*?)\nend",
            source,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(raw_builder)
        raw_body = raw_builder.group("body")
        self.assertIn("legacy_phase", raw_body)
        self.assertIn("carrier_sign * imaginary_unit * wave_number", raw_body)
        self.assertIn("tangent * legacy_phase", raw_body)
        self.assertNotIn("reconstruct_state", raw_body)
        self.assertNotIn("carrier_value", raw_body)

        evidence_builder = re.search(
            r"function _regularity_evidence\b(?P<body>.*?)\nend",
            source,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(evidence_builder)
        evidence_body = evidence_builder.group("body")
        self.assertIn("reconstruct_state", evidence_body)
        self.assertIn("_relative_reconstruction_error", evidence_body)
        self.assertIn("_Xrho_backward_residual", evidence_body)
        self.assertIn("_carrier_operation_scale", evidence_body)
        self.assertIn("carrier_value", evidence_body)

    def test_endpoint_scale_aware_reconstruction_gate_is_load_bearing(
        self,
    ) -> None:
        source = self.initial_conditions_source
        self.assertIn("reconstruction_tolerance::T", source)
        self.assertIn("carrier_operation_scale::T", source)
        self.assertIn("Xrho_backward_residual::T", source)
        self.assertIn("function _carrier_operation_scale", source)
        self.assertIn("function _scale_aware_reconstruction_tolerance", source)
        self.assertIn("min(sqrt(eps(T))", source)
        self.assertIn("T(256) * eps(T) * carrier_operation_scale", source)
        self.assertIn("function _Xrho_backward_residual", source)
        self.assertIn("abs(A * state.Yrho)", source)
        self.assertIn("abs(A * q * state.Y)", source)
        self.assertIn("abs(legacy.Xrho)", source)
        self.assertIn("function _assert_reconstruction_within_tolerance", source)
        self.assertIn("ALGEBRAIC_REPRESENTATION_SINGULAR", source)

        gate = re.search(
            r"function _assert_reconstruction_within_tolerance\b"
            r"(?P<body>.*?)\nend",
            source,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(gate)
        gate_body = gate.group("body")
        self.assertIn("relative_X_error", gate_body)
        self.assertIn("Xrho_backward_residual", gate_body)
        self.assertNotIn("relative_Xrho_error", gate_body)

    def test_endpoint_radius_is_derived_from_a_callable_witness(self) -> None:
        source = self.initial_conditions_source
        self.assertIn("function _endpoint_radius_from_witness", source)
        self.assertIn("applicable(radius_from_rho, rho)", source)
        self.assertIn("radius_from_rho(rho)", source)
        self.assertIn("radius witness result", source)

        builder = re.search(
            r"function _factored_endpoint_initialconditions\b"
            r"(?P<body>.*?)\nend",
            source,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(builder)
        body = builder.group("body")
        self.assertIn("radius_from_rho", body)
        self.assertIn("_endpoint_radius_from_witness", body)
        self.assertNotIn("r::Union{T,Complex{T}}", body)

        for function_name in (
            "factored_infinity_outgoing_initialconditions",
            "factored_horizon_ingoing_initialconditions",
            "factored_horizon_outgoing_initialconditions",
        ):
            signature = re.search(
                rf"function {function_name}\(\n(?P<body>.*?)\n\)",
                source,
                flags=re.DOTALL,
            )
            self.assertIsNotNone(signature)
            self.assertIn("radius_from_rho", signature.group("body"))
            self.assertNotRegex(signature.group("body"), r"(?m)^\s*r::")

    def test_horizon_location_uses_stable_central_geometry(self) -> None:
        source = self.initial_conditions_source
        self.assertIn("function _assert_endpoint_location", source)
        self.assertIn("stable_horizon_geometry(key.a)", source)
        self.assertIn("geometry.rplus", source)
        self.assertIn("geometry.omega_horizon", source)
        self.assertNotIn("r_plus(key.a)", source)
        self.assertNotIn("omega_horizon(key.a)", source)
        self.assertIn(
            "exact horizon radius r=r_plus is incompatible with a finite rho endpoint",
            source,
        )

        builder = re.search(
            r"function _factored_endpoint_initialconditions\b"
            r"(?P<body>.*?)\nend",
            source,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(builder)
        body = builder.group("body")
        self.assertIn("_assert_endpoint_location", body)
        self.assertIn("_assert_reconstruction_within_tolerance", body)

    def test_horizon_radial_factor_uses_product_geometry_near_rplus(self) -> None:
        self.assertIn("rminus = a^2 / rplus", self.kerr_source)
        self.assertIn("rminus=rminus", self.kerr_source)

        source = self.initial_conditions_source
        radial_factor = re.search(
            r"function _endpoint_radial_factor\b"
            r"(?P<body>.*?)\nend",
            source,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(radial_factor)
        body = radial_factor.group("body")
        self.assertIn("kind::CarrierKind", body)
        self.assertIn("kind === INFINITY_OUTGOING", body)
        self.assertIn("Delta(key.a, r)", body)
        self.assertIn("stable_horizon_geometry(key.a)", body)
        self.assertIn("(r - rplus) * (r - rminus)", body)
        self.assertIn('"stable horizon Delta product"', body)
        self.assertGreaterEqual(
            source.count("_endpoint_radial_factor("), 3
        )

        julia_tests = self.julia_test_source
        self.assertIn(
            'testset "horizon radial factor avoids near-rplus cancellation"',
            julia_tests,
        )
        self.assertIn("high_precision_oracle", julia_tests)
        self.assertIn("direct_delta_factor", julia_tests)
        self.assertIn(
            "abs(stable_factor - high_precision_oracle) <",
            julia_tests,
        )

    def test_endpoint_argument_error_translation_is_operation_classified(self) -> None:
        source = self.initial_conditions_source
        self.assertIn("function _translate_endpoint_argument_error", source)
        translator = re.search(
            r"function _translate_endpoint_argument_error\b"
            r"(?P<body>.*?)\nend",
            source,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(translator)
        body = translator.group("body")
        self.assertIn(
            "argument_error_reason::AsymptoticFailureReason", body
        )
        self.assertNotIn("occursin(", body)
        self.assertNotIn("lowercase(", body)
        self.assertIn("reason must classify the callback operation", body)

        radius_builder = re.search(
            r"function _endpoint_radius_from_witness\b"
            r"(?P<body>.*?)\nend",
            source,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(radius_builder)
        self.assertIn(
            "argument_error_reason=INVALID_ASYMPTOTIC_INPUT",
            radius_builder.group("body"),
        )

        convention_builder = re.search(
            r"function _assert_endpoint_convention\b"
            r"(?P<body>.*?)\nend",
            source,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(convention_builder)
        self.assertGreaterEqual(
            convention_builder.group("body").count(
                "argument_error_reason=INVALID_ASYMPTOTIC_INPUT"
            ),
            2,
        )

        evidence_builder = re.search(
            r"function _regularity_evidence\b(?P<body>.*?)\nend",
            source,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(evidence_builder)
        self.assertGreaterEqual(
            evidence_builder.group("body").count(
                "argument_error_reason="
                "ALGEBRAIC_REPRESENTATION_SINGULAR"
            ),
            2,
        )

        endpoint_builder = re.search(
            r"function _factored_endpoint_initialconditions\b"
            r"(?P<body>.*?)\nend",
            source,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(endpoint_builder)
        self.assertIn(
            "argument_error_reason=INVALID_ASYMPTOTIC_INPUT",
            endpoint_builder.group("body"),
        )

        julia_tests = self.julia_test_source
        self.assertIn("radius_callback_error", julia_tests)
        self.assertIn("nonfinite_radius_result_error", julia_tests)
        self.assertIn("algebraic_callback_error", julia_tests)
        self.assertIn(
            "radius_callback_error.reason == AEC.INVALID_ASYMPTOTIC_INPUT",
            julia_tests,
        )
        self.assertRegex(
            julia_tests,
            r"nonfinite_radius_result_error\.reason\s*==\s*"
            r"AEC\.NONFINITE_ASYMPTOTIC_DATA",
        )
        self.assertRegex(
            julia_tests,
            r"algebraic_callback_error\.reason\s*==\s*"
            r"AEC\.ALGEBRAIC_REPRESENTATION_SINGULAR",
        )

    def test_endpoint_convention_numerically_validates_both_wave_number_legs(
        self,
    ) -> None:
        source = self.initial_conditions_source
        validator = re.search(
            r"function _assert_endpoint_convention\b"
            r"(?P<body>.*?)\nend",
            source,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(validator)
        body = validator.group("body")
        self.assertIn("_endpoint_wave_number(key, HORIZON_INGOING)", body)
        self.assertIn("assert_wave_number_matches_leg(", body)
        self.assertIn("key.omega, convention, :infinity", body)
        self.assertIn("p_horizon, convention, :horizon", body)
        self.assertGreaterEqual(
            body.count("_translate_endpoint_argument_error("), 2
        )

        julia_tests = self.julia_test_source
        self.assertIn("fake_p_horizon_convention", julia_tests)
        self.assertIn("fake_omega_convention", julia_tests)
        self.assertIn(
            "infinity_cross_leg_error.reason == AEC.INVALID_ASYMPTOTIC_INPUT",
            julia_tests,
        )
        self.assertIn(
            "horizon_cross_leg_error.reason == AEC.INVALID_ASYMPTOTIC_INPUT",
            julia_tests,
        )

    def test_rho_zero_tests_bridge_existing_raw_initial_conditions(self) -> None:
        source = self.julia_test_source
        self.assertIn(
            'testset "rho=0 factored endpoints reproduce legacy raw APIs"',
            source,
        )
        self.assertIn("IC.Xup_initialconditions", source)
        self.assertIn("IC.Xin_initialconditions", source)
        self.assertIn(
            "infinity_contour_tangent(convention) * legacy_up_drstar",
            source,
        )
        self.assertIn(
            "horizon_contour_tangent(convention) * legacy_in_drstar",
            source,
        )
        self.assertIn(
            "legacy_raw_horizon_outgoing_rho_initialconditions",
            source,
        )
        self.assertIn(
            'testset "large-rho endpoint reconstruction remains scale-aware"',
            source,
        )
        self.assertIn("T(5000)", source)


if __name__ == "__main__":
    unittest.main()
