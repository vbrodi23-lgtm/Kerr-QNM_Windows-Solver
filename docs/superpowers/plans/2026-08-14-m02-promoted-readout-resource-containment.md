# M02 Promoted-Readout Resource Containment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bound pathological promoted Julia root readouts, preserve authenticated control evidence, quarantine only the affected leaf, and continue the M02 campaign without changing scientific identities or numerical policy.

**Architecture:** Add one canonical operational resource policy at the Julia request boundary; enforce it cooperatively inside Julia; translate authenticated control receipts into three Python exception types; and persist failures in a versioned append-only checkpoint ledger. Reports and progress views consume the ledger but never turn execution failures into scientific results.

**Tech Stack:** Python 3.12 dataclasses/unittest, Julia 1.10 source contracts, canonical JSON/SHA-256, PowerShell-facing progress/status JSON.

## Global Constraints

- Do not execute Julia, Kerr determinants, campaign commands, or any scientific payload.
- Preserve all numerical controls and the complete diagnostic sequence after a successful promoted primary.
- Preserve leaf/root/backend/scientific-policy identities and existing solved-leaf compatibility.
- Catch only the three typed resource/timeout failures at the campaign continuation boundary.
- Keep unknown events, malformed receipts, protocol errors, and identity failures fatal.
- Keep TASK-075 and TASK-076 open and leave the M02 milestone unchanged.

---

### Task 1: Request policy and typed backend receipts

**Files:**
- Modify: `src/windows_solver/julia_response_backend.py`
- Modify: `src/windows_solver/progress.py`
- Test: `tests/test_julia_response_backend.py`
- Test: `tests/test_worker_lifecycle_contract.py`
- Test: `tests/test_root_readout_cache.py`

**Interfaces:**
- Produces: canonical execution-resource mappings, request-bound resource SHA-256, and typed bounded failure receipts.
- Preserves: scientific backend identity and solved-leaf identity inputs.

- [ ] Write tests that distinguish ODE limit, readout infeasibility, timeout, malformed failure, and request-digest behavior.
- [ ] Run the focused tests and confirm each new assertion fails for the missing behavior.
- [ ] Implement canonical policy validation, request injection, timeout synthesis, and typed exception mapping.
- [ ] Re-run focused tests and retain only behavior needed by the contracts.

### Task 2: Julia cooperative containment and primary short-circuit

**Files:**
- Modify: `src/windows_solver/data/julia/m02_worker.jl`
- Test: `tests/test_julia_response_backend.py`
- Test: `tests/test_worker_lifecycle_contract.py`

**Interfaces:**
- Consumes: the authenticated execution-resource object flattened from each request.
- Produces: reserved ODE/resource events and bounded `CONTROL` failure responses.

- [ ] Add static contract tests for finite `maxiters`, callback ceilings, readout feasibility, primary short-circuit, and reserved-event registration.
- [ ] Run those tests and confirm the unbounded/current source fails them.
- [ ] Implement callback enforcement, determinant accounting, feasibility estimation, and absent diagnostic fields after failed primary.
- [ ] Re-run static tests without launching Julia.

### Task 3: Append-only campaign quarantine and retry

**Files:**
- Modify: `src/windows_solver/response_batches.py`
- Test: `tests/test_linear_response_precision.py`
- Test: `tests/test_solved_leaf_cache.py`
- Test: `tests/test_campaign_progress_live.py`

**Interfaces:**
- Consumes: only the three typed backend failures.
- Produces: authenticated attempt records, deferred non-computed leaves, atomic checkpoints, and explicit-resume retry behavior.

- [ ] Add synthetic campaign tests for ODE limit, timeout, following-leaf continuation, fatal malformed failures, no solved receipt, completed-neighbour reuse, and explicit resume.
- [ ] Run the focused tests and observe the pre-change campaign abort.
- [ ] Add the versioned attempt record/envelope compatibility path and typed continuation boundary.
- [ ] Re-run focused tests and verify schema-version-3 fixtures still load.

### Task 4: Reports, dashboard, and status JSON

**Files:**
- Modify: `src/windows_solver/campaign_reports.py`
- Modify: `src/windows_solver/progress_output.py`
- Test: `tests/test_campaign_reports.py`
- Test: `tests/test_campaign_progress_live.py`

**Interfaces:**
- Consumes: authenticated checkpoint attempts and typed `leaf_failed` payloads.
- Produces: `m02-resource-failures.csv`, status failure categories, and non-scientific deferred counters.

- [ ] Add report/status tests proving resource details are exposed and scientific fields remain absent.
- [ ] Run the focused tests and confirm the report/status contracts are missing.
- [ ] Implement resource-failure projections and separate dashboard categories.
- [ ] Re-run focused tests and inspect emitted JSON/CSV literals.

### Task 5: Tracking, verification, review, and draft PR

**Files:**
- Modify: `.tasks/BACKLOG.md`
- Modify: `.tasks/WORK_LOG.md`
- Verify: all files changed by Tasks 1–4

**Interfaces:**
- Produces: TASK-076 containment focus, dated evidence-ceiling entry, verified branch, and draft PR.

- [ ] Update TASK-076 Plan/Review Focus and prepend the dated work-log entry without changing task or milestone state.
- [ ] Run TaskPlanner validation, Python compilation, focused mocked/static tests, and only then the confirmed non-scientific Python regression suite.
- [ ] Review the complete diff for scientific-identity drift, generic continuation catches, fabricated science, and unsynchronized events.
- [ ] Commit explicit paths, push `agent/m02-promoted-readout-resource-containment`, and open a draft PR against `main` without merging.
