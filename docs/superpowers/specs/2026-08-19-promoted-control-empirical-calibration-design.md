# Promoted-Control Empirical Calibration Design

## Authority and readiness boundary

This design records the operator decision supplied on 2026-08-19. It makes
promoted M02 calculation runnable through the native PowerShell path; it does
not make a publication or final scientific-admission claim.

The committed receipt is `promoted-control-empirical-calibration/v1`. It is
explicitly empirical, operator-approved, and derived from authenticated
production evidence. It is neither interval arithmetic nor an independent
mathematical proof. Independent mathematical review remains a separate,
admission/publication-only gate.

Binary64 is deliberately outside this receipt. Existing binary64 evidence and
its cache identity remain reusable.

## Receipt and negative-provenance contract

The canonical JSON receipt has a strict, versioned schema and a module-pinned
SHA-256 of its canonical bytes. It contains exactly five family/tier budget
entries:

| Determinant family | Tier |
| --- | --- |
| exterior Wronskian | BigFloat-40 |
| exterior Wronskian | BigFloat-80 |
| exterior Wronskian | BigFloat-120 |
| horizon scattering | BigFloat-80 |
| horizon scattering | BigFloat-120 |

Each entry retains an exact empirical numerical-control profile. It is called a
budget entry only at the receipt boundary; it does not claim a calibrated
determinant-to-ODE conversion. Exterior mechanisms share their family/tier
entry; there are no leaf, coordinate, amplitude, or mechanism-specific
sub-budgets. BigFloat-40 reuses the established BigFloat-80 base/refinement ODE
control values while retaining its own root-search step bounds. This assigns no
new tolerance value and leaves more than eighteen decimal guard digits at the
tight profile.

The source audit with SHA-256
`a31a266c8488a7b19510a8d3fea4497cddcb2108eb9e424e27c396fa26ad6ae0`
found no positive authenticated archived `derivative_lower_bound_abs` for
either determinant family. The receipt therefore records, for both families:

```text
archived_derivative_floor_status = ARCHIVED_AUTHENTICATED_LOWER_BOUND_UNAVAILABLE
archived_minimum_derivative_lower_bound_abs = null
receipt_derivative_floor_abs = null
```

The null floor is not converted to zero and is not a claim of calibration.
`CALIBRATION_DOMAIN_EXCEEDED` is reserved for a future receipt that contains a
positive numeric floor. The current calculation instead requires a finite positive
current-run authenticated derivative lower bound:

```text
L = |D'| - step_disagreement_abs - propagated_error_abs
```

The single derivative-authentication constructor owns this calculation. A
missing, nonfinite, or nonpositive `L` fails closed through the existing typed
finite-difference/determinant-uncertainty failure path.

The default loader opens the canonical committed bytes and compares their digest
with the committed value. A caller may supply a replacement only with both an
explicit file path and expected SHA-256; it must be canonical JSON, the exact
schema, operator-approved, correctly family/tier-covered, and match that
digest. There is no unpinned override path.

## Exterior determinant certificate

Exterior promoted determinant evaluations use
`exterior-determinant-absolute-error-certificate/empirical-v1`:

```text
determinant_error_abs = 64 * max(
    delta_same_point,
    delta_cross_precision,
    delta_endpoint_series,
)
```

- `delta_same_point` is the base-versus-tight-control disagreement at the same
  `(omega, amplitude)`.
- `delta_cross_precision` is the same-point result at the immediately
  preceding arithmetic tier. BigFloat-40 bridges to the binary64 native
  determinant; BigFloat-80 bridges to BigFloat-40; BigFloat-120 bridges to
  BigFloat-80.
- `delta_endpoint_series` is the largest authenticated same-point endpoint,
  series-order, best-prefix, or endpoint-resolution disagreement.

All three are mandatory. A missing applicable term produces
`EXTERIOR_DETERMINANT_CERTIFICATE_UNAVAILABLE`; it never becomes zero and no
response disk, root acceptance, derivative, fixed-root validation, truncation,
resolution, or finite-amplitude validation may consume the determinant.

The worker serializes the three terms, safety factor, model identity, and the
explicit statement that the resulting radius is a conservative empirical
certificate—not a formal interval enclosure.

The same-point tight profile halves every relevant ODE relative/absolute
tolerance and doubles endpoint/support resolution while preserving the exact
`(omega, amplitude)` point. For `delta_endpoint_series`, the nearest adequate
outward endpoint and the next legal outward endpoint are mandatory; every
available authenticated best-prefix, series-order, or endpoint-resolution
disagreement is also included in the maximum.

The current-run empirical frequency disk is

```text
root_error_radius_abs = determinant_error_abs / L
```

and exists only when both the determinant certificate and positive derivative
lower bound are authenticated. The existing determinant-derivative route is the
current production route. A new variational exterior-ODE derivative engine is out of
scope; the full signed-amplitude ladder remains validation-only.

## Native boundary and invalidation

`NativeCampaignStageBackend` selects budgets by determinant family plus
semantic precision tier, not by tier alone. The canonical execution contract,
worker request, worker runtime, partial journal, checkpoint, root-readout cache,
and solved-leaf cache all bind the receipt SHA and certificate identity.

Changing the receipt SHA, certificate identity, safety factor, derivative floor,
or a budget entry changes the promoted scientific computation identity. Existing
promoted stages, journals, root-readout entries, and solved-leaf entries are
therefore rejected and recomputed from the first missing promoted tier. Binary64
records stay intact because they have no receipt binding.

## PowerShell surface

The production entry points load the committed receipt automatically. They also
expose `-CalibrationReceiptPath` and `-CalibrationReceiptSha256`; the two must
be supplied together and are passed to the native CLI. The CLI rejects a path
without a matching SHA before it creates a worker request.

After this change a native PowerShell production test may execute, checkpoint,
and calculate empirical uncertainty disks with a successful process exit. Its
scientific status is `EMPIRICAL_TEST_ONLY_NO_ARCHIVED_FLOOR`; final admission
and publication remain blocked pending independent mathematical review and a
future authenticated calibration floor.

## Verification ceiling

Development verification remains air-gapped: Python unit/integration tests,
static Julia source contracts, PowerShell parser/static tests, canonical JSON
and cache-identity checks only. No Julia worker, determinant, ODE solve, root
solve, campaign, or production PowerShell script is executed here.
