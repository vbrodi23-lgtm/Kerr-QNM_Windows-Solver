# M02 Survey, Certification, and Validation Profiles Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Finish the provisional M02 atlas through a minimal bounded-response survey while retaining the existing heavy machinery as explicit certification and validation profiles.

**Architecture:** Add typed execution-policy and evidence-ledger boundaries to the existing campaign runner, then route the current numerical components through that policy. Survey consumes shared root seals and exact-key Dω evidence through a root-forbidden fixed-response interface; certification and validation append stronger evidence without replacing the retained centre.

**Tech Stack:** Python 3.12 standard library, dataclasses/enums, canonical JSON checkpoints, unittest, PowerShell command wrapper (edited and statically tested only).

**Spec:** `docs/superpowers/specs/2026-08-22-m02-survey-certify-validate-design.md`

## Global Constraints

- Do not change Kerr/GSN equations, branch rules, tolerances, derivative formulas, or uncertainty formulas.
- Do not add K2 modes 332 or 442 in PR #63.
- Do not delete checkpoints, caches, solved-leaf receipts, partial journals, or completed evidence.
- Do not execute the production solver, Julia numerical worker, Kerr/GSN mathematical campaign, or PowerShell numerical campaign.
- Run software, static, contract, migration, and mocked orchestration tests only.
- Exact reuse conditions fail closed; no approximate key matching is permitted.
- `survey` is the `m02.ps1` default, but release admission rejects `SCREENED`-only evidence.

---

### Task 1: Typed profile and evidence contracts

**Files:**
- Create: `src/windows_solver/campaign_policy.py`
- Create: `tests/test_campaign_execution_profiles.py`
- Modify: `src/windows_solver/__init__.py`

**Interfaces:**
- Produces: `ExecutionProfile`, `EvidenceLevel`, `CampaignExecutionPolicy.for_profile(profile)`, `CampaignEvidenceRecord`, and `stronger_evidence_level(left, right)`.
- Consumes: canonical JSON hashing conventions already used by `response_batches.py`.

- [ ] **Step 1: Write the failing enum, policy-matrix, and monotonic-evidence tests**

```python
def test_survey_policy_forbids_heavy_operations(self):
    policy = CampaignExecutionPolicy.for_profile(ExecutionProfile.SURVEY)
    self.assertFalse(policy.allow_truncation_root_solve)
    self.assertFalse(policy.allow_resolution_root_solve)
    self.assertFalse(policy.allow_seed_path_root_solve)
    self.assertFalse(policy.allow_expanded_derivative_ladder)
    self.assertFalse(policy.allow_full_complex_root_ladder)
    self.assertFalse(policy.allow_automatic_max_precision)

def test_evidence_merge_never_downgrades(self):
    self.assertIs(
        stronger_evidence_level(EvidenceLevel.VALIDATED, EvidenceLevel.SCREENED),
        EvidenceLevel.VALIDATED,
    )
```

- [ ] **Step 2: Run the focused test and observe RED**

Run: `PYTHONPATH=src python -m unittest tests.test_campaign_execution_profiles -v`

Expected: import failure for `windows_solver.campaign_policy`.

- [ ] **Step 3: Implement the typed profile, policy matrix, and additive evidence record**

```python
class ExecutionProfile(str, Enum):
    SURVEY = "survey"
    CERTIFY = "certify"
    VALIDATE = "validate"

class EvidenceLevel(str, Enum):
    SCREENED = "SCREENED"
    CERTIFIED = "CERTIFIED"
    VALIDATED = "VALIDATED"
```

Validate every persisted field, require canonical round trips, and make evidence upgrades append receipt digests while retaining the original central-stage digest.

- [ ] **Step 4: Run focused tests GREEN**

Run: `PYTHONPATH=src python -m unittest tests.test_campaign_execution_profiles -v`

Expected: all profile/evidence contract tests pass.

- [ ] **Step 5: Commit the contract slice**

```bash
git add src/windows_solver/campaign_policy.py src/windows_solver/__init__.py tests/test_campaign_execution_profiles.py
git commit -m "feat(m02): add campaign evidence profiles"
```

### Task 2: Exact shared-root and Dω reuse boundaries

**Files:**
- Modify: `src/windows_solver/campaign_policy.py`
- Modify: `src/windows_solver/response_engine.py`
- Create: `tests/test_survey_background_reuse.py`

