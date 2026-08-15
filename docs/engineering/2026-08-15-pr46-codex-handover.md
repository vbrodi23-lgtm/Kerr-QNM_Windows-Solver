# Handover — PR #46 continuation after Codex review

This note supersedes the **state and next-steps** sections of
`2026-08-15-horizon-rewrite-handover.md`. That earlier note remains the useful
history of the original implementation.

## Exact branch state

- Repository: `vbrodi23-lgtm/Kerr-QNM_Windows-Solver`
- Pull request: #46, draft, open, targeting `main` at `53e04b4`
- Branch: `claude/read-this-5em1in`
- Current pushed/local HEAD: `653013577bd1b3873eca4b698f44cf085e329f31`
- Worktree at handover: clean; no interrupted fix-round changes exist
- Current PR size: 19 commits, 28 changed files
- Completion plan:
  `docs/superpowers/plans/2026-08-15-pr46-horizon-detector-completion.md`
- TaskPlanner item: `TASK-079` in `.tasks/IN_PROGRESS.md`

The branch is **not ready to merge**. The latest commit is a checkpoint with a
known cross-language integration defect described below.

## Work added after the original handover

### Completion plan

Commit `b7ee632` added a five-task completion plan after a fresh architectural
comparison of `main`, all PR #46 commits, the supplied repair plan, and the
project research notes. The remaining work was divided as follows:

1. verified geometry before homogeneous work;
2. complete determinant and derivative authentication;
3. strict cross-language certificate, failure, and progress protocol;
4. mechanism-scoped policy and compatibility identity;
5. calibration, executable evidence gates, and PR closure.

### Task 1 — complete and pushed

Commits `ea06b01`, `5376675`, and `4caf283` enforce the geometry-first horizon
ordering and repair the explicit-tangent carrier validation. In particular:

- endpoint geometry is represented separately from series adequacy;
- invalid geometry cannot invoke either horizon-series assessment;
- the configured maximum horizon distance is revalidated at selection time;
- endpoint selection occurs before the outer Xup preparation or any
  homogeneous ODE;
- coordinate identity evidence is finite, tolerance-bearing, and fail-closed;
- explicit-tangent horizon carriers preserve the canonical match logarithm.

Hosted Julia workflow `31878328029` passed the load-bearing factored GSN,
real-inner horizon/match-basis, and scaled-scattering/determinant-equivalence
regressions. This corrects the earlier handover's statement that no Julia had
ever been run: Julia has now executed successfully for the Task 1 tree.

### Task 2 — implemented, pushed, then rejected by independent review

Commit `6530135` adds the determinant-error breakdown, tight-control and
raw/normalised discrepancies, authenticated finite-difference estimates,
error-aware damping/ranking/correction, a root-authentication record, and a
worker Julia spec in CI.

Local evidence for that commit was:

- focused Python: 181 passed, 6 skipped;
- complete Python: 693 passed, 7 skipped, 0 failures;
- Python compilation, TaskPlanner validation, and `git diff --check`: passed.

That green local result is **not sufficient**. An independent code review found
one critical and three important defects. No fix-round code was started before
this handover; HEAD is therefore a clean reproduction point.

## Critical defect at current HEAD

`m02_worker.jl` now emits `root_authentication` in ordinary and non-converged
result mappings while the Python backend still strictly consumes response
schema 3. Valid worker output can therefore be rejected by the live backend,
including the exterior path. The producer and consumer were staged in separate
tasks, but that staging left the pushed checkpoint internally incompatible.

Fix this atomically. The preferred repair is to pull forward the minimum strict
schema-4 parser/value types needed to consume the new record, while leaving the
broader persistence, progress, cache, report, and typed-failure work in Task 3.
An internal-only staging alternative is acceptable only if live schema-3
behavior is fully preserved. Add strict end-to-end parsing tests for horizon
success, exterior success, and non-converged responses.

## Other mandatory Task 2 review fixes

1. **Finite-difference bounds cover only base `h`.** The implementation samples
   `h/2` and `2h`, and records `h/2` as the accepted step, so endpoint rungs can
   evaluate outside the configured minimum/maximum. Define admissibility so
   every actual sample and selected step is inside policy, and test both bounds.

2. **Exterior behavior changed globally.** The new rung-list validation and
   clamped attempts apply to every determinant family. Restore the historical
   exterior ladder/validation path when horizon authentication is inapplicable.
   Add an executable characterization test comparing attempted steps, selected
   derivative, convergence, and emitted result with pre-Task-2 behavior.

3. **Julia caller-chain coverage is too static.** The unequal-error test calls
   only the propagation helper. Add an injectable/fake determinant evaluator
   and execute the chain through `finite_difference_pair`, `final_derivative`,
   and the ladder. Prove unequal-error propagation, accepted `h/2` error/lower
   bound/step, same-frequency base/tight depth, finite exhaustion, and unchanged
   exterior behavior. Source-grep assertions are not a substitute.

4. Revert unrelated future Task 4 wording edits in the completion plan unless
   they are separately necessary and documented.

5. `.superpowers/sdd/2026-08-15-pr46-horizon-detector-completion/task-2-report.md`
   was accidentally tracked in `6530135`. Remove it from the Git index while
   retaining local review notes outside the PR.

## Current CI

At handover, workflow `31879815097` for `6530135` was still running. The Julia
job had passed setup, package materialization/precompile, the factored GSN
regression, and the real-inner horizon regression; scaled scattering was in
progress and the new worker determinant/finite-difference regression had not
yet run. Ubuntu and Windows were running the Python test step. Inspect the final
run rather than relying on this snapshot.

## Recommended continuation order

1. Fix all Task 2 review findings in one red-green slice; run the complete
   Python suite and the executable Julia worker spec in hosted CI.
2. Complete Task 3: schema 4, closed-key immutable evidence types, normalized
   typed numerical failures, progress registry/rendering, persistence through
   readouts/caches/reports, and exact same-frequency cross-precision evidence.
3. Complete Task 4: mechanism-scoped policy and identity. Prove old horizon
   receipts stale while a `main`-generated exterior receipt remains compatible.
4. Complete Task 5: validate the calibration receipt contract, run the complete
   vendored Julia package tests, and execute only Gates 1–4 from the completion
   plan. Do not start the 212-leaf campaign.
5. Perform a fresh whole-branch review, resolve every finding, push, and wait
   for required checks. Keep the PR draft/blocked until native evidence exists.

## Scientific evidence ceiling

No native Leaf 13 determinant, authenticated Leaf 13 root, 120-digit coordinate
map, calibrated control profile, or five-mode horizon regression receipt has
been produced. The committed profile remains an uncalibrated starting profile.
Software/unit/hosted-CI evidence must not be described as scientific closure.

The PR's target invariant remains:

> A geometrically invalid horizon path, a precision-derived impossible
> tolerance, or an unresolved tiny determinant can neither consume the old
> resource path nor produce a false solved receipt; it must terminate with a
> specific numerical diagnosis.
