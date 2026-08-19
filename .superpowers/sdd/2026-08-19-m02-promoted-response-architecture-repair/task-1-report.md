# Task 1 Report — Typed promoted-response contracts

## Status

Implemented the scoped pure-contract slice on `solver/campaign-optimization`. No
Kerr determinant, Julia worker, ODE, angular solve, QNM solve, M02 campaign, or
PowerShell production tester was executed. Existing stopped checkpoints,
receipts, TaskPlanner state, and legacy precision presentation remain unchanged.

## Implementation

- Added `ComplexDisk` product, quotient, inversion, exterior-response, and
  analytic-horizon propagation with conservative radii. Zero-containing
  denominators raise `ZeroContainingDiskError`; zero radius requires explicit
  exact-zero provenance.
- Added the authoritative semantic order `binary64 -> bigfloat-40 ->
  bigfloat-80 -> bigfloat-120`, explicit legacy conversion, nominal decimal
  digits, and actual working-bit calculation. Historical
  `precision_tier_presentation()` remains unchanged and readable.
- Added deterministic nearest-adequate outer-endpoint selection. Reliable
  digits, regularity, last term, series spread, and cancellation are hard gates
  with explicit rejection reasons. Evidence records semantic tier, nominal
  digits, and working bits independently.
- Added calibrated request-level determinant/ODE budget records. Tighter root
  requests produce no looser coordinate or homogeneous controls. Missing
  calibration fails with the exact required human-math blocker rather than
  retaining an unnamed tolerance table.
- Added `PartialComponentEntry` and `PartialComponentJournal`. Work-unit and
  entry digests bind component/leaf/job/policy/backend/determinant/tier/bits/
  amplitude/epsilon/role/refinement/request/worker-receipt fields. Writes use
  canonical JSON, file fsync, atomic replace, and parent-directory fsync where
  supported; exact repeats are idempotent, conflicts fail closed, and failed
  replacement rolls back in-memory state.

## Files

- `src/windows_solver/response_uncertainty.py` — new
- `src/windows_solver/adaptive_controls.py` — new
- `src/windows_solver/partial_component_checkpoint.py` — new
- `src/windows_solver/precision_tiers.py` — modified
- `tests/test_precision_tier_ordering.py` — new
- `tests/test_adaptive_outer_endpoint.py` — new
- `tests/test_adaptive_ode_budget.py` — new
- `tests/test_partial_component_checkpoint.py` — new
- `tests/test_promoted_horizon_uncertainty.py` — new
- `.superpowers/sdd/2026-08-19-m02-promoted-response-architecture-repair/task-1-report.md` — new

## RED evidence

Before any production edit:

```bash
for test_file in test_precision_tier_ordering.py test_adaptive_outer_endpoint.py test_adaptive_ode_budget.py test_partial_component_checkpoint.py test_promoted_horizon_uncertainty.py; do
  PYTHONPATH=src python -m unittest discover -s tests -p "$test_file" -v || true
done
```

Observed output:

```text
test_precision_tier_ordering: ImportError: cannot import name 'PrecisionTier'
test_adaptive_outer_endpoint: ModuleNotFoundError: No module named 'windows_solver.adaptive_controls'
test_adaptive_ode_budget: ModuleNotFoundError: No module named 'windows_solver.adaptive_controls'
test_partial_component_checkpoint: ModuleNotFoundError: No module named 'windows_solver.partial_component_checkpoint'
test_promoted_horizon_uncertainty: ModuleNotFoundError: No module named 'windows_solver.response_uncertainty'
```

Two self-review regressions were also observed RED before their fixes:

```bash
PYTHONPATH=src python -m unittest discover -s tests -p 'test_adaptive_outer_endpoint.py' -v
PYTHONPATH=src python -m unittest discover -s tests -p 'test_partial_component_checkpoint.py' -v
```

```text
3 errors: select_outer_endpoint() got an unexpected keyword argument 'precision_tier'
1 failure: failed os.replace left the in-memory journal with no missing work unit
```

## GREEN and verification evidence

Final commands:

```bash
PYTHONPATH=src python -m unittest discover -s tests -p 'test_precision_tiers.py' -v
PYTHONPATH=src python -m unittest discover -s tests -p 'test_precision_tier_ordering.py' -v
PYTHONPATH=src python -m unittest discover -s tests -p 'test_adaptive_outer_endpoint.py' -v
PYTHONPATH=src python -m unittest discover -s tests -p 'test_adaptive_ode_budget.py' -v
PYTHONPATH=src python -m unittest discover -s tests -p 'test_partial_component_checkpoint.py' -v
PYTHONPATH=src python -m unittest discover -s tests -p 'test_promoted_horizon_uncertainty.py' -v
python -m compileall -q src tests
python .tasks/validate_board.py
git diff --check
```

