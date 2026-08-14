from __future__ import annotations

from decimal import Decimal
import io
import json
from pathlib import Path
from types import SimpleNamespace
from tempfile import TemporaryDirectory
import time
import unittest

from windows_solver.campaign_reports import (
    CONDITIONING_REPORT_COLUMNS,
    LEAF_COLUMNS,
    CampaignReportModel,
    _conditioning_report_fields,
)
from windows_solver.progress import ProgressContext, ProgressEvent, ProgressEventKind
from windows_solver.progress_output import CampaignProgressReporter


ROOT = Path(__file__).resolve().parents[1]


def _event(
    kind: ProgressEventKind,
    payload: dict[str, object] | None = None,
    **context: object,
) -> ProgressEvent:
    return ProgressEvent(
        kind=kind,
        context=ProgressContext.from_mapping(context),
        payload={} if payload is None else payload,
        monotonic_seconds=time.monotonic(),
    )


class Task3CConditioningSurfaceTests(unittest.TestCase):
    def test_exact_factored_progress_kinds_are_registered(self) -> None:
        expected = {
            "ASYMPTOTIC_SERIES_EVALUATED": "asymptotic_series_evaluated",
            "CARRIER_CHANGED": "carrier_changed",
            "FACTORED_ODE_COMPLETED": "factored_ode_completed",
            "SCATTERING_COEFFICIENTS_EXTRACTED": (
                "scattering_coefficients_extracted"
            ),
            "DETERMINANT_CHART_EVALUATED": "determinant_chart_evaluated",
            "CONDITIONING_EVALUATED": "conditioning_evaluated",
        }

        self.assertEqual(
            {
                name: getattr(ProgressEventKind, name).value
                for name in expected
            },
            expected,
        )

    def test_dashboard_retains_only_compact_conditioning_evidence(self) -> None:
        with TemporaryDirectory() as temporary:
            checkpoint = Path(temporary) / "campaign.json"
            reporter = CampaignProgressReporter("normal", checkpoint, io.StringIO())
            context = {
                "leaf_id": "leaf-1",
                "leaf_index": 1,
                "leaf_count": 1,
                "precision_digits": 80,
            }
            reporter.publish(_event(
                ProgressEventKind.PRECISION_STAGE_STARTED,
                **context,
            ))
            reporter.publish(_event(
                ProgressEventKind.ASYMPTOTIC_SERIES_EVALUATED,
                {
                    "adequate": True,
                    "maximum_series_digits_lost": "2.125",
                    "maximum_series_evaluation_spread": "1.25e-31",
                    "asymptotic_preflight_avoided_ode": False,
                    "series_eval_horner": {"real": "9" * 80, "imaginary": "1"},
                    "series_eval_compensated": {
                        "real": "8" * 80,
                        "imaginary": "2",
                    },
                    "series_eval_alternate": {
                        "real": "7" * 80,
                        "imaginary": "3",
                    },
                },
                **context,
            ))
            reporter.publish(_event(
                ProgressEventKind.CARRIER_CHANGED,
                {
                    "homogeneous_representation": "factored-plane-wave-gsn/v1",
                    "current_carrier": "horizon-ingoing",
                },
                **context,
            ))
            reporter.publish(_event(
                ProgressEventKind.SCATTERING_COEFFICIENTS_EXTRACTED,
                {"maximum_basis_condition": "3.5e12"},
                **context,
            ))
            reporter.publish(_event(
                ProgressEventKind.DETERMINANT_CHART_EVALUATED,
                {
                    "normalised_determinant_abs": "4.5e-20",
                    "raw_determinant_abs": "6.75e+220",
                    "raw_determinant_evidence_status": "available/v1",
                    "cref_chart_safe": False,
                },
                **context,
            ))
            reporter.publish(_event(
                ProgressEventKind.CONDITIONING_EVALUATED,
                {
                    "maximum_recurrence_digits_lost": "1.75",
                    "maximum_fd_digits_lost": "5.25",
                    "predicted_reliable_digits": "58.625",
                    "required_reliable_digits": "64",
                    "precision_limited": True,
                },
                **context,
            ))

            live = reporter._live_execution_mapping()
            self.assertEqual(
                live["homogeneous_representation"],
                "factored-plane-wave-gsn/v1",
            )
            self.assertEqual(live["current_carrier"], "horizon-ingoing")
            self.assertEqual(live["maximum_series_digits_lost"], "2.125")
            self.assertEqual(live["maximum_basis_condition"], "3.5e12")
            self.assertEqual(live["maximum_fd_digits_lost"], "5.25")
            self.assertEqual(live["predicted_reliable_digits"], "58.625")
            self.assertEqual(live["required_reliable_digits"], "64")
            self.assertEqual(live["determinant_chart"], "Cinc/Cref − R")
            self.assertEqual(
                live["raw_determinant_evidence_status"], "available/v1"
            )
            self.assertEqual(live["raw_determinant_abs"], "6.75e+220")
            self.assertIs(live["cref_chart_safe"], False)
            self.assertIs(live["asymptotic_preflight_adequate"], True)
            self.assertIs(live["asymptotic_preflight_avoided_ode"], False)

            rendered = "\n".join(reporter._current_execution_lines())
            self.assertIn("FACTORED CONDITIONING", rendered)
            self.assertIn("factored-plane-wave-gsn/v1", rendered)
            self.assertIn("horizon-ingoing", rendered)
            self.assertIn("2.125", rendered)
            self.assertIn("1.25e-31", rendered)
            self.assertIn("3.5e12", rendered)
            self.assertIn("5.25", rendered)
            self.assertIn("58.625 / 64", rendered)
            self.assertIn("Cinc/Cref − R", rendered)
            self.assertIn("unsafe", rendered)
            self.assertNotIn("9999999999999999", rendered)
            self.assertNotIn("8888888888888888", rendered)
            self.assertNotIn("7777777777777777", rendered)

            status = json.loads(
                Path(f"{checkpoint}.status.json").read_text(encoding="utf-8")
            )
            self.assertEqual(
                status["live_execution"]["predicted_reliable_digits"],
                "58.625",
            )
            self.assertEqual(
                status["live_execution"]["normalised_determinant_abs"],
                "4.5e-20",
            )
            self.assertEqual(
                status["live_execution"]["raw_determinant_evidence_status"],
                "available/v1",
            )

    def test_live_raw_status_clears_stale_magnitude_when_unavailable(self) -> None:
        """Catches an old finite raw value surviving a typed overflow event."""

        temporary = self.enterContext(TemporaryDirectory())
        reporter = CampaignProgressReporter(
            "normal", Path(temporary) / "campaign.json", io.StringIO()
        )
        context = {
            "leaf_id": "leaf-horizon",
            "mechanism_id": "horizon-admittance",
            "precision_digits": 80,
        }
        reporter.publish(_event(
            ProgressEventKind.PRECISION_STAGE_STARTED,
            **context,
        ))
        reporter.publish(_event(
            ProgressEventKind.DETERMINANT_CHART_EVALUATED,
            {
                "raw_determinant_abs": "6.75E+220",
                "raw_determinant_evidence_status": "available/v1",
            },
            **context,
        ))
        reporter.publish(_event(
            ProgressEventKind.DETERMINANT_CHART_EVALUATED,
            {
                "raw_determinant_abs": None,
                "raw_determinant_evidence_status": (
                    "unavailable-overflow/v1"
                ),
            },
            **context,
        ))

        live = reporter._live_execution_mapping()
        self.assertEqual(
            live["raw_determinant_evidence_status"],
            "unavailable-overflow/v1",
        )
        self.assertIsNone(live["raw_determinant_abs"])
        self.assertIn(
            "unavailable-overflow/v1",
            "\n".join(reporter._current_execution_lines()),
        )

    def test_exterior_conditioning_clears_stale_scattering_live_state(self) -> None:
        """Catches a prior horizon basis/Cref chart surviving an exterior event."""

        temporary = self.enterContext(TemporaryDirectory())
        reporter = CampaignProgressReporter(
            "normal", Path(temporary) / "campaign.json", io.StringIO()
        )
        context = {
            "leaf_id": "leaf-one",
            "mechanism_id": "horizon-admittance",
            "precision_digits": 80,
        }
        reporter.publish(_event(
            ProgressEventKind.CONDITIONING_EVALUATED,
            {
                "determinant_family": "horizon-scattering/v1",
                "determinant_convention": "cinc-over-cref-minus-R/v1",
                "determinant_normalisation": (
                    "cinc-over-cref-minus-reflectivity/v1"
                ),
                "scattering_diagnostics_applicable": True,
                "scattering_column_convention": (
                    "column1=horizon-ingoing-Cref;"
                    "column2=horizon-outgoing-Cinc/v1"
                ),
                "maximum_basis_condition": "3E+12",
                "maximum_basis_backward_error": "2E-40",
                "maximum_matching_reconstruction_residual": "4E-42",
                "minimum_cref_chart_margin": "96",
                "maximum_carrier_change_error": "5E-44",
                "cref_chart_safe": True,
            },
            **context,
        ))
        reporter.publish(_event(
            ProgressEventKind.DETERMINANT_CHART_EVALUATED,
            {"normalised_determinant_abs": "1E-30"},
            **context,
        ))

        reporter.publish(_event(
            ProgressEventKind.CONDITIONING_EVALUATED,
            {
                "determinant_family": "exterior-wronskian/v1",
                "determinant_convention": (
                    "wronskian-perturbed-Xin-with-Xup/v1"
                ),
                "determinant_normalisation": (
                    "unit-asymptotic-branch-wronskian/v1"
                ),
                "scattering_diagnostics_applicable": False,
                "scattering_column_convention": None,
                "maximum_basis_condition": None,
                "maximum_basis_backward_error": None,
                "maximum_matching_reconstruction_residual": None,
                "minimum_cref_chart_margin": None,
                "maximum_carrier_change_error": None,
                "raw_determinant_abs": None,
                "raw_determinant_evidence_status": "not-applicable/v1",
                "normalised_determinant_abs": "7E-31",
            },
            leaf_id="leaf-one",
            mechanism_id="exterior-light-ring",
            precision_digits=80,
        ))

        live = reporter._live_execution_mapping()
        self.assertEqual(live["determinant_family"], "exterior-wronskian/v1")
        self.assertEqual(
            live["determinant_chart"], "unit-asymptotic branch Wronskian"
        )
        self.assertIs(live["scattering_diagnostics_applicable"], False)
        for name in (
            "maximum_basis_condition",
            "maximum_basis_backward_error",
            "maximum_matching_reconstruction_residual",
            "minimum_cref_chart_margin",
            "maximum_carrier_change_error",
            "scattering_column_convention",
            "cref_chart_safe",
            "raw_determinant_abs",
        ):
            self.assertIsNone(live[name], name)
        self.assertEqual(
            live["raw_determinant_evidence_status"],
            "not-applicable/v1",
        )
        self.assertEqual(live["normalised_determinant_abs"], "7E-31")

    def test_exterior_live_state_does_not_reingest_scattering_fields(self) -> None:
        """Catches forbidden horizon evidence being restored after it is cleared."""

        temporary = self.enterContext(TemporaryDirectory())
        reporter = CampaignProgressReporter(
            "normal", Path(temporary) / "campaign.json", io.StringIO()
        )
        reporter.publish(_event(
            ProgressEventKind.CONDITIONING_EVALUATED,
            {
                "determinant_family": "exterior-wronskian/v1",
                "scattering_diagnostics_applicable": False,
                "scattering_column_convention": "forged-horizon-columns/v1",
                "maximum_basis_condition": "0",
                "maximum_basis_backward_error": "0",
                "maximum_matching_reconstruction_residual": "0",
                "minimum_cref_chart_margin": "0",
                "maximum_carrier_change_error": "0",
                "cref_chart_safe": True,
                "raw_determinant_abs": "0",
                "raw_determinant_evidence_status": "not-applicable/v1",
            },
            leaf_id="leaf-exterior",
            mechanism_id="exterior-light-ring",
            precision_digits=80,
        ))

        live = reporter._live_execution_mapping()
        self.assertIs(live["scattering_diagnostics_applicable"], False)
        for name in (
            "maximum_basis_condition",
            "maximum_basis_backward_error",
            "maximum_matching_reconstruction_residual",
            "minimum_cref_chart_margin",
            "maximum_carrier_change_error",
            "scattering_column_convention",
            "cref_chart_safe",
            "raw_determinant_abs",
        ):
            self.assertIsNone(live[name], name)
        self.assertEqual(
            live["raw_determinant_evidence_status"],
            "not-applicable/v1",
        )

    def test_exterior_chart_uses_mechanism_context_without_identity_payload(self) -> None:
        """Catches a Wronskian event being labelled as the horizon Cref chart."""

        temporary = self.enterContext(TemporaryDirectory())
        reporter = CampaignProgressReporter(
            "normal", Path(temporary) / "campaign.json", io.StringIO()
        )
        reporter.publish(_event(
            ProgressEventKind.DETERMINANT_CHART_EVALUATED,
            {"normalised_determinant_abs": "1E-40"},
            leaf_id="leaf-exterior",
            mechanism_id="exterior-alpha-half",
            precision_digits=80,
        ))

        live = reporter._live_execution_mapping()
        self.assertEqual(live["determinant_family"], "exterior-wronskian/v1")
        self.assertIs(live["scattering_diagnostics_applicable"], False)
        self.assertEqual(
            live["determinant_chart"], "unit-asymptotic branch Wronskian"
        )

    def test_campaign_conditioning_fields_preserve_decimal_and_missing_values(self) -> None:
        expected_columns = (
            "homogeneous_representation",
            "determinant_family",
            "determinant_normalisation",
            "scattering_diagnostics_applicable",
            "scattering_column_convention",
            "determinant_convention",
            "series_digits_lost_max",
            "series_evaluation_spread_max",
            "last_term_ratio_max",
            "recurrence_digits_lost_max",
            "asymptotic_predicted_reliable_digits_min",
            "basis_condition_max",
            "basis_backward_error_max",
            "matching_reconstruction_residual_max",
            "endpoint_remainders_regular",
            "endpoint_reconstruction_error_max",
            "contour_angle_deformation_max",
            "fd_digits_lost_max",
            "predicted_reliable_digits",
            "required_reliable_digits",
            "precision_limited",
            "cref_chart_margin_min",
            "carrier_change_error_max",
            "normalised_determinant_abs",
            "raw_determinant_abs",
            "raw_determinant_evidence_status",
        )
        self.assertEqual(CONDITIONING_REPORT_COLUMNS, expected_columns)
        self.assertTrue(set(CONDITIONING_REPORT_COLUMNS) <= set(LEAF_COLUMNS))

        historical = _conditioning_report_fields(
            SimpleNamespace(numerical_conditioning=None)
        )
        self.assertEqual(historical, {name: None for name in expected_columns})

        evidence = SimpleNamespace(
            homogeneous_representation="factored-plane-wave-gsn/v1",
            determinant_family="horizon-scattering/v1",
            determinant_normalisation=(
                "cinc-over-cref-minus-reflectivity/v1"
            ),
            scattering_diagnostics_applicable=True,
            scattering_column_convention=(
                "column1=horizon-ingoing-Cref;"
                "column2=horizon-outgoing-Cinc/v1"
            ),
            determinant_convention="cinc-over-cref-minus-R/v1",
            maximum_series_digits_lost=Decimal("2.1250000000000000000001"),
            maximum_series_evaluation_spread=Decimal("3.75E-31"),
            maximum_last_term_ratio=Decimal("9.125E-18"),
            maximum_recurrence_digits_lost=Decimal("1.75"),
            minimum_asymptotic_predicted_reliable_digits=Decimal("47.625"),
            maximum_basis_condition=Decimal("3.5E+12"),
            maximum_basis_backward_error=Decimal("4.25E-40"),
            maximum_matching_reconstruction_residual=Decimal("5.125E-42"),
            endpoint_remainders_regular=True,
            maximum_endpoint_reconstruction_error=Decimal("6.5E-38"),
            maximum_contour_angle_deformation=Decimal("7.25E-12"),
            maximum_fd_digits_lost=Decimal("5.25"),
            predicted_reliable_digits=Decimal("58.625"),
            required_reliable_digits=Decimal("64"),
            precision_limited=True,
            minimum_cref_chart_margin=Decimal("0.75"),
            maximum_carrier_change_error=Decimal("8.5E-43"),
        )
        current = _conditioning_report_fields(
            SimpleNamespace(
                numerical_conditioning=evidence,
                determinant_residual_abs=4.5e-20,
                normalised_determinant_abs=Decimal(
                    "4.5000000000000000000000000000001E-120"
                ),
                raw_determinant_abs=Decimal(
                    "6.7500000000000000000000000000001E+220"
                ),
                raw_determinant_evidence_status="available/v1",
            )
        )
        self.assertEqual(
            current["series_digits_lost_max"],
            Decimal("2.1250000000000000000001"),
        )
        self.assertEqual(
            current["series_evaluation_spread_max"], Decimal("3.75E-31")
        )
        self.assertEqual(current["last_term_ratio_max"], Decimal("9.125E-18"))
        self.assertEqual(
            current["asymptotic_predicted_reliable_digits_min"],
            Decimal("47.625"),
        )
        self.assertEqual(
            current["normalised_determinant_abs"],
            Decimal("4.5000000000000000000000000000001E-120"),
        )
        self.assertEqual(
            current["raw_determinant_abs"],
            Decimal("6.7500000000000000000000000000001E+220"),
        )
        self.assertEqual(
            current["raw_determinant_evidence_status"], "available/v1"
        )
        self.assertIs(current["endpoint_remainders_regular"], True)
        self.assertIs(current["precision_limited"], True)

        exterior_evidence = SimpleNamespace(
            **{
                **evidence.__dict__,
                "determinant_family": "exterior-wronskian/v1",
                "determinant_normalisation": (
                    "unit-asymptotic-branch-wronskian/v1"
                ),
                "scattering_diagnostics_applicable": False,
                "scattering_column_convention": None,
                "determinant_convention": (
                    "wronskian-perturbed-Xin-with-Xup/v1"
                ),
                "maximum_basis_condition": None,
                "maximum_basis_backward_error": None,
                "maximum_matching_reconstruction_residual": None,
                "minimum_cref_chart_margin": None,
                "maximum_carrier_change_error": None,
            }
        )
        exterior = _conditioning_report_fields(SimpleNamespace(
            numerical_conditioning=exterior_evidence,
            normalised_determinant_abs=Decimal("9.5E-90"),
            raw_determinant_abs=None,
            raw_determinant_evidence_status="not-applicable/v1",
        ))
        self.assertEqual(exterior["determinant_family"], "exterior-wronskian/v1")
        self.assertIs(exterior["scattering_diagnostics_applicable"], False)
        self.assertIsNone(exterior["basis_condition_max"])
        self.assertIsNone(exterior["cref_chart_margin_min"])
        self.assertIsNone(exterior["raw_determinant_abs"])
        self.assertEqual(
            exterior["raw_determinant_evidence_status"],
            "not-applicable/v1",
        )

        unavailable = _conditioning_report_fields(SimpleNamespace(
            numerical_conditioning=evidence,
            normalised_determinant_abs=Decimal("9.5E-90"),
            raw_determinant_abs=None,
            raw_determinant_evidence_status="unavailable-overflow/v1",
        ))
        self.assertIsNone(unavailable["raw_determinant_abs"])
        self.assertEqual(
            unavailable["raw_determinant_evidence_status"],
            "unavailable-overflow/v1",
        )

        no_exact_magnitudes = _conditioning_report_fields(
            SimpleNamespace(
                numerical_conditioning=evidence,
                determinant_residual_abs=4.5e-20,
            )
        )
        self.assertIsNone(no_exact_magnitudes["normalised_determinant_abs"])
        self.assertIsNone(no_exact_magnitudes["raw_determinant_abs"])

    def test_status_scientific_projection_keeps_explicit_missing_fields(self) -> None:
        row = {name: None for name in LEAF_COLUMNS}
        row.update({"leaf_id": "historical", "terminal_state": "PRODUCED"})
        reporter = CampaignProgressReporter("normal", "unused.json", io.StringIO())
        reporter._campaign_report_model = CampaignReportModel(
            leaf_rows=(row,),
            error_channel_rows=(),
            projective_rows=(),
            checkpoint_source_receipt="sha256:" + "0" * 64,
        )

        scientific = dict(reporter._scientific_dashboard_fields())
        for name in CONDITIONING_REPORT_COLUMNS:
            self.assertIn(name, scientific)
            self.assertIsNone(scientific[name])

    def test_status_scientific_projection_preserves_decimal_text(self) -> None:
        with TemporaryDirectory() as temporary:
            checkpoint = Path(temporary) / "campaign.json"
            row = {name: None for name in LEAF_COLUMNS}
            row.update({
                "leaf_id": "leaf-decimal",
                "terminal_state": "PRODUCED",
                "precision_digits": 80,
                "series_digits_lost_max": Decimal(
                    "2.1250000000000000000001"
                ),
                "normalised_determinant_abs": Decimal("4.5000E-120"),
                "raw_determinant_evidence_status": (
                    "unavailable-overflow/v1"
                ),
            })
            reporter = CampaignProgressReporter(
                "quiet", checkpoint, io.StringIO()
            )
            reporter._campaign_report_model = CampaignReportModel(
                leaf_rows=(row,),
                error_channel_rows=(),
                projective_rows=(),
                checkpoint_source_receipt="sha256:" + "0" * 64,
            )

            reporter.publish(_event(
                ProgressEventKind.LEAF_COMPLETED,
                {"state": "PRODUCED"},
                leaf_id="leaf-decimal",
                precision_digits=80,
            ))

            self.assertEqual(reporter.diagnostics, [])
            status = json.loads(
                Path(f"{checkpoint}.status.json").read_text(encoding="utf-8")
            )
            self.assertEqual(
                status["scientific"]["series_digits_lost_max"],
                "2.1250000000000000000001",
            )
            self.assertEqual(
                status["scientific"]["normalised_determinant_abs"],
                "4.5000E-120",
            )
            self.assertEqual(
                status["scientific"]["raw_determinant_evidence_status"],
                "unavailable-overflow/v1",
            )

    def test_runtime_policy_inventories_factored_sources_and_identity(self) -> None:
        policy = json.loads(
            (ROOT / "runtime" / "runtime_policy.json").read_text(encoding="utf-8")
        )
        sources = {source["id"]: source for source in policy["scientific_sources"]}
        expected_paths = {
            "gsn-coordinates": (
                "src/windows_solver/data/julia/GeneralizedSasakiNakamura.jl/"
                "src/Homogeneous/Coordinates.jl"
            ),
            "gsn-factored-solutions": (
                "src/windows_solver/data/julia/GeneralizedSasakiNakamura.jl/"
                "src/Homogeneous/FactoredSolutions.jl"
            ),
            "gsn-complex-frequencies": (
                "src/windows_solver/data/julia/GeneralizedSasakiNakamura.jl/"
                "src/Homogeneous/ComplexFrequencies.jl"
            ),
            "gsn-initial-conditions": (
                "src/windows_solver/data/julia/GeneralizedSasakiNakamura.jl/"
                "src/Homogeneous/InitialConditions.jl"
            ),
            "gsn-asymptotic-expansion-coefficients": (
                "src/windows_solver/data/julia/GeneralizedSasakiNakamura.jl/"
                "src/Homogeneous/AsymptoticExpansionCoefficients.jl"
            ),
            "gsn-solutions": (
                "src/windows_solver/data/julia/GeneralizedSasakiNakamura.jl/"
                "src/Homogeneous/Solutions.jl"
            ),
            "m02-julia-worker": "src/windows_solver/data/julia/m02_worker.jl",
        }
        self.assertEqual(
            {source_id: sources[source_id]["path"] for source_id in expected_paths},
            expected_paths,
        )

        self.assertEqual(
            policy["scientific_result_identity"],
            {
                "homogeneous_representation": "factored-plane-wave-gsn/v1",
                "asymptotic_series_evaluation": (
                    "typed-batch-horner-compensated/v1"
                ),
                "conditioning_diagnostics": "series-recurrence-basis-fd/v1",
                "reliable_digit_safety_margin": "8",
                "required_digit_guard": "6",
                "branch_convention": "gsn-complex-rho/v1",
                "radial_derivative_convention": "state2=dX/drho/v1",
                "regular_remainder_contract": (
                    "known-carrier-times-regular-remainder/v1"
                ),
                "factored_remainder_state_convention": (
                    "state1=Y;state2=dY/drho/v1"
                ),
                "determinant_families": {
                    "horizon-scattering/v1": {
                        "scattering_diagnostics_applicable": True,
                        "scattering_coefficient_extraction": (
                            "scaled-factored-horizon-basis/v1"
                        ),
                        "horizon_determinant_chart": (
                            "cinc-over-cref-minus-reflectivity/v1"
                        ),
                        "scattering_chart_safety_factor": "64",
                        "scattering_column_convention": (
                            "column1=horizon-ingoing-Cref;"
                            "column2=horizon-outgoing-Cinc/v1"
                        ),
                        "determinant_convention": "cinc-over-cref-minus-R/v1",
                        "determinant_normalisation": (
                            "cinc-over-cref-minus-reflectivity/v1"
                        ),
                    },
                    "exterior-wronskian/v1": {
                        "scattering_diagnostics_applicable": False,
                        "scattering_coefficient_extraction": None,
                        "horizon_determinant_chart": None,
                        "scattering_chart_safety_factor": None,
                        "scattering_column_convention": None,
                        "determinant_convention": (
                            "wronskian-perturbed-Xin-with-Xup/v1"
                        ),
                        "determinant_normalisation": (
                            "unit-asymptotic-branch-wronskian/v1"
                        ),
                    },
                },
            },
        )


if __name__ == "__main__":
    unittest.main()
