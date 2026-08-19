# M02 Promoted-Response Architecture Repair Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace promoted exterior perturbed-root production with fixed-root derivative disks, bound promoted horizon uncertainty, and add the adaptive precision, endpoint, recovery, checkpoint, migration, and operator surfaces required to resume M02 safely.

**Architecture:** Keep the existing Kerr determinant and branch machinery authoritative. Add small typed Python policy/evidence modules, route promoted components through explicit derivative or analytic response runners, extend the Julia wire boundary only for fixed-root determinant samples and adaptive endpoint evidence, and retain the old full ladder behind an identity-bound validation policy. Historical checkpoints stay immutable; migration emits a new schema checkpoint after validating the source.

**Tech Stack:** Python 3.12 dataclasses/unittest, Julia 1.10 static source/spec contracts, PowerShell 5.1 parser/static contracts, canonical JSON/SHA-256 identities.

**Spec:** `../upload/codex_m02_production_architecture_repair.md` (operator-supplied authoritative task text; copied into the PR as the engineering note in Task 3).

## Global Constraints

- Never execute a Kerr determinant, Julia worker, radial or coordinate ODE, angular solve, QNM root solve, M02 campaign, or either production PowerShell tester.
- Synthetic Python backends, static Julia checks, canonical serialization/migration tests, compile checks, and deterministic fixture replay are allowed.
- Do not weaken branch, axis, Richardson/order, even-remainder, signal, reliable-digit, or two-endpoint gates.
- Use direct fixed-root determinant differentiation as the admitted exterior fallback; do not claim variational independence until the shared equation/transport implementation is admitted.
- Use semantic tier order `binary64 → bigfloat-40 → bigfloat-80 → bigfloat-120`; record decimal digits and MPFR bits separately.
- Preserve stopped checkpoints and receipts byte-for-byte. Migrations validate the source and write only a new destination.
- Use exact blocker text `TODO: [HUMAN MATH REVIEW REQUIRED - calibrated conversion from determinant/root error budget to ODE local tolerances is not yet established]` when the repository cannot justify the ODE tolerance conversion.
- Every observable behavior change follows red → green → refactor, with the failing command and expected failure recorded before production edits.

---

### Task 1: Typed uncertainty, precision, adaptive-control, and partial-journal contracts

**Files:**
- Create: `src/windows_solver/response_uncertainty.py`
- Create: `src/windows_solver/adaptive_controls.py`
- Create: `src/windows_solver/partial_component_checkpoint.py`
- Modify: `src/windows_solver/precision_tiers.py`
- Create: `tests/test_precision_tier_ordering.py`
- Create: `tests/test_adaptive_outer_endpoint.py`
- Create: `tests/test_adaptive_ode_budget.py`
- Create: `tests/test_partial_component_checkpoint.py`
- Create: `tests/test_promoted_horizon_uncertainty.py`

**Interfaces:**
- Produces `ComplexDisk`, `exterior_response_disk`, `horizon_response_disk`, and typed zero-containing failures.
- Produces `PrecisionTier`, `precision_tier`, `next_precision_tier`, and `working_precision_bits` while retaining explicit legacy boundary conversion.
- Produces deterministic outer-endpoint candidate/selection evidence and request-level ODE error-budget records; absent calibration fails with the exact human-math blocker.
- Produces an atomic `PartialComponentJournal` whose canonical entry identity binds every field listed in the specification and rejects conflicting receipts.

- [ ] Write focused tests first for quotient/product/inversion disks, non-exact zero radius rejection, semantic tier order, nearest adequate endpoint selection, monotone ODE budgets/fail-closed calibration, atomic resume, conflict rejection, and canonical serialization.
- [ ] Run each new test file and record the expected missing-symbol/behavior failures.
- [ ] Implement only the typed pure contracts required by those tests, reusing `canonical_json_bytes` and the repository's atomic JSON pattern.
- [ ] Re-run the focused tests and `python -m compileall -q src tests`.
- [ ] Commit as `feat(m02): add promoted response control contracts`.

### Task 2: Derivative-based promoted components and bounded horizon integration

**Files:**
- Modify: `src/windows_solver/response_engine.py`
- Modify: `src/windows_solver/julia_response_backend.py`
- Modify: `src/windows_solver/response_batches.py`
- Modify: `src/windows_solver/data/julia/m02_worker.jl`
- Modify: `src/windows_solver/data/julia/m02_worker_finite_difference_spec.jl`
- Create: `tests/test_promoted_exterior_derivative.py`
- Extend: `tests/test_promoted_horizon_uncertainty.py`
- Create: `tests/test_selective_readout_promotion.py`
- Extend: `tests/test_julia_response_backend.py`
- Extend: `tests/test_regularised_gsn_worker_static.py`

**Interfaces:**
- Adds a fixed-root determinant-sample boundary returning complex determinant centre, absolute determinant error, family/normalisation/branch identities, request/worker receipt hashes, semantic tier, and MPFR bits.
- Adds `run_promoted_exterior_component`: one authenticated baseline root, real-axis `h` and `h/2` fixed-root stencils, optional imaginary-axis validation only for explicit reasons, `−D_c/D_ω` disk propagation, and optional one signed validation pair.
- Adds `run_promoted_horizon_component/v2`: root/p_H disk from PRIMARY plus fixed-root TRUNCATION/RESOLUTION correction evidence, D′ disk from PRIMARY derivative plus admitted derivative comparison, and analytic inversion disk.
- Keeps the full ladder callable only with `RISK_SELECTED_SENTINEL`, `DERIVATIVE_DISAGREEMENT`, or `PUBLICATION_VALIDATION`; derivative failure never falls back implicitly.

