# Public linear-response closure design

**Date:** 2026-08-07  
**Milestone:** M02  
**Delivery:** PR #4  
**Status:** TASK-006 contract implemented; provider admission remains open

## Outcome

M02 admits one production owner for first-order complex Kerr QNM frequency
shifts only after every frozen-domain leaf has component-local uncertainty and
the bounded multimode ledger is complete. The first delivery slice defines the
contract and keeps the capability unavailable. Contract availability and
scientific completion are separate facts.

The public field quantity is the first-order complex shift per unit physical
mechanism coordinate. Raw Kerr roots, first-order shifts, projective
comparisons, and a later assembled response matrix remain distinct artifact
layers.

## Mathematical contract

For a simple baseline root ωₖ,

`D₀(ωₖ) = 0`, `∂ωD₀(ωₖ) ≠ 0`, and `Gₐ,ₖ = −Lₐ,ₖ / ∂ωD₀,ₖ`.

The time convention is `exp(−iωt + imφ)`, frequency is represented as `Mω`,
and spin is `a/M`. A response centre has units of `Mδω` per unit declared
mechanism coordinate. Its two-dimensional covariance is expressed in the
ordered basis `[Re(Mδω), Im(Mδω)]` and therefore has squared response units.

The native horizon contact coordinate is the additive Robin perturbation
`δB`, not reflectivity. The chart conversion is

`δB = 2ipₕR / (1 + R)` and `R = δB / (2ipₕ − δB)`,

where `pₕ = ω − mΩₕ`. A common `δB` and a common `R` are different multimode
physical laws; reflectivity may appear only as an explicitly labelled derived
chart value.

## Request boundary

The top-level theory and convention identify the pure-Kerr baseline consumed
from `spectral-core`. Mechanism-specific theory and convention identities live
inside the capability-local selection, so a cubic perturbation does not turn
its upstream baseline request into a cubic spectrum request.

The capability-scoped numerical policy carries non-empty `sampling_coordinates`
and `mechanisms` selections. Each mechanism selection has exactly:

- `mechanism_id`: one ID frozen by the release manifest;
- `coordinate_id`: the mechanism's fixed amplitude coordinate;
- `theory_id` and `convention_id`: perturbation identities distinct from the
  pure-Kerr baseline;
- `response_quantity_id`: the field-native response, including `h_B` for the
  horizon law;
- `parameters`: explicit JSON parameters that identify the physical profile or
  theory branch.

The request validator rejects an unsupported mechanism, a coordinate mismatch,
duplicate selections, malformed parameters, an unsupported convention, or a
mechanism/theory mismatch before a provider can begin work. It does not silently
drop selections or return a partial payload.

Each sampling coordinate binds one requested physical spin to either a direct
`a/M` value or a dimensionless surface gravity `Mκ`, including exact rational
input identity and the derived spin's binary64 identity. For the latter,
`x = 2Mκ/(1−2Mκ)` and `a/M = sqrt(1−x²)`. The accepted axes exactly cover the
manifest values: direct spins `0.95`, `0.97`, `0.98`, `0.99`, `0.995`, `0.997`,
`0.999`, `0.9995`, `0.9999`, and `Mκ` values `0.01`, `0.005`, `0.002`, `0.001`.
Every requested spin must have exactly one sampling identity.

The supported coordinate mapping is:

| Mechanism | Native coordinate | Required parameter identity |
|---|---|---|
| `horizon-admittance` | `unit-complex-deltaB` | `h_B`; common unit `δB` |
| `exterior-fixed-r3` | `unit-complex-profile-amplitude` | fixed `3M` centre and `0.45M` half-width rules |
| `exterior-light-ring` | `unit-complex-profile-amplitude` | prograde photon-orbit centre rule |
| `exterior-throat-kappa` | `unit-complex-profile-amplitude` | `κ`-scaled throat centre/width rules |
| `exterior-alpha-zero` | `unit-complex-profile-amplitude` | fixed α=0 centre/width rules |
| `exterior-alpha-half` | `unit-complex-profile-amplitude` | fixed α=1/2 centre/width rules |
| `exterior-alpha-one` | `unit-complex-profile-amplitude` | fixed α=1 centre/width rules |
| `cubic-eft` | `unit-dimensionless-cubic-coupling` | `plus` or `minus` polarization |

