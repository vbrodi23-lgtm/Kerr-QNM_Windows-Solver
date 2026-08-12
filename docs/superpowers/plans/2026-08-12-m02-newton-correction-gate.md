# M02 Newton-Correction Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make root convergence and precision promotion depend on an authenticated local Newton-correction estimate rather than determinant normalization.

**Architecture:** Keep the current determinant and four-phase validation, but evaluate a finite centred Dω before accepting each phase and use `|D|/|Dω|` as the root gate. Bind the policy into solved-leaf identity and migrate only stored binary64 successes whose own derivative evidence passes the new gate.

**Tech Stack:** Python 3.12, Julia 1.10.11 source contract, `unittest`, TaskPlanner.

## Global Constraints

- Do not run Julia, solver scripts, determinants, mathematical tests, or campaigns.
- Do not change the determinant, radial formulation, contour, endpoints, ODE controls, response ladder, branch radius, or evidence ceiling.
- Retain raw determinant residuals as diagnostics and retain BigFloat80/120 as fail-closed recovery tiers.
- Never describe `|D|/|Dω|` as a measured root error or certificate; final acceptance still requires the independent four-phase branch checks.

---

### Task 1: Red root-gate contracts

**Files:**
- Modify: `tests/test_linear_response_provider.py`
- Modify: `tests/test_julia_response_backend.py`
- Modify: `tests/test_campaign_reports.py`

**Interfaces:**
- Consumes: the existing native `_bounded_newton`, Julia worker source, and precision-stage report projection.
- Produces: failing behavioral/static tests for correction convergence and truthful dashboard ratios.

- [ ] Add an analytic determinant test with `|D| = 3.50×10⁻¹¹`, `|Dω| = 36.1`, and `η_D ≈ 9.70×10⁻¹³`; require convergence before damping.
- [ ] Record the Wolfram audit: the observed product is tautological, the estimate is locally first-order for a simple root, and it is not a global certificate.
- [ ] Prove a tiny local estimate cannot override SEED-PATH disagreement outside the branch radius.
- [ ] Run the focused native test and confirm it fails because current main continues on bare residual.
- [ ] Add Julia source-contract assertions for `magnitude / derivative_abs` and correction-based acceptance.
- [ ] Add a report test requiring `CORR_OVER_TOL` to use the Newton-correction estimate rather than bare determinant magnitude.
- [ ] Run the focused tests and preserve the expected failures.

### Task 2: Native and Julia correction gates

**Files:**
- Modify: `src/windows_solver/native_response_kernel.py`
- Modify: `src/windows_solver/data/julia/m02_worker.jl`
- Modify: `src/windows_solver/julia_response_backend.py`

**Interfaces:**
- Consumes: tier-specific root-correction tolerance and existing centred derivatives.
- Produces: four-phase `converged` values derived from correction evidence.

- [ ] Replace the pre-derivative bare-residual stop with a finite derivative and `|D/Dω|` stop in both Newton loops.
- [ ] Recompute returned phase convergence from the final stored `|D|` and `|Dω|` pair.
- [ ] Rename promoted request controls from `root_tolerance` to `root_correction_tolerance` so work-cache identity changes.
- [ ] Run focused tests and confirm the new gate passes while derivative failures remain fail-closed.

### Task 3: Scientific identity, migration, and reporting

**Files:**
- Modify: `src/windows_solver/response_batches.py`
- Modify: `src/windows_solver/campaign_reports.py`
- Modify: `src/windows_solver/progress_output.py`
- Modify: `tests/test_linear_response_precision.py`
- Modify: `tests/test_solved_leaf_cache.py`
- Modify: `.tasks/IN_PROGRESS.md`

**Interfaces:**
- Consumes: stored `RootReadout.newton_correction_estimate` values.
- Produces: versioned root-gate identity, evidence-qualified prior-success migration, and correction-ratio dashboard fields.

- [ ] Bind the root-correction policy to every leaf scientific identity and define exact immediate-predecessor identity material.
- [ ] Permit PRIMARY one-stage binary64 success migration only when every raw readout passes the correction gate.
- [ ] Keep old unresolved/promoted/correction-failing receipts stale.
- [ ] Replace `D_OVER_TOL` with `CORR_OVER_TOL`; continue displaying `D_ABS` independently.
- [ ] Update TASK-075's plan without marking the milestone Done.

### Task 4: Verification, review, and draft PR

**Files:**
- Modify only files listed above.

**Interfaces:**
- Consumes: completed implementation and red/green evidence.
- Produces: reviewed draft PR and operator probe.

- [ ] Run focused non-scientific tests, Python compilation, TaskPlanner validation, and `git diff --check`.
- [ ] Review the exact diff for mathematical scope drift, identity gaps, and unsupported claim changes.
- [ ] Publish one commit whose parent is remote `main@970d228d` and open a draft PR.
- [ ] Record that Julia and scientific execution were not run and provide the exact PowerShell operator probe.
