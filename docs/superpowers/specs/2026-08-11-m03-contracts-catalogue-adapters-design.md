# M03 Contracts and Catalogue Adapters Design

**Date:** 2026-08-11  
**Scope:** TASK-012 only  
**Status:** Approved implementation boundary

## Goal

Create the non-numerical M03 contract layer that converts admitted spectral-root
payloads into stable M03 seed identities and defines the evidence carriers needed
by later field, co-mode, residue, genealogy, classification, NHEK, cache, and
admission work.

## Boundary

This change does not compute a field, co-mode, residue, classification, or NHEK
match. It does not register an M03 provider or alter the admitted spectral
provider. M02 remains the active programme milestone until its 212-leaf campaign
and closure gates complete.

The authoritative root source is the admitted spectral payload built from the
immutable 2,736-root catalogue plus the authenticated 44-root exact-selector
overlay. M02 solved-leaf receipts may add cross-milestone lineage only when their
root identity, root reference, exact coordinate, equation, backend, and policy
identities are explicit. M02 response values never become spectral-field or
residue evidence.

## Architecture

Add one standard-library module, `windows_solver.m03_contracts`, with three
responsibilities:

1. validate and adapt an admitted spectral payload into canonical M03 root seeds;
2. optionally validate and attach an M02 solved-leaf lineage anchor;
3. define immutable, canonical contract records for later M03 evidence and cache
   identity.

No new capability is added to the DAG. No built-in provider is registered.

## Canonical root seed

Each seed binds:

- mode: s, ℓ, m, n, branch, polarization;
- exact spin identity when supplied by the base catalogue;
- binary64 spin identity for both base and overlay roots;
- Mω and angular separation constant A;
- admitted catalogue and overlay hashes;
- source realization: `base-catalogue` or `exact-selector-overlay`;
- a SHA-256 over canonical JSON identity material.

Exact-selector roots are identified from `source_coordinate` and
`spin_binary64_ratio`. Base roots are identified from `spin_exact`.
Ambiguous or malformed roots fail closed.

## M02 lineage anchor

An optional lineage anchor accepts only schema-version-1 solved-leaf receipts
whose terminal state is one of `PRODUCED`, `UNRESOLVED`, `REJECTED`, or
`FAILED`. It records the receipt hash, canonical leaf-record hash, scientific
computation identity, root identity, root reference, exact sampling coordinate,
equation identity, backend identity, and policy identity.

For `PRODUCED` receipts, the nested result lineage must be complete. Other
terminal states may have no result payload and remain outcome-neutral. The
anchor never promotes M02 numerical or scientific state into M03.

## M03 artifact contracts

The module defines exact artifact kinds and evidence states for:

- radial/angular field;
- co-mode and normalization;
- pole residue;
- κ-genealogy;
- ZDM/DM classification;
- NHEK match;
- provider admission.

Every contract envelope binds a root-seed identity, equation and convention
versions, backend revisions, precision, numerical policy, payload, evidence
state, and blockers.

The following start fail-closed because the governing mathematics is not frozen:

- co-mode/normalization:
  `HUMAN_MATH_REVIEW_REQUIRED: freeze the separated adjoint equation, pairing, phase convention, and normalization identity`;
- pole residue:
  `HUMAN_MATH_REVIEW_REQUIRED: derive the Green-function numerator, determinant derivative, source, and readout conventions`;
- ZDM/DM classification:
  `HUMAN_MATH_REVIEW_REQUIRED: freeze classification observables, κ-domain, uncertainty model, and transition policy`;
- NHEK matching:
  `HUMAN_MATH_REVIEW_REQUIRED: supply the matched-asymptotic formula, overlap region, convention map, and error model`.

A blocked envelope cannot claim `PRODUCED` or `ADMITTED`.

## Cache identity

The cache key binds:

- root-seed identity;
- artifact kind;
- equation and convention versions;
- radial and angular grids;
- normalization and pairing IDs;
- backend revisions;
- precision;
- validation-policy identity;
- optional M02 lineage identity.

Changing any bound item changes the canonical cache SHA-256.

## Verification

Tests use synthetic admitted spectral payloads shaped exactly like the current
provider output and a sanitized M02 receipt shaped like the attached production
receipts. They prove:

- base and overlay roots adapt deterministically;
- malformed and ambiguous roots fail closed;
- M02 anchors preserve lineage without importing response values;
- cache identities change when bound conventions change;
- blocked mathematical contracts cannot be promoted;
- produced field/genealogy envelopes require complete validation payloads.

Only standard-library unit tests and Python compilation are permitted in this
change. No solver, Julia worker, determinant, continuation, or mathematical
campaign is executed.
