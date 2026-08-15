# Handover — horizon detector rewrite (PR #46)

Branch `claude/read-this-5em1in`, 13 commits off `main` at `53e04b4` (the PR #45
merge). Draft, not merged.

## What this addresses

The five defects were treated as three, per the review that scoped this work:

- **1 and 2 — one architectural defect.** The horizon side used the wrong
  contour and propagated the wrong solution in the wrong direction.
- **3 and 4 — one numerical-policy defect.** 120-digit *storage* precision was
  converted into a 102-digit *ODE accuracy* demand.
- **5 — one acceptance defect.** A tiny central determinant was treated as
  resolved without carrying an absolute error estimate.

## What landed

### Contour and graph (commits `c870d9c`, `c350bc0`)

`build_real_inner_horizon_contour` implements `r_*(ρ) = rstar_match + ρ`,
`dr_*/dρ = 1`, `ρ < 0` — i.e. `β = 0`, `sign = +1`, `tangent = 1 + 0im` in the
coordinate ODE. `horizon_endpoint_candidates` screens `ρ = -10, -25, -50, -75,
-100` for: `ρ < 0`, `Re(r) > r₊`, negligible `|Im(r)|`, strictly decreasing
`|r − r₊|`, distance within the configured maximum, and both horizon series
passing preflight. The radial-approach conditions are computed independently of
the series verdicts, so no truncation order can substitute for correct geometry.
`select_verified_horizon_endpoints` requires two adequate endpoints (reference +
verification) or raises `NO_VERIFIED_HORIZON_ENDPOINT` with per-candidate detail
and zero homogeneous RHS evaluations.

`evaluate_horizon_determinant` is now three independent legs — infinity outgoing
to match, horizon ingoing and horizon outgoing from a verified real-inner
endpoint to match. The mixed `Xup_match_to_inner` leg is gone and a static CI
test forbids its return. The outer leg is computed once and reused across both
endpoints.

Prototype logic promoted into package APIs:
`FactoredSolutions.horizon_carrier_with_explicit_tangent` (rebinds only `q`,
keeping `log_at_match` canonical), `factor_physical_match_state`,
`Solutions.build_match_horizon_basis`,
`Solutions.solve_scaled_horizon_basis_at_match`.

### Numerical policy (commits `2cc0fb5`, `9e3afde`, `2f4dabc`)

Root target is now 1e-18 base / 1e-20 refinement at **both** 80 and 120 digits
(24 and 26 required reliable digits). The 120-digit tier spends its extra digits
as bounded guard, not as a 1e-102 root demand. `coordinate_ode_*` is split from
`homogeneous_ode_*`. The horizon determinant builds an outer map `0 → +ρ_out`
and a horizon map `0 → horizon_rho_inner_min` (≈ −100) instead of one joined
−5000 → +5000 solve. Both seed `r(0) = match_radius` directly with the
`rstar_from_r` identity checked explicitly, and both report the coordinate
identity residual.

`COORDINATE_INVERSION_STALLED` fires when a coordinate leg burns a generous RHS
threshold with negligible span fraction and microscopic steps — the Leaf 13
condition (2,000,002 RHS, 87.8 s, 1.01e-11 of a 5000 span) now gets a name well
before the hard ceiling.

The frequency step walks a bounded rung range instead of sitting fixed;
exhaustion is `FINITE_DIFFERENCE_NOISE_LIMIT`.

### Acceptance (commit `e4b6955`)

`DeterminantEvaluation` carries `numerical_error_abs` + `error_model_id`.
η_endpoint is `safety_factor × |D_ref − D_ver|`, **absolute**, never divided by
`|D|`. Newton accepts on `(|D| + η_D) / (|D'| − disagreement − η_D')` with the
derivative bound required strictly positive; damping compares error-inclusive
bounds. `DETERMINANT_UNCERTAINTY_TOO_LARGE` covers both the unresolved-slope
case and the case where `|D|` alone would have passed but `|D| + η_D` does not.

