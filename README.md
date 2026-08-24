# Kerr-QNM Windows Solver

A native-Windows, evidence-graded solver for Kerr quasinormal modes and staged linear-response calculations.

The repository separates four things that must never be conflated:

```text
software execution
numerical acceptance
scientific evidence
release admission
```

A process completing successfully is not, by itself, a scientific result. A numerically unresolved result may still be valid evidence. A screened result may be useful for an atlas while remaining inadmissible for publication or release.

---

## Current boundary

The public control plane and authenticated pure-Kerr spectral catalogue are available. The packaged catalogue contains 2,736 roots over the declared ℓ, m, n, and spin domain, with exact-coordinate selection and recorded numerical diagnostics.

M02 linear response is an operator-run evidence pipeline. It can build and resume the response atlas, but the linear-response provider remains closed until the required certification, validation, reduction, and admission gates are satisfied.

The machine-readable release authority is:

```text
src/windows_solver/data/release_domain_manifest.json
```

The human reconciliation is:

```text
docs/release-baseline.md
```

Neither narrative documentation nor a successful campaign run may silently widen the admitted scientific scope.

---

## Windows quick start

Open a 64-bit PowerShell in the repository root.

```powershell
Set-ExecutionPolicy -Scope Process Bypass -Force
.\runtime\bootstrap.ps1
```

The normal managed runtime is stored under:

```text
%LOCALAPPDATA%\Kerr-QNM_Windows-Solver\runtime-1\
```

It requires no administrator rights, does not modify the system `PATH`, and does not install packages into the system Python environment.

Basic control-plane examples:

```powershell
.\solver.ps1 plan .\examples\evidence-plan.json
.\solver.ps1 run .\examples\problem-contract.json --store .\.solver-store
.\solver.ps1 run .\examples\spectrum.json --store .\.solver-store
```

Provision the numerical Python tier when required:

```powershell
.\runtime\bootstrap.ps1 -WithNumericalKernel
```

Provision the complete M02 Python/Julia environment:

```powershell
.\runtime\bootstrap.ps1 -WithM02
```

The M02 environment is pinned to CPython 3.12 and Julia 1.10.11, with solver-owned package, depot, source, and generated-artifact locations.

---

## M02 campaign

The canonical bundled selection is:

```text
examples/m02-campaign.json
```

For the current checkout it should resolve to the declared full-role campaign. The exact campaign ID, selection ID, leaf count, and role counts emitted by `campaign-plan` are authoritative for that commit. Do not hard-code an ID from an earlier checkpoint or pull request.

Inspect the current plan before execution:

```powershell
.\solver.ps1 campaign-plan .\examples\m02-campaign.json
```

`m02.ps1` prepares the selection-scoped GSN resources automatically, on every
cold start and every resume, before it invokes any pass. That step is
equivalent to running the underlying command directly:

```powershell
.\solver.ps1 campaign-prepare-resources .\examples\m02-campaign.json
```

Resource preparation may invoke Julia and writes the sealed resource receipt.
Campaign execution itself is load-only: if that receipt or its files are
absent, stale, or corrupt, the pass stops with `GSN_BOOTSTRAP_REQUIRED` before
leaf 1. You do not need to run the command above yourself before `m02.ps1
-NewCampaign`; it is shown here only for operators driving `solver.ps1`
directly instead of through `m02.ps1`.

### Start or resume the binary64 survey

```powershell
.\m02.ps1
```

Equivalent explicit form:

```powershell
.\m02.ps1 -Profile survey -SurveyPass binary64
```

Under the default binary64 survey profile, the default checkpoint path
decides what happens: if it does not yet exist, this is an ordinary first
run and a new campaign is created before the survey starts; if it exists,
the survey resumes from it. `-NewCampaign` is only needed to protect against
overwriting an existing checkpoint, or to start a new campaign at an
explicit, non-default `-Checkpoint` path:

```powershell
.\m02.ps1 `
  -NewCampaign `
  -Checkpoint .\m02-output\m02-campaign-checkpoint.json
```

`-NewCampaign` refuses to run if that checkpoint already exists. Certify,
validate, and the promoted survey pass always require an existing
checkpoint from prior binary64 work; a missing checkpoint there remains a
hard failure, since there is nothing yet to certify, validate, or promote.

The binary64 survey:

- reuses exact compatible terminal records before constructing a backend;
- performs the minimum fixed-root work required for a bounded response;
- launches no Julia numerical worker;
- records precision escalation in a durable promotion queue;
- never performs promoted work inline;
- advances only after committing the current pass disposition.

### Run the promoted survey

```powershell
.\m02.ps1 -Profile survey -SurveyPass promoted
```

The promoted survey consumes only the durable promotion queue. It uses BF40 first and BF80 only for approved typed arithmetic insufficiency. BF120, publication certificates, diagnostic root ladders, and independent validation are not survey work.

### Certify screened results

```powershell
.\m02.ps1 -Profile certify
```

