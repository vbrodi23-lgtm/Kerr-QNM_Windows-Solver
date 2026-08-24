# PR66 Completion Implementation Plan

> **Status:** This is a non-normative historical planning record. The sole
> authoritative PR66 source is `PR66_GOVERNING_COMPLETION_CONTRACT.md`.
> Where this record differs from that contract, do not execute this record.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Repair every mandatory PR66 software boundary, produce complete permitted software/static evidence on one tested code head, and stop before operator-only native and mathematical canaries.

**Architecture:** Keep schema-11 numerical records immutable while adding authenticated evidence, recovery, reuse, and acceptance ledgers around them. Scientific survey paths fail closed when approved determinant-error evidence is unavailable; reusable roots and canonical Dω evidence cross leaves only through exact identities and durable receipts; certification and independent validation remain separate operations.

**Tech Stack:** Python 3.12 standard library, immutable dataclasses/enums, canonical JSON/SHA-256 artifacts, unittest, PowerShell 5.1 launcher text edited and statically tested only.

**Spec:** The committed `PR66_GOVERNING_COMPLETION_CONTRACT.md`, including authoritative completion decisions 1–7.

## Authoritative course correction — 2026-08-24

This plan has one architecture.  The PR66 Governing Completion Contract, the
seven resolved decisions, and the 2026-08-24 course correction are its
authoritative inputs.  Where an older task below conflicts with that course
correction, the course correction wins; do not create a parallel scheduler,
second reuse implementation, or synthetic incident oracle.

Execute the remaining work in this dependency order:

1. R1 historical scientific-state honesty (complete): authenticate the real
   schema-9 fixture, preserve source bytes, import only uniquely reconstructable
   current identities, record `legacy-compatibility/v1` reasons otherwise, and
   report the absent PR63 oracle as `NOT_SUPPLIED` / Canary X9 `NOT_SUPPLIED`.
2. R2 universal terminal-cache discovery; R3–R5 one shared authenticated
   root-seal provider, RootReadoutStore production wiring, and same-pass seal
   publication; then stop-gate proof that terminal/readout hits construct no
   numerical backend and N compatible roots require at most one permitted solve.
3. R6 cold-machine Julia-free binary64 boundary; R7–R8 removal of unapproved
   determinant-error models; R9–R11 exact promotion/repetition/failure routing;
   R12–R14 durable exact-key Dω evidence and production reuse wiring.
4. R15–R18 authenticated evidence strengthening, release admission,
   certification, and comparator receipts which remain incapable of awarding
   `VALIDATED` without a human mathematical approval.
5. R19–R25 projective triage, pass completion, projections, transactional
   cutover, public CLI/docs parity, and bounded provenance/active-authority
   repair.

Every discovery, recovery, and reuse boundary is cardinality-agnostic.  It
must distinguish `EMPTY`, ordinary `MISS`, `HIT`, trusted `CORRUPT`, and
`CONFLICT` where that boundary can observe a conflict.  Empty and ordinary
miss are normal outcomes.  Each lookup reports exact discovered, compatible,
reused, and rejected counts; it authenticates and reuses only the compatible
subset, and computes only the remainder.  Tests cover empty, one exact match,
nonmatching content, mixed content, and trusted corruption for each important
boundary, with N = 0, 1, 7, 20, 42, 212, and arbitrary N where applicable.

## Global Constraints

