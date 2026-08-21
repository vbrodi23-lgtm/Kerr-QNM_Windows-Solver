from __future__ import annotations

from dataclasses import replace
from decimal import Decimal, localcontext
import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

import windows_solver.response_batches as response_batches
from tests.test_native_campaign_backend import _failed_preflight_attempt
from tests.fixtures import valid_control_failure_diagnostics
import tests.test_promoted_exterior_derivative as exterior_derivative_fixtures
from tests.test_promoted_exterior_derivative import FixedRootOnlyBackend
from tests.test_solved_leaf_cache import _production_outcome
from windows_solver.contracts import canonical_json_bytes
from windows_solver.gsn_cache_producer import GeneratedGsnCache, GsnParameterPair
from windows_solver.julia_response_backend import (
    JuliaNumericalControlError,
    JuliaPrecisionRootBackend,
)
from windows_solver.partial_component_checkpoint import PartialComponentJournal
from windows_solver.precision_tiers import PrecisionTier
from windows_solver.promoted_control_calibration import (
    load_default_calibration_receipt,
)
from windows_solver.response_batches import (
    CampaignLeafRecord,
    NativeCampaignStageBackend,
    PrecisionCapabilities,
    StageOutcome,
    _authenticated_solved_leaf_lookup,
    _campaign_stage_record,
    _component_stage_signed_error_channels,
    _primary_precision120_decision,
    _primary_precision120_terminal_state,
    _stage_with_promotion_decision,
    _validate_component_result,
    _validate_failed_preflight_recovery_stage,
    _validate_record_semantics,
    build_campaign_plan,
    build_campaign_selection,
    run_campaign_selection,
    scientific_computation_identity_sha256,
    validate_campaign_checkpoint,
)
from windows_solver.response_engine import (
    ComponentResult,
    ComponentStatus,
    NativeDeterminantAdapter,
    NumericalPolicy,
    VettedNativeDeterminantKernel,
)
from windows_solver.root_readout_cache import runtime_identity_sha256
from windows_solver.solved_leaf_cache import (
    SolvedLeafLookupStatus,
    SolvedLeafStore,
)


LEAF_42_ID = (
    "b-prime-leaf-5a27a5fdc15f95de33d6773b16f89a9f594fe5ffd018f9ee94bbab91949fd653"
)
FIXED_ROOT_SKIP_REASON = "NOT_REQUIRED_BY_FIXED_ROOT_DERIVATIVE_POLICY"
BINARY_RESPONSE_UNAVAILABLE = "BINARY64_COMPONENT_RESPONSE_UNAVAILABLE"


class _ScientificFixedRootBackend(FixedRootOnlyBackend):
    """Fast worker-boundary substitute retaining real component orchestration."""

    def __init__(self, job, baseline, digits: int) -> None:
        tier = {
            80: PrecisionTier.BIGFLOAT_80,
            120: PrecisionTier.BIGFLOAT_120,
        }[digits]
        super().__init__(
            job,
            baseline,
            runtime_identity=runtime_identity_sha256({}),
            sample_tier=tier,
        )
        self.digits = digits
        self.refinement = 0

    def scientific_runtime_for(self, job):
        receipt = load_default_calibration_receipt()
        return JuliaPrecisionRootBackend(
            job.backend_identity,
            SimpleNamespace(runtime_provenance={}),
            self.digits,
            empirical_control_profile=receipt.budget_for(
                "exterior-wronskian/v1", self.digits
            ),
            calibration_receipt=receipt,
        ).scientific_runtime_for(job)


class _NoisyScientificFixedRootBackend(_ScientificFixedRootBackend):
    def sample_fixed_root_determinant(self, *args, **kwargs):
        sample = super().sample_fixed_root_determinant(*args, **kwargs)
        error_abs = 10.0 * abs(sample.amplitude)
        receipt = dict(sample.worker_response_receipt)
        response = dict(receipt["response_binding"])
        response["determinant_error_abs"] = str(error_abs)
        receipt["response_binding"] = response
        receipt["response_sha256"] = hashlib.sha256(
            canonical_json_bytes(response)
        ).hexdigest()
        return replace(
            sample,
            determinant_error_abs=error_abs,
            worker_response_receipt=receipt,
            worker_response_receipt_sha256=hashlib.sha256(
                canonical_json_bytes(receipt)
            ).hexdigest(),
        )


class _PrecisionLimitedResponseSampleBackend(_NoisyScientificFixedRootBackend):
    """Expose response-tier conditioning without changing root evidence."""

    def __init__(self, job, baseline, digits: int) -> None:
        super().__init__(job, baseline, digits)
        conditioning = baseline.numerical_conditioning
        if conditioning is None:
            raise ValueError("test baseline lacks numerical conditioning")
        self.sample_conditioning = replace(
            conditioning,
            predicted_reliable_digits=Decimal("11"),
            required_reliable_digits=Decimal("24"),
            precision_limited=True,
        )

    def sample_fixed_root_determinant(self, *args, **kwargs):
        sample = super().sample_fixed_root_determinant(*args, **kwargs)
        receipt = dict(sample.worker_response_receipt)
        response = dict(receipt["response_binding"])
        response.update({
            "schema_version": 2,
            "numerical_conditioning": self.sample_conditioning.to_mapping(),
        })
        receipt.update({
            "schema": (
                "windows-solver.fixed-root-determinant-sample-receipt/2"
            ),
            "response_binding": response,
            "response_sha256": hashlib.sha256(
                canonical_json_bytes(response)
            ).hexdigest(),
        })
        return replace(
            sample,
            numerical_conditioning=self.sample_conditioning,
            worker_response_receipt=receipt,
            worker_response_receipt_sha256=hashlib.sha256(
                canonical_json_bytes(receipt)
            ).hexdigest(),
        )


class _FrequencyLimitedResponseSampleBackend(_ScientificFixedRootBackend):
    """Make only the Dω h/h2 family request a response-tier escalation."""

    def __init__(self, job, baseline, digits: int) -> None:
        super().__init__(job, baseline, digits)
        conditioning = baseline.numerical_conditioning
        if conditioning is None:
            raise ValueError("test baseline lacks numerical conditioning")
        self.frequency_conditioning = replace(
            conditioning,
            predicted_reliable_digits=Decimal("11"),
            required_reliable_digits=Decimal("24"),
            precision_limited=True,
        )

    def sample_fixed_root_determinant(self, *args, **kwargs):
        sample = super().sample_fixed_root_determinant(*args, **kwargs)
        conditioned = (
            self.frequency_conditioning
            if sample.readout_role.startswith("frequency-")
            else self.baseline.numerical_conditioning
        )
        assert conditioned is not None
        receipt = dict(sample.worker_response_receipt)
        response = dict(receipt["response_binding"])
        response.update({
            "schema_version": 2,
            "numerical_conditioning": conditioned.to_mapping(),
        })
        receipt.update({
            "schema": "windows-solver.fixed-root-determinant-sample-receipt/2",
            "response_binding": response,
            "response_sha256": hashlib.sha256(
                canonical_json_bytes(response)
            ).hexdigest(),
        })
        return replace(
            sample,
            numerical_conditioning=conditioned,
            worker_response_receipt=receipt,
            worker_response_receipt_sha256=hashlib.sha256(
                canonical_json_bytes(receipt)
            ).hexdigest(),
        )


class _RootForbiddenScientificFixedRootBackend(_ScientificFixedRootBackend):
    """A response worker whose root API is an executable air-gap alarm."""

    def read_root(self, *args, **kwargs):
        raise AssertionError("root-sealed response repair must not call read_root")

    def sample_fixed_root_determinant(self, *args, **kwargs):
        sample = super().sample_fixed_root_determinant(*args, **kwargs)
        job = args[0]
        receipt = dict(sample.worker_response_receipt)
        receipt["scientific_runtime_sha256"] = hashlib.sha256(
            canonical_json_bytes(self.scientific_runtime_for(job))
        ).hexdigest()
        return replace(
            sample,
            worker_response_receipt=receipt,
            worker_response_receipt_sha256=hashlib.sha256(
                canonical_json_bytes(receipt)
            ).hexdigest(),
        )


