# M03 Contracts and Catalogue Adapters Design

**Date:** 2026-08-11  
**Scope:** TASK-012 only  
**Status:** Contract-only slice merged in PR #30; full TASK-012 remains blocked
pending M02 admission/reconciliation, complete field/compactification contracts,
backend reuse, and the declared human-mathematics gates.

## Goal

Create the non-numerical M03 contract layer that converts already-admitted
spectral-root payloads into stable M03 seed identities and defines evidence and
cache carriers for later M03 work.

## Boundary

This change does not compute a field, co-mode, residue, classification, or NHEK
match. It does not register an M03 provider, alter the capability DAG, or admit
artifacts. Its input precondition is a payload already validated by the spectral
provider. Future integration must call it only after
`spectrum.validate_spectral_payload` succeeds.

The authoritative root source is the admitted 2,736-root catalogue plus the
authenticated 44-root exact-selector overlay. M02 solved-leaf receipts may add
lineage only when their identities and coordinate are explicit. M02 response
values and baseline frequencies never become M03 evidence.

## Architecture

Add one standard-library module, `windows_solver.m03_contracts`, with three
responsibilities:

1. adapt an already-admitted spectral payload into canonical M03 root seeds;
2. authenticate an optional M02 solved-leaf lineage anchor while leaving it
   `UNRECONCILED`;
3. define factory-only immutable cache and artifact-envelope records.

No built-in provider or second provider-envelope API is introduced.

## Canonical root seed

Each seed binds the exact admitted mode domain, spin realization, damped Mω,
angular separation constant A, catalogue/overlay hashes, and canonical SHA-256.
Base roots use `spin_exact`; overlay roots use `source_coordinate` and
`spin_binary64_ratio`. The adapter validates canonical binary64 identity,
base/overlay exclusivity, finite values, requested count, and duplicate seeds.

## M02 lineage anchor

Only schema-version-1 solved-leaf receipts with terminal state `PRODUCED` or
`UNRESOLVED` are accepted. `REJECTED` and `FAILED` are checkpoint-only states,
not solved-leaf cache receipts.

The anchor authenticates the receipt and canonical record hashes. It preserves
receipt, computation, root/reference, equation, backend, policy, and exact
sampling-coordinate identities. It excludes response values and baseline ω.
For `PRODUCED`, nested lineage must be complete and agree with its baseline root
reference and equation.

Every imported anchor remains `UNRECONCILED`; no current factory can bind it to
an M03 cache key. A future public reconciliation artifact must define that
transition explicitly.

## Precision compatibility

Cache identities consume the merged `precision_tier_presentation()` contract.
Legacy 64 means IEEE-754 binary64 (about 15.95 decimal digits), while 80 and 120
mean BigFloat tiers. A forged or inconsistent presentation is rejected.

## Artifact contracts

Exact artifact IDs include `co-mode-normalization` and `kappa-genealogy`.
No TASK-012 artifact can claim `ADMITTED`. Co-mode, residue, ZDM/DM
classification, and NHEK matching cannot claim `PRODUCED` until the exact
human-math blockers in the registry are resolved. Provider admission remains
blocked upstream.

`PRODUCED` field evidence is accepted only when its exact residual, boundary,
Wronskian-drift, and resolution-comparison schema satisfies its exact validation
policy. `PRODUCED` genealogy evidence requires nonzero nodes and edges, overlap
guards, branch-resolved continuation invariants, and exact-node polish satisfying
policy. Cyclic genealogy graphs are permitted.

## Cache identity

The canonical cache SHA-256 binds seed, artifact kind, equation/convention
versions, grids, normalization/pairing IDs, backend revisions, canonical
precision tier, validation policy, and an optional explicitly reconciled M02
lineage identity. JSON inputs must have string keys and finite values.

## Verification

Structural tests cover deterministic base/overlay adaptation, receipt/hash
authentication, lineage exclusions, canonical precision, convention-sensitive
cache identity, factory-only construction, exact blockers, non-admission, and
policy-bound field/genealogy evidence. The supplied archive of 24 solved-leaf
receipts is authenticated structurally.

Only focused standard-library tests and in-memory Python compilation are local
verification claims. No solver, Julia worker, determinant, continuation, or
mathematical campaign is executed.
