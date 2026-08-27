"""Immutable, checkpointable promoted numerical artifacts.

This module deliberately models what a worker actually returned.  It does not
turn two independent worker requests into a fictional nine-sample request, and
it does not construct terminal schema-11 records.  Scheduler code may retain
these values; reducers and admission consume them later.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import hashlib
import json
from typing import Mapping

from .contracts import canonical_json_bytes
from .julia_response_backend import (
    FixedRootSurveyPlan,
    JuliaFixedRootSurveyBatch,
    fixed_root_survey_request_contract,
)


PROMOTED_CANONICAL_BACKGROUND_RECEIPT_SCHEMA = (
    "windows-solver.promoted-canonical-background-receipt/3"
)
PROMOTED_BACKGROUND_REUSE_KEY_SCHEMA = (
    "windows-solver.promoted-background-reuse-key/2"
)
PROMOTED_BACKGROUND_BINDING_SCHEMA = "windows-solver.promoted-background-binding/3"
PROMOTED_EXTERIOR_CALCULATION_SCHEMA = (
    "windows-solver.promoted-exterior-calculation/3"
)
PROMOTED_FIXED_ROOT_COMPOSITE_SCHEMA = (
    "windows-solver.promoted-fixed-root-composite/2"
)
PROMOTED_HORIZON_CALCULATION_SCHEMA = (
    "windows-solver.promoted-horizon-calculation/3"
)


def _sha256(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _is_sha256(value: object) -> bool:
    if not isinstance(value, str) or len(value) != 64:
        return False
    try:
        int(value, 16)
    except ValueError:
        return False
    return True


def _canonical_mapping(value: Mapping[str, object], label: str) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} is invalid")
    return json.loads(canonical_json_bytes(dict(value)))


def _decimal_text(value: object, label: str, *, positive: bool = False) -> str:
    """Return one canonical finite decimal without silently rounding it."""

    if not isinstance(value, str) or not value or value.strip() != value:
        raise ValueError(f"{label} is invalid")
    try:
        parsed = Decimal(value)
    except InvalidOperation as error:
        raise ValueError(f"{label} is invalid") from error
    if not parsed.is_finite() or (positive and parsed <= 0):
        raise ValueError(f"{label} is invalid")
    return str(parsed.normalize())


def _complex_mapping(value: Mapping[str, object], label: str) -> dict[str, str]:
    if not isinstance(value, Mapping) or set(value) != {"real", "imaginary"}:
        raise ValueError(f"{label} is invalid")
    return {
        "real": _decimal_text(value["real"], f"{label} real"),
        "imaginary": _decimal_text(value["imaginary"], f"{label} imaginary"),
    }


def _batch_complex_mapping(batch: JuliaFixedRootSurveyBatch) -> dict[str, str]:
    return {
        "real": _decimal_text(format(batch.fixed_root.real, ".17g"), "fixed root real"),
        "imaginary": _decimal_text(
            format(batch.fixed_root.imag, ".17g"), "fixed root imaginary"
        ),
    }


def _require_batch_plan(
    batch: JuliaFixedRootSurveyBatch,
    plan: FixedRootSurveyPlan,
    *,
    label: str,
) -> None:
    if not isinstance(batch, JuliaFixedRootSurveyBatch):
        raise ValueError(f"{label} batch is invalid")
    contract = fixed_root_survey_request_contract(plan)
    if (
        batch.scientific_operation_identity != contract.scientific_operation_identity
        or batch.sample_roles != contract.sample_roles
    ):
        raise ValueError(f"{label} batch does not match its request plan")


def _require_shared_batch_context(
    background: JuliaFixedRootSurveyBatch,
    component: JuliaFixedRootSurveyBatch,
) -> None:
    for field in (
        "root_reference_id",
        "root_seal_sha256",
        "branch_identity",
        "fixed_root",
        "frequency_step",
        "precision_tier",
        "working_precision_bits",
    ):
        if getattr(background, field) != getattr(component, field):
            raise ValueError("promoted fixed-root worker batches disagree on context")


@dataclass(frozen=True, slots=True)
class PromotedBackgroundReuseKey:
    """The exact non-leaf request context that may share five BF samples.

    This key names only the canonical zero-coupling Dω request.  The worker
    receipt retains the source leaf and its original request exactly; support,
    mechanism, amplitude-coordinate, and D_c material belongs exclusively to
    the consuming four-sample component request.
    """

    root_seal_sha256: str
    root_identity_sha256: str
    branch_identity: str
    angular_identity_sha256: str
    backend_identity_sha256: str
    numerical_controls_sha256: str
    fixed_root: Mapping[str, object]
    precision_tier: str
    working_precision_bits: int
    frequency_step: str
    background_operation_identity: str
    sample_roles: tuple[str, ...]

    def __post_init__(self) -> None:
        for name in (
            "root_seal_sha256",
            "root_identity_sha256",
            "angular_identity_sha256",
            "backend_identity_sha256",
            "numerical_controls_sha256",
        ):
            if not _is_sha256(getattr(self, name)):
                raise ValueError(f"promoted background reuse {name} is invalid")
        for name in (
            "branch_identity",
            "precision_tier",
            "background_operation_identity",
        ):
            if not isinstance(getattr(self, name), str) or not getattr(self, name):
                raise ValueError(f"promoted background reuse {name} is invalid")
        if self.precision_tier not in {"bigfloat-40", "bigfloat-80"}:
            raise ValueError("promoted background reuse precision tier is invalid")
        if (
            isinstance(self.working_precision_bits, bool)
            or not isinstance(self.working_precision_bits, int)
            or self.working_precision_bits < 2
        ):
            raise ValueError("promoted background reuse working precision is invalid")
        contract = fixed_root_survey_request_contract(
            FixedRootSurveyPlan.CANONICAL_BACKGROUND_FIVE
        )
        if (
            self.background_operation_identity != contract.scientific_operation_identity
            or tuple(self.sample_roles) != contract.sample_roles
        ):
            raise ValueError("promoted background reuse plan is invalid")
        object.__setattr__(
            self, "fixed_root", _complex_mapping(self.fixed_root, "promoted background fixed root")
        )
        object.__setattr__(
            self,
            "frequency_step",
            _decimal_text(self.frequency_step, "promoted background frequency step", positive=True),
        )
        object.__setattr__(self, "sample_roles", tuple(self.sample_roles))

    def _content(self) -> dict[str, object]:
        return {
            "schema": PROMOTED_BACKGROUND_REUSE_KEY_SCHEMA,
            "root_seal_sha256": self.root_seal_sha256,
            "root_identity_sha256": self.root_identity_sha256,
            "branch_identity": self.branch_identity,
            "angular_identity_sha256": self.angular_identity_sha256,
            "backend_identity_sha256": self.backend_identity_sha256,
            "numerical_controls_sha256": self.numerical_controls_sha256,
            "fixed_root": dict(self.fixed_root),
            "precision_tier": self.precision_tier,
            "working_precision_bits": self.working_precision_bits,
            "frequency_step": self.frequency_step,
            "background_operation_identity": self.background_operation_identity,
            "sample_roles": list(self.sample_roles),
        }

    @property
    def sha256(self) -> str:
        return _sha256(self._content())

    def to_mapping(self) -> dict[str, object]:
        return {**self._content(), "reuse_key_sha256": self.sha256}

    @classmethod
    def from_mapping(cls, value: object) -> "PromotedBackgroundReuseKey":
        fields = {
            "schema",
            "root_seal_sha256",
            "root_identity_sha256",
            "branch_identity",
            "angular_identity_sha256",
            "backend_identity_sha256",
            "numerical_controls_sha256",
            "fixed_root",
            "precision_tier",
            "working_precision_bits",
            "frequency_step",
            "background_operation_identity",
            "sample_roles",
            "reuse_key_sha256",
        }
        if (
            not isinstance(value, Mapping)
            or set(value) != fields
            or value.get("schema") != PROMOTED_BACKGROUND_REUSE_KEY_SCHEMA
            or not isinstance(value.get("sample_roles"), list)
        ):
            raise ValueError("promoted background reuse key is invalid")
        result = cls(
            root_seal_sha256=str(value["root_seal_sha256"]),
            root_identity_sha256=str(value["root_identity_sha256"]),
            branch_identity=str(value["branch_identity"]),
            angular_identity_sha256=str(value["angular_identity_sha256"]),
            backend_identity_sha256=str(value["backend_identity_sha256"]),
            numerical_controls_sha256=str(value["numerical_controls_sha256"]),
            fixed_root=value["fixed_root"],
            precision_tier=str(value["precision_tier"]),
            working_precision_bits=value["working_precision_bits"],
            frequency_step=str(value["frequency_step"]),
            background_operation_identity=str(value["background_operation_identity"]),
            sample_roles=tuple(value["sample_roles"]),
        )
        if value.get("reuse_key_sha256") != result.sha256 or result.to_mapping() != dict(value):
            raise ValueError("promoted background reuse key is not canonical")
        return result


@dataclass(frozen=True, slots=True)
class PromotedCanonicalBackgroundReceipt:
    """The authentic five-sample worker return retained before components run."""

    batch: JuliaFixedRootSurveyBatch
    cache_key_sha256: str
    reuse_key: Mapping[str, object]
    source_queue_ordinal: int
    source_leaf_id: str

    def __post_init__(self) -> None:
        _require_batch_plan(
            self.batch,
            FixedRootSurveyPlan.CANONICAL_BACKGROUND_FIVE,
            label="promoted canonical background",
        )
        if not _is_sha256(self.cache_key_sha256):
            raise ValueError("promoted canonical background cache key is invalid")
        if (
            isinstance(self.source_queue_ordinal, bool)
            or not isinstance(self.source_queue_ordinal, int)
            or self.source_queue_ordinal < 0
            or not isinstance(self.source_leaf_id, str)
            or not self.source_leaf_id
        ):
            raise ValueError("promoted canonical background source is invalid")
        if self.source_leaf_id != self.batch.leaf_id:
            raise ValueError("promoted canonical background source leaf is invalid")
        reuse_key = PromotedBackgroundReuseKey.from_mapping(self.reuse_key)
        if (
            self.cache_key_sha256 != reuse_key.sha256
            or reuse_key.root_seal_sha256 != self.batch.root_seal_sha256
            or reuse_key.branch_identity != self.batch.branch_identity
            or reuse_key.fixed_root != _batch_complex_mapping(self.batch)
            or reuse_key.precision_tier != self.batch.precision_tier.value
            or reuse_key.working_precision_bits != self.batch.working_precision_bits
            or reuse_key.frequency_step != _decimal_text(
                str(self.batch.frequency_step), "promoted background frequency step", positive=True
            )
            or reuse_key.background_operation_identity
            != self.batch.scientific_operation_identity
            or reuse_key.sample_roles != self.batch.sample_roles
        ):
            raise ValueError("promoted canonical background reuse binding is invalid")
        object.__setattr__(
            self,
            "reuse_key",
            reuse_key.to_mapping(),
        )

    @property
    def background_sha256(self) -> str:
        return _sha256({
            "worker_request_sha256": self.batch.request_sha256,
            "samples": self.batch.to_mapping()["samples"],
        })

    def to_mapping(self) -> dict[str, object]:
        content = {
            "schema": PROMOTED_CANONICAL_BACKGROUND_RECEIPT_SCHEMA,
            "cache_key_sha256": self.cache_key_sha256,
            "reuse_key": dict(self.reuse_key),
            "source_queue_ordinal": self.source_queue_ordinal,
            "source_leaf_id": self.source_leaf_id,
            "background_worker_request_sha256": self.batch.request_sha256,
            "background_worker_batch": self.batch.to_mapping(),
            "background_sha256": self.background_sha256,
        }
        return {**content, "receipt_sha256": _sha256(content)}


@dataclass(frozen=True, slots=True)
class PromotedBackgroundBinding:
    """A component's link to one previously retained background receipt."""

    background_receipt_sha256: str
    background_worker_request_sha256: str
    background_sha256: str
    background_reuse_key_sha256: str

    def __post_init__(self) -> None:
        if not all(
            _is_sha256(value)
            for value in (
                self.background_receipt_sha256,
                self.background_worker_request_sha256,
                self.background_sha256,
                self.background_reuse_key_sha256,
            )
        ):
            raise ValueError("promoted background binding digest is invalid")

    def to_mapping(self) -> dict[str, object]:
        content = {
            "schema": PROMOTED_BACKGROUND_BINDING_SCHEMA,
            "background_receipt_sha256": self.background_receipt_sha256,
            "background_worker_request_sha256": self.background_worker_request_sha256,
            "background_sha256": self.background_sha256,
            "background_reuse_key_sha256": self.background_reuse_key_sha256,
        }
        return {**content, "binding_sha256": _sha256(content)}