**Interfaces:**
- Consumes: `PromotedRootSeal`, `regularised_gsn_mechanism_contract`, existing fixed-root derivative and response-disk functions.
- Produces: `BackgroundRootKey.from_job(...)`, `SharedBackgroundRootSeal`, `FixedRootDomegaKey`, `SurveyEvidenceCache`, and `run_exterior_survey_from_seal(...)`.

- [ ] **Step 1: Write failing zero-root-call and exact-key reuse tests**

```python
def test_exterior_survey_has_no_root_reader_after_seal(self):
    backend = FixedRootOnlyBackend()
    result = run_exterior_survey_from_seal(job, backend, seal, cache)
    self.assertTrue(result.response_disk_bounded)
    self.assertEqual(backend.read_root_calls, 0)

def test_domega_reuse_requires_exact_identity(self):
    cache.store(key, evidence)
    self.assertIs(cache.lookup(key), evidence)
    self.assertIsNone(cache.lookup(replace(key, determinant_normalisation="other")))
    self.assertIsNone(cache.lookup(replace(key, controls_sha256="0" * 64)))
```

- [ ] **Step 2: Run focused tests RED**

Run: `PYTHONPATH=src python -m unittest tests.test_survey_background_reuse -v`

Expected: missing shared-root/Dω cache interfaces.

- [ ] **Step 3: Implement root-forbidden survey response execution**

The executor accepts only fixed-root sampling methods; it has no `read_root` parameter. Reuse the existing h/h÷2 fixed-root derivative and disk construction. Construct cache keys from exact determinant family, determinant normalisation, branch, root, controls, precision, backend, and derivative-step identities. Derive each mechanism-bound seal from shared root evidence without a new root read.

- [ ] **Step 4: Run focused tests GREEN**

Run: `PYTHONPATH=src python -m unittest tests.test_survey_background_reuse -v`

Expected: zero post-seal root calls; exact matches reuse Dω; every mismatch misses.

- [ ] **Step 5: Commit the reuse boundary**

```bash
git add src/windows_solver/campaign_policy.py src/windows_solver/response_engine.py tests/test_survey_background_reuse.py
git commit -m "feat(m02): share sealed survey background evidence"
```

### Task 3: Survey orchestration and continue-on-failure

**Files:**
- Modify: `src/windows_solver/response_batches.py`
- Modify: `src/windows_solver/campaign_policy.py`
- Create: `tests/test_campaign_survey_orchestration.py`
- Modify: `tests/test_mechanism_scoped_policy.py`

**Interfaces:**
- Consumes: `CampaignExecutionPolicy`, `SurveyEvidenceCache`, existing `StageOutcome`, `CampaignLeafRecord`, component validators, and lowest-tier precision capabilities.
- Produces: `run_campaign_selection(..., execution_profile=ExecutionProfile.SURVEY)`, backend `execute_survey_stage(...)`, and contained failed/unresolved survey records.

- [ ] **Step 1: Write failing mocked orchestration tests for forbidden work, lowest-tier promotion, all mechanisms, and campaign advancement**

```python
def test_survey_never_dispatches_heavy_operations(self):
    backend = RecordingPolicyBackend()
    run_campaign_selection(plan, selection, backend, checkpoint, resume=False,
                           execution_profile=ExecutionProfile.SURVEY)
    self.assertNotIn("TRUNCATION", backend.operations)
    self.assertNotIn("RESOLUTION", backend.operations)
    self.assertNotIn("SEED_PATH", backend.operations)
    self.assertNotIn("2h", backend.operations)
    self.assertNotIn("ih", backend.operations)
    self.assertNotIn("FULL_COMPLEX_ROOT_LADDER", backend.operations)

def test_failed_survey_leaf_is_recorded_and_next_leaf_runs(self):
    self.assertEqual(summary.records[0].state, "FAILED")
    self.assertEqual(summary.records[1].state, "PRODUCED")
```

- [ ] **Step 2: Run focused tests RED**

Run: `PYTHONPATH=src python -m unittest tests.test_campaign_survey_orchestration tests.test_mechanism_scoped_policy -v`

Expected: campaign runner lacks profile-aware survey dispatch and contained `FAILED` state.

- [ ] **Step 3: Implement the survey dispatch path**

Pass one policy into the existing runner. Survey calls `execute_survey_stage`, stops at the first finite bounded disk, promotes from 64 to the lowest available adequate tier only after a typed unresolved result, never automatically selects 120, records contained failures, checkpoints, and advances. Derive mechanism and mode ordering from `plan.leaves` rather than `_EXECUTION_MODE_ORDER`.

