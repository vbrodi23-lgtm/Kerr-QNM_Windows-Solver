# M02 High-Spin Spectral Extension Implementation Plan

> **Superseded on 2026-08-08.** Do not execute this 3,303-root Cartesian expansion. M02 now uses the stratified B′ domain and a separate 44-root exact-selector overlay. The controlling plan is `docs/keystone/tasks/2026-08-08-m02-b-prime-553-leaf-closure.md`, with execution governed by TASK-069, TASK-070, and TASK-007–TASK-011 plus TASK-071–TASK-074.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the 2,736-root spectral carrier with a 3,303-root exact-node carrier that supplies every direct-spin and `Mκ`-derived baseline root required by M02.

**Architecture:** Preserve the existing spectral provider as the sole production owner. A new offline extension builder authenticates and archives the admitted 2,736-root parent, retains its scientific values, and computes 567 additional roots by simultaneous three-overtone coupled angular/Leaver continuation. The continuation uses stable near-extremal coordinates, predictor/corrector step control, clustered multi-inversion candidate banks, and atomic one-to-one genealogy assignment. Direct-`a/M` and exact-`Mκ` source identities remain distinct provenance while selection uses the derived binary64 spin identity.

**Tech Stack:** CPython 3.12, standard-library artifact validation, NumPy/SciPy only inside offline numerical tools, canonical Leaver continued fraction, spin-weighted spheroidal angular matrix, `unittest`, TaskPlanner, GitHub Actions.

## Global Constraints

- Keep one complete grid per ℓ: 52 spins for ℓ=2, 52 for ℓ=3, and 53 for ℓ=4; total roots are exactly 780 + 1,092 + 1,431 = 3,303.
- Preserve all 63 mode towers: `s = −2`, `ℓ ∈ {2,3,4}`, every `m = −ℓ,…,+ℓ`, and `n ∈ {0,1,2}`.
- Add direct spins `0.9995` and `0.9999` to ℓ=2,3; add all nine M02 direct spins to ℓ=4; add four exact `Mκ`-derived spins to every ℓ.
- The exact `Mκ` values are `1/100`, `1/200`, `1/500`, and `1/1000`; use `x = 2Mκ/(1−2Mκ)` and `a/M = sqrt(1−x²)` exactly as the approved M02 contract defines it.
- Never interpolate, extrapolate, or relabel a stored root. Every new row must be solved at its exact derived binary64 spin.
- Preserve the parent catalog's accepted values and independent 392-row Motohashi comparison evidence; new rows must carry separate canonical-continuation diagnostics.
- The branch label remains `schwarzschild-overtone-continuation`. Do not claim damped-mode/zero-damping-mode classification from this task.
- Keep `formal_root_enclosure = false`; numerical convergence is not a proof-bearing enclosure.
- The installed runtime must not import offline generator modules or numerical dependencies.
- Treat Leaver inversion index as candidate-generation metadata, never as an overtone identity.
- Preserve the parent carrier and receipt as immutable offline inputs after replacement; the wheel contains only the active carrier.
- Generated data may be mechanically written by the authenticated generator; hand-edited source changes use `apply_patch`.

---

### Task 1: Freeze the exact 3,303-key contract

**Files:**
- Modify: `tests/fixtures.py`
- Modify: `tests/test_catalog_builder.py`
- Modify: `tests/test_spectrum.py`
- Modify: `tests/test_linear_response_contract.py`
- Create: `tests/test_spectral_extension.py`

**Interfaces:**
- Consumes: the approved M02 direct-spin and `Mκ` axes from `windows_solver.linear_response`.
- Produces: literal target counts, exact derived-spin hex identities, and behavior tests that the later builder/provider must satisfy.

