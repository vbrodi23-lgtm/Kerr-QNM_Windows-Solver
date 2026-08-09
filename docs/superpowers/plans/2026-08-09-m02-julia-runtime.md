# M02 Package-Local Julia Runtime Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the full 553-leaf M02 campaign runnable and resumable from one PowerShell entry point without undeclared scientific inputs.

**Architecture:** A package-local Julia producer owns exact F/U generation, a pair-level runtime index owns reusable coefficient identity, and an assembled validated cache feeds the existing binary64 consumer. A package-local Julia root worker implements promoted precision behind the existing campaign backend interface, leaving checkpoint, reduction, and admission ownership unchanged.

**Tech Stack:** Python 3.12, Windows PowerShell 5.1, Julia 1.10.11, `GeneralizedSasakiNakamura.jl`, `SpinWeightedSpheroidalHarmonics.jl`, DifferentialEquations, JSON.

## Global Constraints

- Do not execute the Julia producer or physical determinant in the developer environment.
- Keep implementation commits visible on draft PR #8 while work proceeds.
- Use short pair artifact filenames; keep scientific identity in `gsn-index.json`.
- Treat measured scientific-source and artifact hashes as observations during development.
- Preserve the 553-leaf checkpoint, resume, reduction, and admission contracts.
- Keep all generated runtime state below `.runtime` and all campaign checkpoints outside it.

---

### Task 1: Pair-Level F/U Registry

**Files:**
- Modify: `src/windows_solver/gsn_cache_producer.py`
- Modify: `src/windows_solver/data/julia/generate_gsn_cache.jl`
- Test: `tests/test_gsn_cache_producer.py`

**Interfaces:**
- Consumes: `GsnParameterPair` values derived from campaign leaves.
- Produces: `ensure_generated_gsn_cache(...) -> GeneratedGsnCache` with validated pair artifact IDs and an assembled consumer path.

- [x] **Step 1: Write failing pair-identity and reuse tests**
- [x] **Step 2: Confirm failures against the selection-bundle implementation**
- [x] **Step 3: Implement exact identities, pair artifacts, atomic index writes, locking, and independent regeneration**
- [x] **Step 4: Run `PYTHONPATH=src python -m unittest tests.test_gsn_cache_producer` and confirm all cases pass**
- [x] **Step 5: Commit and publish the pair-registry slice to PR #8**
- [x] **Step 6: Correct and regression-test the exact `Mκ` to binary64 `a/M` bridge used by near-extremal leaves**

### Task 2: Package-Local Promoted Precision

**Files:**
- Create: `src/windows_solver/data/julia/m02_worker.jl`
- Create: `src/windows_solver/julia_response_backend.py`
- Modify: `src/windows_solver/response_batches.py`
- Test: `tests/test_julia_response_backend.py`
- Test: `tests/test_native_campaign_backend.py`

**Interfaces:**
- Consumes: an existing `ResponseComponentJob`, numerical policy, and authenticated prior stage outcomes.
- Produces: `RootReadout`-compatible promoted results with truncation, resolution, alternate-seed, and precision-ladder evidence.

- [x] **Step 1: Write failing adapter and promoted-stage contract tests**
- [x] **Step 2: Confirm the native backend rejects unavailable promoted precision**
- [x] **Step 3: Implement the Julia request/response adapter and root worker**
- [x] **Step 4: Route 80/120-digit outcomes through existing campaign and reduction code**
- [x] **Step 5: Run focused backend and precision-resume regression tests**
- [x] **Step 6: Commit and publish the precision slice to PR #8**

### Task 3: Windows Runtime and Full Campaign Launcher

**Files:**
- Modify: `runtime/bootstrap.ps1`
- Modify: `runtime/runtime_policy.json`
- Create: `examples/m02-campaign.json`
- Create: `m02.ps1`
- Modify: `pyproject.toml`
- Test: `tests/test_public_surface.py`
- Test: `tests/test_linear_response_batches.py`

**Interfaces:**
- Consumes: repository-relative package data and a campaign checkpoint path.
- Produces: a bootstrapped package-local runtime and a complete or resumable 553-leaf checkpoint.

- [x] **Step 1: Write surface tests for package-local Julia, full selection, resume, full validation, and clean rebuild**
- [x] **Step 2: Implement Julia provisioning and package-load probe without scientific execution**
- [x] **Step 3: Add the all-leaf 64/80/120 selection and `m02.ps1` launcher**
- [x] **Step 4: Verify `campaign-plan` materializes exactly 553 selected leaves**
- [ ] **Step 5: Parse the PowerShell scripts on a Windows CI runner**
- [ ] **Step 6: Commit and publish the final operator-surface slice to PR #8**

### Task 4: Handoff and Repair Loop

**Files:**
- Modify: `README.md`
- Modify: `docs/response-replay-powershell.md`
- Modify: `.tasks/IN_PROGRESS.md`

**Interfaces:**
- Consumes: verified developer-side source and CI results.
- Produces: the exact Windows command and diagnostic expectations for the user execution environment.

- [x] **Step 1: Document `.\m02.ps1`, pair-level cache behavior, and `.\m02.ps1 -RebuildRuntime`**
- [ ] **Step 2: Run the complete non-scientific Python, package-data, board, and package-build gates**
- [ ] **Step 3: Update draft PR #8 with current verification and execution boundary**
- [ ] **Step 4: Record the handoff state in Notion**
- [ ] **Step 5: Ask the user to run `.\m02.ps1` and return the first failing log if execution stops**
