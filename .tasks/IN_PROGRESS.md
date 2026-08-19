# In Progress

## TASK-079: Regularise promoted GSN propagation and determinant conditioning
**Priority:** P0 | **Tags:** M02, architecture, physics, validation
**Assignee:** Codex | **Estimate:** implementation plus native validation | **Milestone:** M02

### Objective

Replace the promoted raw homogeneous/scattering path with branch-factored GSN
propagation, typed batch asymptotics, scaled horizon-basis extraction, and the
safe `Cinc/Cref − R` determinant chart so Leaf 13 cost and precision decisions
track the regular remainder rather than an enormous carrier normalisation.

### Acceptance Criteria

- [ ] Make the vendored GSN package the sole production owner of the factored homogeneous equation, carrier transformations, and endpoint solves while preserving the existing contour, ODE algorithm, tolerances, endpoint order, derivative step, trust policy, and resource containment; encode the canonical tortoise/contour choice as a first-class versioned branch convention sourced only by `Coordinates.jl`, and encode `X=Aknown·Y` as an explicit regular-remainder contract.
- [ ] Replace precision-losing global asymptotic caches with request-local `Complex{T}` batch series keyed by precision bits, Horner production evaluation, forward and alternate compensated comparisons, and recurrence/series/last-term cancellation evidence.
- [ ] Run an asymptotic-conditioning preflight before any homogeneous RHS evaluation and return `INSUFFICIENT_ASYMPTOTIC_PRECISION` early when the requested tier cannot supply the required reliable digits.
- [ ] Extract `Cref` and `Cinc` through an independently column-scaled factored 2×2 horizon basis solve, undo scaling exactly, record matching reconstruction residual, enforce a fixed chart-safety factor, and retain the raw determinant only as diagnostic evidence.
- [ ] Route horizon and exterior promoted branches through the canonical factored package path and expose typed determinant/conditioning evidence without changing the short real-r compact-support integration.
- [ ] Version and strictly validate the Julia request/response/cache identity; persist conditioning evidence through root readouts, promotion decisions, progress, reports, and runtime/source receipts.
- [ ] Add a load-bearing equivalence matrix and static/mocked contracts for raw↔factored initial states, three-branch endpoint regularity under binary64/BigFloat, low-order explicit↔recurrence coefficients, per-order↔batch coefficients, BigFloat precision preservation, Cramer↔scaled extraction, synthetic independently scaled basis recovery/reconstruction, raw↔normalised determinants, schema closure, persistence, promotion, and source ownership.
- [ ] Preserve an explicit failing review boundary for a small independently generated high-precision GSN reference fixture; do not fabricate reference values from the implementation under test.
- [ ] Preserve a fail-loud mathematical-claim/release gate for human review of carrier signs, `Cref`/`Cinc` column order, horizon normalisation, and the `Cinc/Cref − R` chart, while allowing the promoted numerical path to execute and emit explicitly unapproved evidence for that review.
- [ ] Obtain native PowerShell evidence for the promoted Leaf 13 readout before claiming mathematical or performance validation.

### Dependencies

- **Blocked by:** none for implementation; human math review and native execution for closure
- **Blocks:** TASK-076

### Evidence Output

Factored GSN source and strict cross-language contracts, lightweight algebraic
and static test evidence, explicit unapproved mathematical-claim gate, and the exact
PowerShell command/log requirements for native Leaf 13 validation.

### Verification

- `python .tasks/validate_board.py`
- Focused static and mocked Python tests that do not launch Julia, Kerr solves, or PowerShell.
- Vendored Julia algebraic/unit tests run under pinned Julia 1.10.11 in hosted CI; the Leaf 13 promoted readout remains operator-native evidence.

### Review Focus

Check the transformed equation, complex-contour tangent, branch-specific
carrier signs, absence of a duplicate horizon power, `Cref`/`Cinc` basis order,
chart-safety estimate, analytic determinant normalisation, BigFloat type
preservation, and cache/provenance separation from historical raw-state leaves.

### Plan

