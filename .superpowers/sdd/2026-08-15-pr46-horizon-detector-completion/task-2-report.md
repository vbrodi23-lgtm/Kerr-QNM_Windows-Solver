# Task 2 Report: Complete Determinant and Derivative Authentication

## Status

Implementation complete and locally verified for all available Python/static
checks. The Julia algebraic specification is present and sourced by CI, but Julia
and PowerShell are unavailable in this local environment, so no local Julia
execution is claimed.

Resume HEAD: `4caf2836544e54b2f9373056be48b577a0ddde25`.

## Scope delivered

- Added typed `DeterminantErrorBreakdown` and `DerivativeAuthentication`
  records, plus the nested `RootAuthentication` success record.
- Changed the horizon determinant identity to
  `verified-endpoint-control-equivalence-absolute-error/v2` in the worker and
  Python public scientific identity.
- Added the absolute raw/normalised chart discrepancy
  `abs(raw_determinant / Cref - normalised_determinant)` to the vendored GSN
  package assessment.
- Replaced the horizon scalar error with endpoint, control, equivalence, and
  optional precision components. The precision component remains `nothing`
  because Task 2 has no exact same-frequency cross-precision evaluation.
- Added one-rung, depth-guarded tight-control evaluation at the exact same
  frequency for the final horizon root and every accepted derivative stencil
  point. Diagnostic phases never recursively authenticate.
- Preserved each stencil pair's actual propagated error through
  `finite_difference_pair`, `final_derivative`, the step ladder, derivative
  authentication, and root output.
- Validated finite positive frequency-step policy with ordered bounds and a
  bounded, de-duplicated rung list.
- Changed Newton damping and best-iterate selection to compare `abs(D) + etaD`.
- Preserved the exterior path's not-applicable determinant breakdown and
  historical derivative reuse/no-tightening behavior.
- Added a real Julia algebraic/finite-difference specification and wired it into
  the Julia CI job.
- Updated exact public-surface identity contracts instead of suppressing the
  planned v2 identity.

## TDD evidence

### RED

Before production implementation, twelve minimal focused contracts were run and
failed for the intended missing behaviors: typed determinant components and max
aggregation; absolute raw/normalised equivalence; unequal endpoint stencil-error
propagation; finite/positive/ordered step policy; bounded unique rungs;
same-frequency tight controls without recursive diagnostic tightening;
error-inclusive best ranking; derivative/root authentication fields; the exact
v2 public identity; and CI execution of the worker Julia spec. Result: **12
failures**.

During exterior-path self-review, the new final-authentication path was shown to
recompute the exterior accepted derivative. A dedicated exterior regression
contract was added and observed failing: **1 failure**. The implementation was
then restricted with
`authenticate_controls && root_evaluation.error_breakdown !== nothing`, after
which the exterior contract passed.

### GREEN

- Focused Task 1/Task 2 baseline before Task 2 implementation:
  `PYTHONPATH=src python -m unittest tests.test_regularised_gsn_worker_static tests.test_julia_response_backend`
  — **77 passed**.
- Affected focused suites after implementation and final cleanup:
  `PYTHONPATH=src python -m unittest tests.test_regularised_gsn_worker_static tests.test_regularised_gsn_factored_propagation_static tests.test_julia_response_backend tests.test_numerical_conditioning_contract tests.test_public_surface`
  — **181 passed, 6 skipped**, 11.940 seconds.
- Complete Python suite after fixing the stale Task 1 static boundary:
  `PYTHONPATH=src python -m unittest discover -s tests`
  — **693 passed, 7 skipped**, 97.888 seconds.
- `python -m compileall -q src tests tools` — exit 0.
- `git diff --check` — exit 0.
- `python .tasks/validate_board.py` — exit 0; 79 unique tasks, 12 milestones,
  13 Done, 0 Next, 1 In Progress, acyclic dependencies.

