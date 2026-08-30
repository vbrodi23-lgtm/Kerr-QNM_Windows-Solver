from __future__ import annotations

from decimal import Decimal, localcontext
import hashlib
import json
import os
from pathlib import Path
import shutil
import unittest

from windows_solver.contracts import canonical_json_bytes
from windows_solver.julia_response_backend import (
    FixedRootSurveyPlan,
    JuliaPrecisionRootBackend,
    JuliaResponseAdapter,
)
from windows_solver.progress import (
    ProgressEventKind,
    activate_progress,
)
from windows_solver.promoted_artifacts import (
    PromotedBackgroundReuseKey,
    PromotedCanonicalBackgroundReceipt,
    PromotedFixedRootComposite,
)
from windows_solver.promoted_control_calibration import (
    empirical_exterior_determinant_error_abs,
    load_default_calibration_receipt,
)
from windows_solver.response_batches import (
    PrecisionCapabilities,
    build_campaign_plan,
)
from windows_solver.response_engine import (
    BINARY64_FIXED_ROOT_SAMPLE_ROLES,
    NumericalPolicy,
    VettedNativeDeterminantKernel,
)


REAL_INNER_POLICY = (
    "cause-aware-real-inner-fixed-root-exterior-endpoint-recovery/v2"
)
MECHANISMS = (
    "exterior-alpha-half",
    "exterior-light-ring",
    "exterior-throat-kappa",
)


class _Observer:
    def __init__(self) -> None:
        self.events = []

    def publish(self, event) -> None:
        self.events.append(event)


