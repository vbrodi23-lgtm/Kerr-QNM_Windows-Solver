# TASK-070 — Admit the 44-root exact-selector overlay for B′

## Status

DONE

## Files changed

- `tools/compute_kerr_qnm_overlay.py` — literal 44-target enumerator, authenticated-parent boundary, canonical two-schedule cohort continuation, multi-inversion assignment, exact-target polish/refinement, reverse/path gates, deterministic checkpoint/receipt serialization, and atomic publication.
- `src/windows_solver/data/kerr_qnm_m02_overlay_44.csv` — real 44-row numerical sparse overlay.
- `src/windows_solver/data/kerr_qnm_m02_overlay_receipt.json` — strict canonical receipt binding parents, target set, policy, generator, backend, runtime, validation extrema, and artifact bytes.
- `historical-records/m02/spectral-overlay-44/task-2-overlay-checkpoint.json` — complete 44-row checkpoint bound to the same generator/backend/runtime/parents/policy/target set.
- `src/windows_solver/spectrum.py` — strict overlay receipt/CSV loading and validation, exact disjoint base-plus-overlay selection, and payload provenance while preserving the base carrier surface and sole spectral provider owner.
- `src/windows_solver/data/release_domain_manifest.json`, `src/windows_solver/release_manifest.py`, and `pyproject.toml` — release hash/count/module ownership and package-data bindings.
- `tests/test_spectral_extension.py` and `tests/test_release_manifest.py` — red/green builder, checkpoint, exact-target, runtime-union, immutable-parent, manifest, and fail-closed regression coverage.
- `.tasks/` — TASK-070 completion, TASK-007 as sole Next, and work-log evidence.

The immutable files `src/windows_solver/data/kerr_qnm_roots_2736.csv` and `src/windows_solver/data/kerr_qnm_lattice_receipt.json` were not changed.

## Red/green evidence

1. Initial red: `PYTHONPATH=src:tools python -m unittest tests.test_spectral_extension -v` ran 10 tests with 8 expected failures because the sparse builder, packaged resources, strict receipt, and runtime union did not exist. The two frozen-domain/board tests remained green.
2. Target enumeration red/green: the deep-spin target test initially exposed a binary64 mismatch from `(1−s)(1+s)` rather than the TASK-069-frozen `1−s²` evaluation. The stable formula and exact rational/binary64 identity test then passed.
3. Builder red/green: tests first failed for absent parent pre-authentication, candidate assignment/adaptive halving, independent/reverse rejection, deterministic 1/4-worker bytes, complete zero-work reuse, corrupt/stale checkpoint rejection, and cohort resume. Each passed after its implementation.
4. Numerical regression red/green: the first real cohort exposed an exact-target remainder incorrectly recorded as an adaptive-halving step. A regression test failed before `_updated_minimum_adaptive_step` distinguished exact remainders and passed after the fix; the stale checkpoint was discarded before the accepted clean run.
5. Self-review red/green: a result with `angular_overlap_min=0.899` was incorrectly accepted by generator-side validation even though policy/runtime required `≥0.9`. The focused regression failed with “ValueError not raised”, passed after the gate fix, and the real 44 rows were regenerated from a clean checkpoint under the final generator hash.
6. Execution-smoke red/green: `OverlayExecutionSmokeTests` first failed with `NameError: _overlay_smoke_rows is not defined`. After the eight representative row IDs and independent recompute/reload harness were added, both smoke tests passed.
7. Review remediation red/green: three focused contract tests produced 12 red assertions—five same-mode cohorts were not in numeric-spin order, and canonical-reserialized frequency/diagnostic mutations in complete/partial checkpoints were accepted. After numeric ordering and a canonical `results_sha256` envelope binding were implemented, the focused tests passed 3/3 and all builder contract tests passed 7/7. The accepted 44-row artifact was then regenerated cleanly under the final generator hash.

Final focused verification passed 56 tests.

## Exact generator command and runtime

```text
PYTHONPATH=src:tools python tools/compute_kerr_qnm_overlay.py --base-catalog src/windows_solver/data/kerr_qnm_roots_2736.csv --base-receipt src/windows_solver/data/kerr_qnm_lattice_receipt.json --output-catalog src/windows_solver/data/kerr_qnm_m02_overlay_44.csv --output-receipt src/windows_solver/data/kerr_qnm_m02_overlay_receipt.json --checkpoint historical-records/m02/spectral-overlay-44/task-2-overlay-checkpoint.json --workers 4
```