- Do not execute the production Kerr/GSN solver, Julia numerical worker, M02 PowerShell campaign, or mathematical acceptance canaries.
- Do not invent numerical tolerances, ULP admission thresholds, or determinant-error models.
- `predicted_reliable_digits`, ULPs, and stencil disagreement remain diagnostic only.
- Binary64 survey launches zero Julia workers and performs no inline promotion.
- Survey precision stops at BF80; BF120 is forbidden in survey.
- Root-seal reuse is permitted across exact-compatible selected leaves; originating leaf and mechanism remain provenance unless they genuinely determine the root solve.
- Dω reuse additionally requires the exact reuse key and a durable exact-key `background-equivalence/v1` receipt.
- First use without a receipt performs the ordinary nine samples and seals reusable evidence from that work; later exact-key use performs four mechanism samples.
- Background equivalence is an exact structural c = 0 construction identity, never a discrepancy tolerance.
- Store actual 40-character Git OIDs as `tested_code_head_git_oid`, `main_base_git_oid`, and `receipt_commit_git_oid`.
- Acceptance finalisation is one metadata-only commit Y whose parent is tested code head X; any solver-affecting change requires new canaries.
- The committed acceptance receipt always keeps `landing_approval_status` equal to `PENDING`; operator landing approval is external GitHub review/comment state.
- PR66 remains draft. Do not mark ready, enable auto-merge, request merge, or merge.
- Preserve source checkpoints, caches, stores, journals, and Git history; recovery performs zero numerical work and writes only a new destination.
- Use Unicode mathematical notation in prose; do not introduce LaTeX.

---

### Task 1: Freeze all PR66 defects with production-boundary regressions

**Files:**
- Create: `tests/test_pr66_scientific_boundaries.py`
- Create: `tests/test_pr66_recovery_reuse.py`
- Create: `tests/test_pr66_operations_governance.py`
- Restore fixture: `tests/fixtures/m02_schema9_production_checkpoint.json.xz`
- Modify: `tests/test_public_surface.py`

**Interfaces:**
- Consumes current public adapters such as `_campaign_reduce`, `run_native_binary64_pass`, `recover_campaign`, `_horizon_outcome`, `write_schema11_triage`, and `schema11_dashboard_snapshot`.
- Produces the named PR66-T01 through PR66-T16 red signals without implementing production fixes.

- [ ] **Step 1: Add behavior-first tests for the scientific gates**

```python
def test_binary64_not_claimed_certificate_cannot_produce():
    outcome = screen_binary64_fixed_root_batch(smooth_nine_sample_batch())
    assert outcome.disposition is Binary64SurveyDisposition.PROMOTION_PENDING_RESPONSE
    assert outcome.response_disk is None
    assert outcome.reason_code == "DETERMINANT_ERROR_EVIDENCE_UNAVAILABLE"
```

- [ ] **Step 2: Add production-adapter recovery, reuse, failure, reporting, and operations tests**

Tests must prove real schema-9 fixture loading, oracle mismatch classes, exact root-readout reuse, nine-then-four sample sequencing, corrupt trusted evidence failure, typed horizon routing, projective-before-triage, evidence dashboard counts, NEW/RECOVER distinction, resolved PowerShell paths, migration diagnostics, and acceptance-receipt rejection.

- [ ] **Step 3: Run the PR66 regression files and capture meaningful RED**

Run: `PYTHONPATH=src python -m unittest tests.test_pr66_scientific_boundaries tests.test_pr66_recovery_reuse tests.test_pr66_operations_governance -v`

Expected: failures correspond one-for-one to missing PR66 behavior; setup/import failures are corrected until assertions reach production boundaries.

- [ ] **Step 4: Commit the red contract tests**

```bash
git add tests/test_pr66_scientific_boundaries.py tests/test_pr66_recovery_reuse.py tests/test_pr66_operations_governance.py tests/fixtures/m02_schema9_production_checkpoint.json.xz tests/test_public_surface.py
git commit -m "test(pr66): freeze completion contract defects"
```

### Task 2: Restore release admission and remove unapproved survey bounds

**Files:**
- Modify: `src/windows_solver/cli.py`
- Modify: `src/windows_solver/campaign_evidence.py`
- Modify: `src/windows_solver/response_engine.py`
- Modify: `src/windows_solver/campaign_runtime.py`
- Modify: `src/windows_solver/campaign_survey.py`
- Test: `tests/test_pr66_scientific_boundaries.py`
- Test: `tests/test_campaign_evidence_passes.py`
- Test: `tests/test_binary64_fixed_root_survey.py`
- Test: `tests/test_promoted_survey_scheduler.py`

