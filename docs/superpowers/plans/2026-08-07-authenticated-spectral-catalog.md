# Pure-Kerr 2,736-Root Lattice Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development to implement this plan task-by-task.
> Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver PR #2 as one computed, validated, immutable 2,736-root
pure-Kerr QNM spectral provider: 690 for ℓ=2, 966 for ℓ=3, and 1,080 for ℓ=4.
PR #3 is the separate `linear-response` migration.

**Architecture:** An offline adapter uses qnm only to continue the 63
Schwarzschild-labelled branches, then feeds every exact-node seed to the
existing canonical Leaver determinant and angular machinery for the stored
root. It validates the complete ℓ-dependent lattice and compares exact
overlaps with Motohashi v0.2.0. The dependency-free installed provider
hash-validates and selects the packaged CSV; it never performs interpolation
or claims formal enclosure.

**Tech Stack:** CPython 3.12, the existing Leaver continued-fraction backend,
qnm 0.4.4, NumPy, SciPy, Numba, standard-library CSV/JSON/hash validation,
`unittest`, PowerShell 5.1, GitHub Actions.

## Global Constraints

- Modes are exactly ℓ ∈ {2,3,4}, m = −ℓ,…,+ℓ, n ∈ {0,1,2}; 63 modes.
- ℓ=2,3 use χ = 19i/780 for i=0,…,39 plus
  {97/100,49/50,99/100,199/200,997/1000,999/1000}; 46 unique values.
- ℓ=4 uses χ = i/52 for i=0,…,39; 40 values.
- Counts are exactly 690 + 966 + 1,080 = 2,736.
- One s=−2 pure-Kerr root per (ℓ,m,n,χ); no polarization or EFT row axis.
- Frequencies use Mω and Im(Mω) < 0 under the outgoing convention.
- No requested row may come from interpolation, extrapolation, or Motohashi
  table substitution.
- Catalog key identity uses reduced rational χ; binary64 χ is only the solver
  evaluation.
- Full-grid ceilings: radial residual ≤ 1×10⁻⁸, continued-fraction error
  ≤ 1×10⁻⁹, angular refinement |ΔA| ≤ 1×10⁻⁹, repeat-polish |Δω| ≤ 1×10⁻⁹.
- Exact-overlap Motohashi ceilings: |Δ(Mω)| ≤ 5×10⁻⁹ and |ΔA| ≤ 1×10⁻⁸.
- `formal_root_enclosure = false`; scientific state remains
  `NOT_EVALUATED`.
- The installed package retains no runtime dependency outside the standard
  library.
- Current public code and status documents contain no stale 91/819/728,
  2,520, or 5,508 scope claim.

---

### Task 1: Lock the exact lattice contract

**Files:**
- Modify: `tests/test_catalog_builder.py`
- Modify: `tests/test_spectrum.py`
- Modify: `tests/test_public_surface.py`
- Modify: `tests/fixtures.py`
- Test: `tests/test_catalog_builder.py`
- Test: `tests/test_spectrum.py`

**Interfaces:**
- Consumes: approved exact lattice in the design specification.
- Produces: executable expected key set and catalog/payload acceptance contract.

- [ ] **Step 1: Add the exact rational-key helper and failing count tests**

Define expected keys with `fractions.Fraction`:

```python
def expected_lattice_keys():
    high = {
        Fraction(97, 100), Fraction(49, 50), Fraction(99, 100),
        Fraction(199, 200), Fraction(997, 1000), Fraction(999, 1000),
    }
    keys = set()
    for ell in (2, 3, 4):
        spins = (
            {Fraction(19 * i, 780) for i in range(40)} | high
            if ell in (2, 3)
            else {Fraction(i, 52) for i in range(40)}
        )
        for m in range(-ell, ell + 1):
            for n in range(3):
                for spin in spins:
                    keys.add((ell, m, n, spin.numerator, spin.denominator))
    return keys
```

Assert 2,736 keys, per-ℓ counts 690/966/1080, 46/46/40 spin counts,
one 0.95 per ℓ=2,3 mode, and no high-spin extras for ℓ=4.

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```text
PYTHONPATH=src python -m unittest tests.test_catalog_builder tests.test_spectrum -v
```

Expected: failures identify the superseded resource and payload contract.

- [ ] **Step 3: Add failing tamper and evidence tests**

Assert that missing, duplicate, extra, cross-ℓ, unreduced-rational,
non-finite, non-damped, over-threshold diagnostic, stale receipt, and wrong
ordering rows all fail. Assert row keys and scope counts have no
`polarization` or EFT `sector` dimension.

