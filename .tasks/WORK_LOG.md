# Work Log

Add the newest completed task or milestone-control entry immediately below this heading.

## 2026-08-19 — TASK-079 adaptive recovery implementation ready for operator review

- **Task:** TASK-079 — Regularise promoted GSN propagation and determinant conditioning.
- **Deliverable:** Task 3 adds exhaustive two-endpoint horizon recovery with
  independent branch prefixes, cap-reused nearest-adequate outer selection,
  exhaustive safe-window backtracking and selective semantic-tier promotion,
  request-bound ODE-budget controls, atomic partial-component resume,
  destination-only authenticated checkpoint migration, two isolated
  operator-only PowerShell entry points, and the architecture engineering note.
- **Verification:** 34 focused synthetic/static tests and 48 existing worker
  static tests passed; changed Python files compiled; the TaskPlanner board and
  diff check passed. No Julia worker, Kerr determinant, ODE/angular/QNM solve,
  M02 campaign, or PowerShell script was executed.
- **Evidence ceiling:** TASK-079 remains In Progress. Native operator receipts,
  calibrated determinant-to-ODE allocation, human mathematics review, and
  release admission remain outstanding.
- **Change reference:** local Task 3 commit; no push performed.
- **Independent-review repair:** Production promoted readouts now consume the
  durable partial journal, changed 40/80/120 requests fail before worker work
  without a recorded ODE budget, safe-window recovery emits readout-specific
  semantic-tier plans, endpoint failures are typed without a legacy-selector
  fallback, and the light-ring report uses StrictMode-safe real schema keys.
- **Final integration repair:** Ordinary signed and expanded root reads now
  journal full outputs and resume exactly; Julia journal identities are the
  exact ODE-budget-bound requests; and the campaign executes only the recorded
  selective signed-pair plan at semantic BigFloat-40 while retaining binary64
  readouts. A focused 42-test synthetic suite passed without a solver or
  production-script run.
- **Semantic-loop re-review:** Tier-keyed recorded ODE budgets now drive the
  full selective BigFloat-40 → BigFloat-80 → BigFloat-120 sequence inside one
  existing campaign stage, with per-tier journal identities, cumulative
  retained evidence, exact missing-tier blockers, and no whole-component
  fallback. Convergence and precision-exhaustion fakes passed in a focused
  45-test safe regression.
- **Campaign compatibility re-review:** A strict selective-stage terminal
  contract now checkpoints and reloads converged semantic recovery as
  `PRODUCED` and BigFloat-120 exhaustion as `UNRESOLVED`, while leaving legacy
  self-refinement/discrepancy fields null. Focused `run_campaign_selection`
  tests and a 35-test safe regression passed.
- **Selective evidence-authentication re-review:** Every semantic tier now
  checkpoints a complete canonical projection of its promoted journal entries,
  exact current worker receipts, Julia requests, scientific runtime, and
  recorded ODE budget. Reload authenticates request/runtime/budget/tier/job/
  role/amplitude/work-unit bindings for current and prior tiers. Resealed
  receipt-stripping and journal-digest forgeries fail closed; 17 focused safe
  selective/journal tests passed without scientific execution. The final
  selective/journal/recovery/ODE-budget regression comprised 38 passing tests.
- **Canonical-request re-review:** Selective checkpoint validation now rebuilds
  each full Julia request byte-for-byte, binding BF40 to its binary64
  same-amplitude predecessor and BF80/BF120 to the preceding tier's journal
  output. Fully resealed predictor, non-budget policy, and exterior-support
  mutations fail closed. A 29-test focused safe regression passed.
- **Full Python compatibility migration:** Synthetic promoted-request fixtures
  now supply explicit recorded ODE budgets without restoring defaults;
  historical failed-preflight receipts reconstruct from their own recorded
  budget; all five endpoint recovery outcomes carry authenticated typed
  evidence; intentional policy/cache identities and static ownership checks
  were recomputed and migrated narrowly. Full safe discovery passed 881 tests
  with 7 skips. No scientific solver, M02 campaign, Julia worker, or production
  PowerShell entry point was executed.