**Interfaces:**
- Produces `DETERMINANT_ERROR_EVIDENCE_UNAVAILABLE` as the sole missing-error-evidence survey reason and maps it to response promotion.
- Produces a release reduction boundary that authenticates every selected record/stage against schema-11 `CERTIFIED`-or-stronger evidence before reducer construction.

- [ ] **Step 1: Run focused release and survey tests RED**

Run: `PYTHONPATH=src python -m unittest tests.test_pr66_scientific_boundaries -v`

- [ ] **Step 2: Gate release reduction before `reduce_projective_rows()`**

Build exact requirements from selected component leaf IDs, call `require_release_evidence(checkpoint, requirements)`, and reject absent, detached, or SCREENED ledger entries before any reduction object is constructed.

- [ ] **Step 3: Make binary64 screening diagnostic-only without an approved error receipt**

Return a point estimate only as diagnostic data. Keep all scientific disk fields and root-correction bounds `None`, disposition `PROMOTION_PENDING_RESPONSE`, certificate status `unavailable`, and exact reason `DETERMINANT_ERROR_EVIDENCE_UNAVAILABLE`.

- [ ] **Step 4: Make promoted survey ignore `predicted_reliable_digits` for scientific radii**

BF40 may request BF80 only through the closed response-promotion allowlist. BF80 without approved per-sample determinant-error receipts terminates `UNRESOLVED`; no BF120 survey request is emitted.

- [ ] **Step 5: Run focused tests GREEN and commit**

Run: `PYTHONPATH=src python -m unittest tests.test_pr66_scientific_boundaries tests.test_campaign_evidence_passes tests.test_binary64_fixed_root_survey tests.test_binary64_survey_scheduler tests.test_promoted_survey_scheduler -v`

```bash
git add src/windows_solver/cli.py src/windows_solver/campaign_evidence.py src/windows_solver/response_engine.py src/windows_solver/campaign_runtime.py src/windows_solver/campaign_survey.py tests
git commit -m "fix(pr66): restore fail-closed scientific gates"
```

### Task 3: Implement schema-9 compatibility and a real incident oracle

**Files:**
- Modify: `src/windows_solver/campaign_recovery.py`
- Modify: `src/windows_solver/cli.py`
- Test: `tests/test_pr66_recovery_reuse.py`
- Test: `tests/test_campaign_recovery.py`
- Fixture: `tests/fixtures/m02_schema9_production_checkpoint.json.xz`

**Interfaces:**
- Produces `legacy-compatibility/v1` receipts containing source digest, translated digest, exact reason codes, and preserved scientific values.
- Produces closed oracle statuses `NOT_SUPPLIED`, `INCOMPLETE_FIXTURE`, `PASS`, and `MISMATCH` plus row-level missing/unexpected/state/hash/malformed lists.

- [ ] **Step 1: Run the real-fixture and oracle tests RED**

Run: `PYTHONPATH=src python -m unittest tests.test_pr66_recovery_reuse tests.test_campaign_recovery -v`

- [ ] **Step 2: Add the deterministic legacy adapter**

Authenticate schema-9 envelope and records, reconstruct only unique current identities, preserve terminal scientific mappings byte-for-byte when possible, reject schema 10, and record every incompatible item without guessing.

- [ ] **Step 3: Parse and compare the incident oracle**

Use duplicate-rejecting JSON, bind file/campaign/selection digests, compare authoritative row fields, and seal the comparison receipt. Oracle evidence never authorizes recovery.

- [ ] **Step 4: Prove zero numerics, source immutability, and arbitrary N GREEN**

Run: `PYTHONPATH=src python -m unittest tests.test_pr66_recovery_reuse tests.test_campaign_recovery tests.test_m02_recover_script -v`

- [ ] **Step 5: Commit**

