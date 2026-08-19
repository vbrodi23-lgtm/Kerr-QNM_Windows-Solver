# Task 3 Report — Adaptive recovery and durable readout resume

## Status

Implementation complete under the Task 3 air-gap. Operator/native validation
is deliberately incomplete, so TASK-079 remains In Progress. No Kerr
determinant, Julia worker, ODE/angular/QNM solve, M02 campaign, or production
PowerShell script was executed.

## Isolation gate

Before mutation:

```text
workspace: /workspace/scratch/311f98c11e2d/repo
branch: solver/campaign-optimization
HEAD: 01725bfc4a00828a7dfa977622d7ff482c0e261d
git status --porcelain: empty
worktrees: one
```

## RED evidence

Each production slice began with a failing focused test:

- `tests.test_response_ladder_recovery`: import failed because
  `windows_solver.response_ladder_recovery` did not exist.
- `tests.test_adaptive_horizon_endpoint`: five static contract failures exposed
  the absent typed pair-recovery orchestrator, independent best-prefix evidence,
  captured five-candidate fixture, and pre-pair zero-RHS gate.
- `tests.test_partial_component_checkpoint`: import failed because
  `PartialComponentWorkUnit` and the resume executor did not exist.
- `tests.test_campaign_checkpoint_migration`: import failed because the
  migration module did not exist.
- Both production-script tests failed because their exact `.ps1` files did not
  exist.
- The added production outer-endpoint test failed because neither the request
  schedule nor cap-geometry selection existed.
- The added ODE integration tests failed because
  `_adaptive_ode_request_controls` did not exist.

All RED runs used synthetic Python or static source inspection only.

## Implementation outcome

- Horizon recovery materializes the complete order schedule, caches geometry
  failures without retry, scores ingoing/outgoing prefixes independently,
  requires two verified endpoints, records typed canonical outcomes, and
  preserves zero homogeneous RHS work before the pair gate.
- Response recovery enumerates every consecutive window of at least four
  levels and applies the existing signal, real/imaginary order, axis, even,
  branch, and diagnostic gates. It selects the deterministic finest admissible
  window, records excluded fine reasons, expands exact amplitudes first, and
  promotes only failing signed-axis pairs through semantic tiers.
- The partial-component journal validates the complete work plan, commits each
  work unit atomically, resumes exact prior entries without recomputation, and
  rejects identity conflicts closed.
- Checkpoint migration authenticates and rechecks source bytes, creates only a
  new destination, preserves unaffected/terminal evidence, and invalidates only
  receipts bound to a changed endpoint policy.
- Outer-endpoint production requests carry the increasing
  `100,250,500,1000,2000,5000` schedule. The worker builds the cap coordinate
  map once, reuses it for every candidate, applies the package-owned asymptotic
  gate, selects the nearest adequate candidate, and emits complete evidence.
- Changed requests can consume a serialized `ODEErrorBudget`; an absent budget
  fails with the exact `ODE_CALIBRATION_BLOCKER`. Historical provisional
  controls were not relabelled as calibrated.
- The two exact operator scripts isolate output/cache state, constrain exact
  leaves, produce detailed recovery reports, and include deliberate
  interruption/resume evidence. They were inspected statically, never run.

## GREEN evidence

Focused test transitions observed:

```text
tests.test_response_ladder_recovery                 3 passed
tests.test_adaptive_horizon_endpoint                5 passed
tests.test_partial_component_checkpoint             6 passed
tests.test_campaign_checkpoint_migration            3 passed
production PowerShell static tests                  6 passed
tests.test_adaptive_outer_endpoint                  5 passed
tests.test_adaptive_ode_budget                       6 passed
```

The final verification section below records the exact combined commands and
results after all edits.

## Final restricted verification

```bash
PYTHONPATH=src python -m unittest -v \
  tests.test_response_ladder_recovery \
  tests.test_adaptive_horizon_endpoint \
  tests.test_adaptive_outer_endpoint \
  tests.test_adaptive_ode_budget \
  tests.test_partial_component_checkpoint \
  tests.test_campaign_checkpoint_migration \
  tests.test_production_222_endpoint_recovery_script \
  tests.test_production_light_ring_response_recovery_script
```

Result: `Ran 34 tests ... OK`.

```bash
PYTHONPATH=src python -m unittest -v tests.test_regularised_gsn_worker_static
```

