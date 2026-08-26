# Layer 2 Calculation and Admission Separation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Execute and durably retain the locked 172 BF40 exterior and 40 BF80 horizon routes under the canonical `CALCULATE_ONLY` policy, then admit retained work without numerical recomputation.

**Architecture:** The calibration parser returns a typed execution mode. Schema-11 keeps routing and digest pointers in the promotion queue while checkpoint-owned promoted stage, background, and root ledgers retain Layer-2 work under explicit numerically-terminal admission-pending states. A separate admission function validates an independent-review receipt, derives SCREENED records from retained stages, and never accepts a numerical backend.

**Tech Stack:** Python 3.12, dataclasses/enums, canonical SHA-256 JSON contracts, `unittest`, schema-11 checkpoint/lock infrastructure.

**Spec:** `docs/superpowers/specs/2026-08-26-layer2-calculation-admission-separation-design.md`

## Global Constraints

- Do not run a production solver, Julia worker, or M02 campaign.
- Preserve the existing checkpoint and binary64 lock; Layer 1 must remain unchanged.
- Do not modify the canonical calibration receipt bytes or the PR summary.
- The canonical receipt must resolve to `CALCULATE_ONLY`.
- Official mocked proof must report 172 exterior BF40 routes, 40 horizon BF80 routes, 928 locked predecessor evaluations consumed, and zero binary64 evaluations recomputed.

---

### Task 1: Typed calibration execution mode and preflight

**Files:**
- Modify: `src/windows_solver/promoted_control_calibration.py`
- Modify: `src/windows_solver/reviewed_determinant_error_issuance.py`
- Modify: `tests/test_promoted_control_calibration.py`
- Replace behavior in: `tests/test_locked_bf40_determinant_gate_static.py`

**Interfaces:**
- Produces: `PromotedExecutionMode`, `CalibrationAdmissionBoundary`, `PromotedExecutionPreflight`, and `require_locked_bf40_determinant_error_issuance_authority(receipt, *, route)`.
- Consumes: the canonical receipt `admission_boundary` mapping.

- [ ] **Step 1: Write failing mode/preflight tests**

```python
receipt = load_default_calibration_receipt()
self.assertIs(PromotedExecutionMode.CALCULATE_ONLY, receipt.execution_mode)
preflight = require_locked_bf40_determinant_error_issuance_authority(
    receipt, route="EXTERIOR_BF40"
)
self.assertTrue(preflight.calculation_permitted)
self.assertFalse(preflight.admission_permitted)
```

- [ ] **Step 2: Run red tests**

Run: `PYTHONPATH=src python -m unittest -v tests.test_promoted_control_calibration tests.test_locked_bf40_determinant_gate_static`

Expected: FAIL because typed modes/preflight do not exist and the legacy function raises.

- [ ] **Step 3: Implement typed parsing and preflight**

```python
class PromotedExecutionMode(str, Enum):
    CALCULATE_AND_ADMIT = "CALCULATE_AND_ADMIT"
    CALCULATE_ONLY = "CALCULATE_ONLY"
    BLOCK_ALL = "BLOCK_ALL"

@dataclass(frozen=True, slots=True)
class CalibrationAdmissionBoundary:
    calculation: str
    checkpointing: str
    publication: str
    scientific_admission: str
    uncertainty_disks: str

    @property
    def execution_mode(self) -> PromotedExecutionMode:
        calculation_ready = (
            self.calculation == "permitted/v1"
            and self.checkpointing == "permitted/v1"
        )
        admission_ready = (
            self.publication == "permitted/v1"
            and self.scientific_admission == "permitted/v1"
        )
        if calculation_ready and admission_ready:
            return PromotedExecutionMode.CALCULATE_AND_ADMIT
        if calculation_ready:
            return PromotedExecutionMode.CALCULATE_ONLY
        return PromotedExecutionMode.BLOCK_ALL

@dataclass(frozen=True, slots=True)
class PromotedExecutionPreflight:
    mode: PromotedExecutionMode
    route: str
    calculation_permitted: bool
    checkpointing_permitted: bool
    admission_permitted: bool
    publication_permitted: bool
    result_code: str
```

Store the parsed boundary on `PromotedControlCalibrationReceipt`; return a preflight object from the legacy-named function with no raise.

- [ ] **Step 4: Run green tests**

