# Kerr Solver TaskPlanner

This board is the executable work system for the Kerr Solver Completion Programme. Programme governance is maintained in Notion; no private workspace identifier is stored in this public repository.

## Authority

- Notion controls the programme charter, M00–M12 milestone status, decisions, risks, and blockers.
- This board controls 1–2 day executable tasks, dependencies, acceptance checks, evidence outputs, and PR state.
- Computed artifacts and merged provider code control scientific and implementation truth.

Do not create another stage list. Do not mark a milestone complete because code exists. A completed task must carry verification, provenance, an evidence ceiling, and a commit/PR reference when repository content changed.

## Queue rules

- One dependency-ready task belongs in `NEXT.md` while open work remains and no task is in progress.
- At most one task belongs in `IN_PROGRESS.md`; `NEXT.md` stays empty while that task is active.
- A blocked task stays in Backlog with its dependency recorded.
- Task IDs never change.
- Scientific scope or dependency changes require an accepted Notion decision before board edits.

## Milestone task ranges

| Milestone | Tasks |
|---|---|
| M01 — Scope and evidence baseline | TASK-001–TASK-005 |
| M02 — Public linear response | TASK-006–TASK-011 |
| M03 — Spectral fields and branch genealogy | TASK-012–TASK-017 |
| M04 — Operator stability and pseudospectra | TASK-018–TASK-023 |
| M05 — First-order handoff and derivative couplings | TASK-024–TASK-029 |
| M06 — Physical quadratic response | TASK-030–TASK-036 |
| M07 — Physical response matrix | TASK-037–TASK-041 |
| M08 — Physical inverse inference | TASK-042–TASK-047 |
| M09 — Signals and waveforms | TASK-048–TASK-053 |
| M10 — Detector inference | TASK-054–TASK-058 |
| M11 — Canonical evidence package | TASK-059–TASK-063 |
| M12 — Reproducible release | TASK-064–TASK-068 |

Run `python .tasks/validate_board.py` after every structural board edit.
