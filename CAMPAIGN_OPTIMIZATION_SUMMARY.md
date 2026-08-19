# Campaign Optimization: Adaptive Response Ladder and Promoted-Horizon Uncertainty

## Summary

The M02 solver's Kerr root engine and branch-continuation mathematics are functioning correctly. Current production campaign testing revealed two architectural inefficiencies:

1. **Promoted-exterior cost model**: The default response calculation routes all promoted components (binary64 failures triggering 80-digit promotion) through a universal 17-readout full ladder (±ε, ±iε across four epsilon levels, with PRIMARY/TRUNCATION/RESOLUTION diagnostics). Single exterior light-ring components at a/M = 0.9999 consume 4–7 hours under this protocol, while the underlying physics is determined within the first baseline root and derivative evaluation. The full ladder is mathematically sound for validation but operationally unacceptable as the default production path.

2. **Promoted-horizon uncertainty contract violation**: The nine analytic promoted-horizon responses in the current checkpoint are labeled `UNCALIBRATED_ANALYTIC_RESPONSE` but published with zero uncertainty (disk radius = 0, all error channels = 0, usable = true). An uncalibrated component must propagate evidence of its calibration-pending status into response uncertainty, not present itself as an exact point in projective geometry.

Both issues are architectural, not mathematical. The solver recovers from binary64 failures correctly and computes roots with full precision. The fixes require:
- Restructuring promoted-exterior calculation to use direct determinant/derivative evaluation as the production default, reserving the expensive ladder for risk-selected validation.
- Propagating PRIMARY/TRUNCATION/RESOLUTION disagreement into the analytic horizon response uncertainty model.
- Repairing horizon-endpoint selection and exterior-response backtracking to handle near-extremal cases where current fixed limits fail.

This PR implements the restructured production paths, adaptive control policies, and closed uncertainty model. It does not change the mathematical engine, contracts, or validation machinery; those remain in place for verification and publication.

## Actions

### 1. Restructure promoted-exterior production path
- Replace the default 17-readout full-ladder calculation with: authenticated baseline root → direct determinant derivative (or variational exterior derivative) → complex frequency-shift response → selected finite-amplitude validation on risk-identified rows.
- Reserve the full ±ε, ±iε, four-level ladder for: risk-selected sentinel rows, disagreement cases, and publication validation rows (not default production).
- Add an adaptive intermediate BigFloat tier at approximately 32–48 decimal digits, positioned between binary64 failure and 80-digit promotion.
- Replace fixed ρ_out = 5000 with nearest-adequate infinity endpoint selection (convergence-driven).
- Implement adaptive ODE tolerances derived from required reliable digits (preflight prediction) rather than fixed global policy.
- Add durable checkpointing after every signed root evaluation and finite-amplitude readout.

### 2. Close promoted-horizon uncertainty gap
- Propagate uncertainty through the analytic horizon formula using: PRIMARY determinant and derivative errors, fixed-root TRUNCATION disagreement, fixed-root RESOLUTION disagreement, and independent derivative comparison (if available).
- Ensure zero uncertainty in response propagation means mathematically exact evaluation, not "the expensive finite-amplitude ladder was deferred."
- Update the promoted-horizon response contract to carry nonzero uncertainty disk (radius and relative radius derived from observed disagreements) instead of publishing as an exact point.

### 3. Repair horizon-endpoint adaptive selection
- Replace the fixed candidate list (ρ ∈ {−10, −25, −50, −75, −100}) with adaptive depth generation that extends until either two endpoints pass verification or a declared coordinate floor is reached.
- Implement best-prefix or least-term series truncation at each candidate ρ depth, allowing order adaptation independent of depth.
- Distinguish between three separate failure modes: insufficient series order, insufficient arithmetic precision, insufficient geometric depth.
- Enable selective 120-digit promotion only when the preflight and endpoint diagnostics specifically demonstrate precision limitation (not for geometric or order defects).

### 4. Implement exterior-response safe-subset backtracking
- Detect when the ε ladder crosses into binary64 noise floor (finest levels become unresolved while coarse levels remain valid).
- Automatically backtrack to the finest consecutive ε subset where signed displacements remain resolved above noise floor.
- Perform Richardson/Holdout reduction on the safe subset; apply selective precision promotion only to signed roots still limited by root error.
- Record which fine levels were excluded; retain NOISE_FLOOR diagnosis only when no defensible safe subset exists.
- Enlarge ε before increasing arithmetic precision in recovery attempts.

### 5. Update campaign strategy and projective result scope
- Restructure the immediate campaign to prioritize K0 = {220, 330, 440} primary leaves across four baseline spins and all four exterior mechanisms (60 total leaves).
- Execute only K0 until complete and validated; defer K1 {221, 331, 441} and K22 {220/221/222 comparisons} until promoted-exterior architecture is repaired.
- Defer all control and deep-precision rows from the immediate scope.
- Update ETA and risk models to account for new production-path costs (expect significant reduction from current 4–7 hour per-component overhead).

### 6. Preserve working validation and fail-closed machinery
- Retain the full complex ladder, two-endpoint horizon verification, and existing fail-closed gates as verification/publication machinery (not removed, only repositioned from default production).
- Maintain binary64/BigFloat promotion triggers and precision-selection criteria.
- Keep all existing test coverage and regression detection.
