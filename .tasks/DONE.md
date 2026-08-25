# Done

> Historical M02 records below preserve the scope under which they closed.
> PR #21 later replaced the 553-leaf, 87-selector, 174-row production contract
> with the canonical 212-leaf, 48-selector campaign and 57-row reduction
> contract. Current delivery state is recorded in `IN_PROGRESS.md` and the
> newest `WORK_LOG.md` entry.

## TASK-011: Build fail-closed M02 validation, admission, and operator closure commands
**Priority:** P1 | **Tags:** M02, provider, validation, tooling
**Assignee:** Codex | **Estimate:** 1 day | **Milestone:** M02

### Objective

Finish the installable M02 machinery and operator handoff while keeping the linear-response provider unavailable until the user's complete PowerShell evidence bundle passes admission.

### Acceptance Criteria

- [x] Validate exactly 553 produced leaves, zero missing leaves, governed unresolved IDs, complete checkpoint root identities reconciled to one 87-root spectral receipt, checkpoint-bound reducer centres/channels, 174 payload comparisons exactly bound to aligned projective rows, role ceilings, hashes, runtime lineage, and policy identity.
- [x] Provide PowerShell-friendly `validate`, `reduce`, `admit`, and `export` commands with deterministic machine-readable output and useful failure messages.
- [x] Prove smoke/partial bundles cannot register the provider; prove a structurally complete signed test bundle exercises the availability transition without claiming scientific evidence.
- [x] Keep exactly one provider owner, unrelated capabilities unchanged, and admission contingent on the external evidence receipt, an exact spectral-upstream receipt, plus detached expected admission ID rather than build completion.
- [x] Pass Windows-oriented command/path tests, Ubuntu tests, cold/warm cache, wheel content, manifest, compile, and head/tail/risk end-to-end smoke gates.

### Dependencies

- **Blocked by:** TASK-010
- **Blocks:** TASK-075

### Evidence Output

Installable fail-closed admission package and CLI; an explicit dynamic provider transition only for a complete admitted package; exact sparse 87-root upstream selection; PowerShell operator runbook; cold/warm cache, wheel, manifest, and head/tail/risk smoke gates; and a build-completion report that keeps scientific evidence pending.

### Verification

- `PYTHONPATH=src python -m unittest discover -s tests -v` — 225 passed.
- Predecessor hosted GitHub Actions run `31249917661` passed on `ubuntu-latest` and `windows-latest`, including full tests, wheel inspection, M02 admission/cache, campaign smoke, planning, admitted providers, and PowerShell 5.1 launcher parity; the PR head containing the campaign-to-spectral root reconciliation must repeat the same matrix.
- `python .tasks/validate_board.py`, `python tools/validate_release_manifest.py`, `python -m compileall -q src tools tests`, and `git diff --check` — passed.
- **Evidence ceiling:** Structurally complete signed test evidence only; no 553-leaf physical campaign, populated scientific atlas, or scientific claim. The default provider remains unavailable until the user's complete operator package passes admission.
- **Change references:** admission core `be706164cab2574f2f102f35f625ea72ddfe8430`; CLI/integration `dbb20779f8cca44ceff2a47be23f3853ec0c342b`; handoff/CI `5ecb2f050426650db504959c18b728e29320aadb`; cross-platform identity fixes `3580b73f432d808c4e032a1bb6d68b7d1ea730ac` and `2b09a9b48097c15fcae49c5bdeada3f914e8f7c8`; immutable admitted package `759b37f2faaad6056d94de6a86e4f8bc1c8e800f`; TaskPlanner/report closure `57e4d4ee1e779e299ad97413c19441755e57a774`.

### Review Focus

Complete/partial separation is fail closed; every campaign record carries its complete ω/angular/catalog-owner root identity and the 553 records reproduce one sealed 87-root set; every reducer centre/channel is bound to its authenticated checkpoint record; every final component is value/state-bound to its authenticated produced-record payload; every projective comparison is bound to its sealed reduction row; admission reconciles the campaign roots to the installed spectral payload before the package seals that provider/request/root-payload identity, and replay rejects upstream drift; serialized package loads require an independently preserved admission ID; that ID participates in the provider/cache identity; the admitted package is deeply immutable; provider registration is explicit and unique; native runtime identity is stable across Windows and Ubuntu; operator paths and CLI output are deterministic; scientific readiness is not inferred from build readiness.

### Plan