Result after updating its direct-call assertion for the package-owned recovery
orchestrator: `Ran 48 tests ... OK`.

Changed Python files passed `python -m py_compile`; `python
.tasks/validate_board.py` reported 79 unique tasks, 12 milestones, 13 Done, one
In Progress, and acyclic dependencies; `git diff --check` passed.

## Deferred operator evidence

The following remain intentionally open: native Julia syntax/unit execution,
the promoted 222 endpoint-recovery run, the three-leaf light-ring stop/resume
run, calibrated determinant-to-ODE error allocation, human mathematical review,
and release admission. The authoritative blocker remains:

```text
TODO: [HUMAN MATH REVIEW REQUIRED - calibrated conversion from determinant/root error budget to ODE local tolerances is not yet established]
```

## Independent-review remediation

The first Task 3 commit was blocked at independent review. The follow-up fix
made the previously pure recovery contracts load-bearing:

- `KERR_QNM_PARTIAL_COMPONENT_JOURNAL_ROOT` is now consumed by the promoted
  exterior runner. The complete baseline/fixed-sample plan is authenticated
  before work, each full output (including baseline diagnostics) is committed
  immediately, and a fresh runner reconstructs exact completed outputs without
  calling the backend again.
- Changed 40/80/120 request construction now requires a recorded
  `ODEErrorBudget` before consulting any worker boundary. Historical
  provisional ODE tables are not loaded for changed identities; tests that
  execute synthetic requests provide an explicit synthetic calibration.
- `run_component` now invokes `recover_response_ladder`, retains attempted
  expansion levels, records all window/gate/ratio/exclusion/branch evidence,
  and emits a semantic-tier promotion plan naming only the failing signed-axis
  pairs. The mode-220/330 cap is exactly `0.008, 0.016`; mode 440 may also use
  `0.032`.
- The horizon worker consumes the package recovery result directly. Five
  distinct typed outcomes are serialized, only arithmetic insufficiency is
  retryable at the next tier, and the legacy generic endpoint selector is not
  called on the worker path.
- The light-ring operator report reads the real serialized recovery keys via a
  StrictMode-safe optional-property helper.

These are software/static guarantees only. The operator and human-review
evidence ceiling above is unchanged.

The remediation verification ran 62 focused synthetic/static tests with no
failures, compiled every changed Python surface, passed `git diff --check`, and
validated the TaskPlanner board. No prohibited numerical or PowerShell entry
point was executed.

## Final review integration fixes

A second independent review found that ordinary signed-root execution and the
campaign consumer still bypassed parts of the recovery architecture. The final
TDD pass closes those integration gaps:

- ordinary `run_component` reads now use the environment-selected partial
  journal for baseline, signed, expanded, and nested diagnostic evidence;
  completed full `RootReadout` mappings are reconstructed without a backend
  call after interruption;
- Julia backends expose an exact request-preview identity, including the
  recorded ODE budget, while native reads use a full identity-bound canonical
  pseudo-request; changed budgets change the plan and reject reuse;
- the native campaign consumes `readout_specific_promotion_plan`, executes only
  those signed roots at semantic BigFloat-40 first, retains binary64 evidence,
  reruns the existing component gates, and records mixed-tier/journal evidence;
  absence of calibration fails with the exact ODE calibration blocker before
  selective work, without whole-component fallback.

RED was observed for the absent generic journal, missing Julia preview API, and
missing selective campaign constructor/route. The final focused safe regression
run executed 42 synthetic Python tests with no failures. No production solver,
Julia worker, campaign, or PowerShell entry point was executed.

### Semantic-tier loop re-review

The final P1 re-review identified that one recorded budget and two legacy
campaign slots could execute only BigFloat-40 and BigFloat-80. A failing
campaign test demonstrated that BigFloat-120 was never reached. The campaign
backend now accepts tier-keyed recorded budgets (or a tier-keyed provider) and
runs the selective semantic sequence inside one existing legacy stage until it
converges or exhausts BigFloat-120. Each tier has a distinct exact-request
journal identity; only the named signed readouts execute; earlier tier evidence
and counts remain serialized. A missing required tier budget raises the exact
ODE calibration blocker before any work at that tier.

The convergence, BigFloat-120 exhaustion, and missing-BigFloat-80 cases passed,
followed by a 45-test focused safe regression. The scientific/operator evidence
ceiling remains unchanged and no prohibited numerical entry point was run.

