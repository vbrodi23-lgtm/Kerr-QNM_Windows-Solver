# In Progress

## TASK-001: Freeze the release completion manifest and reconcile every claimed legacy/public result against actual artifacts, hashes, tests, and merged PRs
**Priority:** P0 | **Tags:** M01, evidence, architecture
**Assignee:** Codex | **Estimate:** 1–2 days | **Milestone:** M01

### Objective

Create the single release-domain manifest that defines what the solver must compute and proves the current state of every claimed input without trusting narrative status labels.

### Acceptance Criteria

- [ ] Enumerate required modes, spins, branches, parent pairs, theories, waveforms, detector cases, platforms, and evidence profiles.
- [ ] For every claimed result, record artifact location, SHA-256, generating code/commit, merged PR, tests, license, conventions, and strongest evidence state.
- [ ] Classify each item as publicly admitted, validated legacy evidence, framework only, missing, invalid, or superseded; missing receipts fail closed.
- [ ] Record unresolved scope questions as governance decisions or blockers rather than assumptions.

### Dependencies

- **Blocked by:** M00 project-control setup (complete)
- **Blocks:** TASK-002, TASK-003, TASK-004

### Evidence Output

Versioned completion manifest plus reconciliation report with no unreferenced scientific claim.

### Verification

- `python -m unittest tests.test_release_manifest -v`
- `python tools/validate_release_manifest.py`

### Review Focus

Look for legacy code being treated as a provider, unsupported evidence promotion, omitted release-domain coordinates, and private labels.

### Plan

- Inventory primary repository, merged-PR, retained-artifact, and supplied research-context evidence.
- Freeze the exact release domain and classify every claim without promoting external evidence to a provider.
- Admit a strict machine-readable manifest only after source receipts, ownership, conventions, and evidence ceilings validate.

---

