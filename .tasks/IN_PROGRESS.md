# In Progress

## TASK-075: Build the self-originating scientific runtime and public GSN backend
**Priority:** P0 | **Tags:** M02, architecture, bootstrap, provider, validation
**Assignee:** Unassigned | **Estimate:** 3–5 days | **Milestone:** M02

### Objective

Make every M02 numerical prerequisite executable from a fresh checkout and declared repository inputs, with no preinstalled scientific runtime, hidden cache, external precision plugin, or manual dependency discovery.

### Current Status

Implementation through PR #40 is merged on `main`. Ten of eleven acceptance
criteria have repository and CI evidence. Closure remains blocked only by the
absent immutable receipt for the Black Hole Perturbation Toolkit Mathematica
spheroidal validation source. Native cold/warm execution evidence belongs to
TASK-076 and is not being claimed by this task.

### Acceptance Criteria

- [x] Put the existing CPython tier and a solver-owned Julia 1.10.11 tier behind one runtime policy, using a per-user managed root by default and an explicit checkout-local portable mode; require neither administrator rights nor system Python/Julia.
- [x] Vendor the GSN and spheroidal source packages, licences, Julia project, and seed manifest at stable repository-relative paths; validate required paths and package loading before execution.
- [x] Implement solver-owned F/U generation plus binary64 and `BigFloat` 80/120-digit adapters; generated scientific artifacts must be declared outputs, never historic external inputs.
- [x] Index one resolved `(a,m)` record per short artifact ID using spin weight, exact rational spin where available, the exact integer-ratio representation of a κ-derived campaign binary64 spin, normalization, equation convention, and producer/consumer contract versions; retain originating exact `M−κ` coordinates as metadata.
- [x] Validate every reused coefficient artifact and producer status structurally; regenerate missing or invalid pairs independently under the same indexed ID, serialize concurrent allocation, write the index atomically, and preserve one previous index.
- [x] Record runtime, source, manifest, worker, and generated-artifact SHA-256 values as observations without making evolving scientific bytes a development execution gate.
- [x] Preserve existing campaign checkpoint/resume, signed reduction, full validation, and admission behavior across binary64, 80-digit, and 120-digit stages.
- [ ] Keep the Black Hole Perturbation Toolkit Mathematica spheroidal repository as an independently pinned validation source, not a runtime dependency or competing production owner.
- [x] Remove every operational requirement to search old Downloads folders or possess a historic private cache; preserve an old cache only as a non-authoritative comparator fixture when its exact receipt is available.
- [x] Expose one PowerShell command that bootstraps, runs or resumes all 212 leaves, and performs full checkpoint validation; include a clean runtime rebuild option.
- [x] Pass focused adapter, precision, tamper, licence, managed/portable bootstrap, pair reuse, PowerShell parser, package-build, and non-scientific preflight tests on supported CI platforms.

### Dependencies

- **Blocked by:** TASK-011
- **Blocks:** TASK-076

### Evidence Output

Declared runtime/source policy, solver-owned managed Julia environment,
solver-owned generation/adapter boundary, pair-level GSN index, complete
runtime observations, binary64/BigFloat validation fixtures, and a full
PowerShell campaign launcher.

### Verification

- `python .tasks/validate_board.py`
- Focused public-backend, runtime-bootstrap, cold/warm reuse, precision, provenance, and tamper tests.
- Full Python test suite, release-manifest validation, wheel-content inspection, and PowerShell parser checks.
- GitHub Actions run `31640576550` passed on PR #40's exact final head on
  Ubuntu and Windows: 471 tests plus the 11-test follow-on gate, wheel
  inspection, compilation, admission/cache, campaign smoke, provider checks,
  and Windows launcher parity.

### Review Focus

Confirm the missing Mathematica validation source is pinned by immutable source
identity and licence without entering runtime dependency closure or becoming a
production owner. Preserve the already-merged runtime, campaign, evidence, and
numerical contracts while closing that receipt-only gap.

### Plan

- Preserve the solver-owned runtime, generated-pair registry, promoted
  precision, checkpoint/cache, progress, determinant, and ODE behavior merged
  through PR #40.
- Add an immutable source-and-licence receipt for the independent Black Hole
  Perturbation Toolkit Mathematica spheroidal validation repository.
- Prove that receipt is validation-only and absent from runtime/provider
  dependency closure.
- After that focused evidence passes, move TASK-075 to Done and promote
  TASK-076 to Next for native cold/warm execution proof.

---
