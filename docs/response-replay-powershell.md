# Selected response replay from PowerShell

These commands exercise the authenticated representative replay only. They do
not enable the linear-response provider and do not create release evidence.

Create a selection file containing the pinned replay backend and one or more of
the five predeclared leaf IDs:

```powershell
$selection = @{
  schema_version = 1
  backend_id = "recorded-response-risk-replay"
  leaf_ids = @(
    "b-prime-leaf-9e5777728144433e089f9559b92b6e139e16115a5a53099f40403a45297aa3c3"
  )
} | ConvertTo-Json -Depth 4 -Compress
Set-Content -Path selection.json -Value $selection -Encoding utf8NoBOM
```

Plan, execute cold, resume with zero work, and validate the checkpoint:

```powershell
python -m windows_solver response-plan selection.json --checkpoint checkpoint.json
python -m windows_solver response-run selection.json --checkpoint checkpoint.json
python -m windows_solver response-resume selection.json --checkpoint checkpoint.json
python -m windows_solver response-validate selection.json --checkpoint checkpoint.json
```

Each command writes exactly one JSON object. Invalid selections, stale bindings,
tampered results, and incorrect cold/resume state return a nonzero exit code and
one machine-readable error object on standard error.

## B-prime 212-leaf campaign handoff

The campaign commands plan all 212 literal B-prime leaves but execute only the
explicit role-bounded selection. They never complete a Cartesian product. The
provider remains unavailable and every partial or merged checkpoint reports
`release_admissible=false`.

Create a binary64 selection manifest. The compatibility field
`precision_digits` is a mixed-unit tier selector: `64` means IEEE-754 binary64
(~15–16 significant decimal digits), while `80` and `120` mean decimal-digit
Julia BigFloat tiers. Reports retain that legacy field and add unambiguous
precision-tier metadata. `leaf_ids` and `cohort_ids` are mutually
exclusive; IDs must already be in canonical plan order.

```powershell
$selection = @{
  schema_version = 1
  backend_id = "vetted-native-gsn-determinant"
  precision_digits = @(64)
  precision_backend = $null
  role = "primary"
  leaf_ids = @(
    "b-prime-leaf-9e5777728144433e089f9559b92b6e139e16115a5a53099f40403a45297aa3c3"
  )
  cohort_ids = $null
} | ConvertTo-Json -Depth 5 -Compress
Set-Content -Path campaign-selection.json -Value $selection -Encoding utf8NoBOM
python -m windows_solver campaign-plan campaign-selection.json > campaign-plan.json
```

For a cohort run, copy the desired canonical `cohort_id` from
`campaign-plan.json`, set `leaf_ids=$null`, and set `cohort_ids=@($cohortId)`.

The permitted build-time preflight replays exactly three authenticated records
and exercises seven explicitly synthetic orchestration records. It performs no
native determinant solve:

```powershell
python -m windows_solver campaign-smoke
```

Physical selected execution uses the persistent per-user Julia environment to
generate the exact F/U coefficient records required by the selected campaign
leaves. Provision CPython, NumPy/SciPy, and Julia once:

```powershell
.\runtime\bootstrap.ps1 -WithM02
.\solver.ps1 campaign-run .\campaign-selection.json --checkpoint .\primary-part.json
.\solver.ps1 campaign-resume .\campaign-selection.json --checkpoint .\primary-part.json
.\solver.ps1 campaign-validate .\campaign-selection.json --checkpoint .\primary-part.json
```

