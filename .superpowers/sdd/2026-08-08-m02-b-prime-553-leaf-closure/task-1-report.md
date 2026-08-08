# TASK-069 — Freeze the B′ 553-leaf M02 release domain

## Status

DONE

## Files changed

- `src/windows_solver/linear_response.py` — typed B′ production leaves, root-selector and missing-overlay ledgers, projective rows, precision gates/sentinels, and exact admission boundary.
- `src/windows_solver/data/release_domain_manifest.json` and `src/windows_solver/release_manifest.py` — B′ role/count/support/precision receipt contract and package hash binding.
- `tests/test_linear_response_contract.py`, `tests/test_spectral_extension.py`, `tests/test_catalog_builder.py`, `tests/test_spectrum.py`, and `tests/fixtures.py` — literal B′ contract coverage; removed obsolete 3,303-root Cartesian targets.
- `docs/evidence/m02-b-prime-wolfram-arithmetic-receipt.json` — durable exact-arithmetic receipt.
- `docs/keystone/tasks/2026-08-08-m02-b-prime-553-leaf-closure.md` and `docs/superpowers/plans/2026-08-08-m02-high-spin-spectral-extension.md` — controlling plan and explicit supersession record.
- `.tasks/` — TASK-069 completion, TASK-070 as the sole Next task, and work log.

## Red/green evidence

1. Red: `PYTHONPATH=src python -m unittest tests.test_spectral_extension.FrozenM02BPrimeDomainTests -v` failed with `ImportError` because `B_PRIME_RELEASE_DOMAIN` was absent. Green: the same focused test passed after the typed release-domain implementation.
2. Red: `PYTHONPATH=src python -m unittest tests.test_linear_response_contract.LinearResponseContractTests.test_b_prime_precision_and_completeness_contract_is_frozen_before_production -v` failed because a one-leaf candidate was admissible. Green: the same test passed after admission was restricted to the exact 553 B′ role-scoped leaf set.
3. Red baseline reconciliation: the full suite exposed two rejected Cartesian contracts (missing `tools.extend_kerr_qnm_lattice` and a 3,303-root catalog requirement). They were replaced by the literal 44-selector sparse-overlay and immutable-2,736-base tests; the fresh full suite is green.

## Full verification

- `PYTHONPATH=src python -m unittest tests.test_linear_response_contract tests.test_spectral_extension -v` — 22 passed.
- `PYTHONPATH=src python -m unittest discover -s tests -v` — 134 passed.
- `python .tasks/validate_board.py` — valid: 74 unique tasks, 12 milestones, 7 Done, 1 Next, 0 In Progress, acyclic dependencies.
- `python tools/validate_release_manifest.py` — valid with bound manifest SHA-256 `bab9700f7684b2b39e8641a0356b81b2806ee68eb22dc486778e5f3a8a0bbb80`.
- `python -m compileall -q src tools tests` — passed.
- `git diff --check` — passed; diff against `src/windows_solver/data/kerr_qnm_roots_2736.csv` and its authenticated receipt was empty before commit.

## Commit SHA(s)

- `a3c40ddc7481a094bb3e8fc7d0db7ad4850b3615` — `feat: freeze M02 B-prime release domain`

## Self-review findings

- Axis leakage: no ambient ℓ/m/n or spin Cartesian completion remains executable; each B′ role owns its declared modes, coordinates, and mechanisms.
- Cubic promotion: no `cubic-eft` leaf is in the 553 production set; all eight retained rows are comparator-only.
- Missing versus unresolved: the exact admission set requires 553 produced and zero missing leaves, while evidence-bearing `UNRESOLVED` components remain admissible.
- Obsolete targets: removed 3,303-root provider/builder test contracts; the superseded plan is explicitly marked non-executable.
- Immutable spectrum: no base catalog or authenticated receipt bytes were changed.

## Risks / gaps

- This is a contract-only closure. TASK-070 still must authenticate and bind the sparse 44-root overlay; no numerical roots or response leaves were generated.
- A full 553-component candidate artifact has intentionally not been produced because the provider remains unavailable.

## Review remediation — 2026-08-08

The review identified that the initial B′ admission comparison was unsatisfiable because it expanded the request axes as a global Cartesian product, and that the strict component schema could not carry deep precision evidence.

- Added explicit `role_scoped_leaves` request entries. Their exact `(role, mode, coordinate, mechanism)` identities must equal the frozen 553-leaf B′ set; payload/root-reference validation now consumes that role-scoped set rather than `modes × spins × mechanisms`.
- Added an exact 553-component all-`UNRESOLVED` candidate test. It is admitted without numerical production and rejects role leakage, omissions, and additions.
- Added strict deep `precision_evidence`: promotion trigger IDs, promoted flag, 80-digit run, conditional 120-digit repeat, self-refinement/discrepancy enclosure, and exact eight-sentinel identity. Forged evidence and false sentinels fail validation.
- Post-remediation verification: 23 focused tests and 135 full tests passed; board, manifest, compile, diff-check, and immutable-spectrum diff checks passed.
- Remediation commit: `e192b4646fe25393f2e8293de07977cd4e1cbc7f` — `fix: enforce role-scoped B-prime admission`.

## Round-3 review remediation — 2026-08-08

The rereview found that a declared sentinel could still mask a binary64-to-80-digit trigger-policy false negative, and that the addition test exercised a duplicate rather than an off-domain leaf.

- Added required, exact `sentinel_comparison` evidence for each of the eight fixed deep sentinels: finite nonnegative binary64-to-80 discrepancy, strictly positive trigger threshold, and declared false-negative outcome. The outcome is checked against the recorded comparison and trigger IDs; a true false negative fails payload validation and therefore admission. Non-sentinel deep leaves must carry `null` for this field.
- Added negative coverage for a false negative at admission, a forged false-negative outcome, promotion mismatch, wrong 80-digit precision, missing required 120-digit repeat, and an `ACCEPTED` result lacking an enclosed 80/120 discrepancy. The valid 553-leaf all-`UNRESOLVED` payload remains the positive sentinel-evidence case.
- Replaced the duplicate addition with a unique, structurally valid primary-to-control cross-role leaf outside B′. It reaches exact-set comparison and is rejected with `must exactly match` rather than duplicate detection.
- Red/green: before validator support, the new valid candidate failed with `unknown deep precision evidence fields: sentinel_comparison`; after the typed comparison and fail-closed rule, `PYTHONPATH=src python -m unittest tests.test_linear_response_contract tests.test_spectral_extension -v` passed 24 tests.
- Fresh verification: `PYTHONPATH=src python -m unittest discover -s tests -v` passed 136 tests; TaskPlanner board validation, release-manifest validation (SHA-256 `bab9700f7684b2b39e8641a0356b81b2806ee68eb22dc486778e5f3a8a0bbb80`), `python -m compileall -q src tools tests`, and `git diff --check` all passed. An explicit diff against the immutable 2,736-root CSV and authenticated receipt was empty.
- Self-review: comparison values reject booleans/nonfinite values through the existing numeric validator; threshold/discrepancy signs are checked; the false-negative flag cannot contradict observed high-precision evidence; no catalog, receipt, board, or manifest bytes changed.
- Remediation commit: `7c015f0788298d6f40967b48dcefb211e39554aa` — `fix: fail closed on B-prime sentinel discrepancies`.

## Independent review verdict

Approved after three scoped rounds. The final rereview reported no Critical, Important, or Minor findings; exact role-scoped admission, fail-closed sentinel comparisons, every precision-ladder transition, and unique off-domain addition rejection were all confirmed from the committed delta.
