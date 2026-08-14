# Horizon Basis at Match Prototype Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> `superpowers:executing-plans` to implement this plan task-by-task.

**Goal:** Obtain decisive native evidence for a pure horizon-basis-at-match
representation without modifying or activating the production determinant
path.

**Architecture:** Reuse the existing Leaf 13 benchmark harness for the outer
leg and telemetry.  Add a standalone Julia prototype that constructs a real
inner tortoise ray, authenticates the two horizon series, propagates each
regular remainder to the match point, and performs an independently scaled
two-column connection solve there.

**Tech Stack:** Julia 1.10.11, DifferentialEquations/SciML, vendored
GeneralizedSasakiNakamura package, BigFloat at 298 bits.

## Constraints

- Keep the production readiness assertion closed and production worker code
  unchanged.
- Bypass readiness only inside the explicitly performance-only prototype.
- Do not alter schemas, cache identities, promotion policy, or determinant
  activation receipts.
- Fail before a horizon RHS evaluation if geometry or asymptotic conditioning
  is inadequate.

### Task 1: Red prototype contracts

**Files:**
- Create: `src/windows_solver/data/julia/horizon_basis_at_match_prototype_spec.jl`

- [x] Pin the physical-state carrier/factor round trip for a non-aligned real
  tangent.
- [x] Pin independent column scaling and exact coefficient recovery at the
  match point.
- [x] Pin fail-closed radial-approach and preflight predicates.
- [x] Run the focused spec and observe the missing prototype API failures.

### Task 2: Prototype implementation

**Files:**
- Create: `tools/benchmark_leaf13_horizon_basis_at_match.jl`

- [x] Build and verify the real inner radial map.
- [x] Select the nearest endpoint that passes both horizon preflights.
- [x] Build explicit-tangent carriers and pure horizon remainder seeds.
- [x] Propagate ingoing and outgoing branches independently to `rho=0` with
  production algorithm/tolerances and endpoint-only saves.
- [x] Convert the outer result into the real-inner match coordinate, solve the
  scaled basis, and emit bounded JSON evidence.

### Task 3: Native Leaf 13 decision run

**Files:**
- Create: `docs/engineering/2026-08-14-leaf13-horizon-basis-at-match.md`

- [x] Run the focused spec.
- [x] Run the full prototype at 298 bits.
- [x] Record per-leg cost, conditioning, reconstruction, verdict, and the
  performance-only claim ceiling.

### Task 4: Verification and delivery

**Files:**
- Modify: `.tasks/IN_PROGRESS.md`

- [x] Run the full vendored Julia suite, focused Python source contracts,
  TaskPlanner validation, and whitespace checks.
- [x] Review the diff for accidental production-path or policy changes.
- [x] Commit and push the prototype and evidence to PR #44.
