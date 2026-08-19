# Task 2 Report — Derivative promoted components and bounded horizon integration

## Status

Complete. No Kerr determinant, Julia worker, radial or coordinate ODE,
angular solve, QNM root solve, M02 campaign, or production PowerShell tester has
been executed.

## Isolation gate

Before mutation, the worktree was clean at the required baseline:

```text
workspace: /workspace/scratch/311f98c11e2d/repo
branch: solver/campaign-optimization
HEAD: 57ecd9cb7d66486ab7173d7171fa2e70a4bd422c
git status --porcelain: empty
```

Planned blast radius is the Task 2 files named in the controlling plan. Existing
checkpoints, solved-leaf cache, receipts, production scripts, and unrelated
modules are protected and remain untouched.

## RED evidence

The first observable behavior is that an ordinary promoted exterior component
uses one authenticated zero-amplitude root plus fixed-root determinant samples
at `+h`, `-h`, `+h/2`, and `-h/2`, and performs no perturbed-root readouts.
The test also requires serialized determinant counts, identities, selected
step, and nonzero derivative/response disks.

Before any production edit:

```bash
PYTHONPATH=src python -m unittest discover -s tests -p 'test_promoted_exterior_derivative.py' -v
```

Observed expected RED:

```text
ImportError: cannot import name 'EXTERIOR_DERIVATIVE_COMPONENT_IDENTITY'
from 'windows_solver.response_engine'
Ran 1 test ... FAILED (errors=1)
```

The failure is caused by the absent fixed-root derivative route and evidence
surface, not by test setup or a prohibited numerical operation.

The bounded horizon-v2 slice was then run before its production change:

```bash
PYTHONPATH=src python -m unittest discover -s tests -p 'test_promoted_horizon_uncertainty.py' -v
```

Observed expected RED:

```text
ImportError: cannot import name 'BOUNDED_ANALYTIC_RESPONSE'
from 'windows_solver.response_engine'
Ran 1 test ... FAILED (errors=1)
```

The new tests require a positive serialized analytic response disk and a typed,
unusable zero-containing result; neither v2 surface existed.

Restricted validation was then tested before adding policy behavior:

```bash
PYTHONPATH=src python -m unittest discover -s tests -p 'test_promoted_exterior_derivative.py' -v
```

Observed expected RED:

```text
ImportError: cannot import name 'FULL_COMPLEX_LADDER_VALIDATION_IDENTITY'
from 'windows_solver.response_engine'
Ran 1 test ... FAILED (errors=1)
```

The test rejects an automatic derivative-failure fallback before any backend
call and requires an allowed publication reason to add only a fixed-root
imaginary-axis pair, never a perturbed-root ladder.

The Julia adapter fixed-root sample boundary was tested before implementation:

```bash
PYTHONPATH=src python -m unittest tests.test_julia_response_backend.JuliaResponseBackendTests.test_fixed_root_determinant_sample_boundary_preserves_evidence -v
```

Observed expected RED:

```text
AttributeError: 'JuliaPrecisionRootBackend' object has no attribute
'sample_fixed_root_determinant'
Ran 1 test ... FAILED (errors=1)
```

The test exercises the request/response boundary and asserts the returned
sample's hashes, determinant identities, semantic tier, MPFR bits, fixed root,
and readout role.

The Julia operation was then statically specified before source changes:

```bash
PYTHONPATH=src python -m unittest tests.test_regularised_gsn_worker_static.RegularisedGsnWorkerSourceTests.test_fixed_root_sample_operation_evaluates_once_without_newton -v
```

Observed expected RED:

```text
ValueError: substring not found for function
fixed_root_determinant_sample_fields
Ran 1 test ... FAILED (errors=1)
```

PRIMARY derivative-specific serialization was also RED before its worker edit:

```text
test_primary_serializes_derivative_specific_uncertainty_without_post_newton_work:
FAIL — `bounded_newton` lacked the `derivative h/2` comparison and the PRIMARY
response lacked `derivative_authentication`.
```

The native promoted exterior route was exercised end-to-end with a synthetic
adapter before routing changes:

```bash
PYTHONPATH=src python -m unittest discover -s tests -p 'test_selective_readout_promotion.py' -v
```

Observed expected RED:

```text
Expected one `root-readout` plus four `fixed-root-determinant-sample`
operations; observed 29 `root-readout` operations from the production full
ladder/self-refinement route. Ran 1 test ... FAILED (failures=1).
```

The semantic BigFloat-40 readout boundary was tested before relaxing the Julia
backend's legacy 80/120-only guard:

```text
test_bigfloat40_readout_surface_is_semantic_not_legacy_campaign_order:
ValueError: Julia precision backend requires 80 or 120 digits
```

Typed exterior failure/admissibility was RED before implementation:

```text
missing derivative evidence raised ValueError instead of returning a typed
unusable result; successful evidence lacked `conditioning_decision`.
test_promoted_exterior_derivative.py: FAILED (errors=2)
```

## Implementation outcome

- Promoted exterior PRIMARY now performs one authenticated baseline root
  readout followed by four fixed-root determinant samples at real-axis
  `h`/`h/2`; no perturbed-root readout or implicit full ladder is used.
- The serialized exterior derivative certificate records every sample and
  receipt, propagated sample errors, h-to-h/2 disagreement, selected step,
  determinant count, conditioning decision, and identity-bound optional
  imaginary-axis validation. Missing/zero-containing derivatives return the
  typed unusable `DERIVATIVE_UNRESOLVED` outcome.
