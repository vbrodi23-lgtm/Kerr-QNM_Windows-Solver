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
- [ ] Preserve a fail-loud production-activation gate for human review of carrier signs, `Cref`/`Cinc` column order, horizon normalisation, and the `Cinc/Cref − R` chart.
- [ ] Obtain native PowerShell evidence for the promoted Leaf 13 readout before claiming mathematical or performance validation.

### Dependencies

- **Blocked by:** none for implementation; human math review and native execution for closure
- **Blocks:** TASK-076

### Evidence Output

Factored GSN source and strict cross-language contracts, lightweight algebraic
and static test evidence, explicit unactivated math-review gate, and the exact
PowerShell command/log requirements for native Leaf 13 validation.

### Verification

- `python .tasks/validate_board.py`
- Focused static and mocked Python tests that do not launch Julia, Kerr solves, or PowerShell.
- Julia algebraic/unit tests and the Leaf 13 promoted readout are execution-airgapped to the operator.

### Review Focus

Check the transformed equation, complex-contour tangent, branch-specific
carrier signs, absence of a duplicate horizon power, `Cref`/`Cinc` basis order,
chart-safety estimate, analytic determinant normalisation, BigFloat type
preservation, and cache/provenance separation from historical raw-state leaves.

### Plan

- Implement representation primitives and precision-preserving asymptotics in the vendored GSN package, with tests written before production changes.
- Move promoted horizon and exterior orchestration onto the canonical factored endpoint solver and scaled coefficient extraction.
- Propagate conditioning evidence through strict Julia/Python schemas, promotion policy, progress, reports, and runtime identity.
- Run a time-boxed, performance-only Leaf 13 diagnostic through the existing post-readiness factored executor, measuring the outer-to-match and match-to-inner legs separately before any further hardening.
- Run only permitted static/mocked checks, independently review the diff, then stop for human math review and native PowerShell execution.

---
