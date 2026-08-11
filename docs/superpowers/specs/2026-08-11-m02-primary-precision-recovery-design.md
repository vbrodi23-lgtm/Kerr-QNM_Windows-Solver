# M02 PRIMARY precision-recovery design

**Date:** 2026-08-11

**Milestone:** M02

**Status:** Approved for implementation

## Outcome

Every `PRIMARY` response leaf gets one conditional recovery path when its
authenticated binary64 component result is `NOT_CONVERGED`. The campaign runs
the existing 80-digit stage, escalates to 120 digits only under the rules below,
and publishes a terminal record without weakening branch authentication,
enclosure evidence, or the existing scientific policy.

`CONTROL` remains binary64-only. `DEEP` retains its existing trigger, sentinel,
and promotion grammar byte-for-byte. `BRANCH_LOSS`, `NOISE_FLOOR`, and
`AXIS_MISMATCH` remain terminal scientific outcomes and never trigger PRIMARY
precision promotion.

## PRIMARY state machine

The campaign authenticates every production `ComponentResult` against the
selected leaf, baseline root, branch identity, policy, backend, and readout
lineage before using its status as a promotion signal.

| Stage | Result/evidence | Next action |
|---|---|---|
| 64 | `CONVERGED` | Terminal `PRODUCED` |
| 64 | `BRANCH_LOSS`, `NOISE_FLOOR`, or `AXIS_MISMATCH` | Terminal `UNRESOLVED`; never promote |
| 64 | authenticated `NOT_CONVERGED` | Run 80 digits |
| 80 | `BRANCH_LOSS`, `NOISE_FLOOR`, or `AXIS_MISMATCH` | Terminal `UNRESOLVED`; never promote |
| 80 | authenticated `NOT_CONVERGED` | Run 120 digits |
| 80 | `CONVERGED`, self-refinement enclosed, and 64/80 discrepancy enclosed | Terminal `PRODUCED` |
| 80 | `CONVERGED` with failed self-refinement or unenclosed 64/80 discrepancy | Run 120 digits |
| 120 | `CONVERGED` and 80/120 discrepancy enclosed | Terminal `PRODUCED` |
| 120 | any other authenticated outcome | Terminal `UNRESOLVED` |

When a required promoted tier is unavailable, the leaf remains
`MISSING_PRECISION` with the required digit count. It is not misreported as a
terminal scientific failure and is not written to the solved-leaf store.

## Contract and checkpoint identity

One canonical PRIMARY recovery-policy fragment is shared by execution,
semantic validation, scientific identity, and checkpoint binding. It declares:

- binary64 trigger: authenticated `NOT_CONVERGED` only;
- recovery digits: 80 then optional 120;
- independent 120 gates: 80 remains `NOT_CONVERGED`, 80 self-refinement is not
  enclosed, or 64/80 discrepancy is not enclosed;
- terminal 120 success: `CONVERGED` with enclosed discrepancy.

The fragment enters only `PRIMARY` leaf scientific identities. Existing
`CONTROL` and `DEEP` identity material remains unchanged. The campaign's
existing `precision_contract_sha256` checkpoint binding also includes this
fragment, so checkpoints created under the old orchestration policy are
rejected without changing campaign schema 2, checkpoint schema 3, the numerical
policy, or the native-backend identity.

## Exact legacy-success migration

Changing the PRIMARY precision contract changes PRIMARY solved-leaf identities.
The cache lookup therefore derives the one exact immediately preceding
binary64-only identity rather than trusting a generic same-leaf stale receipt.
It may republish a legacy record under the new identity only when all of these
conditions hold:

- the independently sealed receipt exists at that exact legacy identity;
- the record is `PRIMARY`, `PRODUCED`, and has exactly one 64-digit stage;
- the component status is canonically `CONVERGED`;
- no promotion, deep-trigger, sentinel, comparison, or missing-precision fields
  are present;
- full current leaf/job/factory/root/policy/backend/readout authentication passes;
- the record is valid under the new PRIMARY semantic grammar.

The inner campaign record is republished unchanged and the legacy receipt is
retained. A legacy `UNRESOLVED` PRIMARY record is never migrated; it is
recomputed so authenticated `NOT_CONVERGED` can enter the new recovery ladder.
Receipts from arbitrary stale identities, malformed evidence, or changed
tolerances/backends are not migrated. Old checkpoints are rejected rather than
migrated.

## Protected behavior

This change does not alter determinant evaluation, Julia execution, tolerance
values, component-status classification, branch semantics, CONTROL execution,
DEEP sentinel behavior, sealed record fields, or public schema/backend versions.
Verification uses synthetic structural outcomes only. Local solver, Julia,
PowerShell, and mathematical workloads are outside this implementation run.

## Verification matrix

Synthetic tests cover 64-digit success, every non-promoting terminal status,
authenticated 64→80 recovery, each independent 80→120 gate, all 120 terminal
outcomes, missing promoted capabilities, CONTROL and DEEP regressions, exact
legacy-success migration, legacy-unresolved recomputation, arbitrary-stale and
corrupt receipt rejection, and old-checkpoint binding rejection.
