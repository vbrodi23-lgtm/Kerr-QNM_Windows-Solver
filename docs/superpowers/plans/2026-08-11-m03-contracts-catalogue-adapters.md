# M03 Contracts and Catalogue Adapters Implementation Plan

> **Implementation result:** the contract-only slice described here merged in
> PR #30. Its unchecked boxes preserve the plan-at-authoring state and are not
> live task status. TASK-012 remains in Backlog because PR #30 deliberately did
> not reconcile admitted M02 lineage, specify the complete numerical field and
> compactification contract, reuse the field backend, or clear human-math
> blockers.

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the TASK-012 standard-library contract layer that adapts admitted
spectral payloads into canonical M03 seed identities and defines fail-closed
evidence/cache contracts for later M03 work.

**Architecture:** A standalone `windows_solver.m03_contracts` module consumes
the current spectral provider's public payload mapping. It has no dependency on
the numerical backend and is not registered as a provider. Immutable dataclasses
validate mappings, derive canonical SHA-256 identities, and enforce mathematical
blockers.

**Tech Stack:** CPython 3.12 standard library, dataclasses, enum, hashlib, JSON,
unittest.

## Global Constraints

- Do not execute solver scripts, Julia workers, determinants, continuations, or
  mathematical campaigns.
- Do not modify `builtin.py`, the capability DAG, M02 code, spectral catalogue
  data, or current provider admission.
- The admitted spectral payload remains the authoritative root source.
- M02 solved-leaf receipts remain `UNRECONCILED` until an explicit public
  reconciliation artifact exists.
- Co-mode, residue, ZDM/DM, and NHEK mathematics fail closed with exact
  human-review blockers.
- Runtime dependencies remain empty.

---

### Task 1: Adapt admitted spectral roots

**Files:**
- Create: `tests/test_m03_contracts.py`
- Create: `src/windows_solver/m03_contracts.py`

**Interfaces:**
- Consumes: `adapt_spectral_payload(payload: Mapping[str, object])`
- Produces: `tuple[M03RootSeed, ...]`, each with `identity_sha256` and
  `to_mapping()`.

- [ ] **Step 1: Write failing base/overlay adaptor tests**

Create literal current-provider root mappings. Assert a base root produces
`source_realization == "base-catalogue"`, an overlay root produces
`source_realization == "exact-selector-overlay"`, identity digests are 64
lowercase hexadecimal characters, and repeated adaptation is byte-identical.

- [ ] **Step 2: Run the focused tests and observe RED**

Run:

```text
PYTHONPATH=src python -m unittest tests.test_m03_contracts.M03CatalogAdapterTests -v
```

Expected: import failure because `windows_solver.m03_contracts` does not exist.

- [ ] **Step 3: Implement the minimum adaptor**

Implement:

```python
@dataclass(frozen=True, slots=True)
class M03RootSeed:
    mode: Mapping[str, object]
    source_realization: str
    spin: float
    spin_identity: Mapping[str, object]
    spin_binary64_hex: str
    frequency: Mapping[str, object]
    angular_separation_constant_A: Mapping[str, object]
    catalog_id: str
    catalog_data_sha256: str
    overlay_data_sha256: str
    identity_sha256: str

    @classmethod
    def from_spectral_root(
        cls,
        root: Mapping[str, object],
        *,
        catalog_id: str,
        catalog_data_sha256: str,
        overlay_data_sha256: str,
    ) -> "M03RootSeed": ...

def adapt_spectral_payload(
    payload: Mapping[str, object],
) -> tuple[M03RootSeed, ...]: ...
```

Validate finite damped Mω, finite A, exact mode fields, canonical binary64 hex,
base/overlay exclusivity, requested-root count, and duplicate identities.

- [ ] **Step 4: Run focused tests and observe GREEN**

Run the same unittest command. Expected: all adaptor tests pass.

### Task 2: Preserve M02 lineage and derive cache identities

**Files:**
- Modify: `tests/test_m03_contracts.py`
- Modify: `src/windows_solver/m03_contracts.py`

**Interfaces:**
- Consumes:
  `M02LineageAnchor.from_receipt(receipt: Mapping[str, object])`