@dataclass(frozen=True, slots=True)
class PromotedExteriorCalculationResult:
    """The authentic four-sample component return and its retained background."""

    component_batch: JuliaFixedRootSurveyBatch
    background: PromotedBackgroundBinding

    def __post_init__(self) -> None:
        _require_batch_plan(
            self.component_batch,
            FixedRootSurveyPlan.MECHANISM_COMPONENT_FOUR,
            label="promoted exterior component",
        )
        if not isinstance(self.background, PromotedBackgroundBinding):
            raise ValueError("promoted exterior calculation background is invalid")

    def to_mapping(self) -> dict[str, object]:
        content = {
            "schema": PROMOTED_EXTERIOR_CALCULATION_SCHEMA,
            "component_worker_request_sha256": self.component_batch.request_sha256,
            "component_worker_batch": self.component_batch.to_mapping(),
            "background": self.background.to_mapping(),
        }
        return {**content, "calculation_sha256": _sha256(content)}


@dataclass(frozen=True, slots=True)
class PromotedFixedRootComposite:
    """A reducer-owned nine-sample view over two authentic worker results."""

    background_batch: JuliaFixedRootSurveyBatch
    component_batch: JuliaFixedRootSurveyBatch
    background_receipt_sha256: str

    def __post_init__(self) -> None:
        _require_batch_plan(
            self.background_batch,
            FixedRootSurveyPlan.CANONICAL_BACKGROUND_FIVE,
            label="promoted fixed-root background",
        )
        _require_batch_plan(
            self.component_batch,
            FixedRootSurveyPlan.MECHANISM_COMPONENT_FOUR,
            label="promoted fixed-root component",
        )
        _require_shared_batch_context(self.background_batch, self.component_batch)
        if not _is_sha256(self.background_receipt_sha256):
            raise ValueError("promoted fixed-root background receipt is invalid")

    @property
    def samples(self) -> tuple[object, ...]:
        return self.background_batch.samples + self.component_batch.samples

    @property
    def leaf_id(self) -> str:
        return self.component_batch.leaf_id

    @property
    def job_id(self) -> str:
        return self.component_batch.job_id

    @property
    def mechanism_id(self) -> str:
        return self.component_batch.mechanism_id

    @property
    def root_reference_id(self) -> str:
        return self.component_batch.root_reference_id

    @property
    def branch_identity(self) -> str:
        return self.background_batch.branch_identity

    @property
    def fixed_root(self):
        return self.background_batch.fixed_root

    @property
    def working_precision_bits(self) -> int:
        return self.background_batch.working_precision_bits

    @property
    def scientific_operation_identity(self) -> str:
        return "promoted-fixed-root-composite/v2"

    @property
    def frequency_step(self):
        return self.background_batch.frequency_step

    @property
    def coordinate_step(self):
        return self.component_batch.coordinate_step

    @property
    def precision_tier(self):
        return self.background_batch.precision_tier

    @property
    def root_seal_sha256(self) -> str:
        return self.background_batch.root_seal_sha256

    def to_mapping(self) -> dict[str, object]:
        content = {
            "schema": PROMOTED_FIXED_ROOT_COMPOSITE_SCHEMA,
            "operation_identity": self.scientific_operation_identity,
            # These fields name the consuming mechanism request.  The two
            # nested worker batches below retain their own, possibly earlier,
            # request identities without being rewritten to this leaf.
            "leaf_id": self.leaf_id,
            "job_id": self.job_id,
            "mechanism_id": self.mechanism_id,
            "root_reference_id": self.root_reference_id,
            "root_seal_sha256": self.root_seal_sha256,
            "branch_identity": self.branch_identity,
            "fixed_root": dict(self.component_batch.to_mapping()["fixed_root"]),
            "frequency_step": str(self.frequency_step),
            "coordinate_step": str(self.coordinate_step),
            "precision_tier": self.precision_tier.value,
            "working_precision_bits": self.working_precision_bits,
            "sample_roles": [sample.role for sample in self.samples],
            "sample_count": len(self.samples),
            "background_receipt_sha256": self.background_receipt_sha256,
            "background_worker_request_sha256": self.background_batch.request_sha256,
            "component_worker_request_sha256": self.component_batch.request_sha256,
            "background_worker_batch": self.background_batch.to_mapping(),
            "component_worker_batch": self.component_batch.to_mapping(),
        }
        return {**content, "composition_sha256": _sha256(content)}


