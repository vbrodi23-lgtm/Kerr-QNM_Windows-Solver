# Task 4 report

## Scope

Separated the human mathematical review receipt from the independent
high-precision reference-fixture receipt. Both gates remain explicitly absent,
carry null digests, and fail loudly. Production readiness calls both assertions.

The four gate identities are now bound through the Python precision policy,
Julia request validation, versioned worker conditioning evidence, scientific
runtime, `RootReadout`/component/checkpoint serialization, and request-derived
root-cache identity.

## Files changed

- `src/windows_solver/response_engine.py`
- `src/windows_solver/julia_response_backend.py`
- `src/windows_solver/response_batches.py`
- `src/windows_solver/data/julia/m02_worker.jl`
- `src/windows_solver/data/julia/GeneralizedSasakiNakamura.jl/src/GeneralizedSasakiNakamura.jl`
- `src/windows_solver/data/julia/GeneralizedSasakiNakamura.jl/src/Homogeneous/FactoredSolutions.jl`
- static/mocked Python tests, Julia specifications, and shared fixtures

## RED evidence

Before the evidence-schema implementation, the focused regressions reported:

```text
current conditioning gate evidence: ValueError: numerical conditioning evidence fields are invalid
historical schema-2 round trip: ValueError: numerical conditioning evidence fields are invalid
current worker with schema-2 evidence: stale evidence reached policy comparison instead of the current-schema rejection
historical combined policy: campaign promoted scientific runtime policy disagrees with mechanism
```

## GREEN evidence

```text
PYTHONPATH=src python -m unittest -q \
  tests.test_linear_response_precision \
  tests.test_linear_response_batches \
  tests.test_solved_leaf_cache \
  tests.test_julia_response_backend \
  tests.test_root_readout_cache \
  tests.test_numerical_conditioning_contract \
  tests.test_regularised_gsn_primitives_static \
  tests.test_regularised_gsn_factored_propagation_static \
  tests.test_regularised_gsn_worker_static

Ran 262 tests
OK

python -m compileall -q src tests
git diff --check
```

`windows-solver.m02-conditioning/3` is the only schema accepted from a current
worker response. Schema 2 remains readable only as bounded historical evidence:
it cannot contain backfilled gate fields and authenticates only against the
exact former combined policy. Current checkpoint/cache validation rejects it.

Tamper coverage changes each status and digest independently at the evidence,
request, scientific-runtime/checkpoint, and request-derived cache-identity
surfaces. Static coverage also proves that if either assertion were
hypothetically satisfied alone, the other assertion remains in the production
readiness path.

## Limitations and execution boundary

No receipt was created, approved, signed, frozen, or assigned a fabricated
digest. The human review must still cover carrier signs, horizon basis
order/normalisation, determinant chart, and contour-tangent review. The
independent reference fixture remains absent.

No Julia, Kerr determinant, PowerShell, solver, or scientific payload was
executed. Julia specifications were updated but remain unexecuted.

## PR commits

- `1895d7b` — `fix: separate regularised GSN activation gates`
- `87f0e9f` — `fix: bind activation gates in conditioning evidence`
- `07a7745` — `fix: bound historical conditioning compatibility`