- Bound the exact 553-leaf campaign, 174-row reduction, and accepted 87-root spectral upstream to one immutable, hash- and lineage-validated admission package.
- Added deterministic `m02-validate`, `m02-admit`, and `m02-export` commands plus explicit `plan`/`run` admission input and exact sparse spectral selection.
- Proved partial rejection, structural full-bundle transition, cold/warm replay, packaging, PowerShell parity, and both hosted operating systems before closing software readiness.

---

## TASK-010: Build the empirical uncertainty and projective-reduction pipeline
**Priority:** P1 | **Tags:** M02, evidence, physics, tooling
**Assignee:** Codex | **Estimate:** 1–2 days | **Milestone:** M02

### Objective

Build deterministic uncertainty propagation and projective reduction that operates on user-supplied complete evidence, while validating the algorithms with synthetic and representative smoke inputs.

### Acceptance Criteria

- [x] Propagate signed-root, centred-step, refinement, continuation-path, and precision-ladder channels through the response/Richardson algebra.
- [x] Construct PSD component and cross-component empirical error Gram matrices from shared signed channels without statistical-covariance claims.
- [x] Compute the frozen 162 primary and 12 deep projective row schemas only when aligned inputs exist; partial smoke inputs return an explicit incomplete state, never a scientific classification.
- [x] Smoke-test head/tail/risk reductions, zero-containing calibrations, non-PSD rejection, unresolved propagation, and available independent holdouts.
- [x] Accept the complete external 553-leaf bundle later without code or threshold changes.

### Dependencies

- **Blocked by:** TASK-009
- **Blocks:** TASK-011

### Evidence Output

Digest-owned signed-channel ledgers, exact empirical-Gram recomputation, calibrated-normalized projective Jacobian propagation, exact 174-row planner, partial-honest reducer, exactly six synthetic/representative reductions, and zero-backend PowerShell handoff.

### Verification

- `PYTHONPATH=src python -m unittest discover -s tests` — 206 passed.
- `python .tasks/validate_board.py`, `python tools/validate_release_manifest.py`, `python -m compileall -q src tools tests`, `git diff --check`, and wheel-content inspection — passed.
- **Evidence ceiling:** Exact plans plus six synthetic/representative reductions only; no physical campaign, populated 174-row atlas, scientific admission, or provider availability.
- **Change references:** implementation `b9b952c3409146ab695df082662a13a922f6e03e`; review/CI remediation published on PR #5 as `6e60a94481c5d8f83026f56f54adeba285105a4b`.

### Review Focus

Each campaign stage owns a complete digest-bound signed-channel ledger; serialized Grams are exactly recomputed; projective uncertainty uses an explicit local `J G Jᵀ` diagnostic; partial evidence remains unclassified; authenticated package bytes survive Windows checkout unchanged.

### Plan

- Bound every signed channel to the stage component digest and rejected stale or injected evidence.
- Made every serialized empirical Gram recomputable and propagated it through a calibrated-normalized local Jacobian.
- Preserved six reductions, repaired cross-platform authenticated bytes/smoke tolerance, and passed the full build gate before activating TASK-011.

---

## TASK-009: Build the complete B′ batch planner and PowerShell production handoff
**Priority:** P1 | **Tags:** M02, provider, physics, tooling
**Assignee:** Codex | **Estimate:** 1–2 days | **Milestone:** M02

### Objective

Build one deterministic runner that can plan, execute, resume, validate, and merge all 553 B′ leaves when invoked by the user's PowerShell evidence workflow; Codex does not run the full campaign.

### Acceptance Criteria

- [x] Enumerate exactly 441 primary, 48 control, and 64 deep leaf IDs with no ambient Cartesian completion, including all seven mechanisms and exact direct-χ/Mκ provenance.
- [x] Provide machine-readable `plan`, selected `run`, `resume`, `validate`, and `merge` operations with atomic cohort checkpoints and clear PowerShell examples.
- [x] Enforce deep 80/120-digit triggers and sentinels, control-only claim ceilings, computed-but-unresolved semantics, and zero-missing full-bundle validation without executing all leaves here.
- [x] Smoke-test canonical head/tail plus predeclared risk-bearing middle leaves across primary/control/deep roles, all mechanism implementations, high spin, negative m, low signal, and precision promotion.
- [x] Reject partial or mixed-policy bundles as release evidence while preserving them as resumable operator outputs.

### Dependencies

- **Blocked by:** TASK-007, TASK-008, TASK-070
- **Blocks:** TASK-010

