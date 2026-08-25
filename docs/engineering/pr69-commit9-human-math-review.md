# PR69 Commit 9 — Human Mathematical Review Receipt v1

## Status

APPROVED MATHEMATICAL DECISION.

This receipt resolves the conceptual choices required before recovery/migration. It does not certify any numerical output produced under an earlier scientific identity.

## Identity

- Receipt schema: `windows-solver.m02-human-math-review/1`
- Decision identity: `m02-horizon-exterior-response-math/v1`
- Required successor horizon operation identity: `binary64-horizon-production/v3`
- Required determinant convention identity: `finite-radius-endpoint-wedge/raw-oriented/v1`
- Native horizon coordinate: common complex additive admittance increment `δB`
- Supplementary exact-reach coordinate: complex reflected amplitude `R`

## Governing conventions

1. Time/frequency, horizon-wave, determinant-row/column, and branch conventions must be bound by hash in every record.
2. The declared horizon line is

   `Y_R = Y_in + R Y_out,H`.

3. The canonical scientific determinant is the common finite-radius oriented endpoint wedge determinant

   `D_raw(ω,R) = det(Y_R, Y_∞) = D₀(ω) + R D_H(ω)`.

4. The horizon chart is

   `p_H = ω − m Ω_H`,

   `δB = 2 i p_H R / (1 + R)`,

   `R = δB / (2 i p_H − δB)`.

## Decision 1 — determinant normalisation

Use `D_raw` as the canonical scientific determinant.

A numerical evaluator may rescale it by `D̃ = f D_raw` only when `f` is holomorphic and nonzero on the complete root/response neighbourhood and the rescaling receipt binds `f`, the determinant orientation, basis normalisations, match point, equation identity, endpoint policy, and arithmetic tier.

The response quotient must use numerator and denominator from the same determinant representation. Mixing a raw numerator with a normalised denominator, or vice versa, is invalid.

## Decision 2 — horizon numerator and sign

At an unperturbed simple pole `ω₀`, the unit-`δB` response is

`h_B = (∂ω/∂δB)|₀ = −D_H(ω₀) / [2 i p_H(ω₀) D₀,ω(ω₀)]`.

The minus sign follows from implicit differentiation of `D(ω(δB),δB)=0`.

At `δB=0`,

`∂R/∂δB = 1/(2 i p_H)`

and

`∂R/∂ω = 0`.

Therefore no additional first-order chain term from the `ω`-dependence of `p_H` appears in `D_ω` at the base point.

A reversal of determinant orientation multiplies both `D_H` and `D₀,ω` by `−1`; the quotient is unchanged. A change in the definition of `R`, `δB`, `p_H`, or the Fourier convention is a new scientific identity.

## Decision 3 — whether `D_R` is explicit or exactly `−1`

Production policy: `D_R = D_H` explicitly.

Do not hard-code `D_R = −1` in the canonical path.

A locally normalised diagnostic may define

`F = D_raw/D_H = D₀/D_H + R`,

for which `F_R = +1`, or may negate `F`, for which `F_R = −1`. The sign is therefore a normalisation convention, not physical content. Such a diagnostic is valid only when `F_ω` is computed from that same `F` and the nonzero `D_H` condition is authenticated.

The raw explicit numerator is retained because it carries the horizon-channel mechanism and is required by the exact reachability relation `R_required = −D₀/D_H`.

## Decision 4 — `D_R` uncertainty

Because the canonical path uses explicit `D_H`, `D_R` requires a complex numerical uncertainty disk.

No finite-difference-in-`R` truncation term is required: affine dependence on `R` makes the derivative algebraically exact. The uncertainty is instead the numerical uncertainty in evaluating `D_H`, including:

- horizon and infinity endpoint data;
- angular/separation data;
- ODE propagation;
- match/readout consistency;
- asymptotic endpoint truncation;
- arithmetic/rounding;
- evaluation over the authenticated root disk.