- PRIMARY worker schema 8 and policy v2 authenticate `D_omega` with a genuine
  same-point h/h2 stencil before acceptance. Historical schema/policy parsing
  remains accepted without relabelling.
- Promoted horizon v2 propagates PRIMARY/TRUNCATION/RESOLUTION root evidence
  into the horizon-frequency disk and derivative-specific PRIMARY evidence
  into the derivative disk. Zero-containing inputs are typed unusable;
  bounded results use `BOUNDED_ANALYTIC_RESPONSE`.
- BigFloat-40 is exposed only as semantic precision/readout metadata. It was
  not inserted into the legacy integer campaign ordering, and executable
  request construction fails closed with the exact `ODE_CALIBRATION_BLOCKER`
  because no calibrated `ODEErrorBudget` exists.

## Focused verification

No Kerr determinant, Julia worker, ODE, angular solve, root solve, campaign,
or production PowerShell was executed.

```bash
PYTHONPATH=src python -m unittest \
  tests.test_promoted_exterior_derivative \
  tests.test_promoted_horizon_uncertainty \
  tests.test_selective_readout_promotion \
  tests.test_julia_response_backend.JuliaResponseBackendTests.test_fixed_root_determinant_sample_boundary_preserves_evidence \
  tests.test_julia_response_backend.JuliaResponseBackendTests.test_promoted_backend_uses_practical_80_digit_policy \
  tests.test_julia_response_backend.JuliaResponseBackendTests.test_success_wire_schema_is_seven_and_worker_errors_remain_schema_one \
  tests.test_regularised_gsn_worker_static -q
```

Result: `Ran 61 tests in 2.136s — OK`.

```bash
python -m compileall -q src/windows_solver \
  tests/test_promoted_exterior_derivative.py \
  tests/test_promoted_horizon_uncertainty.py \
  tests/test_selective_readout_promotion.py \
  tests/test_promoted_horizon_component.py \
  tests/test_julia_response_backend.py \
  tests/test_regularised_gsn_worker_static.py
git diff --check
```

Result: both passed.

## Review remediation

The independent review RED reproduced ten failures in the 25-test historical
promoted-horizon/native-backend suite: horizon v2 was not classified by the
predictor, promotion, terminal, payload, lineage, or reduction gates, and
non-primary promoted exterior jobs reached a primary-only guard. A separate
RED proved that absent determinant error models could still produce a bounded
exterior result. Receipt mutations and direct generic-ladder entry were then
specified before their production fixes.

The corrected implementation now:

- explicitly distinguishes historical horizon v1, bounded horizon v2, and
  exterior derivative v1 throughout campaign authentication;
- routes every promoted exterior role, including failed-preflight recovery,
  through one fixed-root derivative operation and no self-refinement ladder;
- requires admitted nonzero determinant-error models in PRIMARY derivative
  evidence and every fixed-root sample, otherwise returning the exact
  human-math-review TODO as typed unusable evidence;
- binds fixed-root receipts to canonical complete request and response
  material and rejects request/response mutations even when the outer receipt
  digest is recomputed; and
- marks promoted precision backends so generic `run_component` rejects them
  before work unless invoked through the identity/reason-bound full-ladder
  validation wrapper.

Final focused verification:

```text
Ran 87 tests in 6.265s — OK
python -m compileall ... — OK
git diff --check — OK
```

## Coherent derivative-certificate resealing review

The final RED coherently changed all four sample values, canonical requests,
worker responses and hashes, then recomputed the coordinate and response
disks. `ComponentResult.from_mapping` incorrectly accepted that self-consistent
but detached ladder.

Exterior derivative checkpoints now enforce the exact four-sample real-axis
ladder (or the identity/reason-bound six-sample validation form), bind every
sample to the baseline omega, job, mechanism convention, precision, and
baseline worker scientific-runtime digest, and independently recompute the
coordinate derivative disk, conditioning decision, PRIMARY frequency disk,
optional imaginary-axis check, and final response disk. Campaign validation
also matches both receipt runtime digests to the authenticated stage runtime.

Final permitted verification:

```text
PYTHONPATH=src python -m unittest tests.test_promoted_exterior_derivative -q
Ran 8 tests in 1.421s — OK

Focused checkpoint/non-primary route: Ran 2 tests in 0.672s — OK
python -m compileall ... — OK
git diff --check — OK
```

This includes the requested 25-test older suite. Campaign-wide journal/resume
extension remains scoped to Task 3; no scientific gate was weakened.

## Final evidence-validation review

The final review identified two additional REDs:

```text
test_horizon_primary_propagates_real_h_and_h2_determinant_errors:
FAIL — solve_binary64_parity_primary still passed
`propagate_derivative_error=false`.

test_component_result_rejects_resealed_fixed_sample_tampering:
FAIL — ComponentResult.from_mapping accepted a nested sample whose response
material and both receipt hashes had been coherently resealed.
```

The horizon PRIMARY worker now propagates endpoint determinant error through
both h and h/2 stencils only when the horizon request carries the admitted
determinant-error model. Its wire status is `available/v1` only when that model
exists and the propagated contribution is positive; exterior remains honestly
unavailable and therefore typed unusable.

Persisted derivative evidence now reconstructs every fixed-root sample through
`FixedRootDeterminantSample.from_mapping`, requires canonical round-trip,
checks the declared count, and requires common determinant family,
normalisation, branch, semantic tier, and MPFR bits. Campaign validation also
derives the worker-runtime identity from stage scientific provenance and
matches every sample receipt against it.

Final permitted verification:

```text
Ran 91 tests in 6.593s — OK
python -m compileall ... — OK
git diff --check — OK
```