### Campaign terminal compatibility re-review

Synthetic `run_campaign_selection` REDs showed the ordinary 80-digit contract
rejecting valid selective outcomes because their deliberately inapplicable
self-refinement and legacy discrepancy fields are null. A distinct strict
selective-stage validator now authenticates the semantic tier trace, named-only
plans, per-tier journals, cumulative evidence, component lineage, and either a
converged terminal result or explicit BigFloat-120 exhaustion. The runner and
checkpoint validator use that contract to publish `PRODUCED` or preserve
`UNRESOLVED` without fabricating legacy evidence or adding a third legacy stage.
Both campaign-selection/checkpoint round trips passed; the focused regression
ran 35 safe synthetic tests without prohibited execution.

### Selective evidence-authentication re-review

A subsequent P1 review showed that the selective terminal validator still
trusted tier labels and counts while the authoritative Julia request/receipt
evidence lived only in external journal files. RED checkpoint tests could not
find any embedded journal projection. The production result now embeds, for
each executed semantic tier, a canonical complete projection containing the
exact promoted work-unit entries, journal digest, scientific runtime, recorded
ODE budget, and their hashes. Reload reconstructs every projected
`PartialComponentEntry` and `RootReadout` and requires a current worker receipt
bound to the exact request SHA, runtime SHA, tier/digits/bits, ODE-budget
policy, job/leaf/backend, determinant convention, signed role/amplitude, and
work-unit identity. Prior tiers are validated by the same contract; the final
mixed-tier component alone is not accepted as proof.

The fake campaign backend was upgraded to emit real-worker-shaped current
receipts and exact Julia preview requests. Resealed negative checkpoints that
strip one promoted receipt or forge the embedded journal digest now fail
closed. The same integration exposed a legitimate mixed diagnostic surface:
retained binary64 roots have TRUNCATION/RESOLUTION/SEED-PATH while current
promoted roots intentionally have fixed-root TRUNCATION/RESOLUTION only. The
component gate now evaluates their common authenticated diagnostic families
and retains the existing zero SEED-PATH channel for the promoted policy; no
diagnostic family outside either existing accepted set is allowed.

RED: two focused checkpoint tests failed because no canonical embedded journal
existed; a third focused RED caught the initial diagnostic-family merge being
too broad. GREEN: the final 38-test selective/journal/recovery/ODE-budget suite
passed, including the 11 selective-promotion and 6 partial-journal tests. No
Julia worker, determinant, ODE/QNM solve, campaign, or PowerShell entry point
was executed.

### Canonical selective-request re-review

An adversarial follow-up showed that a self-consistent reseal could alter a
promoted request's predictor, non-budget policy fields, support, or resource
policy and recompute every stored digest. Focused RED tests confirmed that
forged `primary_predictor`, `policy.endpoint_series_order`, and exterior
support requests were accepted. The validator now reconstructs the entire
canonical Julia request with the authenticated job, parsed exact
`ODEErrorBudget`, semantic tier, signed amplitude, and predecessor root, then
requires byte-for-byte mapping equality. BF40 predictors bind to the matching
binary64 signed readout; BF80 predictors bind to the matching BF40 journal
output; BF120 predictors bind to BF80. The binary predecessor stage is threaded
through both live campaign validation and checkpoint reload.

All three predictor tiers and the non-budget policy/support reseals now fail
closed. The 29-test selective/journal/ODE focused suite passed. No prohibited
numerical or operator entry point was executed.

### Full Python compatibility migration

Full safe discovery initially reported 8 failures and 98 errors from synthetic
fixtures that predated mandatory recorded ODE budgets and the promoted
scientific-identity changes. RED was reproduced by affected module. Fixtures
that intentionally construct promoted Julia requests now provide an explicit
`synthetic_ode_error_budget(digits)`; production defaults remain fail-closed.
Historical failed-preflight request validation reconstructs only from the exact
budget recorded in the receipt. The five typed horizon recovery failures now
authenticate their distinct outcome, stage, retryability, complete canonical
search evidence, order schedule, rejected candidates, and zero pre-pair RHS
count. Static ownership, public identity allowlisting, runtime fixture fields,
and deliberately frozen cache/campaign digests were migrated only to values
recomputed from the current canonical policies.