A normalised diagnostic with exact `F_R = ±1` does not remove this uncertainty; it transfers the same information into `F_ω = D₀,ω/D_H`.

## Decision 5 — authenticated root uncertainty

A root uncertainty radius must never default to zero.

### SCREENED root evidence

A SCREENED root receipt may carry a predeclared empirical complex radius assembled from named, independently recorded diagnostics:

- Newton correction or residual-to-derivative estimate;
- cross-precision root shift;
- tightened ODE tolerance shift;
- endpoint/order shift;
- match/readout shift;
- angular-eigenvalue shift;
- branch/continuation repeat shift.

The receipt must state that this is empirical, not an interval enclosure.

### CERTIFIED root evidence

A CERTIFIED root receipt requires a validated complex enclosure proving a unique simple zero. The preferred route is complex interval/ball Newton or Krawczyk inclusion using validated determinant and derivative enclosures. A validated Rouché/argument-principle count is an acceptable independent alternative or cross-check.

The certificate must bind the root disk, determinant convention, branch, angular enclosure, endpoint-tail bound, validated ODE route, arithmetic library/version, and proof inequalities.

Existing roots may be reused only if an authenticated receipt supplies their actual radius under the current determinant identity. A zero residual/correction inserted by construction is not evidence.

## Decision 6 — `p_H` uncertainty

Construct

`P_H = Ω_root − m Ω_H(A,M)`

with complex/real ball arithmetic, where `Ω_root` is the authenticated root disk and `A,M` are the declared background-parameter balls.

For fixed exact background coordinates, the only background contribution is directed-rounding/transform uncertainty. If the spin or mass carries physical/input uncertainty, propagate it through the full interval image of `Ω_H`, not a one-ULP placeholder.

A simple radius inequality is

`rad(P_H) ≤ rad(Ω_root) + |m| rad(Ω_H)`.

The unit-`δB` response is admissible only when `0 ∉ P_H` and `0 ∉ D₀,ω`. Otherwise the result is promoted or recorded as an unbounded/chart-singular outcome. Exact corotation requires a separate chart and is outside this receipt.

## Decision 7 — exterior determinant absolute-error construction

Two evidence levels are approved and must not be conflated.

### A. SCREENED empirical determinant error

For each determinant sample `j`, retain named absolute discrepancy channels:

- `Δ_precision,j`: exact-compatible BF40/BF80 or binary64/BF40 same-point difference;
- `Δ_ode,j`: tightened ODE-control difference;
- `Δ_endpoint,j`: endpoint displacement and/or higher asymptotic-order difference;
- `Δ_match,j`: alternate regular match/readout difference;
- `Δ_angular,j`: higher-precision/refined angular-data difference;
- `ε_round,j`: directed rounding or arithmetic-ball radius where available.

The SCREENED sample radius is additive across distinct channels:

`ε_D,j^screen = s_precision Δ_precision,j + s_ode Δ_ode,j + s_endpoint Δ_endpoint,j + s_match Δ_match,j + s_angular Δ_angular,j + ε_round,j`.

Do not replace the sum by a global relative cover. Do not divide by a near-zero component to define a whole-atlas relative error.

The safety factors `s_*` are not universal mathematical constants. They must be frozen by a separate calibration receipt:

1. predeclare calibration and holdout sentinel sets;
2. compute independent BF120 or validated-ball reference values outside the survey pass;
3. choose each `s_*` by a stated conservative rounding rule that covers the calibration discrepancies;
4. verify the frozen factors on the disjoint holdout set;
5. fail closed if any reference error is not covered;
6. preserve the factors and all calibration data by hash.

The previous uncalibrated `64 × max(...)` construction is not approved as a theorem. It may be recovered only if the calibration procedure independently returns and validates that factor.

Retained binary64 predecessor samples may be consumed by BF40 only when exact compatibility is proved. BF40 computes BF40 work only; it must not silently recreate binary64 samples.

