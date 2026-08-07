# Done

## TASK-001: Freeze the release completion manifest and reconcile every claimed legacy/public result against actual artifacts, hashes, tests, and merged PRs
**Priority:** P0 | **Tags:** M01, evidence, architecture
**Assignee:** Codex | **Estimate:** 1–2 days | **Milestone:** M01

### Objective

Create the single release-domain manifest that defines what the solver must compute and proves the current state of every claimed input without trusting narrative status labels.

### Acceptance Criteria

- [x] Enumerate required modes, spins, branches, parent pairs, theories, waveforms, detector cases, platforms, and evidence profiles.
- [x] For every claimed result, record artifact location, SHA-256, generating code/commit, merged PR, tests, license, conventions, and strongest evidence state.
- [x] Classify each item as publicly admitted, validated legacy evidence, framework only, missing, invalid, or superseded; missing receipts fail closed.
- [x] Record unresolved scope questions as governance decisions or blockers rather than assumptions.

### Dependencies

- **Blocked by:** M00 project-control setup (complete)
- **Blocks:** TASK-002, TASK-003, TASK-004

### Evidence Output

`release_domain_manifest.json` and `docs/release-baseline.md` reconcile 14 claims, 17 available source receipts, and 10 explicitly missing receipts. The manifest SHA-256 is `697c92744e098fe409f481bcfa0ebeecfc61cd222291e36cd4158fbc5857b742`.

### Verification

