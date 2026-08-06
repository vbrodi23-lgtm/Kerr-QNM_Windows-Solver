# Public Capability DAG Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the tested public control plane for The Windows Solver without importing private development architecture or claiming unavailable scientific calculations.

**Architecture:** A standard-library Python 3.12 package models immutable scientific contracts, plans a fixed capability DAG, resolves one provider per capability, and writes content-addressed artifacts plus run records. A thin CLI and PowerShell launcher expose the same engine; scientific providers fail closed until migrated.

**Tech Stack:** CPython 3.12 standard library, `unittest`, PowerShell 5.1+, GitHub Actions.

## Global Constraints

- Public source and output contain no historical version, sequence, or upgrade labels.
- Mathematical notation in documentation uses Unicode, not LaTeX.
- Mechanism, equation, convention, provider, runtime, numerical-policy, and upstream hashes contribute to artifact identity.
- Execution, numerical evidence, and scientific conclusion remain independent states.
- Exactly one active provider may own a capability.
- Unavailable science fails closed; no synthetic numerical result is permitted.
- All commands emit deterministic JSON and use nonzero exit status for invalid input, unavailable providers, or failed verification.

---

### Task 1: Strict scientific contracts

**Files:**
- Create: `pyproject.toml`
- Create: `src/windows_solver/__init__.py`
- Create: `src/windows_solver/contracts.py`
- Create: `tests/test_contracts.py`

**Interfaces:**
- Produces: `Capability`, `ModeKey`, `StudyRequest`, `EvidenceState`, `canonical_json_bytes()`, and `load_study()`.
- Consumes: JSON-compatible values only.

- [ ] **Step 1: Write failing contract tests**

Add literal fixtures proving valid mode parsing, rejection of `|m| > ell`, rejection of unknown request fields, rejection of spins outside `−1 < a_over_m < 1`, deterministic canonical JSON, and distinct convention identities.

- [ ] **Step 2: Run the tests and observe the missing-module failure**

Run: `python -m unittest tests.test_contracts -v`

Expected: import failure for `windows_solver.contracts`.

- [ ] **Step 3: Implement the minimum typed contracts**

Use frozen dataclasses and string enums. `StudyRequest.from_mapping()` must consume every allowed field and reject extras. Canonical JSON uses sorted keys, compact separators, UTF-8, and rejects NaN/Infinity through `allow_nan=False`.

- [ ] **Step 4: Run focused tests**

Run: `python -m unittest tests.test_contracts -v`

Expected: all contract tests pass.

- [ ] **Step 5: Commit**

Commit message: `Add strict public scientific contracts`

### Task 2: Capability planner and provider registry

**Files:**
- Create: `src/windows_solver/planner.py`
- Create: `src/windows_solver/providers.py`
- Create: `tests/test_planner.py`
- Create: `tests/test_providers.py`

**Interfaces:**
- Consumes: `Capability` and provider objects implementing `descriptor` plus `execute(request, upstream)`.
- Produces: `ExecutionPlan`, `ProviderDescriptor`, `ProviderRegistry`, `ProviderUnavailableError`, and `DuplicateProviderError`.

- [ ] **Step 1: Write failing planner and registry tests**

Assert the literal dependency order for `evidence-package`; assert that `quadratic-ringdown` plans only problem contract, spectral core, and quadratic ringdown; assert duplicate active providers are rejected; assert missing providers identify the first unavailable capability.

- [ ] **Step 2: Run and observe missing-module failures**

Run: `python -m unittest tests.test_planner tests.test_providers -v`

- [ ] **Step 3: Implement the fixed DAG and registry**

Use an explicit dependency mapping. Validate acyclicity on module import with a deterministic depth-first traversal. Build plans by dependency closure followed by stable topological sorting in declared capability order.

- [ ] **Step 4: Run focused tests**

Run: `python -m unittest tests.test_planner tests.test_providers -v`

- [ ] **Step 5: Commit**

Commit message: `Add capability planning and provider ownership`

### Task 3: Content-addressed execution and evidence

**Files:**
- Create: `src/windows_solver/artifacts.py`
- Create: `src/windows_solver/engine.py`
- Create: `src/windows_solver/builtin.py`
- Create: `tests/test_artifacts.py`
- Create: `tests/test_engine.py`

**Interfaces:**
- Consumes: `StudyRequest`, `ExecutionPlan`, and `ProviderRegistry`.
- Produces: `ArtifactEnvelope`, `ArtifactStore`, `RunRecord`, `ExecutionEngine`, and a built-in problem-contract provider.

- [ ] **Step 1: Write failing artifact and engine tests**

Assert hand-derived SHA-256 behavior from canonical bytes, tamper detection, successful problem-contract execution, zero provider executions on a warm repeat, fail-closed unavailable spectral execution, and independent execution/numerical/scientific states.

- [ ] **Step 2: Run and observe missing-module failures**

Run: `python -m unittest tests.test_artifacts tests.test_engine -v`