- [ ] **Step 1: Add literal failing target-grid tests**

  Define expected keys from explicit direct rationals plus these hand-checked derived identities:

  ```python
  EXPECTED_KAPPA_SPINS = {
      Fraction(1, 100): (0.999791731748236, "0x1.ffe4b3ad56fa5p-1"),
      Fraction(1, 200): (0.9999489834961278, "0x1.fff9502b91917p-1"),
      Fraction(1, 500): (0.9999919355814243, "0x1.fffef1672c027p-1"),
      Fraction(1, 1000): (0.9999979919739198, "0x1.ffffbc9f2ff3bp-1"),
  }
  ```

  Assert 3,303 keys, `{2: 780, 3: 1092, 4: 1431}` roots, `{2: 52, 3: 52, 4: 53}` spin counts, and no duplicate binary64 spin identity.

- [ ] **Step 2: Add the M02 exact-selection regression**

  Construct all 11 frozen response modes and all 13 sampling coordinates through the public request contract, select each mode × derived spin from the spectral catalog, and assert exactly 143 returned roots with matching mode and `float.hex()` identities.

- [ ] **Step 3: Add fail-closed provenance tests**

  Assert that each catalog row exposes one source coordinate: direct rows use reduced `a_over_M`; derived rows use reduced `M-kappa`, the approved transformation ID, and an exact derived spin hex. Reject a forged source rational, transformation ID, grid family, or duplicate derived spin.

- [ ] **Step 4: Run the red gate**

  Run:

  ```bash
  PYTHONPATH=src python -m unittest tests.test_spectral_extension tests.test_spectrum tests.test_catalog_builder -v
  ```

  Expected result: failures naming the still-2,736 catalog, absent extension builder, and missing provenance columns.

- [ ] **Step 5: Commit the red contract**

  ```bash
  git add tests/fixtures.py tests/test_catalog_builder.py tests/test_spectrum.py tests/test_linear_response_contract.py tests/test_spectral_extension.py
  git commit -m "test: freeze M02 high-spin spectral domain"
  ```

### Task 2: Implement the authenticated continuation builder

**Files:**
- Create: `tools/extend_kerr_qnm_lattice.py`
- Modify: `tools/kerr_cf_solver.py`
- Modify: `tests/test_spectral_extension.py`
- Modify: `tests/test_catalog_builder.py`

**Interfaces:**
- Consumes: authenticated parent CSV/receipt bytes and the canonical coupled angular/radial backend.
- Produces: `SpinTarget`, `extension_targets_for_ell(ell)`, resumable tower checkpoints, `extend_lattice(parent_csv, parent_receipt, workers=1) -> tuple[bytes, bytes]`, and deterministic CSV/receipt bytes.

- [ ] **Step 1: Define the target record and exact coordinate mapping**

  Implement this immutable boundary:

  ```python
  @dataclass(frozen=True, slots=True)
  class SpinTarget:
      spin: float
      spin_binary64_numerator: int
      spin_binary64_denominator: int
      spin_binary64_hex: str
      coordinate_id: str
      coordinate_exact: Fraction
      transformation_id: str
      grid_family: str
  ```

  Direct targets use `identity-a-over-M`; `Mκ` targets use `kerr-prograde-spin-from-dimensionless-surface-gravity`. For every target require `(spin_binary64_numerator, spin_binary64_denominator) == spin.as_integer_ratio()` and `spin_binary64_hex == spin.hex()`. The exact `Mκ` rational is the source-coordinate identity; it is never described as an exact rational physical spin. Sort by numeric spin, assign the index in the full ℓ-grid, and reject repeated binary64 identities.

- [ ] **Step 2: Authenticate the parent before numerical work**

  Require the exact admitted parent CSV SHA-256, receipt SHA-256, 2,736-row key set, receipt/catalog binding, and canonical backend source hashes before invoking any solver. Add a mocked test proving a one-byte parent change fails before the solver call count changes from zero.

- [ ] **Step 3: Implement stable near-extremal coordinates and predictors**

  Evaluate the horizon gap without cancellation:

  ```python
  epsilon = sqrt((1.0 - spin) * (1.0 + spin))
  M_kappa = epsilon / (2.0 * (1.0 + epsilon))
  ```

  Continue independently under two schedules: A uses `x = −log(epsilon)` and B uses `y = −log(M_kappa)`. Initialize every labelled `n = 0,1,2` predictor from the final two authenticated parent nodes, extrapolate secantly in the active coordinate, and land exactly on each requested binary64 target. Use measured caps `Δx ≤ 0.16` for ℓ=2 and `Δx ≤ 0.12` for ℓ=3,4; use `Δy ≤ 0.12` for ℓ=2 and `Δy ≤ 0.09` for ℓ=3,4.