A SCREENED disk supports wording such as “empirically uncertainty-qualified.” It does not support “rigorously certified” or “interval-enclosed.”

### B. CERTIFIED determinant error

A CERTIFIED determinant sample requires:

- interval/ball angular data;
- endpoint initial-data balls with an explicit asymptotic-tail remainder;
- validated complex ODE propagation;
- interval/ball determinant evaluation at the declared match point;
- validated arithmetic and rounding;
- exact binding to the root disk, branch, mechanism, support, sample role, controls, endpoint policy, and operation identity.

Finite-difference or Richardson derivatives must be formed from the determinant balls, with analytic truncation remainder or validated nested-step enclosure. Quotient propagation is then performed entirely with complex ball arithmetic.

## Response-disk construction

Construct complex balls

- `B_R` for `D_H`;
- `B_ω` for `D₀,ω` over the authenticated root disk;
- `P_H` for `p_H`.

Then evaluate

`H_B = −B_R / (2 i P_H B_ω)`

by complex ball arithmetic.

Admission requires the denominator ball to exclude zero. All named input radii and their contribution to the final response radius must remain inspectable.

## Claim consequences

### Analytic claims now authorised

- local determinant-normalisation invariance under a common holomorphic nonzero factor;
- exact affine horizon reachability in `R`;
- the unit-`δB` numerator and minus sign above;
- mechanism-specific numerators with a common simple-root denominator.

### Numerical claim levels

- Central noncollinearity may be reported from validated central computations and independent canaries.
- Empirically uncertainty-resolved projective separation requires the frozen SCREENED model, vector-level correlated propagation, and positive lower Fubini–Study bounds for every claimed row.
- “Certified,” “rigorous enclosure,” or equivalent wording requires the CERTIFIED route.

## Migration consequences

1. All `binary64-horizon-production/v2` response records are scientifically stale because the numerator/normalisation and root/`p_H` uncertainty identity changes.
2. Preserve them as forensic evidence and possible numerical seeds only.
3. They may not be imported as terminal SCREENED/CERTIFIED records under `v3`.
4. Existing root centres may be reused only when a separate authenticated root-uncertainty receipt validates them under the current identity.
5. Existing exterior raw samples may be migrated only when the samples themselves and every compatibility field are present and authenticate. A queue entry without its provisional sample stage cannot recreate discarded work.
6. Recovery/migration may proceed after this decision is implemented and its static/mocked tests pass; scientific admission remains gated by the required calibration or certified evidence receipts.

## Literature basis

- Gesztesy, Latushkin, and Makarov, *Evans Functions, Jost Functions, and Fredholm Determinants*, Archive for Rational Mechanics and Analysis 186 (2007), DOI 10.1007/s00205-007-0071-7.
- Karambal and Malham, *Evans function and Fredholm determinants*, Proceedings of the Royal Society A 471 (2015), DOI 10.1098/rspa.2014.0597.
- Chen, Wang, and Chen, *Tidal response and near-horizon boundary conditions for spinning exotic compact objects*, Physical Review D 103, 104054 (2021), DOI 10.1103/PhysRevD.103.104054.
- Cano et al., *Parametrized quasinormal mode framework for modified Teukolsky equations*, Physical Review D 110, 104007 (2024), together with the 2026 erratum, Physical Review D 113, 069902, DOI 10.1103/88mw-35d4.
- Nedialkov, *Interval Tools for ODEs and DAEs*, SCAN 2006, DOI 10.1109/SCAN.2006.28.
- A verified method for bounding clusters of zeros of analytic functions, Journal of Computational and Applied Mathematics 199 (2007), DOI 10.1016/j.cam.2005.08.038.

## Required code review blocker

`TODO: [HUMAN NUMERICAL CALIBRATION REQUIRED — freeze and authenticate the SCREENED exterior safety factors on a predeclared calibration/holdout set, or supply validated determinant-ball evidence.]`
