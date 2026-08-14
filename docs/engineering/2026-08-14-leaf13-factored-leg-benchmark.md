# Leaf 13 factored-leg benchmark

## Decision

The regularised infinity-outgoing representation materially reduces the cost
of `Xup_outer_to_match`, but it does not produce the required cost collapse on
the controlling `Xup_match_to_inner` leg. The present representation is not a
Leaf 13 performance breakthrough.

This is performance-only evidence. It is not mathematical validation and does
not satisfy the production-activation gate.

## Exact case

- Mode: `s=-2`, `ell=2`, `m=2`, `n=1` (`221`)
- Spin: `a/M=0.95`
- Frequency: `0.744582472105827 - 0.1596868021342034im`
- Stored angular seed: `1.7454647938369572 + 0.5746522102718097im`
- Arithmetic: 80 decimal digits / 298 bits
- ODE controls: `reltol=1e-18`, `abstol=1e-20`
- Contour: `rho_out=5000`, match at `rho=0`, `rho_in=-5000`
- Algorithm: `AutoVern9(Rosenbrock23(autodiff=false))`
- Endpoint order: 28
- Readout/match radius: `r=6M`
- Julia: 1.10.11 on the Codex Linux execution environment

## Native observations

### Contour construction

| Leg | RHS evaluations | Accepted | Rejected | Wall time |
| --- | ---: | ---: | ---: | ---: |
| `r_from_rho_positive` | 2,978 | 186 | 0 | 8.12 s |
| `r_from_rho_negative` | 3,794 | 237 | 0 | 0.11 s |

### Asymptotic preflight

| Branch | Adequate | Predicted reliable digits | Required | Initial remainder norm | Last-term ratio |
| --- | --- | ---: | ---: | ---: | ---: |
| Infinity outgoing | yes | 67.1344 | 24 | 0.999788 | 7.34e-76 |
| Horizon ingoing | no | -7.99999 | 24 | 7.97e110 | 0.999978 |
| Horizon outgoing | no | -7.99999 | 24 | 7.78e108 | 0.999977 |

The inner cost diagnostic did not use the rejected horizon endpoint state. It
used the infinity solution after the exact carrier change at `rho=0`. The
horizon preflight failure therefore remains a production blocker but does not
invalidate the limited integration-cost observation.

### Factored homogeneous legs

| Leg | Status | RHS evaluations | Accepted | Rejected | Wall time / position |
| --- | --- | ---: | ---: | ---: | --- |
| `Xup_outer_to_match` | completed | 254,850 | 15,928 | 0 | 98.73 s; reached `rho=0` |
| `Xup_match_to_inner` | stopped after decision | 1,227,458 | 76,716 | 0 | 471.51 s; reached `rho=-3606.59` |

The outer remainder norm stayed between `0.7071` and `0.9998`. Its carrier
change reconstruction errors were `8.10e-90` for `X` and `1.24e-89` for
`Xrho`, below the `2.32e-87` diagnostic tolerance.

The inner accepted step settled at approximately `0.04702314` with zero
rejections. Scaling the observed RHS count by traversed distance projects
approximately 1.70 million RHS evaluations at `rho=-5000`. The controlling
diagnosis recorded approximately 1.96 million RHS evaluations on the same
historically expensive leg. The projected improvement is only approximately
1.15 times, not an order-of-magnitude reduction.

## Native defects found and corrected

The benchmark exposed two pre-ODE source defects:

1. `_potential_workspaces` used repeated local named-function definitions in
   mutually exclusive branches. Julia treated these as method overwrites
   during precompilation and then raised `UndefVarError: P_function` at runtime.
   The branch callbacks now use anonymous closures.
2. `InitialConditions.jl` used four `AsymptoticFailureReason` enum values that
   were not exported by `AsymptoticExpansionCoefficients.jl`. The first radius
   witness check therefore raised `UndefVarError: INVALID_ASYMPTOTIC_INPUT`.
   All six enum values are now exported.

The ensuing native package run exposed three more defects that had been hidden
behind those failures:

3. Julia's automatically generated `SeriesKey` outer constructor was more
   specific than the checked constructor for exact `Complex{T}` inputs. An
   explicit inner storage constructor now forces inferred construction through
   the precision and input checks.
4. The negative-tortoise inverse documented a bisection algorithm but relied on
   `Roots.find_zero`'s default `A42` selection. `A42` fails against the
   `-Inf` horizon endpoint for `BigFloat`; the call now explicitly selects
   `Roots.Bisection()`.
5. The scaled scattering solver used ordinary Euclidean norms for the target
   and coefficient pair. Finite components near `floatmax(T)` could therefore
   produce an infinite diagnostic norm and abort an otherwise finite,
   normalised determinant chart. Those two diagnostic norms now use stable,
   saturating scaling.

The propagation specification's nominally adequate fixture was also only at
`r=14M`, where its own empirical preflight correctly rejected the order-two
series. The fixture now uses a genuinely asymptotic outer radius before testing
that the separate human-review gate remains non-bypassable.

## Verification

- Full native Julia package suite: passed.
- Regularised-GSN Python static contracts: 76 passed.
- TaskPlanner board validation: passed (79 unique tasks, acyclic).
- `git diff --check`: passed.

## Command

The temporary diagnostic harness is
`tools/benchmark_leaf13_factored_legs.jl`. It deliberately calls the existing
post-readiness endpoint executor rather than changing the production gate.

```text
julia --startup-file=no --project=<m02-project> tools/benchmark_leaf13_factored_legs.jl
```

Set `KERR_QNM_PROGRESS=1` to emit the ordinary per-leg ODE telemetry alongside
the benchmark records.

## Consequence

Do not spend the next implementation cycle on promotion schemas, determinant
fixtures, or production activation under the assumption that plane-wave
factoring solves Leaf 13 cost. Retain the useful outer-leg result, but regroup
the inner propagation around a representation or coordinate that removes the
nearly constant small-step requirement near the horizon.
