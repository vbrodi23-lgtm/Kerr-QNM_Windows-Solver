# Task 3 report

## Scope

Closed the cache-publication gap for promoted Julia worker successes. A
scientific response is retained only after complete schema, mechanism,
conditioning, branch, and exact-decimal validation. A rejected reused response
invalidates only its exact request/runtime entry so a later call can recompute.

## Files changed

- `src/windows_solver/julia_response_backend.py`
- `src/windows_solver/root_readout_cache.py`
- `src/windows_solver/response_engine.py`
- `src/windows_solver/response_batches.py`
- response/cache/conditioning tests and shared mocked promoted fixtures

## RED evidence

Before the production change, the focused regressions reported:

```text
invalid fresh status-ok response: cache count 1, expected 0
invalid cached status-ok response: cache count 1, expected 0
worker response receipt: AttributeError on RootReadout
```

The fresh response had the correct request digest but swapped the
mechanism-specific determinant identity. The poisoned cached response used a
stale successful wire schema.

## GREEN evidence

```text
PYTHONPATH=src python -m unittest \
  tests.test_linear_response_precision \
  tests.test_linear_response_batches \
  tests.test_solved_leaf_cache -q

Ran 105 tests
OK

PYTHONPATH=src python -m unittest \
  tests.test_julia_response_backend \
  tests.test_root_readout_cache \
  tests.test_numerical_conditioning_contract -q

Ran 114 tests
OK

PYTHONPATH=src python -m compileall -q src tests
git diff --check
```

The version-2 root-readout cache supports a generic optional receipt, while
the scientific promoted path requires a closed
`windows-solver.worker-response-receipt/1` mapping. It binds the canonical
request and digest, scientific runtime digest, successful wire schema, exact
normalised/raw determinant texts, typed raw-evidence status, and its content
digest. Current checkpoint validation binds every receipt to the persisted
job, policy, precision/refinement, and scientific runtime.

The tamper regression changes determinant text below binary64 resolution and
reseals the unkeyed receipt digest, but still fails because the exact cached
response and receipt disagree. This is an unkeyed local integrity receipt, not
a detached signature against an adversary able to forge and reseal all
evidence together.

## Execution boundary

No Julia, Kerr determinant, PowerShell, solver, or scientific payload was
executed. All evidence is static or mocked Python.

## PR commits

- `cc06046` — `fix: validate promoted responses before caching`
- `812f894` — `test: bind promoted worker response receipts`
- `d50ef82` — `fix: authenticate mocked promoted receipts`
