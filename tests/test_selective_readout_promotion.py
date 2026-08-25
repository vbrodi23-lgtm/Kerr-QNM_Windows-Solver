from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from pathlib import Path
import re
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tests.test_julia_response_backend import FakeAdapter
from tests.test_native_campaign_backend import _result
from tests.test_promoted_horizon_component import _promoted_baseline
from tests.fixtures import synthetic_ode_error_budget
import windows_solver.response_engine as response_engine
import windows_solver.response_batches as response_batches
from windows_solver.contracts import canonical_json_bytes
from windows_solver.adaptive_controls import ODE_CALIBRATION_BLOCKER
from windows_solver.gsn_cache_producer import GeneratedGsnCache, GsnParameterPair
from windows_solver.julia_response_backend import JuliaPrecisionRootBackend
from windows_solver.precision_tiers import PrecisionTier, working_precision_bits
from windows_solver.partial_component_checkpoint import PartialComponentJournal
from windows_solver.promoted_control_calibration import (
    EXTERIOR_DETERMINANT_ABSOLUTE_ERROR_CERTIFICATE,
    load_default_calibration_receipt,
)
from windows_solver.response_batches import (
    NativeCampaignStageBackend,
    PrecisionCapabilities,
    StageOutcome,
    build_campaign_selection,
    build_campaign_plan,
    run_campaign_selection,
    synthetic_stage_signed_error_channels,
    validate_campaign_checkpoint,
)
from windows_solver.response_engine import (
    EXTERIOR_DERIVATIVE_COMPONENT_IDENTITY,
    ComponentStatus,
    DiagnosticRootReadout,
    NativeDeterminantAdapter,
    NumericalPolicy,
    RootReadout,
    VettedNativeDeterminantKernel,
    run_component,
)


class CampaignSampleAdapter(FakeAdapter):
    def evaluate_for_validation(self, request):
        if request["operation"] == "root-readout":
            return super().evaluate_for_validation(request)
        self.requests.append(request)
        amplitude = complex(
            float(request["amplitude"]["real"]),
            float(request["amplitude"]["imaginary"]),
        )
        sample_omega = complex(
            float(request["omega"]["real"]),
            float(request["omega"]["imaginary"]),
        )
        fixed_omega = complex(
            float(request["fixed_omega"]["real"]),
            float(request["fixed_omega"]["imaginary"]),
        )
        determinant = (
            1.0e-12
            + (2.0 + 3.0j) * amplitude
            + (4.0 + 5.0j) * (sample_omega - fixed_omega)
        )
        amplitude_abs = abs(amplitude)
        # The fixed-root frequency stencil evaluates at zero amplitude.  Keep
        # a positive deterministic numerical-error floor there; zero error is
        # not a valid available receipt even in this stub worker.
        determinant_error_abs = max(1.0e-12 * amplitude_abs, 1.0e-12)
        request_sha256 = hashlib.sha256(canonical_json_bytes(request)).hexdigest()
        response = {
            "schema_version": 1,
            "status": "ok",
            "operation": "fixed-root-determinant-sample",
            "request_sha256": request_sha256,
            "omega_re": request["fixed_omega"]["real"],
            "omega_im": request["fixed_omega"]["imaginary"],
            "amplitude_re": request["amplitude"]["real"],
            "amplitude_im": request["amplitude"]["imaginary"],
            "determinant_re": format(determinant.real, ".17g"),
            "determinant_im": format(determinant.imag, ".17g"),
            "determinant_error_abs": format(determinant_error_abs, ".17g"),
            "determinant_error_status": "available/v1",
            "determinant_error_model_id": request["policy"][
                "determinant_error_model"
            ],
            "determinant_family": "exterior-wronskian/v1",
            "determinant_normalisation": "unit-asymptotic-branch-wronskian/v1",
            "branch_identity": "gsn-complex-rho/v1",
            "branch_authenticated": True,
            "semantic_precision_tier": request["semantic_precision_tier"],
            "working_precision_bits": request["working_precision_bits"],
            "readout_role": request["readout_role"],
        }
        return SimpleNamespace(
            response=response,
            request_binding=dict(request),
            request_sha256=request_sha256,
            runtime_identity_sha256="f" * 64,
            reused=False,
            cached_worker_response_receipt=None,
        )