Run the Step 2 command. Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/windows_solver/promoted_control_calibration.py src/windows_solver/reviewed_determinant_error_issuance.py tests/test_promoted_control_calibration.py tests/test_locked_bf40_determinant_gate_static.py
git commit -m "fix(policy): separate promoted calculation from admission"
```

### Task 2: Durable calculated-awaiting-admission Layer-2 state

**Files:**
- Modify: `src/windows_solver/campaign_policy.py`
- Modify: `src/windows_solver/campaign_survey.py`
- Modify: `tests/test_campaign_schema11.py`
- Modify: `tests/test_binary64_layer_lock.py`

**Interfaces:**
- Produces: `SurveyDisposition.CALCULATED_AWAITING_ADMISSION`, `PromotionQueueDisposition.AWAITING_ADMISSION`, top-level `promoted_stage_ledger`, `promoted_background_ledger`, and `promoted_root_ledger`, plus `retain_promoted_calculation(...)` and `complete_promoted_admission(...)`.
- Preserves: `promotion_source_fingerprint_sha256()` and `project_binary64_layer()` source material.

- [ ] **Step 1: Write failing state-transition tests**

```python
retained = retain_promoted_stage(
    checkpoint,
    queue_ordinal=0,
    promoted_stage=stage,
    execution_mode="CALCULATE_ONLY",
    layer1_guard=guard,
)
self.assertEqual("AWAITING_ADMISSION", retained["promotion_queue"]["entries"][0]["disposition"])
self.assertEqual(before_projection, project_binary64_layer(retained, **projection_args))
```

Add an admission-transition assertion proving the retained stage remains byte-identical while queue/pass state becomes `COMPLETED`. Assert `promoted_pass_exhaustion()` treats `AWAITING_ADMISSION` as numerically exhausted.

- [ ] **Step 2: Run red tests**

Run: `PYTHONPATH=src python -m unittest -v tests.test_campaign_schema11 tests.test_binary64_layer_lock`

Expected: FAIL because the states and transition functions do not exist.

- [ ] **Step 3: Implement additive checkpoint-owned Layer-2 ledgers**

Keep only `retained_promoted_stage_sha256` and disposition state in each queue entry. Authenticate ledger entries by queue ordinal and leaf ID, exclude Layer-2 pointer/state fields from the Layer-1 source fingerprint, and add explicit transitions:

```python
def retain_promoted_calculation(
    checkpoint: Mapping[str, object],
    *,
    queue_ordinal: int,
    promoted_stage: Mapping[str, object],
    execution_mode: str,
    layer1_guard: object | None = None,
) -> dict[str, object]:
    """Authenticate and retain one calculated Layer-2 stage."""

def complete_promoted_admission(
    checkpoint: Mapping[str, object],
    *,
    queue_ordinal: int,
    admission_receipt: Mapping[str, object],
    layer1_guard: object | None = None,
) -> dict[str, object]:
    """Transition one retained stage after independent review."""
```

- [ ] **Step 4: Run green tests**

Run the Step 2 command. Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/windows_solver/campaign_policy.py src/windows_solver/campaign_survey.py tests/test_campaign_schema11.py tests/test_binary64_layer_lock.py
git commit -m "feat(checkpoint): retain review-pending Layer 2 stages"
```

### Task 3: CALCULATE_ONLY route execution and retention

**Files:**
- Modify: `src/windows_solver/campaign_survey.py`
- Modify: `src/windows_solver/campaign_runtime.py`
- Modify: `src/windows_solver/julia_response_backend.py`
- Modify: `tests/test_promoted_survey_scheduler.py`

**Interfaces:**
- Consumes: typed route preflight and locked routes.
- Produces: authenticated `windows-solver.promoted-retained-stage/1` mappings and extended `PromotedSurveyRun` counters.

- [ ] **Step 1: Write failing exterior/horizon retention tests**

Use real scheduler/checkpoint contracts with fake numerical runners. Assert exterior starts at BF40 and escalates to BF80 only for allowlisted numerical insufficiency, horizon receives BF80 only, both are persisted as `CALCULATED_AWAITING_ADMISSION` / `AWAITING_ADMISSION`, no evidence ledger entry exists, and terminal publication is not called.

- [ ] **Step 2: Run red test**

Run: `PYTHONPATH=src python -m unittest -v tests.test_promoted_survey_scheduler`

Expected: FAIL because execution mode is not wired and no retained-stage outcome exists.

- [ ] **Step 3: Implement route-specific calculation**

Remove both kill-switch calls. Pass per-route preflight into `run_promoted_survey`; for `CALCULATE_ONLY`, execute the locked starting tier, permit only allowlisted BF40-to-BF80 numerical escalation, build authenticated stage/background/root ledger entries containing raw/combined batches, screenings, receipts, disagreement evidence, counters, and source bindings, then atomically commit their digest pointer and `AWAITING_ADMISSION` state before advancing. Do not call `record_evidence` or `terminal_record_committed` for calculated-but-unadmitted outcomes.

- [ ] **Step 4: Implement same-tier promoted background reuse**

Add an exact promoted background key and split promoted exterior acquisition into five reusable background roles plus four mechanism roles. Reconstruct a full nine-role logical batch from an authenticated same-tier retained background; never reuse across precision/control keys.

- [ ] **Step 5: Run green test and focused regressions**