### Evidence Output

Exact 553-leaf campaign metadata, deterministic selected runner/checkpoints,
semantic result/precision/factory validation, authenticated immutable-byte
plugin handoff, safe CLI outputs, zero-work merge, frozen smoke, and runbook.

### Verification

- `PYTHONPATH=src:tools python -m unittest tests.test_linear_response_batches tests.test_linear_response_smoke tests.test_linear_response_precision -v` — 23 passed.
- `PYTHONPATH=src:tools python -m unittest discover -s tests -q` — 193 passed.
- `python .tasks/validate_board.py`, `python -m compileall -q src tools tests`, and `git diff --check` — passed.
- **Evidence ceiling:** All 553 leaves planned, none physically computed; exactly three recorded replays plus seven synthetic orchestration cases; no cache generation/download, scientific atlas, or provider admission.
- **Change references:** implementation `dd3d0c41568a8a4853723936d936fe68276a915f`; semantic/plugin remediation `f0819b0e3932461748676a4decac81dc01b75c79`; factory-provenance remediation `68f6d4323420587bf70161c9ea8ea7566fc3b6cd`.

### Review Focus

Stable factory name/module digest is plan/checkpoint/stage bound; capability
availability only grows by superset; validate/merge reject same-backend module
substitution; the imported code is exactly the once-verified bytes; provider
remains unavailable.

### Plan

- Captured factory-binding tamper, module substitution, capability downgrade, and verified-byte race as three focused failing tests.
- Bound factory provenance throughout the plan/checkpoint/stage/merge path and removed source-reopen TOCTOU without numerical work.
- Passed the required software gates and restored TASK-010 as sole Next.

---

## TASK-008: Build the two-path linear-response engine and representative slice
**Priority:** P1 | **Tags:** M02, provider, validation, tooling
**Assignee:** Codex | **Estimate:** 1–2 days | **Milestone:** M02

### Objective

Build both physical response execution paths behind the unavailable provider contract, then prove them with a small representative slice rather than a full evidence campaign.

### Acceptance Criteria

- [x] Consume exact spectral roots and compute horizon-admittance plus one exterior response through the common determinant/derivative boundary with native coordinates and complete lineage.
- [x] Expose deterministic cold-run, resume, and zero-work verified-cache APIs that the later batch runner can call on Windows or Ubuntu.
- [x] Smoke-test canonical head/tail and risk cases spanning low spin, near-extremal spin, a low-signal exterior case, and an adverse branch/convention case.
- [x] Compare available independent representative centres without promoting missing local uncertainty or requiring the full operator evidence bundle.
- [x] Keep the provider unavailable and reject partial smoke artifacts at admission.

### Dependencies

- **Blocked by:** TASK-006, TASK-007
- **Blocks:** TASK-009

### Evidence Output

Reusable two-path response engine with authenticated dual source/installed root mapping receipts, execution-time native diagnostic gates, strict canonical replay checkpoints, representative smoke receipts, cache proof, and PowerShell-callable command surface.

### Verification

- `PYTHONPATH=src:tools python -m unittest tests.test_linear_response_provider tests.test_linear_response_smoke tests.test_artifacts -v` — 25 passed.
- `PYTHONPATH=src:tools python -m unittest discover -s tests -v` — 177 passed.
- `python .tasks/validate_board.py`, `python -m compileall -q src tools tests`, and `git diff --check` — passed.
- **Evidence ceiling:** Authenticated replay/reduction of exactly five pinned rows only; no physical solve, cache generation, pilot rerun, response campaign, or provider admission.
- **Change references:** initial implementation `d4cad85e03cf496a68df6cc6860aeb8c5645ec75`; first review remediation `6eb90f7c13446453e3ba74418d553f7d2cb73c86`; lineage/diagnostic remediation `f12b806`; checkpoint-consistency remediation `84493d3`.

### Review Focus

Dual source/installed root identity receipts are plan/result/readout/checkpoint bound; native convergence requires truncation, resolution, alternate seed/path, and continuation agreement; checkpoint reuse verifies every raw installed identity plus authenticated baseline omega; provider remains unavailable.

### Plan

- Captured the rereview findings as three narrow regression methods before changing runtime behavior.
- Bound canonical source→installed mapping receipts, required all native diagnostic variants before convergence, and closed receipt-preserving checkpoint identity tampering.
- Passed the required software gates and restored TASK-009 as sole Next without numerical production.

---