- **Endpoint/checkpoint architecture re-review:** Only typed horizon arithmetic
  insufficiency now advances 80→120; the live checkpoint is schema 8 with
  schema 7 historical; the migration consumes authenticated real campaign
  records/attempts and emits a normal resumable destination plus sidecar while
  preserving source bytes and unaffected evidence. Current scientific IDs bind
  bounded analytic horizon v2 and fixed-root exterior derivative evidence.
  Julia endpoint recovery statically searches all deterministic prefixes to
  each maximum order, and the light-ring script waits for process-tree exit and
  selects resume versus cold journal-reuse based on checkpoint existence. The
  affected regression passed 279 tests with 6 skips; full safe discovery passed
  885 tests with 7 skips; compile, manifest, board, and diff checks passed. No
  prohibited numerical or PowerShell entry point was executed, and TASK-079
  remains In Progress pending operator and human-math evidence.
- **Final identity/dispatch re-review:** The real Native campaign now recovers
  typed endpoint arithmetic directly from authenticated 80-digit failure to
  120 digits without fabricating a legacy stage; frozen origin/main schema-7
  source, factory, request, and precision bindings migrate to current schema 8;
  and promoted dispatch/contracts are mechanism-scoped so deep horizon leaves
  use bounded analytic evidence while all deep exterior leaves use fixed-root
  derivative evidence. Retained historical stage mappings remain byte-for-byte
  unchanged. Migration publishes its checkpoint/receipt pair transactionally
  with source-race rollback, and the interruption script launches the current
  PowerShell executable using quoted `-File` arguments. Focused synthetic/static
  regressions and compilation passed; no prohibited scientific or operator
  execution occurred.
- **Deep-horizon reload and migration closure:** Schema-7 migration now cuts
  every leaf record at its first promoted stage because both historical
  horizon and exterior promoted calculations changed, while the retained
  binary64 `CampaignStageRecord` mappings remain identical. Deep-leaf
  scientific identities are mechanism-scoped. Bounded analytic deep-horizon
  evidence now survives checkpoint validation/resume, including direct
  80-control-failure to 120-digit endpoint-arithmetic recovery: a converged
  non-sentinel is `PRODUCED`, while the sentinel audit remains `UNRESOLVED`.
  The affected 158-test safe regression and full 895-test discovery passed
  (7 skipped), together with compilation, manifest, board, and diff checks.
  No prohibited scientific or PowerShell entry point was executed.

## 2026-08-18 — TASK-079 promoted horizon component reduced to a single Julia readout

