# In Progress

## TASK-075: Build the self-originating scientific runtime and public GSN backend
**Priority:** P0 | **Tags:** M02, architecture, bootstrap, provider, validation
**Assignee:** Unassigned | **Estimate:** 3–5 days | **Milestone:** M02

### Objective

Make every M02 numerical prerequisite executable from a fresh checkout and declared repository inputs, with no preinstalled scientific runtime, hidden cache, external precision plugin, or manual dependency discovery.

### Acceptance Criteria

- [ ] Put the existing package-local CPython tier and a package-local Julia 1.10.11 tier behind one solver-owned runtime policy; require neither administrator rights nor system Python/Julia.
- [ ] Vendor the GSN and spheroidal source packages, licences, Julia project, and seed manifest at stable repository-relative paths; validate required paths and package loading before execution.
- [ ] Implement solver-owned F/U generation plus binary64 and `BigFloat` 80/120-digit adapters; generated scientific artifacts must be declared outputs, never historic external inputs.
- [ ] Index one resolved `(a,m)` record per short artifact ID using spin weight, exact rational spin where available, the exact integer-ratio representation of a κ-derived campaign binary64 spin, normalization, equation convention, and producer/consumer contract versions; retain originating exact `M−κ` coordinates as metadata.
- [ ] Validate every reused coefficient artifact and producer status structurally; regenerate missing or invalid pairs independently under the same indexed ID, serialize concurrent allocation, write the index atomically, and preserve one previous index.
- [ ] Record runtime, source, manifest, worker, and generated-artifact SHA-256 values as observations without making evolving scientific bytes a development execution gate.
- [ ] Preserve existing campaign checkpoint/resume, signed reduction, full validation, and admission behavior across binary64, 80-digit, and 120-digit stages.
- [ ] Keep the Black Hole Perturbation Toolkit Mathematica spheroidal repository as an independently pinned validation source, not a runtime dependency or competing production owner.
- [ ] Remove every operational requirement to search old Downloads folders or possess a historic private cache; preserve an old cache only as a non-authoritative comparator fixture when its exact receipt is available.
- [ ] Expose one PowerShell command that bootstraps, runs or resumes all 553 leaves, and performs full checkpoint validation; include a clean runtime rebuild option.
- [ ] Pass focused adapter, precision, tamper, licence, package-local bootstrap, pair reuse, PowerShell parser, package-build, and non-scientific preflight tests on supported CI platforms.

### Dependencies

- **Blocked by:** TASK-011
- **Blocks:** TASK-076

### Evidence Output

Declared runtime/source policy, package-local Julia environment, solver-owned generation/adapter boundary, pair-level GSN index, complete runtime observations, binary64/BigFloat validation fixtures, and a full PowerShell campaign launcher.

### Verification

- `python .tasks/validate_board.py`
- Focused public-backend, runtime-bootstrap, cold/warm reuse, precision, provenance, and tamper tests.
- Full Python test suite, release-manifest validation, wheel-content inspection, and PowerShell parser checks.

### Review Focus

Confirm that a fresh checkout can originate every M02 numerical prerequisite from declared repository inputs, all reusable pair records are structurally and mathematically identity-checked, Julia remains the promoted-precision authority, Mathematica remains validation-only, and no historic cache is silently trusted.

### Plan

- Replace the fixed-cache `campaign-run` boundary with the package-local Julia F/U cache producer.
- Index and validate one exact pair record at a time, then assemble the records selected by the campaign for the existing `StandardSN` consumer.
- Route package-owned Julia 80/120-digit root readouts through the existing campaign stage and evidence contracts.
- Launch all 553 leaves from `m02.ps1`; the user supplies the physical Windows execution evidence and failure logs.
- Add out-of-band quiet/normal/trace inner-leaf progress while preserving scientific execution and checkpoint/evidence bytes.
- Bind `m02.ps1` bootstrap switches as actual PowerShell parameters, and prove the boundary with a mocked Windows bootstrap invocation.

---
