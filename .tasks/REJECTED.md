# Rejected

> TASK-071–TASK-074 retain the historical 553-leaf partition they superseded.
> PR #21 later narrowed the canonical production domain to 212 leaves; these
> rejected records are provenance, not current campaign instructions.

## TASK-071: Superseded bulk primary batch-B evidence campaign
**Priority:** P1 | **Tags:** M02, superseded, evidence
**Assignee:** Unassigned | **Estimate:** Superseded | **Milestone:** M02

### Objective

Retire the separate 126-leaf alpha-half/light-ring production campaign from the software-build scope.

### Acceptance Criteria

- [x] Generic execution is owned by TASK-009.
- [x] Full evidence collection is consolidated into TASK-077 after TASK-075–TASK-076 make the public backend reproducible.
- [x] Representative mechanism coverage remains required by TASK-009 smoke gates.

### Dependencies

- **Blocked by:** TASK-009

### Evidence Output

Supersession record only; no bulk evidence artifact is produced by Codex.

### Verification

- `python .tasks/validate_board.py`

### Review Focus

Confirm no mechanism implementation or exact leaf ID was dropped from TASK-009.

### Plan

- Do not execute this campaign separately.

---

## TASK-072: Superseded bulk primary completion campaign
**Priority:** P1 | **Tags:** M02, superseded, evidence
**Assignee:** Unassigned | **Estimate:** Superseded | **Milestone:** M02

### Objective

Retire the separate 126-leaf alpha1/throat-κ production campaign from the software-build scope.

### Acceptance Criteria

- [x] Generic execution is owned by TASK-009.
- [x] Full evidence collection is consolidated into TASK-077 after TASK-075–TASK-076 make the public backend reproducible.
- [x] Primary 441-ID planning and representative mechanism coverage remain mandatory.

### Dependencies

- **Blocked by:** TASK-009

### Evidence Output

Supersession record only; no bulk evidence artifact is produced by Codex.

### Verification

- `python .tasks/validate_board.py`

### Review Focus

Confirm TASK-009 still validates the exact 441 primary IDs and all mechanisms.

### Plan

- Do not execute this campaign separately.

---

## TASK-073: Superseded bulk control evidence campaign
**Priority:** P1 | **Tags:** M02, superseded, evidence
**Assignee:** Unassigned | **Estimate:** Superseded | **Milestone:** M02

### Objective

Retire the separate 48-leaf control production campaign from the software-build scope.

### Acceptance Criteria

- [x] Generic execution and exact 48-ID control planning are owned by TASK-009.
- [x] Full evidence collection is consolidated into TASK-077 after TASK-075–TASK-076 make the public backend reproducible.
- [x] Negative-m, no-symmetry, and control-only behavior remain required smoke gates.

### Dependencies

- **Blocked by:** TASK-009

### Evidence Output

Supersession record only; no bulk evidence artifact is produced by Codex.

### Verification

- `python .tasks/validate_board.py`

### Review Focus

Confirm control identity and claim-ceiling checks remain in TASK-009.

### Plan

- Do not execute this campaign separately.

---

## TASK-074: Superseded bulk deep-precision evidence campaign
**Priority:** P1 | **Tags:** M02, superseded, evidence
**Assignee:** Unassigned | **Estimate:** Superseded | **Milestone:** M02

### Objective

Retire the separate 64-leaf multiprecision production campaign from the software-build scope.

### Acceptance Criteria

- [x] Generic execution and exact 64-ID deep planning are owned by TASK-009.
- [x] Full multiprecision evidence collection is consolidated into TASK-077 after TASK-075–TASK-076 validate the public BigFloat path.
- [x] Trigger, sentinel, 80/120-digit, exact-Mκ, and unresolved behavior remain required smoke/validation gates.

### Dependencies

- **Blocked by:** TASK-009

### Evidence Output

Supersession record only; no bulk evidence artifact is produced by Codex.

### Verification

- `python .tasks/validate_board.py`

### Review Focus

Confirm the deep precision policy remains executable and fail-closed in TASK-009.

### Plan

- Do not execute this campaign separately.

---
