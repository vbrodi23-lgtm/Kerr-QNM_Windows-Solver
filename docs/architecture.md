# Architecture

## Scientific dependency graph

The public architecture is a directed acyclic graph. It encodes required computed inputs, not a serial user workflow.

| Capability | Direct computed inputs |
|---|---|
| Problem contract | — |
| Spectral core | Problem contract |
| Linear response | Spectral core |
| Operator stability | Spectral core |
| Quadratic ringdown | Spectral core |
| Response matrix | Linear response, quadratic ringdown |
| Inverse inference | Response matrix |
| Signals | Response matrix |
| Detector inference | Signals |
| Evidence package | Operator stability, inverse inference, detector inference |

After the spectral core, linear response, operator stability, and quadratic ringdown are independent. The planner selects the transitive dependency closure of the requested target and emits a deterministic topological order.

## Problem identity

Every study fixes:

- target capability;
- theory or mechanism identity;
- convention identity;
- `ModeKey = (s, ell, m, n, branch, polarization)` values;
- dimensionless Kerr spins `−1 < a_over_m < 1`;
- evidence profile;
- numerical policy.

Top-level numerical-policy keys named for capabilities are local policy
namespaces; all other keys are global. Before executing a provider, the engine
replaces the user-facing target with that provider's capability and removes
other capabilities' local policy namespaces. The sealed run keeps the full
original request. This makes an upstream artifact reusable across downstream
targets without losing run-level provenance.

Different boundary laws, gauges, normalizations, source definitions, or mechanism conventions remain different requests. They cannot share a provider identity or be combined by relabelling.

## Provider ownership

Exactly one active production provider owns each capability. A provider declares its stable ID, implementation version, equation and convention IDs, runtime and numerical-policy fingerprints, ordered upstream artifact types, output artifact type, availability, and evidence level. Before execution, the engine requires those upstream types to match the direct DAG inputs exactly.

The engine snapshots every provider descriptor before any provider executes and
uses that immutable snapshot for cache identity, input types, and output type.
A provider cannot change its contract mid-run. Before recording `SUCCEEDED`,
the engine runs the same research-integrity verification exposed by the CLI.

A provider is admitted only with:

1. an exact public input/output contract;
2. declared equations, boundary conditions, gauge, normalization, units, and domain;
3. validation fixtures with independent expected values;
4. numerical acceptance and failure criteria;
5. a documented evidence ceiling;
6. provenance and dependency licenses;
7. native-Windows and Ubuntu test coverage where the backend supports both.

Missing providers fail before partial execution. Test fixtures are never registered as production providers.

## Artifact identity and caching

The artifact SHA-256 covers canonical JSON containing:

- schema and artifact type;
- capability;
- provider, equation, convention, runtime, and policy fingerprints;
- the canonical request scoped to that capability;
- ordered direct-upstream artifact identities;
- payload;
- evidence state.

Artifact, cache-binding, and run files must equal their canonical UTF-8 JSON
encoding byte for byte. Duplicate object keys, non-finite numbers, alternate
encodings, and representation changes are rejected before identity checking,
preventing different JSON parsers from interpreting one stored file differently.

A separate computation key maps the inputs and provider fingerprint to the resulting content identity. Cache reuse loads the artifact, verifies its content hash, recomputes that key from the artifact's capability, provider, request, and ordered upstream identities, and requires an exact match. Atomic replacement prevents partially written artifacts or bindings from becoming visible.

Changing a downstream inference policy does not invalidate spectrum artifacts. It invalidates that capability and descendants reached through changed upstream identities. Changing a convention, equation, runtime fingerprint, relevant numerical policy, or upstream artifact produces a different identity.

Artifact provider, request, and payload mappings are deep immutable snapshots
in memory. A downstream provider cannot mutate an upstream artifact after its
identity is computed and then claim lineage to the original persisted value.

## Evidence model

Every artifact records four independent dimensions:

| Dimension | States |
|---|---|
| Carrier | `VALID`, `INVALID`, `NOT_APPLICABLE` |
| Execution | `NOT_RUN`, `RUNNING`, `SUCCEEDED`, `FAILED` |
| Numerical | `NOT_EVALUATED`, `CONVERGED`, `ACCEPTED`, `REJECTED`, `UNRESOLVED` |
| Scientific | `NOT_EVALUATED`, `SUPPORTED`, `CONDITIONALLY_SUPPORTED`, `FRAGILE`, `UNRESOLVED`, `CONTRADICTED` |

No downstream claim may exceed the weakest upstream evidence. Rejection and contradiction propagate as adverse results; unevaluated, unresolved, converged, fragile, and conditional states act as evidence ceilings. Invalid or failed carriers cannot become successful downstream artifacts. Residual validation is not a formal root enclosure. A pole-frequency result is not a waveform, detector, or quadratic-amplitude result.

## Storage layout

```text
STORE/
  artifacts/<artifact-sha256>.json
  cache/<computation-sha256>.json
  runs/<run-id>.json
```

`solver export` writes a self-contained JSON package with the run record and every artifact referenced by that run.

Run records include a SHA-256 over their canonical metadata. Verification also
reconstructs the requested plan and requires a complete capability-to-artifact
closure, exact direct-upstream lineage, the expected capability-scoped request,
provider type agreement, consistent execution accounting, and target evidence equality.
The digest detects unsealed modification; closure verification rejects a
malformed record even if someone recomputes its digest.

The research profile applies these integrity checks to any completed target.
The publication profile additionally requires the full evidence-package target
and evaluated numerical and scientific states. `UNRESOLVED` and
`CONTRADICTED` remain publishable evidence outcomes when their record is intact.
