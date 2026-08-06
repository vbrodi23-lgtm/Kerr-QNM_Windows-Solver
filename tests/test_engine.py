from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import tempfile
import unittest

from windows_solver.artifacts import (
    ArtifactEnvelope,
    ArtifactStore,
    ArtifactVerificationError,
    computation_cache_key,
)
from windows_solver.builtin import ProblemContractProvider, default_registry
from windows_solver.contracts import (
    Capability,
    CarrierState,
    EvidenceState,
    ExecutionState,
    NumericalState,
    ScientificState,
    StudyRequest,
    canonical_json_bytes,
)
from windows_solver.engine import ExecutionEngine, RunRecord, verify_run_integrity
from windows_solver.planner import CAPABILITY_DEPENDENCIES
from windows_solver.providers import (
    ProviderDescriptor,
    ProviderRegistry,
    ProviderResult,
)

from tests.fixtures import VALID_STUDY


def evidence(
    *,
    carrier: CarrierState = CarrierState.VALID,
    execution: ExecutionState = ExecutionState.SUCCEEDED,
    numerical: NumericalState = NumericalState.ACCEPTED,
    scientific: ScientificState = ScientificState.NOT_EVALUATED,
) -> EvidenceState:
    return EvidenceState(carrier, execution, numerical, scientific)


class StaticProvider:
    def __init__(
        self,
        capability: Capability,
        output_type: str,
        result_evidence: EvidenceState,
        *,
        upstream_types: tuple[str, ...] = (),
        failure: Exception | None = None,
    ) -> None:
        self.descriptor = ProviderDescriptor(
            capability=capability,
            provider_id=f"static-{capability.value}",
            implementation_version="1",
            equations_id="test-equations",
            conventions_id="request-bound",
            runtime_fingerprint="test-runtime",
            numerical_policy_fingerprint="request-bound",
            upstream_artifact_types=upstream_types,
            output_artifact_type=output_type,
            available=True,
            evidence_level="test",
        )
        self.result_evidence = result_evidence
        self.failure = failure

    def execute(self, request, upstream):
        if self.failure is not None:
            raise self.failure
        return ProviderResult(
            payload={"capability": self.descriptor.capability.value},
            evidence=self.result_evidence,
        )


class MalformedProvider(StaticProvider):
    def execute(self, request, upstream):
        return {"not": "a provider result"}


class MutationProbeProvider(StaticProvider):
    def execute(self, request, upstream):
        problem = upstream[Capability.PROBLEM_CONTRACT]
        top_level_blocked = False
        nested_blocked = False
        try:
            problem.payload["request_sha256"] = "MUTATED-IN-MEMORY"
        except TypeError:
            top_level_blocked = True
        try:
            problem.payload["request"]["theory_id"] = "mutated-theory"
        except TypeError:
            nested_blocked = True
        return ProviderResult(
            payload={
                "top_level_blocked": top_level_blocked,
                "nested_blocked": nested_blocked,
                "seen_request_sha256": problem.payload["request_sha256"],
            },
            evidence=self.result_evidence,
        )


class DescriptorChangingProvider(StaticProvider):
    def execute(self, request, upstream):
        self.descriptor = replace(
            self.descriptor,
            output_artifact_type="changed-output",
        )
        return ProviderResult(
            payload={"descriptor_changed": True},
            evidence=self.result_evidence,
        )


