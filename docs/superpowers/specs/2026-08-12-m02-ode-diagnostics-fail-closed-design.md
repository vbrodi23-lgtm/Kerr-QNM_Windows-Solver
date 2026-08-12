# M02 ODE Diagnostics and Fail-Closed Worker Design

## Problem

The promoted Julia worker reports sampled right-hand-side activity but not the
solver's accepted/rejected-step statistics or final ODE return code.  Internal
GSN segment solutions are used before the package boundary can inspect them.
Operational failures can also enter the predictor fallback path, while timeout
or interruption kills only the direct Julia process.  At a precision promotion,
the live dashboard retains binary64 root and determinant values until new Julia
events replace them.

Together these gaps make a collapsed high-spin ODE hard to diagnose and allow
resource/control failures to be displayed too much like scientific
nonconvergence.

## Selected design

Add neutral observation hooks at the vendored GSN boundary.  Invoke a fresh,
observation-only callback during each package-owned `solve`, then inspect the
raw solution immediately after return and before evaluating that solution.  The
callback uses `save_positions=(false,false)`, reports that it has not modified
the state, and never changes time, step size, tolerances, stops, or algorithm
state.  The M02 worker records the existing SciML `retcode` and `stats` counters
for every named segment, emits typed completion/failure events, and throws a
dedicated ODE control exception for an unsuccessful return code.  The worker's
predictor fallback explicitly rethrows every ODE control exception.

Keep every numerical input and solve option unchanged: algorithms, tolerances,
domains, endpoint order, `dtmax`, `maxiters`, Newton controls, branch radius,
and acceptance gates.  In particular, this diagnostic change introduces no new
step or evaluation ceiling: r-from-rho retains SciML's default, complex X legs
retain `maxiters=Inf`, and real-radius legs retain `maxiters=10^7`.  An existing
SciML `MaxIters` return and the existing request timeout become explicit,
distinct resource/control failures instead of numerical outcomes.  Complex X
legs therefore remain unbounded until a separately reviewed numerical-policy
change selects a finite limit.

At the Python boundary, retain bounded worker receipts on dedicated timeout and
ODE-resource exception types.  Start Julia in its own POSIX session.  On
Windows, first start a blocked package-owned bootstrap, assign that bootstrap to
a kill-on-close Job Object, and only then release it to create Julia; every
Julia descendant is therefore born in the owned job and remains terminable even
after the direct worker exits.  Terminate the owned tree on timeout or any
unwinding exception.
A worker exception continues through the campaign failure path; promotion
remains possible only after a valid `StageOutcome` returns.

At `PRECISION_STAGE_STARTED`, clear all live root, determinant, suboperation,
radial, and ODE measurements from the preceding tier.  Project new ODE events
into the status JSON and dashboard, including solve/segment identity, return
code, right-hand-side evaluations, accepted/rejected steps, nonlinear and
Jacobian work, and accepted-step size diagnostics.  Coordinates and step sizes
remain numeric strings, so the diagnostics are reusable by future arithmetic
backends without binary64 coercion.

## Failure semantics

- `ode_solve_completed`: a segment returned a successful SciML return code and
  carries exact final statistics.
- `ode_solve_failed`: a segment returned an unsuccessful non-resource code and
  the worker aborts.
- `ode_resource_limit`: SciML returned `MaxIters`; the worker aborts with
  `ODEResourceLimit`.
- Python request timeout: the complete Julia process tree is terminated and a
  `JuliaWorkerTimeoutError` is raised.
- None of these paths returns `NOT_CONVERGED`, retries from the authenticated
  background seed, or advances to another precision tier.

## Adjacent-repository findings

The pinned `parametrized_qnm_framework` commit `6131f4c` is suitable only as an
offline comparator.  Its Kerr tables cover all 63 combinations of ℓ=2,3,4,
m=−ℓ…ℓ, and n=0,1,2, with exact rows through χ=0.9999, but its Python wrapper
uses working-directory-relative files, default cubic extrapolation, and
non-fail-closed missing quadratic data.  It must not replace the authenticated
catalogue or runtime backend.

MultiFloats.jl v3.2.6 is deferred to a separate precision-architecture change.
Float64x4 provides about 63 decimal digits, not 80; complex arithmetic, the GSN
transcendental path, StaticArrays, and AutoVern9/Rosenbrock23 compatibility are
not established by its test suite.  A future isolated Float64x4 predictor may be
benchmarked against a full independent BigFloat80 recomputation, but it does not
belong in an arithmetic-neutral diagnostic PR and cannot yet be called a
certification tier.

## Verification boundary

Python unit tests and static source-contract tests prove event validation,
failure typing/propagation, precision-state reset, and subprocess cleanup.  They
also pin the unchanged numerical call options.  Julia parsing and all scientific
execution remain airgapped for the Windows operator to run after reviewing the
draft PR.