- [ ] **Step 4: Assign all three overtones atomically**

  At each proposed node, solve the full three-predictor × three-inversion candidate bank. Select the angular eigenpair using the continued separation/eigenvector rather than the spherical eigenvalue alone. Reject non-finite or non-damped roots, optimizer residual above `1e-8`, continued-fraction error above `1e-9`, exhausted fractions, or angular-label/refinement failures.

  Cluster candidates without using inversion as identity, with radius `min(2e-8, 0.02 × predicted_minimum_overtone_separation)`. Deterministically assign three distinct clusters to labels `n = 0,1,2` by minimizing the global correction-to-local-separation cost. Require:

  - at least three assigned clusters and assigned minimum separation `≥ 1e-6`;
  - best/second-best assignment separation of at least five percent;
  - every `predictor_correction_to_separation ≤ 0.24`.

  On any failure, halve the coordinate step without mutating accepted state. Fail closed below step `0.003`. Grow a successful step by at most `1.35` when the maximum trust ratio is below `0.06`. Tests must reproduce the stale-seed `(2,2)` four-cluster branch hop and prove that adaptive atomic assignment preserves the three authenticated labels.

- [ ] **Step 5: Polish exact nodes and prove two-path/reverse agreement**

  At every requested exact node, run the full candidate bank, canonical polish, repeat polish, continued-fraction depth/tolerance refinement, and angular padding refinement `20→24`. Record separately:

  ```python
  {
      "optimizer_residual_abs": residual,
      "continued_fraction_error": cf_error,
      "continued_fraction_terms": cf_terms,
      "angular_refinement_abs": abs(A24 - A20),
      "repeat_polish_delta_abs": abs(omega_repeat - omega),
      "predictor_correction_abs": abs(omega - predictor),
      "predictor_correction_to_separation": trust_ratio,
      "canonical_polish_delta_abs": abs(omega_polished - omega_assigned),
      "continuation_path_delta_abs": abs(omega_schedule_A - omega_schedule_B),
      "reverse_continuation_delta_abs": abs(omega_reverse - omega_forward),
  }
  ```

  Reserve `branch_seed_delta_abs` for the parent cohort's original exact-node qnm-seed meaning; never populate it with a continuation predictor correction. Continue backward from the most extreme target through every exact extension target and the authenticated parent endpoint. Reject path or reverse disagreement above `1e-8`. These are numerical genealogy diagnostics, not formal uniqueness proofs.

- [ ] **Step 6: Make checkpoints and outputs deterministic**

  Bind every checkpoint to the parent CSV/receipt hashes, generator source hash, canonical backend hashes, policy/target-list hashes, and numerical runtime versions. A corrupt, truncated, wrong-policy, or stale-parent checkpoint must fail before reuse. Publish outputs atomically only after all towers validate, and prove one-worker and four-worker runs emit byte-identical CSV and receipt bytes.

  Preserve every parent scientific value and its 392 Motohashi-comparison rows. Add `generation_cohort`, exact source-coordinate fields, binary64 spin ratio/hex, and extension-only genealogy diagnostics. Parent rows are labelled `parent-2736` and retain their original diagnostic semantics; extension rows are labelled `m02-extension-567`. Do not claim the extension diagnostics for the parent cohort.

- [ ] **Step 7: Run focused green tests**

  Run:

  ```bash
  PYTHONPATH=src:tools python -m unittest tests.test_spectral_extension tests.test_catalog_builder tests.test_linear_response_contract -v
  ```

  Expected result: all deterministic-builder, authentication, mapping, checkpoint, branch-hop, assignment, path/reverse, and failure-policy tests pass without running the full lattice.