An earlier broad run had 692 tests with one stale source-slice error in
`test_regularised_gsn_factored_propagation_static.py`. That boundary was updated
from the removed `estimate_horizon_determinant_error` symbol to
`determinant_error_breakdown`, the affected suites passed, and the complete suite
was rerun to the green result above.

## Numerical formula audit

| Quantity | Implemented formula and provenance | Downstream use | Verdict |
| --- | --- | --- | --- |
| Endpoint discrepancy | `eta_endpoint = abs(D_reference - D_verification)` | Every online horizon evaluation and final certificate | Matches binding context |
| Equivalence discrepancy | `eta_equiv = abs(raw_determinant / Cref - normalised_determinant)` when raw evidence and nonzero `Cref` exist | Max across reference/verification and base/tight evaluations | Absolute, not the retained relative diagnostic |
| Control discrepancy | `eta_control = abs(D_base - D_tight)` at identical `omega` | Final root and every final stencil sample | Same-frequency only |
| Precision discrepancy | Optional; currently `nothing` | Included in typed/output schema only when available | No cross-root or cross-frequency proxy used |
| Determinant error | `etaD = safety_factor * max(available absolute components)` | Newton derivative resolution, correction, damping, ranking, final root record | Constructor validates finite/nonnegative components and exact aggregation |
| Centred-stencil propagated error | `eta_prime = (eta_plus + eta_minus) / (2 * abs(h))` | Returned by `finite_difference_pair` and preserved by every caller | Unequal endpoint errors tested directly |
| Accepted derivative | Real-axis estimate at `h/2` | Root derivative and correction certificate | Matches binding decision |
| Step disagreement | `max(abs(Dprime_h/2-Dprime_h), abs(Dprime_2h-Dprime_h/2), abs(Dprime_ih-Dprime_h/2))` | Derivative lower bound | Conservative across rung and axis comparisons |
| Derivative lower bound | `abs(Dprime_h/2) - step_disagreement - eta_prime_h/2` | Must be strictly positive before acceptance | Constructor and ladder both enforce positivity |
| Residual upper bound | `abs(D) + etaD` | Newton damping, best iterate, final correction numerator | Exterior reduces to historical `abs(D)` because `etaD=0` |
| Correction upper bound | `(abs(D) + etaD) / derivative_lower_bound` | Final convergence decision and root record | Finite positive denominator required |

Frequency-step policy validates nominal, minimum, and maximum as finite and
strictly positive with `minimum <= nominal <= maximum`. Rungs start at nominal,
move coarser then finer by a factor of four, clamp to the configured bounds,
de-duplicate, remain within bounds, and never exceed 64 entries.

## Interface and regression audit

- `DeterminantEvaluation.value` remains the central complex determinant.
- Horizon evaluations carry a typed breakdown; exterior evaluations explicitly
  carry `nothing` and retain their historical zero-error acceptance reduction.
- Final primary horizon authentication uses one tight-control rung. `TRUNCATION`,
  `RESOLUTION`, and `SEED-PATH` phases call `solve_once` with authentication
  disabled. The depth marker rejects any attempted recursive tightening.
- The initial Newton residual reuse remains intact. Horizon final derivative
  authentication deliberately does not reuse the online derivative because
  every accepted stencil point must receive base/tight evidence; exterior does
  reuse its historical accepted derivative.
- Root output preserves central determinant, all error components, residual
  upper bound, derivative estimate, propagated error, step disagreement, lower
  bound, selected step, correction upper bound, axis, and error-model identity
  as precision text for Task 3 transport.
- Task 1 geometry-before-series, endpoint-pair-before-homogeneous-ODE, and
  real-inner carrier tangent source boundaries remain covered by the focused and
  complete Python suites.

## Duplicate and complexity review

Exact line-number inspection confirmed that the apparent duplicate
`T, initial_determinant` call and duplicate `::Type{T}, request` signature were
terminal-output overlap artifacts. A whole-file adjacent-line scan found only
intentional repeated constructor values (`nothing`, `zero(T)`, and booleans).
The only repeated function names are legitimate `Float64`/`BigFloat` or typed
overloads. No duplicated statement, signature, function body, or control block
remains.

