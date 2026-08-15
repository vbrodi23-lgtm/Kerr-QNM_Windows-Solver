# Handover — PR #46 software completion and evidence boundary

This note supersedes the state and next-step sections of
`2026-08-15-horizon-rewrite-handover.md`. That earlier note remains the history
of the prototype and initial implementation.

## Current status

- Repository: `vbrodi23-lgtm/Kerr-QNM_Windows-Solver`
- Pull request: #46, open as a draft against `main`
- Branch: `claude/read-this-5em1in`
- TaskPlanner authority: `TASK-079` in `.tasks/IN_PROGRESS.md`
- Software repair: implemented and passing local and hosted software gates
- Scientific release admission: blocked, intentionally and explicitly

The branch must remain draft. The software now fails closed around the known
mechanisms, but no native Leaf 13 calibration/root receipt, human mathematical
review receipt, or independent high-precision reference fixture exists yet.

## What the branch now enforces

### Horizon graph and geometry

The horizon path owns a real-inner tortoise contour,

```text
r_*(rho) = rstar_match + rho,  dr_*/drho = 1,  rho < 0,
```

separate from the frequency-aligned outer contour. A geometry-first gate checks
exterior radius, imaginary-radius tolerance, monotone approach to the horizon,
maximum horizon distance, and both horizon series at a bounded candidate set.
Two adequate endpoints are mandatory before any homogeneous ODE starts.

Production then uses three independent solutions: infinity-outgoing to match,
horizon-ingoing to match, and horizon-outgoing to match. The mixed
match-to-inner Xup leg is absent from `evaluate_horizon_determinant` and is
forbidden there by static CI. The two horizon columns are independently scaled
and solved at match, with basis condition, backward-error, carrier, and
reconstruction diagnostics retained.

### Numerical policy and coordinate containment

Working precision is separate from the scientific correction target. Both the
80- and 120-digit tiers use correction tolerances of 1e-18 at base and 1e-20 at
refinement; 120 digits provide guard precision rather than imposing 1e-102 ODE
accuracy. Coordinate and homogeneous ODE tolerances are separate.

Coordinate maps start directly from the matching radius, verify the tortoise
identity, and construct only the needed outer or roughly -100 real-inner span.
The early coordinate-stall failure now records current and target rho, span
fraction, RHS and accepted/rejected steps, minimum and last steps, current
complex radius, and coordinate-identity residual.

### Determinant and root authentication

The horizon determinant carries an absolute error certificate. Endpoint,
control, raw/normalised-equivalence, and optional same-frequency precision
discrepancies remain absolute quantities and are combined by the declared
safety factor. Missing evidence remains absent rather than being encoded as
zero.

The authenticated derivative uses the real-axis h/2 estimate; h, 2h, and ih
provide disagreement, and the h/2 samples provide the propagated determinant
error. One constructor derives the positive lower bound. Bounded exhaustion is
`FINITE_DIFFERENCE_NOISE_LIMIT`; a small central determinant whose error blocks
acceptance is `DETERMINANT_UNCERTAINTY_TOO_LARGE`.

Newton damping, candidate ranking, best-iterate retention, and final acceptance
compare error-inclusive determinant bounds. The complete closed certificate is
transported through Julia responses and failures, Python parsing, readouts,
caches, checkpoints, solved-leaf receipts, campaign reports, and progress.
The exterior path retains its historical unauthenticated behavior and identity.

### Calibration and admission

The benchmark and calibration tools share one package-owned harness. Their
receipts bind source, manifest, and policy identities and use the worker's
canonical determinant-error accessor. The PowerShell wrapper rejects malformed
or incomplete evidence.

The committed controls are deliberately named a `provisional promoted control
profile` with `calibration_status = "UNMEASURED"`. Release admission rejects
that status. Nothing in this PR calls those values calibrated.

## Verification completed

Local verification at the final software code checkpoint:

- `PYTHONPATH=src python -m unittest discover -s tests -q` — 730 tests passed,
  7 skipped
- focused worker and numerical-control contract tests — passed
- `python .tasks/validate_board.py` — passed
- `python tools/validate_release_manifest.py` — passed
- `python -m compileall -q src tests tools` — passed
- `git diff --check` — passed

Hosted workflow run `31891628648` on code commit `74f4181` passed:

- Ubuntu Python/package/provider gates
- Windows Python/package/provider/PowerShell parity gates
- pinned Julia 1.10.11 project materialization and precompile
- complete vendored GSN unit suite
- executable worker finite-difference/root-authentication specification
- executable shared Leaf 13 harness specification

This is software and internal numerical-contract evidence. It is not a native
Leaf 13 scientific receipt.

## Required evidence still absent

Do not mark the PR ready or merge it as scientifically admitted until all of
the following exist and are reviewed:

1. Fixed Leaf 13 determinant at 80 digits with verified endpoints, all three
   propagation legs, finite coefficients, determinant error, and basis gates.
2. Leaf 13 root with error-aware correction at or below 1e-18 and explicit
   derivative/error evidence.
3. A 120-digit coordinate-map receipt reaching its endpoint without stall.
4. The bounded five-mode regression set from the completion plan.
5. A reviewed calibration receipt and committed measured control profile.
6. Human review of carrier signs, branch convention, basis-column order,
   horizon normalization, and the Cinc/Cref minus reflectivity chart.
7. An independently generated high-precision reference fixture.

Do not start the 212-leaf campaign to obtain these gates. Run only the bounded
Gate 1 through Gate 4 sequence documented in
`docs/superpowers/plans/2026-08-15-pr46-horizon-detector-completion.md`.

## Handover invariant

The implemented repair guarantees that the known invalid contour, mixed Xup
leg, digit-derived impossible tolerance, coordinate micro-step stall, and
unresolved tiny determinant cannot silently produce the previous resource
failure or a solved receipt. Any remaining limitation must terminate with a
specific numerical diagnosis. Scientific correctness and calibrated production
readiness remain separate evidence gates.
