# Task 2 report

## Scope

Closed the checkpoint/recovery persistence gaps for schema-6 promoted
evidence, cached 64-to-120 failed-preflight recovery, and durable 120-digit
asymptotic-precision containment.  The implementation is orchestration-only:
it uses mocked Python fixtures and preserves request/job/precision binding and
solved-leaf cache quarantine.

## Files changed

- `src/windows_solver/response_batches.py`
- `tests/test_linear_response_precision.py`
- `.superpowers/sdd/regularised-gsn-review-fixes/progress.md`

## RED evidence

Before the production fixes:

```text
test_schema_six_rejects_resealed_package_evidence_downgraded_to_historical_shape
FAIL: ValueError not raised

test_cached_failed_preflight_recovery_materializes_predecessor_before_checkpointing
FAIL: cache hit must not execute the leaf

test_120_asymptotic_failure_is_durable_and_not_retried_on_resume
ERROR: JuliaNumericalControlError: synthetic INSUFFICIENT_ASYMPTOTIC_PRECISION
```

The schema test resealed ordinary stage, record, and checkpoint digests after
removing all readout conditioning/determinant evidence and the precision
policy.  The cache test placed an earlier outer attempt before the cached leaf,
forcing safe predecessor renumbering.

## GREEN evidence

```text
PYTHONPATH=src python -m unittest \
  tests.test_linear_response_precision.PromotedConditioningDecisionTests.test_schema_six_rejects_resealed_package_evidence_downgraded_to_historical_shape \
  tests.test_linear_response_precision.PromotedResourceContainmentTests.test_cached_failed_preflight_recovery_materializes_predecessor_before_checkpointing \
  tests.test_linear_response_precision.PromotedResourceContainmentTests.test_120_asymptotic_failure_is_durable_and_not_retried_on_resume -v

Ran 3 tests
OK

PYTHONPATH=src python -m unittest tests.test_linear_response_precision -v

Ran 47 tests
OK

python -m compileall -q src tests
git diff --check
```

Schema-6 package-promoted evidence now requires complete conditioning, exact
mechanism-specific determinant evidence (including Task 1's typed raw-evidence
status), and the exact precision policy.  Explicit schemas 3–5 retain the
bounded historical path.  A cached failed-preflight predecessor is reconstructed
with the local contiguous ordinal/index, its digest is recomputed, and the
embedded stage mapping is resealed to match it.  A well-formed 120-digit
`INSUFFICIENT_ASYMPTOTIC_PRECISION` failure is durably retained and blocks a
second promotion attempt on resume while later leaves continue.

## Execution boundary and limitations

No Julia, PowerShell, Kerr determinant, solver, or scientific payload was
executed.  Evidence is mocked/static Python only.  This task does not change
Task 3 cache-publication validation or Task 4 activation gates.

## Commit

`77402210e729869a0b554dafce49dac4891300f8` —
`fix: preserve checkpoint recovery evidence`

Post-review compatibility follow-up:

`8f77145` — `fix: enforce current promoted evidence contracts`

This follow-up closes the remaining current-schema evidence-kind downgrade,
updates older mocked 80/120-digit component fixtures to carry complete package
conditioning/runtime evidence, and adds resealed request-identity tamper
coverage.  The affected checkpoint, campaign-batch, and solved-leaf-cache suite
ran 105 tests successfully before the follow-up commit.