Certification consumes the canonical mixed-role triage queue and may add stronger local uncertainty and authentication evidence. It does not silently replace the retained numerical centre.

### Validate selected publication or risk rows

```powershell
.\m02.ps1 -Profile validate -QueuePath <selection-or-queue.json>
```

Validation is explicit. It is reserved for publication rows, risk-selected sentinels, disagreement cases, near-zero components, projective controllers, and independent-route checks.

There is no automatic transition between:

```text
survey / binary64
survey / promoted
certify
validate
```

---

## Recovery

Recovery is generic and count-agnostic. It may receive zero, one, or many compatible historical records.

```powershell
.\m02-recover.ps1 `
  -Selection .\examples\m02-campaign.json `
  -OutputCheckpoint .\m02-output\m02-campaign-checkpoint.schema11.candidate.json `
  -Receipt .\m02-output\m02-recovery-receipt.json `
  -SourceCheckpoint <optional-checkpoint> `
  -SolvedLeafStore <optional-store> `
  -RootReadoutStore <optional-store>
```

The recovery contract is:

```text
valid compatible terminal records supplied     N
valid compatible terminal records recovered    N
lost valid records                              0
fabricated records                              0
numerical recomputation                         0
```

`N` may be zero. No operator-specific archive, receipt count, filename, checkpoint hash, or incident fixture is a runtime prerequisite.

Recovery writes a new candidate. Production cutover is a separate explicit action with a verified backup and atomic replacement.

---

## M02 state model

M02 keeps scientific state, evidence strength, scheduler progress, and operational failure history separate.

### Numerical record

| State | Meaning |
|---|---|
| `PRODUCED` | Finite retained central response and bounded disk |
| `UNRESOLVED` | The permitted numerical policy was exhausted without an admissible bounded response |
| `REJECTED` | A validly constructed leaf failed an explicit scientific rejection rule |
| `IN_PROGRESS` | Transient, never terminal |

`FAILED` is not a numerical terminal state. It is operational history only.

### Evidence level

```text
none → SCREENED → CERTIFIED → VALIDATED
```

Evidence upgrades are monotone and do not rewrite the retained numerical record.

### Survey disposition

| Disposition | Meaning |
|---|---|
| `CACHE_REUSED` | Exact terminal record reused with zero backend work |
| `COMPLETED` | The requested survey pass completed |
| `PROMOTION_PENDING_ROOT` | A later survey tier is required for the root |
| `PROMOTION_PENDING_RESPONSE` | A later survey tier is required for the response |
| `UNRESOLVED` | All work permitted by the active survey policy is exhausted |
| `DEFERRED` | Explicitly postponed by policy, scheduling, or operator instruction |
| `REJECTED` | Explicit scientific rejection after valid construction |

A system defect, malformed worker response, schema defect, identity mismatch, unexpected exception, or work-budget breach writes a system-failure receipt and aborts the active pass. It is never converted into a completed scientific leaf.

---

## Dashboard

The main M02 PowerShell window uses the Python in-process dashboard.

Its rendering contract is:

```text
banner                         printed once
campaign summary               printed once
historical completed rows      printed once
new completed row              appended once
live execution                 exactly one bounded physical line
heartbeat or state change      rewrites that same live line
```

The dashboard does not clear the screen, move the cursor upward, redraw multiple lines, or add heartbeat scrollback. It remains usable if advanced projective or triage reporting is degraded because authoritative counts come from the checkpoint and ledgers.

Completed rows expose, where available:

```text
time
leaf and mode
spin
mechanism
survey pass
evidence level
precision tier
binary64 / BF40 / BF80 / BF120 timing
total timing
response magnitude
relative disk
numerical state
```

Reconstructed historical timing is marked with `~`.

---

## Checkpoint reports

After each committed checkpoint update, the basic projections are written independently:

```text
m02-leaves.csv
m02-precision-stages.csv
m02-error-channels.csv
m02-resource-failures.csv
```

Advanced projections are separate:

```text
m02-projective.csv
m02-triage.json
```

Projection status is recorded in:

```text
m02-report-status.json
```

An advanced-report failure must not remove or zero the basic campaign tables. A basic-report failure preserves the checkpoint and stops the active pass with an explicit reporting failure.

The checkpoint and its ledgers are authoritative. CSV files and the dashboard are projections.

---

## Identity, caching, and immutability

All reusable scientific work is content-addressed and identity-bound.

Exact reuse requires agreement on every relevant scientific identity, including the root seal, branch, determinant family, normalization, mechanism or support mapping, numerical controls, precision tier, backend, and operation identity.

Rules:

- no approximate cache matching;
- no nearby-spin aliases;
- no timestamp-based scientific precedence;
- no replacing a stronger terminal record with weaker or failed work;
- no reusing a changed realised support mapping;
- no cross-mechanism Dω reuse without exact-key agreement and an authenticated background-equivalence receipt;
- no backend construction on an exact terminal cache hit.

A valid `PRODUCED` record never becomes `UNRESOLVED`, `REJECTED`, or operationally failed. A valid `UNRESOLVED` record remains terminal on ordinary resume and runs again only through explicit requeue under a changed policy or selection.

