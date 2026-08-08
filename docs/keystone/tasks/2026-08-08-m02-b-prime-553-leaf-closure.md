# Task Creation: M02 B′ 553-leaf linear-response closure

## Goal

Build one admission-ready first-order Kerr QNM linear-response provider over a stratified 553-leaf general-relativity domain. It becomes publicly available only after the operator supplies a complete admitted evidence bundle. The software must preserve typed mechanism identity, component-local correlated empirical uncertainty, exact background-root provenance, and outcome-neutral projective results.

## Build-only execution amendment — 2026-08-08

The user clarified the operator boundary after TASK-070: Codex builds and smoke-tests the M02 machinery; the user performs the complete 553-leaf scientific evidence collection in PowerShell. This amendment supersedes any later instruction in this plan that assigns the full response campaign to Codex.

- Codex delivers the evidence importer, response engine, exact 553-leaf planner, resumable cross-platform batch runner, precision policy, uncertainty/projective reducer, fail-closed admission validator, PowerShell runbook, and representative head/tail/risk smoke evidence.
- Codex does not run all 553 response leaves, construct the final scientific atlas, or infer release conclusions from the smoke subset.
- The installed linear-response provider remains unavailable until a complete operator-produced bundle passes the exact 553-leaf, zero-missing, 174-row, lineage, uncertainty, and policy admission gates.
- TASK-071–TASK-074 are superseded as separate bulk campaigns. TASK-009 owns one generic runner that still plans every original leaf and mechanism; their computation moves to the operator workflow.
- The active build sequence after TASK-070 is TASK-007 → TASK-008 → TASK-009 → TASK-010 → TASK-011.
- Software readiness and scientific evidence completion are separate states and must be reported separately.

## Context inspected

- `src/windows_solver/linear_response.py`
- `src/windows_solver/data/kerr_qnm_roots_2736.csv`
- `src/windows_solver/data/kerr_qnm_lattice_receipt.json`
- `src/windows_solver/data/release_domain_manifest.json`
- `docs/superpowers/specs/2026-08-07-public-linear-response-closure-design.md`
- `docs/superpowers/plans/2026-08-08-m02-high-spin-spectral-extension.md`
- `.tasks/IN_PROGRESS.md`, `.tasks/BACKLOG.md`, and `.tasks/validate_board.py`
- The supplied project and adjacent-literature context, especially the canonical seven-spin atlas, overtone sensitivity, and near-extremal evidence ceilings
- Wolfram symbolic and exact-arithmetic checks performed on 2026-08-08

## Governing scope decision

The previous 1,287-leaf Cartesian contract and 3,303-root carrier expansion are rejected. They mix unsupported cubic production leaves into the GR provider and extend every spectral tower even though M02 consumes only a small typed selector set.

B′ is the controlling M02 release domain:

| Role | Modes | Sampling coordinates | Mechanisms | Leaves | Evidence role |
|---|---|---|---|---:|---|
| Primary | `220, 221, 222, 330, 331, 440, 441` | direct χ = `0.95, 0.97, 0.98, 0.99, 0.995, 0.997, 0.999, 0.9995, 0.9999` | horizon admittance plus all six exterior families | 441 | Production response and projective claims |
| Control | `(2,1,0), (2,−2,0), (3,2,0), (3,−3,0)` | direct χ = `0.95, 0.999` | six exterior families only | 48 | Counterrotation and response-concentration falsification; no horizon-transfer claim |
| Deep | `220, 221, 222, 210` | exact Mκ = `1/100, 1/200, 1/500, 1/1000` | horizon admittance, `alpha1`, `light_ring`, `throat_kappa` | 64 | Exploratory near-extremal response with a stricter precision ceiling |

The deep mode `210` is deliberate. It shares ℓ = 2 with the `22n` tower but is farther from corotation, so it separates overtone effects from a generic high-spin or same-ℓ effect. At positive spin, negative-m controls are counterrotating modes, not mirror modes.

The deep exterior subset contains the three strongest near-horizon tracking families. `alpha_half` remains in the primary block as the intermediate family; `fixed_r3` and `alpha0` remain exterior controls away from the horizon.

The eight retained parity-even cubic `220` rows remain authenticated comparator evidence at χ = `0, 0.3, 0.5, 0.7`. They are outside the 553-leaf production domain and cannot be extrapolated onto the high-spin grid.

## Exact arithmetic and root dependency

The count ledger is exact:

- Primary: `7 × 9 × 7 = 441`.
- Control: `4 × 2 × 6 = 48`.
- Deep: `4 × 4 × 4 = 64`.
- Total: `441 + 48 + 64 = 553`.

