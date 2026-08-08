# In Progress

## TASK-010: Build the empirical uncertainty and projective-reduction pipeline
**Priority:** P1 | **Tags:** M02, evidence, physics, tooling
**Assignee:** Codex | **Estimate:** 1–2 days | **Milestone:** M02

### Objective

Build deterministic uncertainty propagation and projective reduction that operates on user-supplied complete evidence, while validating the algorithms with synthetic and representative smoke inputs.

### Acceptance Criteria

- [ ] Propagate signed-root, centred-step, refinement, continuation-path, and precision-ladder channels through the response/Richardson algebra.
- [ ] Construct PSD component and cross-component empirical error Gram matrices from shared signed channels without statistical-covariance claims.
- [ ] Compute the frozen 162 primary and 12 deep projective row schemas only when aligned inputs exist; partial smoke inputs return an explicit incomplete state, never a scientific classification.
- [ ] Smoke-test head/tail/risk reductions, zero-containing calibrations, non-PSD rejection, unresolved propagation, and available independent holdouts.
- [ ] Accept the complete external 553-leaf bundle later without code or threshold changes.

### Dependencies

- **Blocked by:** TASK-009
- **Blocks:** TASK-011

### Evidence Output

Reusable signed-channel and empirical-Gram schema, exact 174-row planner,
partial-honest projective reducer, exactly six synthetic/representative smoke
cases, zero-backend `campaign-reduce` command, and PowerShell handoff.

### Verification

- `PYTHONPATH=src python -m unittest tests.test_linear_response_uncertainty tests.test_linear_response_projective tests.test_linear_response_contract -v`
- `PYTHONPATH=src python -m unittest discover -s tests -v`
- `python .tasks/validate_board.py`

### Review Focus

Check signed coefficients, shared-root correlation, PSD marginals, deterministic terminology, partial-state honesty, and outcome-neutral thresholds.

### Plan

- Version TASK-009 stage/checkpoint evidence so each digested stage owns a strict complete signed-channel ledger; reject stale v1 and external evidence injection.
- Serialize and semantically recompute every empirical Gram carried by a campaign reduction artifact.
- Replace finite full-amplitude perturbation with a frozen calibrated-normalized local Jacobian and explicit `J G J^T` diagnostic.
- Preserve exactly six smoke cases, run the required gates, update the report, and restore TASK-011 as sole Next.

---
