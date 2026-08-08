# M02 validation, admission, and export from PowerShell

The installed M02 machinery performs no hidden full campaign. The operator
produces the 553 scientific leaf records, then supplies those files to the
validator and reducer. The provider is unavailable unless a sealed admission
package is passed explicitly to `plan` or `run`.

All commands below emit one JSON object. A nonzero exit code means no admission
or export was created.

## 1. Validate the operator evidence and campaign

From the directory containing the operator files:

```powershell
.\solver.ps1 validate-evidence .\evidence\evidence-bundle.json
.\solver.ps1 campaign-validate .\campaign-selection.json `
  --checkpoint .\campaign-complete.json --full
```

The evidence manifest must have state `complete-operator`, exactly 553 produced
leaf IDs, zero missing IDs, authenticated payload/source hashes, the frozen M02
policy fingerprint, a valid producer runtime lineage, the exact spectral
provider/root-set receipt, and a complete checkpoint root identity on every
produced record. `UNRESOLVED` is a governed produced state; missing, rejected,
malformed, duplicated, or unexecuted leaves fail admission.

## 2. Reduce all frozen projective rows

Use the reduction bundle described in
[response-replay-powershell.md](response-replay-powershell.md), selecting all
174 frozen row IDs:

```powershell
.\solver.ps1 campaign-reduce .\reduction-bundle.json `
  --output .\reduction.json
```

The reducer authenticates its checkpoint receipts and performs no determinant
or response solve. Admission requires reducer state `COMPLETE`, 162 primary
rows plus 12 deep rows, the exact row order, every required component present,
and zero missing components. Projective `UNRESOLVED` outcomes remain honest
produced results. Each payload projective comparison must then reproduce the
same ordered reduction row: mapped response-component IDs, calibration pair,
empirical-Gram identity, nominal/bounded angles, calibration state, outcome,
scientific state, and reason. Admission rejects an empty, reordered, stale, or
unrelated comparison array. For every resolved row, `covariance_id` must equal
the sealed empirical-Gram ID and the referenced payload block must reproduce
that Gram's mapped component/quadrature basis and complete matrix exactly.
Overlapping component bases across different row Grams are allowed; an extra
cross-component covariance block that is not sealed by a reduction Gram is not.
A row containing an unresolved component uses null
covariance, empirical-Gram, angle, and calibration-state fields rather than an
invented identity or numerical value.

## 3. Build the admission input

Prepare the frozen full-domain study request and final linear-response payload
as `request.json` and `payload.json`. The payload lineage must include the
evidence bundle digest, the evidence manifest file digest, the reduction file
digest, and every reduction source receipt.

Each of the 553 `produced_records` must also point to a JSON payload whose
object is the exact corresponding entry in `payload.json`'s
`response_components` array. Admission matches the record and component by
mode, binary64 spin identity, and mechanism; requires identical numerical state
and root reference; and rereads the record payload under its declared byte size
and SHA-256 before comparing the complete object. A copied lineage hash cannot
make a stale or unrelated component admissible. Admission also compares every
record's complete campaign root identity to the installed catalog and to the
exact root object in the scoped 87-root spectral payload. A campaign produced
under catalog A cannot be admitted or replayed under catalog B, even if all
mode/spin reference IDs and internal evidence hashes are consistently resealed.

Create `admission-input.json` with safe paths relative to its own directory:

```json
{
  "schema_version": 1,
  "kind": "m02-linear-response-admission-input",
  "evidence_bundle": {
    "path": "evidence/evidence-bundle.json",
    "sha256": "<lowercase SHA-256 of evidence-bundle.json>"
  },
  "request": {
    "path": "request.json",
    "sha256": "<lowercase SHA-256 of request.json>"
  },
  "reduction": {
    "path": "reduction.json",
    "sha256": "<lowercase SHA-256 of reduction.json>"
  },
  "payload": {
    "path": "payload.json",
    "sha256": "<lowercase SHA-256 of payload.json>"
  }
}
```

PowerShell computes each lowercase digest without changing the file:

```powershell
(Get-FileHash .\request.json -Algorithm SHA256).Hash.ToLowerInvariant()
```

Absolute paths, drive-relative paths such as `C:result.json`, parent traversal,
alternate data streams, symlink crossings, digest mismatches, and existing
output files fail closed.

## 4. Validate, admit, and export

```powershell
.\solver.ps1 m02-validate .\admission-input.json
$admission = .\solver.ps1 m02-admit .\admission-input.json `
  --output .\m02-admitted.json | ConvertFrom-Json
$admissionId = $admission.admission_id
.\solver.ps1 m02-export .\m02-admitted.json `
  --admission-id $admissionId --output .\m02-export.json
```

`m02-validate` reports `release_admissible: false` because it does not write or
register a provider. `m02-admit` and `m02-export` revalidate every bound object
and produce a content-sealed package. The package always records
`scientific_claims_admitted: false`: availability means the supplied evidence
passed the frozen structural/numerical contract, not that any scientific
outcome was favorable. The package also seals a spectral-upstream receipt: the
exact spectral provider descriptor, capability-scoped request, output artifact
type, accepted evidence state, and SHA-256 of the canonical 87-root payload.

Preserve `$admissionId` independently from `m02-admitted.json`. It is the
detached expected identity for every later package load. Editing the package
and recomputing its internal content hash cannot change this external pin.

## 5. Run the evidence-bound provider

The default registry remains closed. Supply the package for each plan or run:

```powershell
.\solver.ps1 plan .\request.json `
  --linear-response-admission .\m02-admitted.json `
  --linear-response-admission-id $admissionId

.\solver.ps1 run .\request.json --store .\.solver-store `
  --linear-response-admission .\m02-admitted.json `
  --linear-response-admission-id $admissionId
```

The first run materializes problem-contract, the exact 87-root sparse spectral
upstream, and linear-response artifacts. Repeating the identical command
against the same store reuses all three verified artifacts with zero provider
work. A different request, modified package, incomplete bundle, partial smoke,
missing package, missing detached ID, or ID mismatch cannot register the
provider. The admission ID is also part of the response provider's cache
identity, so a second valid package cannot reuse a response artifact produced
by a different admitted package in the same store. Before returning the
admitted response, the provider compares the actual spectral artifact to the
sealed receipt and rejects provider, request, catalog, root-value, artifact
type, or evidence-state drift.