class _RootForbiddenScientificFrequencyBackend(
    _RootForbiddenScientificFixedRootBackend
):
    """A rootless response worker with independent fixed-frequency Dω data."""

    def sample_fixed_root_determinant(self, *args, **kwargs):
        sample = super().sample_fixed_root_determinant(*args, **kwargs)
        determinant = 5.0 * sample.omega + (2.0 + 3.0j) * sample.amplitude
        receipt = dict(sample.worker_response_receipt)
        response = dict(receipt["response_binding"])
        response.update({
            "determinant_re": str(determinant.real),
            "determinant_im": str(determinant.imag),
            "determinant_error_abs": "1e-18",
        })
        receipt["response_binding"] = response
        receipt["response_sha256"] = hashlib.sha256(
            canonical_json_bytes(response)
        ).hexdigest()
        return replace(
            sample,
            determinant=determinant,
            determinant_error_abs=1.0e-18,
            worker_response_receipt=receipt,
            worker_response_receipt_sha256=hashlib.sha256(
                canonical_json_bytes(receipt)
            ).hexdigest(),
        )


class _FailingScientificFixedRootBackend(_ScientificFixedRootBackend):
    """Raise one authenticated control failure at the worker boundary."""

    def __init__(self, job, baseline, digits: int, failure) -> None:
        super().__init__(job, baseline, digits)
        self.failure = failure
        self.read_calls = 0

    def read_root(self, *args, **kwargs):
        self.read_calls += 1
        raise self.failure