class ExecutionEngineTests(unittest.TestCase):
    def complete_registry(self) -> ProviderRegistry:
        artifact_types = {
            capability: capability.value for capability in Capability
        }
        return ProviderRegistry(
            tuple(
                StaticProvider(
                    capability,
                    artifact_types[capability],
                    evidence(scientific=ScientificState.SUPPORTED),
                    upstream_types=tuple(
                        artifact_types[dependency]
                        for dependency in CAPABILITY_DEPENDENCIES[capability]
                    ),
                )
                for capability in Capability
            )
        )

    def test_problem_contract_run_materializes_verified_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = ArtifactStore(Path(directory))
            engine = ExecutionEngine(store=store, registry=default_registry())

            record = engine.run(StudyRequest.from_mapping(VALID_STUDY))

            self.assertEqual(record.status, "SUCCEEDED")
            self.assertEqual(record.provider_execution_count, 1)
            self.assertEqual(record.cache_hit_count, 0)
            artifact_id = record.artifact_ids["problem-contract"]
            self.assertTrue(store.verify_artifact(artifact_id))
            self.assertEqual(
                record.evidence.to_mapping(),
                {
                    "carrier": "VALID",
                    "execution": "SUCCEEDED",
                    "numerical": "ACCEPTED",
                    "scientific": "NOT_EVALUATED",
                },
            )

    def test_identical_warm_run_executes_no_provider_work(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = ArtifactStore(Path(directory))
            request = StudyRequest.from_mapping(VALID_STUDY)
            first = ExecutionEngine(store, default_registry()).run(request)

            second = ExecutionEngine(store, default_registry()).run(request)

            self.assertEqual(first.artifact_ids, second.artifact_ids)
            self.assertEqual(second.provider_execution_count, 0)
            self.assertEqual(second.cache_hit_count, 1)

    def test_upstream_artifact_is_reused_across_requested_targets(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = ArtifactStore(Path(directory))
            engine = ExecutionEngine(store, self.complete_registry())
            problem_request = StudyRequest.from_mapping(VALID_STUDY)
            evidence_request = StudyRequest.from_mapping(
                dict(VALID_STUDY, target="evidence-package")
            )

            first = engine.run(problem_request)
            second = engine.run(evidence_request)

            self.assertEqual(
                first.artifact_ids["problem-contract"],
                second.artifact_ids["problem-contract"],
            )
            self.assertEqual(second.provider_execution_count, 9)
            self.assertEqual(second.cache_hit_count, 1)

    def test_detector_policy_change_recomputes_only_detector_descendants(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = ArtifactStore(Path(directory))
            engine = ExecutionEngine(store, self.complete_registry())
            first_policy = dict(
                VALID_STUDY["numerical_policy"],
                **{"detector-inference": {"threshold": 1.0}},
            )
            second_policy = dict(
                VALID_STUDY["numerical_policy"],
                **{"detector-inference": {"threshold": 2.0}},
            )
            first_request = StudyRequest.from_mapping(
                dict(
                    VALID_STUDY,
                    target="evidence-package",
                    numerical_policy=first_policy,
                )
            )
            second_request = StudyRequest.from_mapping(
                dict(
                    VALID_STUDY,
                    target="evidence-package",
                    numerical_policy=second_policy,
                )
            )

            first = engine.run(first_request)
            second = engine.run(second_request)

            for capability in Capability:
                if capability in {
                    Capability.DETECTOR_INFERENCE,
                    Capability.EVIDENCE_PACKAGE,
                }:
                    self.assertNotEqual(
                        first.artifact_ids[capability.value],
                        second.artifact_ids[capability.value],
                    )
                else:
                    self.assertEqual(
                        first.artifact_ids[capability.value],
                        second.artifact_ids[capability.value],
                    )
            self.assertEqual(second.provider_execution_count, 2)
            self.assertEqual(second.cache_hit_count, 8)

    def test_unavailable_science_fails_before_partial_execution(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = ArtifactStore(Path(directory))
            request = StudyRequest.from_mapping(
                dict(VALID_STUDY, target="spectral-core")
            )

            record = ExecutionEngine(store, default_registry()).run(request)

            self.assertEqual(record.status, "FAILED")
            self.assertEqual(record.unavailable_capability, "spectral-core")
            self.assertEqual(record.provider_execution_count, 0)
            self.assertEqual(record.cache_hit_count, 0)
            self.assertEqual(record.artifact_ids, {})
            self.assertEqual(record.evidence.execution.value, "FAILED")
            self.assertEqual(record.evidence.numerical.value, "NOT_EVALUATED")
            self.assertEqual(record.evidence.scientific.value, "NOT_EVALUATED")

    def test_provider_exception_writes_structured_failure_after_upstream_work(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = ArtifactStore(Path(directory))
            registry = ProviderRegistry(
                (
                    ProblemContractProvider(),
                    StaticProvider(
                        Capability.SPECTRAL_CORE,
                        "spectrum",
                        evidence(),
                        upstream_types=("problem-contract",),
                        failure=RuntimeError("provider exploded"),
                    ),
                )
            )
            request = StudyRequest.from_mapping(
                dict(VALID_STUDY, target="spectral-core")
            )

            record = ExecutionEngine(store, registry).run(request)

            self.assertEqual(record.status, "FAILED")
            self.assertEqual(record.failed_capability, "spectral-core")
            self.assertEqual(record.provider_execution_count, 1)
            self.assertIn("problem-contract", record.artifact_ids)
            self.assertEqual(record.error, "RuntimeError: provider exploded")
            self.assertEqual(
                ExecutionEngine(store, registry).load_run(record.run_id), record
            )

    def test_downstream_claim_is_constrained_by_upstream_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = ArtifactStore(Path(directory))
            registry = ProviderRegistry(
                (
                    StaticProvider(
                        Capability.PROBLEM_CONTRACT,
                        "problem-contract",
                        evidence(
                            numerical=NumericalState.REJECTED,
                            scientific=ScientificState.CONTRADICTED,
                        ),
                    ),
                    StaticProvider(
                        Capability.SPECTRAL_CORE,
                        "spectrum",
                        evidence(scientific=ScientificState.SUPPORTED),
                        upstream_types=("problem-contract",),
                    ),
                )
            )
            request = StudyRequest.from_mapping(
                dict(VALID_STUDY, target="spectral-core")
            )

            record = ExecutionEngine(store, registry).run(request)
            target = store.load_artifact(record.artifact_ids["spectral-core"])

            self.assertEqual(record.status, "SUCCEEDED")
            self.assertIs(target.evidence.numerical, NumericalState.REJECTED)
            self.assertIs(target.evidence.scientific, ScientificState.CONTRADICTED)
            self.assertEqual(record.evidence, target.evidence)

    def test_wrong_upstream_artifact_type_fails_before_provider_execution(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = ArtifactStore(Path(directory))
            registry = ProviderRegistry(
                (
                    ProblemContractProvider(),
                    StaticProvider(
                        Capability.SPECTRAL_CORE,
                        "spectrum",
                        evidence(),
                        upstream_types=("different-contract",),
                    ),
                )
            )
            request = StudyRequest.from_mapping(
                dict(VALID_STUDY, target="spectral-core")
            )

            record = ExecutionEngine(store, registry).run(request)

            self.assertEqual(record.status, "FAILED")
            self.assertEqual(record.failed_capability, "spectral-core")
            self.assertIn("upstream artifact types", record.error)

    def test_malformed_provider_result_becomes_structured_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = ArtifactStore(Path(directory))
            registry = ProviderRegistry(
                (
                    ProblemContractProvider(),
                    MalformedProvider(
                        Capability.SPECTRAL_CORE,
                        "spectrum",
                        evidence(),
                        upstream_types=("problem-contract",),
                    ),
                )
            )
            request = StudyRequest.from_mapping(
                dict(VALID_STUDY, target="spectral-core")
            )

            record = ExecutionEngine(store, registry).run(request)

            self.assertEqual(record.status, "FAILED")
            self.assertEqual(record.failed_capability, "spectral-core")
            self.assertEqual(record.provider_execution_count, 1)
            self.assertIn("TypeError: provider must return ProviderResult", record.error)

    def test_provider_cannot_mutate_upstream_artifact_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = ArtifactStore(Path(directory))
            registry = ProviderRegistry(
                (
                    ProblemContractProvider(),
                    MutationProbeProvider(
                        Capability.SPECTRAL_CORE,
                        "spectrum",
                        evidence(),
                        upstream_types=("problem-contract",),
                    ),
                )
            )
            request = StudyRequest.from_mapping(
                dict(VALID_STUDY, target="spectral-core")
            )

            record = ExecutionEngine(store, registry).run(request)
            problem = store.load_artifact(
                record.artifact_ids["problem-contract"]
            )
            spectrum = store.load_artifact(record.artifact_ids["spectral-core"])

            self.assertEqual(record.status, "SUCCEEDED")
            self.assertTrue(spectrum.payload["top_level_blocked"])
            self.assertTrue(spectrum.payload["nested_blocked"])
            self.assertEqual(
                spectrum.payload["seen_request_sha256"],
                problem.payload["request_sha256"],
            )
            self.assertEqual(
                spectrum.upstream_artifact_ids,
                (problem.artifact_id,),
            )

    def test_provider_descriptor_is_snapshotted_before_execution(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = ArtifactStore(Path(directory))
            provider = DescriptorChangingProvider(
                Capability.SPECTRAL_CORE,
                "declared-output",
                evidence(),
                upstream_types=("problem-contract",),
            )
            registry = ProviderRegistry((ProblemContractProvider(), provider))
            request = StudyRequest.from_mapping(
                dict(VALID_STUDY, target="spectral-core")
            )

            record = ExecutionEngine(store, registry).run(request)
            spectrum = store.load_artifact(record.artifact_ids["spectral-core"])

            self.assertEqual(record.status, "SUCCEEDED")
            self.assertEqual(spectrum.artifact_type, "declared-output")
            self.assertEqual(
                spectrum.provider["output_artifact_type"],
                "declared-output",
            )
            verify_run_integrity(store, record)

    def test_publication_profile_accepts_complete_evaluated_adverse_or_supported_run(
        self,
    ) -> None:
        for conclusion in (
            ScientificState.SUPPORTED,
            ScientificState.CONTRADICTED,
        ):
            with self.subTest(conclusion=conclusion), tempfile.TemporaryDirectory() as directory:
                store = ArtifactStore(Path(directory))
                artifact_types = {
                    capability: capability.value for capability in Capability
                }
                providers = tuple(
                    StaticProvider(
                        capability,
                        artifact_types[capability],
                        evidence(scientific=conclusion),
                        upstream_types=tuple(
                            artifact_types[dependency]
                            for dependency in CAPABILITY_DEPENDENCIES[capability]
                        ),
                    )
                    for capability in Capability
                )
                request = StudyRequest.from_mapping(
                    dict(VALID_STUDY, target="evidence-package")
                )
                engine = ExecutionEngine(store, ProviderRegistry(providers))

                record = engine.run(request)
                artifacts = verify_run_integrity(
                    store, record, profile="publication"
                )

                self.assertEqual(record.status, "SUCCEEDED")
                self.assertEqual(record.evidence.scientific, conclusion)
                self.assertEqual(len(artifacts), len(Capability))

    def test_publication_profile_rejects_unevaluated_branch_hidden_by_contradiction(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = ArtifactStore(Path(directory))
            artifact_types = {
                capability: capability.value for capability in Capability
            }
            conclusions = {
                capability: ScientificState.SUPPORTED
                for capability in Capability
            }
            conclusions[Capability.OPERATOR_STABILITY] = (
                ScientificState.NOT_EVALUATED
            )
            conclusions[Capability.INVERSE_INFERENCE] = (
                ScientificState.CONTRADICTED
            )
            providers = tuple(
                StaticProvider(
                    capability,
                    artifact_types[capability],
                    evidence(scientific=conclusions[capability]),
                    upstream_types=tuple(
                        artifact_types[dependency]
                        for dependency in CAPABILITY_DEPENDENCIES[capability]
                    ),
                )
                for capability in Capability
            )
            request = StudyRequest.from_mapping(
                dict(VALID_STUDY, target="evidence-package")
            )
            record = ExecutionEngine(
                store, ProviderRegistry(providers)
            ).run(request)

            self.assertEqual(
                record.evidence.scientific,
                ScientificState.CONTRADICTED,
            )
            with self.assertRaisesRegex(
                ArtifactVerificationError,
                "publication evidence package has unevaluated evidence",
            ):
                verify_run_integrity(store, record, profile="publication")

    def test_run_record_hash_detects_unsealed_metadata_tampering(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = ArtifactStore(Path(directory))
            engine = ExecutionEngine(store, default_registry())
            record = engine.run(StudyRequest.from_mapping(VALID_STUDY))
            path = store.runs_directory / f"{record.run_id}.json"
            mapping = store.load_run_mapping(record.run_id)
            mapping["provider_execution_count"] = 999
            path.write_bytes(canonical_json_bytes(mapping))

            with self.assertRaisesRegex(
                ArtifactVerificationError, "run record content hash mismatch"
            ):
                engine.load_run(record.run_id)

    def test_duplicate_run_keys_are_rejected_before_record_hashing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = ArtifactStore(Path(directory))
            engine = ExecutionEngine(store, default_registry())
            record = engine.run(StudyRequest.from_mapping(VALID_STUDY))
            path = store.runs_directory / f"{record.run_id}.json"
            run_json = path.read_text(encoding="utf-8")
            path.write_text(
                '{"provider_execution_count":999,' + run_json[1:],
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                ArtifactVerificationError, "run .* is unreadable"
            ):
                engine.load_run(record.run_id)

    def test_cache_cannot_turn_failed_artifact_into_successful_run(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = ArtifactStore(Path(directory))
            request = StudyRequest.from_mapping(VALID_STUDY)
            provider = ProblemContractProvider()
            provider_mapping = provider.descriptor.to_mapping()
            envelope = ArtifactEnvelope(
                schema_version=1,
                artifact_type="problem-contract",
                capability=Capability.PROBLEM_CONTRACT,
                provider=provider_mapping,
                request=request.to_mapping(),
                upstream_artifact_ids=(),
                payload={"forged": True},
                evidence=evidence(execution=ExecutionState.FAILED),
            )
            artifact_id = store.put_artifact(envelope)
            cache_key = computation_cache_key(
                Capability.PROBLEM_CONTRACT,
                provider_mapping,
                request.to_mapping(),
                (),
            )
            store.bind_cache(cache_key, artifact_id)

            record = ExecutionEngine(store, default_registry()).run(request)

            self.assertEqual(record.status, "FAILED")
            self.assertEqual(record.failed_capability, "problem-contract")
            self.assertIn("cached artifact execution did not succeed", record.error)

    def test_cache_rejects_artifact_with_wrong_output_type(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = ArtifactStore(Path(directory))
            request = StudyRequest.from_mapping(VALID_STUDY)
            provider = ProblemContractProvider()
            provider_mapping = provider.descriptor.to_mapping()
            envelope = ArtifactEnvelope(
                schema_version=1,
                artifact_type="wrong-output-type",
                capability=Capability.PROBLEM_CONTRACT,
                provider=provider_mapping,
                request=request.to_mapping(),
                upstream_artifact_ids=(),
                payload={"forged": True},
                evidence=evidence(),
            )
            artifact_id = store.put_artifact(envelope)
            cache_key = computation_cache_key(
                Capability.PROBLEM_CONTRACT,
                provider_mapping,
                request.to_mapping(),
                (),
            )
            store.bind_cache(cache_key, artifact_id)

            record = ExecutionEngine(store, default_registry()).run(request)

            self.assertEqual(record.status, "FAILED")
            self.assertEqual(record.failed_capability, "problem-contract")
            self.assertIn(
                "cached artifact output type does not match provider",
                record.error,
            )

    def test_invalid_carrier_cannot_verify_as_successful_run(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = ArtifactStore(Path(directory))
            request = StudyRequest.from_mapping(VALID_STUDY)
            provider_mapping = ProblemContractProvider().descriptor.to_mapping()
            invalid_evidence = evidence(carrier=CarrierState.INVALID)
            envelope = ArtifactEnvelope(
                schema_version=1,
                artifact_type="problem-contract",
                capability=Capability.PROBLEM_CONTRACT,
                provider=provider_mapping,
                request=request.to_mapping(),
                upstream_artifact_ids=(),
                payload={"forged": True},
                evidence=invalid_evidence,
            )
            artifact_id = store.put_artifact(envelope)
            record = RunRecord(
                schema_version=1,
                run_id="a" * 32,
                target="problem-contract",
                request=request.to_mapping(),
                status="SUCCEEDED",
                plan=("problem-contract",),
                artifact_ids={"problem-contract": artifact_id},
                provider_execution_count=1,
                cache_hit_count=0,
                evidence=invalid_evidence,
            )

            with self.assertRaisesRegex(
                ArtifactVerificationError,
                "successful run metadata is inconsistent",
            ):
                RunRecord.from_mapping(record.to_mapping())
            with self.assertRaisesRegex(
                ArtifactVerificationError, "run artifact carrier is invalid"
            ):
                verify_run_integrity(store, record)


if __name__ == "__main__":
    unittest.main()