- Python: `3.12.13`
- NumPy: `2.3.5`
- SciPy: `1.17.0`
- Platform: `Linux-6.18.35-x86_64-with-glibc2.39`
- Generator SHA-256: `303f82877e4c557022a906f73b02d42ad44e2a3e1b821212183cbe8d8db1eacb`
- Target-set SHA-256: `e195928deccd6300b04fab28d60998511f0e788419c1832ee2cfbf28c83b7d90`
- Policy SHA-256: `5c62a1db00110ae3d3935f60d6e612acf1dae82fca52e2b6d81228e734824678`
- Canonical angular module SHA-256: `109642519372736375c24b15a879fe15c2a06714b78d743f065497fdad50738a`
- Canonical continued-fraction module SHA-256: `8ad69fba84d1100ca4b4647760b595ee15ea4a13ffd0a1bfdd9fe635c119d2e4`

The completed checkpoint was replayed with the same command and performed zero solver work; the CSV, receipt, and checkpoint hashes were unchanged.

## Artifact hashes and counts

| Artifact | Rows | SHA-256 |
|---|---:|---|
| Immutable base CSV | 2,736 | `9ebae4271309cd45a1b26c90d31155602ed8ef33bb79069adb5897e8afe7a564` |
| Immutable base receipt | — | `61a428a858de1eb7e42fe4cbbda37bf1fddcc808d98be2a62fd33ef4b5b74379` |
| Sparse overlay CSV | 44 | `c4c61a1b73e850d537dba5f5eb947af100449aa2a1958a1ec8ea086f60ffe8e8` |
| Sparse overlay receipt | — | `93a2e7586878d9c84e32d19ed9e7ad44d03572a91640625c44501bfbc46a5525` |
| Complete checkpoint | 44 | `f5a0fb6c2ecadbb5b75c692f79f17093d8f37999c142db5ad6b87168b8759f71` |
| Release manifest | — | `f946e02b50b87864547a6577636061d97244aff5c616f35398c01c524c0192cb` |

The checkpoint envelope authenticates the canonical result mappings with `results_sha256=704df4272793a586e55d9f9ba3ca6d7c55f464a06d9afebf00cb6fe4d03b9798`; both partial and complete checkpoint content changes are rejected before any backend work.

The overlay is exactly 28 primary direct-spin roots plus 16 exact-source-`Mκ` deep roots. Controls add no new base roots; the exact base-plus-overlay selector union covers all 87 B′ selectors.

## Numerical extrema

All 44 roots are finite and damped; zero failed. Values below are computed directly from the final CSV.

| Diagnostic | Minimum | Maximum | Gate |
|---|---:|---:|---:|
| Optimizer residual | `2.673771110915334e-15` | `7.088554314349275e-10` | `≤1e-8` |
| Continued-fraction error | `1.8621624263021126e-15` | `2.211011313778066e-13` | `≤1e-9` |
| Angular refinement | `1.3877787807814457e-17` | `1.2790406497749723e-13` | `≤1e-9` |
| Repeat-polish delta | `0` | `5.3299221744222913e-14` | `≤1e-9` |
| Predictor correction | `0.00033588505339121226` | `0.0365965290451337` | recorded |
| Predictor correction / separation | `0.00371402891905418` | `0.2296874712405642` | `≤0.24` |
| Assigned separation | `0.00099926955633728` | `0.1075627126809358` | `≥1e-6` |
| Assignment relative gap | `3.484353829789523` | `256.3484736706516` | `≥0.05` |
| Canonical-polish delta | `0` | `8.461015903014635e-14` | recorded |
| Independent-path delta | `2.8609792490763985e-16` | `6.5979741248900096e-12` | `≤1e-8` |
| Reverse-continuation delta | `5.967448757360216e-16` | `8.142017357683242e-14` | `≤1e-8` |
| Angular overlap | `0.9998083974611836` | `0.9999999940810185` | `≥0.9` |
| Minimum adaptive step | `0.022499999999999964` | `0.12` | `≥0.003` |

The tightest relative gate is predictor correction / separation: `0.2296874712405642` against the precommitted `0.24` ceiling.

## Literal probe roots