Run: `PYTHONPATH=src python -m unittest -v tests.test_promoted_survey_scheduler tests.test_pr66_terminal_cache_wiring tests.test_binary64_layer_lock`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/windows_solver/campaign_survey.py src/windows_solver/campaign_runtime.py src/windows_solver/julia_response_backend.py tests/test_promoted_survey_scheduler.py
git commit -m "feat(promoted): calculate and retain unadmitted routes"
```

### Task 4: Zero-numerics independent-review admission

**Files:**
- Create: `src/windows_solver/promoted_admission.py`
- Modify: `src/windows_solver/campaign_runtime.py`
- Modify: `src/windows_solver/cli.py`
- Create: `tests/test_promoted_admission.py`
- Modify: `tests/test_public_surface.py`

**Interfaces:**
- Produces: `IndependentReviewReceipt`, `admit_retained_promoted_work(plan, selection, checkpoint, lock, review_receipt)`, `run_native_promoted_admission(plan, selection, recovery_selection, checkpoint, *, checkpoint_path, binary64_lock_path, review_receipt_path, solved_leaf_store=None)`, and CLI command `campaign-admit-promoted`.
- Consumes: checkpoint-retained stages, the binary64 lock, and a canonical independent-review receipt.

- [ ] **Step 1: Write failing admission tests**

Assert an authorized per-route receipt upgrades retained work to SCREENED, transitions queue/pass state to `COMPLETED`, and publishes the terminal record. Pass evaluator functions that raise if called to prove admission performs no numerical work. Assert malformed, foreign-lock, or unauthorized receipts fail before checkpoint mutation.

- [ ] **Step 2: Run red tests**

Run: `PYTHONPATH=src python -m unittest -v tests.test_promoted_admission tests.test_public_surface`

Expected: FAIL because the admission module/command do not exist.

- [ ] **Step 3: Implement receipt authentication and pure admission**

```python
@dataclass(frozen=True, slots=True)
class IndependentReviewReceipt:
    calibration_receipt_sha256: str
    binary64_lock_receipt_sha256: str
    authority: Mapping[str, object]
    route_decisions: Sequence[Mapping[str, object]]
    receipt_sha256: str

def admit_retained_promoted_work(
    plan: object,
    selection: RecoverySelection,
    checkpoint: Mapping[str, object],
    lock: Mapping[str, object],
    review_receipt: IndependentReviewReceipt,
) -> PromotedAdmissionResult:
    """Admit only digest-bound retained stages without a numerical backend."""
```

Exterior admission issues reviewed determinant-error receipts from retained current-run terms and reduces retained samples. Horizon admission builds from the retained BF80 stage. Persist the checkpoint under the existing Layer-1 guard before publishing records.

- [ ] **Step 4: Wire CLI and run green tests**

Run the Step 2 command. Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/windows_solver/promoted_admission.py src/windows_solver/campaign_runtime.py src/windows_solver/cli.py tests/test_promoted_admission.py tests/test_public_surface.py
git commit -m "feat(admission): screen retained promoted evidence without numerics"
```

### Task 5: Official mocked 212-route production shape

**Files:**
- Create: `tests/test_pr73_calculate_only_production_shape.py`
- Modify: implementation files only if this behavioral proof exposes a missing contract.

**Interfaces:**
- Consumes: public promoted calculate-only scheduler/result contracts.
- Proves: exact official shape and Layer-1 immutability.

- [ ] **Step 1: Write the official mocked fixture test**

Build 212 locked typed routes with literal expected totals: 172 `EXTERIOR_BF40`, 40 `HORIZON_BF80`, 48 full nine-sample and 124 reused four-sample binary64 predecessors, giving `48*9 + 124*4 == 928`. Fake only the external numerical boundary and assert scheduler/checkpoint behavior.

- [ ] **Step 2: Run red test**

Run: `PYTHONPATH=src python -m unittest -v tests.test_pr73_calculate_only_production_shape`

Expected: FAIL until all official counters and retention contracts are wired.

- [ ] **Step 3: Complete the minimal missing orchestration**

Expose literal result counters `exterior_bf40_executed_count`, `horizon_bf80_executed_count`, `binary64_predecessor_evaluation_count`, `binary64_recomputed_evaluation_count`, and `review_pending_count`; derive predecessor count from the authenticated lock, never from a new evaluator.

- [ ] **Step 4: Run green test**

Run the Step 2 command. Expected: PASS with 172/40/928/0 and zero SCREENED entries.

- [ ] **Step 5: Commit**

```bash
git add tests/test_pr73_calculate_only_production_shape.py src/windows_solver
git commit -m "test(pr73): prove official calculate-only production shape"
```

### Task 6: Regression proof and PR delivery

**Files:**
- Review all task-related diffs.
- Do not edit the PR body.

**Interfaces:**
- Produces: verified commits pushed append-only to PR73.

- [ ] **Step 1: Run static and compile checks**

Run: `PYTHONPATH=src python -m compileall -q src tests`

- [ ] **Step 2: Run the full Python test suite without Julia/M02 execution**

Run the repository's Python-only CI command after confirming it does not launch Julia; otherwise run the complete affected module set plus CLI/public-surface tests.

- [ ] **Step 3: Review diff and Layer-1 projection invariants**

Run: `git diff --check` and `git status --short`; inspect every changed production file and verify no canonical receipt, checkpoint fixture, Julia source, or PR summary changed.

- [ ] **Step 4: Run change review and verification-before-completion skills**

Resolve every blocking finding and rerun affected checks.

- [ ] **Step 5: Push append-only and monitor PR73 CI**

Create a normal descendant commit from the remote PR head, update the existing PR branch without force, leave the user-authored PR summary unchanged, and report exact CI results.
