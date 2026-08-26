# Layer 2 Calculation and Admission Separation

## Status

Approved in chat on 2026-08-26. This design repairs PR73 without changing the locked Layer-1 numerical evidence or requesting an operator run.

## Problem

PR73 currently treats absent scientific-admission authority as absent calculation authority. `require_locked_bf40_determinant_error_issuance_authority()` raises unconditionally before the promoted scheduler, and the exterior route repeats that gate before backend construction.

The canonical calibration receipt says otherwise:

- calculation: permitted;
- checkpointing: permitted;
- publication: blocked pending independent review;
- scientific admission: blocked pending independent review.

The current scheduler also persists promoted batches only through outcomes that become SCREENED evidence. Consequently, calculated-but-unadmitted work has no durable owner, horizon work is globally blocked by exterior publication policy, and the policy boundary is misclassified as an unhandled software exception.

## Governing Invariants

1. The existing schema-11 checkpoint and binary64 lock remain the sole Layer-1 authority.
2. Layer 1 is immutable after lock creation.
3. Layer 2 may consume locked predecessors but may not execute binary64 numerical work.
4. Numerical production, evidence admission, and solved-leaf publication are distinct transitions.
5. A known policy boundary returns typed state; it does not raise an unhandled exception.
6. Every completed Layer-2 numerical stage is durable before the scheduler advances.
7. Independent admission reuses retained Layer-2 stages and launches no numerical backend.

## Execution Modes

The calibration receipt parser owns a typed `PromotedExecutionMode`:

- `CALCULATE_AND_ADMIT`: calculation and checkpointing are permitted, and both publication and scientific admission are permitted.
- `CALCULATE_ONLY`: calculation and checkpointing are permitted, while publication or scientific admission awaits independent review.
- `BLOCK_ALL`: calculation or checkpointing is not permitted, or the boundary is otherwise unsupported.

The committed canonical receipt resolves exactly to `CALCULATE_ONLY`.

The legacy-named `require_locked_bf40_determinant_error_issuance_authority()` returns a typed route preflight. It contains no unconditional raise. `BLOCK_ALL` is represented as a known policy result, not `UNHANDLED_PYTHON_EXCEPTION` and not `SOFTWARE`.

## Durable Layer-2 Ownership

The atomic schema-11 checkpoint separates routing from retained numerical work:

- `promotion_queue` owns routing, locked source bindings, current disposition, and an authenticated digest pointer to retained Layer-2 work;
- `promoted_stage_ledger` owns raw BF40/BF80 batches, current-run disagreement terms, timings, predecessor/reuse bindings, and the authenticated stage digest;
- `promoted_background_ledger` owns canonical same-tier backgrounds, exact reuse keys, and equivalence receipts;
- `promoted_root_ledger` owns retained BF80 horizon/root evidence and its uncertainty evidence.

All three ledgers are keyed by queue ordinal and leaf ID. Large numerical stages are never embedded directly in queue entries, and no rejected sidecar is introduced.

The Layer-1 guard continues to validate the source fields before write, after durable readback, and after checkpoint callbacks. Layer-2 fields cannot alter any locked predecessor, route, record, root seal, background object, or source digest.

After calculation, the promoted pass records `CALCULATED_AWAITING_ADMISSION` and the queue records `AWAITING_ADMISSION`. The promoted scheduler treats `AWAITING_ADMISSION` as numerically terminal and never reruns it on resume. Admission remains separately incomplete. These states are not SCREENED.

## Route Execution

Admission policy is evaluated per locked route.

### Exterior

- Consume and authenticate the binary64 provisional predecessor.
- Start at the locked BF40 tier.
- Preserve same-tier background reuse using an exact key that binds BF40 arithmetic, working precision, controls, root seal, fixed root, branch, angular identity, determinant convention, backend, and frequency-step policy.
- The first exact key retains five background samples plus four mechanism samples; compatible routes retain four new mechanism samples and the authenticated reuse receipt.
- Retain the raw and combined BF40 batches, worker receipts, conditioning, and every available current-run disagreement term.
- Stop after BF40 when it is numerically sufficient. Escalate to BF80 only for an allowlisted BF40 numerical insufficiency; absent publication authority alone must never trigger escalation.

### Horizon

- Consume the locked binary64 source record and stage without recomputation.
- Run the locked BF80 route independently of exterior admission status.
- Retain the BF80 stage, component result, comparison terms, worker receipt, and source bindings.

Each queue entry receives only the retained stage digest pointer. The stage/background/root ledgers and queue transition are atomically persisted before moving to the next route.

## Admission

An authenticated independent-review receipt binds:

- the calibration receipt digest;
- the binary64 lock receipt digest;
- reviewer authority and authorization status;
- each leaf, queue ordinal, route, retained stage digest, and route decision.
- the disagreement-term receipt digests and exact scientific identity.

The zero-numerics admission step validates the full retained stage and applies only authorized route decisions. For admitted exterior stages it converts retained current-run determinant-error evidence into reviewed receipts, performs response-space reduction from retained samples, builds the terminal record, and records SCREENED evidence. For admitted horizon stages it builds the terminal record from the retained BF80 stage and records SCREENED evidence.

Admission consumes only `AWAITING_ADMISSION`, transitions the queue and promoted pass to `COMPLETED`, then permits solved-leaf publication. Withheld routes remain `CALCULATED_AWAITING_ADMISSION` / `AWAITING_ADMISSION`. The admission path has no backend, root solver, Julia worker, root read, determinant evaluator, or binary64 evaluator dependency and is idempotent for an identical review receipt.

## Typed Results

Promoted preflight and survey results expose:

- execution mode and policy result code;
- route counts executed and retained;
- locked predecessor evaluation count consumed;
- binary64 recomputation count;
- review-pending and admitted counts;
- SCREENED and publication counts.

Known `BLOCK_ALL` policy results leave the checkpoint intact and return incomplete route identities without creating a system-failure record.

Typed policy results do not weaken authenticated-state checks. Layer-1 lock mismatch, digest mismatch, malformed retained stages, conflicting exact-key backgrounds, conflicting root evidence, scientific identity mismatch, and queue-source mutation remain hard failures.

## Verification

Tests are written before production changes and must prove:

- the authority function contains no unconditional raise;
- the canonical receipt selects `CALCULATE_ONLY`;
- the official mocked 212-route shape executes 172 exterior BF40 routes and 40 horizon BF80 routes;
- 928 locked binary64 predecessor evaluations are consumed and zero are recomputed;
- same-tier background reuse is retained and authenticated;
- Layer 1 remains byte-for-byte/projectively unchanged across every Layer-2 write;
- every BF40/BF80 stage and receipt survives interruption and resume;
- review-pending work creates no SCREENED evidence and no terminal publication;
- independent admission performs zero numerical work and can publish admitted retained records;
- horizon execution is unaffected by exterior publication authority;
- known policy boundaries do not create unhandled/software failures.

Only mocked Python/static/compile checks are run by the development agent. No production solver, Julia worker, or M02 campaign is executed.