| Mode/source coordinate | Derived spin | Binary64 spin | `Mω` |
|---|---:|---|---|
| `220`, direct `χ=1999/2000` | `0.9995` | `0x1.ffbe76c8b4396p-1` | `0.9684382574496465 − 0.007577015072536927 i` |
| `220`, direct `χ=9999/10000` | `0.9999` | `0x1.fff2e48e8a71ep-1` | `0.9856735483827012 − 0.0034686730676767082 i` |
| `220`, source `Mκ=1/500` | `0.9999919355814243` | `0x1.fffef1672c027p-1` | `0.9958959649528077 − 0.0009985784229040661 i` |
| `220`, source `Mκ=1/1000` | `0.9999979919739198` | `0x1.ffffbc9f2ff3bp-1` | `0.9979485204094692 − 0.0004996426609646101 i` |
| `440`, direct `χ=999/1000` | `0.999` | `0x1.ff7ced916872bp-1` | `1.9229928773337701 − 0.010536400989477383 i` |

For deep rows the exact rational identity is the source `Mκ`; the physical spin is explicitly stored only as its derived binary64 ratio and hexadecimal identity.

## Representative execution-smoke evidence

The smoke harness predeclares eight rows rather than choosing them after results are known. It covers the canonical serialized head and tail, all four deepest `Mκ=1/1000` modes, both highest-spin `ℓ=4` modes at direct `χ=9999/10000`, and representatives attaining the global error/genealogy extrema. Some extrema are cohort-wide ties; the table names the sampled tie owner rather than claiming uniqueness.

For every row, the test independently called the canonical coupled backend at angular padding 20 and 24, matched the padding-20 angular value to the CSV, matched the padding-24 angular delta to the recorded refinement, then cleared every spectrum/receipt catalog cache and performed exact selection plus payload construction/validation through `SpectralCatalogProvider`. Every installed reload frequency delta was exactly zero.

| Exact row ID `(ℓ,m,n,source,num/den,spin_hex)` | Smoke role | `|F|` pad 20 | `|F|` pad 24 | CF error 20/24 | Angular refinement | Reload `|Δω|` |
|---|---|---:|---:|---:|---:|---:|
| `(2,1,0,M-kappa,1/100,0x1.ffe4b3ad56fa5p-1)` | canonical head | `2.9069931782354892e-12` | `2.933128782910337e-12` | `9.992112968424569e-15` | `1.3324765027951542e-14` | `0` |
| `(4,4,1,a-over-M,999/1000,0x1.ff7ced916872bp-1)` | numeric-order middle sentinel | `3.580548948608344e-13` | `3.5581281351423575e-13` | `4.148419911160778e-16` | `1.0659441999608839e-14` | `0` |
| `(2,1,0,M-kappa,1/1000,0x1.ffffbc9f2ff3bp-1)` | maximum residual; deepest `210` | `7.088554314349275e-10` | `7.088554314349275e-10` | `9.997626953243362e-15` | `6.217248937900877e-15` | `0` |
| `(2,2,0,M-kappa,1/1000,0x1.ffffbc9f2ff3bp-1)` | minimum separation/gap representative; deepest `220` | `1.5924462403002926e-11` | `1.5925049964990274e-11` | `9.767785201001778e-15` | `1.1102396263467957e-15` | `0` |
| `(2,2,1,M-kappa,1/1000,0x1.ffffbc9f2ff3bp-1)` | minimum-separation tie; deepest `221` | `8.968881412999631e-12` | `8.966350449172791e-12` | `9.873310604820458e-15` | `1.3323399077344022e-15` | `0` |
| `(2,2,2,M-kappa,1/1000,0x1.ffffbc9f2ff3bp-1)` | deepest `222` | `4.213605729117988e-11` | `4.212803271086569e-11` | `9.96653448056596e-15` | `1.3322856994638522e-15` | `0` |
| `(4,4,0,a-over-M,9999/10000,0x1.fff2e48e8a71ep-1)` | highest-spin `440` | `4.864407436331911e-13` | `4.928520477902735e-13` | `1.808531382004215e-15` | `1.4210861491463966e-14` | `0` |
| `(4,4,1,a-over-M,9999/10000,0x1.fff2e48e8a71ep-1)` | canonical numeric-spin tail; maximum correction/minimum overlap representative | `1.1279572198070861e-12` | `1.3490380595323041e-12` | `4.6059832885838804e-15` | `3.197453152923794e-14` | `0` |