@unittest.skipUnless(
    os.environ.get("PR76_REAL_INNER_PRODUCTION_SEAM") == "1",
    "real-inner installed-worker production seam is not enabled",
)
class M02ExteriorRealInnerProductionSeamTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        root = Path(__file__).resolve().parents[1]
        receipt_path = os.environ.get("M02_WORKER_BUNDLE_RECEIPT")
        if not receipt_path:
            raise AssertionError("M02 worker bundle receipt is unavailable")
        cls.bundle_receipt = json.loads(Path(receipt_path).read_text(encoding="utf-8"))
        receipt_material = {
            key: value for key, value in cls.bundle_receipt.items()
            if key != "receipt_sha256"
        }
        if cls.bundle_receipt.get("receipt_sha256") != hashlib.sha256(
            canonical_json_bytes(receipt_material)
        ).hexdigest():
            raise AssertionError("M02 worker bundle receipt digest is invalid")
        worker = Path(cls.bundle_receipt["worker_path"]).resolve()
        source_worker = (
            root / "src/windows_solver/data/julia/m02_worker.jl"
        ).resolve()
        if worker == source_worker or worker.read_bytes() != source_worker.read_bytes():
            raise AssertionError("production seam did not select the immutable worker")
        contract = cls.bundle_receipt["worker_contract"]
        ordered_contract = {
            field: contract[field]
            for field in (
                "schema_version",
                "worker_sha256",
                "fixed_root_authority_sha256",
                "promoted_calibration_sha256",
            )
        }
        bootstrap_contract_sha256 = hashlib.sha256(json.dumps(
            ordered_contract,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=False,
        ).encode("utf-8")).hexdigest()
        if (
            cls.bundle_receipt["worker_contract_sha256"]
            != bootstrap_contract_sha256
            or cls.bundle_receipt["worker_contract_id"]
            != f"m02-worker-{bootstrap_contract_sha256[:24]}"
        ):
            raise AssertionError("M02 worker identity differs from bootstrap")
        if hashlib.sha256(worker.read_bytes()).hexdigest() != contract[
            "worker_sha256"
        ]:
            raise AssertionError("installed worker digest is invalid")

        executable = shutil.which("julia")
        project = os.environ.get("M02_PROJECT")
        depot = os.environ.get("JULIA_DEPOT_PATH")
        if executable is None or project is None:
            raise AssertionError("Julia seam runtime is unavailable")
        executable_path = Path(executable).resolve()
        project_path = Path(project).resolve()
        depot_path = Path(
            depot.split(os.pathsep)[0] if depot else Path.home() / ".julia"
        ).resolve()
        manifest = project_path / "Manifest.toml"
        runtime_policy = root / "runtime/runtime_policy.json"
        provenance = {
            "julia_version": "1.10.11",
            "julia_executable_sha256": hashlib.sha256(
                executable_path.read_bytes()
            ).hexdigest(),
            "julia_manifest_sha256": hashlib.sha256(
                manifest.read_bytes()
            ).hexdigest(),
            "worker_sha256": contract["worker_sha256"],
            "worker_contract_id": cls.bundle_receipt["worker_contract_id"],
            "runtime_policy_sha256": hashlib.sha256(
                runtime_policy.read_bytes()
            ).hexdigest(),
            "scientific_sources": [],
        }
        cls.adapter = JuliaResponseAdapter(
            julia_executable=executable_path,
            julia_project=project_path,
            julia_depot=depot_path,
            worker_script=worker,
            runtime_provenance=provenance,
        )
        plan = build_campaign_plan(
            policy=NumericalPolicy(),
            backend_identity=VettedNativeDeterminantKernel.identity,
            precision_capabilities=PrecisionCapabilities((64, 80, 120)),
        )
        cls.jobs = {
            (format(leaf.job.spin, ".17g"), leaf.job.mechanism_id): leaf.job
            for leaf in plan.leaves
            if (
                leaf.job.mode.s,
                leaf.job.mode.ell,
                leaf.job.mode.m,
                leaf.job.mode.n,
            ) == (-2, 2, 2, 0)
            and format(leaf.job.spin, ".17g") in {
                "0.94999999999999996", "0.98999999999999999"
            }
            and leaf.job.mechanism_id in MECHANISMS
        }
        if len(cls.jobs) != 6:
            raise AssertionError("production seam did not resolve its six jobs")
        reference = json.loads((
            root / "tests/fixtures/m02_exterior_real_inner_canary_reference_v1.json"
        ).read_text(encoding="utf-8"))
        cls.references = {
            (case["spin"], case["mechanism_id"]): case["determinant"]
            for case in reference["cases"]
        }
        cls.calibration = load_default_calibration_receipt()

    @classmethod
    def _backend(cls, refinement: int = 0) -> JuliaPrecisionRootBackend:
        return JuliaPrecisionRootBackend(
            VettedNativeDeterminantKernel.identity,
            cls.adapter,
            40,
            refinement=refinement,
            empirical_control_profile=cls.calibration.budget_for(
                "exterior-wronskian/v1", 40
            ),
            calibration_receipt=cls.calibration,
        )

    def _run_batch(self, job, plan, *, refinement: int = 0):
        backend = self._backend(refinement)
        prepared = backend.prepare_fixed_root_survey_request(
            job,
            fixed_root=job.root.omega,
            root_seal_sha256="1" * 64,
            branch_identity=job.root.branch_id,
            plan=plan,
        )
        observer = _Observer()
        with activate_progress(observer):
            batch = backend.fixed_root_survey_batch(
                job,
                fixed_root=job.root.omega,
                root_seal_sha256="1" * 64,
                branch_identity=job.root.branch_id,
                plan=plan,
                prepared_request=prepared,
            )
        policy = prepared.request["fixed_root_endpoint_recovery_policy"]
        expected_roles = (
            BINARY64_FIXED_ROOT_SAMPLE_ROLES[:5]
            if plan is FixedRootSurveyPlan.CANONICAL_BACKGROUND_FIVE
            else BINARY64_FIXED_ROOT_SAMPLE_ROLES[5:]
        )
        self.assertIs(batch.plan, plan)
        self.assertEqual(batch.sample_roles, expected_roles)
        self.assertEqual(batch.sample_count, len(expected_roles))
        self.assertEqual(tuple(prepared.request["sample_roles"]), expected_roles)
        self.assertEqual(policy["identity"], REAL_INNER_POLICY)
        self.assertEqual(
            policy["horizon_geometry_schedule"],
            [
                "-10", "-25", "-50", "-75", "-100", "-150", "-225",
                "-337.5", "-400",
            ],
        )
        self.assertEqual(batch.request_sha256, prepared.request_sha256)
        self.assertEqual(
            batch.execution_identity["request_sha256"],
            prepared.request_sha256,
        )
        self.assertEqual(batch.precision_tier.value, "bigfloat-40")
        for sample in batch.samples:
            determinant = sample.determinant
            self.assertTrue(determinant.real.is_finite())
            self.assertTrue(determinant.imaginary.is_finite())
            conditioning = sample.numerical_conditioning.mapping
            horizon = conditioning["endpoint_receipts"][0]
            self.assertEqual(horizon["schema"],
                "windows-solver.exterior-endpoint-recovery-receipt/2")
            self.assertEqual(horizon["contour_identity"],
                "real-inner-tortoise-contour/v1")
            self.assertIs(horizon["coordinate_identity"]["passed"], True)
            self.assertEqual(horizon["candidate_limitation"], "adequate/v1")
            self.assertEqual(horizon[
                "factored_homogeneous_rhs_evaluations_before_decision"
            ], 0)
        factored = [
            event for event in observer.events
            if event.kind is ProgressEventKind.FACTORED_ODE_COMPLETED
        ]
        self.assertTrue(factored)
        self.assertTrue(any(
            event.payload["factored_homogeneous_rhs_evaluations"] > 0
            for event in factored
        ))
        return batch

    @staticmethod
    def _background_receipt(job, batch) -> PromotedCanonicalBackgroundReceipt:
        angular_identity = hashlib.sha256(canonical_json_bytes({
            "angular_separation_constant": {
                "real": format(job.root.angular_separation_constant.real, ".17g"),
                "imaginary": format(
                    job.root.angular_separation_constant.imag, ".17g"
                ),
            },
            "angular_owner": job.root.owner_data_sha256,
        })).hexdigest()
        key = PromotedBackgroundReuseKey(
            root_seal_sha256=batch.root_seal_sha256,
            root_identity_sha256=job.root.identity_sha256,
            branch_identity=batch.branch_identity,
            angular_identity_sha256=angular_identity,
            backend_identity_sha256=job.backend_identity.identity_sha256,
            numerical_controls_sha256=job.policy.identity_sha256,
            fixed_root={
                "real": format(batch.fixed_root.real, ".17g"),
                "imaginary": format(batch.fixed_root.imag, ".17g"),
            },
            precision_tier=batch.precision_tier.value,
            working_precision_bits=batch.working_precision_bits,
            frequency_step=str(batch.frequency_step),
            background_operation_identity=batch.scientific_operation_identity,
            sample_roles=batch.sample_roles,
        )
        return PromotedCanonicalBackgroundReceipt(
            batch=batch,
            cache_key_sha256=key.sha256,
            reuse_key=key.to_mapping(),
            source_queue_ordinal=0,
            source_leaf_id=batch.leaf_id,
        )

    def test_two_backgrounds_six_components_and_authenticated_joins(self):
        backgrounds = {}
        components = {}
        tight_components = {}
        composites = {}
        for spin in ("0.94999999999999996", "0.98999999999999999"):
            background_job = self.jobs[(spin, "exterior-alpha-half")]
            background = self._run_batch(
                background_job, FixedRootSurveyPlan.CANONICAL_BACKGROUND_FIVE
            )
            backgrounds[spin] = background
            background_receipt = self._background_receipt(background_job, background)
            receipt_sha256 = background_receipt.to_mapping()["receipt_sha256"]
            for mechanism in MECHANISMS:
                job = self.jobs[(spin, mechanism)]
                component = self._run_batch(
                    job, FixedRootSurveyPlan.MECHANISM_COMPONENT_FOUR
                )
                components[(spin, mechanism)] = component
                composite = PromotedFixedRootComposite(
                    background_batch=background,
                    component_batch=component,
                    background_receipt_sha256=receipt_sha256,
                )
                mapping = composite.to_mapping()
                material = {
                    key: value for key, value in mapping.items()
                    if key != "composition_sha256"
                }
                self.assertEqual(len(composite.samples), 9)
                self.assertEqual(
                    tuple(sample.role for sample in composite.samples),
                    BINARY64_FIXED_ROOT_SAMPLE_ROLES,
                )
                self.assertEqual(
                    mapping["composition_sha256"],
                    hashlib.sha256(canonical_json_bytes(material)).hexdigest(),
                )
                composites[(spin, mechanism)] = composite
                tight_components[(spin, mechanism)] = self._run_batch(
                    job,
                    FixedRootSurveyPlan.MECHANISM_COMPONENT_FOUR,
                    refinement=1,
                )

        for key, component in components.items():
            spin, mechanism = key
            base_sample = next(
                sample for sample in component.samples
                if sample.role == "DC_PLUS_EPSILON"
            )
            tight_sample = next(
                sample for sample in tight_components[key].samples
                if sample.role == "DC_PLUS_EPSILON"
            )
            reference = self.references[key]
            with localcontext() as context:
                context.prec = 100
                base = complex(
                    float(base_sample.determinant.real),
                    float(base_sample.determinant.imaginary),
                )
                tight = complex(
                    float(tight_sample.determinant.real),
                    float(tight_sample.determinant.imaginary),
                )
                expected = complex(
                    float(Decimal(reference["real"])),
                    float(Decimal(reference["imaginary"])),
                )
                delta_same_point = abs(base - tight)
                comparator_radius = empirical_exterior_determinant_error_abs(
                    delta_same_point=delta_same_point,
                    delta_cross_precision=0.0,
                    delta_endpoint_series=0.0,
                )
            self.assertLessEqual(abs(base - expected), comparator_radius)

        first = composites[("0.94999999999999996", "exterior-alpha-half")]
        with self.assertRaisesRegex(ValueError, "context"):
            PromotedFixedRootComposite(
                background_batch=backgrounds["0.98999999999999999"],
                component_batch=first.component_batch,
                background_receipt_sha256=first.background_receipt_sha256,
            )
        with self.assertRaisesRegex(ValueError, "policy"):
            PromotedFixedRootComposite(
                background_batch=backgrounds["0.94999999999999996"],
                component_batch=tight_components[
                    ("0.94999999999999996", "exterior-alpha-half")
                ],
                background_receipt_sha256=first.background_receipt_sha256,
            )
