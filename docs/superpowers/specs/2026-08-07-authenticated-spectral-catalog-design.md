# Pure-Kerr Background QNM Lattice Design

**Status:** Approved by the user on 2026-08-07. PR #2 implements this exact
2,736-root scope: 690 for ℓ=2, 966 for ℓ=3, and 1,080 for ℓ=4. PR #3 freezes
the M01 release and evidence boundary; PR #4 begins the separate
`linear-response` migration.

## Goal

Compute, validate, package, and admit one background Kerr quasinormal-mode
lattice containing exactly 2,736 distinct roots. The lattice is a pure
general-relativity calculation. It contains no EFT sector and no polarization
split.

## Exact lattice

All rows use spin weight s = −2, mass-normalized frequency Mω, the outgoing
Kerr QNM convention, and branches continued from the Schwarzschild overtone
label n.

The mode set is:

- ℓ ∈ {2,3,4};
- every integer m from −ℓ through +ℓ;
- n ∈ {0,1,2};
- 63 distinct (ℓ,m,n) modes.

The χ sets are ℓ-dependent.

For ℓ = 2 and ℓ = 3:

- base grid χᵢ = 19i/780 for i = 0,…,39;
- this is 40 evenly spaced points from 0 through 19/20 = 0.95;
- add H = {97/100, 49/50, 99/100, 199/200, 997/1000, 999/1000};
- 0.95 is not added twice;
- total: 46 unique χ values per mode.

For ℓ = 4:

- χᵢ = i/52 for i = 0,…,39;
- this is 40 evenly spaced points from 0 through 3/4 = 0.75.

The exact counts are:

| ℓ | (m,n) modes | χ values | Rows |
|---|---:|---:|---:|
| 2 | 15 | 46 | 690 |
| 3 | 21 | 46 | 966 |
| 4 | 27 | 40 | 1,080 |
| Total | 63 | ℓ-dependent | 2,736 |

The catalog key is exactly
(ℓ, m, n, χ numerator, χ denominator), with every fraction reduced. IEEE-754
χ is an evaluated solver input and convenience value, not the source of key
identity.

The generic control-plane ModeKey retains one fixed
`polarization = "gravitational"` value for compatibility. That fixed metadata
is not a lattice axis, does not appear in the catalog key, and never duplicates
a row. No EFT identifier or sector appears in the catalog key, row schema, or
count.

## Numerical method

The production catalog is computed rather than interpolated or copied.

1. Reuse the existing canonical Leaver continued-fraction backend, pinned by
   its source commit and blob hashes. Its determinant equations and inversion
   machinery are migrated unchanged.
2. Use qnm 0.4.4, pinned by release artifact hash, to originate and continue
   each n = 0,1,2 Schwarzschild-labelled branch. This branch atlas is required
   because the continued-fraction inversion index alone admits more than one
   nearby zero.
3. Continue each branch monotonically with non-output seed nodes so no qnm
   continuation step exceeds 0.004. Hidden seed nodes are never serialized as
   catalog rows.
4. At every requested rational χ, feed the branch-atlas root to the canonical
   backend and root-polish the coupled angular/radial system. Store the
   canonical-backend result, not an interpolant or copied seed.
5. Solve the radial Teukolsky equation with the existing Leaver
   continued-fraction inversion and the angular equation with the existing
   spin-weighted spheroidal spectral matrix.
6. Store Mω and the angular separation constant A as complex real/imaginary
   fields, together with solver diagnostics.
7. Sort deterministically by ℓ, m, n, then exact χ.

The generator is an offline development tool. The installed public solver
continues to have no numerical runtime dependency: it validates and selects the
immutable packaged catalog.

## Validation

Every one of the 2,736 rows must satisfy all full-grid gates recorded by the
generator:

- the nonlinear root solve reports success;
- Mω and A are finite and Im(Mω) < 0;
- the polished radial residual is within the declared threshold;
- the continued-fraction error is within the declared threshold;
- a higher angular truncation changes A by no more than the declared threshold;
- an independent re-polish changes Mω by no more than the declared threshold;
- the canonical determinant-polished root remains within the declared
  cross-implementation distance of its branch-atlas seed;