There are 87 distinct background-root selectors:

- 63 primary selectors;
- 8 control selectors;
- 16 deep selectors.

Only 44 selectors are absent from the admitted 2,736-root lattice:

- 28 primary roots: 6 for ℓ = 2, 4 for ℓ = 3, and 18 for ℓ = 4;
- 0 control roots;
- 16 deep roots.

The admitted 2,736-root lattice remains immutable. TASK-070 adds a separate hash-bound 44-root M02 overlay under the existing spectral owner; it does not replace the base lattice with a sparse object or compute 523 unused roots.

For q = Mκ,

- horizon gap `s = 2q/(1−2q)`;
- spin `χ = √(1−s²)`;
- inverse `q = √(1−χ²) / (2(1+√(1−χ²)))`.

Wolfram reduced the composed inverse to zero. The four derived spins are approximately `0.999791731748236`, `0.999948983496128`, `0.999991935581424`, and `0.999997991973920`.

## Projective result sets

Primary leaves feed three declared supports at each of nine direct spins:

- `K₀ = (220, 330, 440)`, calibrated on `220`;
- `K₁ = (221, 331, 441)`, calibrated on `221`;
- `K₂₂ = (220, 221, 222)`, calibrated on `220`.

Each support compares horizon admittance with each of six exterior families, producing `3 × 9 × 6 = 162` primary projective rows.

Deep leaves feed exploratory `K₂₂` comparisons between horizon admittance and the three deep exterior families, producing `4 × 3 = 12` deep projective rows. Control leaves produce diagnostic and falsification ledgers only.

Every projective row is outcome-neutral. A zero-containing calibration disk or failed bound produces an explicit `UNRESOLVED` result. It does not become missing and does not block admission after the required computation and evidence record exist.

## Requirements inventory

### Critical requirements

- Exactly 553 typed response leaf IDs and an empty missing list at admission.
- Missing computation and computed-but-unresolved physics remain different states.
- Native horizon coordinate is common additive `δB`; reflectivity remains a labelled chart conversion only.
- Production scope contains seven GR mechanisms and excludes cubic-EFT production leaves.
- The 44-root overlay is solved at exact target binary64 spins with source-rational provenance; interpolation and symmetry relabelling are forbidden.
- Branch genealogy is cohort-based. Simultaneous overtone matching is required when continuation can collide or jump.
- Component disks and cross-component matrices are derived from shared signed numerical error channels. They are empirical error Gram matrices, not statistical covariance estimates.
- Provider admission permits governed `UNRESOLVED` leaves but rejects missing, malformed, duplicated, or unexecuted leaves.

### Non-functional requirements

- One installed provider owner per capability.
- Deterministic canonical artifacts, resumable batches, atomic publication, and zero-work verified cache reuse.
- CPython 3.12 package; offline numerical dependencies do not leak into the installed runtime.
- Windows and Ubuntu parity, full lineage hashes, and release-manifest reconciliation.
- No threshold may be tuned after inspecting whether a mechanism is supported or contradicted.
- Every numerical batch must smoke-test its canonical head and tail plus predeclared risk-bearing middle cases before and after full production. Risk cases include extrema of conditioning/genealogy/error diagnostics and the deepest or highest-spin coordinates. Reports must identify the sampled leaf/root IDs and record independent backend recomputation plus installed-provider reload, not merely aggregate test counts.

### Constraints and evidence ceilings

- The base 2,736-root lattice and its 392 external comparisons remain unchanged.
- The 44-root overlay is residual- and genealogy-validated numerical evidence, not a formal root enclosure or DM/ZDM proof.
- The primary block can support release-domain projective conclusions.
- The control block can falsify concentration or expose branch/provenance errors; it carries no positive horizon-transfer claim.
- The deep block is exploratory near-extremal evidence with no external comparator and no exact-extremal extrapolation.
- Cubic evidence remains comparator-only.

## Precision policy

Primary and control leaves begin in the existing binary64 path. Deep leaves begin with the same path and record two condition amplifiers: the angular-eigenvalue separation condition and the centred-difference cancellation ratio.

A deep leaf is promoted to 80-decimal-digit arithmetic if any of these precommitted gates fires:

- the condition amplifiers predict fewer than ten reliable decimal digits;
- step-halving or Richardson centres disagree by more than one quarter of the provisional local disk;
- repeat-polish, angular-refinement, or independent continuation paths exceed their frozen ceiling;
- a denominator or calibration disk contains zero because of numerical, rather than physical, width.