Observed output:

```text
test_precision_tiers.py: Ran 3 tests ... OK
test_precision_tier_ordering.py: Ran 3 tests ... OK
test_adaptive_outer_endpoint.py: Ran 3 tests ... OK
test_adaptive_ode_budget.py: Ran 2 tests ... OK
test_partial_component_checkpoint.py: Ran 3 tests ... OK
test_promoted_horizon_uncertainty.py: Ran 4 tests ... OK
compileall: exit 0, no output
TaskPlanner board valid: 79 unique tasks, 12 milestones, 13 Done, 0 Next, 1 In Progress, acyclic dependencies.
git diff --check: exit 0, no output
```

## Self-review

Verdict: **Looks good** for this contract-only slice; no P0–P3 findings remain.

- Spec axis: all named Task 1 interfaces and focused behaviors are present; the
  exact blocker text is preserved; legacy presentation remains compatible.
- Correctness axis: disk bounds use denominator floors; invalid/non-finite
  inputs fail closed; endpoint selection is input-order independent; ODE
  calibration is mandatory; journal identities cover all specified fields.
- Persistence axis: duplicate exact entries are idempotent, conflicting entries
  reject before mutation, temporary files are cleaned on failure, in-memory
  state rolls back on failed replace, and loaded entries/digests are revalidated.
- Scope/security axis: no external input reaches a shell or unsafe decoder; no
  production execution or unrelated file mutation occurred.

## Risks and evidence ceiling

- These are pure Python policy/evidence contracts and synthetic tests only.
  They are not yet routed into the promoted component/backend execution paths;
  that belongs to later tasks in the approved plan.
- No numerical calibration is claimed. Real ODE tolerance derivation remains
  deliberately blocked until a human-approved calibration is supplied.
- No physical, mathematical, performance, Julia, Kerr, or PowerShell production
  evidence is claimed.
- Parent-directory fsync is performed on POSIX. Windows exposes the repository's
  existing durable file-fsync plus atomic-replace pattern but no portable Python
  directory-fsync primitive.

## Independent-review remediation

An independent review of commit `f40fb8c` blocked on three contract defects. The
follow-up fixes are intentionally limited to those findings:

- derived ODE totals, every allocation, and every coordinate/homogeneous
  tolerance must be finite, strictly positive, and representable; the immutable
  `ODEErrorBudget` constructor now enforces the same canonical invariants;
- worker receipts are normalized through canonical JSON and recursively frozen,
  so nested caller mutation cannot change an entry; every record/write path
  reconstructs and revalidates the receipt digest before persistence;
- predicted reliable digits must strictly exceed the requirement plus margin;
  equality now records `INSUFFICIENT_RELIABLE_DIGITS`.

Review-remediation RED commands:

```bash
PYTHONPATH=src python -m unittest discover -s tests -p 'test_adaptive_ode_budget.py' -v
PYTHONPATH=src python -m unittest discover -s tests -p 'test_adaptive_outer_endpoint.py' -v
PYTHONPATH=src python -m unittest discover -s tests -p 'test_partial_component_checkpoint.py' -v
```

Observed RED output:

```text
test_adaptive_ode_budget.py: 3 failures; underflowed/overflowed total,
  allocation underflow, and tolerance underflow did not raise
test_adaptive_outer_endpoint.py: 1 failure; equality selected rho_out=100.0
  instead of the strictly adequate rho_out=250.0
test_partial_component_checkpoint.py: 1 error and 1 failure; nested caller
  mutation caused a persisted receipt digest mismatch, and the entry receipt
  remained directly mutable
```

Focused remediation GREEN output:

```text
test_adaptive_ode_budget.py: Ran 4 tests ... OK
test_adaptive_outer_endpoint.py: Ran 4 tests ... OK
test_partial_component_checkpoint.py: Ran 5 tests ... OK
```

Final post-remediation verification reran all five Task 1 files:

```text
test_precision_tier_ordering.py: Ran 3 tests ... OK
test_adaptive_outer_endpoint.py: Ran 4 tests ... OK
test_adaptive_ode_budget.py: Ran 4 tests ... OK
test_partial_component_checkpoint.py: Ran 5 tests ... OK
test_promoted_horizon_uncertainty.py: Ran 4 tests ... OK
python -m compileall -q src tests: exit 0, no output
git diff --check: exit 0, no output
```
