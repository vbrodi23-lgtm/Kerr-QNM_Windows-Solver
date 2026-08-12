# M02 Package-Local Julia Runtime Design

> **Historical implementation record.** PR #13 moved the default runtime from
> checkout-local `.runtime` storage to the versioned per-user managed root, and
> PR #21 replaced the 553-leaf campaign with the canonical 212-leaf,
> 48-selector campaign and 57-row reduction contract. Use `README.md`,
> `docs/response-replay-powershell.md`, and the release manifest for current
> behavior; the original design below is retained as provenance.

**Status:** Approved for implementation on 2026-08-09.

## Goal

A fresh Windows checkout can launch the complete M02 campaign from PowerShell
without a historic F/U cache, an external precision backend, a system Julia
installation, or pre-known scientific-source hashes. The existing campaign
checkpoint, resume, reduction, validation, and admission contracts remain the
owners of orchestration and evidence.

## Runtime boundary

`runtime/bootstrap.ps1 -WithM02` provisions the numerical Python tier and a
portable Julia 1.10.11 under `.runtime`. It copies the repository-owned Julia
project and vendored `GeneralizedSasakiNakamura.jl` and
`SpinWeightedSpheroidalHarmonics.jl` sources into runtime-local paths, resolves
the declared package environment, precompiles it, and performs a package-load
probe. The probe does no determinant or scientific solve.

`m02.ps1` is the operator entry point. It bootstraps when required, uses
`campaign-run` for a new checkpoint, uses `campaign-resume` for an existing
checkpoint, and finishes with `campaign-validate --full`. The default selection
contains all 553 leaves and declares binary64, 80-digit, and 120-digit stages.

## GSN coefficient identity

The development registry is `.runtime/generated/gsn/gsn-index.json`. Each row
maps one canonical scientific identity to one short artifact ID such as
`gsn-000001`.

Canonical identity contains:

- spin weight;
- resolved `a/M`: the exact rational for a direct-spin leaf, or the exact
  integer-ratio representation of the binary64 campaign spin for a κ-derived
  leaf;
- the canonical binary64 `a/M` consumed by the campaign;
- azimuthal index `m`;
- mass normalization;
- GSN equation convention;
- producer contract version;
- consumer contract version.

The original campaign coordinate is retained separately. For a near-extremal
leaf this includes the exact `M−κ` numerator and denominator, coordinate name,
and transformation ID. The required transformation is

`a/M = sqrt(1 - 4 Mκ) / (1 - 2 Mκ)`.

Because this value is generally irrational for rational `Mκ`, Julia receives
the exact rational representation of the already-resolved campaign binary64
spin while the exact `Mκ` source remains attached as origin metadata.
Coordinate representation does not split records that resolve to the same
physical binary64 spin identity.

Artifacts are pair-level, not selection-level. A campaign requesting pairs A
and B reuses the same A record later when only A is requested. Ordering cannot
create a second identity. A small assembled cache is recreated from validated
pair records for the existing `_native_sn_standard.py` consumer; it is not the
owner of scientific identity.

## Generation and validation

The Julia producer reads one exact rational pair request, calls the vendored
`Potentials.sF` and `Potentials.sU` equations with exact symbolic rational
algebra, validates generated values against direct equation evaluation, and
writes the consumer coefficient schema. Python accepts a record only when:

- producer and consumer contract fields match the running software;
- spin weight, normalization, equation convention, exact spin, binary64 spin,
  and `m` match the indexed identity;
- the artifact contains exactly one requested F/U record;
- every numerator and denominator coefficient array is nonempty text;
- the producer status reports one accepted pair and all direct checks accepted.

Reuse performs these checks against the artifact itself every time. Index or
status metadata alone never authorizes a record. Missing or invalid artifacts
regenerate under the same logical ID. Source and artifact hashes are measured
and recorded as observations, but byte changes do not block development
execution while the mathematical contract version remains unchanged.

## Failure and concurrency behavior

Index loading rejects duplicate JSON keys, duplicate logical identities,
duplicate artifact IDs, inconsistent filename bindings, noncanonical exact and
binary64 spin pairs, and malformed observation metadata. Index replacement is
atomic and preserves the prior valid bytes as `gsn-index.previous.json`.

An atomic runtime lock serializes index allocation across PowerShell processes.
Each accepted pair is added to the index immediately, so a later producer
failure cannot discard earlier successful records. If an artifact is deleted,
its indexed ID is regenerated. If the index is deleted while artifacts survive,
allocation scans surviving short IDs, preserves their files, and regenerates
the requested identity under the next ID. A corrupt present index fails with an
explicit error and retains the previous-index copy for diagnosis.

`.\m02.ps1 -RebuildRuntime` is the development cleanup path. It removes and
reprovisions `.runtime` while leaving the campaign checkpoint outside that
directory intact.

## Precision backend

Binary64 continues through the existing Python native GSN adapter. Promoted
80/120-digit stages use the package-owned Julia worker behind the same root
readout interface consumed by `run_component`. The worker derives angular and
radial quantities at the requested working precision and returns primary,
endpoint-refined, resolution-refined, and alternate-seed roots. Existing
campaign code remains responsible for signed amplitude reduction, precision
ladder discrepancies, checkpoint sealing, resume, and admission.

## Development and release boundary

This design makes mathematical execution and structural compatibility the
development gate. Portable-runtime archive digests remain download-integrity
checks. Scientific source, generated artifact, worker, and manifest hashes are
recorded as provenance observations.

After the user completes the real Windows campaign, a separate
provenance-hardening pass may pin the stable release identities and strengthen
checkpoint tamper policy. That work must not replace or delay the executable
physics path.

## Verification boundary

Developer verification may compile Python, exercise mocked subprocess
boundaries, materialize the 553-leaf plan, test PowerShell surface text, build
the package, and run non-scientific orchestration tests. The developer does not
run the Julia producer or determinant locally. The user executes the physical
campaign on Windows and returns logs for any required repair.