## TASK-007: Build authenticated evidence intake for operator-run calculations
**Priority:** P1 | **Tags:** M02, evidence, validation, tooling
**Assignee:** Codex | **Estimate:** 1 day | **Milestone:** M02

### Objective

Build the strict import and validation boundary for evidence produced by the user's PowerShell workflow, without making legacy code or full evidence collection a production dependency.

### Acceptance Criteria

- [x] Define canonical manifests for partial smoke bundles and complete 553-leaf evidence bundles, with source hashes, exact leaf IDs, coordinate provenance, runtime lineage, and explicit missing-local-evidence fields.
- [x] Import and hash-bind the available independent pilot/golden, adverse, and eight cubic comparator-only fixtures as representative migration checks; do not invent the absent 147-component local ladders.
- [x] Authenticate runtime, producer source, Git-blob, and comparator identity provenance bindings bidirectionally.
- [x] Reject every Windows drive designator plus UNC/ADS path hazards before source access.
- [x] Reject malformed numerical-state types with one deterministic CLI JSON error and exit 2.
- [x] Keep full evidence collection outside this task; a partial smoke bundle must never satisfy release admission.

### Dependencies

- **Blocked by:** TASK-005, TASK-006
- **Blocks:** TASK-008, TASK-009

### Evidence Output

Versioned evidence-bundle schema with B′ contract SHA `e29c27ed5db8e45e93db66b85e76e0e3289f75afb761df0ac330c39bdc98eaf0`; authenticated runtime/source/blob/comparator bindings; strict safe paths and typed numerical state; representative receipt `ab93c8fb73abd39372f4890f7c2f129cc2b6f87211adae011a6fc0c12ac7a423`; PowerShell validation.

### Verification

- `PYTHONPATH=src python -m unittest tests.test_linear_response_evidence_intake tests.test_linear_response_contract -v` — 34 passed.
- `PYTHONPATH=src python -m unittest discover -s tests -v` — 160 passed.
- `python .tasks/validate_board.py`, `python -m compileall -q src tools tests`, and `git diff --check` — passed.
- **Evidence ceiling:** Structural intake and representative migration checks only; no response solve, reduction, complete operator evidence, or provider admission.
- **Change references:** implementation `35d7f39de46b125a8e0e01de8f8dfbb12df363ff`; review remediation `a4a722a72daf84f9eef49507c481db49fe1b0595`.

### Review Focus

Forged provenance bindings, Windows drive/UNC/ADS path rejection, malformed numerical-state types, deterministic CLI errors, comparator quarantine, fixture independence, and preservation of the evidence ceiling passed focused and full review.

### Plan

- Captured the reviewer findings as focused failing tests before changing validation.
- Bound runtime/source/blob/comparator provenance, rejected unsafe Windows namespaces, and type-checked numerical state.
- Passed focused/full software gates, updated the report, and restored TASK-008 as sole Next.

---


## TASK-070: Admit the 44-root exact-selector overlay for B′
**Priority:** P0 | **Tags:** M02, M03, provider, physics, evidence
**Assignee:** Codex | **Estimate:** 1–2 days | **Milestone:** M02

### Objective

Supply the 44 genuinely missing B′ background roots without replacing or widening the admitted 2,736-root base lattice.

### Acceptance Criteria

- [x] Compute the exact missing set: 28 primary roots and 16 deep Mκ-derived roots; controls add no roots.
- [x] Store the results as a separate hash-bound overlay consumed by the existing spectral owner, with exact direct-χ or source-Mκ identity and derived binary64 spin identity.
- [x] Preserve overtone genealogy through cohort continuation, angular overlap, independent schedules, reverse continuation, repeat polish, and refinement checks.
- [x] Prove exact union selection for all 87 B′ selectors and byte/hash immutability of the base catalog and receipt.
- [x] Keep the overlay evidence numerical: no interpolation, formal enclosure, DM/ZDM classification, mirror substitution, or unused-tower expansion.

### Dependencies

- **Blocked by:** TASK-069
- **Blocks:** TASK-009, TASK-012, TASK-074

### Evidence Output

Authenticated 44-root CSV `c4c61a1b73e850d537dba5f5eb947af100449aa2a1958a1ec8ea086f60ffe8e8`, strict receipt `93a2e7586878d9c84e32d19ed9e7ad44d03572a91640625c44501bfbc46a5525`, complete bound checkpoint `f5a0fb6c2ecadbb5b75c692f79f17093d8f37999c142db5ad6b87168b8759f71` with canonical results digest `704df4272793a586e55d9f9ba3ca6d7c55f464a06d9afebf00cb6fe4d03b9798`, exact-selector union tests, and release-manifest binding.