- branch continuation reaches the requested χ without a missing step.

The exact thresholds and observed maxima are written into the hash-pinned
receipt and provider policy fingerprint. They are not chosen until the complete
run has been inspected.

Independent comparison uses the authenticated Motohashi v0.2.0 archive only at
mode–χ pairs that exactly overlap this lattice. The archive uses 2Mω and is
converted exactly to Mω by division by two. The receipt records the number and
coverage of comparisons, maximum frequency and A differences, archive hash,
dataset DOI, and license. Comparison never supplies or interpolates a catalog
row.

Validation establishes a converged, independently checked numerical catalog.
It is not interval arithmetic, a formal root enclosure, a continuum-operator
certificate, an EFT response, or a scientific conclusion. The spectral
artifact therefore keeps `formal_root_enclosure = false` and scientific state
`NOT_EVALUATED`.

## Packaged data and provenance

The package ships:

- `kerr_qnm_roots_2736.csv`;
- a canonical JSON computation/validation receipt;
- provenance for the migrated canonical continued-fraction and angular
  backend source blobs;
- the qnm MIT license and citation;
- Motohashi comparison attribution and CC BY 4.0 license;
- no 60 MB source archive, remote numerical cache, pickles, or build
  environment.

The receipt pins:

- generator source hash;
- canonical backend source commit and blob hashes plus numerical dependencies;
- qnm version, wheel SHA-256, and branch-continuation policy;
- Motohashi archive SHA-256 and DOI;
- exact rational lattice definition;
- solver convention, equations, continuation policy, tolerances, and
  truncations;
- 2,736-row CSV SHA-256;
- full-grid diagnostic maxima and counts;
- independent comparison coverage and maxima;
- operating system, Python version, and relevant library versions.

Loading fails closed on hash, canonical encoding, schema, key-set, count,
ordering, rational reduction, non-finite value, damping sign, diagnostic,
receipt, or validation mismatch.

## Provider behavior

The spectral provider admits exact catalog selection only.

- Supported theory: `general-relativity`.
- Supported convention: `kerr-mass-normalized-outgoing`.
- Supported branch: `schwarzschild-overtone-continuation`.
- One fixed gravitational identity; no polarization split.
- Unsupported mode–χ pairs fail structurally with no partial spectral artifact.
- Duplicate requested pairs fail.
- Warm identical requests reuse verified artifacts and execute zero providers.
- Cache hits and stored artifacts are revalidated against the same 2,736-row
  catalog contract.

The packaged CSV is the complete requested output. The existing request schema
may select supported Cartesian subsets. A mixed-ℓ full-catalog export is not
represented by inventing a global spin grid; the CLI export exposes the
packaged catalog as its own authenticated resource.

## Public status after PR #2

PR #2 admits two providers:

- problem contract;
- the computed 2,736-row pure-Kerr spectral core.

Every downstream capability remains unavailable and fails closed. PR #3 is the
M01 release-baseline migration. PR #4 begins linear response; it may consume
this background lattice but cannot add polarization or EFT rows to PR #2
retroactively.

## Acceptance criteria

- Exact key-set equality with the approved 2,736 keys.
- Per-ℓ counts 690, 966, and 1,080.
- Exactly 46 χ values for every ℓ=2,3 mode and 40 for every ℓ=4 mode.
- No duplicate 0.95 and no ℓ=4 high-spin extras.
- All 63 (ℓ,m,n) modes are complete, including negative and zero m.
- No catalog row is interpolated, extrapolated, or copied from the independent
  comparison dataset.
- Every row passes the declared full-grid numerical gates.
- Independent Motohashi comparisons pass at every exact overlap.
- Catalog and receipt bytes are canonical and hash-pinned.
- Provider, cache, verify, inspect, export, wheel, Ubuntu, and Windows tests
  pass.
- Current public status language contains 2,736 and no stale 91/819/728,
  2,520, or 5,508 scope claim.
- No scientific claim exceeds the numerical evidence described above.
