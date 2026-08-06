from __future__ import annotations

import unittest
from unittest.mock import patch

from windows_solver.contracts import Capability
from windows_solver import planner
from windows_solver.planner import build_plan


class CapabilityPlannerTests(unittest.TestCase):
    def test_evidence_package_has_complete_stable_dependency_order(self) -> None:
        plan = build_plan(Capability.EVIDENCE_PACKAGE)

        self.assertEqual(
            tuple(capability.value for capability in plan.capabilities),
            (
                "problem-contract",
                "spectral-core",
                "linear-response",
                "operator-stability",
                "quadratic-ringdown",
                "response-matrix",
                "inverse-inference",
                "signals",
                "detector-inference",
                "evidence-package",
            ),
        )

    def test_quadratic_plan_excludes_unrelated_capabilities(self) -> None:
        plan = build_plan(Capability.QUADRATIC_RINGDOWN)

        self.assertEqual(
            tuple(capability.value for capability in plan.capabilities),
            ("problem-contract", "spectral-core", "quadratic-ringdown"),
        )

    def test_plan_reports_direct_dependencies(self) -> None:
        plan = build_plan(Capability.RESPONSE_MATRIX)

        self.assertEqual(
            tuple(
                capability.value
                for capability in plan.dependencies[Capability.RESPONSE_MATRIX]
            ),
            ("linear-response", "quadratic-ringdown"),
        )

    def test_topological_order_does_not_depend_on_enum_declaration_order(self) -> None:
        dependencies = {
            Capability.PROBLEM_CONTRACT: (Capability.SPECTRAL_CORE,),
            Capability.SPECTRAL_CORE: (),
        }

        with patch.object(planner, "CAPABILITY_DEPENDENCIES", dependencies):
            plan = build_plan(Capability.PROBLEM_CONTRACT)

        self.assertEqual(
            plan.capabilities,
            (Capability.SPECTRAL_CORE, Capability.PROBLEM_CONTRACT),
        )


if __name__ == "__main__":
    unittest.main()
