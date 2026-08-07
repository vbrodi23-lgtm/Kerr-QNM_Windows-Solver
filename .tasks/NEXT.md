# Next

## TASK-007: Freeze independent golden results for the legacy linear calculation
**Priority:** P1 | **Tags:** M02, evidence, validation
**Assignee:** Unassigned | **Estimate:** 1–2 days | **Milestone:** M02

### Objective

Characterize the accepted component-local response calculations without making legacy code a production dependency.

### Acceptance Criteria

- [ ] Select manifest-declared modes/spins and both horizon/exterior or theory mechanisms as golden fixtures.
- [ ] Record central complex shifts, local solver diagnostics, signed-root uncertainty inputs, covariance, and projective classifications.
- [ ] Authenticate source artifacts, code, runtime, and comparison method.
- [ ] Include adverse/unresolved fixtures and independent published or alternate-backend comparisons where available.

### Dependencies

- **Blocked by:** TASK-005, TASK-006
- **Blocks:** TASK-008, TASK-009, TASK-010

### Evidence Output

Hash-bound linear-response golden fixture set and comparison receipt.

### Verification

undefined

### Review Focus

Confirm fixtures are independent enough to detect migration errors and do not embed obsolete scope.

### Plan

- Select release-domain fixture slices.
- Authenticate and independently compare values.
- Lock tolerances from observed diagnostics, not desired outcomes.

---
