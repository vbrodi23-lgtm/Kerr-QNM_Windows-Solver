# PR #46 Horizon Detector Completion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> `superpowers:subagent-driven-development` to implement this plan task-by-task.

**Goal:** Complete PR #46 as one verified real-inner horizon-detector rewrite
whose geometry, determinant uncertainty, derivative authentication, policy,
identity, and receipts form one fail-closed contract.

**Architecture:** The vendored GSN package owns contour geometry, carriers,
pure horizon branches, and the scaled basis solve. The Julia worker owns the
three-leg workflow and root-authentication certificates. Python owns policy,
promotion, transport, persistence, and mechanism-scoped compatibility. CI and
the native calibration tools own executable evidence.

**Tech Stack:** Julia 1.10.11, DifferentialEquations/SciML, BigFloat,
Python 3.12, `unittest`, PowerShell 5.1/7, GitHub Actions.

## Global Constraints

- Work only on PR #46, based on main commit
  `53e04b4211166a8018fe3269af3d3f36c3b61167`.
- Preserve the short real-r compact-support exterior integration and exterior
  determinant behavior.
- The horizon graph is exactly three independent legs: infinity-outgoing to
  match, horizon-ingoing to match, horizon-outgoing to match. The outer leg is
  reused for endpoint verification.
- Select two verified horizon endpoints before starting any homogeneous ODE,
  including the outer Xup solve.
- Horizon geometry is assessed before either horizon series is evaluated.
- Root tolerances remain `1e-18` base and `1e-20` refinement at both 80 and
  120 decimal working digits.
- Coordinate, homogeneous GSN, and exterior perturbed-radial controls remain
  distinct policy classes.
- A horizon determinant always carries an absolute error certificate. Relative
  error in a near-zero determinant is never an acceptance variable.
- Basis condition, basis backward error, reconstruction residual, and carrier
  reconstruction errors remain separate gates; they are not added to the
  determinant error without a derived conversion.
- Production `evaluate_horizon_determinant` must not reference
  `solve_factored_xup_scattering_endpoint`, `Xup_match_to_inner`,
  `horizon_match_to_inner`, or `solve_factored_horizon_match_to_inner`.
- Existing legacy package APIs may remain only where required by untouched
  exterior or historical diagnostics; they must not be reachable from the
  production horizon evaluator.
- Old horizon receipts become stale. Exterior receipts remain compatible only
  after a main-generated compatibility fixture proves it.
- Do not begin the 212-leaf campaign. Execute only the bounded evidence gates
  listed in Task 5.
- Julia and PowerShell are unavailable in the current container. For Julia
  behavior, observe a local failing Python contract first and require the real
  Julia test in CI before accepting the slice. Native Leaf 13 evidence remains
  a separate gate and may not be inferred from static checks.

---

### Task 1: Verified Geometry Before Homogeneous Work

**Files:**
- Modify: `src/windows_solver/data/julia/GeneralizedSasakiNakamura.jl/src/Homogeneous/ComplexFrequencies.jl`
- Modify: `src/windows_solver/data/julia/GeneralizedSasakiNakamura.jl/test/real_inner_horizon_spec.jl`
- Modify: `src/windows_solver/data/julia/m02_worker.jl`
- Modify: `tests/test_regularised_gsn_worker_static.py`
- Modify: `tests/test_regularised_gsn_factored_propagation_static.py`

**Interfaces:**
- Produce `HorizonEndpointGeometryCandidate{T}` containing only rho, radius,
  horizon distance, imaginary drift, exterior/real-axis/approach/distance
  verdicts, and contour provenance.
- Produce `horizon_endpoint_geometry_candidates(spectral, contour;
  rho_candidates, maximum_horizon_distance)`.
- Change `horizon_endpoint_candidates` to consume only geometry candidates that
  pass the radial gate before evaluating the ingoing/outgoing series.