- `python tools/validate_release_manifest.py` — passed; exact scope, claims, receipts, conventions, and blockers validated.
- `PYTHONPATH=src python -m unittest discover -s tests -v` — 110 tests passed.
- **Evidence ceiling:** This proves the release scope and evidence state were exhaustively declared against available records; it does not promote missing, comparator, framework-only, or retained evidence to production science.
- **Change reference:** commit `8aeaf5adb2667756b3623daa76f50720118fa5d2`; draft PR [#3](https://github.com/vbrodi23-lgtm/Kerr-QNM_Windows-Solver/pull/3).

### Review Focus

Look for legacy code being treated as a provider, unsupported evidence promotion, omitted release-domain coordinates, and private labels.

### Plan

- Inventory primary repository, merged-PR, retained-artifact, and supplied research-context evidence.
- Freeze the exact release domain and classify every claim without promoting external evidence to a provider.
- Admit a strict machine-readable manifest only after source receipts, ownership, conventions, and evidence ceilings validate.

---

## TASK-002: Bind source repositories, artifacts, licenses, and runtime receipts
**Priority:** P0 | **Tags:** M01, evidence, validation
**Assignee:** Codex | **Estimate:** 1–2 days | **Milestone:** M01

### Objective

Turn every manifest source into a reproducible receipt so later tasks consume immutable inputs rather than remembered locations.

### Acceptance Criteria

- [x] Record repository URL, commit/blob identity, artifact hash, license, runtime, and retrieval method for every required source.
- [x] Verify all available bytes against their recorded hashes and reject mutable or ambiguous aliases.
- [x] Identify unavailable inputs with an owner and explicit unblock action.
- [x] Store receipts in a machine-readable format covered by repository tests.

### Dependencies

- **Blocked by:** TASK-001
- **Blocks:** TASK-003, TASK-004

### Evidence Output

The manifest carries immutable local and external receipts, including exact comparator blob identities and SHA-256 values, plus an owner/action ledger for every unavailable source.

### Verification

- `python tools/validate_release_manifest.py` — passed with 17 authenticated available receipts and 10 fail-closed missing receipts.
- `PYTHONPATH=src python -m unittest tests.test_release_manifest -v` — strict receipt, hash, duplicate-key, non-finite, recursion, and size-limit cases passed.
- **Evidence ceiling:** Available bytes and recorded identities are authenticated; unavailable inputs remain blockers, and GPL comparator data remains outside production dependency closure.
- **Change reference:** commit `8aeaf5adb2667756b3623daa76f50720118fa5d2`; draft PR [#3](https://github.com/vbrodi23-lgtm/Kerr-QNM_Windows-Solver/pull/3).

### Review Focus

Check license compatibility, mutable URLs, local-only artifacts, and runtime gaps.

### Plan

- Normalize source identities and licenses.
- Implement or extend receipt validation.
- Test clean and tampered cases.

---

## TASK-003: Classify every existing module by public scientific responsibility
**Priority:** P0 | **Tags:** M01, architecture, evidence
**Assignee:** Codex | **Estimate:** 1–2 days | **Milestone:** M01

### Objective

Map each existing implementation to exactly one role: active provider, validator, comparator, extension, retired fixture, or out of release scope.

### Acceptance Criteria

- [x] Cover every scientific module and executable entry point named by TASK-001.
- [x] Assign at most one active production owner to each capability and record public input/output contracts.
- [x] Identify duplicate or conflicting implementations and state the replacement test required before any ownership change.
- [x] Prohibit retired/comparator code from production dependency closure.

### Dependencies

- **Blocked by:** TASK-001, TASK-002
- **Blocks:** TASK-004, TASK-005

### Evidence Output

The manifest ownership matrix covers every `src/windows_solver/*.py` module, every `tools/*.py` entry point, and `solver.ps1`, with only the problem-contract and spectral-core capabilities admitted.

### Verification

- `python tools/validate_release_manifest.py` — module inventory, unique ownership, registry consistency, and comparator quarantine passed.
- `PYTHONPATH=src python -m unittest tests.test_release_manifest.ReleaseManifestTests.test_module_ownership_covers_public_code_and_tools -v` — passed.
- **Evidence ceiling:** The matrix establishes implementation responsibility and quarantine boundaries; it does not independently validate the scientific correctness of a classified module.
- **Change reference:** commit `8aeaf5adb2667756b3623daa76f50720118fa5d2`; draft PR [#3](https://github.com/vbrodi23-lgtm/Kerr-QNM_Windows-Solver/pull/3).

### Review Focus

Look for scrapbook façade dependencies, hidden production comparators, and new physics misclassified as replacement code.

### Plan

- Inventory modules and dependency edges.
- Classify roles against public capabilities.
- Cross-check registry and quarantine conflicts.

---

## TASK-004: Freeze equations, conventions, normalizations, and evidence ceilings
**Priority:** P0 | **Tags:** M01, physics, evidence
**Assignee:** Codex | **Estimate:** 1–2 days | **Milestone:** M01

### Objective

Define the scientific identity required for cache keys and prevent later tasks from silently changing boundary conditions, gauge, tetrad, units, or normalization.

### Acceptance Criteria

- [x] Record equation IDs, boundary conditions, Fourier/sign conventions, tetrad, gauge, units, field and amplitude normalizations for every release capability.
- [x] Define numerical acceptance gates and maximum scientific claim for each artifact class.
- [x] Record corrected or disputed conventions as explicit invalidation/replacement decisions.
- [x] Bind the manifest fields into canonical identity tests.

### Dependencies

- **Blocked by:** TASK-001, TASK-002, TASK-003
- **Blocks:** TASK-005, TASK-006, TASK-012

### Evidence Output

The canonical convention register and evidence-ceiling matrix are hash-bound within the release manifest, with unresolved ORG/Hertz and cubic-EFT questions preserved as explicit blockers.

### Verification

- `python tools/validate_release_manifest.py` — equation, convention, normalization, evidence-ceiling, and blocker identities passed.
- `PYTHONPATH=src python -m unittest tests.test_release_manifest -v` — canonical identity and prohibited evidence-promotion cases passed.
- **Evidence ceiling:** The declared conventions and ceilings are frozen for identity and gating; unresolved formulations are not asserted as validated or production-ready.
- **Change reference:** commit `8aeaf5adb2667756b3623daa76f50720118fa5d2`; draft PR [#3](https://github.com/vbrodi23-lgtm/Kerr-QNM_Windows-Solver/pull/3).

### Review Focus

Check especially Ψ₄ signs, QNM time convention, ORG/Hertz normalization, forced-frequency labels, and detector units.

### Plan

- Extract conventions from code and receipts.
- Resolve or record conflicts without guessing.
- Add identity and evidence-ceiling validation.

---

## TASK-005: Admit the machine-readable release-domain manifest
**Priority:** P0 | **Tags:** M01, architecture, validation
**Assignee:** Codex | **Estimate:** 1–2 days | **Milestone:** M01

### Objective

Make the frozen completion scope executable so unsupported, missing, or overclaimed work is detected before scientific computation.

### Acceptance Criteria

- [x] Add a versioned manifest schema and strict parser to the public repository.
- [x] Validate capability coverage, coordinate completeness, source receipts, conventions, licenses, evidence ceilings, and milestone mapping.
- [x] Provide one canonical manifest fixture and negative fixtures for missing/duplicate/incompatible entries.
- [x] Close M01 only after human and automated reconciliation agree.

### Dependencies

- **Blocked by:** TASK-003, TASK-004
- **Blocks:** TASK-006, TASK-012

### Evidence Output

The repository contains the canonical manifest, immutable strict parser, CLI validator, negative tests, packaged-data binding, and human-readable M01 closure report.

### Verification

- `git diff --check` — passed.
- `python tools/validate_release_manifest.py` — passed.
- `PYTHONPATH=src python -m unittest discover -s tests -v` — 110 tests passed.
- Cross-platform manifest checkout regression — passed; Git enforces LF bytes before package build on Windows and Ubuntu.
- Clean wheel build/import — passed; wheel SHA-256 `cbfd6887ed07f186a6966a3093da2bb0e580a8402b53868855be6125240dea18`.
- Change Review — no blocking findings after remediation.
- **Evidence ceiling:** M01 validates scope-control machinery and packaging only; it changes no spectral bytes, scientific provider behavior, or evidence state beyond the two previously admitted capabilities.
- **Change reference:** commit `8aeaf5adb2667756b3623daa76f50720118fa5d2`; draft PR [#3](https://github.com/vbrodi23-lgtm/Kerr-QNM_Windows-Solver/pull/3).

### Review Focus

Ensure the manifest freezes required scope without promising science outside available evidence.

### Plan

- Define schema from TASK-001–004 outputs.
- Implement strict validation and fixtures.
- Run change review and update M01 only on full closure.

---

## TASK-006: Define the public linear-response artifact and provider contract
**Priority:** P1 | **Tags:** M02, provider, physics
**Assignee:** Codex | **Estimate:** 1–2 days | **Milestone:** M02

### Objective

Specify one field-native artifact for physical first-order complex QNM shifts, local covariance/disks, mechanism identity, and bounded multimode comparisons.

### Acceptance Criteria

- [x] Define payload keys, units, modes/spins, mechanism parameters, complex covariance, local uncertainty disks, and unresolved classifications.
- [x] Separate raw roots, pole shifts, projective reductions, and later response-matrix quantities.
- [x] Bind equations, conventions, numerical policy, runtime, upstream hashes, and evidence ceiling.
- [x] Reject unsupported mechanisms or coordinates before partial output.

### Dependencies

- **Blocked by:** TASK-005
- **Blocks:** TASK-007, TASK-008

### Evidence Output

`src/windows_solver/linear_response.py` defines the unavailable descriptor and strict request/payload/admission contracts. `src/windows_solver/payload_validation.py` dispatches candidate artifact validation. The example, design, implementation plan, and 19 focused tests bind direct-spin and `Mκ` sampling, all eight mechanisms, component-local and correlated covariance, uncertainty disks, projective reductions, completeness, lineage, and fail-closed semantics.

### Verification

- `PYTHONPATH=src python -m unittest tests.test_linear_response_contract -v` — 19 tests passed.
- `PYTHONPATH=src python -m unittest discover -s tests -v` — 129 tests passed.
- `python .tasks/validate_board.py` — passed before completion transition.
- `python tools/validate_release_manifest.py` — passed unchanged; manifest SHA-256 `697c92744e098fe409f481bcfa0ebeecfc61cd222291e36cd4158fbc5857b742`.
- Wolfram identities — simple-root tangent, `Mκ` to `a/M`, and `δB` to reflectivity inverse residuals all reduced to zero.
- Independent Change Review — no blocking findings after remediation of the covariance PSD and frozen-coordinate checks.
- **Evidence ceiling:** Contract-only. No response leaf was computed, the descriptor remains unavailable and unregistered, and M02 remains open. Full closure is blocked by absent high-spin/`Mκ` spectral roots, unauthenticated candidate pilots, and the missing frozen-domain covariance/recomputation bundle.
- **Change reference:** implementation commit `a12ef02f57038ac8a8c912381f1fe64c76237860`; draft PR [#4](https://github.com/vbrodi23-lgtm/Kerr-QNM_Windows-Solver/pull/4).

### Review Focus

Check field-native terminology, physical mechanism distinctions, exact frozen-coordinate coverage, and no atlas-wide uncertainty substitute.

### Plan

- Translate frozen manifest into an exact contract.
- Add red contract and identity tests.
- Review evidence boundary before migration.

---