```bash
git add src/windows_solver/campaign_recovery.py src/windows_solver/cli.py tests/test_pr66_recovery_reuse.py tests/test_campaign_recovery.py tests/fixtures/m02_schema9_production_checkpoint.json.xz
git commit -m "feat(pr66): authenticate legacy recovery and oracle"
```

### Task 4: Add exact-compatible root seals and durable Dω reuse

**Files:**
- Create: `src/windows_solver/campaign_reuse.py`
- Modify: `src/windows_solver/root_readout_cache.py`
- Modify: `src/windows_solver/response_engine.py`
- Modify: `src/windows_solver/campaign_policy.py`
- Modify: `src/windows_solver/campaign_recovery.py`
- Modify: `src/windows_solver/campaign_runtime.py`
- Modify: `src/windows_solver/campaign_survey.py`
- Modify: `src/windows_solver/cli.py`
- Test: `tests/test_pr66_recovery_reuse.py`
- Test: `tests/test_root_readout_cache.py`
- Test: `tests/test_exterior_background_reuse.py`
- Test: `tests/test_binary64_survey_scheduler.py`

**Interfaces:**
- Produces `RootSolveIdentity`, `AuthenticatedRootSealProvider`, `DurableBackgroundStore`, and `DurableBackgroundEquivalenceStore`.
- Root provider precedence: checkpoint terminal record → solved-leaf receipt → recovered/authenticated root-readout seal → miss.
- Durable reuse resolver consumes exact `ExteriorBackgroundReuseKey`; trusted malformed receipts raise a typed evidence-corruption error while ordinary absence triggers the nine-sample path.

- [ ] **Step 1: Run root-provider and durable-reuse tests RED**

Run: `PYTHONPATH=src python -m unittest tests.test_pr66_recovery_reuse tests.test_root_readout_cache tests.test_exterior_background_reuse tests.test_binary64_survey_scheduler -v`

- [ ] **Step 2: Separate root-solving identity from leaf provenance**

`RootSolveIdentity` binds every root-solving input but excludes leaf/mechanism IDs unless the request proves they alter the root operation. Authentication retains the originating leaf/request/worker receipt as provenance.

- [ ] **Step 3: Import trusted root readouts into a sealed schema-11 auxiliary ledger**

Recovery authenticates request, runtime, worker response, branch/root/angular/policy identities and writes no destination on conflict or corruption. Runtime consumes the ledger before queuing any root solve.

- [ ] **Step 4: Persist canonical backgrounds and exact structural equivalence receipts**

The receipt binds the complete exact reuse key, canonical background digest, structural zero-coupling proof digest, and mechanism contract proof. It contains no discrepancy tolerance. First nine-sample completion writes both stores atomically; later exact-key leaves execute four samples.

- [ ] **Step 5: Wire production resolver and prove 9→4 sequencing GREEN**

Run: `PYTHONPATH=src python -m unittest tests.test_pr66_recovery_reuse tests.test_root_readout_cache tests.test_exterior_background_reuse tests.test_binary64_survey_scheduler tests.test_campaign_recovery -v`

- [ ] **Step 6: Commit**

```bash
git add src/windows_solver/campaign_reuse.py src/windows_solver/root_readout_cache.py src/windows_solver/response_engine.py src/windows_solver/campaign_policy.py src/windows_solver/campaign_recovery.py src/windows_solver/campaign_runtime.py src/windows_solver/campaign_survey.py src/windows_solver/cli.py tests
git commit -m "feat(pr66): persist exact root and background reuse"
```

### Task 5: Preserve horizon failure meaning through production routing

**Files:**
- Modify: `src/windows_solver/campaign_runtime.py`
- Modify: `src/windows_solver/campaign_failures.py`
- Modify: `src/windows_solver/campaign_survey.py`
- Test: `tests/test_pr66_scientific_boundaries.py`
- Test: `tests/test_campaign_failures.py`

