# Next

## TASK-075: Integrate the reproducible public GSN backend and Julia runtime
**Priority:** P0 | **Tags:** M02, architecture, provider, validation
**Assignee:** Unassigned | **Estimate:** 1–2 days | **Milestone:** M02

### Objective

Replace the historic fixed-cache dependency with a reproducible, pinned public GSN calculation path that the packaged Windows solver can provision and execute.

### Acceptance Criteria

- [ ] Provision a package-local Julia runtime without administrator rights and pin exact source commits for `GeneralizedSasakiNakamura.jl` and its Julia `SpinWeightedSpheroidalHarmonics.jl` dependency, including licences, `Project.toml`, `Manifest.toml`, and source digests.
- [ ] Implement one solver-owned adapter that evaluates the required radial/angular quantities in binary64 and `BigFloat` 80/120-digit modes and either generates the infinity-series artifact or supplies the same values directly to the response kernel.
- [ ] Seal backend commit, environment, numerical policy, generated artifact, and SHA-256 identities into every campaign checkpoint; reject branch-head drift, unpinned packages, and incompatible cached artifacts.
- [ ] Keep the Black Hole Perturbation Toolkit Mathematica spheroidal repository as an independently pinned validation source, not a runtime dependency or competing production owner.
- [ ] Remove every operational requirement to search old Downloads folders or possess a historic private cache; preserve the old cache only as a comparator fixture when its exact receipt is available.
- [ ] Pass focused adapter, precision, provenance, tamper, licence, and package-local bootstrap tests on supported CI platforms.

### Dependencies

- **Blocked by:** TASK-011
- **Blocks:** TASK-076

### Evidence Output

Pinned upstream-source receipt, reproducible Julia environment, GSN adapter, generated-cache/direct-evaluation contract, and binary64/BigFloat validation fixtures.

### Verification

- `python .tasks/validate_board.py`
- Focused public-backend, runtime-bootstrap, precision, provenance, and tamper tests.
- Full Python test suite, release-manifest validation, wheel-content inspection, and PowerShell parser checks.

### Review Focus

Confirm that every numerical byte is reproducible from pinned public sources, the Julia angular authority is singular, Mathematica remains validation-only, and no historic cache is silently trusted.

### Plan

- Pin and receipt the public radial/angular sources and package-local Julia environment.
- Build the adapter and generated-artifact boundary with binary64 and BigFloat paths.
- Prove provenance, tamper rejection, packaging, and clean bootstrap behavior before campaign execution.

---