class PromotedExteriorCampaignFlowCanary(unittest.TestCase):
    """Leaf-42 production-path canary for the fixed-root exterior lifecycle."""

    def setUp(self) -> None:
        self.capabilities = PrecisionCapabilities((64, 80, 120))
        self.plan = build_campaign_plan(
            policy=NumericalPolicy(),
            backend_identity=VettedNativeDeterminantKernel.identity,
            precision_capabilities=self.capabilities,
        )
        self.leaf = next(
            leaf for leaf in self.plan.leaves if leaf.leaf_id == LEAF_42_ID
        )
        self.assertEqual(self.leaf.role, "primary")
        self.assertEqual(self.leaf.mechanism_id, "exterior-light-ring")
        self.assertEqual(self.leaf.leaf.mode_label, "221")
        self.assertEqual(self.leaf.job.spin, 0.95)
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.addCleanup(self.temporary.cleanup)
        self.journal_patch = patch.dict(
            os.environ,
            {
                "KERR_QNM_PARTIAL_COMPONENT_JOURNAL_ROOT": str(
                    self.root / "component-journals"
                )
            },
        )
        self.journal_patch.start()
        self.addCleanup(self.journal_patch.stop)

    def _native_backend(self, leaf=None) -> NativeCampaignStageBackend:
        selected = self.leaf if leaf is None else leaf
        generated = GeneratedGsnCache(
            ("gsn-000001",),
            self.root / "gsn-selection.json",
            "a" * 64,
            (GsnParameterPair(19, 20, selected.job.mode.m),),
        )
        native = NativeDeterminantAdapter(
            identity=VettedNativeDeterminantKernel.identity,
            kernel=SimpleNamespace(),
        )
        return NativeCampaignStageBackend(
            native,
            self.capabilities,
            generated,
            SimpleNamespace(runtime_provenance={}),
        )

    def _binary_result(self, leaf=None, *, shifted_root: bool = False):
        selected = self.leaf if leaf is None else leaf
        baseline_omega = (
            selected.job.root.omega + complex(1.0e-12, 0.0)
            if shifted_root
            else selected.job.root.omega
        )
        outcome = _production_outcome(
            selected,
            digits=64,
            status=ComponentStatus.NOT_CONVERGED,
            baseline_omega=baseline_omega,
        )
        return ComponentResult.from_mapping(outcome.component_result["result"])

    def _precision_backend(
        self,
        leaf,
        digits: int,
        *,
        precision_limited: bool = False,
        primary_predictor: complex | None = None,
    ):
        from tests.test_promoted_horizon_component import _with_worker_receipt

        baseline = (
            exterior_derivative_fixtures.PromotedExteriorDerivativeTests
            ._baseline_with_derivative_evidence(leaf)
        )
        baseline = replace(baseline, omega=leaf.job.root.omega)
        if precision_limited:
            conditioning = baseline.numerical_conditioning
            self.assertIsNotNone(conditioning)
            baseline = replace(
                baseline,
                numerical_conditioning=replace(
                    conditioning,
                    predicted_reliable_digits=Decimal("11"),
                    required_reliable_digits=Decimal("24"),
                    precision_limited=True,
                ),
            )
        baseline = _with_worker_receipt(
            leaf.job,
            baseline,
            digits,
            baseline.omega if primary_predictor is None else primary_predictor,
        )
        return _ScientificFixedRootBackend(leaf.job, baseline, digits)

    def _native_stages(self, leaf=None, *, shifted_binary_root: bool = False):
        selected = self.leaf if leaf is None else leaf
        backend = self._native_backend(selected)
        primary_predictor = (
            selected.job.root.omega + complex(1.0e-12, 0.0)
            if shifted_binary_root
            else selected.job.root.omega
        )
        workers = {
            digits: self._precision_backend(
                selected, digits, primary_predictor=primary_predictor
            )
            for digits in (80, 120)
        }
        with patch(
            "windows_solver.response_batches.run_component",
            return_value=self._binary_result(
                selected, shifted_root=shifted_binary_root
            ),
        ), patch.object(
            backend,
            "_julia_precision_backend_for",
            side_effect=lambda job, digits, refinement=0: workers[digits],
        ):
            binary = backend.execute_stage(selected, 64)
            promoted80 = backend.execute_promoted_stage(
                selected, 80, (binary,)
            )
        return backend, workers, binary, promoted80

    @staticmethod
    def _explicit_na(outcome: StageOutcome) -> StageOutcome:
        result = ComponentResult.from_mapping(outcome.component_result["result"])
        component = dict(outcome.component_result)
        component.update({
            "precision_ladder_discrepancy_applicable": False,
            "precision_ladder_discrepancy_reason": BINARY_RESPONSE_UNAVAILABLE,
        })
        radius = sum(result.error_channels.values())
        return replace(
            outcome,
            component_result=component,
            local_disk_radius_abs=radius,
            signed_error_channels=_component_stage_signed_error_channels(
                component,
                result,
                repeat_applicable=False,
                precision_ladder_applicable=False,
            ),
            self_refinement_enclosed=None,
            discrepancy_from_previous_abs=None,
            discrepancy_enclosed=None,
        )

    @staticmethod
    def _empirical_failed_preflight_error(leaf, *, digits: int = 80):
        predecessor = _failed_preflight_attempt(leaf)
        failure = JuliaNumericalControlError(
            "synthetic INSUFFICIENT_ASYMPTOTIC_PRECISION",
            "INSUFFICIENT_ASYMPTOTIC_PRECISION",
        )
        receipt = json.loads(canonical_json_bytes(
            predecessor.failure_receipt
        ))
        calibration = load_default_calibration_receipt()
        request = JuliaPrecisionRootBackend(
            leaf.job.backend_identity,
            SimpleNamespace(runtime_provenance={}),
            digits,
            empirical_control_profile=calibration.budget_for(
                "exterior-wronskian/v1", digits
            ),
            calibration_receipt=calibration,
        )._request(leaf.job, 0.0j, leaf.job.root.omega)
        failure_payload = receipt["failure"]
        failure_payload.pop("promotion_decision", None)
        failure_payload.update({
            "precision_digits": digits,
            "request_binding": request,
            "request_sha256": hashlib.sha256(
                canonical_json_bytes(request)
            ).hexdigest(),
            "execution_resource_policy": {
                name: request["execution_resource"][name]
                for name in ("schema", "version", "sha256")
            },
            "diagnostics": valid_control_failure_diagnostics(
                "INSUFFICIENT_ASYMPTOTIC_PRECISION",
                precision_bits=request["working_precision_bits"],
            ),
        })
        failure.worker_failure = receipt
        return failure

    def test_leaf42_native_80_stage_uses_explicit_na_response_comparison(self):
        """Catches a root-frequency delta relabelled as response discrepancy."""

        _, workers, binary, promoted = self._native_stages()
        result = ComponentResult.from_mapping(promoted.component_result["result"])

        self.assertEqual(binary.numerical_state, "NOT_CONVERGED")
        self.assertIsNone(
            ComponentResult.from_mapping(binary.component_result["result"]).response
        )
        self.assertEqual(result.status, ComponentStatus.CONVERGED)
        self.assertEqual(
            result.component_scientific_identity,
            "fixed-root-exterior-derivative-component/v1",
        )
        self.assertEqual(
            promoted.component_result["self_refinement_skipped_reason"],
            FIXED_ROOT_SKIP_REASON,
        )
        self.assertIsNone(promoted.component_result["self_refinement_result"])
        self.assertIsNone(promoted.self_refinement_enclosed)
        self.assertIs(
            promoted.component_result["precision_ladder_discrepancy_applicable"],
            False,
        )
        self.assertEqual(
            promoted.component_result["precision_ladder_discrepancy_reason"],
            BINARY_RESPONSE_UNAVAILABLE,
        )
        self.assertIsNone(promoted.discrepancy_from_previous_abs)
        self.assertIsNone(promoted.discrepancy_enclosed)
        precision_channel = next(
            item
            for item in promoted.signed_error_channels
            if item["family"] == "precision-ladder-discrepancy"
        )
        self.assertEqual(
            precision_channel["provenance"]["derivation"],
            "not-applicable-precision-ladder-discrepancy",
        )
        self.assertEqual(
            precision_channel["signed_delta"],
            {"real": 0.0, "imaginary": 0.0},
        )
        self.assertEqual(workers[80].root_amplitudes, [0.0j])
        self.assertEqual(len(workers[80].sample_amplitudes), 4)
        self.assertEqual(workers[120].root_amplitudes, [])

    def test_leaf42_adequate_80_completes_checkpoint_cache_and_resumes(self):
        """Catches admission/decision/persistence paths bypassing fixed-root evidence."""

        checkpoint = self.root / "checkpoint.json"
        cache = SolvedLeafStore(self.root / "solved-leaves")
        selection = build_campaign_selection(
            self.plan, role="primary", leaf_ids=(self.leaf.leaf_id,)
        )
        backend = self._native_backend()
        workers = {
            digits: self._precision_backend(self.leaf, digits)
            for digits in (80, 120)
        }
        with patch(
            "windows_solver.response_batches.run_component",
            return_value=self._binary_result(),
        ), patch.object(
            backend,
            "_julia_precision_backend_for",
            side_effect=lambda job, digits, refinement=0: workers[digits],
        ):
            try:
                cold = run_campaign_selection(
                    self.plan,
                    selection,
                    backend,
                    checkpoint,
                    resume=False,
                    solved_leaf_store=cache,
                )
            except ValueError as error:
                self.fail(
                    "live fixed-root exterior stage was rejected before "
                    f"checkpoint publication: {error}"
                )

        self.assertEqual(cold.state, "COMPLETE")
        self.assertEqual(cold.executed_stage_count, 2)
        self.assertEqual(cold.records[0].state, "PRODUCED")
        self.assertEqual(
            tuple(stage.outcome.digits for stage in cold.records[0].stages),
            (64, 80),
        )
        decision = cold.records[0].stages[-1].outcome.component_result[
            "promotion_decision"
        ]
        self.assertEqual(decision["state"], "SUPPRESSED")
        self.assertEqual(workers[120].root_amplitudes, [])

        raw_checkpoint = checkpoint.read_bytes()
        self.assertEqual(
            raw_checkpoint,
            canonical_json_bytes(json.loads(raw_checkpoint)),
        )
        self.assertEqual(
            tuple(checkpoint.parent.glob(f".{checkpoint.name}.*.tmp")),
            (),
        )
        validated = validate_campaign_checkpoint(self.plan, checkpoint)
        self.assertEqual(validated.records, cold.records)

        journal_paths = tuple(
            sorted((self.root / "component-journals").glob("*.json"))
        )
        self.assertEqual(len(journal_paths), 2)
        journals = tuple(PartialComponentJournal.load(path) for path in journal_paths)
        self.assertEqual(
            sorted((journal.complete, len(journal.entries)) for journal in journals),
            [(True, 1), (True, 4)],
        )
        journal_bytes = {path: path.read_bytes() for path in journal_paths}

        contract = backend.scientific_execution_contract_for(self.leaf)
        scientific_identity = scientific_computation_identity_sha256(
            self.plan,
            self.leaf,
            scientific_execution_contract=contract,
        )
        self.assertEqual(cache.stored_count, 1)
        self.assertIs(
            cache.lookup(scientific_identity, self.leaf.leaf_id).status,
            SolvedLeafLookupStatus.HIT,
        )
        authenticated = _authenticated_solved_leaf_lookup(
            self.plan,
            self.leaf,
            SolvedLeafStore(self.root / "solved-leaves"),
            scientific_execution_contract=contract,
        )
        self.assertIs(authenticated.status, SolvedLeafLookupStatus.HIT)

        resume_backend = self._native_backend()
        with patch(
            "windows_solver.response_batches.run_component",
            side_effect=AssertionError("resume repeated binary numerics"),
        ), patch.object(
            resume_backend,
            "_julia_precision_backend_for",
            side_effect=AssertionError("resume repeated promoted numerics"),
        ):
            resumed = run_campaign_selection(
                self.plan,
                selection,
                resume_backend,
                checkpoint,
                resume=True,
                solved_leaf_store=cache,
            )
            cached = run_campaign_selection(
                self.plan,
                selection,
                resume_backend,
                self.root / "cache-reload.json",
                resume=False,
                solved_leaf_store=SolvedLeafStore(self.root / "solved-leaves"),
            )
        self.assertEqual(resumed.executed_stage_count, 0)
        self.assertEqual(resumed.reused_stage_count, 2)
        self.assertEqual(cached.executed_stage_count, 0)
        self.assertEqual(cached.reused_stage_count, 2)
        self.assertEqual(checkpoint.read_bytes(), raw_checkpoint)
        for path, persisted in journal_bytes.items():
            self.assertEqual(path.read_bytes(), persisted)

    def test_live_rejects_mismatched_80_predictor_before_checkpoint(self):
        """A malformed promoted transition must not enter durable state."""

        checkpoint = self.root / "mismatched-80-predictor.json"
        selection = build_campaign_selection(
            self.plan, role="primary", leaf_ids=(self.leaf.leaf_id,)
        )
        backend = self._native_backend()
        wrong_predictor = self.leaf.job.root.omega + complex(1.0e-5, -1.0e-5)
        workers = {
            80: self._precision_backend(
                self.leaf, 80, primary_predictor=wrong_predictor
            ),
            120: self._precision_backend(self.leaf, 120),
        }
        with patch(
            "windows_solver.response_batches.run_component",
            return_value=self._binary_result(),
        ), patch.object(
            backend,
            "_julia_precision_backend_for",
            side_effect=lambda job, digits, refinement=0: workers[digits],
        ), self.assertRaisesRegex(
            ValueError,
            "promoted fixed-readout PRIMARY predictor binding is invalid",
        ):
            run_campaign_selection(
                self.plan,
                selection,
                backend,
                checkpoint,
                resume=False,
            )

        validated = validate_campaign_checkpoint(self.plan, checkpoint)
        self.assertEqual(
            tuple(stage.outcome.digits for stage in validated.records[0].stages),
            (64,),
        )

    def test_live_rejects_mismatched_120_predictor_before_checkpoint(self):
        """Only a root-specific retry may invoke a 120 root predictor."""

        checkpoint = self.root / "mismatched-120-predictor.json"
        selection = build_campaign_selection(
            self.plan, role="primary", leaf_ids=(self.leaf.leaf_id,)
        )
        backend = self._native_backend()
        wrong_predictor = self.leaf.job.root.omega + complex(1.0e-5, -1.0e-5)
        workers = {
            80: self._precision_backend(
                self.leaf, 80, precision_limited=True
            ),
            120: self._precision_backend(
                self.leaf, 120, primary_predictor=wrong_predictor
            ),
        }
        with patch(
            "windows_solver.response_batches.run_component",
            return_value=self._binary_result(),
        ), patch.object(
            backend,
            "_julia_precision_backend_for",
            side_effect=lambda job, digits, refinement=0: workers[digits],
        ), self.assertRaisesRegex(
            ValueError,
            "promoted fixed-readout PRIMARY predictor binding is invalid",
        ):
            run_campaign_selection(
                self.plan,
                selection,
                backend,
                checkpoint,
                resume=False,
            )

        validated = validate_campaign_checkpoint(self.plan, checkpoint)
        self.assertEqual(
            tuple(stage.outcome.digits for stage in validated.records[0].stages),
            (64, 80),
        )
        self.assertEqual(validated.records[0].state, "IN_PROGRESS")

    def test_leaf42_unbounded_80_terminalizes_without_a_root_escalation(self):
        """An unbounded response cannot authorize a replacement root."""

        checkpoint = self.root / "unbounded-then-120.json"
        selection = build_campaign_selection(
            self.plan, role="primary", leaf_ids=(self.leaf.leaf_id,)
        )
        backend = self._native_backend()
        baseline80 = (
            exterior_derivative_fixtures.PromotedExteriorDerivativeTests
            ._baseline_with_derivative_evidence(self.leaf)
        )
        workers = {
            80: _NoisyScientificFixedRootBackend(
                self.leaf.job, baseline80, 80
            ),
            120: self._precision_backend(self.leaf, 120),
        }
        with patch(
            "windows_solver.response_batches.run_component",
            return_value=self._binary_result(),
        ), patch.object(
            backend,
            "_julia_precision_backend_for",
            side_effect=lambda job, digits, refinement=0: workers[digits],
        ):
            summary = run_campaign_selection(
                self.plan,
                selection,
                backend,
                checkpoint,
                resume=False,
            )

        record = summary.records[0]
        self.assertEqual(summary.executed_stage_count, 2)
        self.assertEqual(record.state, "UNRESOLVED")
        self.assertEqual(
            tuple(stage.outcome.digits for stage in record.stages),
            (64, 80),
        )
        self.assertEqual(
            record.stages[1].outcome.component_result[
                "promotion_decision"
            ]["state"],
            "SUPPRESSED",
        )
        self.assertEqual(
            ComponentResult.from_mapping(
                record.stages[1].outcome.component_result["result"]
            ).status,
            ComponentStatus.DERIVATIVE_UNRESOLVED,
        )
        self.assertEqual(workers[120].root_amplitudes, [])
        self.assertEqual(workers[120].sample_amplitudes, [])
        self.assertEqual(validate_campaign_checkpoint(
            self.plan, checkpoint
        ).records, summary.records)

    def test_leaf42_nonconverged_80_runs_bounded_120_to_terminal_checkpoint(self):
        """A typed 80 root miss must survive the full durable lifecycle."""

        from tests.test_promoted_horizon_component import _with_worker_receipt

        checkpoint = self.root / "nonconverged-then-120.json"
        cache = SolvedLeafStore(self.root / "nonconverged-solved-leaves")
        selection = build_campaign_selection(
            self.plan, role="primary", leaf_ids=(self.leaf.leaf_id,)
        )
        backend = self._native_backend()
        baseline80 = (
            exterior_derivative_fixtures.PromotedExteriorDerivativeTests
            ._baseline_with_derivative_evidence(self.leaf)
        )
        primary = baseline80.primary_acceptance
        self.assertIsNotNone(primary)
        self.assertIsNotNone(baseline80.normalised_determinant_abs)
        scale = Decimal("1000000")
        rejected_determinant = replace(
            primary.determinant,
            real=primary.determinant.real * scale,
            imaginary=primary.determinant.imaginary * scale,
        )
        with localcontext() as context:
            context.prec = 180
            rejected_correction = (
                rejected_determinant.magnitude()
                / primary.derivative.magnitude()
            )
        rejected_primary = replace(
            primary,
            determinant=rejected_determinant,
            correction_abs=rejected_correction,
            accepted=False,
        )
        rejected_residual = baseline80.normalised_determinant_abs * scale
        baseline80 = replace(
            baseline80,
            determinant_residual_abs=float(rejected_residual),
            converged=False,
            truncation_radius=None,
            resolution_radius=None,
            diagnostic_readouts={},
            diagnostics_skipped_reason="PRIMARY_NOT_CONVERGED",
            normalised_determinant_abs=rejected_residual,
            primary_acceptance=rejected_primary,
            worker_response_receipt=None,
        )
        baseline80 = _with_worker_receipt(
            self.leaf.job,
            baseline80,
            80,
            self.leaf.job.root.omega,
        )
        workers = {
            80: _ScientificFixedRootBackend(
                self.leaf.job, baseline80, 80
            ),
            120: self._precision_backend(self.leaf, 120),
        }

        with patch(
            "windows_solver.response_batches.run_component",
            return_value=self._binary_result(),
        ), patch.object(
            backend,
            "_julia_precision_backend_for",
            side_effect=lambda job, digits, refinement=0: workers[digits],
        ):
            summary = run_campaign_selection(
                self.plan,
                selection,
                backend,
                checkpoint,
                resume=False,
                solved_leaf_store=cache,
            )

        record = summary.records[0]
        self.assertEqual(summary.executed_stage_count, 3)
        self.assertEqual(record.state, "PRODUCED")
        self.assertEqual(
            tuple(stage.outcome.digits for stage in record.stages),
            (64, 80, 120),
        )
        self.assertEqual(
            ComponentResult.from_mapping(
                record.stages[1].outcome.component_result["result"]
            ).status,
            ComponentStatus.NOT_CONVERGED,
        )
        self.assertEqual(
            record.stages[1].outcome.component_result[
                "promotion_decision"
            ]["state"],
            "REQUESTED",
        )
        self.assertEqual(workers[80].root_amplitudes, [0.0j])
        self.assertEqual(workers[80].sample_amplitudes, [])
        self.assertEqual(len(workers[120].sample_amplitudes), 4)
        self.assertEqual(
            ComponentResult.from_mapping(
                record.stages[2].outcome.component_result["result"]
            ).status,
            ComponentStatus.CONVERGED,
        )
        raw_checkpoint = checkpoint.read_bytes()
        self.assertEqual(
            raw_checkpoint,
            canonical_json_bytes(json.loads(raw_checkpoint)),
        )
        self.assertEqual(
            tuple(checkpoint.parent.glob(f".{checkpoint.name}.*.tmp")),
            (),
        )
        self.assertEqual(
            validate_campaign_checkpoint(self.plan, checkpoint).records,
            summary.records,
        )

        journal_paths = tuple(
            sorted((self.root / "component-journals").glob("*.json"))
        )
        self.assertEqual(len(journal_paths), 3)
        journals = tuple(
            PartialComponentJournal.load(path) for path in journal_paths
        )
        self.assertEqual(
            sorted(
                (journal.complete, len(journal.entries))
                for journal in journals
            ),
            [(True, 1), (True, 1), (True, 4)],
        )
        journal_bytes = {
            path: path.read_bytes() for path in journal_paths
        }

        contract = backend.scientific_execution_contract_for(self.leaf)
        scientific_identity = scientific_computation_identity_sha256(
            self.plan,
            self.leaf,
            scientific_execution_contract=contract,
        )
        self.assertEqual(cache.stored_count, 1)
        self.assertIs(
            cache.lookup(scientific_identity, self.leaf.leaf_id).status,
            SolvedLeafLookupStatus.HIT,
        )
        authenticated = _authenticated_solved_leaf_lookup(
            self.plan,
            self.leaf,
            SolvedLeafStore(self.root / "nonconverged-solved-leaves"),
            scientific_execution_contract=contract,
        )
        self.assertIs(authenticated.status, SolvedLeafLookupStatus.HIT)

        cache_checkpoint = self.root / "nonconverged-cache-reload.json"
        resume_backend = self._native_backend()
        with patch(
            "windows_solver.response_batches.run_component",
            side_effect=AssertionError("resume repeated binary numerics"),
        ), patch.object(
            resume_backend,
            "_julia_precision_backend_for",
            side_effect=AssertionError("resume repeated promoted numerics"),
        ):
            resumed = run_campaign_selection(
                self.plan,
                selection,
                resume_backend,
                checkpoint,
                resume=True,
                solved_leaf_store=cache,
            )
            cached = run_campaign_selection(
                self.plan,
                selection,
                resume_backend,
                cache_checkpoint,
                resume=False,
                solved_leaf_store=SolvedLeafStore(
                    self.root / "nonconverged-solved-leaves"
                ),
            )

        self.assertEqual(resumed.executed_stage_count, 0)
        self.assertEqual(resumed.reused_stage_count, 3)
        self.assertEqual(cached.executed_stage_count, 0)
        self.assertEqual(cached.reused_stage_count, 3)
        self.assertEqual(resumed.records, summary.records)
        self.assertEqual(cached.records, summary.records)
        self.assertEqual(checkpoint.read_bytes(), raw_checkpoint)
        cached_checkpoint_bytes = cache_checkpoint.read_bytes()
        self.assertEqual(
            cached_checkpoint_bytes,
            canonical_json_bytes(json.loads(cached_checkpoint_bytes)),
        )
        self.assertEqual(
            validate_campaign_checkpoint(
                self.plan, cache_checkpoint
            ).records,
            summary.records,
        )
        self.assertEqual(
            tuple(cache_checkpoint.parent.glob(
                f".{cache_checkpoint.name}.*.tmp"
            )),
            (),
        )
        self.assertEqual(
            tuple(
                sorted(
                    (self.root / "component-journals").glob("*.json")
                )
            ),
            journal_paths,
        )
        for path, persisted in journal_bytes.items():
            self.assertEqual(path.read_bytes(), persisted)

    def test_leaf42_terminal_120_failure_is_not_retried_on_resume(self):
        """A durable max-precision failure must not repeat expensive work."""

        checkpoint = self.root / "terminal-120-failure.json"
        selection = build_campaign_selection(
            self.plan, role="primary", leaf_ids=(self.leaf.leaf_id,)
        )
        backend = self._native_backend()
        worker80 = self._precision_backend(
            self.leaf, 80, precision_limited=True
        )

        baseline120 = (
            exterior_derivative_fixtures.PromotedExteriorDerivativeTests
            ._baseline_with_derivative_evidence(self.leaf)
        )
        worker120 = _FailingScientificFixedRootBackend(
            self.leaf.job,
            baseline120,
            120,
            self._empirical_failed_preflight_error(self.leaf, digits=120),
        )
        workers = {80: worker80, 120: worker120}
        with patch(
            "windows_solver.response_batches.run_component",
            return_value=self._binary_result(),
        ), patch.object(
            backend,
            "_julia_precision_backend_for",
            side_effect=lambda job, digits, refinement=0: workers[digits],
        ):
            first = run_campaign_selection(
                self.plan,
                selection,
                backend,
                checkpoint,
                resume=False,
            )

        self.assertEqual(first.state, "PARTIAL")
        self.assertEqual(first.executed_stage_count, 2)
        self.assertEqual(
            tuple(stage.outcome.digits for stage in first.records[0].stages),
            (64, 80),
        )
        self.assertEqual(worker120.read_calls, 1)
        self.assertEqual(len(first.attempts), 1)
        self.assertEqual(first.attempts[0].precision_digits, 120)
        self.assertEqual(
            first.attempts[0].failure_code,
            "INSUFFICIENT_ASYMPTOTIC_PRECISION",
        )
        validated_first = validate_campaign_checkpoint(self.plan, checkpoint)
        self.assertEqual(validated_first.attempts, first.attempts)
        durable_bytes = checkpoint.read_bytes()

        resume_backend = self._native_backend()
        resume_worker120 = _FailingScientificFixedRootBackend(
            self.leaf.job,
            baseline120,
            120,
            self._empirical_failed_preflight_error(self.leaf, digits=120),
        )
        with patch(
            "windows_solver.response_batches.run_component",
            side_effect=AssertionError("resume repeated binary numerics"),
        ), patch.object(
            resume_backend,
            "_julia_precision_backend_for",
            return_value=resume_worker120,
        ):
            resumed = run_campaign_selection(
                self.plan,
                selection,
                resume_backend,
                checkpoint,
                resume=True,
            )

        validated_resumed = validate_campaign_checkpoint(self.plan, checkpoint)
        self.assertEqual(
            (
                resume_worker120.read_calls,
                len(resumed.attempts),
                resumed.attempts == first.attempts,
                validated_resumed.attempts == validated_first.attempts,
                checkpoint.read_bytes() == durable_bytes,
            ),
            (0, 1, True, True, True),
        )

    def test_failed_preflight_exterior_recovery_persists_and_reuses(self):
        """A real typed 80 failure must admit the one-result 120 override."""

        checkpoint = self.root / "failed-preflight.json"
        cache = SolvedLeafStore(self.root / "failed-preflight-cache")
        selection = build_campaign_selection(
            self.plan, role="primary", leaf_ids=(self.leaf.leaf_id,)
        )
        native = self._native_backend()
        failure = self._empirical_failed_preflight_error(self.leaf)
        worker80 = _FailingScientificFixedRootBackend(
            self.leaf.job,
            (
                exterior_derivative_fixtures
                .PromotedExteriorDerivativeTests
                ._baseline_with_derivative_evidence(self.leaf)
            ),
            80,
            failure,
        )
        worker120 = self._precision_backend(self.leaf, 120)
        with patch(
            "windows_solver.response_batches.run_component",
            return_value=self._binary_result(),
        ), patch.object(
            native,
            "_julia_precision_backend_for",
            side_effect=lambda job, digits, refinement=0: {
                80: worker80,
                120: worker120,
            }[digits],
        ):
            summary = run_campaign_selection(
                self.plan,
                selection,
                native,
                checkpoint,
                resume=False,
                solved_leaf_store=cache,
            )

        record = summary.records[0]
        self.assertEqual(record.state, "PRODUCED")
        self.assertEqual(
            tuple(stage.outcome.digits for stage in record.stages),
            (64, 120),
        )
        self.assertEqual(len(summary.attempts), 1)
        self.assertEqual(worker80.read_calls, 1)
        recovered = record.stages[1].outcome
        self.assertIsNone(recovered.self_refinement_enclosed)
        self.assertIsNone(
            recovered.component_result["self_refinement_result"]
        )
        self.assertEqual(
            recovered.component_result["comparison_kind"],
            "failed-preflight-120-fixed-root-exterior-derivative/v1",
        )
        self.assertEqual(
            validate_campaign_checkpoint(self.plan, checkpoint).records,
            summary.records,
        )
        self.assertEqual(cache.stored_count, 1)

        class NoNumerics:
            identity = native.identity
            precision_capabilities = native.precision_capabilities

            def scientific_execution_contract_for(self, leaf):
                return native.scientific_execution_contract_for(leaf)

            def execute_stage(self, leaf, digits):
                raise AssertionError("cache reload repeated binary numerics")

            def execute_promoted_stage(self, leaf, digits, previous):
                raise AssertionError("cache reload repeated promoted numerics")

            def execute_promoted_stage_after_failed_preflight(
                self, leaf, digits, predecessor
            ):
                raise AssertionError("cache reload repeated recovery numerics")

        cached = run_campaign_selection(
            self.plan,
            selection,
            NoNumerics(),
            self.root / "failed-preflight-cache-reload.json",
            resume=False,
            solved_leaf_store=SolvedLeafStore(
                self.root / "failed-preflight-cache"
            ),
        )
        self.assertEqual(cached.executed_stage_count, 0)
        self.assertEqual(cached.reused_stage_count, 2)

    def test_deep_failed_preflight_compares_available_binary_response(self):
        """Recovery derives 64→120 response evidence instead of forcing N/A."""

        deep = next(
            leaf
            for leaf in self.plan.leaves
            if leaf.role == "deep"
            and leaf.mechanism_id == "exterior-light-ring"
            and leaf.job.spin < 0.9999
            and leaf.leaf_id
            not in set(
                response_batches.B_PRIME_RELEASE_DOMAIN
                .fixed_precision_sentinel_leaf_ids
            )
        )
        binary_fixture = _production_outcome(
            deep, digits=64, status=ComponentStatus.CONVERGED
        )
        binary_result = ComponentResult.from_mapping(
            binary_fixture.component_result["result"]
        )
        native = self._native_backend(deep)
        failure = self._empirical_failed_preflight_error(deep)
        worker80 = _FailingScientificFixedRootBackend(
            deep.job,
            (
                exterior_derivative_fixtures
                .PromotedExteriorDerivativeTests
                ._baseline_with_derivative_evidence(deep)
            ),
            80,
            failure,
        )
        worker120 = self._precision_backend(deep, 120)
        checkpoint = self.root / "deep-failed-preflight.json"
        selection = build_campaign_selection(
            self.plan, role="deep", leaf_ids=(deep.leaf_id,)
        )

        with patch(
            "windows_solver.response_batches.run_component",
            return_value=binary_result,
        ), patch.object(
            native,
            "_julia_precision_backend_for",
            side_effect=lambda job, digits, refinement=0: {
                80: worker80,
                120: worker120,
            }[digits],
        ):
            summary = run_campaign_selection(
                self.plan,
                selection,
                native,
                checkpoint,
                resume=False,
            )

        record = summary.records[0]
        self.assertEqual(
            tuple(stage.outcome.digits for stage in record.stages),
            (64, 120),
        )
        self.assertTrue(record.trigger_ids)
        self.assertFalse(record.sentinel)
        recovered = record.stages[1].outcome
        recovered_result = ComponentResult.from_mapping(
            recovered.component_result["result"]
        )
        expected_delta = recovered_result.response - binary_result.response
        self.assertIs(
            recovered.component_result[
                "precision_ladder_discrepancy_applicable"
            ],
            True,
        )
        self.assertIsNone(
            recovered.component_result[
                "precision_ladder_discrepancy_reason"
            ]
        )
        self.assertEqual(
            recovered.discrepancy_from_previous_abs, abs(expected_delta)
        )
        precision_channel = next(
            channel
            for channel in recovered.signed_error_channels
            if channel["family"] == "precision-ladder-discrepancy"
        )
        self.assertEqual(
            precision_channel["provenance"]["derivation"],
            "explicit-signed-precision-ladder-discrepancy",
        )
        self.assertEqual(
            complex(
                precision_channel["signed_delta"]["real"],
                precision_channel["signed_delta"]["imaginary"],
            ),
            expected_delta,
        )
        self.assertEqual(
            validate_campaign_checkpoint(self.plan, checkpoint).records,
            summary.records,
        )

    def test_deep_fixed_root_80_does_not_require_self_refinement(self):
        """Catches the deep decision treating policy N/A as failed refinement."""

        deep = next(
            leaf
            for leaf in self.plan.leaves
            if leaf.role == "deep"
            and leaf.mechanism_id == "exterior-light-ring"
            and leaf.job.spin < 0.9999
            and leaf.leaf_id
            not in set(
                response_batches.B_PRIME_RELEASE_DOMAIN.fixed_precision_sentinel_leaf_ids
            )
        )
        _, workers, _, promoted = self._native_stages(deep)
        decision = response_batches._deep_precision120_decision(
            promoted, sentinel_false_negative=False
        )

        self.assertIsNone(promoted.self_refinement_enclosed)
        self.assertEqual(
            promoted.component_result["self_refinement_skipped_reason"],
            FIXED_ROOT_SKIP_REASON,
        )
        self.assertEqual(decision["state"], "SUPPRESSED")
        self.assertEqual(workers[120].root_amplitudes, [])

    def test_deep_fixed_root_80_completes_live_without_false_120(self):
        """Deep admission, checkpoint reload, and cache use share the policy."""

        deep = next(
            leaf
            for leaf in self.plan.leaves
            if leaf.role == "deep"
            and leaf.mechanism_id == "exterior-light-ring"
            and leaf.job.spin < 0.9999
            and leaf.leaf_id
            not in set(
                response_batches.B_PRIME_RELEASE_DOMAIN
                .fixed_precision_sentinel_leaf_ids
            )
        )
        checkpoint = self.root / "deep.json"
        cache = SolvedLeafStore(self.root / "deep-cache")
        selection = build_campaign_selection(
            self.plan, role="deep", leaf_ids=(deep.leaf_id,)
        )
        backend = self._native_backend(deep)
        workers = {
            digits: self._precision_backend(deep, digits)
            for digits in (80, 120)
        }
        with patch(
            "windows_solver.response_batches.run_component",
            return_value=self._binary_result(deep),
        ), patch.object(
            backend,
            "_julia_precision_backend_for",
            side_effect=lambda job, digits, refinement=0: workers[digits],
        ):
            summary = run_campaign_selection(
                self.plan,
                selection,
                backend,
                checkpoint,
                resume=False,
                solved_leaf_store=cache,
            )

        record = summary.records[0]
        self.assertEqual(record.state, "PRODUCED")
        self.assertTrue(record.trigger_ids)
        self.assertEqual(
            tuple(stage.outcome.digits for stage in record.stages),
            (64, 80),
        )
        self.assertIsNone(record.stages[1].outcome.self_refinement_enclosed)
        self.assertEqual(workers[120].root_amplitudes, [])
        self.assertEqual(
            validate_campaign_checkpoint(self.plan, checkpoint).records,
            summary.records,
        )
        self.assertEqual(cache.stored_count, 1)

    def test_failed_preflight_fixed_root_override_needs_no_refinement(self):
        """Catches generic paired-refinement validation on the exterior override."""

        backend = self._native_backend()
        predecessor = _failed_preflight_attempt(self.leaf)
        worker120 = self._precision_backend(self.leaf, 120)
        with patch.object(
            backend,
            "_julia_precision_backend_for",
            return_value=worker120,
        ):
            recovered = backend.execute_promoted_stage_after_failed_preflight(
                self.leaf, 120, predecessor
            )

        self.assertEqual(recovered.digits, 120)
        self.assertIsNone(recovered.self_refinement_enclosed)
        self.assertIsNone(recovered.component_result["self_refinement_result"])
        self.assertEqual(
            recovered.component_result["self_refinement_skipped_reason"],
            FIXED_ROOT_SKIP_REASON,
        )
        try:
            embedded, produced = _validate_failed_preflight_recovery_stage(
                self.leaf, recovered
            )
        except ValueError as error:
            self.fail(
                "honest fixed-root failed-preflight override was rejected: "
                f"{error}"
            )
        self.assertEqual(embedded.to_mapping(), predecessor.to_mapping())
        self.assertTrue(produced)

    def test_precision_limited_fixed_root_80_requests_120(self):
        """A live conditioning gate executes and persists the 120 stage."""

        backend = self._native_backend()
        workers = {
            80: self._precision_backend(
                self.leaf, 80, precision_limited=True
            ),
            120: self._precision_backend(self.leaf, 120),
        }
        checkpoint = self.root / "precision-limited.json"
        selection = build_campaign_selection(
            self.plan, role="primary", leaf_ids=(self.leaf.leaf_id,)
        )
        with patch(
            "windows_solver.response_batches.run_component",
            return_value=self._binary_result(),
        ), patch.object(
            backend,
            "_julia_precision_backend_for",
            side_effect=lambda job, digits, refinement=0: workers[digits],
        ):
            summary = run_campaign_selection(
                self.plan,
                selection,
                backend,
                checkpoint,
                resume=False,
            )

        record = summary.records[0]
        self.assertEqual(
            tuple(stage.outcome.digits for stage in record.stages),
            (64, 80, 120),
        )
        stage80 = record.stages[1].outcome
        result80 = ComponentResult.from_mapping(
            stage80.component_result["result"]
        )
        self.assertTrue(
            result80.baseline.numerical_conditioning.precision_limited
        )
        self.assertEqual(
            stage80.component_result["promotion_decision"]["state"],
            "REQUESTED",
        )
        self.assertEqual(record.state, "PRODUCED")
        self.assertEqual(
            validate_campaign_checkpoint(self.plan, checkpoint).records,
            summary.records,
        )

    def test_unbounded_fixed_root_80_cannot_request_a_root_retry(self):
        """A response disk failure is not root-location evidence."""

        backend = self._native_backend()
        binary_result = self._binary_result()
        baseline = (
            exterior_derivative_fixtures.PromotedExteriorDerivativeTests
            ._baseline_with_derivative_evidence(self.leaf)
        )
        noisy80 = _NoisyScientificFixedRootBackend(
            self.leaf.job, baseline, 80
        )
        good120 = self._precision_backend(self.leaf, 120)
        workers = {80: noisy80, 120: good120}
        with patch(
            "windows_solver.response_batches.run_component",
            return_value=binary_result,
        ), patch.object(
            backend,
            "_julia_precision_backend_for",
            side_effect=lambda job, digits, refinement=0: workers[digits],
        ):
            binary = backend.execute_stage(self.leaf, 64)
            stage80 = backend.execute_promoted_stage(
                self.leaf, 80, (binary,)
            )
            decision = _primary_precision120_decision(stage80)

        result80 = ComponentResult.from_mapping(
            stage80.component_result["result"]
        )
        self.assertEqual(result80.status, ComponentStatus.DERIVATIVE_UNRESOLVED)
        self.assertEqual(
            result80.response_uncertainty_status,
            "UNBOUNDED_DERIVATIVE_RESPONSE",
        )
        self.assertEqual(decision["state"], "SUPPRESSED")
        self.assertEqual(len(noisy80.sample_amplitudes), 4)
        self.assertEqual(good120.root_amplitudes, [])
        self.assertEqual(good120.sample_amplitudes, [])

    def test_sealed_response_precision_repair_never_calls_the_120_root(self):
        """A precision-limited response stencil may escalate without re-rooting."""

        backend = self._native_backend()
        baseline = self._precision_backend(self.leaf, 80).baseline
        workers = {
            80: _PrecisionLimitedResponseSampleBackend(
                self.leaf.job, baseline, 80
            ),
            120: _RootForbiddenScientificFixedRootBackend(
                self.leaf.job, baseline, 120
            ),
        }
        checkpoint = self.root / "sealed-response-repair.json"
        selection = build_campaign_selection(
            self.plan, role="primary", leaf_ids=(self.leaf.leaf_id,)
        )
        with patch(
            "windows_solver.response_batches.run_component",
            return_value=self._binary_result(),
        ), patch.object(
            backend,
            "_julia_precision_backend_for",
            side_effect=lambda job, digits, refinement=0: workers[digits],
        ):
            summary = run_campaign_selection(
                self.plan,
                selection,
                backend,
                checkpoint,
                resume=False,
            )

        record = summary.records[0]
        self.assertEqual(
            tuple(stage.outcome.digits for stage in record.stages),
            (64, 80, 120),
        )
        stage80, stage120 = (stage.outcome for stage in record.stages[1:])
        result80 = ComponentResult.from_mapping(stage80.component_result["result"])
        result120 = ComponentResult.from_mapping(stage120.component_result["result"])
        self.assertEqual(result80.status, ComponentStatus.DERIVATIVE_UNRESOLVED)
        self.assertEqual(
            stage80.component_result["promotion_decision"]["state"],
            "SUPPRESSED",
        )
        self.assertFalse(result80.baseline.numerical_conditioning.precision_limited)
        self.assertEqual(result120.status, ComponentStatus.CONVERGED)
        self.assertEqual(
            stage120.component_result["evidence_kind"],
            "package-owned-julia-root-sealed-response-repair",
        )
        self.assertEqual(
            stage120.component_result["response_repair_scope"],
            "fixed-root-dc-stencil-only/v1",
        )
        self.assertEqual(
            result120.derivative_evidence["response_repair_scope"],
            {
                "schema": "windows-solver.fixed-root-response-repair-scope/1",
                "requested_families": ["coordinate"],
                "recomputed_families": ["coordinate"],
                "reused_families": [],
            },
        )
        self.assertEqual(result120.baseline.omega, result80.baseline.omega)
        self.assertEqual(workers[80].root_amplitudes, [0.0j])
        self.assertEqual(workers[120].root_amplitudes, [])
        self.assertEqual(len(workers[80].sample_amplitudes), 4)
        self.assertEqual(len(workers[120].sample_amplitudes), 4)
        self.assertEqual(
            validate_campaign_checkpoint(self.plan, checkpoint).records,
            summary.records,
        )

    def test_frequency_only_response_repair_preserves_the_80_coordinate_stencil(
        self,
    ):
        """A Dω-only 120 repair does not recompute D_c or the sealed root."""

        from tests.test_promoted_horizon_component import _with_worker_receipt

        backend = self._native_backend()
        baseline = self._precision_backend(self.leaf, 80).baseline
        primary = baseline.primary_acceptance
        self.assertIsNotNone(primary)
        authentication = primary.derivative_authentication
        self.assertIsNotNone(authentication)
        baseline = replace(
            baseline,
            primary_acceptance=replace(
                primary,
                derivative_authentication=replace(
                    authentication,
                    determinant_error_status="unavailable/v1",
                    determinant_error_model_id=None,
                ),
            ),
            worker_response_receipt=None,
        )
        baseline = _with_worker_receipt(
            self.leaf.job, baseline, 80, baseline.omega
        )
        workers = {
            80: _FrequencyLimitedResponseSampleBackend(
                self.leaf.job, baseline, 80
            ),
            120: _RootForbiddenScientificFrequencyBackend(
                self.leaf.job, baseline, 120
            ),
        }
        checkpoint = self.root / "frequency-only-response-repair.json"
        selection = build_campaign_selection(
            self.plan, role="primary", leaf_ids=(self.leaf.leaf_id,)
        )
        with patch(
            "windows_solver.response_batches.run_component",
            return_value=self._binary_result(),
        ), patch.object(
            backend,
            "_julia_precision_backend_for",
            side_effect=lambda job, digits, refinement=0: workers[digits],
        ):
            summary = run_campaign_selection(
                self.plan,
                selection,
                backend,
                checkpoint,
                resume=False,
            )

        record = summary.records[0]
        self.assertEqual(
            tuple(stage.outcome.digits for stage in record.stages),
            (64, 80, 120),
        )
        repair = record.stages[2].outcome
        repaired = ComponentResult.from_mapping(repair.component_result["result"])
        self.assertEqual(repair.component_result["response_repair_scope"], "fixed-root-domega-stencil-only/v1")
        self.assertEqual(
            repaired.derivative_evidence["response_repair_scope"],
            {
                "schema": "windows-solver.fixed-root-response-repair-scope/1",
                "requested_families": ["frequency"],
                "recomputed_families": ["frequency"],
                "reused_families": ["coordinate"],
            },
        )
        self.assertEqual(workers[80].root_amplitudes, [0.0j])
        self.assertEqual(workers[120].root_amplitudes, [])
        self.assertEqual(len(workers[120].sample_amplitudes), 4)
        self.assertEqual(
            validate_campaign_checkpoint(self.plan, checkpoint).records,
            summary.records,
        )

    def test_schema8_leaf42_response_failure_migrates_without_any_root_read(self):
        """The stale Dω receipt is discarded while its accepted root is retained."""

        from tests.test_promoted_horizon_component import _with_worker_receipt

        backend, _workers, binary, promoted = self._native_stages()
        result = ComponentResult.from_mapping(promoted.component_result["result"])
        primary = result.baseline.primary_acceptance
        self.assertIsNotNone(primary)
        authentication = primary.derivative_authentication
        self.assertIsNotNone(authentication)
        stale_baseline = replace(
            result.baseline,
            primary_acceptance=replace(
                primary,
                derivative_authentication=replace(
                    authentication,
                    determinant_error_status="unavailable/v1",
                    determinant_error_model_id=None,
                ),
            ),
            worker_response_receipt=None,
        )
        stale_baseline = _with_worker_receipt(
            self.leaf.job,
            stale_baseline,
            80,
            stale_baseline.omega,
        )
        stale_result = replace(
            result,
            baseline=stale_baseline,
            status=ComponentStatus.DERIVATIVE_UNRESOLVED,
            convergence_basis="UNRESOLVED_FIXED_ROOT_DERIVATIVE",
            response=None,
            closed_form_response=None,
            error_channels={name: 0.0 for name in result.error_channels},
            response_uncertainty_status="UNBOUNDED_DERIVATIVE_RESPONSE",
            error_channel_applicability={
                name: False for name in result.error_channels
            },
            derivative_evidence={
                "conditioning_decision": {
                    "accepted": False,
                    "identity": "fixed-root-h-h2-conditioning/v1",
                    "rejection_reason": "DETERMINANT_ERROR_MODEL_UNAVAILABLE",
                    "selected_candidate": None,
                },
                "determinant_count": 0,
                "failure_code": "DETERMINANT_ERROR_MODEL_UNAVAILABLE",
                "fixed_root_samples": [],
                "response_disk_identity": "exterior-derivative-response-disk/v1",
            },
        )
        old_component = dict(promoted.component_result)
        old_component["result"] = stale_result.to_mapping()
        old_unbound = replace(
            promoted,
            numerical_state=ComponentStatus.DERIVATIVE_UNRESOLVED.value,
            component_result=old_component,
            local_disk_radius_abs=0.0,
            signed_error_channels=_component_stage_signed_error_channels(
                old_component,
                stale_result,
                repeat_applicable=False,
                precision_ladder_applicable=False,
            ),
            self_refinement_enclosed=None,
            discrepancy_from_previous_abs=None,
            discrepancy_enclosed=None,
        )
        old_stage = _stage_with_promotion_decision(
            old_unbound,
            {
                "schema": "windows-solver.precision-promotion-decision/2",
                "from_precision_digits": 80,
                "to_precision_digits": 120,
                "state": "REQUESTED",
                "reason": "ROOT_TYPED_RETRY_REQUIRED",
                "predicted_reliable_digits": str(
                    stale_baseline.numerical_conditioning.predicted_reliable_digits
                ),
                "required_reliable_digits": str(
                    stale_baseline.numerical_conditioning.required_reliable_digits
                ),
                "precision_limited": False,
                "asymptotic_preflight_avoided_ode": (
                    stale_baseline.numerical_conditioning
                    .asymptotic_preflight_avoided_ode
                ),
            },
        )
        record = CampaignLeafRecord(
            leaf_id=self.leaf.leaf_id,
            role="primary",
            state="IN_PROGRESS",
            stages=(
                _campaign_stage_record(self.plan, self.capabilities, binary),
                response_batches.CampaignStageRecord(
                    old_stage,
                    response_batches.CampaignStageRecord(
                        promoted,
                        {
                            "precision_factory_identity": (
                                self.plan.precision_factory_identity.to_mapping()
                            ),
                            "available_precision_digits": list(
                                self.capabilities.digits
                            ),
                        },
                    ).runner_provenance,
                ),
            ),
        )
        selection = build_campaign_selection(
            self.plan, role="primary", leaf_ids=(self.leaf.leaf_id,)
        )
        checkpoint = self.root / "leaf42-schema8-stale-response.json"
        historical = response_batches._checkpoint_mapping(
            self.plan, selection, (record,)
        )
        historical["schema_version"] = 8
        historical["bindings"]["precision_contract_sha256"] = (
            response_batches._SCHEMA8_PRECISION_CONTRACT_SHA256
        )
        checkpoint.write_bytes(canonical_json_bytes(historical))

        response_worker = _RootForbiddenScientificFrequencyBackend(
            self.leaf.job,
            stale_baseline,
            80,
        )
        resume_backend = self._native_backend()
        with patch(
            "windows_solver.response_batches.run_component",
            side_effect=AssertionError("migration repeated binary numerics"),
        ), patch.object(
            resume_backend,
            "_julia_precision_backend_for",
            return_value=response_worker,
        ):
            summary = run_campaign_selection(
                self.plan,
                selection,
                resume_backend,
                checkpoint,
                resume=True,
            )

        repaired = summary.records[0]
        self.assertEqual(
            tuple(stage.outcome.digits for stage in repaired.stages),
            (64, 80, 80),
        )
        self.assertEqual(repaired.state, "PRODUCED")
        migrated_result = ComponentResult.from_mapping(
            repaired.stages[1].outcome.component_result["result"]
        )
        repair_result = ComponentResult.from_mapping(
            repaired.stages[2].outcome.component_result["result"]
        )
        self.assertEqual(migrated_result.baseline.omega, stale_baseline.omega)
        self.assertEqual(repair_result.baseline.omega, stale_baseline.omega)
        self.assertEqual(response_worker.root_amplitudes, [])
        self.assertEqual(len(response_worker.sample_amplitudes), 8)
        self.assertEqual(
            json.loads(checkpoint.read_bytes())["schema_version"],
            response_batches.CAMPAIGN_CHECKPOINT_SCHEMA_VERSION,
        )
        self.assertEqual(
            validate_campaign_checkpoint(self.plan, checkpoint).records,
            summary.records,
        )

    def test_fixed_root_payload_tampering_fails_closed(self):
        """Catches rehashed skip/applicability/refinement claims being trusted."""

        _, _, _, native = self._native_stages()
        honest = self._explicit_na(native)
        self.assertTrue(_validate_component_result(self.leaf, honest))
        cases = (
            {
                "self_refinement_skipped_reason": "NOT_REQUIRED",
            },
            {
                "precision_ladder_discrepancy_applicable": True,
                "precision_ladder_discrepancy_reason": None,
            },
        )
        for changes in cases:
            with self.subTest(changes=changes):
                component = {**honest.component_result, **changes}
                tampered = replace(
                    honest,
                    component_result=component,
                    signed_error_channels=_component_stage_signed_error_channels(
                        component,
                        ComponentResult.from_mapping(component["result"]),
                        repeat_applicable=False,
                        precision_ladder_applicable=not (
                            component[
                                "precision_ladder_discrepancy_applicable"
                            ]
                            is False
                        ),
                    ),
                )
                with self.assertRaises(ValueError):
                    _validate_component_result(self.leaf, tampered)

        fabricated = replace(honest, self_refinement_enclosed=True)
        with self.assertRaises(ValueError):
            _validate_component_result(self.leaf, fabricated)

    def test_record_rejects_root_delta_mislabeled_as_response_delta(self):
        """Catches a canonical record using root space for an N/A response delta."""

        _, _, binary, native = self._native_stages(shifted_binary_root=True)
        result = ComponentResult.from_mapping(native.component_result["result"])
        binary_result = ComponentResult.from_mapping(
            binary.component_result["result"]
        )
        honest = _stage_with_promotion_decision(
            native,
            _primary_precision120_decision(native, predecessor=binary),
        )
        honest_record = CampaignLeafRecord(
            leaf_id=self.leaf.leaf_id,
            role="primary",
            state="PRODUCED",
            stages=(
                _campaign_stage_record(self.plan, self.capabilities, binary),
                _campaign_stage_record(
                    self.plan, self.capabilities, honest
                ),
            ),
        )
        self.assertTrue(_validate_record_semantics(
            self.leaf,
            honest_record,
            self.plan.precision_factory_identity,
        ))
        root_delta = abs(result.baseline.omega - binary_result.baseline.omega)
        self.assertGreater(root_delta, 0.0)
        component = dict(native.component_result)
        component.update({
            "precision_ladder_discrepancy_applicable": True,
            "precision_ladder_discrepancy_reason": None,
        })
        radius = sum(result.error_channels.values()) + root_delta
        mislabeled = replace(
            native,
            component_result=component,
            local_disk_radius_abs=radius,
            signed_error_channels=_component_stage_signed_error_channels(
                component,
                result,
                repeat_applicable=False,
                precision_delta=complex(root_delta, 0.0),
            ),
            self_refinement_enclosed=None,
            discrepancy_from_previous_abs=root_delta,
            discrepancy_enclosed=True,
        )
        mislabeled = _stage_with_promotion_decision(
            mislabeled,
            honest.component_result["promotion_decision"],
        )
        record = CampaignLeafRecord(
            leaf_id=self.leaf.leaf_id,
            role="primary",
            state="PRODUCED",
            stages=(
                _campaign_stage_record(self.plan, self.capabilities, binary),
                _campaign_stage_record(
                    self.plan, self.capabilities, mislabeled
                ),
            ),
        )

        with self.assertRaises(ValueError):
            _validate_record_semantics(
                self.leaf,
                record,
                self.plan.precision_factory_identity,
            )


if __name__ == "__main__":
    unittest.main()