The worker diff is large because Task 2 replaces a scalar error field and threads
the resulting certificate through determinant evaluation, tight controls,
Newton, four derivative stencils, convergence, progress, and success output. The
implementation remains a single explicit data path with three small domain
records and narrowly named helpers; no unresolved architectural ambiguity was
found.

## Julia execution state

- Carrier state: `VALID_CARRIER` — the Julia specification is a pure algebraic
  test file that includes the guarded worker and performs no ODE, PowerShell, or
  external I/O work.
- Execution state: `NOT_RUN` locally — `julia`, `pwsh`, and `powershell` are not
  installed in this environment.
- Evidence state: `PRESENT` for authored source/spec and Python/static contracts;
  hosted Julia runtime evidence remains pending CI.
- CI command:
  `julia --startup-file=no --history-file=no --project="$M02_PROJECT" src/windows_solver/data/julia/m02_worker_finite_difference_spec.jl`.

No local Julia success is claimed. The numerical-certificate implementation is
therefore conditionally supported by complete Python/static evidence pending the
independent hosted Julia 1.10 execution surface.

## Known staged boundary

Task 2 adds `root_authentication` to the worker success mapping while retaining
worker response schema 3. The current strict Python reader accepts only the
pre-certificate schema-3 key set and would reject a live response containing the
new field. This is an explicit inter-slice boundary rather than hidden
compatibility: Task 3 owns `julia_response_backend.py`, bumps the worker response
to schema 4, and adds strict `DeterminantErrorEvidence` and
`RootAuthenticationEvidence` parsing and persistence. No Python parser widening
or premature schema bump was made in Task 2. Consequently, this commit is ready
as the determinant/derivative producer slice but is not a standalone end-to-end
worker/backend release without Task 3.

## Files changed

- `.github/workflows/ci.yml`
- `docs/superpowers/plans/2026-08-15-pr46-horizon-detector-completion.md`
- `src/windows_solver/data/julia/GeneralizedSasakiNakamura.jl/src/Homogeneous/Solutions.jl`
- `src/windows_solver/data/julia/GeneralizedSasakiNakamura.jl/test/scaled_scattering_spec.jl`
- `src/windows_solver/data/julia/m02_worker.jl`
- `src/windows_solver/data/julia/m02_worker_finite_difference_spec.jl`
- `src/windows_solver/response_engine.py`
- `tests/test_julia_response_backend.py`
- `tests/test_numerical_conditioning_contract.py`
- `tests/test_public_surface.py`
- `tests/test_regularised_gsn_factored_propagation_static.py`
- `tests/test_regularised_gsn_worker_static.py`
- `.superpowers/sdd/2026-08-15-pr46-horizon-detector-completion/task-2-report.md`

## Task 2 checklist

- [x] One minimal failing contract was observed for each new behavior.
- [x] Absolute endpoint and equivalence discrepancies are implemented.
- [x] Safety-factor maximum aggregation is typed and validated.
- [x] Unequal stencil endpoint errors propagate through every caller.
- [x] Frequency steps are finite, positive, ordered, bounded, and de-duplicated.
- [x] Newton damping and best-iterate ranking use `abs(D) + etaD`.
- [x] Final horizon root and stencil samples receive exact-frequency tight-control authentication.
- [x] Diagnostic phases cannot recursively tighten.
- [x] Accepted derivative is the real-axis `h/2` estimate with a strictly positive authenticated lower bound.
- [x] Exterior behavior is preserved.
- [x] Complete root-authentication values are emitted as precision text.
- [x] Exact v2 public identity is implemented and contract-tested.
- [x] Real Julia specification is sourced by CI.
- [x] Affected focused Python suites are green.
- [x] Complete Python suite is green after the stale-boundary fix.
- [x] Compile, diff, and board checks are green.
- [x] Local Julia execution is explicitly not claimed.
- [x] The intentional Task 3 schema/parser dependency is explicitly disclosed.
