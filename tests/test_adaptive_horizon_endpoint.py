from __future__ import annotations

from pathlib import Path
import re
import unittest

from windows_solver.julia_response_backend import horizon_geometry_controls


ROOT = Path(__file__).resolve().parents[1]
COMPLEX_FREQUENCIES = ROOT / (
    "src/windows_solver/data/julia/GeneralizedSasakiNakamura.jl/src/"
    "Homogeneous/ComplexFrequencies.jl"
)
WORKER = ROOT / "src/windows_solver/data/julia/m02_worker.jl"
JULIA_SPEC = ROOT / (
    "src/windows_solver/data/julia/GeneralizedSasakiNakamura.jl/test/"
    "horizon_endpoint_adaptive_spec.jl"
)


def _function(source: str, name: str) -> str:
    match = re.search(rf"(?m)^function\s+{re.escape(name)}\b", source)
    if match is None:
        raise AssertionError(f"missing Julia function {name}")
    following = source.find("\nfunction ", match.end())
    return source[match.start() : following if following >= 0 else len(source)]


class AdaptiveHorizonEndpointStaticTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.package_source = COMPLEX_FREQUENCIES.read_text(encoding="utf-8")
        cls.worker_source = WORKER.read_text(encoding="utf-8")
        cls.spec_source = JULIA_SPEC.read_text(encoding="utf-8")

    def test_preserved_order_28_failure_fixture_contains_all_five_exact_rows(self) -> None:
        for rho, distance in (
            (-10, "0.780708315432074"),
            (-25, "0.1343843030342528"),
            (-50, "0.04199390049280419"),
            (-75, "0.020989841197182793"),
            (-100, "0.01225366578659957"),
        ):
            with self.subTest(rho=rho):
                self.assertIn(f"rho={rho}", self.spec_source)
                self.assertIn(f"horizon_distance={distance}", self.spec_source)
        self.assertIn("endpoint_order=28", self.spec_source)
        self.assertIn("NO_VERIFIED_HORIZON_ENDPOINT", self.spec_source)

    def test_recovery_exhausts_depth_schedule_at_each_order_and_caches_geometry(self) -> None:
        recovery = _function(
            self.package_source,
            "recover_verified_horizon_endpoint_pair",
        )
        order_loop = recovery.index("for endpoint_order in endpoint_orders")
        depth_loop = recovery.index("for geometry in geometry_schedule", order_loop)
        self.assertLess(order_loop, depth_loop)
        self.assertIn("geometry_cache", recovery)
        self.assertIn("geometry_invalid_rhos", recovery)
        self.assertIn("continue", recovery)
        self.assertIn("length(verified_by_rho) >= 2", recovery)
        self.assertIn(
            "endpoint_orders=horizon_endpoint_prefix_orders(", recovery
        )
        self.assertIn("minimum_order=prefix_minimum_order", recovery)
        self.assertIn("order_step=prefix_order_step", recovery)
        self.assertNotIn("endpoint_orders=Int[endpoint_order]", recovery)

    def test_best_prefix_is_selected_independently_for_both_horizon_branches(self) -> None:
        selector = _function(
            self.package_source,
            "select_horizon_endpoint_best_prefix",
        )
        self.assertIn("scaled_term_magnitudes", selector)
        self.assertIn("cancellation", selector)
        self.assertIn("last_term", selector)
        recovery = _function(
            self.package_source,
            "recover_verified_horizon_endpoint_pair",
        )
        candidate_builder = _function(self.package_source, "horizon_endpoint_candidates")
        self.assertIn("HORIZON_INGOING", candidate_builder)
        self.assertIn("HORIZON_OUTGOING", candidate_builder)
        self.assertIn("ingoing_best_prefix_order", recovery)
        self.assertIn("outgoing_best_prefix_order", recovery)

    def test_nonfinite_prefix_schedules_remain_typed_candidates(self) -> None:
        candidate_builder = _function(
            self.package_source, "horizon_endpoint_candidates"
        )
        self.assertIn(
            "if ingoing_assessment === nothing || outgoing_assessment === nothing",
            candidate_builder,
        )
        self.assertIn("nothing,", candidate_builder)
        self.assertIn("continue", candidate_builder)

    def test_worker_candidate_event_carries_both_selected_prefix_orders(self) -> None:
        emitter = _function(self.worker_source, "emit_horizon_endpoint_candidate")
        self.assertIn('"ingoing_best_prefix_order"', emitter)
        self.assertIn('"outgoing_best_prefix_order"', emitter)
        self.assertIn('"attempted_endpoint_order"', emitter)
        self.assertIn("candidate.ingoing_evaluation.order", emitter)
        self.assertIn("candidate.outgoing_evaluation.order", emitter)

    def test_successful_endpoint_certificate_is_persisted_in_worker_response(self) -> None:
        determinant = _function(
            self.worker_source, "evaluate_horizon_determinant"
        )
        result_fields = _function(self.worker_source, "result_fields")
        self.assertIn(
            "horizon_endpoint_search_evidence::Vector{Any}",
            self.worker_source,
        )
        self.assertIn(
            "context.conditioning.horizon_endpoint_search_evidence",
            determinant,
        )
        self.assertIn(
            '"horizon_endpoint_search_evidence"', result_fields
        )
        self.assertIn('"schema_version" => 12', result_fields)

    def test_search_floor_and_real_inner_contour_share_one_signed_policy_bound(self) -> None:
        controls = horizon_geometry_controls()
        self.assertEqual(
            controls["horizon_rho_inner_min"],
            controls["horizon_endpoint_rho_floor"],
        )
        self.assertEqual(controls["horizon_endpoint_rho_floor"], "-400")
        self.assertEqual(
            controls["horizon_endpoint_rho_candidates"][-1], "-100"
        )
        flattening = _function(self.worker_source, "flatten_request")
        self.assertIn(
            '"horizon_endpoint_rho_floor" => required(', flattening
        )

    def test_prefix_schedule_retains_intermediate_least_term_before_growth(self) -> None:
        selector = _function(
            self.package_source,
            "select_horizon_endpoint_best_prefix",
        )
        schedule = _function(
            self.package_source,
            "horizon_endpoint_prefix_orders",
        )
        self.assertIn("minimum_order::Int=4", schedule)
        self.assertIn("order_step::Int=4", schedule)
        self.assertIn("push!(orders, maximum_order)", schedule)
        self.assertNotIn("assessment.adequate && break", selector)
        self.assertIn(
            "assessment.predicted_reliable_digits >",
            selector,
        )
        fixture = {4: 18.0, 8: 26.0, 12: 31.5, 16: 29.0, 20: 21.0}
        self.assertEqual(max(fixture, key=fixture.get), 12)

    def test_distinct_typed_outcomes_and_policy_bound_canonical_evidence_exist(self) -> None:
        for outcome in (
            "NO_GEOMETRY_VALID_CANDIDATE",
            "MAX_SERIES_ORDER_INADEQUATE",
            "ARITHMETIC_PRECISION_INADEQUATE",
            "COORDINATE_INVERSION_FAILURE",
            "FEWER_THAN_TWO_VERIFIED_ENDPOINTS",
        ):
            self.assertRegex(
                self.package_source,
                rf"const\s+{outcome}\s*=\s*\"[^\"]+/v1\"",
            )
        evidence = _function(
            self.package_source,
            "canonical_horizon_endpoint_search_evidence",
        )
        self.assertIn("policy_identity", evidence)
        self.assertIn("selected_pair", evidence)
        self.assertIn("rejected_candidates", evidence)
        self.assertIn("attempted_endpoint_order", evidence)
        self.assertIn("ingoing_best_prefix_order", evidence)
        self.assertIn("outgoing_best_prefix_order", evidence)
        self.assertIn("limitation = horizon_endpoint_limitation(", evidence)
        self.assertIn("limitation=limitation", evidence)
        self.assertIn("precision_limited=", evidence)
        self.assertIn("limitation_conditioning=", evidence)
        self.assertIn("maximum_last_term_ratio", evidence)
        self.assertIn("maximum_recurrence_digits_lost", evidence)
        self.assertIn("maximum_series_evaluation_digits_lost", evidence)
        self.assertIn("maximum_truncation_digits_lost", evidence)

    def test_worker_obtains_verified_pair_before_any_homogeneous_solve(self) -> None:
        determinant = _function(self.worker_source, "evaluate_horizon_determinant")
        pair = determinant.index("CF.recover_verified_horizon_endpoint_pair")
        outer = determinant.index("CF.solve_factored_xup_to_match")
        horizon = determinant.index("CF.solve_verified_horizon_basis_to_match")
        self.assertLess(pair, outer)
        self.assertLess(pair, horizon)
        self.assertIn("length(endpoint_recovery.selected_pair) != 2", determinant)
        self.assertIn("homogeneous_rhs_evaluations_before_pair == 0", determinant)

    def test_worker_consumes_recovery_result_and_serializes_distinct_failures(self) -> None:
        determinant = _function(self.worker_source, "evaluate_horizon_determinant")
        failure = _function(self.worker_source, "horizon_endpoint_recovery_failure")
        self.assertNotIn("CF.select_verified_horizon_endpoints(", determinant)
        self.assertIn("CF.verified_horizon_endpoints_from_recovery(", determinant)
        self.assertIn("endpoint_recovery.outcome", determinant)
        for outcome, failure_code in (
            ("NO_GEOMETRY_VALID_CANDIDATE", "HORIZON_GEOMETRY_EXHAUSTED"),
            ("MAX_SERIES_ORDER_INADEQUATE", "HORIZON_MAXIMUM_ORDER_INADEQUATE"),
            ("ARITHMETIC_PRECISION_INADEQUATE", "HORIZON_ARITHMETIC_INADEQUATE"),
            ("COORDINATE_INVERSION_FAILURE", "HORIZON_COORDINATE_INVERSION_FAILED"),
            ("FEWER_THAN_TWO_VERIFIED_ENDPOINTS", "HORIZON_ONLY_ONE_ENDPOINT"),
        ):
            self.assertIn(outcome, failure)
            self.assertIn(failure_code, failure)
        self.assertIn(
            "retryable=outcome == CF.ARITHMETIC_PRECISION_INADEQUATE",
            failure,
        )
        self.assertIn('"recovery_outcome" => outcome', failure)
        coordinate = _function(
            self.worker_source,
            "canonical_horizon_coordinate_failure_evidence",
        )
        self.assertIn("horizon_endpoint_order_ladder", coordinate)
        self.assertIn("horizon_endpoint_recovery_policy_identity", coordinate)
        self.assertIn('"selected_pair" => Any[]', coordinate)
        self.assertIn('"rejected_candidates" => Any[]', coordinate)
        self.assertIn("failure isa CoordinateInversionStalled", determinant)
        self.assertIn(
            "canonical_horizon_coordinate_failure_evidence(request)",
            determinant,
        )
        self.assertIn(
            'stage=outcome == CF.COORDINATE_INVERSION_FAILURE ?', failure
        )
        self.assertIn('"coordinate-inversion"', failure)
        canonical = _function(
            self.package_source,
            "canonical_horizon_endpoint_search_evidence",
        )
        self.assertIn("selected_keys", canonical)
        self.assertIn("candidate.attempted_endpoint_order", canonical)
        self.assertNotIn("selected_rhos", canonical)


if __name__ == "__main__":
    unittest.main()