- Repair PR #55 under the air-gapped architecture plan at
  `docs/superpowers/plans/2026-08-19-m02-promoted-response-architecture-repair.md`:
  add semantic precision tiers, provenance-bound uncertainty disks, adaptive
  endpoint/error-budget policies, and an atomic per-work-unit journal before
  changing promoted execution routing.
- Replace promoted exterior perturbed-root production with an authenticated
  baseline plus fixed-root determinant derivative and selected validation;
  restrict the full complex ladder to explicit validation reasons.
- Bound analytic promoted-horizon responses through explicit p_H and D′ disks;
  make unbounded/zero-containing evidence unusable by projective reduction.
- Complete adaptive horizon depth/order/best-prefix search and low-signal
  window backtracking, then add selective readout promotion, immutable
  checkpoint migration, targeted operator scripts, and an engineering note.
- Preserve the package-owned factored GSN determinant, contour, carrier, branch,
  conditioning, and naturally available determinant-error telemetry unchanged.
- Apply the operator-validated promoted-readout policy identity
  `binary64-parity-primary-fixed-root-diagnostics/v1`: PRIMARY accepts exactly
  when raw `|D / Dprime| <= 2e-11`, retains complex `Dprime`, and performs no
  determinant evaluation after Newton convergence.
- Hold the accepted PRIMARY frequency fixed for TRUNCATION and RESOLUTION,
  reuse complex `Dprime`, evaluate exactly one determinant in each phase, add
  eight endpoint-series orders only for TRUNCATION, and halve only homogeneous
  ODE relative/absolute tolerances for RESOLUTION.
- Omit routine SEED-PATH work explicitly with required/executed flags and a
  zero determinant count; do not synthesize an independent solve or radius.
- Version the worker response and response receipt, and strictly bind the
  changed request/runtime, root-readout-cache, solved-leaf-cache, convergence,
  and uncertainty identities so incompatible evidence is stale rather than
  reused.
- Prove determinant budgets, fixed-root invariance, raw acceptance, control
  isolation, schema honesty, cache invalidation, and final convergence using
  static/parser/mocked/unit tests only. Do not execute Julia, Kerr determinants,
  ODE benchmarks, Leaf 13, or the 212-leaf campaign; native mathematical and
  performance validation is the operator's successful Leaf 13 v1.4 receipt.
- Replace the outer promoted PRIMARY horizon component multiplier with one
  zero-amplitude Julia root readout, using the immediately preceding baseline
  omega as its root predictor, then derive the response from the retained
  complex PRIMARY derivative without signed-amplitude or self-refinement work.
- Bind the new `single-promoted-root-analytic-horizon-component/v1` identity,
  represent all unmeasured response-uncertainty channels as non-applicable,
  keep admission fail-closed as `UNCALIBRATED_ANALYTIC_RESPONSE`, and migrate
  authenticated predecessor checkpoints by retaining canonical binary64 stages
  while dropping old promoted horizon multi-readout stages.

### Work Log

- 2026-08-19 — Task 3 recovery implementation completed under the strict
  air-gap: adaptive two-endpoint horizon search, cap-reused outer endpoint
  selection, exhaustive safe-window backtracking/selective semantic-tier
  promotion, request-bound ODE-budget controls with the exact missing-math
  blocker, partial-component resume journal, immutable checkpoint migration,
  two operator-only PowerShell entry points, and the engineering note. Focused
  synthetic/static tests pass; no Julia, Kerr determinant, ODE/angular/QNM
  solve, M02 campaign, or PowerShell script was executed. TASK-079 remains In
  Progress pending human math review and native operator evidence.
- 2026-08-19 — Final P1 remediation keeps TASK-079 open while making
  `HORIZON_ARITHMETIC_INADEQUATE` the only endpoint outcome that promotes,
  versioning the live checkpoint as schema 8 with schema-7 historical parsing,
  migrating real authenticated campaign records to a normal resumable
  destination with a provenance sidecar, binding current horizon-v2 and
  fixed-root exterior scientific contracts, searching all deterministic Julia
  prefixes to each maximum order, and making the light-ring stop/resume branch
  wait for the process tree and cold-start when no checkpoint exists. Full safe
  Python discovery passed 885 tests with 7 skips; native/human evidence remains
  outstanding and the task was not moved to Done.

---