class SelectiveReadoutPromotionTests(unittest.TestCase):
    def test_empirical_selective_journal_binds_receipt_without_ode_budget(self):
        """Catches dropping the receipt SHA from partial promoted work."""

        plan = build_campaign_plan(
            policy=NumericalPolicy(),
            backend_identity=VettedNativeDeterminantKernel.identity,
            precision_capabilities=PrecisionCapabilities((64, 80, 120)),
        )
        leaf = next(
            item for item in plan.leaves
            if item.role == "primary"
            and item.mechanism_id == "exterior-light-ring"
        )
        job = leaf.job

        class BinaryAxisLimited:
            identity = VettedNativeDeterminantKernel.identity

            def read_root(self, selected, amplitude, primary_predictor=None):
                value = complex(amplitude)
                response = complex(0.01, -0.02) if value.real else 1.0e-10 + 0j
                diagnostic = DiagnosticRootReadout(
                    omega_delta_from_primary=0j,
                    determinant_residual_abs=1.0e-12,
                    determinant_derivative_abs=1.0,
                    converged=True,
                )
                return RootReadout(
                    omega=selected.root.omega + response * value,
                    determinant_residual_abs=1.0e-12,
                    determinant_derivative_abs=1.0,
                    converged=True,
                    root_reference_id=selected.root.root_reference_id,
                    branch_id=selected.root.branch_id,
                    equation_id=selected.equation_id,
                    diagnostic_readouts={
                        family: diagnostic
                        for family in ("truncation", "resolution", "seed-path")
                    },
                )

            def closed_form_horizon_response(self, selected):
                return None

        previous = run_component(job, BinaryAxisLimited())
        receipt = load_default_calibration_receipt()
        promoted = JuliaPrecisionRootBackend(
            job.backend_identity,
            FakeAdapter(),
            40,
            empirical_control_profile=receipt.budget_for(
                "exterior-wronskian/v1", 40
            ),
            calibration_receipt=receipt,
            diagnostic_model_identity=EXTERIOR_DETERMINANT_ABSOLUTE_ERROR_CERTIFICATE,
        )
        with tempfile.TemporaryDirectory() as temporary, patch.dict(
            "os.environ",
            {"KERR_QNM_PARTIAL_COMPONENT_JOURNAL_ROOT": temporary},
        ):
            result = response_engine.run_selective_readout_promotion(
                job, previous, promoted
            )

        evidence = result.resolved_window["journal_evidence"]
        self.assertEqual(
            evidence["schema"],
            "windows-solver.selective-tier-journal-evidence/2",
        )
        self.assertEqual(evidence["evidence_level"], "SCREENED")
        self.assertEqual(
            evidence["evidence_disposition"],
            "EMPIRICAL_CERTIFICATE_AUTHENTICATED",
        )
        self.assertNotIn("ode_error_budget", evidence)
        self.assertEqual(
            evidence["promoted_control_calibration"]["receipt_sha256"],
            receipt.sha256,
        )
        self.assertEqual(
            evidence["empirical_control_profile_sha256"],
            promoted.scientific_runtime_for(job)[
                "empirical_control_profile_sha256"
            ],
        )
        binary_component = {"result": previous.to_mapping()}
        predecessor = StageOutcome(
            digits=64,
            numerical_state=previous.status.value,
            component_result=binary_component,
            local_disk_radius_abs=sum(previous.error_channels.values()),
            signed_error_channels=synthetic_stage_signed_error_channels(
                binary_component, sum(previous.error_channels.values())
            ),
        )
        validated_runtime, validated_readouts = (
            response_batches._validate_selective_tier_journal(
                leaf,
                "bigfloat-40",
                previous.resolved_window["readout_specific_promotion_plan"],
                evidence,
                response_batches._selective_predecessor_readouts(
                    leaf, predecessor
                ),
            )
        )
        self.assertEqual(validated_runtime, promoted.scientific_runtime_for(job))
        self.assertTrue(validated_readouts)

    def test_ordinary_component_cannot_mix_binary_and_promoted_diagnostic_sets(self):
        """Catches weakening the diagnostic-family gate outside selective recovery."""

        plan = build_campaign_plan(
            policy=NumericalPolicy(),
            backend_identity=VettedNativeDeterminantKernel.identity,
            precision_capabilities=PrecisionCapabilities((64, 80, 120)),
        )
        job = next(
            item.job for item in plan.leaves
            if item.role == "primary"
            and item.mechanism_id == "exterior-light-ring"
        )
        diagnostic = DiagnosticRootReadout(
            omega_delta_from_primary=0.0j,
            determinant_residual_abs=1.0e-12,
            determinant_derivative_abs=1.0,
            converged=True,
        )

        class MixedOrdinaryBackend:
            identity = VettedNativeDeterminantKernel.identity

            def read_root(self, selected, amplitude, primary_predictor=None):
                value = complex(amplitude)
                omega = selected.root.omega + complex(0.01, -0.02) * value
                if value.imag:
                    return _promoted_baseline(
                        selected,
                        omega=omega,
                        conditioning_mechanism=selected.mechanism_id,
                    )
                return RootReadout(
                    omega=omega,
                    determinant_residual_abs=1.0e-12,
                    determinant_derivative_abs=1.0,
                    converged=True,
                    root_reference_id=selected.root.root_reference_id,
                    branch_id=selected.root.branch_id,
                    equation_id=selected.equation_id,
                    diagnostic_readouts={
                        family: diagnostic
                        for family in ("truncation", "resolution", "seed-path")
                    },
                )

            def closed_form_horizon_response(self, selected):
                return None

        with self.assertRaisesRegex(ValueError, "families are inconsistent"):
            run_component(job, MixedOrdinaryBackend())

    def _run_semantic_tier_loop(
        self, *, resolve_at_120: bool, missing_budget_tier: int | None = None,
        through_campaign: bool = False,
    ):
        capabilities = PrecisionCapabilities((64, 80, 120))
        plan = build_campaign_plan(
            policy=NumericalPolicy(),
            backend_identity=VettedNativeDeterminantKernel.identity,
            precision_capabilities=capabilities,
        )
        leaf = next(
            item for item in plan.leaves
            if item.role == "primary" and item.mechanism_id == "exterior-light-ring"
        )

        class BinaryAxisLimited:
            identity = VettedNativeDeterminantKernel.identity

            def read_root(self, job, amplitude, primary_predictor=None):
                value = complex(amplitude)
                response = complex(0.01, -0.02) if value.real else 1.0e-10 + 0.0j
                diagnostic = DiagnosticRootReadout(
                    omega_delta_from_primary=0.0j,
                    determinant_residual_abs=1.0e-12,
                    determinant_derivative_abs=1.0,
                    converged=True,
                )
                return RootReadout(
                    omega=job.root.omega + response * value,
                    determinant_residual_abs=1.0e-12,
                    determinant_derivative_abs=1.0,
                    converged=True,
                    root_reference_id=job.root.root_reference_id,
                    branch_id=job.root.branch_id,
                    equation_id=job.equation_id,
                    diagnostic_readouts={
                        family: diagnostic
                        for family in ("truncation", "resolution", "seed-path")
                    },
                )

            def closed_form_horizon_response(self, job):
                return None

        previous_result = run_component(leaf.job, BinaryAxisLimited())
        if through_campaign:
            previous_result = replace(
                previous_result,
                status=ComponentStatus.NOT_CONVERGED,
                convergence_basis="UNRESOLVED",
                response=None,
                signed_root_crosscheck=None,
            )
        previous = SimpleNamespace(
            digits=64,
            component_result={"result": previous_result.to_mapping()},
            local_disk_radius_abs=0.0,
        )
        calls = {40: [], 80: [], 120: []}
        supplied_budget_hashes = []

        class SemanticBackend:
            identity = VettedNativeDeterminantKernel.identity

            def __init__(self, digits, budget):
                self.digits = digits
                self.budget = budget

            def scientific_runtime_for(self, job):
                return {
                    "precision_digits": self.digits,
                    "working_precision_bits": working_precision_bits(
                        PrecisionTier(f"bigfloat-{self.digits}")
                    ),
                    "semantic_precision_tier": f"bigfloat-{self.digits}",
                    "refinement_level": 0,
                    "regularised_gsn_precision_policy": dict(
                        response_engine.regularised_gsn_precision_policy(
                            job.mechanism_id
                        )
                    ),
                }

            def preview_root_request(
                self, job, amplitude, primary_predictor=None,
                primary_predictor_kind=None, readout_role=None,
            ):
                del readout_role
                return JuliaPrecisionRootBackend(
                    job.backend_identity,
                    object(),
                    self.digits,
                    ode_error_budget=self.budget,
                )._request(
                    job,
                    amplitude,
                    primary_predictor,
                    primary_predictor_kind,
                )

            def read_root(self, job, amplitude, primary_predictor=None):
                value = complex(amplitude)
                calls[self.digits].append(value)
                response = (
                    complex(0.01, -0.02)
                    if self.digits == 120 and resolve_at_120
                    else 1.0e-10 + 0.0j
                )
                baseline = _promoted_baseline(
                    job,
                    omega=job.root.omega + response * value,
                    conditioning_mechanism=job.mechanism_id,
                )
                # This fixture deliberately exercises the historical injected
                # ODE-budget tier loop.  Persist it as wire 9, which predates
                # the authenticated raw-count field, instead of claiming the
                # current empirical exterior certificate contract.
                baseline = replace(
                    baseline,
                    diagnostic_readouts={
                        family: replace(
                            diagnostic,
                            fixed_root_evidence=replace(
                                diagnostic.fixed_root_evidence,
                                raw_determinant_evaluation_count=None,
                            ),
                        )
                        for family, diagnostic in (
                            baseline.diagnostic_readouts.items()
                        )
                    },
                )
                request = self.preview_root_request(
                    job, value, primary_predictor
                )
                runtime = self.scientific_runtime_for(job)
                material = {
                    "schema": response_engine.WORKER_RESPONSE_RECEIPT_SCHEMA,
                    "request_binding": request,
                    "request_sha256": hashlib.sha256(
                        canonical_json_bytes(request)
                    ).hexdigest(),
                    "scientific_runtime_sha256": hashlib.sha256(
                        canonical_json_bytes(runtime)
                    ).hexdigest(),
                    "worker_response_schema_version": (
                        9
                    ),
                    "root_residual_abs_text": str(
                        baseline.normalised_determinant_abs
                    ),
                    "raw_determinant_abs_text": None,
                    "raw_determinant_evidence_status": "not-applicable/v1",
                    "promoted_root_readout_policy": (
                        response_engine.PROMOTED_ROOT_READOUT_POLICY
                    ),
                    "primary_acceptance_sha256": hashlib.sha256(
                        canonical_json_bytes(
                            baseline.primary_acceptance.to_mapping()
                        )
                    ).hexdigest(),
                    "horizon_endpoint_search_evidence": None,
                }
                receipt = {
                    **material,
                    "receipt_sha256": hashlib.sha256(
                        canonical_json_bytes(material)
                    ).hexdigest(),
                }
                return replace(baseline, worker_response_receipt=receipt)

        budgets = {
            digits: synthetic_ode_error_budget(digits)
            for digits in (40, 80, 120)
        }
        if missing_budget_tier is not None:
            budgets.pop(missing_budget_tier)
        self._last_semantic_calls = calls
        self._last_supplied_budget_hashes = supplied_budget_hashes
        campaign = NativeCampaignStageBackend(
            NativeDeterminantAdapter(
                identity=VettedNativeDeterminantKernel.identity,
                kernel=SimpleNamespace(),
            ),
            capabilities,
            GeneratedGsnCache(
                ("gsn-000001",), Path(".runtime/generated/gsn/selective-loop.json"),
                "a" * 64, (GsnParameterPair(19, 20, leaf.job.mode.m),),
            ),
            SimpleNamespace(runtime_provenance={}),
            ode_error_budgets=budgets,
        )

        def backend_factory(identity, adapter, digits, **kwargs):
            budget = kwargs["ode_error_budget"]
            supplied_budget_hashes.append((
                digits,
                hashlib.sha256(canonical_json_bytes(budget.to_mapping())).hexdigest(),
            ))
            return SemanticBackend(digits, budget)

        with tempfile.TemporaryDirectory() as temporary, patch.dict(
            "os.environ",
            {"KERR_QNM_PARTIAL_COMPONENT_JOURNAL_ROOT": temporary},
        ), patch(
            "windows_solver.response_batches.JuliaPrecisionRootBackend",
            side_effect=backend_factory,
        ), patch(
            "windows_solver.response_batches.run_promoted_exterior_component",
            side_effect=AssertionError("whole component promotion is forbidden"),
        ):
            if through_campaign:
                binary_component = {
                    "evidence_kind": "native-task-008-component-engine",
                    "result": previous_result.to_mapping(),
                    "scientific_runtime": {},
                }
                binary = StageOutcome(
                    digits=64,
                    numerical_state=previous_result.status.value,
                    component_result=binary_component,
                    local_disk_radius_abs=sum(previous_result.error_channels.values()),
                    signed_error_channels=synthetic_stage_signed_error_channels(
                        binary_component,
                        sum(previous_result.error_channels.values()),
                    ),
                )

                class CampaignBackend:
                    identity = campaign.identity
                    precision_capabilities = capabilities

                    def execute_stage(self, selected, digits):
                        return binary

                    def execute_stage_with_predictor(
                        self, selected, digits, response_predictor
                    ):
                        return binary

                    def execute_promoted_stage(
                        self, selected, digits, previous_outcomes
                    ):
                        return campaign.execute_promoted_stage(
                            selected, digits, previous_outcomes
                        )

                    def execute_promoted_stage_with_predictor(
                        self, selected, digits, previous_outcomes, response_predictor
                    ):
                        return campaign.execute_promoted_stage_with_predictor(
                            selected, digits, previous_outcomes, response_predictor
                        )

                selection = build_campaign_selection(
                    plan, role="primary", leaf_ids=(leaf.leaf_id,)
                )
                checkpoint = Path(temporary) / "campaign-checkpoint.json"
                summary = run_campaign_selection(
                    plan, selection, CampaignBackend(), checkpoint, resume=False
                )
                self._last_campaign_summary = summary
                self._last_campaign_reloaded = validate_campaign_checkpoint(
                    plan, checkpoint
                )
                self._last_campaign_checkpoint = json.loads(
                    checkpoint.read_text(encoding="utf-8")
                )
                self._last_campaign_plan = plan
                outcome = summary.records[0].stages[-1].outcome
            else:
                outcome = campaign.execute_promoted_stage_with_predictor(
                    leaf, 80, (previous,), None
                )
            journals = tuple(Path(temporary).glob("*.json"))
        return outcome, previous_result, calls, supplied_budget_hashes, budgets, journals

    @staticmethod
    def _reseal_campaign(value):
        for record in value["records"]:
            for stage in record["stages"]:
                source_sha256 = hashlib.sha256(
                    canonical_json_bytes(stage["component_result"])
                ).hexdigest()
                for channel in stage["signed_error_channels"]:
                    channel["provenance"]["source_sha256"] = source_sha256
                stage["stage_sha256"] = hashlib.sha256(
                    canonical_json_bytes({
                        key: item for key, item in stage.items()
                        if key != "stage_sha256"
                    })
                ).hexdigest()
            record["record_sha256"] = hashlib.sha256(
                canonical_json_bytes({
                    key: item for key, item in record.items()
                    if key != "record_sha256"
                })
            ).hexdigest()
        value["records_sha256"] = hashlib.sha256(
            canonical_json_bytes(value["records"])
        ).hexdigest()

    @staticmethod
    def _current_selective_journal(checkpoint):
        result = checkpoint["records"][0]["stages"][-1][
            "component_result"
        ]["result"]
        return result["resolved_window"]["journal_evidence"]

    @staticmethod
    def _selective_journal_for_tier(checkpoint, tier):
        result = checkpoint["records"][0]["stages"][-1][
            "component_result"
        ]["result"]
        window = result["resolved_window"]
        if window["executed_precision_tier"] == tier:
            return window["journal_evidence"]
        return next(
            item["journal_evidence"]
            for item in window["prior_tier_recovery_evidence"]
            if item["executed_precision_tier"] == tier
        )

    @staticmethod
    def _reseal_current_selective_request(journal, mutate):
        old_id = journal["promoted_work_unit_ids"][0]
        snapshot = journal["journal"]
        entry = snapshot["entries"].pop(old_id)
        wrapper = entry["worker_response_receipt"]
        output = wrapper["output"]
        receipt = output["worker_response_receipt"]
        request = receipt["request_binding"]
        mutate(request)
        request_sha256 = hashlib.sha256(
            canonical_json_bytes(request)
        ).hexdigest()
        receipt["request_sha256"] = request_sha256
        receipt["receipt_sha256"] = hashlib.sha256(canonical_json_bytes({
            key: item for key, item in receipt.items()
            if key != "receipt_sha256"
        })).hexdigest()
        entry["request_sha256"] = request_sha256
        entry["worker_response_receipt_sha256"] = hashlib.sha256(
            canonical_json_bytes(wrapper)
        ).hexdigest()
        work_unit = {
            key: item for key, item in entry.items()
            if key not in {
                "entry_sha256", "work_unit_id", "worker_response_receipt",
                "worker_response_receipt_sha256",
            }
        }
        new_id = hashlib.sha256(canonical_json_bytes(work_unit)).hexdigest()
        entry["work_unit_id"] = new_id
        entry["entry_sha256"] = hashlib.sha256(canonical_json_bytes({
            key: item for key, item in entry.items() if key != "entry_sha256"
        })).hexdigest()
        snapshot["entries"][new_id] = entry
        snapshot["expected_work_unit_ids"] = [
            new_id if item == old_id else item
            for item in snapshot["expected_work_unit_ids"]
        ]
        journal["promoted_work_unit_ids"] = [
            new_id if item == old_id else item
            for item in journal["promoted_work_unit_ids"]
        ]
        snapshot["journal_sha256"] = hashlib.sha256(canonical_json_bytes({
            key: item for key, item in snapshot.items()
            if key != "journal_sha256"
        })).hexdigest()
        journal["journal_sha256"] = snapshot["journal_sha256"]

    def test_checkpoint_rejects_resealed_selective_tier_without_worker_receipt(self):
        """Catches accepting labels after the per-tier worker proof is stripped."""

        self._run_semantic_tier_loop(resolve_at_120=True, through_campaign=True)
        forged = self._last_campaign_checkpoint
        journal = self._current_selective_journal(forged)
        promoted_id = journal["promoted_work_unit_ids"][0]
        snapshot = journal["journal"]
        entry = snapshot["entries"][promoted_id]
        output = entry["worker_response_receipt"]["output"]
        output.pop("worker_response_receipt")
        wrapper = entry["worker_response_receipt"]
        entry["worker_response_receipt_sha256"] = hashlib.sha256(
            canonical_json_bytes(wrapper)
        ).hexdigest()
        entry_material = {
            key: item for key, item in entry.items() if key != "entry_sha256"
        }
        entry["entry_sha256"] = hashlib.sha256(
            canonical_json_bytes(entry_material)
        ).hexdigest()
        journal_material = {
            key: item for key, item in snapshot.items()
            if key != "journal_sha256"
        }
        snapshot["journal_sha256"] = hashlib.sha256(
            canonical_json_bytes(journal_material)
        ).hexdigest()
        journal["journal_sha256"] = snapshot["journal_sha256"]
        self._reseal_campaign(forged)
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "stripped.json"
            path.write_bytes(canonical_json_bytes(forged))
            with self.assertRaisesRegex(ValueError, "worker.*receipt"):
                validate_campaign_checkpoint(self._last_campaign_plan, path)

    def test_checkpoint_rejects_resealed_selective_tier_journal_digest(self):
        """Catches accepting a forged per-tier journal projection digest."""

        self._run_semantic_tier_loop(resolve_at_120=True, through_campaign=True)
        forged = self._last_campaign_checkpoint
        journal = self._current_selective_journal(forged)
        journal["journal_sha256"] = "0" * 64
        self._reseal_campaign(forged)
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "forged-digest.json"
            path.write_bytes(canonical_json_bytes(forged))
            with self.assertRaisesRegex(ValueError, "journal"):
                validate_campaign_checkpoint(self._last_campaign_plan, path)

    def test_checkpoint_binds_terminal_readout_to_selective_journal_output(self):
        """Catches a branch-valid terminal root detached from its tier journal."""

        self._run_semantic_tier_loop(resolve_at_120=True, through_campaign=True)
        forged = self._last_campaign_checkpoint
        result = forged["records"][0]["stages"][-1][
            "component_result"
        ]["result"]
        journal = self._current_selective_journal(forged)
        entry = journal["journal"]["entries"][
            journal["promoted_work_unit_ids"][0]
        ]
        role, _, epsilon_text = entry["readout_role"].partition("@")
        level = next(
            item
            for item in result["levels"]
            if item["epsilon"] == float(epsilon_text)
        )
        readout = level[role.replace("-", "_")]
        readout["omega"]["real"] += 1.0e-12
        if role.startswith("imaginary-"):
            plus = complex(
                level["imaginary_plus"]["omega"]["real"],
                level["imaginary_plus"]["omega"]["imaginary"],
            )
            minus = complex(
                level["imaginary_minus"]["omega"]["real"],
                level["imaginary_minus"]["omega"]["imaginary"],
            )
            secant = (plus - minus) / (2.0j * level["epsilon"])
            level["imaginary_secant"] = {
                "real": secant.real,
                "imaginary": secant.imag,
            }
        else:
            plus = complex(
                level["real_plus"]["omega"]["real"],
                level["real_plus"]["omega"]["imaginary"],
            )
            minus = complex(
                level["real_minus"]["omega"]["real"],
                level["real_minus"]["omega"]["imaginary"],
            )
            secant = (plus - minus) / (2.0 * level["epsilon"])
            level["real_secant"] = {
                "real": secant.real,
                "imaginary": secant.imag,
            }
        self._reseal_campaign(forged)

        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "detached-terminal-readout.json"
            path.write_bytes(canonical_json_bytes(forged))
            with self.assertRaisesRegex(
                ValueError, "journal.*terminal|terminal.*journal"
            ):
                validate_campaign_checkpoint(self._last_campaign_plan, path)

    def test_checkpoint_rejects_resealed_selective_terminal_readout_omission(self):
        """The terminal result must project every predecessor/journal readout."""

        self._run_semantic_tier_loop(resolve_at_120=True, through_campaign=True)
        forged = self._last_campaign_checkpoint
        result = forged["records"][0]["stages"][-1][
            "component_result"
        ]["result"]
        self.assertGreaterEqual(len(result["levels"]), 4)
        result["levels"].pop(0)
        self._reseal_campaign(forged)
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "omitted-terminal-readout.json"
            path.write_bytes(canonical_json_bytes(forged))
            with self.assertRaisesRegex(
                ValueError, "terminal.*journal|resolved.window"
            ):
                validate_campaign_checkpoint(self._last_campaign_plan, path)

    def test_checkpoint_rejects_resealed_selective_predictor_forgery(self):
        """Catches self-consistent requests detached from predecessor roots."""

        for tier in ("bigfloat-40", "bigfloat-80", "bigfloat-120"):
            with self.subTest(tier=tier):
                self._run_semantic_tier_loop(
                    resolve_at_120=True, through_campaign=True
                )
                forged = self._last_campaign_checkpoint
                journal = self._selective_journal_for_tier(forged, tier)
                self._reseal_current_selective_request(
                    journal,
                    lambda request: request["primary_predictor"].__setitem__(
                        "real", "123.5"
                    ),
                )
                self._reseal_campaign(forged)
                with tempfile.TemporaryDirectory() as temporary:
                    path = Path(temporary) / f"forged-predictor-{tier}.json"
                    path.write_bytes(canonical_json_bytes(forged))
                    with self.assertRaisesRegex(
                        ValueError, "canonical.*request|predictor"
                    ):
                        validate_campaign_checkpoint(
                            self._last_campaign_plan, path
                        )

    def test_checkpoint_rejects_resealed_selective_request_policy_or_support(self):
        """Catches request fields authenticated only by attacker-recomputed hashes."""

        for label, mutate in (
            (
                "policy",
                lambda request: request["policy"].__setitem__(
                    "endpoint_series_order", 999
                ),
            ),
            (
                "support",
                lambda request: request["support"].__setitem__(
                    "outer_radius", "999"
                ),
            ),
        ):
            with self.subTest(label=label):
                self._run_semantic_tier_loop(
                    resolve_at_120=True, through_campaign=True
                )
                forged = self._last_campaign_checkpoint
                journal = self._current_selective_journal(forged)
                self._reseal_current_selective_request(journal, mutate)
                self._reseal_campaign(forged)
                with tempfile.TemporaryDirectory() as temporary:
                    path = Path(temporary) / f"forged-{label}.json"
                    path.write_bytes(canonical_json_bytes(forged))
                    with self.assertRaisesRegex(ValueError, "canonical.*request"):
                        validate_campaign_checkpoint(
                            self._last_campaign_plan, path
                        )

    def test_semantic_selective_loop_executes_40_80_120_without_legacy_slots(self):
        outcome, previous, calls, hashes, budgets, journals = (
            self._run_semantic_tier_loop(resolve_at_120=True)
        )
        expected = {
            complex(0.0, item["epsilon"] if item["readout_role"].endswith("plus") else -item["epsilon"])
            for item in previous.resolved_window["readout_specific_promotion_plan"]
        }
        self.assertEqual([digits for digits, _ in hashes], [40, 80, 120])
        self.assertEqual(
            hashes,
            [
                (digits, hashlib.sha256(canonical_json_bytes(
                    budgets[digits].to_mapping()
                )).hexdigest())
                for digits in (40, 80, 120)
            ],
        )
        for digits in (40, 80, 120):
            self.assertEqual(set(calls[digits]), expected)
            self.assertTrue(all(value and value.real == 0.0 for value in calls[digits]))
        result = outcome.component_result["result"]
        self.assertEqual(result["status"], "CONVERGED")
        self.assertEqual(
            outcome.component_result["semantic_selective_tier_trace"],
            ["bigfloat-40", "bigfloat-80", "bigfloat-120"],
        )
        self.assertEqual(
            result["resolved_window"]["promoted_readout_count_by_tier"],
            {tier: len(expected) for tier in (
                "bigfloat-40", "bigfloat-80", "bigfloat-120"
            )},
        )
        self.assertEqual(len(journals), 3)

    def test_semantic_selective_loop_exhausts_after_bigfloat120(self):
        outcome, _, calls, _, _, _ = self._run_semantic_tier_loop(
            resolve_at_120=False
        )
        self.assertNotEqual(outcome.numerical_state, "CONVERGED")
        self.assertEqual(
            outcome.component_result["semantic_selective_tier_trace"],
            ["bigfloat-40", "bigfloat-80", "bigfloat-120"],
        )
        self.assertTrue(all(calls[digits] for digits in (40, 80, 120)))
        self.assertIsNone(
            outcome.component_result["result"]["resolved_window"][
                "next_precision_tier"
            ]
        )

    def test_semantic_selective_loop_blocks_before_missing_bigfloat80_budget(self):
        with self.assertRaisesRegex(RuntimeError, re.escape(ODE_CALIBRATION_BLOCKER)):
            self._run_semantic_tier_loop(
                resolve_at_120=True, missing_budget_tier=80
            )
        self.assertTrue(self._last_semantic_calls[40])
        self.assertEqual(self._last_semantic_calls[80], [])
        self.assertEqual(self._last_semantic_calls[120], [])
        self.assertEqual(
            [digits for digits, _ in self._last_supplied_budget_hashes], [40]
        )

    def test_campaign_selection_publishes_converged_semantic_selective_stage(self):
        self._run_semantic_tier_loop(resolve_at_120=True, through_campaign=True)
        self.assertEqual(self._last_campaign_summary.records[0].state, "PRODUCED")
        self.assertEqual(self._last_campaign_reloaded.records[0].state, "PRODUCED")
        self.assertEqual(len(self._last_campaign_summary.records[0].stages), 2)

    def test_campaign_selection_preserves_exhausted_semantic_selective_stage(self):
        self._run_semantic_tier_loop(resolve_at_120=False, through_campaign=True)
        self.assertEqual(self._last_campaign_summary.records[0].state, "UNRESOLVED")
        self.assertEqual(self._last_campaign_reloaded.records[0].state, "UNRESOLVED")
        self.assertEqual(len(self._last_campaign_summary.records[0].stages), 2)

    def test_campaign_executes_only_planned_signed_pair_at_bigfloat40(self) -> None:
        capabilities = PrecisionCapabilities((64, 80, 120))
        plan = build_campaign_plan(
            policy=NumericalPolicy(),
            backend_identity=VettedNativeDeterminantKernel.identity,
            precision_capabilities=capabilities,
        )
        leaf = next(
            item for item in plan.leaves
            if item.role == "primary" and item.mechanism_id == "exterior-light-ring"
        )

        class BinaryAxisLimited:
            identity = VettedNativeDeterminantKernel.identity

            def read_root(self, job, amplitude, primary_predictor=None):
                value = complex(amplitude)
                response = complex(0.125, -0.375) if value.real else 1.0e-10 + 0.0j
                return RootReadout(
                    omega=job.root.omega + response * value,
                    determinant_residual_abs=1.0e-12,
                    determinant_derivative_abs=1.0,
                    converged=True,
                    root_reference_id=job.root.root_reference_id,
                    branch_id=job.root.branch_id,
                    equation_id=job.equation_id,
                )

            def closed_form_horizon_response(self, job):
                return None

        previous_result = run_component(leaf.job, BinaryAxisLimited())
        self.assertEqual(previous_result.status.value, "AXIS_MISMATCH")
        previous = SimpleNamespace(
            digits=64,
            component_result={"result": previous_result.to_mapping()},
            local_disk_radius_abs=0.0,
        )
        promoted_calls = []

        class SelectiveBackend:
            identity = VettedNativeDeterminantKernel.identity
            digits = 40

            def read_root(self, job, amplitude, primary_predictor=None):
                promoted_calls.append(complex(amplitude))
                value = complex(amplitude)
                return RootReadout(
                    omega=job.root.omega + complex(0.125, -0.375) * value,
                    determinant_residual_abs=1.0e-16,
                    determinant_derivative_abs=1.0,
                    converged=True,
                    root_reference_id=job.root.root_reference_id,
                    branch_id=job.root.branch_id,
                    equation_id=job.equation_id,
                )

            def scientific_runtime_for(self, job):
                return {"semantic_precision_tier": "bigfloat-40"}

        generated = GeneratedGsnCache(
            ("gsn-000001",), Path(".runtime/generated/gsn/selective-test.json"),
            "a" * 64, (GsnParameterPair(19, 20, leaf.job.mode.m),),
        )
        campaign = NativeCampaignStageBackend(
            NativeDeterminantAdapter(
                identity=VettedNativeDeterminantKernel.identity,
                kernel=SimpleNamespace(),
            ),
            capabilities,
            generated,
            SimpleNamespace(runtime_provenance={}),
            ode_error_budget=synthetic_ode_error_budget(40),
        )
        selective = SelectiveBackend()
        expected = {
            complex(0.0, sign * item["epsilon"])
            for item in previous_result.resolved_window[
                "readout_specific_promotion_plan"
            ]
            for sign in ([1] if item["readout_role"] == "imaginary_plus" else [-1])
        }
        with tempfile.TemporaryDirectory() as temporary, patch.dict(
            "os.environ",
            {"KERR_QNM_PARTIAL_COMPONENT_JOURNAL_ROOT": temporary},
        ), patch(
            "windows_solver.response_batches.JuliaPrecisionRootBackend",
            return_value=selective,
        ), patch(
            "windows_solver.response_batches.run_promoted_exterior_component",
            side_effect=AssertionError("whole component promotion is forbidden"),
        ):
            outcome = campaign.execute_promoted_stage_with_predictor(
                leaf, 80, (previous,), None
            )
            journals = tuple(Path(temporary).glob("*.json"))
            self.assertEqual(len(journals), 1)
            journal = PartialComponentJournal.load(journals[0])
            promoted_entries = tuple(
                entry for entry in journal.entries.values()
                if entry.precision_tier is PrecisionTier.BIGFLOAT_40
            )
            self.assertEqual(len(promoted_entries), len(expected))

        self.assertEqual(set(promoted_calls), expected)
        self.assertNotIn(0.0j, promoted_calls)
        self.assertTrue(all(value.real == 0.0 for value in promoted_calls))
        mapping = outcome.component_result["result"]
        self.assertEqual(mapping["resolved_window"]["executed_precision_tier"], "bigfloat-40")
        evidence = mapping["resolved_window"]["journal_evidence"]
        self.assertEqual(evidence["evidence_level"], "NOT_SCREENED")
        self.assertEqual(
            evidence["evidence_disposition"],
            "BLOCKED_BY_REVIEWED_ERROR_EVIDENCE",
        )
        self.assertNotIn("promoted_control_calibration", evidence)
        self.assertNotIn("empirical_control_profile", evidence)
        self.assertNotIn("empirical_control_profile_sha256", evidence)
        self.assertEqual(
            mapping["resolved_window"]["promoted_readout_count_by_tier"],
            {"bigfloat-40": len(expected)},
        )

    def test_bigfloat40_readout_surface_is_semantic_not_legacy_campaign_order(self) -> None:
        capabilities = PrecisionCapabilities((64, 80, 120))
        plan = build_campaign_plan(
            policy=NumericalPolicy(),
            backend_identity=VettedNativeDeterminantKernel.identity,
            precision_capabilities=capabilities,
        )
        job = next(
            leaf.job
            for leaf in plan.leaves
            if leaf.role == "primary" and leaf.mechanism_id == "exterior-light-ring"
        )
        backend = JuliaPrecisionRootBackend(
            VettedNativeDeterminantKernel.identity,
            SimpleNamespace(runtime_provenance={}),
            40,
        )
        runtime = backend.scientific_runtime

        self.assertEqual(runtime["precision_digits"], 40)
        self.assertEqual(runtime["semantic_precision_tier"], PrecisionTier.BIGFLOAT_40.value)
        self.assertEqual(
            runtime["working_precision_bits"],
            working_precision_bits(PrecisionTier.BIGFLOAT_40),
        )
        with self.assertRaisesRegex(RuntimeError, re.escape(ODE_CALIBRATION_BLOCKER)):
            backend._request(job, 0.0j)
        with self.assertRaisesRegex(ValueError, "precision capabilities"):
            PrecisionCapabilities((64, 40, 80, 120))

    def test_native_promoted_exterior_routes_to_fixed_root_derivative(self) -> None:
        capabilities = PrecisionCapabilities((64, 80, 120))
        plan = build_campaign_plan(
            policy=NumericalPolicy(),
            backend_identity=VettedNativeDeterminantKernel.identity,
            precision_capabilities=capabilities,
        )
        leaf = next(
            item
            for item in plan.leaves
            if item.role == "primary" and item.mechanism_id == "exterior-light-ring"
        )
        generated = GeneratedGsnCache(
            ("gsn-000001",),
            Path(".runtime/generated/gsn/selective-test.json"),
            "a" * 64,
            (GsnParameterPair(19, 20, leaf.job.mode.m),),
        )
        adapter = CampaignSampleAdapter()
        backend = NativeCampaignStageBackend(
            NativeDeterminantAdapter(
                identity=VettedNativeDeterminantKernel.identity,
                kernel=SimpleNamespace(),
            ),
            capabilities,
            generated,
            adapter,
        )
        binary64_result = _result(leaf.job, 0.25 + 0.5j)
        previous = SimpleNamespace(
            digits=64,
            component_result={
                "evidence_kind": "native-task-008-component-engine",
                "result": binary64_result.to_mapping(),
                "scientific_runtime": {},
            },
            local_disk_radius_abs=sum(binary64_result.error_channels.values()),
        )

        outcome = backend.execute_promoted_stage_with_predictor(
            leaf,
            80,
            (previous,),
            response_predictor=None,
        )
        operations = [request["operation"] for request in adapter.requests]
        root_requests = [
            request for request in adapter.requests if request["operation"] == "root-readout"
        ]

        self.assertEqual(
            operations,
            ["root-readout"]
            + ["fixed-root-determinant-sample"] * 8,
        )
        self.assertEqual(
            [request["amplitude"] for request in root_requests],
            [{"real": "0", "imaginary": "0"}],
        )
        mapping = outcome.component_result["result"]
        self.assertEqual(
            mapping["component_scientific_identity"],
            EXTERIOR_DERIVATIVE_COMPONENT_IDENTITY,
        )
        self.assertEqual(mapping["status"], "CONVERGED")
        self.assertNotIn("failure_code", mapping["derivative_evidence"])
        self.assertEqual(
            len(mapping["derivative_evidence"]["fixed_root_samples"]),
            8,
        )
        self.assertGreater(outcome.local_disk_radius_abs, 0.0)


if __name__ == "__main__":
    unittest.main()
