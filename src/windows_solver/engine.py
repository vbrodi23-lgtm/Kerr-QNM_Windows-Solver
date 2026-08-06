"""Resumable execution and sealed verification over the capability graph."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import re
from typing import Mapping
import uuid

from .artifacts import (
    ArtifactEnvelope,
    ArtifactStore,
    ArtifactVerificationError,
    _freeze_json,
    _thaw_json,
    computation_cache_key,
)
from .contracts import (
    Capability,
    CarrierState,
    EvidenceState,
    ExecutionState,
    NumericalState,
    ScientificState,
    StudyRequest,
    canonical_json_bytes,
)
from .planner import ExecutionPlan, build_plan
from .providers import ProviderRegistry, ProviderResult, ProviderUnavailableError


_RUN_ID = re.compile(r"[0-9a-f]{32}")
_CONTENT_ID = re.compile(r"[0-9a-f]{64}")
_RUN_STATUSES = frozenset({"SUCCEEDED", "FAILED"})
_PROVIDER_FIELDS = {
    "capability",
    "provider_id",
    "implementation_version",
    "equations_id",
    "conventions_id",
    "runtime_fingerprint",
    "numerical_policy_fingerprint",
    "upstream_artifact_types",
    "output_artifact_type",
    "available",
    "evidence_level",
}


def _strict_evidence(value: object) -> EvidenceState:
    if not isinstance(value, Mapping) or set(value) != {
        "carrier",
        "execution",
        "numerical",
        "scientific",
    }:
        raise ArtifactVerificationError("run evidence fields are invalid")
    try:
        return EvidenceState(
            carrier=CarrierState(value["carrier"]),
            execution=ExecutionState(value["execution"]),
            numerical=NumericalState(value["numerical"]),
            scientific=ScientificState(value["scientific"]),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise ArtifactVerificationError("run evidence values are invalid") from error


def _nonnegative_integer(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ArtifactVerificationError(f"run {name} is invalid")
    return value


def _optional_string(value: object, name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise ArtifactVerificationError(f"run {name} is invalid")
    return value


@dataclass(frozen=True, slots=True)
class RunRecord:
    schema_version: int
    run_id: str
    target: str
    request: Mapping[str, object]
    status: str
    plan: tuple[str, ...]
    artifact_ids: Mapping[str, str]
    provider_execution_count: int
    cache_hit_count: int
    evidence: EvidenceState
    unavailable_capability: str | None = None
    failed_capability: str | None = None
    error: str | None = None

    def __post_init__(self) -> None:
        request = _freeze_json(self.request)
        artifact_ids = _freeze_json(self.artifact_ids)
        if not isinstance(request, Mapping) or not isinstance(
            artifact_ids, Mapping
        ):
            raise TypeError("run mappings must be objects")
        object.__setattr__(self, "request", request)
        object.__setattr__(self, "artifact_ids", artifact_ids)
        object.__setattr__(self, "plan", tuple(self.plan))

    def identity_mapping(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "target": self.target,
            "request": _thaw_json(self.request),
            "status": self.status,
            "plan": list(self.plan),
            "artifact_ids": _thaw_json(self.artifact_ids),
            "provider_execution_count": self.provider_execution_count,
            "cache_hit_count": self.cache_hit_count,
            "evidence": self.evidence.to_mapping(),
            "unavailable_capability": self.unavailable_capability,
            "failed_capability": self.failed_capability,
            "error": self.error,
        }

    @property
    def record_sha256(self) -> str:
        return hashlib.sha256(canonical_json_bytes(self.identity_mapping())).hexdigest()

    def to_mapping(self) -> dict[str, object]:
        return {
            "record_sha256": self.record_sha256,
            **self.identity_mapping(),
        }

    @classmethod
    def from_mapping(
        cls,
        mapping: Mapping[str, object],
        *,
        expected_run_id: str | None = None,
    ) -> "RunRecord":
        expected_fields = {
            "record_sha256",
            "schema_version",
            "run_id",
            "target",
            "request",
            "status",
            "plan",
            "artifact_ids",
            "provider_execution_count",
            "cache_hit_count",
            "evidence",
            "unavailable_capability",
            "failed_capability",
            "error",
        }
        if not isinstance(mapping, Mapping) or set(mapping) != expected_fields:
            raise ArtifactVerificationError("run record fields are invalid")

        schema_version = mapping["schema_version"]
        run_id = mapping["run_id"]
        target = mapping["target"]
        request_mapping = mapping["request"]
        status = mapping["status"]
        plan = mapping["plan"]
        artifact_ids = mapping["artifact_ids"]
        record_sha256 = mapping["record_sha256"]
        if (
            isinstance(schema_version, bool)
            or not isinstance(schema_version, int)
            or schema_version != 1
        ):
            raise ArtifactVerificationError("run schema version is invalid")
        if not isinstance(run_id, str) or _RUN_ID.fullmatch(run_id) is None:
            raise ArtifactVerificationError("run identity is invalid")
        if expected_run_id is not None and run_id != expected_run_id:
            raise ArtifactVerificationError("run record identity mismatch")
        try:
            target_capability = Capability(target)
        except (TypeError, ValueError) as error:
            raise ArtifactVerificationError("run target is invalid") from error
        if not isinstance(request_mapping, Mapping):
            raise ArtifactVerificationError("run request is invalid")
        try:
            request = StudyRequest.from_mapping(_thaw_json(request_mapping))
        except ValueError as error:
            raise ArtifactVerificationError("run request is invalid") from error
        if request.to_mapping() != _thaw_json(request_mapping):
            raise ArtifactVerificationError("run request is not canonical")
        if request.target is not target_capability:
            raise ArtifactVerificationError("run request target mismatch")
        if not isinstance(status, str) or status not in _RUN_STATUSES:
            raise ArtifactVerificationError("run status is invalid")
        if (
            not isinstance(plan, list)
            or not all(isinstance(item, str) for item in plan)
            or len(plan) != len(set(plan))
        ):
            raise ArtifactVerificationError("run plan is invalid")
        try:
            plan_capabilities = tuple(Capability(item).value for item in plan)
        except ValueError as error:
            raise ArtifactVerificationError("run plan is invalid") from error
        if not isinstance(artifact_ids, Mapping) or not all(
            isinstance(key, str)
            and isinstance(value, str)
            and _CONTENT_ID.fullmatch(value) is not None
            for key, value in artifact_ids.items()
        ):
            raise ArtifactVerificationError("run artifact identities are invalid")
        try:
            normalized_artifacts = {
                Capability(key).value: value for key, value in artifact_ids.items()
            }
        except ValueError as error:
            raise ArtifactVerificationError("run artifact capabilities are invalid") from error
        if not isinstance(record_sha256, str) or _CONTENT_ID.fullmatch(record_sha256) is None:
            raise ArtifactVerificationError("run record hash is invalid")

        record = cls(
            schema_version=schema_version,
            run_id=run_id,
            target=target_capability.value,
            request=request.to_mapping(),
            status=status,
            plan=plan_capabilities,
            artifact_ids=normalized_artifacts,
            provider_execution_count=_nonnegative_integer(
                mapping["provider_execution_count"], "provider execution count"
            ),
            cache_hit_count=_nonnegative_integer(
                mapping["cache_hit_count"], "cache hit count"
            ),
            evidence=_strict_evidence(mapping["evidence"]),
            unavailable_capability=_optional_string(
                mapping["unavailable_capability"], "unavailable capability"
            ),
            failed_capability=_optional_string(
                mapping["failed_capability"], "failed capability"
            ),
            error=_optional_string(mapping["error"], "error"),
        )
        if record.record_sha256 != record_sha256:
            raise ArtifactVerificationError("run record content hash mismatch")
        for name, capability_value in (
            ("unavailable capability", record.unavailable_capability),
            ("failed capability", record.failed_capability),
        ):
            if capability_value is not None:
                try:
                    Capability(capability_value)
                except ValueError as error:
                    raise ArtifactVerificationError(f"run {name} is invalid") from error
        if record.status == "SUCCEEDED" and (
            record.unavailable_capability is not None
            or record.failed_capability is not None
            or record.error is not None
            or record.evidence.execution is not ExecutionState.SUCCEEDED
            or record.evidence.carrier is CarrierState.INVALID
        ):
            raise ArtifactVerificationError("successful run metadata is inconsistent")
        if record.status == "FAILED" and (
            record.error is None
            or record.evidence.execution is not ExecutionState.FAILED
            or (record.unavailable_capability is None)
            == (record.failed_capability is None)
        ):
            raise ArtifactVerificationError("failed run metadata is inconsistent")
        return record


def _failed_evidence() -> EvidenceState:
    return EvidenceState(
        carrier=CarrierState.VALID,
        execution=ExecutionState.FAILED,
        numerical=NumericalState.NOT_EVALUATED,
        scientific=ScientificState.NOT_EVALUATED,
    )


def _error_text(error: Exception) -> str:
    return f"{type(error).__name__}: {error}"


class ExecutionEngine:
    def __init__(self, store: ArtifactStore, registry: ProviderRegistry) -> None:
        self.store = store
        self.registry = registry

    def _failure_record(
        self,
        *,
        run_id: str,
        plan: ExecutionPlan,
        request: StudyRequest,
        artifact_ids: Mapping[str, str],
        execution_count: int,
        cache_hit_count: int,
        error: Exception,
        failed_capability: Capability | None = None,
        unavailable_capability: Capability | None = None,
    ) -> RunRecord:
        record = RunRecord(
            schema_version=1,
            run_id=run_id,
            target=plan.target.value,
            request=request.to_mapping(),
            status="FAILED",
            plan=tuple(item.value for item in plan.capabilities),
            artifact_ids=dict(artifact_ids),
            provider_execution_count=execution_count,
            cache_hit_count=cache_hit_count,
            evidence=_failed_evidence(),
            unavailable_capability=(
                unavailable_capability.value
                if unavailable_capability is not None
                else None
            ),
            failed_capability=(
                failed_capability.value if failed_capability is not None else None
            ),
            error=str(error) if isinstance(error, ProviderUnavailableError) else _error_text(error),
        )
        self.store.put_run_mapping(run_id, record.to_mapping())
        return record

    def run(self, request: StudyRequest) -> RunRecord:
        plan = build_plan(request.target)
        run_id = uuid.uuid4().hex
        try:
            providers = {
                capability: self.registry.resolve(capability)
                for capability in plan.capabilities
            }
        except ProviderUnavailableError as error:
            return self._failure_record(
                run_id=run_id,
                plan=plan,
                request=request,
                artifact_ids={},
                execution_count=0,
                cache_hit_count=0,
                error=error,
                unavailable_capability=error.capability,
            )
        descriptors = {
            capability: providers[capability].descriptor
            for capability in plan.capabilities
        }
        for capability, descriptor in descriptors.items():
            if descriptor.capability is not capability:
                return self._failure_record(
                    run_id=run_id,
                    plan=plan,
                    request=request,
                    artifact_ids={},
                    execution_count=0,
                    cache_hit_count=0,
                    error=ValueError("provider descriptor capability changed"),
                    failed_capability=capability,
                )

        envelopes: dict[Capability, ArtifactEnvelope] = {}
        artifact_ids: dict[str, str] = {}
        execution_count = 0
        cache_hit_count = 0
        for capability in plan.capabilities:
            provider = providers[capability]
            descriptor = descriptors[capability]
            scoped_request = request.for_capability(capability)
            request_mapping = scoped_request.to_mapping()
            direct_dependencies = plan.dependencies[capability]
            upstream_envelopes = tuple(
                envelopes[dependency] for dependency in direct_dependencies
            )
            upstream_ids = tuple(
                envelope.artifact_id for envelope in upstream_envelopes
            )
            try:
                actual_upstream_types = tuple(
                    envelope.artifact_type for envelope in upstream_envelopes
                )
                expected_upstream_types = descriptor.upstream_artifact_types
                if actual_upstream_types != expected_upstream_types:
                    raise ValueError(
                        "provider upstream artifact types do not match direct dependencies: "
                        f"expected {expected_upstream_types!r}, got {actual_upstream_types!r}"
                    )

                provider_mapping = descriptor.to_mapping()
                cache_key = computation_cache_key(
                    capability,
                    provider_mapping,
                    request_mapping,
                    upstream_ids,
                )
                envelope = self.store.lookup_cache(cache_key)
                if envelope is None:
                    upstream = {
                        dependency: envelope
                        for dependency, envelope in zip(
                            direct_dependencies, upstream_envelopes, strict=True
                        )
                    }
                    result = provider.execute(scoped_request, upstream)
                    if not isinstance(result, ProviderResult):
                        raise TypeError("provider must return ProviderResult")
                    if not isinstance(result.payload, Mapping):
                        raise TypeError("provider payload must be an object")
                    if not isinstance(result.evidence, EvidenceState):
                        raise TypeError("provider evidence must be EvidenceState")
                    constrained_evidence = result.evidence.constrained_by(
                        tuple(item.evidence for item in upstream_envelopes)
                    )
                    if constrained_evidence.execution is not ExecutionState.SUCCEEDED:
                        raise ValueError("provider result execution did not succeed")
                    if constrained_evidence.carrier is CarrierState.INVALID:
                        raise ValueError("provider result carrier is invalid")
                    envelope = ArtifactEnvelope(
                        schema_version=1,
                        artifact_type=descriptor.output_artifact_type,
                        capability=capability,
                        provider=provider_mapping,
                        request=request_mapping,
                        upstream_artifact_ids=upstream_ids,
                        payload=dict(result.payload),
                        evidence=constrained_evidence,
                    )
                    artifact_id = self.store.put_artifact(envelope)
                    self.store.bind_cache(cache_key, artifact_id)
                    execution_count += 1
                else:
                    if (
                        envelope.capability is not capability
                        or _thaw_json(envelope.provider) != provider_mapping
                        or _thaw_json(envelope.request) != request_mapping
                        or envelope.upstream_artifact_ids != upstream_ids
                    ):
                        raise ArtifactVerificationError(
                            "cached artifact contract does not match request"
                        )
                    if (
                        envelope.artifact_type
                        != descriptor.output_artifact_type
                    ):
                        raise ArtifactVerificationError(
                            "cached artifact output type does not match provider"
                        )
                    constrained_evidence = envelope.evidence.constrained_by(
                        tuple(item.evidence for item in upstream_envelopes)
                    )
                    if constrained_evidence != envelope.evidence:
                        raise ArtifactVerificationError(
                            "cached artifact evidence exceeds upstream evidence"
                        )
                    if envelope.evidence.execution is not ExecutionState.SUCCEEDED:
                        raise ArtifactVerificationError(
                            "cached artifact execution did not succeed"
                        )
                    if envelope.evidence.carrier is CarrierState.INVALID:
                        raise ArtifactVerificationError(
                            "cached artifact carrier is invalid"
                        )
                    cache_hit_count += 1
            except Exception as error:
                return self._failure_record(
                    run_id=run_id,
                    plan=plan,
                    request=request,
                    artifact_ids=artifact_ids,
                    execution_count=execution_count,
                    cache_hit_count=cache_hit_count,
                    error=error,
                    failed_capability=capability,
                )
            envelopes[capability] = envelope
            artifact_ids[capability.value] = envelope.artifact_id

        target_evidence = envelopes[request.target].evidence
        record = RunRecord(
            schema_version=1,
            run_id=run_id,
            target=request.target.value,
            request=request.to_mapping(),
            status="SUCCEEDED",
            plan=tuple(item.value for item in plan.capabilities),
            artifact_ids=artifact_ids,
            provider_execution_count=execution_count,
            cache_hit_count=cache_hit_count,
            evidence=target_evidence,
        )
        try:
            verify_run_integrity(self.store, record, profile="research")
        except Exception as error:
            return self._failure_record(
                run_id=run_id,
                plan=plan,
                request=request,
                artifact_ids=artifact_ids,
                execution_count=execution_count,
                cache_hit_count=cache_hit_count,
                error=error,
                failed_capability=request.target,
            )
        self.store.put_run_mapping(run_id, record.to_mapping())
        return record

    def load_run(self, run_id: str) -> RunRecord:
        return RunRecord.from_mapping(
            self.store.load_run_mapping(run_id), expected_run_id=run_id
        )


def verify_run_integrity(
    store: ArtifactStore,
    record: RunRecord,
    *,
    profile: str = "research",
) -> dict[str, ArtifactEnvelope]:
    """Verify the sealed run, complete closure, lineage, and evidence ceiling."""

    if record.status != "SUCCEEDED":
        raise ArtifactVerificationError("run did not complete successfully")
    try:
        target = Capability(record.target)
    except ValueError as error:
        raise ArtifactVerificationError("run target is invalid") from error
    if profile == "publication" and target is not Capability.EVIDENCE_PACKAGE:
        raise ArtifactVerificationError(
            "publication verification requires a complete evidence-package run"
        )
    if profile not in {"research", "publication"}:
        raise ArtifactVerificationError("verification profile is invalid")
    if not isinstance(record.request, Mapping):
        raise ArtifactVerificationError("run request is invalid")
    try:
        request = StudyRequest.from_mapping(_thaw_json(record.request))
    except ValueError as error:
        raise ArtifactVerificationError("run request is invalid") from error
    if request.to_mapping() != _thaw_json(record.request):
        raise ArtifactVerificationError("run request is not canonical")
    if request.target is not target:
        raise ArtifactVerificationError("run request target mismatch")

    plan = build_plan(target)
    expected_plan = tuple(capability.value for capability in plan.capabilities)
    if record.plan != expected_plan:
        raise ArtifactVerificationError("run plan does not match target")
    if set(record.artifact_ids) != set(expected_plan):
        raise ArtifactVerificationError("run artifact closure is incomplete")
    if (
        record.provider_execution_count + record.cache_hit_count
        != len(expected_plan)
    ):
        raise ArtifactVerificationError("run execution accounting is inconsistent")

    envelopes: dict[Capability, ArtifactEnvelope] = {}
    for capability in plan.capabilities:
        envelope = store.load_artifact(record.artifact_ids[capability.value])
        if envelope.capability is not capability:
            raise ArtifactVerificationError("run artifact capability mismatch")
        expected_request = request.for_capability(capability).to_mapping()
        if _thaw_json(envelope.request) != expected_request:
            raise ArtifactVerificationError(
                "run artifact request scope mismatch"
            )

        direct_dependencies = plan.dependencies[capability]
        expected_upstream_ids = tuple(
            envelopes[dependency].artifact_id for dependency in direct_dependencies
        )
        if envelope.upstream_artifact_ids != expected_upstream_ids:
            raise ArtifactVerificationError("run artifact lineage mismatch")
        expected_types = tuple(
            envelopes[dependency].artifact_type for dependency in direct_dependencies
        )
        provider_upstream_types = envelope.provider.get("upstream_artifact_types")
        if set(envelope.provider) != _PROVIDER_FIELDS:
            raise ArtifactVerificationError("run provider fields are invalid")
        provider_string_fields = _PROVIDER_FIELDS - {
            "upstream_artifact_types",
            "available",
        }
        if not all(
            isinstance(envelope.provider.get(field), str)
            and bool(envelope.provider[field].strip())
            for field in provider_string_fields
        ) or envelope.provider.get("available") is not True:
            raise ArtifactVerificationError("run provider values are invalid")
        if not isinstance(provider_upstream_types, (list, tuple)) or tuple(
            provider_upstream_types
        ) != expected_types:
            raise ArtifactVerificationError("run provider upstream artifact types mismatch")
        if envelope.provider.get("capability") != capability.value:
            raise ArtifactVerificationError("run provider capability mismatch")
        if envelope.provider.get("output_artifact_type") != envelope.artifact_type:
            raise ArtifactVerificationError("run provider output artifact type mismatch")
        constrained = envelope.evidence.constrained_by(
            tuple(envelopes[item].evidence for item in direct_dependencies)
        )
        if constrained != envelope.evidence:
            raise ArtifactVerificationError(
                "run artifact evidence exceeds upstream evidence"
            )
        if envelope.evidence.execution is not ExecutionState.SUCCEEDED:
            raise ArtifactVerificationError("run artifact execution did not succeed")
        if envelope.evidence.carrier is CarrierState.INVALID:
            raise ArtifactVerificationError("run artifact carrier is invalid")
        envelopes[capability] = envelope

    target_envelope = envelopes[target]
    if record.evidence != target_envelope.evidence:
        raise ArtifactVerificationError("run evidence does not match target artifact")
    if profile == "publication" and any(
        envelope.evidence.numerical is NumericalState.NOT_EVALUATED
        or envelope.evidence.scientific is ScientificState.NOT_EVALUATED
        for envelope in envelopes.values()
    ):
        raise ArtifactVerificationError(
            "publication evidence package has unevaluated evidence"
        )
    return {capability.value: envelope for capability, envelope in envelopes.items()}