---

## General command surface

Core commands:

```text
solver plan STUDY.json
solver run STUDY.json [--store PATH]
solver verify RUN_ID [--store PATH] [--profile research|publication]
solver inspect RUN_ID [--store PATH]
solver export RUN_ID --output PACKAGE.json [--store PATH]
```

Campaign commands:

```text
solver campaign-plan SELECTION.json
solver campaign-prepare-resources SELECTION.json
solver campaign-new SELECTION.json --output CHECKPOINT.json
solver campaign-survey-binary64 SELECTION.json --checkpoint CHECKPOINT.json
solver campaign-survey-promoted SELECTION.json --checkpoint CHECKPOINT.json
solver campaign-certify SELECTION.json --checkpoint CHECKPOINT.json [--queue QUEUE.json]
solver campaign-evidence-validate SELECTION.json --checkpoint CHECKPOINT.json --queue QUEUE.json
solver campaign-schema11-validate SELECTION.json --checkpoint CHECKPOINT.json [--pass PASS]
solver campaign-recover SELECTION.json --output CANDIDATE.json --receipt RECEIPT.json
solver campaign-merge MANIFEST.json --output CHECKPOINT.json
solver campaign-reduce REDUCTION-BUNDLE.json --output REDUCTION.json
```

The older `campaign-run`, `campaign-resume`, and `campaign-validate` commands
remain general-purpose legacy checkpoint operations. They are not independent
M02 schedulers and do not own schema-11 M02 state transitions.

Admission commands:

```text
solver validate-evidence BUNDLE
solver m02-validate ADMISSION-INPUT.json
solver m02-admit ADMISSION-INPUT.json --output ADMITTED.json
solver m02-export ADMITTED.json --admission-id ID --output EXPORTED.json
```

Use `solver --help` or the corresponding `*.ps1` wrapper for the exact options supported by the checked-out commit.

---

## Repository map

```text
src/windows_solver/        production Python package
src/windows_solver/data/   packaged scientific data, manifests, licences, and Julia sources
runtime/                   managed-runtime bootstrap and discovery
examples/                  canonical study and campaign inputs
tests/                     software, contract, migration, and regression tests
tools/                     offline generation, validation, and diagnostic utilities
docs/                      current architecture and operator runbooks only
.tasks/                    current delivery board only
```

Historical design plans, PR handovers, implementation scratch reports, and superseded architecture documents belong in Git history, not the active documentation surface.

---

## Documentation authority

Use the following order when documents disagree:

1. machine-readable manifests, authenticated artifacts, checkpoint receipts, and emitted identities;
2. current production code and passing contract tests;
3. this README, `docs/architecture.md`, and the current operator runbooks;
4. `.tasks/` for delivery state only;
5. Git history for superseded decisions and provenance.

While draft PR #66 is being completed, its committed
`PR66_GOVERNING_COMPLETION_CONTRACT.md` governs PR-specific completion and
acceptance. It does not replace the enduring production architecture above,
and the PR body is intentionally only a pointer to that committed authority.

The active operator runbooks are:

```text
docs/response-replay-powershell.md
docs/evidence-intake-powershell.md
docs/m02-admission-powershell.md
```

A pull-request description, old implementation plan, dated handover, unchecked historical checkbox, or archived benchmark does not override current code or the authorities above.

The delivery board has one live source:

```text
.tasks/IN_PROGRESS.md
.tasks/NEXT.md
.tasks/BACKLOG.md
.tasks/DONE.md
.tasks/REJECTED.md
.tasks/WORK_LOG.md
```

Do not create a second backlog or treat historical plans as executable instructions.

---

## Development and verification

Run the permitted software suite from a source checkout:

```powershell
$env:PYTHONPATH = "src"
python -m unittest discover -s tests -v
python tools/validate_release_manifest.py
python .tasks/validate_board.py
```

These checks establish software, schema, migration, serialization, orchestration, and static worker contracts. They do not replace native mathematical evidence.

Production Kerr/GSN campaigns and native PowerShell/Python/Julia canaries are operator-run. A development agent must not use the production campaign as a unit test or silently substitute mocked success for a required native boundary.

---

## Evidence and release discipline

The solver reports the weakest supported conclusion.

- `SCREENED` is sufficient for provisional atlas visibility and triage.
- `CERTIFIED` adds the required local authentication and uncertainty evidence.
- `VALIDATED` adds explicit independent or publication-grade checks.
- `SCREENED` alone is not release-admissible.
- A discrepancy outside the retained disk is recorded; it does not silently replace the centre.
- `UNRESOLVED` and adverse outcomes remain valid evidence when their provenance is intact.

Release admission is explicit, content-sealed, and fail-closed.

---

## Licences


```text
src/windows_solver/data/
src/windows_solver/data/julia/GeneralizedSasakiNakamura.jl/
src/windows_solver/data/julia/SpinWeightedSpheroidalHarmonics.jl/
```
