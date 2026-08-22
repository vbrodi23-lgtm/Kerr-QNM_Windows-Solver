from __future__ import annotations

from dataclasses import replace
import hashlib
import unittest

from tests.test_promoted_exterior_derivative import (
    RootForbiddenFrequencyFallbackBackend,
)
from tests.test_promoted_horizon_component import (
    _promoted_baseline,
    _with_worker_receipt,
)
from windows_solver.campaign_policy import (
    BackgroundRootKey,
    FixedRootDomegaKey,
    SurveyEvidenceCache,
)
from windows_solver.contracts import canonical_json_bytes
from windows_solver.precision_tiers import PrecisionTier, working_precision_bits
from windows_solver.response_batches import (
    PrecisionCapabilities,
    StageOutcome,
    _component_stage_signed_error_channels,
    _validate_survey_stage_for_leaf,
    build_campaign_plan,
)
from windows_solver.response_engine import (
    NumericalPolicy,
    PromotedRootSeal,
    SharedBackgroundRootSeal,
    VettedNativeDeterminantKernel,
    regularised_gsn_precision_policy,
    restore_survey_evidence_cache_from_result,
    run_exterior_survey_from_shared_seal,
    run_promoted_exterior_response_from_seal,
)


def _matching_exterior_leaves():
    plan = build_campaign_plan(
        policy=NumericalPolicy(),
        backend_identity=VettedNativeDeterminantKernel.identity,
        precision_capabilities=PrecisionCapabilities((64, 80, 120)),
    )
    candidates = [
        leaf
        for leaf in plan.leaves
        if (
            leaf.role == "primary"
            and leaf.job.mode_label == "221"
            and leaf.job.spin == 0.95
            and leaf.mechanism_id
            in {"exterior-light-ring", "exterior-throat-kappa"}
        )
    ]
    by_mechanism = {leaf.mechanism_id: leaf for leaf in candidates}
    return (
        by_mechanism["exterior-light-ring"],
        by_mechanism["exterior-throat-kappa"],
    )


def _controls_sha256(mechanism_id: str) -> str:
    return hashlib.sha256(canonical_json_bytes(
        dict(regularised_gsn_precision_policy(mechanism_id))
    )).hexdigest()


def _shared_seal():
    source, target = _matching_exterior_leaves()
    baseline = _promoted_baseline(
        source.job,
        conditioning_mechanism=source.mechanism_id,
    )
    baseline = replace(baseline, omega=source.job.root.omega)
    baseline = _with_worker_receipt(
        source.job, baseline, 80, baseline.omega
    )
    promoted = PromotedRootSeal.derive(source.job, baseline)
    shared = SharedBackgroundRootSeal.derive(
        source.job,
        promoted,
        controls_sha256=_controls_sha256(source.mechanism_id),
        precision_tier=PrecisionTier.BIGFLOAT_80,
        working_precision_bits=working_precision_bits(
            PrecisionTier.BIGFLOAT_80
        ),
    )
    return source, target, baseline, shared


class SharedBackgroundSealTests(unittest.TestCase):
    def test_same_background_binds_a_second_exterior_without_root_work(self):
        source, target, baseline, shared = _shared_seal()

        rebound = shared.bind(
            target.job,
            controls_sha256=_controls_sha256(target.mechanism_id),
            precision_tier=PrecisionTier.BIGFLOAT_80,
            working_precision_bits=working_precision_bits(
                PrecisionTier.BIGFLOAT_80
            ),
        )

        self.assertEqual(rebound.root_readout, baseline)
        self.assertEqual(rebound.leaf_id, target.leaf_id)
        self.assertEqual(rebound.mechanism_id, target.mechanism_id)
        self.assertNotEqual(rebound.sha256, shared.source_root_seal_sha256)
        self.assertEqual(
            source.job.root.identity_sha256,
            target.job.root.identity_sha256,
        )

    def test_mismatched_controls_fail_closed(self):
        _, target, _, shared = _shared_seal()

        with self.assertRaisesRegex(ValueError, "background reuse identity"):
            shared.bind(
                target.job,
                controls_sha256="0" * 64,
                precision_tier=PrecisionTier.BIGFLOAT_80,
                working_precision_bits=working_precision_bits(
                    PrecisionTier.BIGFLOAT_80
                ),
            )

    def test_horizon_determinant_family_cannot_reuse_exterior_background(self):
        _, _, _, shared = _shared_seal()
        plan = build_campaign_plan(
            policy=NumericalPolicy(),
            backend_identity=VettedNativeDeterminantKernel.identity,
            precision_capabilities=PrecisionCapabilities((64, 80, 120)),
        )
        horizon = next(
            leaf
            for leaf in plan.leaves
            if (
                leaf.role == "primary"
                and leaf.job.mode_label == "221"
                and leaf.job.spin == 0.95
                and leaf.mechanism_id == "horizon-admittance"
            )
        )

        with self.assertRaisesRegex(ValueError, "exterior background"):
            shared.bind(
                horizon.job,
                controls_sha256=_controls_sha256(horizon.mechanism_id),
                precision_tier=PrecisionTier.BIGFLOAT_80,
                working_precision_bits=working_precision_bits(
                    PrecisionTier.BIGFLOAT_80
                ),
            )


