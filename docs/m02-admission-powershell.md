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
policy fingerprint, and a valid producer runtime lineage. `UNRESOLVED` is a
governed produced state; missing, rejected, malformed, duplicated, or
unexecuted leaves fail admission.

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
produced results.

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
make a stale or unrelated component admissible.

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
.\solver.ps1 m02-admit .\admission-input.json --output .\m02-admitted.json
.\solver.ps1 m02-export .\m02-admitted.json --output .\m02-export.json
```

`m02-validate` reports `release_admissible: false` because it does not write or
register a provider. `m02-admit` and `m02-export` revalidate every bound object
and produce a content-sealed package. The package always records
`scientific_claims_admitted: false`: availability means the supplied evidence
passed the frozen structural/numerical contract, not that any scientific
outcome was favorable.

## 5. Run the evidence-bound provider

The default registry remains closed. Supply the package for each plan or run:

```powershell
.\solver.ps1 plan .\request.json `
  --linear-response-admission .\m02-admitted.json

.\solver.ps1 run .\request.json --store .\.solver-store `
  --linear-response-admission .\m02-admitted.json
```

The first run materializes problem-contract, the exact 87-root sparse spectral
upstream, and linear-response artifacts. Repeating the identical command
against the same store reuses all three verified artifacts with zero provider
work. A different request, modified package, incomplete bundle, partial smoke,
or missing package cannot register the provider.