- Produces:
  `M02LineageAnchor` with `reconciliation_state == "UNRECONCILED"`;
  `M03CacheIdentity.build(...)` with canonical `cache_sha256`.

- [ ] **Step 1: Add failing receipt and cache tests**

Use a sanitized literal shaped like an attached production M02 receipt. Assert
the anchor retains receipt/record/computation/root/equation/backend/policy
identities and exact coordinate, excludes response values, and remains
`UNRECONCILED`. Assert changing `pairing_id` changes `cache_sha256`.

- [ ] **Step 2: Run the focused tests and observe RED**

Expected: missing `M02LineageAnchor` and `M03CacheIdentity`.

- [ ] **Step 3: Implement immutable lineage and cache records**

The cache build interface is:

```python
M03CacheIdentity.build(
    seed=seed,
    artifact_kind=M03ArtifactKind.RADIAL_ANGULAR_FIELD,
    equation_version="...",
    convention_version="...",
    radial_grid={"...": "..."},
    angular_grid={"...": "..."},
    normalization_id="...",
    pairing_id="...",
    backend_revisions={"...": "..."},
    precision_digits=64,
    validation_policy={"...": "..."},
    reconciled_m02_lineage_sha256=None,
)
```

Reject non-finite values, non-positive precision, malformed hashes, empty IDs,
and any M02 lineage hash that is supplied without explicit reconciliation.

- [ ] **Step 4: Run focused tests and observe GREEN**

Run the receipt/cache test class. Expected: all tests pass.

### Task 3: Enforce M03 mathematical blockers

**Files:**
- Modify: `tests/test_m03_contracts.py`
- Modify: `src/windows_solver/m03_contracts.py`

**Interfaces:**
- Consumes:
  `build_m03_envelope(kind, seed, cache_identity, evidence_state, payload)`
- Produces:
  `M03ArtifactEnvelope` or a fail-closed `ValueError`.

- [ ] **Step 1: Add failing blocker and validation tests**

Assert co-mode, residue, branch-classification, and NHEK envelopes reject
`PRODUCED` and `ADMITTED`. Assert field and κ-genealogy envelopes accept
`PRODUCED` only when their exact validation fields are present. Assert no
artifact can be `ADMITTED` through this TASK-012 layer.

- [ ] **Step 2: Run focused tests and observe RED**

Expected: missing artifact-kind, evidence-state, and envelope APIs.

- [ ] **Step 3: Implement contract registry and envelope validation**

Use enums for artifact kinds/evidence states and a literal contract registry.
The required blocker strings are copied from the design spec. Field validation
requires equation residual, horizon/infinity boundary residuals, Wronskian
drift, and resolution comparison. Genealogy validation requires nonzero
node/edge counts, overlap guards, continuation invariants, and exact-node
polish. Other produced states fail closed.

- [ ] **Step 4: Run focused tests and observe GREEN**

Run:

```text
PYTHONPATH=src python -m unittest tests.test_m03_contracts -v
```

Expected: all M03 contract tests pass.

### Task 4: Verify the non-solver slice

**Files:**
- Review:
  `src/windows_solver/m03_contracts.py`
  `tests/test_m03_contracts.py`
  `docs/superpowers/specs/2026-08-11-m03-contracts-catalogue-adapters-design.md`

- [ ] **Step 1: Compile only Python source/tests**

Run:

```text
python -m compileall -q src/windows_solver/m03_contracts.py tests/test_m03_contracts.py
```

Expected: exit 0.

- [ ] **Step 2: Run the focused unit suite**

Run:

```text
PYTHONPATH=src python -m unittest tests.test_m03_contracts -v
```

Expected: zero failures.

- [ ] **Step 3: Inspect the diff against scope**

Confirm no provider registration, DAG, M02 runtime, spectral data, Julia, or
PowerShell file changed.

- [ ] **Step 4: Commit and open a draft PR**

Commit the exact scoped files, push
`agent/m03-contracts-catalogue-adapters`, and open a draft PR against
`main`. The PR must disclose that full-repository CI and mathematical
execution are not local verification claims.