- [ ] **Step 4: Run focused tests GREEN**

Run: `PYTHONPATH=src python -m unittest tests.test_campaign_survey_orchestration tests.test_mechanism_scoped_policy -v`

Expected: all exterior mechanisms follow one policy, failures do not halt, and forbidden operations are absent.

- [ ] **Step 5: Commit survey orchestration**

```bash
git add src/windows_solver/response_batches.py src/windows_solver/campaign_policy.py tests/test_campaign_survey_orchestration.py tests/test_mechanism_scoped_policy.py
git commit -m "feat(m02): survey the atlas before certification"
```

### Task 4: Additive checkpoint migration and resume

**Files:**
- Modify: `src/windows_solver/response_batches.py`
- Modify: `src/windows_solver/campaign_checkpoint_migration.py`
- Modify: `src/windows_solver/solved_leaf_cache.py`
- Create: `tests/test_campaign_evidence_migration.py`
- Modify: `tests/test_campaign_checkpoint_migration.py`

**Interfaces:**
- Consumes: schema-9 checkpoint and solved-receipt validators, `CampaignEvidenceRecord`.
- Produces: schema-10 checkpoint evidence ledger, computation-free schema-9 migration, monotone cache import/reuse, first-missing-survey resume.

- [ ] **Step 1: Write failing migration tests with a backend that raises on every numerical method**

```python
def test_schema9_completed_records_migrate_without_numerical_calls(self):
    summary = run_campaign_selection(plan, selection, NoNumericsBackend(), path,
                                     resume=True,
                                     execution_profile=ExecutionProfile.SURVEY)
    self.assertEqual(summary.executed_stage_count, 0)
    self.assertTrue(all(item.level >= EvidenceLevel.CERTIFIED
                        for item in summary.evidence_records))

def test_stronger_evidence_is_not_downgraded(self):
    self.assertEqual(reloaded.evidence_level, EvidenceLevel.VALIDATED)
```

- [ ] **Step 2: Run migration tests RED**

Run: `PYTHONPATH=src python -m unittest tests.test_campaign_evidence_migration tests.test_campaign_checkpoint_migration -v`

Expected: schema/evidence ledger is absent.

- [ ] **Step 3: Implement schema-10 additive migration**

Keep numerical records, stages, attempts, caches, and journals intact. Add an authenticated evidence ledger/digest and profile field. Infer `CERTIFIED` conservatively for historical completed records and `VALIDATED` only from explicit stored full-ladder evidence. Rewrite only the normal atomic checkpoint envelope; do not invoke the backend. Merge cache evidence with max-level semantics.

- [ ] **Step 4: Run migration tests GREEN**

Run: `PYTHONPATH=src python -m unittest tests.test_campaign_evidence_migration tests.test_campaign_checkpoint_migration tests.test_solved_leaf_cache -v`

Expected: no numerical calls and no downgrade/recomputation.

- [ ] **Step 5: Commit persistence migration**

```bash
git add src/windows_solver/response_batches.py src/windows_solver/campaign_checkpoint_migration.py src/windows_solver/solved_leaf_cache.py tests/test_campaign_evidence_migration.py tests/test_campaign_checkpoint_migration.py
git commit -m "feat(m02): migrate additive campaign evidence"
```

### Task 5: Explicit certification and validation routing

**Files:**
- Modify: `src/windows_solver/response_batches.py`
- Modify: `src/windows_solver/response_engine.py`
- Create: `tests/test_campaign_certify_validate_profiles.py`
- Modify: `tests/test_promoted_exterior_campaign_flow.py`

**Interfaces:**
- Consumes: existing heavy local uncertainty runner, `run_promoted_full_ladder_validation`, retained screened centre/disk, evidence ledger.
- Produces: explicit `certify` and `validate` upgrades plus `CENTRAL_RESPONSE_DISCREPANCY_REVIEW_REQUIRED` evidence.

- [ ] **Step 1: Write failing routing and discrepancy tests**

```python
def test_certify_dispatches_existing_heavy_local_path(self):
    run_profile(ExecutionProfile.CERTIFY, screened_checkpoint, backend)
    self.assertEqual(backend.operations, ["HEAVY_LOCAL_UNCERTAINTY"])

def test_validate_dispatches_existing_full_ladder_path(self):
    run_profile(ExecutionProfile.VALIDATE, certified_checkpoint, backend)
    self.assertIn("FULL_COMPLEX_ROOT_LADDER", backend.operations)

def test_certification_cannot_silently_replace_screened_centre(self):
    self.assertEqual(record.evidence_level, EvidenceLevel.SCREENED)
    self.assertEqual(record.discrepancy_code,
                     "CENTRAL_RESPONSE_DISCREPANCY_REVIEW_REQUIRED")
```