- [ ] **Step 4: Add failing public-status tests**

Require 2,736, 690, 966, and 1,080 in current status documents and prohibit
semantic legacy counts. Retain the fixed generic gravitational ModeKey only as
request metadata.

- [ ] **Step 5: Commit the red contract**

Commit only tests/spec/plan with message:

```text
test: lock exact 2736-root Kerr lattice contract
```

### Task 2: Compute and authenticate the lattice

**Files:**
- Create: `tools/compute_kerr_qnm_lattice.py`
- Create: `tools/kerr_cf_solver.py`
- Create: `tools/kerr_angular.py`
- Create: `src/windows_solver/data/kerr_qnm_roots_2736.csv`
- Create: `src/windows_solver/data/kerr_qnm_lattice_receipt.json`
- Create: `src/windows_solver/data/LICENSE-QNM-MIT.txt`
- Modify: `src/windows_solver/data/LICENSE-CC-BY-4.0.txt`
- Delete: `tools/build_kerr_qnm_catalog.py`
- Delete: `src/windows_solver/data/kerr_qnm_roots_91.csv`
- Delete: `src/windows_solver/data/kerr_qnm_catalog_receipt.json`
- Delete: `src/windows_solver/data/kerr_qnm_independent_benchmarks.csv`
- Delete: `src/windows_solver/data/kerr_qnm_benchmark_receipt.json`
- Test: `tests/test_catalog_builder.py`

**Interfaces:**
- Consumes: the pinned canonical continued-fraction/angular source snapshot,
  qnm 0.4.4 branch tracker, and authenticated Motohashi archive path.
- Produces:
  `compute_lattice(archive_bytes) -> tuple[catalog_bytes, receipt_bytes]`.

- [ ] **Step 1: Implement exact lattice enumeration**

Represent every χ as a reduced `Fraction`; evaluate it once as binary64 for
the canonical solver and record `float.hex(χ)`. Enumerate deterministically by
(ℓ,m,n,χ).

- [ ] **Step 2: Implement continuation and exact-node polishing**

Use qnm to originate each n = 0,1,2 Schwarzschild overtone and continue it
with non-output nodes so no step exceeds 0.004. At every requested χ, use that
branch-labelled root only as the seed for the canonical determinant solver.
Record the stored canonical ω and A, determinant residual, continued-fraction
error and depth, angular truncation, branch-seed distance, continuation
diagnostics, and repeat-polish delta.

- [ ] **Step 3: Enforce full-grid gates before serialization**

Abort on any missing key, solver failure, non-finite field, Im(Mω) ≥ 0,
diagnostic over a Global Constraint ceiling, wrong count, duplicate key, or
noncanonical order. No partial CSV may be written.

- [ ] **Step 4: Compare every exact Motohashi overlap**

Verify archive size 60,243,941 bytes and SHA-256
`9a096cdcf873039baaac66fe0194f64c430df17125713a16d8f546129ef238fa`.
Read all 63 relevant source members. Convert source 2Mω to Mω exactly.
Compare only exact χ matches and record coverage plus observed maxima; never
use source values to fill catalog rows.

- [ ] **Step 5: Generate the immutable CSV and canonical receipt**

The receipt records the canonical determinant/angular source commit and blob
hashes, qnm wheel hash/version, generator hash, lattice fractions, policies
and ceilings, catalog hash, full-grid observed maxima, comparison
coverage/maxima, environment, licenses, and citations.

- [ ] **Step 6: Run builder tests and verify GREEN**

Run:

```text
PYTHONPATH=src python -m unittest tests.test_catalog_builder -v
```

Expected: all exact-lattice, failure-path, source-integrity, and deterministic
rebuild tests pass.

- [ ] **Step 7: Commit computation assets**

Commit with message:

```text
feat: compute complete 2736-root Kerr lattice
```

### Task 3: Admit the 2,736-row spectral provider

**Files:**
- Modify: `src/windows_solver/spectrum.py`
- Modify: `src/windows_solver/payload_validation.py`
- Modify: `src/windows_solver/data/LICENSE.txt`
- Modify: `pyproject.toml`
- Test: `tests/test_spectrum.py`
- Test: `tests/test_engine.py`

**Interfaces:**
- Consumes: immutable CSV and receipt from Task 2.
- Produces:
  `load_spectrum_catalog() -> SpectrumCatalog`,
  `build_spectral_payload(request) -> dict[str, object]`, and one active
  `SpectralCatalogProvider`.

- [ ] **Step 1: Replace catalog constants and schemas**

