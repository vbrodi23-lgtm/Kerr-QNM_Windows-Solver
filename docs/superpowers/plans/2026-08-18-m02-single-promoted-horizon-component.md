# M02 Single Promoted Horizon Component Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace multiplied promoted horizon component execution with one operator-validated root readout and an algebraic response while preserving binary64 and non-horizon behavior.

**Architecture:** Add one narrow runner in `response_engine.py`, select it only from the promoted primary horizon campaign boundary, and represent its uncalibrated response honestly. Version the outer component/checkpoint identity and migrate only authenticated binary64 stages from the predecessor checkpoint contract.

**Tech Stack:** Python 3.12 dataclasses, Decimal evidence, unittest, Julia subprocess adapter contracts, JSON checkpoint/cache identities, PowerShell operator harness.

## Global Constraints

- Do not change `src/windows_solver/data/julia/m02_worker.jl`.
- Do not execute Julia, Kerr determinants, ODE solves, Leaf 13, amplitude ladders, campaigns, or the PowerShell tester.
- Scope the dedicated path to primary `horizon-admittance` leaves at 80/120 digits.
- Preserve generic binary64, exterior, control, and deep behavior.
- Use `h_B = 1 / (2j * p_H * Dprime_PRIMARY)` with no determinant evaluation.

---

### Task 1: Dedicated component and evidence contract

**Files:**
- Modify: `src/windows_solver/response_engine.py`
- Create: `tests/test_promoted_horizon_component.py`

**Interfaces:**
- Consumes: `ResponseComponentJob`, `RootReadoutBackend`, and the operator-validated `RootReadout.primary_acceptance`/fixed-root evidence.
- Produces: `run_promoted_horizon_component(job, backend, primary_predictor) -> ComponentResult` and optional analytic evidence fields on `ComponentResult`.

- [x] Write focused tests for one `0.0j` readout, baseline progress scope, strict root evidence, formula fixture, error cases, empty levels, and non-applicable uncertainty channels.
- [x] Run the focused module and confirm failures name the missing runner/evidence fields.
- [x] Add the minimal dedicated runner and serialization fields.
- [x] Re-run the focused module to green and refactor only shared validation needed by the runner.

### Task 2: Campaign selection, predictor, and promotion policy

**Files:**
- Modify: `src/windows_solver/response_batches.py`
- Modify: `tests/test_native_campaign_backend.py`
- Modify: `tests/test_linear_response_precision.py`

**Interfaces:**
- Consumes: preceding `StageOutcome.component_result["result"]`.
- Produces: one-readout 80/120 stages with explicit discrepancy applicability and no `refinement=1` backend.

- [x] Write tests proving previous baseline omega is the root predictor and response continuation is not substituted.
- [x] Write tests proving primary horizon 80/120 executes one readout, skips self-refinement, and promotes only from typed root/conditioning gates.
- [x] Run those tests and confirm the current generic ladder/refinement path fails them.
- [x] Route only eligible leaves through the dedicated runner, separate predictor names, and implement the evidence-driven 80→120 decision.
- [x] Re-run focused tests, then existing native/deep/exterior regressions.

### Task 3: Checkpoint and solved-leaf identity migration

**Files:**
- Modify: `src/windows_solver/response_batches.py`
- Modify: `tests/test_linear_response_batches.py`
- Modify: `tests/test_solved_leaf_cache.py`

**Interfaces:**
- Consumes: authenticated predecessor checkpoint/record mappings.
- Produces: current checkpoint records containing retained canonical binary64 stages only for affected old promoted horizon records.

- [x] Write tests for retaining completed binary64 records, removing incomplete/complete old promoted horizon stages, and refusing unauthenticated predecessor evidence.
- [x] Run the tests and observe the predecessor partial-checkpoint rejection/reuse failure.
- [x] Add the component identity, checkpoint contract version, and narrow migration.
- [x] Re-run checkpoint/cache tests and validate the TaskPlanner board.

### Task 4: Operator production-equivalence tester

**Files:**
- Create: the production Leaf 13 equivalence PowerShell tester.
- Create or modify: a static/parser test for the tester contract.

**Interfaces:**
- Consumes: clean production campaign APIs only.
- Produces: operator-run assertions for one Julia amplitude readout, no signed roots/self-refinement/refinement=1, validated determinant budgets, converged root/component, and finite analytic response.

- [x] Write the static contract test first and confirm the tester is absent.
- [x] Add the PowerShell harness without overlays, monkeypatches, or copied Julia source.
- [x] Run only the static/parser test; do not execute PowerShell.

### Task 5: Verification and delivery

**Files:**
- Verify all changed files and the protected worker.

- [x] Run focused unit/static suites, Python compile checks, board validation, and `git diff --check`.
- [x] Confirm the worker SHA-256 still equals `d3b2f32984775d8247cadac92b63cf70f9c55f7cf1687f9f724bcf958c595309` and has no diff.
- [x] Review the diff against every operator count and scope exclusion.
- [x] Commit, push `codex/fix-promoted-horizon-single-readout-component`, and open the requested draft PR against `main`.
