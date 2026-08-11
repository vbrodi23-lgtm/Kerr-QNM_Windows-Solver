# M02 PRIMARY precision-recovery implementation plan

> **For agentic workers:** Execute this plan test-first. Run only synthetic or
> structural Python tests; do not invoke the solver, Julia worker, PowerShell,
> or mathematical campaign workloads.

**Goal:** Recover authenticated `PRIMARY` binary64 `NOT_CONVERGED` outcomes at
80/120 digits while preserving role boundaries, scientific identity, cache
authentication, and fail-closed checkpoint behavior.

**Architecture:** Define one canonical PRIMARY recovery contract in
`response_batches.py` and reuse it in leaf identity, checkpoint binding,
execution, and semantic validation. Preserve an exact legacy binary64 identity
derivation for success-only solved-receipt migration. Keep native promoted-stage
execution generic and leave `response_engine.py`, numerical policies, CONTROL,
and DEEP behavior unchanged.

**Tech stack:** CPython standard library, `unittest`, canonical JSON/SHA-256
bindings, existing `SolvedLeafStore`, TaskPlanner 2.1.1.

---

### Task 1: Freeze the PRIMARY recovery contract in red tests

**Files:**
- Modify: `tests/test_linear_response_precision.py`
- Modify: `tests/test_linear_response_batches.py`
- Modify: `tests/test_solved_leaf_cache.py`

- [ ] Add authenticated synthetic `ComponentResult` fixtures for `CONVERGED`
  and `NOT_CONVERGED`, with exact leaf/root/policy/backend lineage.
- [ ] Assert PRIMARY 64→80 recovery, each independent 80→120 gate, and exact
  terminal state at 80 and 120.
- [ ] Assert `BRANCH_LOSS`, `NOISE_FLOOR`, and `AXIS_MISMATCH` never promote;
  CONTROL remains one 64 stage; existing DEEP ladders remain unchanged.
- [ ] Assert missing 80/120 capability yields `MISSING_PRECISION` rather than a
  cacheable terminal record.
- [ ] Assert only PRIMARY identity changes and an old precision binding is
  rejected without a campaign/checkpoint schema bump.
- [ ] Assert exact legacy PRIMARY binary64 success migration and legacy
  unresolved recomputation.
- [ ] Run the focused tests and confirm they fail for the absent PRIMARY ladder,
  old identity, and missing migration—not fixture or import errors.

### Task 2: Implement the role-specific ladder and semantics

**Files:**
- Modify: `src/windows_solver/response_batches.py`

- [ ] Add canonical current/legacy PRIMARY precision-contract helpers and share
  scientific identity material without changing CONTROL/DEEP identity bytes.
- [ ] Include the PRIMARY contract in `precision_contract_sha256` while retaining
  schema 2/checkpoint schema 3.
- [ ] Split semantic validation into CONTROL, PRIMARY, and unchanged DEEP
  grammars; require authenticated production evidence before PRIMARY promotion.
- [ ] Split campaign execution by role. At 64 promote PRIMARY only for
  authenticated `NOT_CONVERGED`; at 80 force 120 for authenticated
  `NOT_CONVERGED`, failed self-refinement, or unenclosed discrepancy; at 120 use
  `CONVERGED && discrepancy_enclosed` for `PRODUCED`.
- [ ] Run the focused precision/campaign tests to green and verify the existing
  DEEP regression remains green.

### Task 3: Add exact success-only solved-receipt migration

**Files:**
- Modify: `src/windows_solver/response_batches.py`
- Modify: `tests/test_solved_leaf_cache.py`

- [ ] On a current-ID miss, derive and query the exact legacy PRIMARY identity;
  never authorize migration from the cache's generic same-leaf stale result.
- [ ] Fully authenticate a one-stage binary64 `PRODUCED`/`CONVERGED` record,
  republish its unchanged inner record under the current identity, retain the
  old receipt, and re-read the current receipt.
- [ ] Refuse migration for legacy unresolved, corrupt, or non-exact stale
  receipts so normal campaign execution recomputes them.
- [ ] Run focused cache tests, structural compilation, `git diff --check`, and
  the TaskPlanner validator. Obtain an independent code review before publish.

### Task 4: Publish for Windows evidence

**Files:**
- Modify: `.tasks/IN_PROGRESS.md`
- Add: this design and plan

- [ ] Commit task-scoped changes on `agent/fix-m02-primary-precision-recovery`.
- [ ] Publish the branch and open a new pull request against `main`; do not merge.
- [ ] Report safe local test evidence and explicitly defer solver/Julia/
  PowerShell execution evidence to the user.