RED after the migration was narrowed to one stale campaign identity in an
881-test discovery; all primary/control/deep values were recomputed before the
fixture update. GREEN: `PYTHONPATH=src python -m unittest discover -s tests -q`
ran 881 tests successfully with 7 skips. No Julia worker, determinant,
ODE/angular/QNM solve, M02 campaign, or production PowerShell entry point was
executed.

### Endpoint arithmetic and checkpoint-architecture re-review

A clean full-discovery rerun exposed one malformed synthetic arithmetic receipt:
the fixture marked only `INSUFFICIENT_ASYMPTOTIC_PRECISION` retryable even
though the typed endpoint contract makes `HORIZON_ARITHMETIC_INADEQUATE` the
only endpoint outcome eligible for the next semantic tier. The fixture now
emits the canonical retryability bit, and the campaign path records the failed
80-digit preflight and invokes exact 120-digit recovery for that outcome only.
Geometry exhaustion, maximum-order exhaustion, coordinate inversion, and
one-endpoint evidence remain terminal and never promote.

The subsequent architecture REDs demonstrated four further gaps:

- checkpoint migration operated on a toy envelope rather than authenticated
  `CampaignLeafRecord` and `CampaignExecutionAttempt` structures;
- current checkpoint/scientific identities still described schema 7,
  unbounded analytic horizon v1, and the historical multi-readout exterior
  contract;
- the Julia recovery search evaluated only the singleton maximum order rather
  than deterministic intermediate prefixes; and
- the light-ring interruption script attempted resume even when its journal
  entry committed before any campaign checkpoint existed, and did not wait for
  the entire stopped process tree.

The live checkpoint schema is now 8 and schema 7 is an explicit read-only
historical contract. Migration authenticates canonical source bytes, parses
the real campaign records and attempts, invalidates only nested evidence bound
to a changed endpoint policy, emits a normal loadable/resumable schema-8
checkpoint, records provenance in a separate authenticated sidecar, and proves
the source bytes are unchanged. Current identities bind bounded analytic
horizon v2 and the fixed-root exterior derivative component, response disk,
conditioning, axis validation, and full-validation policy; schema-7 aliases
retain the prior horizon v1/unbounded contract.

The package-owned Julia source now generates each branch recurrence once to
the requested maximum order and evaluates the full deterministic prefix
schedule independently for ingoing and outgoing evidence. A captured static
fixture selects order 12 while later order-16/order-20 terms grow; no Julia
code was executed. The operator script now terminates and waits for the child
process tree, validates and resumes only when a checkpoint exists, and starts a
cold campaign otherwise so the already committed partial journal is reused.

RED/GREEN evidence was retained in the focused migration, contract, static
prefix, and script tests. Final verification ran 279 affected synthetic/static
tests with 6 skips, then full safe discovery ran 885 tests with 7 skips.
Compilation, release-manifest validation, TaskPlanner validation, and
`git diff --check` passed. No Julia worker, Kerr determinant, ODE/angular/QNM
solve, production M02 campaign, or PowerShell script was executed. Native
operator receipts, calibrated determinant-to-ODE allocation, human mathematics
review, and release admission remain open.

### Final campaign-identity and migration re-review

The final production-path REDs exposed three remaining architecture defects:
the 80-digit endpoint-arithmetic attempt could not enter the ordinary 120-digit
API without a fabricated 80 stage; origin/main schema-7 bindings were being
reconstructed from current source material; and promoted deep horizon leaves
were dispatched and validated as exterior multi-readout work. A dedicated
endpoint-arithmetic recovery entry point now authenticates the exact failed
80 request and executes the 120 horizon recovery directly. Frozen schema-7
campaign/source/factory/request material reproduces the origin precision hash
`3f6364f6fc28eebeeb788af20524f8ada3c97f23e41fb68f4ead3da365368dcb`.
Current campaign/source identities are versioned independently, and every
promoted exterior contract, including deep and failed-preflight work, binds the
fixed-root derivative/disk/conditioning/validation policy.

Promoted horizon dispatch is now mechanism-scoped for PRIMARY and deep leaves.
The campaign has a distinct bounded-analytic deep terminal path: it accepts no
fabricated self-refinement evidence, retains the real binary-to-promoted
discrepancy when applicable, uses the existing promoted root/conditioning gate
for 80→120, and preserves the sentinel false-negative audit. An actual
`NativeCampaignStageBackend` synthetic campaign test reaches and checkpoints
that path. All Native promoted Julia constructors consume the tier-matched
recorded ODE budget before worker work.