### Verification

- `PYTHONPATH=src:tools python -m unittest tests.test_spectral_extension tests.test_spectrum tests.test_linear_response_contract -v` — 56 passed, including eight-row head/tail/risk smoke recomputation and installed-provider reload.
- `PYTHONPATH=src python -m unittest discover -s tests -v` — 148 passed.
- `python .tasks/validate_board.py`, `python tools/validate_release_manifest.py`, `python -m compileall -q src tools tests`, and `git diff --check` — passed.
- Partial and complete checkpoint content mutations are rejected before backend work; zero-work replay reproduced the same 44-row CSV, receipt, and checkpoint hashes; an offline wheel contains both overlay resources.
- **Evidence ceiling:** Numerical continuation and genealogy evidence only; no external comparator, formal root enclosure, interpolation, or DM/ZDM classification.
- **Change references:** implementation commit `6e01e403a53c9dc592004bca688bb8e976f3157d`; overlap-floor remediation commit `38d702ea58cb98fa9d562126afda9ba6396832af`; representative smoke commit `3ff1262cc1666b51ea4985e6adc383ff503cf806`; checkpoint-integrity/numeric-order remediation commit `d2e96c6494ef9908be6c2a4b4807fbcb729f7c44`.

### Review Focus

Exact target equality, sparse-overlay provenance, cohort assignment, reverse/path agreement, base immutability, absence of unused roots, checkpoint result-content authentication, and receipt-consistent numeric-spin ordering were inspected and remediated.

### Plan

- Bound a canonical results digest inside partial and complete checkpoint envelopes and rejected content changes before backend work.
- Sorted same-mode overlay targets by numeric binary64 spin so receipt and bytes share one intuitive order.
- Regenerated, rebound, smoke-tested, and reran the complete acceptance stack without response-evidence work.

---

## TASK-069: Freeze the B′ 553-leaf M02 release domain
**Priority:** P0 | **Tags:** M02, provider, physics, evidence, architecture
**Assignee:** Codex | **Estimate:** 1 day | **Milestone:** M02

### Objective

Replace the rejected Cartesian M02 scope with one exact, typed B′ contract before numerical production.

### Acceptance Criteria

- [x] Encode the exact primary, control, and deep product sets: 441 + 48 + 64 = 553 response leaves, with no implicit Cartesian completion.
- [x] Encode 87 distinct background-root selectors and an exact 44-root missing-selector ledger; preserve the admitted 2,736-root lattice.
- [x] Freeze `K₀`, `K₁`, and `K₂₂` primary supports plus exploratory deep `K₂₂`: 162 primary and 12 deep comparisons.
- [x] Keep controls exterior-only and claim-negative; name negative-m positive-spin rows counterrotating.
- [x] Keep the eight retained cubic `220` rows comparator-only and outside production.
- [x] Require 553 produced and zero missing leaves at admission while allowing evidence-bearing `UNRESOLVED` leaves.
- [x] Bind exact Mκ identities, 80/120-digit policy, eight sentinels, evidence ceilings, and the Wolfram zero-residual receipt.

### Dependencies

- **Blocked by:** TASK-005, TASK-006
- **Blocks:** TASK-070

### Evidence Output

Typed B′ contract/schema, literal count tests, supersession record, Wolfram arithmetic receipt, and reconciled M02 execution plan.

### Verification

- `PYTHONPATH=src python -m unittest tests.test_linear_response_contract tests.test_spectral_extension -v` — 22 passed.
- `PYTHONPATH=src python -m unittest discover -s tests -v` — 134 passed.
- `python .tasks/validate_board.py`, `python tools/validate_release_manifest.py`, and `python -m compileall -q src tools tests` — passed.
- **Evidence ceiling:** Contract-only; provider remains unavailable and no numerical response/root artifact or immutable base-spectrum byte changed.
- **Change reference:** implementation commit `a3c40ddc7481a094bb3e8fc7d0db7ad4850b3615`.

### Review Focus

Exact role products, axis leakage, cubic exclusion, projective support counts, missing-versus-unresolved semantics, obsolete executable Cartesian targets, and base-spectrum immutability.

### Plan