A promoted leaf is repeated at 120 digits when the 80-digit self-refinement does not fit inside the provisional disk. It is accepted only when the 80/120-digit discrepancy is enclosed by the final empirical disk; otherwise it is recorded `UNRESOLVED` with the precision ladder attached.

Eight fixed sentinel leaves—horizon `220` and throat-κ `222` at all four Mκ values—run at 80 digits even when no trigger fires. Any sentinel false negative invalidates the trigger policy before production admission.

## Iteration layering

### Iteration 1: Freeze scope and roots

- Outcome: B′ is the only M02 contract and all 87 root selectors resolve through the base lattice plus the authenticated 44-root overlay.
- Tasks: TASK-069, TASK-070.
- Deferred: response computation.

### Iteration 2: Prove and scale the response path

- Outcome: independent fixtures and a two-mechanism `220` slice prove the provider, then all 441 primary leaves are computed in three reviewable batches.
- Tasks: TASK-007, TASK-008, TASK-009, TASK-071, TASK-072.
- Deferred: controls, deep precision, final uncertainty aggregation.

### Iteration 3: Falsification and deep evidence

- Outcome: all 48 controls and 64 deep leaves are computed with typed roles and the precision ladder.
- Tasks: TASK-073, TASK-074.
- Deferred: final provider admission.

### Iteration 4: Uncertainty, ledgers, and admission

- Outcome: shared signed-error channels produce component disks and correlated error Gram matrices; all projective rows and completeness ledgers are published; one provider is admitted.
- Tasks: TASK-010, TASK-011.

## Vertical slices

1. **TASK-069 — Freeze B′ and retire the Cartesian contract**
   - Value: makes every later count and selector mechanically auditable.
   - Dependencies: TASK-005, TASK-006.
   - Acceptance: exact role axes, 553 leaf IDs, 87 selectors, 44 missing roots, 174 projective rows, cubic comparator-only status, and outcome-neutral completeness rules are encoded in contract tests and documentation.
   - Verification: focused contract tests, literal count tests, Wolfram receipt, full suite, board validator.
   - Review focus: axis leakage, unsupported cubic promotion, and missing-versus-unresolved semantics.

2. **TASK-070 — Admit the 44-root M02 spectral overlay**
   - Value: removes the smallest sufficient upstream dependency without weakening the base lattice.
   - Dependencies: TASK-069.
   - Acceptance: all 44 exact target roots pass residual, angular refinement, repeat polish, independent path, reverse continuation, and branch assignment gates; base and overlay select all 87 roots exactly.
   - Verification: overlay builder/selection tests, full spectral tests, artifact hashes, full suite.
   - Review focus: branch jumps, sparse-overlay provenance, and base-lattice immutability.

3. **TASK-007 — Authenticate independent golden and adverse fixtures**
   - Value: creates migration comparators without making legacy code a production dependency.
   - Dependencies: TASK-005, TASK-006.
   - Acceptance: canonical 147-component central-value overlap, available local ladders, adverse fixtures, and eight cubic comparator rows are hash-bound; absent local uncertainty is recorded missing rather than reconstructed.
   - Verification: fixture schema/hashes, independence scan, comparator tests.
   - Review focus: legacy global-cover leakage and production imports from fixture code.

4. **TASK-008 — Prove one two-mechanism `220` slice**
   - Value: validates both horizon and exterior execution paths before scale-up.
   - Dependencies: TASK-006, TASK-007.
   - Acceptance: `(220, χ=0.95)` horizon and fixed-r3 leaves match independent fixtures inside local disks, persist canonically, reject wrong lineage, and warm-cache with zero provider work.
   - Verification: focused provider, cache, tamper, and golden tests.
   - Review focus: determinant derivative, native coordinates, and fixture isolation.

5. **TASK-009 — Compute primary batch A**
   - Value: delivers horizon, fixed-r3, and alpha0 responses for every primary mode and spin.
   - Dependencies: TASK-007, TASK-008, TASK-070.
   - Acceptance: exactly 189 leaves with resumable batch receipts and complete per-leaf diagnostics.
   - Verification: 189-ID equality, batch restart, independent overlaps, full suite.
   - Review focus: missing leaves, partial publication, and policy drift.

6. **TASK-071 — Compute primary batch B**
   - Value: adds intermediate and light-ring tracking responses.
   - Dependencies: TASK-009.
   - Acceptance: exactly 126 alpha-half and light-ring leaves; primary running total is 315.
   - Verification: exact ID/count audit, refinement ladders, overlap fixtures, full suite.
   - Review focus: low-signal light-ring behaviour and local rather than atlas-wide uncertainty.

