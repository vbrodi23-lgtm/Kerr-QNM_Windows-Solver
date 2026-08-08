# Next

## TASK-011: Build fail-closed M02 validation, admission, and operator closure commands
**Priority:** P1 | **Tags:** M02, provider, validation, tooling
**Assignee:** Unassigned | **Estimate:** 1 day | **Milestone:** M02

### Objective

Finish the installable M02 machinery and operator handoff while keeping the linear-response provider unavailable until the user's complete PowerShell evidence bundle passes admission.

### Acceptance Criteria

- [ ] Validate exactly 553 produced leaves, zero missing leaves, governed unresolved IDs, 174 aligned projective rows, role ceilings, hashes, runtime lineage, and policy identity.
- [ ] Provide PowerShell-friendly `validate`, `reduce`, `admit`, and `export` commands with deterministic machine-readable output and useful failure messages.
- [ ] Prove smoke/partial bundles cannot register the provider; prove a structurally complete signed test bundle exercises the availability transition without claiming scientific evidence.
- [ ] Keep exactly one provider owner, unrelated capabilities unchanged, and admission contingent on the external evidence receipt rather than build completion.
- [ ] Pass Windows-oriented command/path tests, Ubuntu tests, cold/warm cache, wheel content, manifest, compile, and head/tail/risk end-to-end smoke gates.

### Dependencies

- **Blocked by:** TASK-010
- **Blocks:** TASK-037, TASK-038

### Evidence Output

Installable build, fail-closed admission CLI, PowerShell runbook, structural full-bundle test fixture, representative smoke receipts, CI/cache/export checks, and build-completion report that distinguishes software readiness from scientific evidence completion.

### Verification

- `PYTHONPATH=src python -m unittest tests.test_linear_response_provider tests.test_linear_response_cli tests.test_release_manifest -v`
- `PYTHONPATH=src python -m unittest discover -s tests -v`
- `python .tasks/validate_board.py`
- `python tools/validate_release_manifest.py`
- `python -m compileall -q src tools tests`

### Review Focus

Inspect partial/full separation, provider uniqueness, Windows command behavior, exact count reconciliation, evidence gating, and honest readiness language.

### Plan

- Integrate the importer, runner, and reducer behind operator commands.
- Exercise structural full-bundle and representative smoke paths.
- Ship build readiness without fabricating or collecting the user's research evidence.

---
