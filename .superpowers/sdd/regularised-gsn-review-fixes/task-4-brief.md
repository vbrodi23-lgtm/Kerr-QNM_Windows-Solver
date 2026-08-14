# Task 4 brief — independent activation gates

## Goal

Make human mathematical approval and the independent high-precision reference fixture two distinct, fail-loud, versioned activation gates. A future fixture addition must not silently activate production without separate human approval.

## Required workflow

1. Work strict TDD. Add runnable Python static/contract tests and air-gapped Julia specifications first; record Python RED before production edits.
2. In `FactoredSolutions.jl`, add a separately exported human-math-review receipt assertion with its own versioned receipt/status identity. Keep the existing independent-reference assertion distinct. `assert_regularised_gsn_production_ready()` must require both.
3. Do not create, approve, sign, freeze, or invent either receipt. Both assertions must still fail loudly with gate-specific messages in this branch.
4. Replace the ambiguous combined activation status with explicit identities for:
   - independent reference fixture receipt/status;
   - human math review receipt/status covering carrier signs, horizon basis order/normalisation, determinant chart, and the unresolved contour-tangent review.
   Use explicit absent/unapproved state and null digest (or an equivalently strict representation); do not use a fake SHA-256.
5. Bind both gate identities through the Python precision policy, Julia request validation, worker response evidence, scientific runtime mapping, `RootReadout`/component/checkpoint serialization, and cache identity. A stale response or cache entry with the combined/one-gate policy must not authenticate as current.
6. If the conditioning/response schema must change to carry these identities, version it explicitly and update only current fixtures/contracts. Preserve explicit historical checkpoint compatibility through the schema-aware path; do not allow current evidence to omit either gate.
7. Add tamper tests for swapping either status/digest and tests proving the production gate still blocks if only one future gate is hypothetically satisfied.
8. Run focused mocked/static Python tests only. Do not execute Julia, PowerShell, Kerr determinants, solver commands, or scientific payloads.
9. Commit locally, do not push.

## Acceptance

- Two distinct exported gate assertions exist and both are called by production readiness.
- Neither receipt exists or claims approval.
- Exact gate status/digest identities survive request -> worker response -> runtime/readout -> checkpoint/cache paths.
- Current policy rejects old combined-only evidence; historical checkpoints remain bounded to their explicit schemas.
- Focused mocked/static Python checks pass; Julia specs are present but unexecuted.

## Report

Write `.superpowers/sdd/regularised-gsn-review-fixes/task-4-report.md` with exact RED/GREEN evidence, files, limitations, and commit SHA; update the Task 4 ledger line.