- Produce `CoordinateIdentityEvidence{T}` and
  `assert_coordinate_identity(...)`; nonfinite or excessive residual throws
  `COORDINATE_IDENTITY_MISMATCH` with complete diagnostics.

- [ ] Add a worker ordering test that fails because
  `solve_factored_xup_to_match` currently appears before
  `select_verified_horizon_endpoints`.
- [ ] Add a package behavior test proving an invalid geometry candidate cannot
  invoke horizon-series assessment, and a selector test proving the configured
  maximum distance is revalidated rather than trusted from a boolean field.
- [ ] Add a coordinate-identity contract test requiring finite max absolute and
  relative residuals, explicit tolerance fields, and a typed failure.
- [ ] Run the focused Python tests and preserve the expected red output.
- [ ] Split geometry screening from series preflight in the package.
- [ ] Replace telemetry-only `emit_coordinate_identity` with a function that
  validates, emits, returns evidence, and throws on failure.
- [ ] Reorder `evaluate_horizon_determinant` to build and verify the inner
  contour and endpoint pair before outer preparation or any homogeneous solve.
- [ ] Run the focused Python tests green; require
  `real_inner_horizon_spec.jl` in CI.
- [ ] Commit this slice.

### Task 2: Complete Determinant and Derivative Authentication

**Files:**
- Modify: `src/windows_solver/data/julia/m02_worker.jl`
- Modify: `src/windows_solver/data/julia/GeneralizedSasakiNakamura.jl/src/Homogeneous/Solutions.jl`
- Modify: `src/windows_solver/data/julia/GeneralizedSasakiNakamura.jl/test/scaled_scattering_spec.jl`
- Create: `src/windows_solver/data/julia/m02_worker_finite_difference_spec.jl`
- Modify: `tests/test_regularised_gsn_worker_static.py`
- Modify: `tests/test_julia_response_backend.py`

**Interfaces:**

```julia
struct DeterminantErrorBreakdown{T<:AbstractFloat}
    endpoint_disagreement_abs::T
    control_disagreement_abs::Union{Nothing,T}
    equivalence_disagreement_abs::Union{Nothing,T}
    precision_disagreement_abs::Union{Nothing,T}
    safety_factor::T
    numerical_error_abs::T
end

struct DerivativeAuthentication{T<:AbstractFloat}
    value::Complex{T}
    propagated_error_abs::T
    step_disagreement_abs::T
    lower_bound_abs::T
    step::T
    axis::String
end
```

- Use error model identity
  `verified-endpoint-control-equivalence-absolute-error/v2`. Add the precision
  component only when an exact same-frequency cross-precision evaluation is
  available.
- Each online Newton evaluation includes endpoint and absolute raw/normalised
  equivalence discrepancies.
- Final authentication re-evaluates the root and every accepted derivative
  stencil point with a bounded tight-control request and includes
  `|Dbase-Dtight|`.
- `finite_difference_pair` returns its actual propagated error. No caller may
  replace it with `root_error_abs / h`.

- [ ] Add failing tests for absolute raw/normalised equivalence, complete error
  breakdown validation, and safety-factor max aggregation.
- [ ] Add a failing derivative test where unequal errors at `omega+h` and
  `omega-h` distinguish the correct propagated value from central-root error.
- [ ] Add failing tests for finite positive step bounds satisfying
  `minimum <= nominal <= maximum`, bounded exhaustion, and best-iterate ranking
  by `|D| + etaD`.
- [ ] Run focused tests and preserve the expected red output.
- [ ] Implement the determinant breakdown and authenticated tight-control
  evaluator without recursively tightening diagnostic phases.
- [ ] Make `final_derivative` return value, diagnostics, and the actual stencil
  error; use those values for every `h/2`, `h`, `2h`, and `ih` estimate.
- [ ] Make Newton damping and best-iterate selection use residual upper bounds.
- [ ] Return a complete root authentication record: central complex determinant,
  error components, residual upper bound, derivative estimate, propagated
  error, step disagreement, lower bound, selected step, correction upper bound,
  and error-model identity.