- **Task:** TASK-079 — Regularise promoted GSN propagation and determinant conditioning.
- **Deliverable:** A promoted `horizon-admittance` primary component at 80 or 120 digits performs one Julia root readout at zero amplitude and derives its response algebraically from the retained complex PRIMARY derivative, replacing the prior multi-readout finite-amplitude ladder. PRIMARY accepts on `|D| / |D′|` with zero post-Newton determinant evaluations and retains the accepted complex `D′`. TRUNCATION and RESOLUTION each evaluate exactly one determinant at the accepted PRIMARY frequency and accept on `|D_phase| / |D′_PRIMARY| ≤ 2×10⁻¹¹`; TRUNCATION varies only `endpoint_series_order`, RESOLUTION only the homogeneous ODE tolerances. SEED-PATH is omitted, with required/executed/count carried as false/false/0. No same-precision self-refinement pass runs on this path; 80→120 promotion is decided from the component's own convergence and conditioning. The routing applies identically to normal 80/120 promotion and to 120-digit recovery after a failed 80-digit preflight. The dedicated component runner independently re-validates the full contract — policy identity, PRIMARY/TRUNCATION/RESOLUTION determinant budgets, SEED-PATH omission, fixed-root and derivative-reuse evidence, determinant convention, branch identity — before deriving the response, and fails closed on any mismatch, on a non-finite or zero retained derivative, on a non-finite or zero horizon frequency, and on a Kerr spin that is non-finite or not strictly sub-extremal. The response carries component identity `single-promoted-root-analytic-horizon-component/v1`, response method `analytic-horizon-from-promoted-primary-derivative/v1`, and uncertainty status `UNCALIBRATED_ANALYTIC_RESPONSE`, with every error channel marked not-applicable rather than measured-zero. The Julia worker (`m02_worker.jl`) is unmodified; the change is confined to the Python component/campaign layer.
- **Verification:** GitHub Actions run on the final merged head passed on `windows-latest`, `ubuntu-latest`, and the Julia factored-GSN job.
- **Change reference:** PR [#52](https://github.com/vbrodi23-lgtm/Kerr-QNM_Windows-Solver/pull/52), merged as `ae29858`.

## 2026-08-14 — TASK-076 promoted Julia readout containment triage

- **Leaf 13 benchmark:** M02 Leaf 13/212 (`221`, `a/M = 0.95`, `horizon-admittance`) exhausted all four binary64 phases after 216 determinant evaluations and about 361 seconds. At 80 decimal digits it had spent 5,271.5 seconds in PRIMARY, Newton iteration 1, determinant 3, with zero completed promoted readouts; `Xup_match_to_inner` was active at about 1.96 million radial RHS evaluations, zero rejected steps, zero nonlinear failures, and a healthy heartbeat. The observed raw determinant magnitude near `3.83e1450` is recorded but is not itself classified as failure.
- **Architectural diagnosis:** The promoted worker had unbounded homogeneous `maxiters`, no cooperative deadline or per-leg work ceilings, no determinant-cost feasibility guard, and no campaign-level typed quarantine. One pathological leaf therefore depended on the outer 7,200-second Python kill boundary, could abort all 212 leaves, and could lose the exact phase/ODE cost location or be confused with scientific nonconvergence.
- **Containment PR scope:** Add a request-digested but science-identity-excluded execution-resource policy; finite Julia ODE/request/leg limits; first-determinant root-readout feasibility triage; PRIMARY diagnostic short-circuit; distinct typed ODE/readout/timeout failures; schema-version-4 append-only attempt records with schema-version-3 loading; atomic deferred-leaf quarantine and next-leaf continuation; explicit-resume retry; and resource CSV/status/dashboard fields. Mathematical performance redesign remains outside this slice.
- **Task state:** TASK-076 remains Backlog and blocked by TASK-075. TASK-075 remains In Progress, and the M02 milestone status is unchanged.
- **Evidence ceiling:** Static Julia source contracts, Python compilation, and mocked/synthetic Python unit tests only. No Julia worker, Kerr determinant, 80/120-digit mathematical payload, native Leaf 13 rerun, PowerShell campaign, or physical campaign evidence is claimed.
- **Change reference:** branch `agent/m02-promoted-readout-resource-containment`; draft PR to be opened against `main` without merge.

## 2026-08-13 — TASK-075 implementation reconciled after PR #40

- **Current position:** The canonical M02 domain is 212 leaves, 48 campaign roots, and 57 projective rows. PR #21 superseded the earlier 553/87/174 execution scope, and PR #40 merged the determinant, branch, finite-difference, Newton, support-contract, checkpoint-boolean, and promoted-ODE repairs. Earlier work-log entries retain their historical scope rather than being silently rewritten.
- **Task state:** Ten of TASK-075's eleven acceptance criteria now have merged repository and CI evidence. The task remains In Progress because no immutable Black Hole Perturbation Toolkit Mathematica spheroidal validation-source receipt exists in the repository. TASK-076 therefore remains blocked rather than being prematurely promoted.
- **Verification:** GitHub Actions run `31640576550` passed on PR #40's exact final head on Ubuntu and Windows: 471 tests plus the 11-test follow-on gate, wheel inspection, compilation, admission/cache, campaign smoke, provider checks, and Windows launcher parity. The release-manifest validator passes, and direct contract introspection returns 212 leaves, 48 campaign roots, and 57 projective rows.
- **Evidence ceiling:** Software, static/promoted-worker contract tests, and hosted cross-platform Python/PowerShell gates only. No native Julia physics benchmark, representative cold/warm scientific execution, complete 212-leaf campaign, populated atlas, or admitted linear-response provider is claimed.
- **Change reference:** canonical scope PR [#21](https://github.com/vbrodi23-lgtm/Kerr-QNM_Windows-Solver/pull/21); final implementation repair PR [#40](https://github.com/vbrodi23-lgtm/Kerr-QNM_Windows-Solver/pull/40), merged as `c10fbeccb8c4a2253a542166e82637c14232c594`.

## 2026-08-09 — M02 self-originating scientific execution set as the active delivery path

- **Current position:** PR #5 merged the complete 553-leaf planning, execution, reduction, and fail-closed admission machinery. PR #6 merged the package-local Python bootstrap. No 553-leaf physical campaign or admitted linear-response result exists yet.
- **Delivery sequence:** TASK-075 makes the solver originate its package-local runtime, pinned public GSN/angular sources, generated numerical prerequisites, and provenance ledger; TASK-076 proves the one-command cold/warm multi-precision path with preflight, resume, and failure diagnostics; TASK-077 produces all 553 physical leaves; TASK-078 reduces 174 rows, admits the provider, and closes M02.
- **Dependency correction:** M03 now starts after TASK-078. M06 forced solves consume the validated M04 operator through TASK-023. M07 consumes TASK-078 rather than the software-only TASK-011 gate.
- **Evidence ceiling:** Roadmap and executable task control only. M02 remains incomplete until TASK-078 produces and admits the physical package.
- **Change reference:** PR [#7](https://github.com/vbrodi23-lgtm/Kerr-QNM_Windows-Solver/pull/7).

## 2026-08-08 — TASK-011 M02 admission and operator closure completed

- **Task:** TASK-011 — Build fail-closed M02 validation, admission, and operator closure commands.
- **Deliverable:** Immutable complete-evidence admission package with exact produced-record component binding, complete checkpoint root identities reduced to and reconciled through one 87-root campaign receipt, checkpoint-derived reducer values/channels, exact 174-row payload/reduction binding, an exact provider/request/payload receipt for the accepted spectral upstream, and a detached expected-ID load boundary; explicit dynamic provider transition, deterministic validation/admission/export CLI, exact sparse selection, cold/warm cache proof, PowerShell operator runbook, package checks, and hosted platform gates.
- **Verification:** 225 local tests passed, including internally resealed campaign/catalog drift, replay-time spectral provider/root drift, sealed Gram/covariance equality, non-finite Cholesky rejection, overlapping row-Gram bases, frozen artifact reload, rank-deficient PSD covariance, rejected-state completeness, exact kappa boundary, branch-type error boundary, forged checkpoint centre/channel, stale projective row, resealed package, cross-package cache, and malformed input regressions; predecessor GitHub Actions run `31249917661` passed on Ubuntu and Windows, and the final PR head must repeat every hosted gate before review readiness; board, release manifest, compile, and diff gates passed.
- **Evidence ceiling:** Software and operator handoff are ready. No physical 553-leaf campaign or populated scientific atlas ran; the default provider remains unavailable until the user's complete evidence passes admission.
- **Change reference:** admission `be706164`; CLI/integration `dbb20779`; handoff/CI `5ecb2f05`; stable cross-platform identities `3580b73f` and `2b09a9b4`; immutable package `759b37f2`; closure `57e4d4ee`; PR #5.

## 2026-08-08 — TASK-010 empirical uncertainty/projective reducer completed

- **Task:** TASK-010 — Build the empirical uncertainty and projective-reduction pipeline.
- **Deliverable:** Digest-owned signed-channel schema, exactly recomputable empirical Grams, calibrated-normalized `J G Jᵀ` propagation, exact 174-row planner, partial-honest reducer, zero-backend CLI, and PowerShell handoff.
- **Verification:** 206 full tests passed after review remediation; exact six-case smoke, stage/Gram tamper rejection, partial honesty, Windows byte preservation, cross-platform angular smoke, wheel, manifest, board, compile, and diff gates passed.
- **Evidence ceiling:** Plans plus six synthetic/representative reductions only; no determinant/cache/campaign, complete 553-leaf evidence, populated scientific atlas, or provider admission.
- **Change reference:** implementation `b9b952c3409146ab695df082662a13a922f6e03e`; review/CI remediation on PR #5 `6e60a94481c5d8f83026f56f54adeba285105a4b`.

## 2026-08-08 — TASK-008 two-path response engine completed after review

- **Task:** TASK-008 — Build the two-path linear-response engine and representative slice.
- **Deliverable:** Concrete source-authenticated native kernel, horizon plus six exterior profiles, shared readout/refinement boundary, authenticated checkpoints, deterministic selected PowerShell commands, and exactly five pinned replay rows with complete recorded correspondence/error channels.
- **Verification:** 22 focused and 174 full tests passed; board, compile, diff, pre-work missing-cache, cold/resume/zero-work/tamper, strict selection, public-surface, and package-data gates passed.
- **Evidence ceiling:** Software and authenticated replay smoke only; the required cache is absent, and no fresh response production, complete operator evidence, or provider admission occurred.
- **Change reference:** implementation `d4cad85e03cf496a68df6cc6860aeb8c5645ec75`; review remediation `6eb90f7c13446453e3ba74418d553f7d2cb73c86`.

## 2026-08-08 — TASK-007 authenticated operator evidence intake completed

- **Task:** TASK-007 — Build authenticated evidence intake for operator-run calculations.
- **Deliverable:** Strict partial/complete B′ bundle loader/validator, deterministic JSON command, PowerShell handoff, five exact pinned fixture inputs, 9 pilot records, 8 cubic comparator rows, and a 147-identity ledger with 138 explicit missing-source entries.
- **Verification:** 30 focused and 156 full tests passed; root binding, duplicate-key, path, hash, partition, comparator, public-surface, compile, board, diff, and offline wheel-content gates passed.
- **Evidence ceiling:** Structural intake and migration fixtures only; no response calculation, complete operator bundle, uncertainty reduction, or provider admission.
- **Change reference:** implementation commit `35d7f39de46b125a8e0e01de8f8dfbb12df363ff`.

## 2026-08-08 — M02 operator boundary corrected to build-and-smoke

- **Decision:** Codex builds and representative-smoke-tests the complete M02 machinery; the user runs the full 553-leaf scientific evidence campaign in PowerShell.
- **Scope change:** TASK-009 now owns one generic exact-domain batch runner; separate bulk campaigns TASK-071–TASK-074 are superseded. TASK-007–TASK-011 deliver import, execution, reduction, validation, and operator commands without fabricating or collecting the final atlas.
- **Verification rule:** Every numerical batch exercises canonical head/tail and predeclared risk-bearing middle cases before handoff; partial smoke bundles remain inadmissible.
- **Evidence ceiling:** Software readiness is distinct from scientific evidence completion; the linear-response provider stays unavailable until a complete operator bundle passes admission.
- **Change reference:** user-directed scope amendment in the controlling M02 plan and TaskPlanner board.

## 2026-08-08 — TASK-070 sparse B′ spectral overlay admitted

- **Task:** TASK-070 — Admit the 44-root exact-selector overlay for B′.
- **Deliverable:** Authenticated 44-root sparse CSV/receipt and content-digested complete checkpoint; deterministic numeric-spin-ordered cohort builder; exact 87-selector base-plus-overlay union; manifest and wheel bindings.
- **Verification:** 56 focused and 148 full unit tests passed, including eight predeclared head/tail/risk roots independently recomputed and reloaded through the installed provider; board, manifest, compile, diff, immutable-base, zero-work replay, and offline wheel-content gates passed.
- **Evidence ceiling:** Numerical continuation and genealogy evidence only; no external comparator, formal root enclosure, interpolation, or DM/ZDM classification.
- **Change reference:** implementation commit `6e01e403a53c9dc592004bca688bb8e976f3157d`; overlap-floor remediation commit `38d702ea58cb98fa9d562126afda9ba6396832af`; representative smoke commit `3ff1262cc1666b51ea4985e6adc383ff503cf806`; checkpoint-integrity/numeric-order remediation commit `d2e96c6494ef9908be6c2a4b4807fbcb729f7c44`.

## 2026-08-08 — TASK-069 B′ M02 release domain frozen

- **Task:** TASK-069 — Freeze the B′ 553-leaf M02 release domain.
- **Deliverable:** Typed 553-leaf role contract, 87-selector/44-overlay ledger, 174 projective rows, exact Mκ precision gates, supersession record, and Wolfram receipt; the numerical provider remains unavailable.
- **Verification:** 22 focused and 134 full unit tests passed; board, manifest, and compilation validators passed; the 2,736-root base catalog and receipt were left unchanged.
- **Evidence ceiling:** Contract-only. TASK-070 must produce the sparse, authenticated 44-root overlay before numerical response production can start.
- **Change reference:** commit `a3c40ddc7481a094bb3e8fc7d0db7ad4850b3615`.

## 2026-08-07 — TASK-006 public linear-response contract completed

- **Task:** TASK-006 — Define the public linear-response artifact and provider contract.
- **Deliverable:** Strict unavailable provider descriptor, exact direct-spin/`Mκ` request sampling, eight mechanism contracts, component-local and cross-component covariance, uncertainty-disk and multimode-projective payload validation, example study, design, plan, and fail-closed tests.
- **Verification:** 19 focused and 129 full unit tests passed; board and unchanged release manifest validated; Wolfram returned zero residual for the simple-root, `Mκ`↔`a/M`, and horizon-coordinate identities; independent Change Review returned no blockers after remediation.
- **Evidence ceiling:** Contract-only; no response computation or provider admission. M02 remains open, with current spectral-domain, provenance, covariance, and frozen recomputation blockers recorded in PR #4.
- **Change reference:** implementation commit `a12ef02f57038ac8a8c912381f1fe64c76237860`; draft PR [#4](https://github.com/vbrodi23-lgtm/Kerr-QNM_Windows-Solver/pull/4).

## 2026-08-07 — M01 release scope and authenticated evidence baseline closed

- **Tasks:** TASK-001–TASK-005
- **Deliverable:** Frozen release-domain manifest, source-receipt ledger, module-ownership matrix, convention/evidence-ceiling register, strict parser and validator, negative tests, packaged-data binding, and human reconciliation report.
- **Verification:** `python .tasks/validate_board.py`; `python tools/validate_release_manifest.py`; `PYTHONPATH=src python -m unittest discover -s tests -v` (110 passed, including the cross-platform manifest checkout regression); clean wheel build/import (SHA-256 `cbfd6887ed07f186a6966a3093da2bb0e580a8402b53868855be6125240dea18`); Change Review returned no blocking findings.
- **Evidence ceiling:** Scope-control and provenance baseline only. No spectral bytes or provider behavior changed, and only the pre-existing problem-contract and spectral-core capabilities are admitted.
- **Change reference:** implementation commit `8aeaf5adb2667756b3623daa76f50720118fa5d2`; draft PR [#3](https://github.com/vbrodi23-lgtm/Kerr-QNM_Windows-Solver/pull/3).

## 2026-08-07 — M00 project-control system initialized

Created the authoritative Notion charter and governance ledgers; initialized TaskPlanner 2.1.1; populated M01–M12 with 68 dependency-linked tasks; selected TASK-001 as the sole Next item; and added structural validation.

### Completion entry template

- **Task:** TASK-NNN — title
- **Deliverable:** artifact or bounded result
- **Verification:** exact checks and outcome
- **Evidence ceiling:** strongest supported numerical/scientific claim
- **Change reference:** commit and PR, or “not applicable”
