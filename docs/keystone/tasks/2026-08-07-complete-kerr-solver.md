# Task Creation: Complete the Kerr ringdown solver

## Goal

Complete one public, native-Windows nonlinear Kerr ringdown solver with evidence-graded spectral, linear-response, operator-stability, quadratic-ringdown, waveform, detector, inverse-inference, and final evidence-package capabilities.

## Context inspected

- `README.md`
- `docs/architecture.md`
- `docs/superpowers/specs/2026-08-06-public-solver-design.md`
- `docs/superpowers/plans/2026-08-06-public-capability-dag.md`
- `src/windows_solver/contracts.py`
- `src/windows_solver/planner.py`
- `src/windows_solver/providers.py`
- Existing test suite and the merged PR #2 spectral boundary
- Approved M00–M12 programme charter and prior scientific closure decisions
- Project-source, adjacent-literature, and terminology context supplied on 7 August 2026

## Requirements inventory

### Critical requirements

- Exactly one production provider per public capability.
- Release-domain scope is frozen before new scientific migration.
- Every artifact binds equations, conventions, inputs, code, runtime, numerical policy, upstream hashes, and evidence.
- Numerical execution, numerical evidence, and scientific conclusion remain separate.
- Linear pole shifts, quadratic amplitudes, and waveforms remain distinct.
- The quadratic pipeline preserves the forced order: first-order fields → derivative couplings → G⁽²⁾ source → forced solve → asymptotic amplitude.
- Publication verification cannot pass until operator stability, inverse inference, and detector inference all close.
- Public content contains no historical implementation labels.

### Non-functional requirements

- Python 3.12 public runtime; numerical backends may remain offline or hidden.
- Native PowerShell 5.1 and Ubuntu CI.
- Deterministic canonical JSON, content-addressed caching, resumable execution, and zero-work warm reruns.
- Fail-closed unsupported domains and evidence ceilings.
- Reproducible source, wheel, Windows, and container deliverables.

### Constraints

- Existing merged spectral provider remains the baseline and is not rewritten without a recorded replacement decision.
- Wolfram Language is an offline symbolic compiler/identity checker, not a mandatory runtime dependency.
- Tactical tasks may be tuned; scientific dependencies or closure gates require a Notion decision.
- No completion claim may rely only on legacy code or framework scaffolding.

### Unknowns and assumptions

- The exact release-domain modes, spins, parent pairs, theories, detector cases, and evidence profiles are frozen by TASK-001.
- Legacy artifacts not present in this checkout are treated as unverified until reconciled.
- Unresolved or contradicted physics is an acceptable final result when computation and evidence are complete.

## Iteration layering

### Iteration 1: Truthful intake and first public science

- Outcome: M01–M03 close; linear response and spectral fields are public, authenticated, and reusable.
- Deferred: operator continuum claims, physical quadratic amplitude, inference, waveforms, and detectors.

### Iteration 2: Independent operator and quadratic branches

- Outcome: M04–M06 close with bounded operator evidence and physical R⁺⁺₄₄.
- Deferred: joint response matrix and observational inference.

### Iteration 3: Integrated inference and signals

- Outcome: M07–M10 close with response matrix, injection/recovery, waveform, and detector artifacts.
- Deferred: only canonical aggregation and release hardening.

### Iteration 4: Verify and release

- Outcome: M11–M12 produce the publication-profile evidence package and reproducible release.

## Vertical slices

1. **M01 — Freeze scope and evidence baseline**
   - Value: removes ambiguous completion claims before implementation.
   - Dependencies: M00.
   - Acceptance: a machine-readable manifest reconciles every required result to artifacts, hashes, tests, licenses, merged code, and evidence ceilings.
   - Verification: manifest validator and human evidence audit.
   - Change Review focus: unsupported legacy claims and hidden scope expansion.

2. **M02 — Admit physical linear response**
   - Value: exposes validated multimode QNM shifts with component-local uncertainty.
   - Dependencies: M01.
   - Acceptance: one provider, golden comparisons, correlated disks, projective unresolved ledger, Windows/Ubuntu and warm-cache checks.
   - Verification: provider contract tests and independent numerical fixtures.
   - Change Review focus: mechanism conventions, uncertainty propagation, and evidence ceiling.

3. **M03 — Close spectral fields and genealogy**
   - Value: supplies eigenfunctions, co-modes, residues, κ continuation, and stable branch labels.
   - Dependencies: M01.
   - Acceptance: normalized field artifacts and ZDM/DM genealogy pass residual, continuation, matching, and completeness gates.
   - Verification: differential residuals, Wronskians, biorthogonality, NHEK matching, and branch invariants.
   - Change Review focus: branch swaps, normalization drift, and unsupported interpolation.