- [ ] **Step 8: Commit the builder**

  ```bash
  git add tools/extend_kerr_qnm_lattice.py tools/kerr_cf_solver.py tests/test_spectral_extension.py tests/test_catalog_builder.py
  git commit -m "feat: add authenticated Kerr lattice extension"
  ```

### Task 3: Generate and admit the 3,303-root artifact

**Files:**
- Create: `src/windows_solver/data/kerr_qnm_roots_3303.csv`
- Create: `tools/data/kerr_qnm_roots_2736_parent.csv`
- Create: `tools/data/kerr_qnm_lattice_receipt_2736_parent.json`
- Modify: `src/windows_solver/data/kerr_qnm_lattice_receipt.json`
- Remove from the installed package only after replacement is verified: `src/windows_solver/data/kerr_qnm_roots_2736.csv`
- Modify: `src/windows_solver/spectrum.py`
- Modify: `src/windows_solver/payload_validation.py` only if the descriptor contract changes require it
- Modify: `pyproject.toml`
- Modify: `tests/test_spectrum.py`
- Modify: `tests/test_public_surface.py`

**Interfaces:**
- Consumes: deterministic builder output from Task 2.
- Produces: `kerr-qnm-computed-lattice-3303`, exact catalog selection, receipt validation, and unchanged spectral artifact shape apart from extended scope/provenance.

- [ ] **Step 1: Run the full resumable generation**

  Run the extension builder against the packaged parent with four workers and a task-scoped checkpoint directory:

  ```bash
  PYTHONPATH=src:tools python tools/extend_kerr_qnm_lattice.py \
    --parent-catalog tools/data/kerr_qnm_roots_2736_parent.csv \
    --parent-receipt tools/data/kerr_qnm_lattice_receipt_2736_parent.json \
    --output-catalog src/windows_solver/data/kerr_qnm_roots_3303.csv \
    --output-receipt /tmp/m02-kerr-qnm-lattice-receipt.json \
    --checkpoint-dir /tmp/m02-kerr-root-checkpoints \
    --workers 4
  ```

  The command must atomically publish both outputs only after 3,303 rows and every ceiling validate.

- [ ] **Step 2: Inspect the generated evidence before admission**

  Verify counts, hashes, all 567 extension rows, per-ℓ maxima, exact `Mκ` provenance, no solver failures, no exhausted fractions, no assignment/path/reverse breach, and all 143 frozen M02 selectors. Compare literal probe roots for `(2,2)` at `.9995`, `.9999`, `Mκ=.002`, `Mκ=.001` and `(4,4)` at `.999`. Move the verified receipt into the packaged data path mechanically.

- [ ] **Step 3: Update the spectral owner test-first**

  Change catalog/provider IDs, hashes, resource path, expected key grids, counts, receipt schema, scope, and row provenance validation. Keep exact `(ℓ,m,n,spin.hex())` selection and fail before partial output. Run the focused spectrum tests until green.

- [ ] **Step 4: Archive and remove the superseded packaged carrier**

  First verify that the byte-identical parent catalog and receipt exist under `tools/data/` and that the extension receipt binds their hashes. Delete the packaged `kerr_qnm_roots_2736.csv` only after the new resource loads, hashes, selects, and passes the full spectrum suite. Update package-data paths so a wheel contains exactly one active root catalog while offline reproduction retains the immutable parent inputs.

- [ ] **Step 5: Run artifact verification**

  Run:

  ```bash
  PYTHONPATH=src python -m unittest tests.test_spectrum tests.test_public_surface tests.test_linear_response_contract -v
  ```

  Expected result: the provider materializes and verifies the 3,303-root artifact, reuses cache with zero work, rejects tampering, and serves every M02 baseline selector.

- [ ] **Step 6: Commit the admitted carrier**

  ```bash
  git add pyproject.toml src/windows_solver/data src/windows_solver/spectrum.py src/windows_solver/payload_validation.py tests/test_spectrum.py tests/test_public_surface.py tests/test_linear_response_contract.py
  git commit -m "feat: admit 3303-root Kerr spectrum"
  ```

