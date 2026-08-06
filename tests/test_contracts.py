from __future__ import annotations

import math
from pathlib import Path
import tempfile
import unittest

from windows_solver.contracts import (
    Capability,
    CarrierState,
    EvidenceState,
    ExecutionState,
    ModeKey,
    NumericalState,
    ScientificState,
    StudyRequest,
    canonical_json_bytes,
    load_study,
)

from tests.fixtures import VALID_STUDY


class ModeKeyTests(unittest.TestCase):
    def test_parses_complete_mode_identity(self) -> None:
        mode = ModeKey.from_mapping(VALID_STUDY["modes"][0])

        self.assertEqual(mode.s, -2)
        self.assertEqual(mode.ell, 2)
        self.assertEqual(mode.m, 2)
        self.assertEqual(mode.n, 0)
        self.assertEqual(mode.branch, "damped")
        self.assertEqual(mode.polarization, "plus")

    def test_rejects_azimuthal_index_outside_angular_band(self) -> None:
        invalid = dict(VALID_STUDY["modes"][0], m=3)

        with self.assertRaisesRegex(ValueError, "absolute m must not exceed ell"):
            ModeKey.from_mapping(invalid)


class StudyRequestTests(unittest.TestCase):
    def test_rejects_unknown_fields(self) -> None:
        invalid = dict(VALID_STUDY, unexpected="hidden")

        with self.assertRaisesRegex(ValueError, "unknown study fields: unexpected"):
            StudyRequest.from_mapping(invalid)

    def test_rejects_spin_outside_open_kerr_interval(self) -> None:
        for spin in (-1.0, 1.0, math.inf):
            with self.subTest(spin=spin):
                invalid = dict(VALID_STUDY, spins=[spin])
                with self.assertRaisesRegex(ValueError, "spins must be finite"):
                    StudyRequest.from_mapping(invalid)

    def test_convention_identity_changes_canonical_request(self) -> None:
        first = StudyRequest.from_mapping(VALID_STUDY)
        second = StudyRequest.from_mapping(
            dict(VALID_STUDY, convention_id="distinct-robin-boundary-law")
        )

        self.assertNotEqual(
            canonical_json_bytes(first.to_mapping()),
            canonical_json_bytes(second.to_mapping()),
        )

    def test_load_study_reads_strict_json_object(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "study.json")
            path.write_bytes(canonical_json_bytes(VALID_STUDY))

            request = load_study(path)

        self.assertIs(request.target, Capability.PROBLEM_CONTRACT)
        self.assertEqual(request.spins, (0.0, 0.7))

    def test_capability_request_excludes_other_capability_policies(self) -> None:
        policy = dict(
            VALID_STUDY["numerical_policy"],
            **{
                "spectral-core": {"basis_size": 64},
                "detector-inference": {"threshold": 8.0},
            },
        )
        request = StudyRequest.from_mapping(
            dict(
                VALID_STUDY,
                target="evidence-package",
                numerical_policy=policy,
            )
        )

        scoped = request.for_capability(Capability.SPECTRAL_CORE)

        self.assertIs(scoped.target, Capability.SPECTRAL_CORE)
        self.assertEqual(
            scoped.numerical_policy,
            {
                "precision_bits": 128,
                "root_tolerance": 1e-10,
                "spectral-core": {"basis_size": 64},
            },
        )


class CanonicalJsonTests(unittest.TestCase):
    def test_is_deterministic_for_different_mapping_order(self) -> None:
        left = {"beta": [2, 1], "alpha": {"z": 3, "a": 4}}
        right = {"alpha": {"a": 4, "z": 3}, "beta": [2, 1]}

        expected = b'{"alpha":{"a":4,"z":3},"beta":[2,1]}'
        self.assertEqual(canonical_json_bytes(left), expected)
        self.assertEqual(canonical_json_bytes(right), expected)

    def test_rejects_non_finite_numbers(self) -> None:
        with self.assertRaises(ValueError):
            canonical_json_bytes({"value": math.nan})


class EvidenceStateTests(unittest.TestCase):
    def test_downstream_evidence_is_bounded_by_rejected_contradicted_input(self) -> None:
        downstream = EvidenceState(
            carrier=CarrierState.VALID,
            execution=ExecutionState.SUCCEEDED,
            numerical=NumericalState.ACCEPTED,
            scientific=ScientificState.SUPPORTED,
        )
        upstream = EvidenceState(
            carrier=CarrierState.VALID,
            execution=ExecutionState.SUCCEEDED,
            numerical=NumericalState.REJECTED,
            scientific=ScientificState.CONTRADICTED,
        )

        constrained = downstream.constrained_by((upstream,))

        self.assertIs(constrained.numerical, NumericalState.REJECTED)
        self.assertIs(constrained.scientific, ScientificState.CONTRADICTED)

    def test_invalid_failed_and_unresolved_inputs_remain_visible(self) -> None:
        downstream = EvidenceState(
            carrier=CarrierState.VALID,
            execution=ExecutionState.SUCCEEDED,
            numerical=NumericalState.ACCEPTED,
            scientific=ScientificState.SUPPORTED,
        )
        upstream = EvidenceState(
            carrier=CarrierState.INVALID,
            execution=ExecutionState.FAILED,
            numerical=NumericalState.UNRESOLVED,
            scientific=ScientificState.FRAGILE,
        )

        constrained = downstream.constrained_by((upstream,))

        self.assertIs(constrained.carrier, CarrierState.INVALID)
        self.assertIs(constrained.execution, ExecutionState.FAILED)
        self.assertIs(constrained.numerical, NumericalState.UNRESOLVED)
        self.assertIs(constrained.scientific, ScientificState.FRAGILE)


if __name__ == "__main__":
    unittest.main()
