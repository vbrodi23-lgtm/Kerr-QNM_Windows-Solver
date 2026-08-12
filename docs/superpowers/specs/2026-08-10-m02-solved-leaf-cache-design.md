# M02 Authenticated Solved-Leaf Cache Design

> **Historical implementation record.** PR #21 later replaced the 553-leaf
> production contract referenced below with the canonical 212-leaf,
> 48-selector campaign and 57-row reduction contract. The cache trust and
> identity design remains a record of the implemented boundary; current status
> and counts come from `.tasks/`, `README.md`, and the release manifest.

## Purpose

M02 may reuse a complete terminal leaf record that the same scientific contract has already originated and certified. The cache is optional acceleration: deleting it must leave cold campaign execution fully functional.

## Trust boundary

The active `m02-campaign-checkpoint.json` remains the record of the current run. The private cache stores one independently authenticated `CampaignLeafRecord` per scientific-computation identity. Cache lookup never substitutes a replay backend, partial readout, determinant value, or final response scalar.

A hit is accepted only after parsing the canonical record, recomputing its `record_sha256` and every `stage_sha256`, checking the outer receipt, and running the current campaign semantic validator for the exact leaf. Only terminal `PRODUCED` and `UNRESOLVED` records are cacheable.

## Identity separation

The scientific-computation identity binds:

- the exact `CampaignLeafPlan` and `ResponseComponentJob`, including coordinates, role, mode, spin, mechanism, root/branch, equation, source-root mapping, policy, and backend scientific identity;
- the precision backend capabilities and precision-factory identity;
- the current deep-leaf promotion gates and fixed-sentinel contract.

It deliberately excludes campaign selection membership, ordered campaign prefix, checkpoint path, progress/dashboard rendering, PowerShell presentation, and full campaign-source hashes. The evidence-record identity remains the canonical leaf `record_sha256` plus the stage digests already inside that record.

## Store

The default Windows root is a schema-one `solved-leaves` directory below `%LOCALAPPDATA%\Kerr-QNM_Windows-Solver`. Tests and operators may override it explicitly. One JSON receipt is stored per scientific identity. Filenames are lookup hints only; every field is recomputed on read.

Receipts contain the schema, scientific identity, leaf ID, complete canonical leaf record, canonical record digest, terminal state, stage count, creation timestamp, and source type. Writes use an exclusive lock and atomic replacement. Existing corrupt evidence is quarantined rather than silently overwritten.

## Execution ordering

At startup, compatible selected leaves are authenticated. Existing current-checkpoint records take precedence. Compatible cache records are inserted into the current checkpoint in canonical selection order and emit `LEAF_REUSED` without constructing or calling the numerical backend for those leaves.

For a miss, stale entry, or corrupt entry, the normal originating solver runs. Once a record is terminal and semantically valid, the active campaign checkpoint is atomically written first. Cache publication follows. Publication failure is reported but cannot invalidate or discard the checkpointed result.

## Import

The checkpoint importer reuses checkpoint envelope parsing, canonical records hashing, leaf/stage parsing, ordering checks, and semantic validation. It accepts terminal records independently. It does not infer completion from selection membership or progress/status events. Operationally stale whole-campaign bindings do not invalidate a leaf whose current scientific identity and semantics still match.

## Scope

This change does not alter Kerr equations, tolerances, refinement, root solving, or the 553-leaf campaign. It implements completed-leaf reuse only; determinant, root-readout, epsilon-level, and partial-stage memoisation remain out of scope.