**Interfaces:**
- `_horizon_outcome()` consumes an authenticated typed native failure report and delegates only to `classify_failure()`.
- Unknown/malformed/system exceptions abort; allowlisted arithmetic response insufficiency promotes RESPONSE; exhaustion rejects/unresolves; resource failures defer.

- [ ] **Step 1: Run the table-driven horizon matrix RED**

Run: `PYTHONPATH=src python -m unittest tests.test_pr66_scientific_boundaries tests.test_campaign_failures -v`

- [ ] **Step 2: Remove manufactured determinant failures and preserve diagnostics**

No branch may synthesize `DETERMINANT_UNCERTAINTY_TOO_LARGE` from `response is None` or non-convergence alone.

- [ ] **Step 3: Run focused tests GREEN and commit**

Run: `PYTHONPATH=src python -m unittest tests.test_pr66_scientific_boundaries tests.test_campaign_failures tests.test_binary64_survey_scheduler -v`

```bash
git add src/windows_solver/campaign_runtime.py src/windows_solver/campaign_failures.py src/windows_solver/campaign_survey.py tests
git commit -m "fix(pr66): preserve typed horizon failures"
```

### Task 6: Wire projective triage and schema-11 dashboard evidence

**Files:**
- Modify: `src/windows_solver/campaign_reports.py`
- Modify: `src/windows_solver/campaign_triage.py`
- Modify: `src/windows_solver/campaign_runtime.py`
- Modify: `src/windows_solver/progress_output.py`
- Modify: `src/windows_solver/campaign_survey.py`
- Modify: `src/windows_solver/cli.py`
- Test: `tests/test_pr66_operations_governance.py`
- Test: `tests/test_campaign_triage.py`
- Test: `tests/test_schema11_reports.py`
- Test: `tests/test_clean_tail_dashboard.py`

**Interfaces:**
- Produces an authenticated non-release projective preview bound to the same checkpoint receipt and marked `release_admissible: false`.
- `write_schema11_triage()` consumes actual controller/angle data or emits `NOT_RUN_PROJECTIVE_BLOCKED`.
- Dashboard snapshot includes no-evidence/SCREENED/CERTIFIED/VALIDATED counts and current fixed-root response/disk values.

- [ ] **Step 1: Run projective/dashboard production tests RED**

Run: `PYTHONPATH=src python -m unittest tests.test_pr66_operations_governance tests.test_campaign_triage tests.test_schema11_reports tests.test_clean_tail_dashboard -v`

- [ ] **Step 2: Generate projective preview before whole-atlas triage**

Preserve missing/unresolved components explicitly; bind checkpoint, policy, row order, and output digest; never route preview output into release admission.

- [ ] **Step 3: Repair dashboard and live progress identity**

Read retained centres and stage response disks, derive evidence counts from the ledger, and carry ordinal/count/role/mode/spin/mechanism/pass/precision/leaf ID through every available progress scope.

- [ ] **Step 4: Run focused tests GREEN and commit**

Run: `PYTHONPATH=src python -m unittest tests.test_pr66_operations_governance tests.test_campaign_triage tests.test_schema11_reports tests.test_clean_tail_dashboard tests.test_progress -v`

```bash
git add src/windows_solver/campaign_reports.py src/windows_solver/campaign_triage.py src/windows_solver/campaign_runtime.py src/windows_solver/progress_output.py src/windows_solver/campaign_survey.py src/windows_solver/cli.py tests
git commit -m "feat(pr66): project evidence into triage and dashboard"
```

### Task 7: Make validation structurally independent

**Files:**
- Modify: `src/windows_solver/campaign_evidence.py`
- Modify: `src/windows_solver/campaign_runtime.py`
- Modify: `src/windows_solver/response_engine.py`
- Modify: `src/windows_solver/campaign_policy.py`
- Test: `tests/test_pr66_scientific_boundaries.py`
- Test: `tests/test_campaign_evidence_passes.py`

**Interfaces:**
- Produces distinct certification and independent-validation request schemas, operation identities, executors, and receipts.
- Validation requires a human-reviewed independence receipt and a different mathematical/code-path identity; unavailable/unreviewed comparison leaves evidence CERTIFIED.

