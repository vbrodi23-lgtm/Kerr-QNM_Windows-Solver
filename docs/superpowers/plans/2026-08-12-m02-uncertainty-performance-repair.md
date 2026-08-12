# M02 Uncertainty, Performance, and Interruption Repair Plan

## Goal

Repair the live M02 response uncertainty reduction, remove duplicate determinant evaluations in both numerical backends, invalidate only scientifically incompatible campaign evidence, and make operator interruption honest and resumable without running the scientific solver in this development environment.

## Constraints

- Do not execute Kerr, GSN, Julia, campaign, or other scientific solver paths locally.
- Preserve response centres, numerical controls, branch-continuation checks, runtime/depot caches, generated GSN caches, and checkpoint atomicity.
- Verify with focused unit/static tests, compilation, board validation, and diff review only; the user supplies Windows/PowerShell scientific execution logs.

## Implementation

1. Add failing response-engine and adapter tests proving diagnostic root shifts are reduced to response units through signed secants and the existing two-finest-level Richardson rule, with baseline diagnostic shifts excluded.
2. Extend live root readouts with authenticated per-phase root evidence while retaining the legacy scalar mapping for recorded replay compatibility; compute truncation, resolution, and seed-path response-disk increments relative to the primary signed response.
3. Add call-count regression tests and carry exact accepted determinant values between Newton iterations; reuse an accepted centred derivative instead of recomputing it in Python and Julia.
4. Bind the corrected uncertainty contract into solved-leaf/checkpoint scientific identity, reject predecessor receipt migration, and prove runtime/depot/generated-GSN cache identities remain separate.
5. Add explicit leaf, campaign, and request interruption progress events; report `INTERRUPTED` without failure counts, associate checkpoint persistence with the correct leaf, emit a concise CLI error, and preserve process exit code 130 through PowerShell.
6. Run only non-scientific focused tests and static verification, update TASK-075 evidence, perform an independent change review, commit, and open a draft PR for CI and user-run PowerShell evidence.

## Verification

- Focused response-engine, native-kernel, Julia-adapter, solved-leaf, progress, response-batch, CLI, and launcher tests.
- `python -m compileall -q src tests tools`
- `python .tasks/validate_board.py`
- Static inspection of Julia and PowerShell changes.
- No scientific solver execution.