7. **TASK-072 — Complete the 441-leaf primary block**
   - Value: adds the strongest near-horizon exterior families and closes all primary supports.
   - Dependencies: TASK-071.
   - Acceptance: exactly 126 alpha1 and throat-κ leaves; primary set equals all 441 declared IDs.
   - Verification: exact completeness audit, batch receipts, projective-input alignment, full suite.
   - Review focus: κ-scaled support identity, branch continuity, and zero-containing responses.

8. **TASK-073 — Compute the 48-leaf control block**
   - Value: tests whether claimed concentration is generic and catches illegal mirror/symmetry substitution.
   - Dependencies: TASK-072.
   - Acceptance: exactly 48 direct computations at the declared positive spins; each row is labelled control-only and carries no horizon-transfer claim.
   - Verification: mode/spin identity tests, no-symmetry-substitution tests, control ledger audit.
   - Review focus: negative-m terminology, falsification neutrality, and claim leakage.

9. **TASK-074 — Compute the 64-leaf deep block**
   - Value: tests overtone and corotation sensitivity in a quarantined precision-hostile regime.
   - Dependencies: TASK-070, TASK-073.
   - Acceptance: exactly 64 attempted computations, all trigger and sentinel records present, no missing leaf, and unresolved precision outcomes retained honestly.
   - Verification: precision-trigger tests, 80/120-digit ladders, sentinel audit, exact Mκ identity, deep evidence ceiling.
   - Review focus: arbitrary-precision trigger integrity and exact-extremal overclaim.

10. **TASK-010 — Propagate shared numerical uncertainty**
    - Value: replaces the legacy global multiplier with local disks and correlated vector-level error geometry.
    - Dependencies: TASK-007, TASK-009, TASK-071, TASK-072, TASK-073, TASK-074.
    - Acceptance: signed shared-error channels generate PSD component and cross-component empirical error Gram matrices; holdout/refinement discrepancies are covered; no statistical interpretation is claimed.
    - Verification: algebraic propagation tests, PSD/marginal checks, coverage audit, adverse cases.
    - Review focus: signed coefficients, shared-root correlations, and covariance terminology.

11. **TASK-011 — Admit the provider and close M02**
    - Value: publishes the complete, uncertainty-qualified linear response as one reusable capability.
    - Dependencies: TASK-010.
    - Acceptance: 553 produced leaves, zero missing leaves, governed unresolved list, 162 primary and 12 deep projective rows, one registered provider, Windows/Ubuntu parity, cold/warm cache, export, and reconciled release evidence.
    - Verification: focused and full suites, manifest validator, wheel/import test, platform CI, independent change review.
    - Review focus: evidence promotion, provider uniqueness, projective degeneracies, and public wording.

## Risks and dependencies

- **Root genealogy:** small residuals can accompany overtone branch jumps. Mitigation: cohort assignment, angular overlap, independent schedules, and reverse continuation.
- **Sparse scope confusion:** a 44-root overlay can be mistaken for a replacement lattice. Mitigation: separate artifact identity, immutable base hashes, union selection owned by one provider.
- **Deep precision cost:** arbitrary precision can expand without control. Mitigation: measured triggers, fixed sentinels, two precision tiers, and fail-closed unresolved outcomes.
- **False statistical language:** deterministic numerical errors can be misrepresented as stochastic covariance. Mitigation: store and document empirical error Gram provenance and forbid posterior interpretation at M02.
- **Outcome tuning:** projective thresholds can be adjusted after results appear. Mitigation: freeze thresholds and completeness rules in TASK-069 before response batches.
- **Comparator leakage:** cubic or legacy global-cover evidence can enter production. Mitigation: comparator-only schema roles and production import tests.

## Handoff

Next module: `implementation` for TASK-069. Its first check is to replace the current 3,303-root and 1,287-leaf red contracts with literal B′ role/count tests while keeping the provider unavailable.

## Keystone checkpoint

- Active sequence: Task Creation for M02 B′.
- Satisfied gates: live repository and TaskPlanner inspected; B′ axes resolved; exact counts and κ inverse certified by Wolfram; implementation slices, dependencies, verification, risks, and evidence ceilings defined.
- Next required skill: `implementation`.
- First next check: confirm TASK-069 is the sole In Progress item and observe the obsolete Cartesian tests fail before rewriting them.
- Continuation action: stop at the project-management boundary; implementation requires a separate execution instruction.
- Todo tail: Next / upcoming task: TASK-069 — freeze B′ and retire the Cartesian contract.
