# Next

## TASK-012: Define spectral-field, co-mode, residue, and genealogy contracts
**Priority:** P1 | **Tags:** M03, physics, architecture
**Assignee:** Unassigned | **Estimate:** 1–2 days | **Milestone:** M03

### Objective

Extend the spectral responsibility beyond root rows with exact normalization and branch objects required downstream.

### Acceptance Criteria

- [ ] Define radial/angular field, derivative, co-mode, residue, normalization, branch-node, branch-edge, κ, and matching-evidence schemas.
- [ ] Specify domain compactification, boundary behavior, precision/resolution policy, and coordinate identity.
- [ ] Keep pure roots compatible with the merged spectral artifact and avoid recomputing unchanged leaves.
- [ ] Reject field artifacts whose normalization or branch identity is unspecified.

### Dependencies

- **Blocked by:** TASK-005
- **Blocks:** TASK-013, TASK-015

### Evidence Output

Versioned spectral-field/genealogy contracts and negative validation fixtures.

### Verification

undefined

### Review Focus

Check whether the public spectral provider remains one owner while internal leaf artifacts stay composable.

### Plan

- Derive contracts from M01 and downstream needs.
- Add strict red tests and compatibility rules.
- Review leaf caching and evidence ceiling.

---