Use the 2,736 resource/receipt hashes and provider identity
`kerr-qnm-computed-lattice-2736`. Remove Motohashi-table-selector semantics,
old 91/819 scope structures, and the 11-row benchmark contract.

- [ ] **Step 2: Implement fail-closed catalog loading**

Validate canonical CSV/JSON bytes, exact columns, reduced rational keys,
binary64 χ hex, full key-set equality, deterministic order, source receipt,
diagnostic ceilings, row count, and finite damped roots.

- [ ] **Step 3: Implement exact selection**

Map request binary64 χ values only to admitted rational-key rows whose
recorded solver value has the same binary64 identity. Reject any unsupported
pair or duplicate without partial output.

- [ ] **Step 4: Update payload and evidence semantics**

Expose computed full-grid scope, method, exact lattice definition,
full-grid diagnostics, independent comparison scope, and provenance.
Report numerical `ACCEPTED`, scientific `NOT_EVALUATED`, and
`formal_root_enclosure = false`.

- [ ] **Step 5: Prove cache/store tamper resistance**

Run:

```text
PYTHONPATH=src python -m unittest tests.test_spectrum tests.test_engine -v
```

Expected: fresh run, warm reuse, verification, forged payload, cache
substitution, unsupported pair, and exact selection tests all pass.

- [ ] **Step 6: Commit provider admission**

Commit with message:

```text
feat: admit computed Kerr spectral lattice
```

### Task 4: Update the public command surface and status

**Files:**
- Modify: `examples/spectrum.json`
- Modify: `README.md`
- Modify: `NOTICE.md`
- Modify: `docs/architecture.md`
- Modify: `docs/superpowers/plans/2026-08-06-public-capability-dag.md`
- Modify: `docs/superpowers/specs/2026-08-06-public-solver-design.md`
- Modify: `.github/workflows/ci.yml`
- Modify: `tests/test_cli.py`
- Modify: `tests/test_public_surface.py`

**Interfaces:**
- Consumes: admitted provider from Task 3.
- Produces: current public status, installed CLI example, and cross-platform
  release checks.

- [ ] **Step 1: Replace all legacy scope wording**

State exactly: PR #2 computes and admits 2,736 pure-Kerr roots at the approved
ℓ-dependent grids; problem-contract and spectral-core are admitted; downstream
providers fail closed; PR #3 is linear response.

- [ ] **Step 2: Update the supported example and CLI assertions**

Use exact supported mode–χ pairs, verify emitted roots and provenance, and
keep unsupported downstream behavior unchanged.

- [ ] **Step 3: Extend Ubuntu/Windows installed-package checks**

Require the wheel to contain the 2,736 CSV, receipt, qnm MIT notice, and
Motohashi attribution;
execute the spectrum example through both Python and PowerShell entry points.

- [ ] **Step 4: Run public-surface and CLI tests**

Run:

```text
PYTHONPATH=src python -m unittest tests.test_cli tests.test_public_surface -v
```

Expected: all tests pass with zero stale-scope matches.

- [ ] **Step 5: Commit integration and status**

Commit with message:

```text
docs: publish complete Kerr spectral scope
```

### Task 5: Verify, review, and publish PR #2

**Files:**
- Verify all files changed since remote `main`.
- Do not merge PR #2.

**Interfaces:**
- Consumes: Tasks 1–4.
- Produces: reviewed draft PR #2 with green Ubuntu and Windows checks.

- [ ] **Step 1: Run full local verification**

Run:

```text
PYTHONPATH=src python -m compileall -q src tests tools
PYTHONPATH=src python -m unittest discover -s tests -v
git diff --check
```

- [ ] **Step 2: Rebuild and compare data deterministically**

Run the pinned generator twice in isolated temporary directories and require
byte-identical CSV and receipt outputs with 2,736 rows.

- [ ] **Step 3: Build and inspect the wheel**

Build offline from the checked-out tree, inspect resource and license members,
install into a clean environment, execute the spectrum example twice, and
verify the warm run executes zero providers.

- [ ] **Step 4: Obtain independent whole-diff scientific and code review**

Review exact key coverage, branch continuation, residual gates, independent
comparison scope, evidence language, payload validation, cache integrity,
Windows portability, licensing, and stale-scope removal. Fix all confirmed
release blockers test-first and re-review.

- [ ] **Step 5: Publish draft PR #2**

Create the remote feature branch from current remote `main`, transfer the
reviewed tree without importing private development history, open draft PR #2,
and state the exact 2,736-row boundary and PR #3 linear-response boundary.

- [ ] **Step 6: Verify GitHub Actions**

Require Ubuntu and Windows PowerShell 5.1 jobs green. Leave PR #2 draft and
unmerged.