The cubic mechanism selection names the parity-even cubic perturbation while
the request baseline remains general relativity under the outgoing Kerr
convention. This is a request-admission rule, not evidence that a selected
leaf has been computed.

## Artifact boundary

The output artifact type is `kerr-qnm-linear-response`. Its payload has exact
top-level fields:

- schema and quantity identities;
- equations, convention, units, spin, and horizon-coordinate identities;
- lineage binding implementation source hashes, runtime, numerical policy, and
  evidence ceiling;
- baseline root references using the spectral provider's numeric, rational,
  and binary64 spin identities plus the originating direct-spin or `Mκ`
  sampling identity, without copying raw root values;
- component-local response rows;
- correlated covariance blocks over ordered component/quadrature bases;
- projective comparison rows;
- a completeness ledger.

Each component row binds one mode, exact spin identity, mechanism selection,
baseline-root reference, branch class, numerical status, diagnostics, and a response
result. A resolved result contains a complex centre, a symmetric
positive-semidefinite 2 × 2 covariance, and a local uncertainty disk centred
on that response. An unresolved result contains no numerical centre,
covariance, or disk and must carry a reason. Missing computation is listed as
missing; it is never recoded as an unresolved physical outcome.

Correlated covariance blocks preserve cross-component terms instead of
silently assembling a block-diagonal approximation. Their ordered basis gives
each component's real and imaginary quadratures and declared units; every
resolved component appears exactly once, and each 2 × 2 marginal must equal
the component-local covariance.

Each projective row binds two aligned multimode vectors, their shared mode
order and spin, a numerator/denominator calibration pair, and the covariance
block used for propagation. It stores the nominal Fubini–Study angle, a bounded
angle interval when one exists, a projective outcome, and a separate scientific
state. A zero-containing denominator disk forces an unbounded result and both
states to `UNRESOLVED`; execution may still have succeeded.

The completeness ledger distinguishes required, produced, unresolved, and
missing leaf IDs. Admission requires no duplicates, exact count identities,
and an empty missing list. The contract slice validates incomplete candidate
artifacts but does not register or expose a production provider.

## Evidence and provenance

The artifact envelope seals the provider descriptor, request, ordered upstream
IDs, payload, and evidence state. The payload does not duplicate an upstream
artifact ID that its validator cannot independently cross-check; instead it
stores exact root selectors while the envelope owns upstream identity.

Legacy global uncertainty covers are comparison evidence only. They cannot be
promoted to component-local covariance or disks. Likewise, reflectivity-based
multimode calculations cannot be relabelled as common-admittance calculations.
Golden fixtures must bind their exact coordinate lineage and remain independent
of production code.

## Provider lifecycle

The contract descriptor is present with `available = false` and is not added
to the default registry. Later M02 slices migrate a golden overlap, one
end-to-end `220` computation, frozen-domain expansion, covariance propagation,
and projective reduction. Only the final admission slice may set the descriptor
available, register it, and update the release manifest.

This sequencing preserves the one-owner invariant and keeps the current CLI
failure mode honest while implementation evidence is incomplete.

## Upstream dependency blocker

The currently admitted spectrum does not cover the whole frozen M02 response
domain: spins `0.9995` and `0.9999` are absent, the ℓ=4 catalog ends at `0.75`,
and the four exact `Mκ` samples require their derived prograde spin roots. The
contract keeps the M02 manifest unchanged and records this as an upstream
extension dependency. M02 cannot close until those exact baseline roots are
admitted or a governed release-domain decision changes the contract. This is a
missing computation dependency, not an unresolved scientific result.

## Verification gates

The contract slice must prove:

- strict request admission and rejection before execution;
- exact payload shape and unknown-field rejection;
- finite complex values and local-disk centre identity;
- covariance symmetry and positive semidefiniteness;
- correlated covariance completeness across component quadratures;
- unresolved/missing semantics;
- aligned multimode projective vectors and zero-denominator handling;
- descriptor identity and non-admission;
- example-study validity;
- full regression, board, and release-manifest validation.

M02 closure additionally requires the frozen-domain computation, component-local
coverage audit, exact golden overlap, cache and export receipts, and Windows and
Ubuntu CI. A passing contract test alone is not milestone closure.
