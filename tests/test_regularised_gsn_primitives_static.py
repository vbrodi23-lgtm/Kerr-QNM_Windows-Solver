from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = (
    ROOT
    / "src/windows_solver/data/julia/GeneralizedSasakiNakamura.jl"
)
COORDINATES = PACKAGE / "src/Homogeneous/Coordinates.jl"
FACTORED = PACKAGE / "src/Homogeneous/FactoredSolutions.jl"
COMPLEX_FREQUENCIES = PACKAGE / "src/Homogeneous/ComplexFrequencies.jl"
ENTRYPOINT = PACKAGE / "src/GeneralizedSasakiNakamura.jl"
JULIA_TESTS = PACKAGE / "test/runtests.jl"

BRANCH_REVIEW_TODO = (
    "TODO: [HUMAN MATH REVIEW REQUIRED — decide whether derivative stencils "
    "freeze only the GSN branch cell while allowing frequency-local contour "
    "angles, or freeze the full contour tangent and use q=±i z t_frozen; verify "
    "contour-deformation invariance before production activation.]"
)
CARRIER_REVIEW_TODO = (
    "TODO: [HUMAN MATH REVIEW REQUIRED — verify the branch-specific plane-wave "
    "carriers, the transformed complex-contour GSN equation, the carrier change "
    "at ρ=0, the factored horizon basis, and the Cinc/Cref determinant chart "
    "against the current GSN amplitude and branch conventions.]"
)
REFERENCE_REVIEW_TODO = (
    "TODO: [HUMAN MATH REVIEW REQUIRED — generate and freeze independent "
    "high-precision reference values for the three GSN asymptotic branches after "
    "the branch and normalization conventions have been verified.]"
)


class RegularisedGsnPrimitiveSourceTests(unittest.TestCase):
    def read(self, path: Path) -> str:
        return path.read_text(encoding="utf-8")

    def test_coordinates_solely_owns_contour_argument_and_half_plane_selection(self):
        coordinates = self.read(COORDINATES)
        factored = self.read(FACTORED)
        complex_frequencies = self.read(COMPLEX_FREQUENCIES)
        entrypoint = self.read(ENTRYPOINT)

        self.assertIn("angle(z)", coordinates)
        self.assertIn("real(z) >= zero", coordinates)
        self.assertIn("gsn_branch_convention", coordinates)
        self.assertNotIn("angle(", factored)
        self.assertNotIn("angle(", complex_frequencies)
        self.assertNotIn("angle(", entrypoint)
        self.assertNotIn("determine_sign", factored)
        self.assertNotIn("determine_sign", entrypoint)
        self.assertIn("using ..Coordinates:", factored)
        self.assertIn("assert_wave_number_matches_leg", factored)
        self.assertIn(
            "using ..Coordinates: r_from_rstar, contour_half_plane_sign",
            complex_frequencies,
        )
        self.assertIn(
            "determine_sign(x) = contour_half_plane_sign(x)",
            complex_frequencies,
        )
        self.assertNotIn("if real(x) >=", complex_frequencies)
        self.assertNotIn("return sign(1.0)", complex_frequencies)
        self.assertNotIn("return sign(-1.0)", complex_frequencies)

    def test_entrypoint_loads_and_exports_factored_primitives(self):
        entrypoint = self.read(ENTRYPOINT)

        coordinates_include = entrypoint.index('include("Homogeneous/Coordinates.jl")')
        factored_include = entrypoint.index(
            'include("Homogeneous/FactoredSolutions.jl")'
        )
        self.assertLess(coordinates_include, factored_include)
        self.assertIn("using .FactoredSolutions", entrypoint)
        self.assertIn("RegularRemainderContract", entrypoint)
        self.assertIn("PlaneWaveCarrier", entrypoint)
        self.assertIn("FactoredEndpointState", entrypoint)

    def test_negative_tortoise_inverse_preserves_requested_precision(self):
        coordinates = self.read(COORDINATES)

        self.assertIn("coordinate_type = promote_type(", coordinates)
        self.assertIn("upper_offset = coordinate_type(7) / coordinate_type(5)", coordinates)
        self.assertIn("find_zero(f, (zero(coordinate_type), upper_offset))", coordinates)
        self.assertNotIn("find_zero(f, (0, 1.4))", coordinates)
        self.assertIn("negative-rstar BigFloat inverse round trip", self.read(JULIA_TESTS))

    def test_exact_contract_identities_and_review_boundaries_are_present(self):
        coordinates = self.read(COORDINATES)
        factored = self.read(FACTORED)
        julia_tests = self.read(JULIA_TESTS)

        self.assertIn('"gsn-complex-rho/v1"', coordinates)
        self.assertIn('"known-carrier-times-regular-remainder/v1"', factored)
        self.assertIn(
            '"column1=horizon-ingoing-Cref;column2=horizon-outgoing-Cinc/v1"',
            factored,
        )
        self.assertIn('"state2=dX/drho/v1"', factored)
        self.assertIn('"cinc-over-cref-minus-R/v1"', factored)
        self.assertIn('"state1=Y;state2=dY/drho/v1"', factored)
        self.assertIn(BRANCH_REVIEW_TODO, coordinates)
        self.assertIn(CARRIER_REVIEW_TODO, factored)
        self.assertIn(REFERENCE_REVIEW_TODO, julia_tests)
        self.assertIn("assert_independent_reference_fixture_available", factored)
        self.assertIn("assert_regularised_gsn_production_ready", factored)
        self.assertIn(
            "assert_independent_reference_fixture_available()\n    return nothing",
            factored,
        )
        self.assertIn("assert_regularised_gsn_production_ready", self.read(ENTRYPOINT))
        self.assertNotIn("@test_broken", julia_tests)
        self.assertNotIn("@test_skip", julia_tests)

    def test_factored_representation_has_no_dynamic_max_abs_normalizer(self):
        factored = self.read(FACTORED)

        forbidden = (
            "maximum(abs.",
            "max(abs(",
            "normalize_remainder",
            "normalise_remainder",
        )
        for fragment in forbidden:
            self.assertNotIn(fragment, factored)
        self.assertIn("X = A * state.Y", factored)
        self.assertIn("Y = raw.X / A", factored)
        self.assertIn("ratio * state.Y", factored)


if __name__ == "__main__":
    unittest.main()
