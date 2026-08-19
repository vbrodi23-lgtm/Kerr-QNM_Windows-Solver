# Promoted-Control Empirical Calibration v1 Implementation Plan

**Goal:** Replace the impossible historical-floor blocker with the
operator-approved, SHA-bound empirical control receipt and make every promoted
exterior determinant carry a fail-closed absolute-error certificate plus a
current-run authenticated derivative lower bound.

**Constraints:** No Julia worker, Kerr determinant, ODE, QNM root solve,
campaign, or PowerShell production script will be run in development. Preserve
binary64 evidence. Do not claim interval arithmetic or independent mathematical
proof.

## Collision and scope

The checkout already contains task-related uncommitted recovery/authentication
changes in `julia_response_backend.py`, `response_batches.py`,
`response_engine.py`, `m02_worker.jl`, and their tests. The operator explicitly
asked to continue and ship this existing PR checkpoint, so this plan builds on
those changes without resetting or discarding them.

Expected changed areas:

- `src/windows_solver/promoted_control_calibration.py` and committed JSON data;
- adaptive controls, Julia adapter, campaign backend, CLI, and receipt/cache
  validators;
- Julia worker and exterior derivative admission;
- `m02.ps1` and the two recovery PowerShell entry points;
- focused Python/static tests, package-data configuration, task record, and
  engineering documentation.

Protected: historical records, existing binary64 behavior, the mathematical
kernel definitions, production outputs, and all pre-existing receipts.

## Steps

1. **Receipt contract (red → green)**
   - Add tests that a canonical default receipt has exactly the five approved
     entries, a pinned digest, valid operator status, the supplied negative
     provenance audit, and an explicit null archived floor for both families.
   - Add strict loader/override tests for digest mismatch, noncanonical bytes,
     wrong schema/status, absent family/tier, and changed identity invalidation.
   - Implement the receipt data model, canonical loader, and family/tier
     empirical-control provider. V1 entries are not serialized
     determinant-to-ODE mathematical budgets.
   - Reuse the established BigFloat-80 ODE controls for BigFloat-40 while
     preserving its existing root-search step bounds; introduce no new numeric
     tolerance value.

2. **Native contract and PowerShell path (red → green)**
   - Add tests proving a native exterior/horizon contract binds its receipt SHA
     and only the reachable family/tier entries; changed receipts invalidate
     promoted, not binary64, computation identity.
   - Add CLI/PowerShell parser tests proving automatic load and the paired
     `-CalibrationReceiptPath`/`-CalibrationReceiptSha256` override contract.
   - Route family-aware empirical controls through the Julia adapter,
     request/runtime,
     journals, checkpoint/cache validators, CLI, and scripts.

3. **Exterior certificate (red → green)**
   - Add behavioral/static tests for the exact three-term maximum, factor 64,
     BigFloat-40 binary64 bridge, and fail-closed unavailable outcome.
   - Implement paired same-point, preceding-tier, and endpoint/series evidence
     in the worker without recursive certification.
   - Bind the certificate model and receipt identity into exterior baseline,
     fixed-root samples, derivative construction, and validation admission.
   - Centralize `L = |D'| - step_disagreement_abs - propagated_error_abs`, reject
     nonpositive current-run bounds, and calculate empirical root disks as
     `determinant_error_abs / L`.
   - Keep the existing authenticated determinant-derivative engine in v1; do
     not add a variational exterior-ODE engine.

4. **Regression and review checkpoint**
   - Run focused tests after every slice, then the permitted full Python suite,
     compile, TaskPlanner validation, diff hygiene, and static PowerShell/Julia
     checks.
   - Perform change review, update TASK-079 and PR #55 with the native test
     command plus the still-pending independent-review boundary.

**First red signal:** importing/loading the approved canonical calibration
receipt from the new test must fail before the provider exists. The post-change
proof is a concrete canonical receipt plus contract, cache-invalidation,
certificate, CLI, and script tests—never a live numerical run.