class SurveyDomegaReuseTests(unittest.TestCase):
    def test_two_mechanisms_reuse_one_exact_domega_evidence(self):
        source, target, baseline, shared = _shared_seal()
        cache = SurveyEvidenceCache()
        source_backend = RootForbiddenFrequencyFallbackBackend(
            source.job, baseline
        )
        target_backend = RootForbiddenFrequencyFallbackBackend(
            target.job, baseline
        )

        source_result = run_exterior_survey_from_shared_seal(
            source.job,
            source_backend,
            shared,
            cache,
            derivative_step=0.004,
            controls_sha256=_controls_sha256(source.mechanism_id),
            precision_tier=PrecisionTier.BIGFLOAT_80,
            working_precision_bits=working_precision_bits(
                PrecisionTier.BIGFLOAT_80
            ),
        )
        target_result = run_exterior_survey_from_shared_seal(
            target.job,
            target_backend,
            shared,
            cache,
            derivative_step=0.004,
            controls_sha256=_controls_sha256(target.mechanism_id),
            precision_tier=PrecisionTier.BIGFLOAT_80,
            working_precision_bits=working_precision_bits(
                PrecisionTier.BIGFLOAT_80
            ),
        )

        self.assertEqual(source_backend.root_amplitudes, [])
        self.assertEqual(target_backend.root_amplitudes, [])
        self.assertEqual(len(source_backend.sample_calls), 8)
        self.assertEqual(len(target_backend.sample_calls), 4)
        self.assertTrue(all(
            role.startswith("coordinate-")
            for _, _, role in target_backend.sample_calls
        ))
        self.assertEqual(cache.domega_evidence_count, 1)
        self.assertIsNotNone(
            source_result.derivative_evidence["shared_domega_evidence"]
        )
        self.assertEqual(
            source_result.derivative_evidence["frequency_derivative_disk"],
            target_result.derivative_evidence["frequency_derivative_disk"],
        )
        self.assertIsNotNone(
            target_result.derivative_evidence["shared_domega_evidence"]
        )

    def test_persisted_result_rehydrates_background_and_domega_cache(self):
        source, _, baseline, shared = _shared_seal()
        source_backend = RootForbiddenFrequencyFallbackBackend(
            source.job, baseline
        )
        result = run_exterior_survey_from_shared_seal(
            source.job,
            source_backend,
            shared,
            SurveyEvidenceCache(),
            derivative_step=0.004,
            controls_sha256=_controls_sha256(source.mechanism_id),
            precision_tier=PrecisionTier.BIGFLOAT_80,
            working_precision_bits=working_precision_bits(
                PrecisionTier.BIGFLOAT_80
            ),
        )

        restored = SurveyEvidenceCache()
        restore_survey_evidence_cache_from_result(result, restored)

        self.assertEqual(restored.domega_evidence_count, 1)
        self.assertEqual(len(restored.background_seal_mappings), 1)
        self.assertEqual(
            restored.background_seal_mappings[0], shared.to_mapping()
        )

    def test_persisted_response_repair_rehydrates_background_without_domega(self):
        source, _, baseline, shared = _shared_seal()
        result = run_promoted_exterior_response_from_seal(
            source.job,
            RootForbiddenFrequencyFallbackBackend(source.job, baseline),
            PromotedRootSeal.derive(source.job, baseline),
            derivative_step=0.004,
            shared_background_seal=shared,
        )
        self.assertIsNone(
            result.derivative_evidence["shared_domega_evidence"]
        )

        restored = SurveyEvidenceCache()
        self.assertTrue(
            restore_survey_evidence_cache_from_result(result, restored)
        )
        self.assertEqual(restored.domega_evidence_count, 0)
        self.assertEqual(
            restored.background_seal_mappings,
            (shared.to_mapping(),),
        )

    def test_persisted_survey_stage_binds_real_fixed_root_evidence(self):
        source, _, baseline, _ = _shared_seal()
        runtime = {
            **dict(regularised_gsn_precision_policy(source.mechanism_id)),
            "semantic_precision_tier": PrecisionTier.BIGFLOAT_80.value,
            "working_precision_bits": working_precision_bits(
                PrecisionTier.BIGFLOAT_80
            ),
            "precision_digits": 80,
        }
        controls_sha256 = hashlib.sha256(
            canonical_json_bytes(runtime)
        ).hexdigest()
        shared = SharedBackgroundRootSeal.derive(
            source.job,
            PromotedRootSeal.derive(source.job, baseline),
            controls_sha256=controls_sha256,
            precision_tier=PrecisionTier.BIGFLOAT_80,
            working_precision_bits=working_precision_bits(
                PrecisionTier.BIGFLOAT_80
            ),
        )
        result = run_exterior_survey_from_shared_seal(
            source.job,
            RootForbiddenFrequencyFallbackBackend(source.job, baseline),
            shared,
            SurveyEvidenceCache(),
            derivative_step=0.004,
            controls_sha256=controls_sha256,
            precision_tier=PrecisionTier.BIGFLOAT_80,
            working_precision_bits=working_precision_bits(
                PrecisionTier.BIGFLOAT_80
            ),
        )
        payload = {
            "evidence_kind": "fixed-root-exterior-survey/v1",
            "execution_profile": "survey",
            "leaf_id": source.leaf_id,
            "mechanism_id": source.mechanism_id,
            "digits": 80,
            "semantic_precision_tier_trace": [
                PrecisionTier.BIGFLOAT_80.value
            ],
            "result": result.to_mapping(),
            "bounded_response_disk": True,
            "survey_promotion_required": False,
            "survey_required_precision_digits": None,
            "survey_failure_code": None,
            "scientific_runtime": runtime,
        }
        radius = sum(result.error_channels.values())
        outcome = StageOutcome(
            digits=80,
            numerical_state=result.status.value,
            component_result=payload,
            local_disk_radius_abs=radius,
            signed_error_channels=_component_stage_signed_error_channels(
                payload,
                result,
                repeat_applicable=False,
                precision_ladder_applicable=False,
            ),
        )

        self.assertTrue(_validate_survey_stage_for_leaf(source, outcome))

        changed_runtime = dict(runtime)
        changed_runtime["precision_digits"] = 79
        tampered_payload = {**payload, "scientific_runtime": changed_runtime}
        tampered = replace(
            outcome,
            component_result=tampered_payload,
            signed_error_channels=_component_stage_signed_error_channels(
                tampered_payload,
                result,
                repeat_applicable=False,
                precision_ladder_applicable=False,
            ),
        )
        with self.assertRaisesRegex(ValueError, "control identity"):
            _validate_survey_stage_for_leaf(source, tampered)

    def test_domega_cache_misses_on_normalisation_or_controls(self):
        source, _, baseline, shared = _shared_seal()
        cache = SurveyEvidenceCache()
        backend = RootForbiddenFrequencyFallbackBackend(source.job, baseline)
        run_exterior_survey_from_shared_seal(
            source.job,
            backend,
            shared,
            cache,
            derivative_step=0.004,
            controls_sha256=_controls_sha256(source.mechanism_id),
            precision_tier=PrecisionTier.BIGFLOAT_80,
            working_precision_bits=working_precision_bits(
                PrecisionTier.BIGFLOAT_80
            ),
        )
        key = cache.domega_keys[0]

        self.assertIsNotNone(cache.lookup_domega(key))
        self.assertIsNone(cache.lookup_domega(replace(
            key,
            determinant_normalisation="different-normalisation/v1",
        )))
        self.assertIsNone(cache.lookup_domega(replace(
            key,
            controls_sha256="0" * 64,
        )))

    def test_key_types_are_canonical_and_exact(self):
        _, _, _, shared = _shared_seal()
        background = BackgroundRootKey.from_mapping(
            shared.background_key.to_mapping()
        )
        key = FixedRootDomegaKey(
            background_key_sha256=background.sha256,
            determinant_family=background.determinant_family,
            determinant_normalisation=background.determinant_normalisation,
            controls_sha256=background.controls_sha256,
            precision_tier=background.precision_tier,
            working_precision_bits=background.working_precision_bits,
            derivative_method="fixed-root-frequency-h-h2-stencil/v1",
            derivative_step_hex=float(0.004).hex(),
        )

        self.assertEqual(
            FixedRootDomegaKey.from_mapping(key.to_mapping()), key
        )


if __name__ == "__main__":
    unittest.main()
