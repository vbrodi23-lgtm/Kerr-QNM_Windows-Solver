# TASK-010 — Empirical uncertainty and projective-reduction pipeline

## Status

DONE, SOFTWARE-ONLY — the deterministic signed-channel reducer, empirical
error Gram validator, exact 174-row planner, partial-honest reducer, and
PowerShell-facing `campaign-reduce` command are implemented. No determinant,
cache generation/download, response campaign, or populated scientific atlas ran.
The complete 553-leaf evidence and all 174 scientific rows are absent, and the
linear-response provider remains unavailable.

## Delivered contract

- Typed resolved and computed-unresolved component evidence preserves ordered
  signed complex channels, frozen families, shared/local scope, units,
  stage/source receipts, applicable-family declarations, and discrepancies.
- The empirical error Gram uses ordered real/imaginary component quadratures,
  globally aligned signed columns, exact outer-product construction, exact 2×2
  marginals, conservative sum-of-norm local disks, symmetry/finite/PSD checks,
  and exact recomputation. Its kind is explicitly
  `empirical-error-gram/deterministic-not-statistical`.
- The row planner exactly reproduces the frozen release-domain order: 162
  primary and 12 deep rows, with no control or ambient row. It binds supports,
  exact rational coordinates, spins, mechanisms, component IDs, calibration
  pair, Gram kind, role ceiling, units, and the frozen 1e-2/1e-3 thresholds.
- Reduction computes the nominal Fubini–Study angle, signed channel/Jacobian
  diagnostic, and conservative disk interval only for complete aligned inputs.
  Missing evidence is `INCOMPLETE` with exact IDs and no classification;
  computed unresolved evidence and zero-containing calibration disks remain
  produced `UNRESOLVED` results.
- `campaign-reduce` performs zero backend work. It validates the canonical
  bundle digest, exact campaign/factory/backend lineage, byte hashes and existing
  TASK-009 semantics of every checkpoint, authenticated signed-channel receipts,
  safe relative paths, and no-overwrite atomic publication.

## Deterministic identities

- Ordered 174-row plan SHA-256:
  `54c61147d0850b1472b8390d6fc30c336c7514e78c05bb63731fb96a51ac0aa9`.
- Reducer source SHA-256:
  `7c9f752fdc241de03347c43f6f0c225be46c8c547687c27df550eeea6cdb6edc`.
- Two-component Gram fixture ID:
  `empirical-error-gram-d72035948886b3bc8b6ba277c39448a1cb5572d0f02336c047d7ce304ed5bba3`.
- That fixture's matrix SHA-256:
  `029f81134b29ce6957e494610d33b58c141b0df0abb14619c790fbb23204be3d`.
- Head Gram ID:
  `empirical-error-gram-69535cdf521fa64e640e16d986ae8204e743eb5a882b0f23feaa858eda8a6f70`.
- Middle Gram ID:
  `empirical-error-gram-165e860de12c943f4c84b96ca08a90ac4898d46364f5f09ce5ed9c7d5ba83017`.

## Exactly six predeclared reductions

1. `primary-K0-19-20-exterior-fixed-r3`, synthetic shared continuation:
   `COMPLETE / SEPARATED / CONTRADICTED`; nominal angle
   `0.7853981633974484`, conservative interval
   `[0.7853970513449327, 0.7853992754499641]`. Ordered components:
   `9e577772…aa3c3`, `6d1c88dd…2c6ee`, `ea3be34f…62d79f`,
   `21a31df9…5aed5`, `7ef38d6f…b6aac`, `69026241…aa5b1` (all IDs have
   the `b-prime-leaf-` prefix).
2. `primary-K1-1999-2000-exterior-alpha-half`, synthetic correlated
   refinement: `COMPLETE / EQUIVALENT_WITHIN_TOLERANCE / SUPPORTED`; nominal
   `1.597157034834823e-05`, interval
   `[1.596783034841625e-05, 1.5975310348280212e-05]`. Ordered components:
   `4df14642…7462a`, `d14e0ffb…b1be5`, `525099df…be77`,
   `735f6d06…05a9a`, `4861cd7f…ee42`, `65d0a36c…696ea`.
3. `deep-K22-1-1000-exterior-throat-kappa`: `INCOMPLETE`, with no angle,
   outcome, or scientific state. Exact missing components are
   `fc945cdb…c7e16`, `c7b0930f…15a13`, `6c63793a…60a58`,
   `f55a699c…49e3`, `d664ab96…52b3`, `bd06b291…80bbf`.
4. `primary-K0-19-20-exterior-fixed-r3#zero-calibration`, synthetic:
   calibration denominator `b-prime-leaf-21a31df9512726338ff0920025fd5e5c42e67ef7d603130e822b3a2798b5aed5`;
   `COMPLETE / UNRESOLVED`, unbounded with no fabricated angle.
5. `primary-K0-19-20-exterior-fixed-r3#computed-unresolved`, synthetic:
   produced-unresolved component
   `b-prime-leaf-ea3be34f9f06cab547552a6b774adba5305ed328a3a8ae4e8e49b2d78562d79f`;
   `COMPLETE / UNRESOLVED`, zero missing components, no Gram or angle.
6. `empirical-error-gram-validation`, synthetic components `component-a` and
   `component-b`: resealed non-PSD, altered cross-term, altered marginal/disk,
   and exact-recomputation tampering were rejected.

Every non-recorded centre/channel above is labelled synthetic contract evidence.
The smoke count is exactly six; no other projective row was reduced.

## Red/green and verification

- Initial red: the signed-channel/Gram test failed because
  `windows_solver.response_reduction` did not exist.
- Separate planner red failed on absent `build_projective_row_plans`; partial
  reducer red failed on absent `reduce_projective_row`; complete cases failed on
  the deliberate `NotImplementedError`; CLI red rejected unknown
  `campaign-reduce`. Each slice was made green before the next.
- Gram negatives cover unsigned substitutes, unknown families, missing
  provenance, nonfinite values, duplicates, missing required families, non-PSD,
  altered cross terms/marginals, and discrepancy-undercovering disks.
- Focused command:
  `PYTHONPATH=src python -m unittest tests.test_linear_response_uncertainty tests.test_linear_response_projective tests.test_linear_response_contract -v`
  — 32/32 passed.
- Full command:
  `PYTHONPATH=src python -m unittest discover -s tests -v`
  — 203/203 passed.
- `python .tasks/validate_board.py`, `python -m compileall -q src tools tests`,
  and `git diff --check` passed.
- The full gate exposed one TASK-009 fixture that built a native-factory
  checkpoint but validated it under a distinct operator-factory identity. The
  fixture now builds under the descriptor's exact `PrecisionFactoryIdentity`;
  production selection/factory binding was not weakened.

## Commit SHA(s)

- `b9b952c3409146ab695df082662a13a922f6e03e` —
  `feat(response): add empirical projective reducer`.
- TaskPlanner/report closure is recorded by the commit containing this report.

## Self-review and concerns

- The full 174-row planner was enumerated and hashed but never populated or
  classified. Only the six frozen synthetic/representative cases ran.
- The reducer consumes authenticated signed-channel evidence but does not create
  it. The operator must supply the complete 553-leaf checkpoint/evidence bundle;
  missing precision stays `INCOMPLETE`.
- Deterministic empirical error geometry is not a stochastic covariance,
  posterior, confidence region, or formal enclosure. Conservative disks are
  bounded numerical-error ledgers under the declared channel model.
- TASK-011 still owns exact full-bundle admission, provider availability,
  release-manifest/export closure, and platform/package gates. No provider
  admission or response evidence was created here.
