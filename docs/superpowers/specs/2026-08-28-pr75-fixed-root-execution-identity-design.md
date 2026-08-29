# PR75 Fixed-Root Execution-Identity Migration

## Status

Approved by the operator in chat on 2026-08-28. The PR75 pull-request body is
the governing contract. This document records the implementation architecture
and the four amendments accepted before implementation began.

## Objective

Complete the fixed-root-survey-batch migration as one authenticated lifecycle:

1. Python constructs a version-3 fixed-root request.
2. Julia validates the request and derives request- or sample-scoped execution
   identity.
3. Julia returns either an authenticated success or a typed control receipt.
4. Python binds every control outcome to the canonical request and validates it.
5. The campaign persists the raw return before classifying it.
6. The campaign persists the classified decision before scheduling continuation.
7. Restart revalidates the full proof before BF80 can run.

The repair is contract and control-plane work. It does not alter Kerr
mathematics, make BF40 succeed, or weaken an asymptotic reliability gate.

## Non-Negotiable Boundaries

- Do not execute a production M02 campaign, determinant kernel, root solver,
  ODE solver, or numerical Julia worker while developing PR75.
- Preserve the operator's Binary64, Layer-1, root, background, horizon,
  checkpoint, and failure evidence.
- Fixed-root request schema `/1` is forensic history only. It cannot authorize
  new execution or continuation after PR75.
- No permissive fallback may infer an operation identity from unrelated fields
  or display text.
- A deterministic no-solver harness is transport and lifecycle evidence, not
  evidence of real BF80 exterior numerical execution.

## Operation-Discriminated Identity

`windows-solver.operation-execution-identity/1` is the common authenticated
identity. Its common projection carries:

- operation and request schema;
- canonical request SHA-256;
- leaf, job, backend, precision, effective-policy, and execution-resource
  identities.

The root-readout projection additionally carries root-specific role, job-policy,
refinement, and root-phase context. The fixed-root batch projection carries the
plan, scientific operation identity, root reference and seal, branch identity,
and ordered sample roles.

Scope is explicit:

- `REQUEST` means no sample is selected; `sample_index` and `sample_role` are
  absent from the execution identity.
- `SAMPLE` requires the request projection plus one zero-based `sample_index`
  and exact `sample_role`.

The outer request may contain an ordered descriptor array such as
`samples[0] = {sample_index: 0, sample_role: D0, ...}`. Selecting that descriptor
inside Julia creates the SAMPLE-scope execution-identity projection. It does
not mutate the outer batch identity into a single-role request.

The same identity or a schema-defined authenticated projection must survive in
request construction, progress, success, control receipt, Python exception,
campaign failure report, raw return, decision, checkpoint, structural trace,
and resume validation.

## Fixed-Root Request Version 3

`windows-solver.fixed-root-survey-batch/3` retains the explicit plan and indexed
nested sample descriptors and additionally authenticates the complete exterior
endpoint-recovery policy. Version `/2` is forensic-only and cannot authorize a
new execution or continuation. It does not restore `root_correction_tolerance`.

The current numeric authority remains the promoted calibration profile. Python
projects that authority into the request as:

- `fixed_root_reliability_target_abs = 2e-11`;
- `fixed_root_reliability_rule =
  minus-log10-target-plus-required-digit-guard/v1`.

Julia calculates required reliable digits only from that projection for a
fixed-root request. Root-readout continues to use its root-specific tolerance.
The calculation must be identical during asymptotic preflight and successful
response construction.

## Typed Control Lifecycle

The fixed-root `/3` worker emits
`windows-solver.operation-control-fact-receipt/2`. It carries authenticated
origin, class, code, stage, scope, operation execution identity, numerical
diagnostics, canonical request binding, and its own canonical digest. It does
not carry campaign retryability, terminality, promotion authority, queue kind,
or a target tier. Compatibility ingress may still decode
`windows-solver.operation-control-receipt/1`; its derived retryability field is
validated at that boundary and cannot become fixed-root authority. Only the
validator can produce a `ValidatedControlReceipt`.

Every CONTROL outcome reachable through the promoted ROOT/RESPONSE lifecycle,
including shared control paths consumed by those operations, has an explicit
entry in one transition registry. Unrelated solver operations remain outside
PR75 unless the shared implementation makes their migration necessary.

`PromotedControlTransition` is the sole owner of the state change. It consumes
the authenticated facts and constructs one immutable closed `ControlOutcome`.
Retryability, terminality, promotion authority, disposition, queue kind, next
tier/action, and persistence requirements are read-only projections of that
outcome. Callers cannot construct or persist those values independently.

The fixed-root promotion constructor encodes the complete predicate:
`SURVEY AND fixed-root-deep-v1 AND promotion-proof-code AND promotable-tier AND
strictly-higher-target-tier`. A false conjunct makes `PROMOTION_PENDING`
unconstructable. The exhaustive 32-case matrix admits exactly the one all-true
configuration. Registry identity includes origin, operation, control profile,
code, stage, scope, tier, and current action. The registry includes the audited
vocabulary and the shared `COORDINATE_IDENTITY_MISMATCH`,
`ODE_SOLVER_FAILURE`, and `WORKER_TIMEOUT` paths. Timeout is not precision
evidence.