- [ ] **Step 2: Run focused tests RED**

Run: `PYTHONPATH=src python -m unittest tests.test_campaign_certify_validate_profiles tests.test_promoted_exterior_campaign_flow -v`

Expected: profile upgrade routing is absent.

- [ ] **Step 3: Route existing heavy machinery behind explicit profiles**

Certification requires a retained screened record and appends local evidence. Validation requires certified evidence and passes an explicit validation reason into the existing full-ladder boundary. Compare any new centre against the retained screened disk; persist a discrepancy and retain the old centre if outside.

- [ ] **Step 4: Run focused tests GREEN**

Run: `PYTHONPATH=src python -m unittest tests.test_campaign_certify_validate_profiles tests.test_promoted_exterior_campaign_flow -v`

Expected: survey never reaches heavy paths, certify reaches local uncertainty, validate reaches full ladders, and discrepancies fail closed.

- [ ] **Step 5: Commit evidence upgrades**

```bash
git add src/windows_solver/response_batches.py src/windows_solver/response_engine.py tests/test_campaign_certify_validate_profiles.py tests/test_promoted_exterior_campaign_flow.py
git commit -m "feat(m02): target certification and validation"
```

### Task 6: Whole-atlas triage and certification queue

**Files:**
- Create: `src/windows_solver/campaign_triage.py`
- Create: `tests/test_campaign_triage.py`
- Modify: `src/windows_solver/cli.py`

**Interfaces:**
- Consumes: `CampaignPlan`, numerical records, evidence ledger, and existing projective reduction rows.
- Produces: `build_campaign_triage_report(plan, records, evidence_records, projective_rows=())` and `campaign-triage` CLI export.

- [ ] **Step 1: Write failing deterministic ranking and dynamic sentinel tests**

```python
def test_triage_emits_explicit_certification_queue(self):
    report = build_campaign_triage_report(plan, records, evidence)
    self.assertEqual(report.queue[0].reasons[0], "UNRESOLVED")
    self.assertTrue(report.queue)

def test_triage_covers_every_dynamic_mechanism_and_mode_family(self):
    covered = {(item.mechanism_id, item.mode_family) for item in report.sentinels}
    self.assertEqual(covered, expected_pairs_derived_from_plan)
```

- [ ] **Step 2: Run triage tests RED**

Run: `PYTHONPATH=src python -m unittest tests.test_campaign_triage -v`

Expected: triage module and command are absent.

- [ ] **Step 3: Implement ranked triage projection**

Rank unresolved/failure, zero-containing or near-zero disks, relative disk size, precision and derivative disagreements, branch risk, smallest projective angles, controlling rows, then deterministic sentinels. Derive mode families and mechanisms from the plan. Emit exact reason codes and an ordered recommended certification queue.

- [ ] **Step 4: Run triage tests GREEN**

Run: `PYTHONPATH=src python -m unittest tests.test_campaign_triage tests.test_cli -v`

Expected: deterministic report and explicit queue pass without numerical execution.

- [ ] **Step 5: Commit triage**

```bash
git add src/windows_solver/campaign_triage.py src/windows_solver/cli.py tests/test_campaign_triage.py
git commit -m "feat(m02): rank atlas certification work"
```

### Task 7: Dashboard, CSV, admission, and PowerShell defaults

**Files:**
- Modify: `src/windows_solver/campaign_reports.py`
- Modify: `src/windows_solver/progress_output.py`
- Modify: `src/windows_solver/linear_response_admission.py`
- Modify: `src/windows_solver/response_reduction.py`
- Modify: `src/windows_solver/cli.py`
- Modify: `m02.ps1`
- Create: `tests/test_campaign_evidence_reporting.py`
- Modify: `tests/test_campaign_reports.py`
- Modify: `tests/test_linear_response_admission.py`
- Modify: `tests/test_cli.py`

**Interfaces:**
- Consumes: evidence ledger and execution profile from campaign summaries/checkpoints.
- Produces: separate evidence/terminal counts, CSV columns, atlas-vs-certification dashboard progress, screened atlas visibility, and certified-only release admission.

- [ ] **Step 1: Write failing report/admission/default-profile tests**

