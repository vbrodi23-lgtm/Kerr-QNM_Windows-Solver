# M02 Live Execution Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep the terminal dashboard visibly current throughout a promoted Julia root solve while preserving the completed-stage table and scientific state.

**Architecture:** Serialize Julia stdout progress and a 2-second Python heartbeat in the adapter wait loop. Project timing/activity into the existing progress reporter, then render independent completed and active dashboard sections.

**Tech Stack:** Python 3.12 standard library, existing typed progress events, `unittest` synthetic fixtures.

## Global Constraints

- Do not execute Julia, the solver, determinants, or a PowerShell campaign.
- Do not change numerical policy, requests, checkpoint/evidence bytes, promotion decisions, or scientific terminal states.
- Keep the precision-stage results table and latest-completed-leaf panel additive and backward compatible.

---

### Task 1: Serialized worker heartbeat

**Files:**
- Modify: `src/windows_solver/progress.py`
- Modify: `src/windows_solver/julia_response_backend.py`
- Test: `tests/test_julia_response_backend.py`

**Interfaces:**
- Produces: `ProgressEventKind.WORKER_HEARTBEAT` with `worker`, `worker_alive`, and `heartbeat_interval_seconds` payload.
- Preserves: reserved Julia stdout events and non-reserved stdout/stderr capture.

- [ ] Write a synthetic child-process test that expects at least one heartbeat before exit and preserves a Julia Newton event.
- [ ] Run the focused test and observe failure because no heartbeat event exists.
- [ ] Queue reserved stdout lines and drain them with heartbeats from the waiting thread.
- [ ] Run the focused backend tests and confirm all pass.

### Task 2: Active execution projection and rendering

**Files:**
- Modify: `src/windows_solver/progress_output.py`
- Test: `tests/test_campaign_reports.py`

**Interfaces:**
- Consumes: existing event context plus `WORKER_HEARTBEAT`.
- Produces: `CURRENTLY EXECUTING` and `LIVE ROOT SOLVE` dashboard lines.

- [ ] Write reporter tests for simultaneous completed/live panels, pending branch evidence, active suboperation, promotion reason, tier elapsed time, and heartbeat redraw.
- [ ] Run the focused test and observe failure because the live sections do not exist.
- [ ] Track precision-stage start and last non-heartbeat activity, derive promotion reason from the last committed stage, and render the two live sections.
- [ ] Run report/backend tests, Python compilation, and whitespace validation.
- [ ] Review the exact diff and publish it to a new draft PR based on live `main`.
