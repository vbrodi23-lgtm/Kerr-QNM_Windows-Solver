# M02 Single Promoted Horizon Component Design

## Authority and scope

This design records the operator-approved production contract supplied on
2026-08-18. The attached operator fast-diagnostics PowerShell tester
is the normative numerical reference; the written production requirements
control wherever tester compatibility scaffolding differs.

The change applies only to primary `horizon-admittance` campaign leaves at
Julia precision 80 or 120. Binary64 components, exterior mechanisms,
control/deep validation ladders, and the Julia worker's operator-validated numerical kernel
remain unchanged.

## Execution boundary

`run_promoted_horizon_component(job, backend, primary_predictor)` is a
dedicated component boundary. It binds and validates the job, emits one
baseline amplitude-readout scope, calls
`backend.read_root(job, 0.0j, primary_predictor=primary_predictor)` exactly
once, validates the complete promoted root contract, derives the response,
and returns immediately. It cannot enter the finite-amplitude epsilon loop or
call generic `run_component()`.

The promoted root contract is:

- policy `binary64-parity-primary-fixed-root-diagnostics/v1`;
- accepted PRIMARY with zero post-Newton determinants;
- one accepted TRUNCATION determinant at the PRIMARY root;
- one accepted RESOLUTION determinant at the PRIMARY root;
- both diagnostics reuse the retained complex PRIMARY derivative;
- SEED-PATH is required=false, executed=false, determinant count zero;
- the branch and installed root identities remain authenticated.

## Analytic response

For determinant convention `cinc-over-cref-minus-R/v1`, use the retained
complex PRIMARY derivative without another determinant evaluation:

```text
r_plus  = 1 + sqrt(1 - a^2)
Omega_H = a / (2 r_plus)
p_H     = omega_PRIMARY - m Omega_H
h_B     = 1 / (2 i p_H Dprime_PRIMARY)
```

The boundary fails closed for absent or rejected evidence, an incorrect
policy or determinant convention, a zero/non-finite `p_H`, or a zero/non-finite
complex derivative.

## Evidence contract

The returned component is computationally `CONVERGED` and carries:

- component identity `single-promoted-root-analytic-horizon-component/v1`;
- response method `analytic-horizon-from-promoted-primary-derivative/v1`;
- an empty level list and null signed-root cross-check;
- finite-amplitude required/executed false and readout count zero;
- explicit error-channel applicability rather than treating retained numeric
  zeros as measured uncertainty;
- uncertainty status `UNCALIBRATED_ANALYTIC_RESPONSE`.

Release/admission remains fail-closed because no response-uncertainty bound is
invented. The fixed-root TRUNCATION and RESOLUTION evidence authenticates the
root readout; it is not silently relabelled as calibrated response uncertainty.

## Promotion and predictors

At 80 digits the root predictor is the immediately preceding binary64
`ComponentResult.baseline.omega`, not `job.root.omega` and not the response
coefficient continuation predictor. At 120 digits it is the immediately
preceding promoted baseline omega.

No same-precision component self-refinement runs. A converged, branch-valid,
accepted, adequately conditioned 80-digit baseline terminates promotion.
Only rejected root/phase/branch evidence, inadequate reliable digits,
`precision_limited=true`, or a typed retryable 80-digit preflight/control
failure requests 120 digits. Missing response evidence on the binary64 stage
is explicitly non-applicable to precision-ladder comparison and never falls
back to comparing response coefficients with root frequencies.

## Checkpoint and cache migration

The new component identity changes the promoted horizon calculation identity.
Old promoted horizon multi-readout stages, including an incomplete Leaf 13
self-refinement stage, are not reusable. A schema migration authenticates the
old checkpoint first, retains completed canonical binary64 stages, drops each
affected incomplete or completed old promoted horizon stage, and resumes from
promotion. Completed unaffected binary64 leaves are not recomputed.

## Verification boundary

Verification is limited to static, parser, schema, compile, and mocked/unit
tests. No Julia worker, Kerr determinant, ODE solve, Leaf 13, finite-amplitude
ladder, campaign, or PowerShell production tester is executed in this
environment. Mathematical validation is the operator's fast-diagnostics receipt.
