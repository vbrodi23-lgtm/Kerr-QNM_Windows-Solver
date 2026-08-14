# Leaf 13 Horizon Basis at Match Prototype

## Result

The representation premise passes decisively.

At the exact Leaf 13 seed, 298-bit working precision, order-28 endpoint
series, `reltol=1e-18`, and `abstol=1e-20`, the two pure horizon remainder
legs required 10,820 RHS evaluations combined:

| Leg | RHS evaluations | Accepted | Rejected | Wall time |
|---|---:|---:|---:|---:|
| Horizon ingoing, `rho=-25 -> 0` | 5,730 | 358 | 0 | 13.29 s |
| Horizon outgoing, `rho=-25 -> 0` | 5,090 | 318 | 0 | 1.47 s |
| Infinity outgoing, `rho=5000 -> 0` | 254,850 | 15,928 | 0 | 89.12 s |

The pure horizon basis is about 181 times cheaper than the historical
approximately 1.96 million-RHS mixed inner leg.  The complete three-leg
prototype costs 265,670 RHS evaluations, about 7.38 times below that historical
inner leg alone.

## Geometry finding

The existing frequency-aligned negative-rho contour is not a horizon contour
for this leaf.  It runs toward complex infinity: at `rho=-100`,
`|r-r_plus| ~= 96.806`.  Sign-flipped and conjugated variants do the same.

The positive real tortoise tangent reaches the exterior horizon branch.  The
prototype selected the nearest candidate that satisfied both geometry and
series gates:

| `rho_in` | `|r-r_plus|` | Ingoing predicted digits | Outgoing predicted digits | Selected |
|---:|---:|---:|---:|:---:|
| -10 | 5.239e-1 | -8.08 | -7.15 | No |
| -25 | 1.224e-2 | 35.99 | 37.28 | Yes |
| -50 | 3.170e-5 | 80.92 | 81.13 | Verification |

No pure horizon RHS evaluation occurs before these gates pass.

## Match-basis evidence

At `rho=0`, the outer solution was converted to `(X,dX/drstar)` and then to
the real-inner horizon-ingoing remainder carrier.  The independently scaled
horizon basis produced:

- scaled basis determinant magnitude:
  `2.79226276267786695799e-3`;
- Frobenius condition estimate: `716.2649685883923`;
- matching reconstruction residual: `3.95312691765303e-88`;
- `Cref = -0.00883114692665753 - 0.0993798347358069im`;
- `Cinc = -9.38556725089545e-13 - 2.23637019754109e-14im`;
- `cref_fraction = 0.9999999999999999999999557`.

The result was repeated with an independently preflighted `rho_in=-50` basis.
The coefficient-pair relative difference was `7.40357e-15`, below the
prototype's `1e-12` endpoint-invariance gate, and the verification basis
reconstructed its target to `4.28347e-88`.

Because `Cinc` is near zero at this seed, `Cinc/Cref` is cancellation-sensitive:
the ratio differed by `7.86799e-4` relatively between the two endpoints even
though the coefficient pair differed by only `7.4e-15` on its natural scale.
This is explicit evidence that production determinant certification will need
a tighter error strategy.  It does not weaken the measured cost collapse.

## Decision

Proceed with production design around a branch-specific real inner contour and
a pure horizon basis propagated to the match point.  Do not continue investing
in the mixed `Xup_match_to_inner` path.

Before activation, production code still needs:

1. a typed real-inner contour identity and explicit-tangent carrier contract;
2. package-owned ingoing/outgoing-to-match solves and scaled extraction;
3. determinant error control adequate for near-zero `Cinc`;
4. independent reference and human sign/column review.

The production gate remains closed.  This result is performance and internal
consistency evidence, not a mathematical validation receipt.

## Reproduction

```bash
JULIA_DEPOT_PATH=/tmp/kerr-julia.plLFjF/depot \
  /tmp/kerr-julia.plLFjF/julia-1.10.11/bin/julia \
  --project=/tmp/kerr-julia.plLFjF/m02-project \
  src/windows_solver/data/julia/horizon_basis_at_match_prototype_spec.jl

JULIA_DEPOT_PATH=/tmp/kerr-julia.plLFjF/depot \
  /tmp/kerr-julia.plLFjF/julia-1.10.11/bin/julia \
  --project=/tmp/kerr-julia.plLFjF/m02-project \
  tools/benchmark_leaf13_horizon_basis_at_match.jl
```