- [ ] **Step 1: Run independence tests RED**

Run: `PYTHONPATH=src python -m unittest tests.test_pr66_scientific_boundaries tests.test_campaign_evidence_passes -v`

- [ ] **Step 2: Add separate independent comparator contracts**

Exterior comparator uses the reviewed finite-amplitude/root-displacement route; horizon comparator uses the reviewed finite-amplitude/scattering route. Same-route refinement, precision, tolerance, or endpoint changes cannot satisfy the independence receipt.

- [ ] **Step 3: Preserve retained centre on agreement or disagreement**

Agreement appends VALIDATED evidence for exactly the selected leaf. Disagreement appends discrepancy evidence and retains CERTIFIED without replacing numerical bytes.

- [ ] **Step 4: Run focused tests GREEN and commit**

Run: `PYTHONPATH=src python -m unittest tests.test_pr66_scientific_boundaries tests.test_campaign_evidence_passes -v`

```bash
git add src/windows_solver/campaign_evidence.py src/windows_solver/campaign_runtime.py src/windows_solver/response_engine.py src/windows_solver/campaign_policy.py tests
git commit -m "feat(pr66): require independent validation routes"
```

### Task 8: Separate NEW/RECOVER, harden paths, and reconcile public commands

**Files:**
- Modify: `src/windows_solver/campaign_policy.py`
- Modify: `src/windows_solver/campaign_recovery.py`
- Modify: `src/windows_solver/cli.py`
- Modify: `m02.ps1`
- Modify: `README.md`
- Modify: `docs/architecture.md`
- Modify: `docs/m02-admission-powershell.md`
- Test: `tests/test_pr66_operations_governance.py`
- Test: `tests/test_pr65_launcher.py`
- Test: `tests/test_public_surface.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Produces `campaign-new` with schema-11 origin `NEW` and no recovery fields.
- Recovery always writes origin `RECOVER` and authenticated recovery receipts.
- Retired public flags return deterministic migration messages naming explicit replacement commands.

- [ ] **Step 1: Run NEW/path/CLI parity tests RED**

Run: `PYTHONPATH=src python -m unittest tests.test_pr66_operations_governance tests.test_pr65_launcher tests.test_public_surface tests.test_cli -v`

- [ ] **Step 2: Implement origin semantics and dedicated new command**

Resume validates both origins; NEW never fabricates zero-source recovery metadata.

- [ ] **Step 3: Forward only resolved absolute PowerShell paths**

Every use after resolution passes `$SelectionPath` and the corresponding resolved checkpoint/queue/calibration/recovery path. Log each resolved identity before execution.

- [ ] **Step 4: Reconcile parser/help/docs and migration errors**

Every published fenced command must parse in help/dry-run mode; obsolete `campaign-run/resume --profile`, `--triage-queue`, and `--queue-limit` forms receive specific replacement guidance.

- [ ] **Step 5: Run focused tests GREEN and commit**

Run: `PYTHONPATH=src python -m unittest tests.test_pr66_operations_governance tests.test_pr65_launcher tests.test_public_surface tests.test_cli tests.test_m02_recover_script -v`

```bash
git add src/windows_solver/campaign_policy.py src/windows_solver/campaign_recovery.py src/windows_solver/cli.py m02.ps1 README.md docs tests
git commit -m "fix(pr66): separate campaign origins and public paths"
```

### Task 9: Restore provenance and remove active-root PR debris

**Files:**
- Restore: `.tasks/IN_PROGRESS.md` from the last authenticated TASK-079 state
- Modify: `.tasks/WORK_LOG.md`
- Delete: `PR65_GOVERNING_PR_COMPLETION_RESTORED_ADDITIVE.md`
- Preserve: `PR66_GOVERNING_COMPLETION_CONTRACT.md` as the sole active PR66 authority
- Modify: `tests/test_public_surface.py`
- Test: `tests/test_pr66_operations_governance.py`

**Interfaces:**
- Restores TASK-079 and the exact 2026-08-22 PR63 entry from commit `0be6dfcc8b5dbcfc402ec6856d29290b9e95c696`.
- Adds a newest-first PR65 incident entry without rewriting historical wording.

- [ ] **Step 1: Confirm board/provenance tests are RED**

Run: `python .tasks/validate_board.py && PYTHONPATH=src python -m unittest tests.test_pr66_operations_governance tests.test_public_surface -v`

Expected before repair: missing `IN_PROGRESS.md`, TASK-079, PR63 milestone, and root-debris failure.

- [ ] **Step 2: Restore exact historical task/work-log material and add PR65 incident**

Use Git history as the source; preserve all historical text verbatim. Add PR66 progress only as new entries.

- [ ] **Step 3: Delete only obsolete PR65 root debris and add the root-surface guard**

The deleted PR65 file remains recoverable through Git history. The guard rejects future governing/handover/scratch debris while explicitly retaining the sole authoritative PR66 contract.

- [ ] **Step 4: Run board/provenance tests GREEN and commit**

Run: `python .tasks/validate_board.py && PYTHONPATH=src python -m unittest tests.test_pr66_operations_governance tests.test_public_surface -v`

```bash
git add .tasks tests/test_public_surface.py tests/test_pr66_operations_governance.py
git rm PR65_GOVERNING_PR_COMPLETION_RESTORED_ADDITIVE.md
git commit -m "docs(pr66): restore project provenance"
```

### Task 10: Add fail-closed PR66 acceptance validation and verify the tested code head

**Files:**
- Create: `src/windows_solver/pr66_acceptance.py`
- Modify: `src/windows_solver/cli.py`
- Modify: `src/windows_solver/__init__.py`
- Test: `tests/test_pr66_operations_governance.py`
- Create later, only after operator logs: `docs/engineering/pr66-native-acceptance.json`

**Interfaces:**
- Produces `validate_pr66_acceptance(mapping, repository_root, receipt_commit_git_oid)` and CLI `pr66-acceptance-validate`.
- Validator recomputes all content digests, requires 40-character Git OIDs, proves `parent(Y)=X`, restricts X→Y to the acceptance JSON and explicitly allowed completion metadata, requires every mandatory canary/log/artifact hash, and requires `landing_approval_status == "PENDING"`.

- [ ] **Step 1: Run acceptance validator tests RED**

Run: `PYTHONPATH=src python -m unittest tests.test_pr66_operations_governance -v`

- [ ] **Step 2: Implement the closed parser and repository diff proof**

Reject missing/extra fields, duplicate JSON keys, stale contract hash, stale Git OIDs, non-parent finalisation commits, solver-affecting X→Y diffs, unhashed logs, absent math-review states, and forged approval.

- [ ] **Step 3: Run focused acceptance tests GREEN**

Run: `PYTHONPATH=src python -m unittest tests.test_pr66_operations_governance -v`

- [ ] **Step 4: Run the complete permitted verification matrix**

```bash
python .tasks/validate_board.py
PYTHONPATH=src python -m unittest discover -s tests -v
python -m compileall -q src tests tools
python tools/validate_release_manifest.py
git diff --check
```

- [ ] **Step 5: Commit and push tested code head X**

```bash
git add src/windows_solver/pr66_acceptance.py src/windows_solver/cli.py src/windows_solver/__init__.py tests docs/engineering/pr66-completion-implementation-plan.md
git commit -m "feat(pr66): enforce tested-head acceptance"
git push origin codex/pr66-governing-contract
```

- [ ] **Step 6: Stop for operator evidence**

Do not create `docs/engineering/pr66-native-acceptance.json` until the operator returns all mandatory native and mathematical canary logs for X. After those logs are reviewed, create exactly one metadata-only finalisation commit Y, validate it, keep landing `PENDING`, and stop for external operator landing review.