- [ ] Run focused tests green and execute the Julia finite-difference spec in CI.
- [ ] Commit this slice.

### Task 3: Strict Cross-Language Certificate, Failure, and Progress Protocol

**Files:**
- Modify: `src/windows_solver/data/julia/m02_worker.jl`
- Modify: `src/windows_solver/julia_response_backend.py`
- Modify: `src/windows_solver/response_engine.py`
- Modify: `src/windows_solver/response_batches.py`
- Modify: `src/windows_solver/root_readout_cache.py`
- Modify: `src/windows_solver/campaign_reports.py`
- Modify: `src/windows_solver/progress.py`
- Modify: `src/windows_solver/progress_output.py`
- Modify: `src/windows_solver/contracts.py`
- Modify: `tests/fixtures.py`
- Modify: `tests/test_julia_response_backend.py`
- Modify: `tests/test_numerical_conditioning_contract.py`
- Modify: `tests/test_root_readout_cache.py`
- Modify: `tests/test_linear_response_precision.py`
- Modify: `tests/test_progress.py`
- Modify: `tests/test_campaign_reports.py`

**Interfaces:**
- Worker response schema becomes version 4.
- Add Python `DeterminantErrorEvidence` and `RootAuthenticationEvidence`
  immutable value types with strict closed-key mapping validation.
- Every typed numerical failure has `failure_code`, `stage`, and a
  `diagnostics` mapping. `COORDINATE_INVERSION_STALLED` must arrive as
  `JuliaNumericalControlError`, not generic `JuliaResponseBackendError`.
- The progress registry must parse and render every event emitted by Julia,
  including horizon endpoint, coordinate identity, determinant error, and
  frequency-step events.

- [ ] Add failing parser tests for all new worker fields, malformed/missing
  fields, nonnegative finite bounds, and internal bound consistency.
- [ ] Add a failing exact wire test for `COORDINATE_INVERSION_STALLED` from JSON
  through campaign classification.
- [ ] Add failing round-trip tests through `RootReadout`, diagnostic readouts,
  root-readout cache, solved-leaf material, and campaign report rows.
- [ ] Add a failing exhaustive progress test comparing Julia-emitted event names
  with parser and renderer coverage.
- [ ] Run focused tests and preserve the expected red output.
- [ ] Implement strict schema parsing and persistence; bump cache/checkpoint
  versions only where the stored shape changes.
- [ ] Normalize the Julia failure envelope and register/render all events from a
  single Python registry. Bind every CONTROL failure to the exact request,
  mechanism, precision policy, and error-model identity; do not special-case
  only asymptotic-preflight failures.
- [ ] Aggregate an optional same-frequency 80/120 discrepancy when both exact
  samples are present; never compare determinants evaluated at different roots.
- [ ] Delete the report-only `1e-102` 120-digit correction target. Reports must
  use the persisted request tolerance/certificate (`1e-18` base or `1e-20`
  refinement), never reconstruct policy from storage precision.
- [ ] Run focused tests green.
- [ ] Commit this slice.

### Task 4: Mechanism-Scoped Policy and Compatibility Identity

**Files:**
- Modify: `src/windows_solver/julia_response_backend.py`
- Modify: `src/windows_solver/response_engine.py`
- Modify: `src/windows_solver/response_batches.py`
- Modify: `src/windows_solver/root_readout_cache.py`
- Modify: `src/windows_solver/solved_leaf_cache.py`
- Modify: `tests/test_linear_response_precision.py`
- Modify: `tests/test_linear_response_batches.py`
- Modify: `tests/test_solved_leaf_cache.py`
- Modify: `tests/test_root_readout_cache.py`
- Modify: `tests/test_numerical_conditioning_contract.py`

**Interfaces:**
- Distinguish coordinate-map, homogeneous-GSN, and exterior perturbed-radial
  controls in policy material.