### Task 4: Synchronize release control and prove the bounded result

**Files:**
- Modify: `src/windows_solver/data/release_domain_manifest.json`
- Modify: `src/windows_solver/release_manifest.py`
- Modify: `tests/test_release_manifest.py`
- Modify: `README.md`
- Modify: `NOTICE.md`
- Modify: `docs/architecture.md`
- Modify: `docs/release-baseline.md`
- Modify: `docs/superpowers/specs/2026-08-07-authenticated-spectral-catalog-design.md`
- Modify: `docs/superpowers/specs/2026-08-07-public-linear-response-closure-design.md`
- Modify: `docs/superpowers/plans/2026-08-07-authenticated-spectral-catalog.md`
- Modify: `docs/superpowers/plans/2026-08-07-public-linear-response-closure.md`
- Modify: `.tasks/IN_PROGRESS.md`
- Modify: `.tasks/DONE.md`
- Modify: `.tasks/NEXT.md`
- Modify: `.tasks/WORK_LOG.md`

**Interfaces:**
- Consumes: the admitted catalog/receipt hashes and fresh verification output.
- Produces: one consistent public status, release-manifest source receipt, TaskPlanner completion record, and PR #5 handoff.

- [ ] **Step 1: Update exact release identities**

  Replace every active 2,736-root provider/catalog/count/path claim with the verified 3,303-root identity. Retain historical PR #2 descriptions only when explicitly labelled historical. Update the spectral source receipt and manifest hash binding without altering unrelated milestone scope.

- [ ] **Step 2: Record the cohort-specific evidence ceiling**

  State that all 3,303 roots are finite, damped, carry their cohort's admitted canonical-backend diagnostics, and are exactly selectable. State separately that the 567 extension roots passed simultaneous genealogy assignment, two-path agreement, reverse continuation, continued-fraction and angular refinement. The 2,736 parent roots retain their original qnm-seed, canonical polish, refinement, and 392-row comparison evidence; do not retroactively claim extension path checks for them. Formal root enclosure, continuum stability, spectral fields, and DM/ZDM classification remain absent.

- [ ] **Step 3: Run fresh complete proof**

  Run:

  ```bash
  PYTHONPATH=src python -m unittest discover -s tests -v
  python .tasks/validate_board.py
  python tools/validate_release_manifest.py
  python -m compileall -q src tools tests
  ```

  Build a wheel, inspect that it contains the 3,303 catalog and excludes the superseded carrier, install it into a temporary target, and run one direct-spin plus one `Mκ`-derived spectral selection.

- [ ] **Step 4: Run independent change review**

  Review the complete branch against this plan on both spec and standards axes. Fix every blocking finding through the implementation loop and re-run the directly affected proof.

- [ ] **Step 5: Complete TaskPlanner and publish PR #5**

  Move TASK-069 to Done only after artifact hashes, commands, evidence ceiling, commit, and PR reference are recorded. Restore TASK-007 as the sole Next item, push the reviewed branch from merged `main`, open draft PR #5, and wait for Windows and Ubuntu CI.

---

## Plan self-review

- Spec coverage: exact axes, counts, coordinate provenance, no interpolation, provider ownership, generation, admission, release control, evidence ceiling, review, and CI each map to a task above.
- Placeholder scan: no deferred implementation or undefined acceptance step remains.
- Type consistency: `SpinTarget`, `extension_targets_for_ell`, and `extend_lattice` are defined once in Task 2 and consumed unchanged by Tasks 3–4.
- Numerical correction: a blocking review showed that low residual and Leaver inversion index do not preserve overtone labels. The revised design requires simultaneous clustered assignment in stable near-extremal coordinates, adaptive halving, two independent schedules, reverse continuation, angular genealogy, and cohort-specific diagnostic semantics. Probe maxima were trust ratio `0.20035`, A/B disagreement `6.18e-14`, and reverse disagreement `5.74e-14`; the frozen ceilings are conservative numerical gates, not uniqueness proofs.