- [ ] **Step 3: Implement atomic storage and execution**

Write artifacts to `<store>/artifacts/<sha256>.json` using a sibling temporary file and `os.replace`. Write runs under `<store>/runs/<run_id>.json`. Cache lookup verifies the stored envelope hash before reuse. The engine records provider execution and cache-hit counts.

- [ ] **Step 4: Run focused tests**

Run: `python -m unittest tests.test_artifacts tests.test_engine -v`

- [ ] **Step 5: Commit**

Commit message: `Add content-addressed execution and evidence`

### Task 4: Public CLI and Windows entry point

**Files:**
- Create: `src/windows_solver/cli.py`
- Create: `src/windows_solver/__main__.py`
- Create: `solver.ps1`
- Create: `examples/problem-contract.json`
- Create: `examples/evidence-plan.json`
- Create: `tests/test_cli.py`

**Interfaces:**
- Consumes: study JSON files and artifact-store paths.
- Produces: `plan`, `run`, `verify`, `inspect`, and `export` JSON commands with stable exit codes.

- [ ] **Step 1: Write failing end-to-end CLI tests**

Invoke `cli.main()` against temporary directories and assert literal JSON structures and exit codes for planning, cached execution, unavailable science, verification, inspection, and export.

- [ ] **Step 2: Run and observe missing-module failures**

Run: `python -m unittest tests.test_cli -v`

- [ ] **Step 3: Implement the command surface**

Use `argparse`; route every command through the same contracts, planner, and engine. Print one JSON value to stdout. Print one structured JSON error to stderr and return `2` for input errors, `3` for unavailable providers, and `4` for verification failures.

- [ ] **Step 4: Run focused tests**

Run: `python -m unittest tests.test_cli -v`

- [ ] **Step 5: Commit**

Commit message: `Add public CLI and native Windows launcher`

### Task 5: Public documentation and continuous verification

**Files:**
- Modify: `README.md`
- Create: `docs/architecture.md`
- Create: `.gitignore`
- Create: `.github/workflows/ci.yml`

**Interfaces:**
- Consumes: the implemented command surface.
- Produces: concise installation, planning, execution, evidence, and provider-migration documentation plus automated verification.

- [ ] **Step 1: Run examples before documenting them**

Run: `PYTHONPATH=src python -m windows_solver plan examples/evidence-plan.json`

Run: `PYTHONPATH=src python -m windows_solver run examples/problem-contract.json --store .tmp-store`

Record the observed JSON shapes; documentation must match them.

- [ ] **Step 2: Write public documentation and CI**

Document capability-first usage, evidence semantics, provider admission, and the no-fake-science boundary. CI runs `python -m compileall -q src tests` and `PYTHONPATH=src python -m unittest discover -s tests -v` on Windows and Ubuntu with Python 3.12.

- [ ] **Step 3: Run repository-wide verification**

Run: `python -m compileall -q src tests`

Run: `PYTHONPATH=src python -m unittest discover -s tests -v`

Run: `PYTHONPATH=src python -m windows_solver plan examples/evidence-plan.json`

Run: `PYTHONPATH=src python -m windows_solver run examples/problem-contract.json --store .tmp-store`

Expected: compile succeeds; all tests pass; plan is deterministic; the run succeeds.

- [ ] **Step 4: Scan the public tree for forbidden historical labels**

Run a case-insensitive repository search excluding `.git` and this implementation-plan directory. Expected: zero matches for private version, sequence, and upgrade labels.

- [ ] **Step 5: Commit**

Commit message: `Document and verify the public solver foundation`

### Task 6: Review-driven integrity hardening

**Files:**
- Modify: `src/windows_solver/contracts.py`
- Modify: `src/windows_solver/planner.py`
- Modify: `src/windows_solver/providers.py`
- Modify: `src/windows_solver/artifacts.py`
- Modify: `src/windows_solver/engine.py`
- Modify: `src/windows_solver/cli.py`
- Modify: `.github/workflows/ci.yml`
- Modify: `tests/`

- [x] **Step 1: Reproduce independent review findings with failing tests**

Cover cache substitution, modified and truncated run records, evidence
overstatement, provider exceptions, upstream artifact-type mismatch, traversal,
unsafe export, inert publication verification, and declaration-order planning.

- [x] **Step 2: Bind storage and execution identities**

Recompute cache keys from loaded artifacts, seal strict run records, enforce
identifier containment, and reject exports into their source store.

- [x] **Step 3: Enforce scientific and provider boundaries**

Apply the weakest-upstream evidence ceiling, require ordered provider input
types, topologically sort plans, and persist structured provider failures.

- [x] **Step 4: Make verification profiles substantive**

Reconstruct and validate the complete run closure. Require a complete,
evaluated evidence package for publication while preserving unresolved and
contradicted outcomes as valid evidence.

- [x] **Step 5: Exercise installed and Windows entry points in CI**

Install the package, call the console script, compare PowerShell/module plan
JSON, and assert matching invalid-input and unavailable-provider exit behavior.