- Replaced obsolete Cartesian tests with literal B′ role, selector, and comparison ledgers.
- Bound strict unavailable-provider admission to the exact B′ leaf set.
- Recorded the durable Wolfram receipt and the explicit supersession of the 3,303-root Cartesian plan.
- Handed the sparse 44-root overlay dependency to TASK-070.

---

## TASK-001: Freeze the release completion manifest and reconcile every claimed legacy/public result against actual artifacts, hashes, tests, and merged PRs
**Priority:** P0 | **Tags:** M01, evidence, architecture
**Assignee:** Codex | **Estimate:** 1–2 days | **Milestone:** M01

### Objective

Create the single release-domain manifest that defines what the solver must compute and proves the current state of every claimed input without trusting narrative status labels.

### Acceptance Criteria

- [x] Enumerate required modes, spins, branches, parent pairs, theories, waveforms, detector cases, platforms, and evidence profiles.
- [x] For every claimed result, record artifact location, SHA-256, generating code/commit, merged PR, tests, license, conventions, and strongest evidence state.
- [x] Classify each item as publicly admitted, validated legacy evidence, framework only, missing, invalid, or superseded; missing receipts fail closed.
- [x] Record unresolved scope questions as governance decisions or blockers rather than assumptions.

### Dependencies

- **Blocked by:** M00 project-control setup (complete)
- **Blocks:** TASK-002, TASK-003, TASK-004

### Evidence Output

`release_domain_manifest.json` and `docs/release-baseline.md` reconcile 14 claims, 17 available source receipts, and 10 explicitly missing receipts. The manifest SHA-256 is `697c92744e098fe409f481bcfa0ebeecfc61cd222291e36cd4158fbc5857b742`.

### Verification

