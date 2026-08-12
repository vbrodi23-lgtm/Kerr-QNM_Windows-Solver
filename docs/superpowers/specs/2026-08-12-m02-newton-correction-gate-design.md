# M02 Newton-Correction Convergence Gate Design

## Problem

The binary64 and promoted Newton solvers currently declare convergence when the
raw determinant magnitude satisfies a fixed threshold.  The determinant is not
normalization invariant.  Live M02 evidence shows that the local Newton-
correction estimate remains at the binary64 floor while the determinant
derivative grows toward extremality:

- at a/M = 0.95, approximately 7.8 × 1.82×10⁻¹² = 1.42×10⁻¹¹;
- at a/M = 0.9999, approximately 36.1 × 9.71×10⁻¹³ = 3.50×10⁻¹¹.

The 4.63-fold derivative growth makes the fixed raw-residual gate fail while the
local correction estimate remains nearly flat.  The displayed products are not
independent evidence: the implementation defines the estimate as `|D| / |Dω|`,
so `|Dω| × η_D = |D|` is an identity up to rounding.  The claim is therefore
limited to a local Newton estimate; it is not a measured root error.

## Selected design

Gate each Newton phase on the local correction estimate
`η_D = |D| / |Dω|`, not on bare `|D|`.  The numerical threshold retains the
existing values at each arithmetic tier: 2×10⁻¹¹ for binary64, 10⁻¹⁸ for
BigFloat80 base, 10⁻²⁰ for BigFloat80 refinement, 10⁻¹⁰² for BigFloat120 base,
and 10⁻¹⁰⁶ for BigFloat120 refinement.  These values now have units of Mω root
correction rather than determinant normalization.

For a nearby simple root with error `e`, Taylor expansion gives
`D / Dω = e + O(e²)`.  Outside that local regime, `η_D` need not approximate
the distance to a root and is not a convergence certificate.  In particular,
the simple-root function `D(z) = exp(k z) z` has `D / D′ = z / (1 + k z)`,
which can be arbitrarily small far from its only root.  Acceptance therefore
continues to require the existing non-tautological safeguards: an authenticated
catalog branch, all four phase variants (including the independent SEED-PATH),
and agreement inside the fixed branch-continuation radius.

Every phase must still return a finite, strictly positive centred derivative.
PRIMARY, TRUNCATION, RESOLUTION, and SEED-PATH must all pass the correction gate,
and the existing branch-continuation geometry remains unchanged.  A singular or
unusable derivative fails closed.  Bare `|D|` remains stored and displayed as a
diagnostic but no longer governs convergence or precision promotion.

The Newton loop evaluates Dω before accepting.  If η_D is already below the
locked threshold, it stops before damping evaluations.  After selecting the best
iterate, the existing final centred derivative is retained and the returned
convergence flag is recomputed from the serialized evidence pair
`(|D|, |Dω|)`.  This makes the receipt self-consistent and replayable.

## Identity and migration

Add a versioned root-convergence policy fragment to every leaf's scientific
precision contract.  This invalidates checkpoints and solved-leaf identities
created under the raw-residual gate without changing leaf IDs, equations, or
backend identity.

For PRIMARY leaves only, the existing solved-leaf migration boundary may
republish a one-stage binary64 `PRODUCED` receipt from immediate main when every
stored raw readout has finite positive derivative evidence and
`|D| / |Dω| ≤ 2×10⁻¹¹`.  Old unresolved, promoted, malformed, or correction-
failing evidence remains stale and recomputes.  No status is inferred from a
bare residual during migration.

## Non-changes

- No determinant, equation, normalization, endpoint, contour, radial domain,
  ODE algorithm, ODE tolerance, derivative stencil, branch radius, amplitude
  ladder, error channel, response reduction, or acceptance disk changes.
- BigFloat80 and BigFloat120 remain available for genuine correction-gate
  failures.
- No MultiFloats tier or radial reformulation is introduced.
- The result remains authenticated numerical evidence.  `η_D` is explicitly a
  Newton-correction estimate, not a formal interval root certificate, measured
  root error, or uniqueness proof.

## Verification boundary

Python tests use analytic fake determinants and synthetic authenticated receipts
to prove the gate, failure semantics, promotion behavior, identity change, and
migration.  Static Julia contracts prove the matching policy is encoded in the
airgapped worker.  Julia loading, determinants, and campaigns remain operator-
only PowerShell checks.
