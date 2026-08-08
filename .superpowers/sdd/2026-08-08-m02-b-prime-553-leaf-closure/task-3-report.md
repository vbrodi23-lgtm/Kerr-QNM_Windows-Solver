# TASK-007 — Authenticated evidence intake for operator-run calculations

## Status

DONE AFTER REVIEW REMEDIATION — software intake is structurally ready; operator response evidence remains absent and the linear-response provider remains unavailable.

## Files changed

- `src/windows_solver/evidence_intake.py` — versioned bundle digest, strict loader/validator, exact B′ partition and root binding, authenticated runtime/source/comparator provenance, cross-platform safe paths, authenticated representative fixture receipt, and explicit legacy missing-evidence ledger.
- `src/windows_solver/cli.py` — deterministic `validate-evidence` JSON command.
- `src/windows_solver/data/evidence_intake/` — five byte-exact pinned inputs under public-neutral `.fixture` package names.
- `pyproject.toml` — package-data bindings for the five authenticated fixtures.
- `tests/test_linear_response_evidence_intake.py` — partial/full, forged-binding, fixture, smoke, Windows-path/ADS, malformed-state, and CLI coverage.
- `docs/evidence-intake-powershell.md` — `Resolve-Path`/`Join-Path` invocation and evidence-ceiling handoff.
- `.tasks/` — TASK-007 completion and TASK-008 as sole Next.

No response solver, uncertainty reducer, batch runner, provider admission path, spectrum source, or spectrum artifact was changed or executed.

## Red/green proof

1. The first focused test failed once because `windows_solver.evidence_intake` did not exist. The minimal public module/API made that slice green.
2. The expanded focused contract then failed at import because the strict digest, loader, fixture receipt, and constants did not exist. The single intake module, CLI seam, and authenticated fixture package made the behavior suite green.
3. Self-review negatives proved a shape-valid but wrong root reference was accepted and duplicate JSON keys were silently canonicalized. Exact `baseline_root_reference_id` comparison and duplicate-key rejection made the focused test green.
4. The first full run produced one expected integration failure because private lineage tokens appeared on the public surface. The same authenticated bytes were preserved under neutral `.fixture` names, original repository paths remained separate provenance, and installed Python composes the private identifiers without publishing them literally. The public-surface test and complete suite then passed.
5. Review remediation began with a focused red run: 12 intake tests produced eight failures and two errors. Undefined runtime identities, unbound/extra producer hashes, forged Git-blob and comparator-identity hashes, `C:relative` and alternate-data-stream paths, and dictionary/list numerical states all crossed the old boundary. The tightened bindings made all 12 intake tests and the 34-test focused intake/contract suite green; malformed CLI state now emits one JSON error and exits 2.

Final focused verification: 34 passed. Final full verification: 160 passed.

## Bundle schema and validation behavior

Schema version 1 binds:

- state `partial-smoke` or `complete-operator`;
- B′ contract SHA-256 `e29c27ed5db8e45e93db66b85e76e0e3289f75afb761df0ac330c39bdc98eaf0` and the exact ordered 553 leaf IDs;
- frozen numerical-policy fingerprint;
- a canonical `cpython-MAJOR.MINOR[.PATCH]-SYSTEM-ARCH` runtime identity and producer source-hash set equal to the byte-verified source-file hashes;
- byte-bound source files and per-leaf payloads;
- exact role, mode, direct-χ/source-Mκ coordinate, mechanism, numerical state, source reference, and exact spectral-root reference;
- exact produced/missing partition and quarantined comparator fixtures whose Git blob and canonical identity hashes are recomputed from declared source bytes/fields;
- separator-normalized canonical bundle-content SHA-256.

The validator rejects duplicate keys/IDs/normalized paths, off-domain leaves, wrong identity/root bindings, incomplete or overlapping partitions, unknown fields, non-finite JSON, malformed runtime lineage, producer/source hash asymmetry, forged sizes/Git blobs/comparator identities, drive-relative/UNC/ADS/traversal/symlink-escaping paths, non-string numerical states, global uncertainty declarations, comparator leakage, and production source-code/executable payloads before reduction.

`complete-operator` requires exactly 553 produced IDs and zero missing IDs. Both states always return `release_admissible: false`; structural validity never admits the provider.

The command accepts a bundle directory or manifest path:

```text
python -m windows_solver validate-evidence <bundle-or-manifest>
solver validate-evidence <bundle-or-manifest>
```

Success emits one canonical JSON object containing command, state, bundle digest, produced/missing/comparator counts, predeclared sampled IDs, validation status, and `release_admissible: false`. Invalid input emits one machine-readable error to stderr and exits nonzero. Windows and POSIX spellings of the same safe relative path produce the same digest.

## Exact pinned provenance

Repository: `vbrodi23-lgtm/Windows-Solver_V2-whiteboard`  
Commit: `0c1e8a3d3bca6e608c34e111476a4f6dcb73e86e`

