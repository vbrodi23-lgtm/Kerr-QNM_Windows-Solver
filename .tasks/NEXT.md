# Next

## TASK-075: Build the self-originating scientific runtime and public GSN backend
**Priority:** P0 | **Tags:** M02, architecture, bootstrap, provider, validation
**Assignee:** Unassigned | **Estimate:** 3–5 days | **Milestone:** M02

### Objective

Make every M02 numerical prerequisite reproducible from a fresh checkout and pinned public inputs, with no preinstalled scientific runtime, hidden cache, or manual dependency discovery.

### Acceptance Criteria

- [ ] Put the existing package-local CPython tier and a package-local Julia tier behind one solver-owned runtime policy that pins OS/architecture, exact tool and interpreter versions, download URLs, cryptographic digests, environment paths, and supported cold/warm behavior; require neither administrator rights nor system Python/Julia.
- [ ] Pin exact source commits for `GeneralizedSasakiNakamura.jl` and its Julia `SpinWeightedSpheroidalHarmonics.jl` dependency, including licences, `Project.toml`, `Manifest.toml`, source digests, and a deterministic acquisition or vendoring procedure.
- [ ] Implement a solver-owned generation stage and adapter that derive the required infinity-series, radial, and angular quantities from those pinned sources in binary64 and `BigFloat` 80/120-digit modes; generated artifacts must be reproducible outputs, never undeclared inputs.
- [ ] Make runtime downloads, source trees, Julia depots, package environments, and generated scientific artifacts content-addressed and self-validating: a cold start obtains or generates them, a warm start reuses only verified identities, and corruption or policy drift forces rejection or regeneration.
- [ ] Start a structured provenance ledger before provisioning and record every download URL, checksum/signature decision, command, executable/version, source commit, project identity, numerical policy, generated artifact, and SHA-256 result needed to reconstruct a run.
- [ ] Seal the same runtime, source, environment, numerical-policy, and generated-artifact identities into every campaign checkpoint; reject branch-head drift, unpinned packages, incompatible cached artifacts, and cross-run identity substitution.
- [ ] Keep the Black Hole Perturbation Toolkit Mathematica spheroidal repository as an independently pinned validation source, not a runtime dependency or competing production owner.
- [ ] Remove every operational requirement to search old Downloads folders or possess a historic private cache; preserve an old cache only as a non-authoritative comparator fixture when its exact receipt is available.
- [ ] Pass focused adapter, precision, provenance, tamper, licence, package-local bootstrap, cold/warm cache, and non-scientific preflight tests on supported CI platforms.

### Dependencies

- **Blocked by:** TASK-011
- **Blocks:** TASK-076

### Evidence Output

Pinned runtime/source policy, reproducible Julia environment, solver-owned generation/adapter boundary, cold/warm content-addressed caches, complete provisioning ledger, and binary64/BigFloat validation fixtures.

### Verification

- `python .tasks/validate_board.py`
- Focused public-backend, runtime-bootstrap, cold/warm reuse, precision, provenance, and tamper tests.
- Full Python test suite, release-manifest validation, wheel-content inspection, and PowerShell parser checks.

### Review Focus

Confirm that a fresh checkout can originate every M02 numerical prerequisite from declared public inputs, all reusable state is identity-checked, the Julia angular authority is singular, Mathematica remains validation-only, and no historic cache is silently trusted.

### Plan

- Freeze the runtime/source policy and package-local filesystem boundary.
- Build the generation/adapter path with binary64 and BigFloat execution.
- Prove cold creation, warm verified reuse, provenance closure, tamper rejection, and packaging before campaign execution.

---