The bootstrap validates an exact existing CPython 3.12.13 and Julia 1.10.11
before downloading managed copies. It keeps the numerical virtual environment,
Julia depot/packages/artifacts/compiled cache, and contract-addressed copies of
the vendored Julia scientific sources under
`%LOCALAPPDATA%\Kerr-QNM_Windows-Solver\runtime-1\` by default. The persistent
M02 Project/Manifest uses those installed source paths rather than a disposable
Downloads checkout. Use `-PortableRuntime` only for an explicitly portable
checkout-local `.runtime` tree.

The producer executes the packaged `Potentials.sF` / `Potentials.sU` equations
with exact symbolic rational algebra, validates them against direct evaluation,
and writes one short artifact per exact `(a,m)` pair under the matching managed
source contract's `generated\gsn\<contract-id>` directory. `gsn-index.json` uses a canonical scientific
identity containing spin weight, the resolved campaign spin, azimuthal index,
mass normalization, equation convention, and the producer/consumer contract
versions. Direct-spin leaves use their exact rational `a/M`. For an `M-kappa`
leaf, the bridge resolves
`a/M = sqrt(1 - 4 M-kappa) / (1 - 2 M-kappa)`, stores the exact integer ratio of
that binary64 value for Julia rational algebra, and retains the exact source
`M-kappa` coordinate as origin metadata.

Warm reuse is pair-level and independent of campaign ordering or subset size.
The status and artifact are reread and structurally validated on every reuse;
an invalid pair regenerates under the same short ID without discarding other
accepted pairs. Index allocation is locked, index replacement is atomic, and
the prior valid index is retained as `gsn-index.previous.json`. Measured hashes
and producer metadata are observations, not development execution gates.

The installed backend owns all declared precision stages. Binary64 uses the
existing Python `StandardSN` path; 80/120-digit stages use the persistent
managed Julia worker and return the same root-readout contract to the existing campaign
runner. No separately supplied precision module is needed for M02.

For the complete campaign, the root launcher selects all 212 leaves, starts or
resumes the checkpoint, and performs full structural validation:

```powershell
.\m02.ps1
```

Use `.\m02.ps1 -RebuildRuntime` only when intentionally discarding the
persistent managed runtime and provisioning it again. The campaign checkpoint
under `m02-output` is checkout-local and is not removed by that option.

Merge manifests name relative, non-symlink checkpoint paths. Absolute, UNC,
drive-relative, traversal, ADS, duplicate-key, nonfinite, stale, mixed-policy,
and disagreeing-overlap inputs are rejected before work.

```powershell
$merge = @{
  schema_version = 1
  backend_id = "vetted-native-gsn-determinant"
  precision_digits = @(64, 80, 120)
  precision_backend = $null
  checkpoint_paths = @("parts\primary-a.json", "parts\primary-b.json")
} | ConvertTo-Json -Depth 4 -Compress
Set-Content -Path campaign-merge.json -Value $merge -Encoding utf8NoBOM
python -m windows_solver campaign-merge campaign-merge.json --output merged.json
python -m windows_solver campaign-validate campaign-selection.json --checkpoint merged.json --full
```

`--full` requires the exact ordered 212 leaf IDs, zero extras or missing records,
terminal precision evidence, and no missing-precision stage. A governed computed
`UNRESOLVED` record is complete; an unexecuted leaf or missing 80/120 stage is
not. Even an exact structurally complete bundle is not admitted by this task:
software readiness, operator computation, and scientific-provider admission are
separate states.

## Deterministic projective reduction

`campaign-reduce` performs no response or determinant work. It authenticates
the named TASK-009 checkpoint bytes, reuses the existing semantic checkpoint
validator, consumes signed-channel evidence, and writes one canonical reduction
object atomically. A partial set stays `INCOMPLETE`; every absent component ID
is listed and no missing row receives a scientific classification.

This example intentionally names the predeclared deep-tail row with no component
evidence, so it demonstrates the honest partial result rather than constructing
a scientific atlas:

```powershell
$checkpointPaths = @("deep-tail-partial.json")
$sourceHashes = @(
  $checkpointPaths | ForEach-Object {
    "sha256:" + (Get-FileHash $_ -Algorithm SHA256).Hash.ToLowerInvariant()
  }
)
$bundle = [ordered]@{
  schema_version = 1
  campaign_id = "b-prime-campaign-80e2150845fe9e32fa37d7ecc660fa24083f2a179668b2915bc2a01b748b4f49"
  backend_id = "vetted-native-gsn-determinant"
  precision_digits = @(64)
  precision_backend = $null
  checkpoint_paths = $checkpointPaths
  selected_row_ids = @("deep-K22-1-1000-exterior-throat-kappa")
  component_evidence = @()
  source_hashes = $sourceHashes
}
$bundle | ConvertTo-Json -Depth 20 -Compress | Set-Content reduction-material.json -Encoding utf8NoBOM
python -c 'from pathlib import Path; import hashlib,json; from windows_solver.contracts import canonical_json_bytes; p=Path("reduction-material.json"); v=json.loads(p.read_text()); v["bundle_sha256"]=hashlib.sha256(canonical_json_bytes(v)).hexdigest(); Path("reduction-bundle.json").write_bytes(canonical_json_bytes(v))'
python -m windows_solver campaign-reduce reduction-bundle.json --output partial-reduction.json
$partial = Get-Content partial-reduction.json -Raw | ConvertFrom-Json
$partial.reducer_state
$partial.missing_component_ids
```

Resolved evidence uses an ordered `contributions` array. Every item supplies a
stable channel ID and family, shared group, signed real/imaginary delta, units,
checkpoint source receipt, and `local` or `shared` scope. Computed unresolved
evidence retains its raw contribution ledger but has no centre, Gram, or disk.
The CLI accepts only `authenticated-campaign` evidence and binds each component
to the same leaf record in the byte-verified checkpoint named by its receipt.
For resolved leaves the centre must equal the final checkpoint response; the
ordered family, signed delta, units, and scope of every channel must equal the
final stage ledger. Local stage job IDs are translated only to the canonical
`local:<leaf-id>:<family>` component ID and leaf shared group. Required families
and recorded precision discrepancies are also exact. Receipt membership by
itself is not sufficient. Duplicate/nonfinite JSON, stale or mixed campaign
lineage, disagreeing checkpoint overlaps, unsafe paths, and existing output
files fail before publication.

Once the operator has the complete admitted 212-leaf evidence, use the same
frozen command and all 57 canonical row IDs. Only that complete evidence may
produce the full 57-row scientific artifact. The reducer software and the
examples above do not admit the provider or populate that atlas.
