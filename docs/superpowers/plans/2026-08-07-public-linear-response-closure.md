# Public linear-response closure implementation plan

**Goal:** Admit one evidence-bound provider for physical first-order complex QNM
frequency shifts over the frozen M02 domain.

**Architecture:** Add a strict contract module first, then migrate numerical
  work behind it in independently verifiable slices. Keep the descriptor
unavailable until the complete component-local artifact and projective ledger
pass the admission gates. The spectrum artifact remains the sole upstream
production capability, but its exact high-spin domain must be extended before
full M02 closure.

**Runtime:** CPython 3.12 standard library for the installed contract/provider;
pinned NumPy and SciPy are offline numerical-test dependencies.

---

## Slice 1 — TASK-006: contract and descriptor

**Files**

- Create `src/windows_solver/linear_response.py`.
- Create `tests/test_linear_response_contract.py`.
- Create `examples/linear-response.json`.
- Modify `src/windows_solver/payload_validation.py`.
- Modify public architecture/status documentation only where the contract
  boundary changes.

**Red gate**

Add tests for descriptor identity, unavailable registry state, exact request
selection, direct-spin and exact surface-gravity sampling, supported
mechanism/coordinate pairs, mechanism/theory rules,
component-local covariance/disks, cross-component covariance blocks,
unresolved results, aligned projective vectors, lineage, completeness,
admission, and the example study. Run the focused module and
observe import or assertion failure before production code is added.

**Green gate**

Implement immutable mechanism contracts and strict validators. Dispatch
linear-response payload verification without registering the provider. Run the
focused module, full suite, board validator, and release-manifest validator.

## Slice 2 — TASK-007: independent golden fixtures

Authenticate the retained component-local pilot and parity-even cubic `220`
benchmarks. Select overlap rows plus adverse rows, normalize identifiers without
altering values, record SHA-256 receipts, and prove the production package does
not import fixture code. Do not use global-cover rows as local uncertainty.

## Slice 3 — TASK-008: one end-to-end `220` computation

Migrate the simple-root determinant response for one manifest coordinate.
Consume the spectrum artifact, reproduce the independent golden disk, bind
determinant and convention identities, seal the result, and prove zero-work
verified cache reuse. Test determinant scaling and finite-amplitude tangency.

Before frozen-domain expansion, extend the admitted spectral input for exact
high-spin coordinates absent from the current catalog. Preserve its provider
ownership and admission gates; do not synthesize or interpolate missing roots.

## Slice 4 — TASK-009: frozen-domain expansion

Enumerate exact mode × spin × mechanism leaves from the manifest. Compute in
resumable batches, retaining determinant derivative, baseline residual,
signed-root ladder, refinement, branch, and failure diagnostics per leaf. Audit
that every required leaf is produced or that the milestone remains open;
uncomputed leaves are never labelled scientific uncertainty.

## Slice 5 — TASK-010: correlated uncertainty

Propagate signed-root errors through real- and imaginary-axis centred
differences and Richardson combinations. Store the resulting component-local
covariance and disks, validate positive semidefiniteness, and audit coverage on
holdout/refinement discrepancies. Reject atlas-wide worst-case substitution.

## Slice 6 — TASK-011: projective ledger and admission

Compute projective quantities only from component-local rows. Enforce exact
calibration cancellation, proportionality-minor identities, scale/phase
invariance, and unbounded classification when the calibration disk contains
zero. Once no computation/evidence blocker remains, set one provider available,
register it, update the manifest and evidence ceiling, and run Windows, Ubuntu,
cold/warm-cache, export, and research-verification gates.

## Delivery controls

Each slice has one TaskPlanner owner and explicit commands. Every red test is
observed before implementation, every green claim is backed by fresh command
output, and each transition records artifact or PR evidence in Notion. PR #4
may remain draft while later numerical slices are incomplete; it must not claim
M02 closure before TASK-011 is done.
