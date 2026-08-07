# In Progress

## TASK-006: Define the public linear-response artifact and provider contract
**Priority:** P1 | **Tags:** M02, provider, physics
**Assignee:** Codex | **Estimate:** 1–2 days | **Milestone:** M02

### Objective

Specify one field-native artifact for physical first-order complex QNM shifts, local covariance/disks, mechanism identity, and bounded multimode comparisons.

### Acceptance Criteria

- [ ] Define payload keys, units, modes/spins, mechanism parameters, complex covariance, local uncertainty disks, and unresolved classifications.
- [ ] Separate raw roots, pole shifts, projective reductions, and later response-matrix quantities.
- [ ] Bind equations, conventions, numerical policy, runtime, upstream hashes, and evidence ceiling.
- [ ] Reject unsupported mechanisms or coordinates before partial output.

### Dependencies

- **Blocked by:** TASK-005
- **Blocks:** TASK-007, TASK-008

### Evidence Output

Linear-response schema, provider descriptor, validation tests, and example study.

### Verification

- `PYTHONPATH=src python -m unittest tests.test_linear_response_contract -v`
- `PYTHONPATH=src python -m unittest discover -s tests -v`
- `python .tasks/validate_board.py`
- `python tools/validate_release_manifest.py`

### Review Focus

Check field-native terminology, physical mechanism distinctions, and no atlas-wide uncertainty substitute.

### Plan

- Translate frozen manifest into an exact contract.
- Add red contract and identity tests.
- Review evidence boundary before migration.

---