- Horizon identity uses the
  `verified-endpoint-control-equivalence-absolute-error/v2` model and current
  real-inner contour/basis identities.
- Exterior scientific identity projects only exterior-relevant policy and
  implementation identity material.

- [ ] Add a failing fixture showing 120 working digits still means root target
  `1e-18`/`1e-20` and never implies `1e-102` ODE accuracy.
- [ ] Add a main-generated exterior receipt compatibility fixture and a failing
  test showing horizon-only changes do not stale it.
- [ ] Add a failing test showing every historical horizon receipt is stale under
  the `verified-endpoint-control-equivalence-absolute-error/v2` identity.
- [ ] Run focused tests and preserve the expected red output.
- [ ] Implement mechanism-scoped identity projections and refresh only the
  horizon-dependent frozen digests.
- [ ] Run focused tests green.
- [ ] Commit this slice.

### Task 5: Calibration, Executable Gates, and PR Closure

**Files:**
- Modify: `tools/calibrate_leaf13_horizon_controls.jl`
- Modify: `m02-calibrate-horizon.ps1`
- Modify: `tools/benchmark_leaf13_factored_legs.jl`
- Modify: `.github/workflows/ci.yml`
- Modify: `docs/engineering/2026-08-15-horizon-rewrite-handover.md`
- Modify: `.tasks/IN_PROGRESS.md`
- Modify: `.tasks/DONE.md`
- Modify: `.tasks/WORK_LOG.md`
- Modify: PR #46 body after evidence exists.

**Receipt contract:** Calibration JSON must explicitly contain coordinate-map
absolute/relative disagreement, reference/verification determinant difference,
base/tight-control difference, raw/normalised absolute difference, RHS and step
counts, derivatives at `h/2`, `h`, `2h`, `ih`, propagated determinant errors,
derivative lower bound, and correction upper bound. It must not depend on
progress output being enabled. It must also bind the git head, worker/package/
tool SHA-256 values, Julia executable/version, project and manifest identities,
depot receipt, complete fixed-frequency request/policy digest, selected endpoint
pair, selected profile, rationale, and its own receipt digest.

- [ ] Add failing calibration receipt validation tests and a CI worker
  parse/load smoke that does not start a Kerr solve.
- [ ] Add the Julia finite-difference spec to CI and keep the existing package
  specs. Run the complete vendored package tests under the pinned M02 project,
  not only three individually included files.
- [ ] Rewrite the old mixed-leg benchmark as an explicitly historical
  comparison or remove its production-like entry point.
- [ ] Commit only a control profile selected by a validated calibration receipt;
  otherwise leave the starting profile labelled uncalibrated and keep the PR
  blocked.
- [ ] Run Gate 0 locally: `python3 -m compileall -q src tests tools`, focused
  suites, full `python3 -m unittest discover -s tests -q`,
  `python3 .tasks/validate_board.py`, and `git diff --check`.
- [ ] Push and require GitHub CI to parse/load the worker and pass all vendored
  Julia package/worker specs.
- [ ] Run native Gate 1: fixed Leaf 13 determinant at 80 digits with geometry,
  endpoint, three-leg, basis, and absolute-error evidence.
- [ ] Run native Gate 2: 120-digit coordinate map reaches its endpoint without a
  microscopic-step stall and reports acceptable identity residuals.
- [ ] Run native Gate 3: Leaf 13 root has accepted `h/2,h,2h,ih` controls and
  correction upper bound `<= 1e-18` with `etaD` and `etaDprime` recorded.
- [ ] Run native Gate 4: horizon regressions `220@0.95`, `221@0.99`,
  `331@0.95`, `441@0.95`, `220@0.9999`; prove exterior behavior and receipt
  compatibility are unchanged.
- [ ] Update handover evidence, condense TASK-079, move it to Done only after
  every gate passes, add the work-log entry, and update PR #46.
- [ ] Run final whole-branch review, resolve findings, push, and wait for required
  checks. Stop at verified PR readiness for explicit landing approval.