Focused smoke command: `PYTHONPATH=src:tools python -m unittest tests.test_spectral_extension.OverlayExecutionSmokeTests -v` — 2 passed. The generator, CSV, receipt, and checkpoint hashes remained unchanged.

## Full verification

- `PYTHONPATH=src:tools python -m unittest tests.test_spectral_extension tests.test_spectrum tests.test_linear_response_contract -v` — 56 passed.
- `PYTHONPATH=src python -m unittest discover -s tests -v` — 148 passed.
- `python .tasks/validate_board.py` — valid after completion: 74 unique tasks, 12 milestones, 8 Done, 1 Next, 0 In Progress, acyclic dependencies.
- `python tools/validate_release_manifest.py` — valid at manifest SHA-256 `f946e02b50b87864547a6577636061d97244aff5c616f35398c01c524c0192cb`.
- `python -m compileall -q src tools tests` — passed.
- `git diff --check` — passed.
- Explicit base hashes matched the admitted values and `git diff --exit-code HEAD --` the base CSV/receipt was empty before the implementation commits.
- Offline wheel build `the_windows_solver-0.2.0-py3-none-any.whl` contained the base CSV/receipt and both new overlay resources; final verification wheel SHA-256 was `ec8afd3dbee4a0434229a694c0871e22ff0aef454b68e647dd22393e75561fcd`.

## Commit SHA(s)

- `6e01e403a53c9dc592004bca688bb8e976f3157d` — `feat(spectrum): admit M02 sparse root overlay`
- `38d702ea58cb98fa9d562126afda9ba6396832af` — `fix(spectrum): enforce overlay overlap floor`
- `3ff1262cc1666b51ea4985e6adc383ff503cf806` — `test(spectrum): smoke representative overlay roots`
- `d2e96c6494ef9908be6c2a4b4807fbcb729f7c44` — `fix(spectrum): authenticate overlay checkpoints`

## Self-review findings

- Verdict after remediation: **Looks good**; no blocking or unresolved non-blocking findings in the task scope.
- Exactness: the serialized target identities equal the literal 44-target set; deep rows preserve exact source `Mκ` and derived binary64 spin without rational-spin claims.
- Genealogy: both paths continue cohorts with multi-inversion clustering, one-to-one assignment, angular overlap, exact polish/refinement, independent-path comparison, and reverse return to an authenticated parent.
- Authentication and failure paths: parent mutations fail before solver calls; checkpoint bindings reject stale/corrupt inputs; complete verified checkpoints do zero work; output publication happens only after all 44 rows validate.
- Compatibility: `SpectrumCatalog.from_csv_bytes()` remains the exact 2,736-root parser; the union exposes the immutable base carrier surface to existing consumers and uses the existing sole provider owner for exact selection.
- Remediation: the review found the generator-side angular-overlap floor mismatch, added a red regression, fixed it, invalidated the old checkpoint, and regenerated the real receipt/checkpoint under the corrected generator hash before re-verification.
- Integrity remediation: review demonstrated that canonical-reserialized numerical changes could bypass solver work. The red tests mutated a frequency in a complete checkpoint and a diagnostic in a partial checkpoint with bindings intact; both were accepted before the fix. The canonical result-mapping SHA-256 now binds the envelope and is checked before deserialization or backend work.
- Ordering remediation: same-mode targets now sort by numeric binary64 spin, matching the receipt declaration. The regenerated CSV contains exactly the same 44 physical rows by exact selection identity; only serialization order and bound hashes changed.
- Execution smoke: eight predeclared head/tail/risk rows independently reproduced coupled-error and angular-refinement evidence and reloaded exactly through the sole installed provider owner.

## Risks / gaps

- Evidence remains numerical continuation/genealogy evidence only. There is no external comparator for these 44 roots, no formal root enclosure, and no DM/ZDM classification.
- The receipt deliberately binds the exact generation runtime and dependency versions. Regeneration on a different stack requires a new receipt and numerical review rather than silent reuse.
- The tightest predictor-correction/separation result is `0.2296874712405642`, below but close to the frozen `0.24` ceiling; it passed both schedules and all independent/reverse/refinement gates.
- No TASK-007 golden-fixture work or linear-response production was started.