### Identities (commit `e6b5f88`)

```
homogeneous_representation  factored-three-leg-horizon-basis-at-match-gsn/v1
horizon_contour             real-inner-tortoise-contour/v1
scattering_extraction       scaled-horizon-basis-at-match/v1
determinant_error_model     verified-endpoint-absolute-error/v1
```

Family-dependent: exterior keeps `factored-plane-wave-gsn/v1` and null horizon
fields. Old horizon receipts go stale by design; frozen digests in the
solved-leaf cache and linear-response tests were refreshed to match.

### Tests and harness (commits `8769d78`, `a0ad22d`, `e4b6955`)

`real_inner_horizon_spec.jl` (8 testsets) plus `scaled_scattering_spec.jl` are
now both wired into CI — the latter holds the raw/normalised equivalence test
and was previously in the repo but never executed. `tools/calibrate_leaf13_horizon_controls.jl`
and `m02-calibrate-horizon.ps1` measure determinant response across control
rungs and the derivative ladder.

## State at handover

Python suite: 667 tests. Everything touched is green. Remaining failures are
pre-existing on the untouched tree — verified by `git stash`:

- 8× `test_spectral_extension` — `TASK-070 overlay builder is absent`
- 2× loader errors — `numpy` / `kerr_angular` absent in this container (CI
  installs `.[numerical-tests]`)

## What has NOT been done

**No Julia executed anywhere in this work.** This container has no Julia
toolchain, so the entire Julia side is verified only by a block-balance check
against HEAD and by Python static-source tests. It has never been parsed,
compiled, or run. Treat first Julia CI as the real syntax check.

None of the four evidence gates were run:

1. Fixed Leaf 13 determinant at 80 digits
2. Leaf 13 root with error-aware bound ≤ 1e-18
3. 120-digit coordinate map reaching its endpoint
4. Regressions: 220 a/M=0.95, 221 a/M=0.99, 331 a/M=0.95, 441 a/M=0.95,
   220 a/M=0.9999

The committed control profile is a **starting point, not a calibrated result.**
The harness exists to replace it with a measured one; that measurement has not
been taken. Anyone reading the values in `promoted_precision_numerical_controls`
as calibrated would be wrong.

## Suggested next steps

1. Run Julia CI first — it is the first real syntax check on ~1,500 lines.
2. Pin the runtime before trusting any Leaf 13 result. The audit found runtime
   `FactoredSolutions.jl` and `ComplexFrequencies.jl` resolving to different
   commits than the audited tree, and `Manifest.seed.toml` omits HDF5 while the
   vendored GSN `Project.toml` declares it — so Pkg re-resolves rather than
   instantiates, and the depot ID hashes a document that never runs.
3. Then Gate 1 at 80 digits, then the calibration harness, then commit a
   measured profile with its receipt.
4. Only then the 120-digit pass and the regression set.

## Open questions worth a second opinion

- **`Cinc/Cref` sensitivity.** The audit read the ρ=−25 → ρ=−50 shift
  (7.9e-4 relative change in the ratio from a 7.4e-15 change in coefficients) as
  cancellation sensitivity. `Cinc → 0` *is* the QNM condition, so poor relative
  accuracy in a residual near its own zero is generic to root-finding, not
  specific to Kerr. This PR therefore gates on the absolute error against `|D'|`
  rather than on the ratio's relative movement. Worth confirming that reading.
- **Endpoint placement vs truncation order.** Order 28 cleared requirement
  everywhere the geometry was right (67.13 digits at infinity; 35.99/37.28 at
  ρ=−25; 80.92/81.13 at ρ=−50). Moving the *endpoint* bought ~45 digits at fixed
  order. If an automatic selector is built, endpoint location looks like the
  larger lever. Not implemented here.
- **Prototype working precision.** Whether the 80.92/81.13 figures came from an
  80- or 120-digit context is not recorded in the audit. If 120, the assumption
  that 80 digits plus correct geometry suffices for Leaf 13 weakens.