@dataclass(frozen=True, slots=True)
class PromotedHorizonCalculationResult:
    """A raw BF80 horizon stage with external Layer-1 lineage.

    The predecessor digest is provenance, not a stage in a terminal record.
    ``component_stage`` is retained so admission can build a fresh terminal
    record after review without invoking a worker.
    """

    component_stage: Mapping[str, object]
    numerical_outcome: Mapping[str, object]
    predecessor_stage_sha256: str
    source_fingerprint_sha256: str
    layer1_lock_receipt_sha256: str

    def __post_init__(self) -> None:
        stage = _canonical_mapping(self.component_stage, "promoted horizon stage")
        outcome = _canonical_mapping(
            self.numerical_outcome, "promoted horizon numerical outcome"
        )
        content = {key: value for key, value in stage.items() if key != "stage_sha256"}
        if (
            not _is_sha256(stage.get("stage_sha256"))
            or stage["stage_sha256"] != _sha256(content)
            or stage.get("precision_tier") != "BF80"
            or stage.get("operation_identity") != "promoted-horizon-component/v2"
        ):
            raise ValueError("promoted horizon stage digest is invalid")
        if not all(
            _is_sha256(value)
            for value in (
                self.predecessor_stage_sha256,
                self.source_fingerprint_sha256,
                self.layer1_lock_receipt_sha256,
            )
        ):
            raise ValueError("promoted horizon calculation lineage is invalid")
        raw_component = outcome.get("component_result")
        if not isinstance(raw_component, Mapping):
            raise ValueError("promoted horizon numerical component is invalid")
        expected_component = dict(raw_component)
        if outcome.get("deep_diagnostics") is not None:
            if not isinstance(outcome["deep_diagnostics"], Mapping):
                raise ValueError("promoted horizon deep diagnostics are invalid")
            expected_component["deep_diagnostics"] = dict(
                outcome["deep_diagnostics"]
            )
        if set(outcome) != {
            "digits",
            "numerical_state",
            "component_result",
            "local_disk_radius_abs",
            "signed_error_channels",
            "deep_diagnostics",
            "self_refinement_enclosed",
            "discrepancy_from_previous_abs",
            "discrepancy_enclosed",
        } or outcome.get("digits") != 80 or (
            outcome.get("numerical_state") != stage.get("numerical_state")
            or expected_component != stage.get("component_result")
        ):
            raise ValueError("promoted horizon numerical outcome binding is invalid")
        object.__setattr__(self, "component_stage", stage)
        object.__setattr__(self, "numerical_outcome", outcome)

    def to_mapping(self) -> dict[str, object]:
        content = {
            "schema": PROMOTED_HORIZON_CALCULATION_SCHEMA,
            "component_stage": dict(self.component_stage),
            "component_stage_sha256": self.component_stage["stage_sha256"],
            "numerical_outcome": dict(self.numerical_outcome),
            "predecessor_stage_sha256": self.predecessor_stage_sha256,
            "source_fingerprint_sha256": self.source_fingerprint_sha256,
            "layer1_lock_receipt_sha256": self.layer1_lock_receipt_sha256,
        }
        return {**content, "calculation_sha256": _sha256(content)}

    @classmethod
    def from_mapping(cls, value: object) -> "PromotedHorizonCalculationResult":
        fields = {
            "schema",
            "component_stage",
            "component_stage_sha256",
            "numerical_outcome",
            "predecessor_stage_sha256",
            "source_fingerprint_sha256",
            "layer1_lock_receipt_sha256",
            "calculation_sha256",
        }
        if not isinstance(value, Mapping) or set(value) != fields:
            raise ValueError("promoted horizon calculation artifact is invalid")
        if value.get("schema") != PROMOTED_HORIZON_CALCULATION_SCHEMA:
            raise ValueError("promoted horizon calculation artifact schema is invalid")
        content = {
            key: item for key, item in value.items() if key != "calculation_sha256"
        }
        if (
            not _is_sha256(value.get("calculation_sha256"))
            or value.get("calculation_sha256") != _sha256(content)
            or not isinstance(value.get("component_stage"), Mapping)
        ):
            raise ValueError("promoted horizon calculation artifact digest is invalid")
        result = cls(
            component_stage=value["component_stage"],
            numerical_outcome=value["numerical_outcome"],
            predecessor_stage_sha256=str(value["predecessor_stage_sha256"]),
            source_fingerprint_sha256=str(value["source_fingerprint_sha256"]),
            layer1_lock_receipt_sha256=str(value["layer1_lock_receipt_sha256"]),
        )
        if (
            value.get("component_stage_sha256")
            != result.component_stage["stage_sha256"]
            or result.to_mapping() != dict(value)
        ):
            raise ValueError("promoted horizon calculation artifact is not canonical")
        return result


__all__ = [
    "PROMOTED_BACKGROUND_BINDING_SCHEMA",
    "PROMOTED_CANONICAL_BACKGROUND_RECEIPT_SCHEMA",
    "PROMOTED_BACKGROUND_REUSE_KEY_SCHEMA",
    "PROMOTED_EXTERIOR_CALCULATION_SCHEMA",
    "PROMOTED_FIXED_ROOT_COMPOSITE_SCHEMA",
    "PROMOTED_HORIZON_CALCULATION_SCHEMA",
    "PromotedBackgroundBinding",
    "PromotedBackgroundReuseKey",
    "PromotedCanonicalBackgroundReceipt",
    "PromotedExteriorCalculationResult",
    "PromotedFixedRootComposite",
    "PromotedHorizonCalculationResult",
]
