# Task 2 brief — checkpoint and recovery persistence closure

## Goal

Close three authenticated campaign persistence gaps without executing scientific code.

## Required workflow

Work strict TDD. Add focused mocked Python regressions and observe each relevant test fail before changing production code. Use existing fixture builders rather than creating scientific values.

### A. Current schema cannot downgrade itself to historical conditioning

- Pass the actual checkpoint schema version into component/runtime validation.
- For current schema 6 and current solved-leaf receipts, package-promoted evidence must carry complete per-readout conditioning, exact determinant fields required by its mechanism, and the exact `regularised_gsn_precision_policy` runtime binding.
- Permit the pre-conditioning shape only for explicit historical schema versions already recognized by the checkpoint loader. Do not infer “historical” merely from missing fields.
- Add a schema-6 tamper regression that strips conditioning/determinant fields and the runtime policy, reseals ordinary content hashes, and is rejected. Preserve an explicit historical compatibility regression.

### B. Cached 64-to-120 recovery must materialize its predecessor

- A terminal solved-leaf record with stages `(64, 120)` embeds its authenticated 80-digit failed-preflight predecessor. When a cold campaign consumes that cache hit, materialize a matching predecessor into the outer checkpoint attempt list before writing.
- Reconstruct/renumber the attempt safely so global attempt ordinals remain contiguous. If renumbering changes the attempt digest, update the record’s embedded predecessor mapping to the identical reconstructed attempt; do not mutate the solved-leaf store receipt.
- Avoid duplicate predecessor attempts on resume or repeated lookup.
- Add an end-to-end mocked regression: cache hit -> write checkpoint -> full checkpoint validation -> resume without executing that leaf.

### C. A 120-digit insufficient-asymptotic-precision failure is durable and terminal for promotion

- `_execution_attempt_from_failure` must apply the special 80-digit failed-preflight predecessor validator only at 80 digits. A well-formed 120-digit `INSUFFICIENT_ASYMPTOTIC_PRECISION` control failure must remain containable.
- Persist that 120-digit attempt in the checkpoint, continue later leaves, and do not request or attempt another precision promotion for that leaf on resume.
- Keep the checkpoint explicitly partial/deferred unless an existing domain state honestly supports terminal unresolved; do not fabricate a scientific result.
- Add mocked tests covering initial containment, later-leaf continuation, validation/reload, and resume without a second 120 attempt.

## Constraints

- Do not run Julia, PowerShell, Kerr determinants, solver commands, or scientific payloads.
- Use apply_patch for edits.
- Keep changes scoped to checkpoint/recovery orchestration and its tests.
- Do not weaken request/job/precision binding or solved-leaf quarantine behavior.
- Commit locally, do not push.

## Report

Write `.superpowers/sdd/regularised-gsn-review-fixes/task-2-report.md` with exact RED/GREEN evidence, files, limitations, and commit SHA; update the Task 2 ledger line.
