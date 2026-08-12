# M02 ODE Diagnostics and Fail-Closed Worker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make promoted ODE behavior diagnosable and make every ODE resource/control failure abort operationally without changing scientific computation.

**Architecture:** Observe each existing SciML solution at the immediate vendored segment boundary with a non-mutating callback and post-solve inspection, translate return codes/statistics into typed Julia progress and failures, preserve those failures across Python/campaign status, and clean the complete Julia process tree on timeout or interruption.

**Tech Stack:** Julia 1.10.11 source contracts, SciMLBase 2.155.1 solution statistics, Python 3.12 standard library, typed progress events, `unittest`.

## Global Constraints

- Work only from `main`; do not merge or alter Tier 2 work.
- Do not execute Julia, solver scripts, determinants, mathematical tests, or campaigns.
- Do not change algorithms, tolerances, domains, endpoint order, `dtmax`, any existing `maxiters` spelling/value, Newton policy, branch policy, promotion policy, or scientific schemas.
- Do not add MultiFloats, comparator data, or any new arithmetic tier; retain adjacent repositories as follow-up evidence only.
- Keep diagnostics out of request identity, checkpoint science, and acceptance decisions.

---

### Task 1: Red contracts

**Files:**
- Modify: `tests/test_julia_response_backend.py`
- Modify: `tests/test_progress.py`

- [x] Add static contracts for immediate per-segment SciML observation, exact `destats`, typed failure, and ODE-failure fallback bypass.
- [x] Add unit contracts for typed worker receipts and process-tree cleanup.
- [x] Add reporter contracts that clear prior-tier live measurements and project ODE statistics.
- [x] Run only the focused non-scientific tests and record the expected failures.

### Task 2: Julia segment diagnostics and failure typing

**Files:**
- Modify: `src/windows_solver/data/julia/GeneralizedSasakiNakamura.jl/src/Homogeneous/ComplexFrequencies.jl`
- Modify: `src/windows_solver/data/julia/m02_worker.jl`

- [x] Add optional non-mutating callback/final-observer hooks to the radius, Xin, and Xup segment boundaries and inspect every solution before use.
- [x] Emit completion/failure statistics from `retcode` and `destats`.
- [x] Throw typed ODE integration/resource exceptions and rethrow them before predictor fallback.
- [x] Confirm the diff leaves every numerical solve option semantically equivalent and every existing `maxiters` spelling/value unchanged.

### Task 3: Python lifecycle, failure receipts, and dashboard truth

**Files:**
- Modify: `src/windows_solver/progress.py`
- Modify: `src/windows_solver/julia_response_backend.py`
- Modify: `src/windows_solver/response_batches.py`
- Modify: `src/windows_solver/cli.py`
- Modify: `src/windows_solver/progress_output.py`

- [x] Add stable ODE event kinds and status projection.
- [x] Raise dedicated timeout and ODE-resource backend exceptions with bounded worker receipts.
- [x] Spawn an isolated POSIX session or a job-bound Windows launch bootstrap and terminate the complete Julia tree during timeout or exceptional unwinding.
- [x] Preserve the worker receipt through leaf, campaign, and final request failure status.
- [x] Clear all prior-tier live numerical state before rendering a promoted stage.

### Task 4: Static verification and delivery

**Files:**
- Modify: `.tasks/IN_PROGRESS.md`

- [x] Run focused tests, Python compilation, TaskPlanner validation, whitespace checks, and source invariants without invoking Julia or scientific execution.
- [x] Review the exact main-only diff for numerical-policy drift and failure-path completeness.
- [x] Commit, push a new branch from current `main`, and open a draft PR with the operator-only verification commands and airgap disclosure.