```python
def test_csv_and_dashboard_separate_evidence_counts(self):
    self.assertIn("evidence_level", CSV_COLUMNS)
    self.assertIn("execution_profile", CSV_COLUMNS)
    self.assertEqual(model.evidence_counts["SCREENED"], 2)
    self.assertEqual(model.evidence_counts["CERTIFIED"], 1)
    self.assertEqual(model.evidence_counts["VALIDATED"], 1)

def test_screened_is_visible_to_atlas_but_rejected_by_release(self):
    self.assertIn(screened.leaf_id, triage_ids)
    with self.assertRaisesRegex(ValueError, "SCREENED"):
        admit_screened_component(screened)
```

- [ ] **Step 2: Run focused tests RED**

Run: `PYTHONPATH=src python -m unittest tests.test_campaign_evidence_reporting tests.test_campaign_reports tests.test_linear_response_admission tests.test_cli -v`

Expected: fields/counts/profile CLI arguments are absent.

- [ ] **Step 3: Implement reporting, admission, CLI, and static PowerShell routing**

Add `--profile {survey,certify,validate}` to run/resume/validate commands with survey default; pass it to the runner; make `m02.ps1` explicitly pass survey. Add evidence columns/counts and dashboard lanes. Keep screened records in atlas/triage projections but reject them from release/publication admission with a typed message.

- [ ] **Step 4: Run focused tests GREEN**

Run: `PYTHONPATH=src python -m unittest tests.test_campaign_evidence_reporting tests.test_campaign_reports tests.test_linear_response_admission tests.test_cli -v`

Expected: separate counts/columns and admission behavior pass; no PowerShell execution occurs.

- [ ] **Step 5: Commit reporting and command surface**

```bash
git add src/windows_solver/campaign_reports.py src/windows_solver/progress_output.py src/windows_solver/linear_response_admission.py src/windows_solver/response_reduction.py src/windows_solver/cli.py m02.ps1 tests/test_campaign_evidence_reporting.py tests/test_campaign_reports.py tests/test_linear_response_admission.py tests/test_cli.py
git commit -m "feat(m02): report atlas evidence separately"
```

### Task 8: Regression closure and delivery evidence

**Files:**
- Modify: `.tasks/IN_PROGRESS.md`
- Modify: `.tasks/WORK_LOG.md`
- Modify: `docs/superpowers/plans/2026-08-22-m02-survey-certify-validate.md`

**Interfaces:**
- Consumes: all prior slices.
- Produces: complete safe verification record and PR-ready source tree.

- [ ] **Step 1: Run the complete focused PR #63 regression matrix**

Run:

```bash
PYTHONPATH=src python -m unittest \
  tests.test_campaign_execution_profiles \
  tests.test_survey_background_reuse \
  tests.test_campaign_survey_orchestration \
  tests.test_campaign_evidence_migration \
  tests.test_campaign_certify_validate_profiles \
  tests.test_campaign_triage \
  tests.test_campaign_evidence_reporting \
  tests.test_mechanism_scoped_policy \
  tests.test_campaign_checkpoint_migration \
  tests.test_promoted_exterior_campaign_flow \
  tests.test_campaign_reports \
  tests.test_linear_response_admission \
  tests.test_cli -v
```

Expected: all tests pass; no numerical worker or PowerShell subprocess is launched.

- [ ] **Step 2: Run the full permitted Python suite**

Run: `PYTHONPATH=src python -m unittest discover -s tests -p 'test_*.py'`

Expected: all safe tests pass, with only existing intentional skips.

- [ ] **Step 3: Run static and board checks**

Run:

```bash
python -m compileall -q src tests
python .tasks/validate_board.py
git diff --check
git status --short
```

Expected: all commands exit 0; status contains only PR #63 files.

- [ ] **Step 4: Update TaskPlanner evidence without closing TASK-079**

Append a dated Task 79 work-log entry stating exact test counts, that no Julia/Kerr/PowerShell production execution occurred, and that native operator logs and human mathematics review remain the closure gate.

- [ ] **Step 5: Commit verification metadata**

```bash
git add .tasks/IN_PROGRESS.md .tasks/WORK_LOG.md docs/superpowers/plans/2026-08-22-m02-survey-certify-validate.md
git commit -m "docs(tasks): record PR 63 verification"
```

- [ ] **Step 6: Review, push, and open PR #63 without merging**

Run the change-review gate over `origin/main...HEAD`, push `feat/m02-atlas-evidence-profiles`, and open a draft PR titled `Separate M02 atlas production from certification`. Do not merge or execute the production campaign.