- [ ] Write failing behavioral tests proving ordinary exterior promotion performs no perturbed-root ladder, determinant counts and identities serialize, denominator disks fail closed, validation reasons are restricted, and bounded horizon results carry positive radius or are unusable.
- [ ] Run the focused tests and record failures caused by the absent route/evidence fields.
- [ ] Implement Python runners and schemas, then the minimal Julia request/response operation using the existing determinant evaluator and finite-difference conditioning machinery without executing it.
- [ ] Route `NativeCampaignStageBackend` exterior 40/80/120 stages to the derivative runner and horizon stages to the current bounded analytic implementation; retain binary64 historical behavior.
- [ ] Re-run focused Python tests, static Julia tests, compile checks, and relevant existing promoted-horizon/backend tests.
- [ ] Commit as `feat(m02): replace promoted exterior roots with derivative disks`.

### Task 3: Adaptive endpoints, safe-window recovery, migration, and operator handoff

**Files:**
- Modify: `src/windows_solver/data/julia/GeneralizedSasakiNakamura.jl/src/Homogeneous/ComplexFrequencies.jl`
- Modify: `src/windows_solver/data/julia/GeneralizedSasakiNakamura.jl/test/horizon_endpoint_adaptive_spec.jl`
- Modify: `src/windows_solver/data/julia/m02_worker.jl`
- Modify: `src/windows_solver/progress.py`
- Modify: `src/windows_solver/response_engine.py`
- Modify: `src/windows_solver/response_batches.py`
- Create: `tests/test_response_ladder_recovery.py`
- Create: `tests/test_adaptive_horizon_endpoint.py`
- Create: `tests/test_campaign_checkpoint_migration.py`
- Create: `tests/test_production_222_endpoint_recovery_script.py`
- Create: `tests/test_production_light_ring_response_recovery_script.py`
- Create: `M02_Production_222_A9999_Endpoint_Recovery_v1.ps1`
- Create: `M02_Production_LightRing_A9999_Response_Recovery_v1.ps1`
- Create: `docs/engineering/2026-08-19-m02-promoted-response-architecture-repair.md`
- Modify: `.tasks/IN_PROGRESS.md`
- Modify: `.tasks/WORK_LOG.md`

**Interfaces:**
- Horizon search exhausts deterministic depths at an order before increasing order, caches geometry, selects ingoing/outgoing best prefixes independently, requires two verified endpoints, and emits distinct typed exhaustion/precision outcomes.
- Ladder recovery enumerates all consecutive windows of at least four levels, applies every existing gate, deterministically selects the finest admissible window, requests exact mode-specific amplitude expansion before precision, and promotes only failing signed roots.
- Checkpoint schema migration authenticates the old checkpoint, preserves it, writes a new destination, and invalidates only changed component identities.
- Operator scripts isolate output/cache roots, select only the specified leaves, print canonical evidence, and expose deliberate one-readout interruption/resume without executing during development.

- [ ] Add minimized preserved-fixture tests first for captured ratios, exact amplitude requests, finest safe window, nonlinear rejection, search ordering, geometry caching, best-prefix stopping, one-endpoint failure, zero ODE-before-pair, canonical evidence, and selective invalidation.
- [ ] Run the focused tests and record the expected failures.
- [ ] Port the prototype control logic into repository types and repair PR #55's newest-level-only verdict so all candidate windows are evaluated without bypassing any gate.
- [ ] Add schema/migration behavior and both operator scripts, then add parser/static tests that inspect behavior rather than merely filenames.
- [ ] Add the engineering note with identities, fail-closed boundaries, operator commands, and explicit statement that no production solver was run.
- [ ] Re-run all focused tests, TaskPlanner validation, PowerShell static/parser tests, and compile checks.
- [ ] Commit as `feat(m02): add adaptive recovery and readout resume`.

### Task 4: Air-gapped regression, review, and PR publication

**Files:**
- Modify only files required by verified regression or review findings.

**Interfaces:**
- Produces a reviewable PR #55 head with all permitted verification evidence and an explicit operator-only validation boundary.

- [ ] Run every new test file plus relevant existing component, precision, backend, campaign, migration, report, public-surface, and static Julia-source suites.
- [ ] Run `python .tasks/validate_board.py`, `python tools/validate_release_manifest.py`, `python -m compileall -q src tools tests`, and `git diff --check`.
- [ ] Confirm neither production PowerShell script nor any Julia/Kerr solver command appears in executed command history for this task.
- [ ] Perform scoped task reviews and a whole-branch review; fix all load-bearing findings and re-run covering tests.
- [ ] Update the task plan/work log with exact commands, counts, evidence ceiling, commit hashes, and the operator next action.
- [ ] Commit remaining review/documentation changes, push `solver/campaign-optimization`, and update draft PR #55 without opening another PR.
