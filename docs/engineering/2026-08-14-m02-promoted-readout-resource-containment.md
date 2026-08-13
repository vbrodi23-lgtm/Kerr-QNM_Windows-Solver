# M02 promoted-readout resource containment

Date: 2026-08-14

## Incident benchmark

Leaf 13/212 (`221`, `a/M = 0.95`, `horizon-admittance`) exhausted 216 binary64 determinant evaluations in about 361 seconds, then entered the 80-decimal-digit Julia stage. After 5,271.5 seconds it remained in `PRIMARY`, Newton iteration 1, determinant 3, with no completed promoted root readout. The active homogeneous leg was `Xup_match_to_inner`; its active determinant had accumulated about 1.96 million radial RHS evaluations. The worker heartbeat remained healthy, with zero rejected ODE steps and zero nonlinear failures.

The observed determinant magnitude, about `3.83e1450`, is not itself classified as failure. The blocker is operational: an internally unbounded promoted readout can consume nearly the complete outer two-hour worker timeout before producing a structured result.

## Architectural diagnosis

- Python enforces a 7,200-second subprocess timeout, but the Julia request has no cooperative deadline.
- `solve_homogeneous_endpoint` sets `maxiters=Inf`; the existing ODE observation callback measures work but does not enforce limits.
- The first completed determinant is not used to decide whether the mandatory remaining determinant work can fit inside the request budget.
- An unsuccessful promoted `PRIMARY` proceeds into three diagnostic root phases even though the readout cannot be accepted.
- A typed worker timeout or resource limit escapes the per-leaf campaign loop and aborts the complete selection.
- Checkpoint schema version 3 authenticates scientific leaf records but has no append-only execution-attempt ledger.

## Containment design

### Operational resource identity

Every promoted request carries `windows-solver.execution-resource-policy/1`, containing the outer request deadline, an inner cooperative deadline, finite ODE `maxiters`, accepted-step and RHS-evaluation ceilings, and an optional per-leg wall-clock ceiling. Its canonical SHA-256 enters the Julia request digest and every control receipt. It is deliberately absent from campaign leaf IDs, root IDs, backend identity, numerical-policy identity, and solved-leaf scientific identity.

The default outer deadline remains 7,200 seconds. Julia's cooperative deadline is 120 seconds inside it. Operator overrides remain operational environment controls and generate a distinct resource-policy/request digest.

### Julia enforcement

The homogeneous ODE callback checks accepted steps, RHS evaluations, elapsed leg time, and elapsed request time on each accepted step. A reached ceiling emits a complete bounded ODE snapshot and throws a typed control exception. `maxiters` is finite and sourced from the same request policy.

After the first determinant, the root-readout guard multiplies its measured duration by the eight determinant evaluations still required by the immediately-convergent path: `+h`, `−h`, and the paired controls at `h/2`, `2h`, and `ih`. If that measured linear lower-bound estimate does not fit inside the remaining cooperative budget, Julia emits `root_readout_resource_infeasible` and exits without making a QNM existence or validity claim.

An unsuccessful promoted `PRIMARY` returns explicit `PRIMARY_NOT_CONVERGED` metadata with absent diagnostic roots/radii. `TRUNCATION`, `RESOLUTION`, and `SEED-PATH` remain unchanged for a successful primary.

### Python and campaign containment

Python maps only authenticated `CONTROL` receipts to `JuliaRootReadoutResourceLimitError`, `JuliaODEResourceLimitError`, or `JuliaWorkerTimeoutError`. Malformed, unknown, identity-invalid, or protocol-invalid responses remain fatal.
If the outer timeout still wins, its synthetic receipt incorporates the last validated Julia progress event, including the available readout/phase/determinant context and complete active ODE snapshot, instead of retaining only the process exit code.

The campaign catches only those three typed exceptions around a promoted stage. It preserves already committed stages, appends a content-digested execution-attempt record, writes the checkpoint atomically, emits `leaf_failed`, and advances to the next selected leaf. The deferred leaf has `computed = false`, cannot publish a solved-leaf receipt, and is retried only by a later explicit resume. Historical attempts remain append-only after a successful retry.

New checkpoints use the smallest versioned envelope extension for an attempt ledger. Existing schema-version-3 checkpoints remain loadable and are treated as having an empty attempt ledger.

### Reporting

The resource-failure CSV and status JSON expose leaf identity, readout/phase/determinant location, elapsed time, limiting resource, ODE counters, policy identity, and retry status. Dashboard counters separate numerical nonconvergence, resource limits, worker timeouts, and fatal protocol/control failures. Deferred execution does not increment the completed-scientific-leaf count.

## Evidence ceiling

This change is validated only by Python tests with fake/synthetic worker responses, source compilation, static Julia/Python contract checks, and TaskPlanner validation. It does not execute Julia, a Kerr determinant, `m02.ps1`, or any 80/120-digit scientific payload. Native performance and physical correctness remain TASK-076 evidence.

## Scientific invariants

No determinant equation, GSN/Teukolsky construction, radial endpoint, ODE tolerance, endpoint series order, angular padding, finite-difference step, Newton tolerance/trust/damping rule, branch radius, amplitude ladder, precision-promotion rule, mechanism, leaf/root ID, backend identity, or scientific policy SHA changes in this containment work.

For the incident leaf, direct comparison with `main` retains leaf ID `b-prime-leaf-28b8e2f139fae4ebbb839320057a127429f7a01a3cc2cac60b526815ad0e7252`, solved-leaf scientific identity `6c957f09f6003e541468721fd8773d9f57360ce82a2250d1d2dd92e964f23bfe`, numerical-policy identity `2d7cee336c6126a11bccd652ee35e73de60837e9418476849b9026cd27bf6171`, and backend identity `035f123f04d02079c6e7d7bed5255069c6152d53be266185b303af8c48c36f5c` exactly. Only the operational Julia request/cache digest changes with the execution-resource policy.

## Deferred mathematical redesign

- TODO: [HUMAN MATH REVIEW REQUIRED - derive a regularized overtone radial state and determinant/scattering reconstruction before replacing raw Xup propagation]
- TODO: [HUMAN MATH REVIEW REQUIRED - derive an exact ω-sensitivity system including angular-eigenvalue dependence before replacing finite-difference determinant derivatives]
