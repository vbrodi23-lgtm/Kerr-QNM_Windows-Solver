# M02 Within-Leaf Momentum Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Accelerate finer signed-ε PRIMARY roots with accepted same-ray predictors while preserving all independent M02 evidence and historical solved-leaf reuse.

**Architecture:** `run_component()` owns four local ray states and passes an optional complex predictor through the existing backend boundary. Native binary64 and Julia promoted-precision backends select or reject that predictor before the unchanged four-phase solve. Progress telemetry remains outside scientific payloads and cache identity.

**Tech Stack:** Python 3.11+, Julia 1.10.11 worker source, `unittest`, typed progress events.

## Global Constraints

- Preserve the exact 212-leaf domain and all numerical/scientific policy values.
- Never pass momentum into SEED-PATH.
- Never serialize predictors or telemetry into scientific evidence or solved-leaf identity.
- Run static/Python tests only; do not execute a Kerr determinant, Julia worker, or campaign.

---

### Task 1: Signed-ray predictor state

**Files:**
- Modify: `src/windows_solver/response_engine.py`
- Test: `tests/test_linear_response_provider.py`

**Interfaces:**
- Produces: `RootReadoutBackend.read_root(job, amplitude, primary_predictor=None)`.
- Preserves: `ComponentResult` and `RootReadout` mappings.

- [ ] Add a test backend that records optional predictors and returns deterministic analytic roots.
- [ ] Prove the current engine fails to provide predictors for finer ε levels.
- [ ] Maintain four ray-local accepted states and pass the scaled predictor only on the corresponding finer ray.
- [ ] Prove first/coarse readouts use no predictor and the scientific computation identity is unchanged.

### Task 2: Conservative native and Julia seed admission

**Files:**
- Modify: `src/windows_solver/native_response_kernel.py`
- Modify: `src/windows_solver/julia_response_backend.py`
- Modify: `src/windows_solver/data/julia/m02_worker.jl`
- Test: `tests/test_linear_response_provider.py`
- Test: `tests/test_julia_response_backend.py`

**Interfaces:**
- Consumes: optional `primary_predictor`.
- Produces: PRIMARY seed selection with explicit fallback; unchanged TRUNCATION, RESOLUTION, and SEED-PATH seeds.

- [ ] Prove a finite in-branch predictor enters the normal PRIMARY Newton solve without a dual-seed determinant preflight.
- [ ] Prove an out-of-branch predictor falls back before work and a failed/escaped predictor attempt retries from the authenticated background.
- [ ] Prove SEED-PATH remains the independently displaced background seed.
- [ ] Add the optional predictor to the authenticated Julia request and static worker contract without running Julia.

### Task 3: Out-of-band momentum telemetry

**Files:**
- Modify: `src/windows_solver/progress.py`
- Modify: `src/windows_solver/progress_output.py`
- Test: `tests/test_native_progress.py`
- Test: `tests/test_progress.py`

**Interfaces:**
- Produces: seed-selection progress event and PRIMARY aggregate statistics.
- Preserves: scientific evidence/checkpoint schemas.

- [ ] Prove each completed PRIMARY phase records seed kind, initial determinant, fallback, Newton iterations, determinant calls, result, and elapsed time.
- [ ] Prove reporter aggregation separates authenticated-background, ε-continuation, and fallback samples.
- [ ] Show the aggregate in status/trace output without claiming improvement.

### Task 4: Compatibility and regression proof

**Files:**
- Modify: `tests/test_solved_leaf_cache.py`
- Modify: `.tasks/IN_PROGRESS.md`
- Modify: `.tasks/WORK_LOG.md` only when the slice is complete.

**Interfaces:**
- Preserves: `scientific_computation_identity_sha256` and historical cache records.

- [ ] Prove a pre-momentum solved record remains a cache hit under the new code.
- [ ] Run focused tests, complete Python tests, compile checks, TaskPlanner validation, and release-manifest validation.
- [ ] Review the diff for domain, numerical-policy, SEED-PATH, evidence-schema, and cache-identity changes.
- [ ] Publish the reviewed increment to the existing draft PR and stop for Windows `./m02.ps1` logs.