For fixed-root exterior work, `INSUFFICIENT_ASYMPTOTIC_PRECISION` is not a
promotion code. The distinct `horizon-ingoing` and `infinity-outgoing` branches
each execute bounded same-tier order/geometry recovery under the package-owned
classifier. Order and geometry exhaustion are typed `UNRESOLVED` outcomes.
Only `EXTERIOR_ENDPOINT_ARITHMETIC_INADEQUATE`, as the aggregate sole remaining
blocker, transitions BF40 to `PROMOTION_PENDING / RESPONSE / BF80`. BF80 repeats
the recovery and has no BF120 continuation; mixed blockers never promote.

## Persistence and Recovery

The order is mandatory:

1. validate the control receipt;
2. durably commit `windows-solver.promoted-exterior-control-return/4`;
3. resolve the one canonical transition through `operation_control`;
4. durably commit `windows-solver.promoted-exterior-control-decision/3` with
   the transition ID and canonical event/outcome payload;
5. create the numerical continuation.

Receipt, return, and decision hashes exclude only their own digest fields. A
control continuation is not a calculation and must not use a fabricated
`calculation_sha256`.

Resume revalidates canonical request binding, receipt digest and diagnostics,
operation identity, effective policy, transition ID and payload, and failure
fingerprint before launching BF80. Compatibility booleans are accepted only
when they exactly equal the canonical outcome projection. Recovery never
reclassifies a historical raw receipt under current semantics.

If the five-sample background succeeds and the four-sample component batch
fails, the checkpoint and route accounting retain all five samples, the
background receipt, two worker launches, and the component control proof.

## Structural Trace

Material `windows-solver.structural-event/2` records carry, where applicable:

- operation, execution identity SHA-256, request SHA-256, plan, and scope;
- sample index and role for SAMPLE scope only;
- control receipt, raw return, and decision SHA-256 values;
- transition ID, canonical outcome kind, current action kind, current tier,
  derived retryability/terminality, and next tier;
- endpoint branch, attempted order and geometry, limiting resource, selected
  intervention, and result.

The trace carries identifiers, not duplicated receipt bodies. It must allow a
reader to reconstruct who acted on which authenticated request/sample, which
control receipt was classified, what was committed, and why BF80 launched.

## PR74 Live-Checkpoint Handover

A mandatory fixture test uses a canonical redacted copy of the failed PR74
promoted checkpoint. It proves:

- Binary64 remains 212/212 and is never replayed;
- root evidence and canonical backgrounds remain intact;
- ordinal 0's retained BF80 horizon result remains intact and is not replayed;
- `/1` fixed-root failure evidence is accepted only as forensic history;
- resolving the active system failure does not erase retained evidence;
- ordinal 1 creates a fresh `/3` fixed-root request with no `/1` or `/2` continuation
  authority, root replay, horizon replay, or background loss.

The fixture must be derived from the archived failed checkpoint. A synthetic
look-alike may supplement negative tests but cannot satisfy this handover gate.

## Hosted No-Solver Proof

The decisive CI test traverses production Python request construction, the real
Julia parser/dispatcher, a test-only deterministic evaluator, Julia control
serialization, Python validation and binding, campaign persistence and
classification, checkpoint reload, BF80 scheduling, deterministic Julia
success serialization, Python success authentication, composite construction,
and reduction.

The evaluator is unavailable through the production wire, CLI, environment,
and main dispatcher. The matrix covers all three plans at BF40 and BF80, plus
failure injection at every sample position. No real determinant, ODE, or root
kernel executes.

## Completion Meaning

The completion row is `Successful deterministic fixed-root response path`.
PR75 may prove BF80 request transport, Julia success serialization, Python
authentication, composite construction, and reduction. Real BF80 exterior
numerical behavior remains an operator canary after merge.

## Cause-Aware Exterior Endpoint Recovery Governing Addendum

Before any factored homogeneous RHS evaluation, each required exterior endpoint
is recovered over request-authenticated order-prefix and branch-specific
geometry schedules. Every terminal receipt retains the branch, policy identity
and digest, base/generated/attempted/terminal orders, candidate and terminal
geometry, last-term ratio, truncation/recurrence/series-evaluation loss,
predicted and required digits, candidate and aggregate limitations, causal
attempt history, and a zero-RHS proof.

Python recomputes every attempt and rejects a Julia label, trajectory,
intervention, summary maximum, or aggregate that disagrees with the evidence.
Both adequate receipts are required before the ODE gate opens. Checkpoint
migration moves authenticated `/2` exterior stages and `/2` promoted background
work into append-only `FORENSIC_ONLY` history, resets only those exterior queue
leaves to fresh BF40 `/3`, and preserves Layer-1/Binary64 ledgers, root evidence,
and unrelated successful horizon work.
