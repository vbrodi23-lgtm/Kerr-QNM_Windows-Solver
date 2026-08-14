# Horizon Basis at Match Prototype Design

## Decision

Build a performance-only Leaf 13 prototype that replaces the expensive mixed
`Xup_match_to_inner` integration with two pure horizon remainder integrations
from a verified near-horizon endpoint to the match point.  Keep the production
readiness gate, worker path, schemas, determinant chart, and cache identities
unchanged.

## Finding that changes the implementation

The current frequency-aligned negative-rho contour does not reach the outer
horizon for Leaf 13.  Direct coordinate-only execution shows all four
sign/conjugation variants escaping toward complex infinity.  The current
variant has `|r-r_plus| ~= 96.8` at `rho=-100` and grows thereafter.  Its
horizon asymptotic failures are therefore geometry failures, not endpoint-order
failures.

The positive real tortoise tangent, `drstar/drho = 1`, stays on the exterior
real branch and reaches `|r-r_plus| ~= 2.2e-10` at `rho=-100`.  At `rho=-25`,
both order-28 horizon series already pass the 24-digit Leaf 13 preflight, with
about 36 and 37 predicted reliable digits.  Factoring the pure ingoing and
outgoing plane waves removes the reason to rotate this inner contour for the
prototype.

## Prototype computation

1. Reuse the existing authenticated Leaf 13 spectral context and canonical
   outer contour.
2. Propagate the infinity-outgoing remainder from `rho_out` to the match point
   with the existing post-readiness executor.
3. Construct a separate real inner radial map with `drstar/drho = 1` and choose
   the nearest endpoint that passes both horizon series preflights.
4. For each pure horizon branch, build
   `X = exp(sign*i*p*rstar) Y` with
   `q = d(log A)/drho = sign*i*p`, seed `Y` from the corresponding horizon
   series, and integrate independently from the inner endpoint to `rho=0`.
5. At the match point, convert the outer result to the physical pair
   `(X, dX/drstar)`.  Convert both horizon columns to the same
   horizon-ingoing remainder carrier at `rho=0`.
6. Independently scale the two columns, solve for `(Cref, Cinc)`, undo the
   column scaling exactly, and record the matching reconstruction residual and
   condition estimate.

The match-point solve is equivalent to endpoint matching because all three
states solve the same linear homogeneous equation and connection coefficients
are constant along a nonsingular shared analytic domain.  The prototype makes
no claim that the resulting coefficient convention is production-approved.

## Evidence and gates

The tool must fail before a horizon RHS call unless the radial map approaches
`r_plus` and both endpoint preflights pass.  It emits:

- selected inner endpoint and `|r-r_plus|`;
- preflight reliability and last-term ratios for both horizon branches;
- RHS evaluations, accepted/rejected steps, elapsed time, and remainder norms
  for all three legs;
- scaled basis determinant, Frobenius condition estimate, `Cref`, `Cinc`, and
  target reconstruction residual.

A combined pure-horizon cost below 200,000 RHS evaluations is a strong
performance pass.  Millions of evaluations or an unresolved basis is a fail.
Coefficient values remain diagnostic until independent reference and human
sign/column review are complete.

## Non-goals

- No production gate flip.
- No worker request/response or checkpoint schema change.
- No precision-promotion, finite-difference, Newton, or cache-policy change.
- No claim that a performance pass validates the horizon sign, column labels,
  or determinant chart.
