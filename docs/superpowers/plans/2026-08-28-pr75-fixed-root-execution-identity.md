# PR75 Fixed-Root Execution-Identity Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Carry fixed-root request identity, typed control outcomes, promotion proof, diagnostics, and recovery end to end so an expected BF40 asymptotic insufficiency is durably promoted to BF80 without replaying retained PR74 work.

**Architecture:** A dedicated operation-control module owns operation-discriminated identities, validated receipts, and the bounded promoted ROOT/RESPONSE transition registry. Python emits fixed-root request `/2`; Julia projects request identity to each selected sample and emits authenticated success or control documents. Campaign persistence records raw return before decision, checkpoints the full proof, revalidates it on resume, and emits reconstructable structural-event identifiers.

**Tech Stack:** Python 3.12, Julia 1.10 hosted no-solver contract harness, dataclasses/enums, canonical SHA-256 JSON documents, `unittest`, schema-11 checkpoint infrastructure, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-08-28-pr75-fixed-root-execution-identity-design.md`

## Global Constraints

- Do not run a production M02 campaign, determinant kernel, root solver, ODE solver, or numerical Julia worker.
- Preserve all operator evidence; never rewrite a live checkpoint during development.
- `/1` fixed-root documents are forensic-only and cannot authorize execution or continuation.
- Write a meaningful failing test before each production behavior change.
- Keep the transition registry limited to CONTROL outcomes reachable through promoted ROOT/RESPONSE and their shared control paths.
- Deterministic CI success is a response-path proof, not numerical Kerr evidence.

## Task Interface Table

| Task | Produces | Consumes | Must not own |
| --- | --- | --- | --- |
| 1 | Operation identity, receipt validator, transition registry | Canonical JSON/hash helpers | Julia transport or campaign persistence |
| 2 | Fixed-root request `/2`, indexed descriptors, reliability projection | Task 1 identity projection | Julia failure serialization |
| 3 | Julia `/2` parse, scoped identity, control/success serialization | Tasks 1-2 contracts | Campaign classification |
| 4 | Python success/control binding and exceptions | Tasks 1-3 wire documents | Campaign scheduling |
| 5 | Raw return/decision persistence, accounting, trace, resume validation | Tasks 1-4 validated results | Request construction |
| 6 | PR74 live-checkpoint handover gate | Task 5 recovery contract, archived fixture | Numerical execution |
| 7 | Hosted no-solver seam and full matrix | Tasks 1-6 production seams | Production evaluator access |
| 8 | Closure audit, docs, CI, full verification | Entire diff | New behavior outside contract |

---

### Task 1: Operation identity, validated control receipts, and bounded registry

**Files:**
- Create: `src/windows_solver/operation_control.py`
- Create: `tests/test_operation_control.py`
- Modify: `src/windows_solver/campaign_failures.py`
- Modify: `tests/test_campaign_failures.py`

**Interfaces:**
- Produces `OperationExecutionIdentity`, request/sample scope validation, `OperationControlReceipt`, `ValidatedControlReceipt`, canonical receipt hashing, `PromotedControlTransition`, and one closed promoted ROOT/RESPONSE registry.
- Consumes existing canonical JSON helpers and current campaign disposition/queue vocabulary without creating a second policy table.

- [ ] Write failing tests for exact root and fixed-root identity variants, REQUEST/SAMPLE field exclusion, digest tampering, incomplete diagnostics, every audited reachable code, queue-kind separation, timeout non-promotion, and reverse root/fixed-root contamination.
- [ ] Run `PYTHONPATH=src python3 -m unittest -v tests.test_operation_control tests.test_campaign_failures` and preserve meaningful red output.
- [ ] Implement the schema types and validators. Only `validate_operation_control_receipt()` may construct `ValidatedControlReceipt`.
- [ ] Move promoted ROOT/RESPONSE CONTROL dispositions into the bounded registry and make legacy campaign classification delegate to it where applicable.
- [ ] Run the focused tests green and commit as `feat(control): add operation-aware promoted control contracts`.

### Task 2: Fixed-root request `/2` and calibrated reliability projection

**Files:**
- Modify: `src/windows_solver/julia_response_backend.py`
- Modify: `tests/test_julia_fixed_root_survey_batch.py`
- Modify: `tests/test_promoted_exterior_wire_contract.py`
- Modify: `tests/test_promoted_exterior_request_flattening.py`

**Interfaces:**
- Produces `windows-solver.fixed-root-survey-batch/2`, explicit plan, indexed `{sample_index, sample_role}` descriptors, request SHA binding, effective-policy identity, and fixed-root reliability target/rule.
- Consumes Task 1 identity projection and the authoritative promoted calibration profile.

- [ ] Write failing tests proving request `/2`, all exact plan roles, outer REQUEST identity without sample fields, indexed nested descriptors, numeric authority `2e-11`, and rejection of executable `/1` or a restored root tolerance.
- [ ] Run the focused tests red.
- [ ] Implement `/2` construction and strict validation; remove producer-side `/1` compatibility and keep `/1` handling explicitly forensic-only.
- [ ] Ensure request hashing covers plan, descriptors, reliability projection, effective policy, branch, and root seal.
- [ ] Run focused tests green and commit as `feat(fixed-root): issue versioned request identities`.

### Task 3: Julia operation-aware parsing, reliability, control, and success paths

**Files:**
- Modify: `src/windows_solver/data/julia/m02_worker.jl`
- Create: `tests/julia/test_fixed_root_operation_control.jl`
- Modify: `tests/test_julia_worker_contract.py`
- Modify: `tests/test_promoted_request_preflight.py`

**Interfaces:**
- Produces strict `/2` flattening/validation, REQUEST-to-SAMPLE identity projection, fixed-root-specific reliable-digit calculation, `operation-control-receipt/1`, fixed-root success `/2`, conditioning `/2`, and operation-aware progress `/2` data.
- Consumes Tasks 1-2 wire contracts.

- [ ] Add static/Python red checks for the known `required_reliable_digits()` contradiction, root-only `control_failure_context()`, display-text role coupling, and `/1` constants.
- [ ] Add a no-solver Julia contract script that exercises parsing, identity projection, deterministic control serialization, and deterministic success serialization without entering determinant/root/ODE code.
- [ ] Implement operation-dispatched reliability and failure context. Fixed-root uses only its calibrated reliability projection; root-readout retains its root tolerance.
- [ ] Emit typed sample identity for every sample failure and request identity for request failures; emit `/2` success and conditioning documents authenticated to the request.
- [ ] Run Python static tests and the Julia contract script where Julia is available; commit as `fix(julia): carry fixed-root control identity end to end`.

### Task 4: Python operation-aware success and control binding

**Files:**
- Modify: `src/windows_solver/julia_response_backend.py`
- Modify: `src/windows_solver/response_batches.py`
- Modify: `tests/test_julia_response_backend.py`
- Modify: `tests/test_worker_lifecycle_contract.py`
- Modify: `tests/test_julia_fixed_root_survey_batch.py`

**Interfaces:**
- Produces operation-aware raw deserialization, canonical request binding for every CONTROL code, validated exceptions containing `ValidatedControlReceipt`, success authentication, and timeout receipts.
- Consumes Tasks 1-3 schemas.

- [ ] Write failing tests for every fixed-root sample position, every reachable control code, request/sample mismatch, plan/root-seal/branch/effective-policy tampering, timeout origin/stage, and root-readout identity preservation.
- [ ] Run focused tests red.
- [ ] Replace root-shaped `_bind_failed_preflight_failure_to_request()` semantics with operation-dispatched canonical binding for every CONTROL outcome.
- [ ] Require a validated receipt before constructing a containable numerical-control exception; make supervisor timeout produce the same receipt schema without pretending it is Julia precision evidence.
- [ ] Authenticate `/2` success and per-sample identities before returning a fixed-root batch.
- [ ] Run focused tests green and commit as `fix(backend): authenticate operation-aware worker outcomes`.

### Task 5: Campaign proof persistence, routing, accounting, and structural trace

**Files:**
- Modify: `src/windows_solver/campaign_survey.py`
- Modify: `src/windows_solver/campaign_policy.py`
- Modify: `src/windows_solver/campaign_failures.py`
- Modify: `src/windows_solver/structural_diagnostics.py`
- Modify: `src/windows_solver/progress.py`
- Modify: `tests/test_promoted_survey_scheduler.py`
- Modify: `tests/test_campaign_schema11.py`
- Modify: `tests/test_structural_diagnostics.py`
- Modify: `tests/test_task3c_conditioning_surfaces.py`

**Interfaces:**
- Produces raw control return `/2`, classified decision `/1`, receipt/request-bound fingerprint, queue-kind enforcement, full continuation proof, resume revalidation, accurate partial-route accounting, progress `/2`, and material structural-event/2 identifiers.
- Consumes Task 4 validated success/control results and Task 1 transition registry.

- [ ] Write failing scheduler tests proving validate-return-classify-decision-continuation order, durable interruption points, no fabricated calculation digest, queue-kind enforcement, malformed diagnostics fail-closed, root/fixed-root operation separation, and BF40 insufficiency to RESPONSE/BF80.
- [ ] Write failing accounting test: background five succeeds, component four fails, sample count remains five, background receipt remains present, worker launch count is two.
- [ ] Write failing structural/progress tests for operation, identity/request hashes, plan/scope/sample fields, receipt/return/decision hashes, and current/next action/tier fields.
- [ ] Implement immutable receipt-derived campaign reports and fingerprints; remove hardcoded fixed-root labels and caller-asserted diagnostic completeness.
- [ ] Persist raw return before pure registry classification and persist decision before continuation. Revalidate the complete proof on reload.
- [ ] Update route accounting immediately after each durably completed batch.
- [ ] Run focused tests green and commit as `feat(campaign): persist and replay promoted control proof`.

### Task 6: Exact PR74 live-checkpoint handover gate

**Files:**
- Add archived fixture: `tests/fixtures/m02_pr74_failed_promoted_checkpoint.json.xz`
- Create: `tests/test_pr74_checkpoint_handover.py`
- Modify recovery code only where the red fixture exposes a contract gap.

**Interfaces:**
- Produces a tested boundary from the archived failed PR74 checkpoint to fresh `/2` ordinal-1 execution authority.
- Consumes Task 5 recovery validation and the archived operator checkpoint fixture.

- [ ] Import a canonical redacted copy of the archived PR74 failed checkpoint. Verify its source checkpoint SHA and record the redaction method; do not synthesize a look-alike.
- [ ] Write the mandatory failing fixture test proving Binary64 212/212, root evidence, canonical backgrounds, and ordinal-0 BF80 horizon retention; `/1` failure evidence is forensic-only; active failure resolution leaves evidence intact; ordinal 1 emits a fresh `/2`; no Binary64, root, horizon, or retained-background replay/loss occurs.
- [ ] Run the test red against main behavior, implement only the exposed handover migration, then run green.
- [ ] Commit as `test(recovery): prove PR74 checkpoint handover to request v2`.

### Task 7: Hosted no-solver lifecycle seam and complete matrix

**Files:**
- Create: `tests/pr75_fixed_root_contract_fixture.py`
- Create: `tests/julia/test_pr75_fixed_root_lifecycle.jl`
- Create: `tests/test_pr75_fixed_root_lifecycle.py`
- Modify: `.github/workflows/ci.yml`
- Modify production files only for defects exposed by the real seam.

**Interfaces:**
- Produces one deterministic test-only evaluator and a hosted end-to-end lifecycle proof through production Python/Julia parsers, serializers, binders, campaign persistence, reload, BF80 scheduling, success authentication, composite construction, and reduction.
- Consumes Tasks 1-6 production seams.

- [ ] Add a structural gate proving the evaluator cannot be selected through production request bytes, CLI, environment, or main dispatcher.
- [ ] Implement six deterministic success cases: three plans at BF40 and BF80.
- [ ] Implement 36 deterministic failure cases: every sample position across all three plans at BF40 and BF80.
- [ ] Implement the decisive BF40 insufficiency to durable raw return/decision, reload, BF80-only success, authenticated composite, and reduction path.
- [ ] Add closed-registry tests for every fixed-root-reachable code, timeout handling, root identity retention, queue enforcement, and full failure proof persistence.
- [ ] Wire the no-solver Julia test into hosted CI and commit as `test(ci): exercise fixed-root lifecycle through real Julia seam`.

### Task 8: Contract closure, review, and PR completion

**Files:**
- Modify: PR75 pull-request body and repository docs/tests only as required by verified evidence.

**Interfaces:**
- Produces a 19/19 completion matrix with exact commands and limitations.
- Consumes the complete branch diff and all prior proof.

- [ ] Search for executable fixed-root `/1`, root-shaped generic binders/reporters, hardcoded diagnostic completeness, ignored queue kinds, and unbound fixed-root control paths. Add a regression test for each surviving false genericity before fixing it.
- [ ] Run focused Python tests, the full Python suite, Julia no-solver contract scripts, compile/static checks, and workflow syntax validation.
- [ ] Obtain independent whole-branch architecture and correctness review; resolve every blocker and rerun affected proof.
- [ ] Commit any review repairs without rewriting history, push normally, and update the PR body with exact evidence and explicit numerical limitations.
- [ ] Shepherd CI/review state to green. Do not merge until the user confirms the exact final head SHA.

## Required Final Evidence

- Baseline: `PYTHONPATH=src python3 -m unittest discover -s tests -v` passed 1,292 tests with 10 skips before implementation.
- Focused red and green evidence for every task.
- Six success plus 36 sample-failure matrix cases through the real no-solver Julia seam.
- Exact archived PR74 checkpoint handover fixture proof.
- Full Python suite and hosted Julia no-solver CI green.
- Independent review with no unresolved blockers.
- PR75 completion matrix uses `Successful deterministic fixed-root response path` and explicitly leaves real BF80 numerical execution to the post-merge operator canary.