4. **M04 — Close operator stability**
   - Value: separates formal root evidence from finite-dimensional and continuum stability claims.
   - Dependencies: M03.
   - Acceptance: 2D Kerr operator, physical Gram/symmetrizer, root enclosure, resolvent, pseudospectrum, and truncation evidence are admitted with an honest ceiling.
   - Verification: spectral cross-checks, refinement ladders, enclosure tests, and perturbation-norm audits.
   - Change Review focus: continuum overclaim and nonphysical norms.

5. **M05 — Close first-order handoff and couplings**
   - Value: creates the authenticated physical inputs required by the quadratic source.
   - Dependencies: M03.
   - Acceptance: Hertz/ORG fields, G⁽¹⁾ residual, derivative tensors, selection rules, and coupling integrals pass frozen-domain gates.
   - Verification: symbolic identity checks and independent numerical convergence.
   - Change Review focus: gauge, tetrad, normalization, and angular–radial coupling completeness.

6. **M06 — Compute physical quadratic response**
   - Value: produces the forced second-order amplitude and R⁺⁺₄₄ rather than relabelling a linear 440 mode.
   - Dependencies: M05.
   - Acceptance: physical G⁽²⁾/Teukolsky source, forced solve, asymptotic extraction, convergence, and provider admission.
   - Verification: source residuals, boundary regularity, refinement, independent extraction, and normalization invariance.
   - Change Review focus: source physics, forced frequency Ω, azimuth M, and evidence provenance.

7. **M07 — Assemble physical response matrix**
   - Value: joins linear and quadratic observables without conflating them.
   - Dependencies: M02 and M06.
   - Acceptance: sparse ordered matrix, correlated covariance, rank, conditioning, and identifiability evidence.
   - Verification: block golden fixtures, finite-difference/analytic Jacobian comparison, and uncertainty checks.
   - Change Review focus: units, parameter ordering, covariance, and rank claims.

8. **M08 — Close physical inverse inference**
   - Value: tests whether authenticated physical mechanisms can be recovered and distinguished.
   - Dependencies: M07.
   - Acceptance: physical injection/recovery, posterior, evidence, model adequacy, admissibility, and rejection ledger.
   - Verification: blind holdouts, coverage checks, posterior predictive diagnostics, and adverse cases.
   - Change Review focus: prior dependence, misspecification, and identifiability overclaim.

9. **M09 — Close signals and waveforms**
   - Value: maps response artifacts to causal Ψ₄ and strain waveforms.
   - Dependencies: M07.
   - Acceptance: excitation, QNM reconstruction, Ψ₄→strain, tails/scattering/greybody effects, and uncertainty propagation.
   - Verification: analytic limits, independent fixtures, normalization checks, and causal reconstruction tests.
   - Change Review focus: excitation versus pole shifts and waveform normalization.

10. **M10 — Close detector inference**
    - Value: produces traceable ground/LISA observables and likelihoods.
    - Dependencies: M09.
    - Acceptance: authenticated PSDs, detector responses, SNR/likelihood, event-evidence validation, and one provider.
    - Verification: reference PSD hashes, independent response cases, injection tests, and platform parity.
    - Change Review focus: PSD provenance, units, windowing, and conditional claims.

11. **M11 — Produce canonical evidence package**
    - Value: proves the frozen study closes as one traceable artifact graph.
    - Dependencies: M04, M08, and M10.
    - Acceptance: Windows/Ubuntu cold runs, zero-work warm rerun, publication verification, independent claim audit, and export.
    - Verification: `solver verify RUN_ID --profile publication` plus cross-platform identity checks.
    - Change Review focus: weakest-evidence propagation and complete closure.

12. **M12 — Release reproducibly**
    - Value: gives users an installable, auditable solver rather than a development snapshot.
    - Dependencies: M11.
    - Acceptance: reproducible builds, clean-machine end-to-end runs, documentation, audit, and authorized release.
    - Verification: independent rebuild hashes and signed release evidence.
    - Change Review focus: package contents, licenses, public terminology, and release authorization.

## Risks and dependencies

- Legacy artifacts may be missing or inconsistent; quarantine them until TASK-001 proves provenance.
- Near-extremal continuation can preserve a small determinant residual while hopping branches; require genealogy invariants.
- Finite-dimensional pseudospectra can overstate continuum evidence; keep evidence layers separate.
- Quadratic-source conventions can silently change amplitudes; hash gauge, tetrad, normalization, and source definitions.
- Response matrices can be numerically full rank but physically unidentifiable; require prior-whitened and uncertainty-aware evidence.
- Detector likelihoods can hide upstream uncertainty; propagate the weakest evidence without promotion.
- The local tree lacks remote tracking; publication work must explicitly bind to merged GitHub main before committing.

## Handoff

Next module: `context-survey` for TASK-001, followed by `implementation` only after the release manifest and source receipts are frozen.

Detailed executable work is in `.tasks/NEXT.md` and `.tasks/BACKLOG.md`.