- `python tools/validate_release_manifest.py` — passed; exact scope, claims, receipts, conventions, and blockers validated.
- `PYTHONPATH=src python -m unittest discover -s tests -v` — 110 tests passed.
- **Evidence ceiling:** This proves the release scope and evidence state were exhaustively declared against available records; it does not promote missing, comparator, framework-only, or retained evidence to production science.
- **Change reference:** commit `8aeaf5adb2667756b3623daa76f50720118fa5d2`; draft PR [#3](https://github.com/vbrodi23-lgtm/Kerr-QNM_Windows-Solver/pull/3).

### Review Focus

Look for legacy code being treated as a provider, unsupported evidence promotion, omitted release-domain coordinates, and private labels.

### Plan

- Inventory primary repository, merged-PR, retained-artifact, and supplied research-context evidence.
- Freeze the exact release domain and classify every claim without promoting external evidence to a provider.
- Admit a strict machine-readable manifest only after source receipts, ownership, conventions, and evidence ceilings validate.

---

## TASK-002: Bind source repositories, artifacts, licenses, and runtime receipts
**Priority:** P0 | **Tags:** M01, evidence, validation
**Assignee:** Codex | **Estimate:** 1–2 days | **Milestone:** M01

### Objective

Turn every manifest source into a reproducible receipt so later tasks consume immutable inputs rather than remembered locations.

### Acceptance Criteria

- [x] Record repository URL, commit/blob identity, artifact hash, license, runtime, and retrieval method for every required source.
- [x] Verify all available bytes against their recorded hashes and reject mutable or ambiguous aliases.
- [x] Identify unavailable inputs with an owner and explicit unblock action.
- [x] Store receipts in a machine-readable format covered by repository tests.

### Dependencies

- **Blocked by:** TASK-001
- **Blocks:** TASK-003, TASK-004

### Evidence Output

The manifest carries immutable local and external receipts, including exact comparator blob identities and SHA-256 values, plus an owner/action ledger for every unavailable source.

### Verification

- `python tools/validate_release_manifest.py` — passed with 17 authenticated available receipts and 10 fail-closed missing receipts.
- `PYTHONPATH=src python -m unittest tests.test_release_manifest -v` — strict receipt, hash, duplicate-key, non-finite, recursion, and size-limit cases passed.
- **Evidence ceiling:** Available bytes and recorded identities are authenticated; unavailable inputs remain blockers, and GPL comparator data remains outside production dependency closure.
- **Change reference:** commit `8aeaf5adb2667756b3623daa76f50720118fa5d2`; draft PR [#3](https://github.com/vbrodi23-lgtm/Kerr-QNM_Windows-Solver/pull/3).

### Review Focus

Check license compatibility, mutable URLs, local-only artifacts, and runtime gaps.

### Plan

- Normalize source identities and licenses.
- Implement or extend receipt validation.
- Test clean and tampered cases.

---

## TASK-003: Classify every existing module by public scientific responsibility
**Priority:** P0 | **Tags:** M01, architecture, evidence
**Assignee:** Codex | **Estimate:** 1–2 days | **Milestone:** M01

### Objective

Map each existing implementation to exactly one role: active provider, validator, comparator, extension, retired fixture, or out of release scope.

### Acceptance Criteria

- [x] Cover every scientific module and executable entry point named by TASK-001.
- [x] Assign at most one active production owner to each capability and record public input/output contracts.
- [x] Identify duplicate or conflicting implementations and state the replacement test required before any ownership change.
- [x] Prohibit retired/comparator code from production dependency closure.

### Dependencies

- **Blocked by:** TASK-001, TASK-002
- **Blocks:** TASK-004, TASK-005

### Evidence Output

The manifest ownership matrix covers every `src/windows_solver/*.py` module, every `tools/*.py` entry point, and `solver.ps1`, with only the problem-contract and spectral-core capabilities admitted.

### Verification

- `python tools/validate_release_manifest.py` — module inventory, unique ownership, registry consistency, and comparator quarantine passed.
- `PYTHONPATH=src python -m unittest tests.test_release_manifest.ReleaseManifestTests.test_module_ownership_covers_public_code_and_tools -v` — passed.
- **Evidence ceiling:** The matrix establishes implementation responsibility and quarantine boundaries; it does not independently validate the scientific correctness of a classified module.
- **Change reference:** commit `8aeaf5adb2667756b3623daa76f50720118fa5d2`; draft PR [#3](https://github.com/vbrodi23-lgtm/Kerr-QNM_Windows-Solver/pull/3).

### Review Focus

Look for scrapbook façade dependencies, hidden production comparators, and new physics misclassified as replacement code.

### Plan

- Inventory modules and dependency edges.
- Classify roles against public capabilities.
- Cross-check registry and quarantine conflicts.

---

## TASK-004: Freeze equations, conventions, normalizations, and evidence ceilings
**Priority:** P0 | **Tags:** M01, physics, evidence
**Assignee:** Codex | **Estimate:** 1–2 days | **Milestone:** M01

### Objective

Define the scientific identity required for cache keys and prevent later tasks from silently changing boundary conditions, gauge, tetrad, units, or normalization.

### Acceptance Criteria

- [x] Record equation IDs, boundary conditions, Fourier/sign conventions, tetrad, gauge, units, field and amplitude normalizations for every release capability.
- [x] Define numerical acceptance gates and maximum scientific claim for each artifact class.
- [x] Record corrected or disputed conventions as explicit invalidation/replacement decisions.
- [x] Bind the manifest fields into canonical identity tests.

### Dependencies

- **Blocked by:** TASK-001, TASK-002, TASK-003
- **Blocks:** TASK-005

### Evidence Output

The canonical convention register and evidence-ceiling matrix are hash-bound within the release manifest, with unresolved ORG/Hertz and cubic-EFT questions preserved as explicit blockers.

### Verification

- `python tools/validate_release_manifest.py` — equation, convention, normalization, evidence-ceiling, and blocker identities passed.
- `PYTHONPATH=src python -m unittest tests.test_release_manifest -v` — canonical identity and prohibited evidence-promotion cases passed.
- **Evidence ceiling:** The declared conventions and ceilings are frozen for identity and gating; unresolved formulations are not asserted as validated or production-ready.
- **Change reference:** commit `8aeaf5adb2667756b3623daa76f50720118fa5d2`; draft PR [#3](https://github.com/vbrodi23-lgtm/Kerr-QNM_Windows-Solver/pull/3).

### Review Focus

Check especially Ψ₄ signs, QNM time convention, ORG/Hertz normalization, forced-frequency labels, and detector units.

### Plan

- Extract conventions from code and receipts.
- Resolve or record conflicts without guessing.
- Add identity and evidence-ceiling validation.

---

## TASK-005: Admit the machine-readable release-domain manifest
**Priority:** P0 | **Tags:** M01, architecture, validation
**Assignee:** Codex | **Estimate:** 1–2 days | **Milestone:** M01

### Objective

Make the frozen completion scope executable so unsupported, missing, or overclaimed work is detected before scientific computation.

### Acceptance Criteria

- [x] Add a versioned manifest schema and strict parser to the public repository.
- [x] Validate capability coverage, coordinate completeness, source receipts, conventions, licenses, evidence ceilings, and milestone mapping.
- [x] Provide one canonical manifest fixture and negative fixtures for missing/duplicate/incompatible entries.
- [x] Close M01 only after human and automated reconciliation agree.

### Dependencies

- **Blocked by:** TASK-003, TASK-004
- **Blocks:** TASK-006, TASK-007, TASK-069

### Evidence Output

The repository contains the canonical manifest, immutable strict parser, CLI validator, negative tests, packaged-data binding, and human-readable M01 closure report.

### Verification

- `git diff --check` — passed.
- `python tools/validate_release_manifest.py` — passed.
- `PYTHONPATH=src python -m unittest discover -s tests -v` — 110 tests passed.
- Cross-platform manifest checkout regression — passed; Git enforces LF bytes before package build on Windows and Ubuntu.
- Clean wheel build/import — passed; wheel SHA-256 `cbfd6887ed07f186a6966a3093da2bb0e580a8402b53868855be6125240dea18`.
- Change Review — no blocking findings after remediation.
- **Evidence ceiling:** M01 validates scope-control machinery and packaging only; it changes no spectral bytes, scientific provider behavior, or evidence state beyond the two previously admitted capabilities.
- **Change reference:** commit `8aeaf5adb2667756b3623daa76f50720118fa5d2`; draft PR [#3](https://github.com/vbrodi23-lgtm/Kerr-QNM_Windows-Solver/pull/3).

### Review Focus

Ensure the manifest freezes required scope without promising science outside available evidence.

### Plan

- Define schema from TASK-001–004 outputs.
- Implement strict validation and fixtures.
- Run change review and update M01 only on full closure.

---

## TASK-006: Define the public linear-response artifact and provider contract
**Priority:** P1 | **Tags:** M02, provider, physics
**Assignee:** Codex | **Estimate:** 1–2 days | **Milestone:** M02

### Objective

Specify one field-native artifact for physical first-order complex QNM shifts, local covariance/disks, mechanism identity, and bounded multimode comparisons.

### Acceptance Criteria

- [x] Define payload keys, units, modes/spins, mechanism parameters, complex covariance, local uncertainty disks, and unresolved classifications.
- [x] Separate raw roots, pole shifts, projective reductions, and later response-matrix quantities.
- [x] Bind equations, conventions, numerical policy, runtime, upstream hashes, and evidence ceiling.
- [x] Reject unsupported mechanisms or coordinates before partial output.

### Dependencies

- **Blocked by:** TASK-005
- **Blocks:** TASK-007, TASK-008, TASK-069

### Evidence Output

`src/windows_solver/linear_response.py` defines the unavailable descriptor and strict request/payload/admission contracts. `src/windows_solver/payload_validation.py` dispatches candidate artifact validation. The example, design, implementation plan, and 19 focused tests bind direct-spin and `Mκ` sampling, all eight mechanisms, component-local and correlated covariance, uncertainty disks, projective reductions, completeness, lineage, and fail-closed semantics.

### Verification

- `PYTHONPATH=src python -m unittest tests.test_linear_response_contract -v` — 19 tests passed.
- `PYTHONPATH=src python -m unittest discover -s tests -v` — 129 tests passed.
- `python .tasks/validate_board.py` — passed before completion transition.
- `python tools/validate_release_manifest.py` — passed unchanged; manifest SHA-256 `697c92744e098fe409f481bcfa0ebeecfc61cd222291e36cd4158fbc5857b742`.
- Wolfram identities — simple-root tangent, `Mκ` to `a/M`, and `δB` to reflectivity inverse residuals all reduced to zero.
- Independent Change Review — no blocking findings after remediation of the covariance PSD and frozen-coordinate checks.
- **Evidence ceiling:** Contract-only. No response leaf was computed, the descriptor remains unavailable and unregistered, and M02 remains open. Full closure is blocked by absent high-spin/`Mκ` spectral roots, unauthenticated candidate pilots, and the missing frozen-domain covariance/recomputation bundle.
- **Change reference:** implementation commit `a12ef02f57038ac8a8c912381f1fe64c76237860`; draft PR [#4](https://github.com/vbrodi23-lgtm/Kerr-QNM_Windows-Solver/pull/4).

### Review Focus

Check field-native terminology, physical mechanism distinctions, exact frozen-coordinate coverage, and no atlas-wide uncertainty substitute.

### Plan

- Translate frozen manifest into an exact contract.
- Add red contract and identity tests.
- Review evidence boundary before migration.

---
