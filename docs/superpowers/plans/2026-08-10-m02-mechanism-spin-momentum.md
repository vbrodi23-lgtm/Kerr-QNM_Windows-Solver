# M02 Mechanism-Local Traversal and Spin Momentum Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Execute the unchanged 212-leaf campaign mechanism-first and use only same-chain accepted responses to seed the next higher-spin coordinate's PRIMARY solves.

**Architecture:** Keep authenticated plan/selection ordering as the scientific and persistence order. Derive a separate execution schedule, store sparse partial records canonically by leaf ID, and pass one invocation-local response predictor through the existing component/root-readout boundary.

**Tech Stack:** Python 3.11+, `unittest`, Julia worker request adapter, canonical JSON checkpoints.

## Global Constraints

- Do not change leaf IDs, domain membership, campaign/selection identities, scientific-computation identities, response jobs, numerical policy, acceptance, uncertainty, reducer logic, or thresholds.
- Every leaf remains anchored to its own authenticated background root.
- Cross-spin continuation is restricted to identical role, mode, mechanism, and coordinate role.
- SEED-PATH remains independent.
- Do not add determinant preflight comparisons.
- Run static/Python tests only; the user runs the Windows campaign.

---

### Task 1: Mechanism-local execution schedule and sparse resume

**Files:**
- Modify: `src/windows_solver/response_batches.py`
- Test: `tests/test_linear_response_batches.py`

**Interfaces:**
- Produces: `_campaign_execution_leaf_ids(plan, selection) -> tuple[str, ...]`
- Preserves: `CampaignPlan.leaves`, `CampaignSelection.leaf_ids`, checkpoint bindings, and canonical record serialization.

- [ ] Write a test with literal expected tuples proving mechanism order, mode order, and ascending physical spin (`.95 → .99 → .999 → .9999`; deep Mκ `.01 → .002 → .001`).
- [ ] Run the focused test and confirm it fails on the old mode/spin/mechanism traversal.
- [ ] Add the deterministic execution-key function without changing plan or selection construction.
- [ ] Add a test loading an old canonical-prefix checkpoint, executing the next scheduled non-prefix leaf, and validating the resulting canonical sparse subset.
- [ ] Run it red, then index active records by leaf ID and serialize selected subsets in canonical order.
- [ ] Keep duplicate, off-domain, noncanonical record order, digest, lineage, and semantic validation fail-closed.
- [ ] Run the focused batch tests green and commit.

### Task 2: Same-chain response continuation

**Files:**
- Modify: `src/windows_solver/response_batches.py`
- Modify: `src/windows_solver/response_engine.py`
- Test: `tests/test_linear_response_batches.py`
- Test: `tests/test_linear_response_provider.py`

**Interfaces:**
- Produces: `run_component(job, backend, response_predictor=None)`.
- Predictor formula: `job.root.omega + amplitude * response_predictor` for the first readout on each signed ray only.

- [ ] Write a component test proving the four coarse signed rays receive the new-background-root plus signed-amplitude displacement, while baseline receives no predictor and finer rays retain epsilon continuation.
- [ ] Run it red, then add the minimal optional response-predictor argument and finite validation.
- [ ] Write a campaign test proving a reused `PRODUCED` previous coordinate seeds only the next leaf in the same role/mode/mechanism/coordinate-role chain.
- [ ] Add negative cases proving no mode, mechanism, role, direct/Mκ, unresolved, or gapped carry-over.
- [ ] Run red, then maintain invocation-local chain state from authenticated `ComponentResult.response` values.
- [ ] Run focused component and campaign tests green and commit.

### Task 3: Binary64/Julia seed telemetry parity

**Files:**
- Modify: `src/windows_solver/response_engine.py`
- Modify: `src/windows_solver/native_response_kernel.py`
- Modify: `src/windows_solver/julia_response_backend.py`
- Modify: `src/windows_solver/data/julia/m02_worker.jl`
- Modify: `src/windows_solver/response_batches.py`
- Test: `tests/test_native_progress.py`
- Test: `tests/test_julia_response_backend.py`
- Test: `tests/test_native_campaign_backend.py`

**Interfaces:**
- Adds optional execution-only `primary_predictor_kind` with admitted values `EPSILON_CONTINUATION` and `SPIN_CONTINUATION`.
- Scientific `RootReadout`, `ComponentResult`, and checkpoint mappings remain unchanged.

- [ ] Write red tests proving the first coarse spin-predicted PRIMARY emits `SPIN_CONTINUATION`, finer rays emit `EPSILON_CONTINUATION`, and fallback reports the requested kind plus `FALLBACK_BACKGROUND`.
- [ ] Thread the optional kind through native and Julia request boundaries without adding numerical work.
- [ ] Update the Julia worker's static request flattening and seed label selection; do not execute Julia.
- [ ] Prove TRUNCATION/RESOLUTION remain `ACCEPTED_PRIMARY` and SEED-PATH remains `INDEPENDENT_SEED_PATH`.
- [ ] Run focused telemetry/backend tests green and commit.

### Task 4: Compatibility and repository proof

**Files:**
- Modify: `.tasks/IN_PROGRESS.md`
- Test: existing cache, checkpoint, progress, provider, backend, and report suites.

**Interfaces:**
- Preserves the historical scientific-computation identity fixture and all report projections.

- [ ] Add the traversal/cross-spin slice to TASK-075's active plan.
- [ ] Run the focused suites for batches, solved cache, response provider, native progress, Julia request contracts, native campaign backend, and campaign reports.
- [ ] Run `python -m compileall -q src tests`, `python .tasks/validate_board.py`, and the full Python `unittest` suite.
- [ ] Inspect the diff for protected-file, identity, SEED-PATH, determinant-preflight, and domain changes.
- [ ] Commit the final proof and hand off for change review and draft PR publication.
