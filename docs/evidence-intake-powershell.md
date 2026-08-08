# Operator evidence intake from PowerShell

TASK-007 validates bundle structure, identity, file bytes, and lineage only. It does not run a response calculation, reduce uncertainty, or admit the linear-response provider.

An operator bundle is a directory containing `evidence-bundle.json` plus every relative source and payload path named by that manifest. The manifest uses schema version 1, one of the states `partial-smoke` or `complete-operator`, the exact ordered 553-leaf B′ contract, and a canonical `bundle_sha256` computed over all fields except the digest itself. Backslashes and forward slashes identify the same safe relative path; absolute paths, every drive designator (including `C:relative.json`), UNC paths, alternate-data-stream colons, and `..` traversal are rejected.

The contract includes a `campaign_spectral_receipt` with the exact spectral
provider descriptor, `root_count: 87`, and the canonical campaign root-set
SHA-256. Every produced record includes both `root_identity` and
`root_identity_sha256`. The identity is copied from the authenticated campaign
job/checkpoint and contains the selector, branch, binary64 spin, complex ω,
angular separation constant, catalog-owner ID/data digest, and complete owner
record. For a `complete-operator` bundle, the 553 records must reduce to exactly
the same ordered 87-root set named by the contract receipt.

Producer provenance is closed rather than descriptive. `runtime_fingerprint` has canonical form `cpython-MAJOR.MINOR[.PATCH]-SYSTEM-ARCH`, using lowercase system and architecture tokens such as `cpython-3.12.4-windows-amd64`. `producer.source_sha256s` must equal the set of SHA-256 values for all byte-verified `source_files`, with neither missing nor extra hashes.

Each comparator binds its declared source twice: `source_sha256` is recomputed directly and `source_blob_sha` is recomputed from the Git blob envelope (`blob`, one space, decimal byte length, NUL, then exact bytes). Its `identity_sha256` is SHA-256 over canonical JSON containing exactly `fixture_id`, `fixture_kind`, `disposition`, normalized `source_path`, `source_blob_sha`, and `source_sha256` in that key-sorted representation. A well-shaped substituted digest is rejected.

From a source checkout:

```powershell
$Bundle = (Resolve-Path (Join-Path $PWD "operator-bundle")).Path
$Result = & python -m windows_solver validate-evidence $Bundle | ConvertFrom-Json
if ($LASTEXITCODE -ne 0) { throw "Evidence validation failed" }
$Result | ConvertTo-Json -Depth 8
```

With the installed command:

```powershell
$Manifest = (Resolve-Path (Join-Path $PWD "operator-bundle\evidence-bundle.json")).Path
$Result = & solver validate-evidence $Manifest | ConvertFrom-Json
if ($LASTEXITCODE -ne 0) { throw "Evidence validation failed" }
```

Success emits exactly one JSON object with the bundle state and digest, produced/missing/comparator counts, predeclared sampled IDs, `validation_status`, and `release_admissible: false`. Invalid input emits one JSON error object on stderr and exits nonzero.

A `partial-smoke` bundle may preserve a nonempty exact B′ subset for diagnostics or resume, but is never release-admissible. A `complete-operator` manifest is structurally valid only at exactly 553 produced IDs and zero missing IDs; structural validity still does not admit the provider. Later tasks own response execution, reduction, scientific validation, and admission.

The packaged migration fixtures remain quarantined: the nine χ=0.95 GR pilot components carry their authenticated component-local signed-amplitude-ladder ceiling, the other 138 identities in the legacy 147-record grid remain `MISSING_SOURCE_EVIDENCE`, and the eight parity-even cubic rows are comparator-only.