Migration preserves every retained historical `CampaignStageRecord` mapping
exactly, while current validation narrowly admits the frozen schema-7 factory
only for preserved binary64 stages. Checkpoint and sidecar bytes are staged and
fsynced together, the source is rechecked immediately before and after install,
and injected second-install or source-race failures roll back both outputs. The
light-ring interruption launcher uses the current PowerShell executable with
an explicit quoted `-File` argument list and retains process-tree termination,
wait, checkpoint validation, and cold journal-reuse branches. These are static
tests only; the PowerShell script was not executed.

RED/GREEN evidence includes the real Native arithmetic predecessor test, exact
origin schema-7 checkpoint fixture, deep-horizon campaign test, retained-stage
identity assertion, transactional failure/race tests, and launcher parser/text
test. Focused verification passed the 26 response-batch, 49 precision-campaign,
28 Native/horizon, 6 migration, 34 endpoint/static/script, and 24 public-surface
tests (6 skipped). Python compilation and diff checks passed. No Julia worker,
Kerr determinant, ODE/angular/QNM solve, production M02 campaign, or production
PowerShell script was executed. Operator and human-mathematics validation
remain incomplete.

### Deep promoted migration and terminal-state closure

The final RED fixtures showed that schema-7 promoted stages could survive
migration when their endpoint policy identifier itself had not changed, even
though both the historical promoted horizon and exterior calculation
identities had changed. Migration now truncates each real `CampaignLeafRecord`
at its first stage above binary64 with reason
`SCHEMA7_PROMOTED_COMPONENT_IDENTITY_CHANGED`. Tests cover historical horizon
and exterior records and assert the retained binary64 stage mapping is exactly
identical before and after migration.

A second RED exercised a non-sentinel deep horizon through typed 80-digit
endpoint-arithmetic failure, direct 120-digit bounded analytic recovery,
checkpoint validation, and reload. It exposed both an unauthenticated payload
shape and the use of a finite-amplitude discrepancy terminal rule for an
analytic component with no such discrepancy. Endpoint-arithmetic evidence now
authenticates its exact predecessor field, and live/reload paths share the
mechanism-scoped bounded-horizon terminal rule. A converged non-sentinel is
`PRODUCED`; a converged sentinel remains `UNRESOLVED` under the independent
false-negative audit. Historical horizon-v1 role restrictions are unchanged.

GREEN verification: the seven affected modules ran 158 tests successfully;
full safe Python discovery ran 895 tests successfully with 7 skips. Python
compilation, release-manifest validation, TaskPlanner validation, and
`git diff --check` passed. No Julia worker, Kerr determinant, ODE/angular/QNM
solve, M02 campaign, or production PowerShell entry point was executed.

### Exact endpoint, selective-terminal, and reachable-budget binding

The final REDs demonstrated that a fully resealed successful endpoint receipt
could substitute its policy label, candidate radius, maximum order, or selected
prefix; typed endpoint failures admitted the same substitutions; a selective
terminal checkpoint could omit authenticated predecessor levels; and a
control-only leaf requested BigFloat budgets it can never execute.

Endpoint success and failure evidence now shares one request-bound validator.
It derives the complete depth schedule from the declared candidate ladder and
contour/floor, derives the order ladder and legal prefix schedule from the
declared request controls, and requires the exact recovery-policy identity.
The worker receives those controls only for horizon requests. Selective
terminal validation now requires exact predecessor-plus-journal readout
equality and recomputes the complete recovery-window projection; execution
preserves authenticated expanded levels in the terminal result. Scientific
execution contracts now return no promoted ODE budget material for control
leaves, so unreachable budget changes cannot alter their cache identity.

GREEN verification passed 294 focused endpoint, promoted, selective, budget,
precision-campaign, numerical-control, recovery-window, policy, and cache
tests. Changed Python compiled, the release manifest and TaskPlanner board
validated, and the cached diff passed whitespace checks. All checks were
synthetic Python or static Julia inspection. No Julia worker, Kerr determinant,
ODE/angular/QNM solve, M02 campaign, or production PowerShell entry point was
executed. Operator and human-mathematics validation remain incomplete.