| Repository path | Bytes | Git blob SHA | SHA-256 |
|---|---:|---|---|
| `docs/evidence/v2-02/v2_local_response_protocol.json` | 748 | `ed729c8420b6c08abc534212dc2a593c1c65cf36` | `421e0751f5a68f95cd69fc0b5cdb155c96fe5cbb83d81e59489bf9130636673b` |
| `docs/evidence/v2-02/v2_local_response_reduction.json` | 5,288 | `3b9034df6eada7ec60ac347518a6f616d4f6683e` | `b6a5018c1f4875ebea2f26d544c354896edb33c2bb176ccebc90a1d511c46203` |
| `docs/evidence/v2-02/v2_local_response_components.csv` | 5,415 | `3f24cb859b4d13641bf0649d214dfd0ded498239` | `20aa65b184e7866827f2283d64148fc68f2a0f16d02f701afc8cd516157b42f4` |
| `docs/evidence/v2-07-physical-cubic-even/v2_07_physical_cubic_even_resolved.csv` | 6,578 | `b6a6620702ce264e0467d7daf0358bae83d5d5d4` | `89f28eabdf0be247a1db87fb13c6f0c8a60bb9065518426b8a9d5a24630b0bd1` |
| `docs/evidence/v2-07-physical-cubic-even/v2_07_physical_cubic_even_status.json` | 5,356 | `8924859018574c0eda7941a2024b03a6e971a012` | `07b12e64fa22783a9429371facfc14990b70fbc28dcf60039c477ec3bdec1d9f` |

The computed representative receipt SHA-256 is `ab93c8fb73abd39372f4890f7c2f129cc2b6f87211adae011a6fc0c12ac7a423`.

## Fixture and missing-evidence counts

- GR pilot: 9 authenticated χ=19/20 components across modes 220/330/440 and horizon-admittance/fixed-r3/light-ring mechanisms.
- Pilot claim ceiling: legacy component-local signed-amplitude-ladder migration evidence only; it is not operator evidence.
- Cubic comparator: exactly 8 mode-220 rows at χ ∈ {0, 3/10, 1/2, 7/10} × {plus, minus}, theory `parity-even-cubic-higher-curvature-eft`, comparator-only.
- Legacy ladder ledger: 147 exact identities = 3 modes × 7 spins × 7 mechanisms.
- Authenticated pilot subset: 9.
- `MISSING_SOURCE_EVIDENCE`: 138, with no inferred values, ladders, or global-cover substitution.

## Representative smoke IDs

The synthetic structural manifest exercises the complete 553-ID partition, while the partial/fixture smoke fixes these head, tail, and risk identities before data inspection:

| Role | Exact ID |
|---|---|
| Canonical B′ head | `b-prime-leaf-9e5777728144433e089f9559b92b6e139e16115a5a53099f40403a45297aa3c3` |
| Canonical B′ tail | `b-prime-leaf-59894e4af3913286bb06cb36d1f01f508f728588937fbc5a45eab6da2906b77d` |
| Low-signal pilot light-ring | `b-prime-leaf-3ee2b2dcdc5276cbcd51264f1210002314acd3ff845bb7a464f1e9333e9115c5` / `pilot:220:19/20:exterior-light-ring` |
| Highest pilot mode | `b-prime-leaf-ea3be34f9f06cab547552a6b774adba5305ed328a3a8ae4e8e49b2d78562d79f` / `pilot:440:19/20:horizon-admittance` |
| Cubic lower endpoint | `cubic:220:0/1:plus` |
| Cubic upper endpoint | `cubic:220:7/10:minus` |

## Verification

- `PYTHONPATH=src python -m unittest tests.test_linear_response_evidence_intake tests.test_linear_response_contract -v` — 34 passed.
- `PYTHONPATH=src python -m unittest discover -s tests -v` — 160 passed.
- `python .tasks/validate_board.py` — valid in-progress and completion states.
- `python -m compileall -q src tools tests` — passed.
- `git diff --check` — passed.
- Offline wheel SHA-256 `733bb5cfe673fa9a0d8d03e7cb1c5a8ac2a8cd90f9d79562adde2123839ebbd3`; it contains all five neutral `.fixture` resources with the authenticated bytes above.

## Commit SHA(s)

- `35d7f39de46b125a8e0e01de8f8dfbb12df363ff` — `feat(evidence): add authenticated operator intake`
- `a4a722a72daf84f9eef49507c481db49fe1b0595` — `fix(evidence): authenticate intake provenance`

## Self-review

- Exact root references are derived from each leaf's frozen mode/spin, not accepted by hash shape alone.
- Duplicate JSON keys fail before canonicalization for manifests, JSON payloads, and JSON fixtures.
- Runtime fingerprints follow a declared canonical grammar, and producer source hashes exactly equal the set backed by byte-verified source files.
- Comparator Git blob hashes are recomputed from the source bytes; comparator identity hashes are recomputed from canonical explicit fixture/source identity fields.
- Path normalization is digest-stable across Windows/POSIX spellings and rejects absolute, drive-qualified, drive-relative, UNC, alternate-data-stream, traversal, and symlink escape paths.
- Numerical-state values are type-checked before membership; malformed CLI input is a deterministic one-object JSON error with exit 2.
- Pilot/cubic bytes authenticate against both Git blob SHA and byte SHA-256 before parsing.
- Comparator fixtures have no path into production completeness, and the provider descriptor remains unavailable.
- Public-neutral fixture names do not alter the pinned bytes or lose their private source paths/commit/blob provenance.

## Concerns / evidence ceiling

- This task proves software intake structure and fixture migration only. It does not prove any response payload scientifically valid.
- The operator has not supplied a complete 553-leaf bundle. The provider must remain unavailable.
- The 138 absent legacy local-ladder identities remain explicit missing source evidence.
- Cubic rows are comparator-only and cannot contribute to GR production completeness or uncertainty reduction.
- No TASK-008 response-engine work or full evidence collection was started.
