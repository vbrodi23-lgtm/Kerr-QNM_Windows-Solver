# M02 Practical High-Precision Policy Design

**Date:** 2026-08-12

**Milestone:** M02

**Status:** Approved for implementation by the user prompt

## Outcome

Keep the promoted 80-decimal-digit Julia BigFloat arithmetic tier and its
298-bit working precision, but make its numerical controls answer the actual
scientific question: whether an authenticated binary64 root becomes stable
under higher-precision arithmetic. Do not demand roughly 62 reliable decimal
places merely because the arithmetic can represent them.

The base 80-digit readout uses:

- root tolerance: 10⁻¹⁸;
- ODE relative tolerance: 10⁻¹⁸;
- ODE absolute tolerance: 10⁻²⁰;
- centred frequency-derivative step: 10⁻⁶.

The 80-digit refinement readout uses:

- root tolerance: 10⁻²⁰;
- ODE relative tolerance: 10⁻²⁰;
- ODE absolute tolerance: 10⁻²⁰;
- centred frequency-derivative step: 10⁻⁷.

The derivative steps follow the central-difference balance h ≈ δ¹ᐟ³ for
determinant evaluations controlled at δ ≈ 10⁻¹⁸–10⁻²⁰. Retaining h = 10⁻⁴⁰
after relaxing the ODE controls would let evaluation error dominate the ±h
difference. The existing endpoint-series, interval-count, angular-padding,
radial-domain, and 16-iteration refinement structure remains unchanged.

The 120-digit request policy remains unchanged. It remains an optional second
recovery tier under the existing authenticated escalation gates.

## Scientific state and identity

The change does not alter the state machine:

- binary64 remains mandatory;
- only authenticated, valid-branch `NOT_CONVERGED` PRIMARY evidence promotes;
- 80 digits promotes to 120 only under the existing numerical-insufficiency,
  refinement-enclosure, or cross-precision-discrepancy gates;
- identity, control, axis, noise-floor, and branch failures never promote;
- leaf acceptance, rejection, preload-store format, and branch authentication
  remain unchanged.

The exact 80/120 numerical-control bundle is added to the canonical PRIMARY
precision contract. This changes the PRIMARY scientific-computation identity
and checkpoint precision binding, preventing an old 10⁻⁶² promoted receipt
from being reused as though it had been computed under the new policy.

The immediately preceding PRIMARY recovery identity and the earlier
binary64-only identity remain exact migration candidates only for authenticated
one-stage binary64 `PRODUCED`/`CONVERGED` records. Old promoted or unresolved
records are retained as stale evidence and recomputed. This preserves the three
legitimate preloaded binary64 successes without accepting an incompatible
promoted result.

## Dashboard presentation

Retain PR #32's independent `LATEST COMPLETED LEAF`, `CURRENTLY EXECUTING`, and
`LIVE ROOT SOLVE` sections and existing Julia progress protocol. Complete the
unit distinction in the committed-stage table and related dashboard fields:

- `binary64 (~15.95 dec)`;
- `BigFloat 80 dec`;
- `BigFloat 120 dec`.

The `PRECISION STAGE RESULTS` ASCII table is mandatory and additive. A bounded
active dashboard must retain all four sections and at least the most recent
completed precision-stage row; extra stage rows use remaining terminal height.

The table's `D_OVER_TOL` display uses the actual base root threshold for each
tier: 2 × 10⁻¹¹ for binary64, 10⁻¹⁸ for BigFloat 80, and the unchanged 10⁻¹⁰²
for BigFloat 120. This ratio is diagnostic-only and does not decide scientific
acceptance.

## Verification boundary

Use synthetic Python fixtures, request inspection, identity/cache tests,
dashboard rendering tests, compilation, board validation, and diff checks.
Do not execute Julia, PowerShell, determinants, radial integration, the Kerr
solver, or a mathematical campaign.
