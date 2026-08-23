# The Windows Solver

A native-Windows, evidence-graded nonlinear Kerr ringdown solver.

The solver is organized around physical outputs: Kerr quasinormal-mode spectra, first-order frequency shifts, operator stability, quadratic mode couplings, waveforms, detector response, and inverse inference. A request selects an output; the planner computes only its mathematical dependency closure.

## Current release boundary

The public control plane is working. It validates study contracts, plans dependencies, admits at most one production provider for each capability, stores content-addressed artifacts, resumes from verified cache entries, and reports evidence without conflating numerical success with a scientific conclusion.

PR #1 admitted `problem-contract`; PR #2 computes and admits `spectral-core`
alongside it. The pure-Kerr lattice contains 2,736 exact mode–spin roots:
ℓ=2 contributes 690, ℓ=3 contributes 966, and ℓ=4 contributes 1,080.
For every ℓ it includes every allowed m and n∈{0,1,2}. The ℓ=2 and ℓ=3
domains use 40 inclusive uniform points from χ=0 to 0.95 plus χ∈{0.97, 0.98,
0.99, 0.995, 0.997, 0.999}; ℓ=4 uses 40 inclusive uniform points from χ=0
to 0.75. There is one pure-Kerr result per coordinate, with no polarization or
EFT result axis.

Every requested node is polished with the coupled angular/Leaver determinant
backend. The packaged catalog records exact rational χ keys, binary64 solver
coordinates, Mω, angular A, residual and continued-fraction diagnostics,
angular refinement, repeat-polish agreement, and branch-continuation evidence.
All rows pass the declared numerical gates. Exact overlaps are compared with
392 independently published Motohashi values; those values are comparison
evidence and are not substituted for computed rows. The provider performs
exact selection only—no interpolation, extrapolation, or nearby-spin aliasing.
Formal root enclosure is not claimed and the scientific state remains
`NOT_EVALUATED`.

Providers beyond `linear-response` remain unavailable and fail closed. PR #3
freezes the M01 release domain, source receipts, module ownership, conventions,
evidence ceilings, and missing-input ledger without changing the accepted
spectrum. PR #4 begins the distinct `linear-response` migration; PR #5 installs
the M02 planner, resumable campaign, uncertainty/projective reduction, and
fail-closed admission machinery. No M02 scientific evidence is shipped: the
linear-response provider remains unavailable by default and can be registered
only from a complete operator package that passes the 212-leaf and 57-row
admission gates. The canonical M02 B′ campaign comprises 140 primary, 24
control, and 48 deep leaves. Reduction inputs are value-bound to their
authenticated checkpoint records, and all 57 payload comparisons are
value-bound to the sealed reduction. Each produced record carries its complete
checkpoint root identity; admission reconciles the resulting 48-root campaign
set against the installed catalog before the package seals the spectral
provider/request/payload
identity. Admission and replay therefore reject catalog or root drift. See [the
M01 release baseline](docs/release-baseline.md) and [the M02 PowerShell
handoff](docs/m02-admission-powershell.md).

M02 software work through PR #52 is merged, including the managed Julia/GSN
runtime, checkpoint and cache contracts, promoted-precision worker, and the
horizon-determinant rewrite: a three-leg solution basis on a verified
real-inner tortoise contour, absolute error-aware Newton acceptance, and a
mechanism-scoped precision policy that keeps exterior receipts written before
the rewrite reusable while correctly retiring stale horizon ones. The
promoted primary `horizon-admittance` component now performs one Julia root
readout per precision stage in place of a multi-readout finite-amplitude
ladder: PRIMARY accepts on `|D| / |D'| <= 2e-11` with zero post-Newton
determinant evaluations and retains the accepted complex derivative;
TRUNCATION and RESOLUTION each evaluate exactly one further determinant at
the fixed PRIMARY frequency by reusing that derivative rather than resolving
it independently. The derived response carries component identity
`single-promoted-root-analytic-horizon-component/v1` and uncertainty status
`UNCALIBRATED_ANALYTIC_RESPONSE`, with every error channel marked
not-applicable rather than measured-zero; admission fails closed on that
status.

TASK-075 remains open only for the missing immutable receipt for the
independent Black Hole Perturbation Toolkit Mathematica spheroidal validation
source. TASK-079 is in progress alongside it, regularising the promoted GSN
propagation and determinant conditioning that TASK-075 depends on; its
acceptance criteria are unmet pending native operator execution evidence for
the promoted Leaf 13 readout. TASK-076, blocked on both, then owns native
Windows/Ubuntu cold/warm execution proof; TASK-077 owns the complete 212-leaf
campaign; and TASK-078 owns reduction, provider admission, and M02 closure.
PR #30 separately added a fail-closed M03 contract precursor, but no M03
field artifact or provider is admitted.

The live delivery authority is [the TaskPlanner board](.tasks/README.md), with
the active item in [.tasks/IN_PROGRESS.md](.tasks/IN_PROGRESS.md), the next
dependency-ready item in [.tasks/NEXT.md](.tasks/NEXT.md), and chronological
evidence in [.tasks/WORK_LOG.md](.tasks/WORK_LOG.md). Dated files under
`docs/superpowers/` and `docs/keystone/` are historical design/implementation
records; unchecked boxes there are not a second backlog. See the
[documentation authority map](docs/README.md).

## Quick start on Windows

Clone or unpack the repository, open a 64-bit PowerShell in it, and provision a
per-user managed runtime once:

```powershell
Set-ExecutionPolicy -Scope Process Bypass -Force
.\runtime\bootstrap.ps1
```

The normal runtime lives under
`%LOCALAPPDATA%\Kerr-QNM_Windows-Solver\runtime-1\`, requires no administrator
rights, adds no registry entry, and does not modify `PATH`. It persists when a
solver ZIP is deleted or re-extracted. The bootstrap validates a healthy,
64-bit CPython 3.12.13 first; if one is available it is used only as the source
for the solver-owned virtual environment. Pinned NumPy/SciPy are installed only
inside that environment, never into the system interpreter. A solver-managed
CPython is downloaded only when no compatible interpreter exists.

Use checkout-local runtime bytes only when portability is explicitly needed:

```powershell
.\runtime\bootstrap.ps1 -PortableRuntime
```

That mode uses the git-ignored `.runtime\` folder beside the checkout.

```powershell
.\solver.ps1 plan .\examples\evidence-plan.json
.\solver.ps1 run .\examples\problem-contract.json --store .\.solver-store
.\solver.ps1 run .\examples\spectrum.json --store .\.solver-store
```

The core Python package has no required third-party Python dependency. Commands
that execute the native response kernel, plus the complete packaged test suite,
need the pinned NumPy and SciPy numerical tier:

```powershell
.\runtime\bootstrap.ps1 -WithNumericalKernel
```

The physical M02 campaign has a single stronger bootstrap tier. It validates an
exact Julia 1.10.11 from the managed runtime, an existing system installation,
or Juliaup before downloading solver-managed Julia. It then reuses or provisions
the pinned numerical environment, contract-addressed persistent GSN/spheroidal
source copies, M02 project, Julia depot/packages/artifacts/compiled cache, and
the package-owned promoted worker. The complete 212-leaf provisional atlas is
a single resumable survey command:

```powershell
.\m02.ps1
```

`survey` is the default execution profile. It records a bounded central
response as `SCREENED`, advances past unresolved or contained failed leaves,
and does not make heavy local or publication validation a prerequisite for
atlas visibility. Later invocations reuse the checkpoint and exact shared
exterior background/Domega evidence. The checkpoint report directory contains
`m02-leaves.csv` and the ordered `m02-triage.json` certification queue.

Targeted evidence upgrades use the same solver behind explicit profiles and
require an existing checkpoint. One triage artifact carries the mixed
primary/deep/control queue; the selected profile filters it to risk,
projective-controller, and sentinel entries that still need that evidence
level. Low-risk leaves remain visible as `REVIEW` rather than silently joining
the heavy queue. A centre discrepancy also forces `REVIEW`; it is never
automatically sent through the same heavy profile again:

```powershell
.\m02.ps1 -Profile certify `
  -TriageQueue .\m02-output\m02-campaign-checkpoint.reports\m02-triage.json
.\m02.ps1 -Profile validate `
  -TriageQueue .\m02-output\m02-campaign-checkpoint.reports\m02-triage.json
```

Certification and validation append evidence around the retained survey
centre. A disagreement outside its retained disk is recorded for review rather
than silently replacing the atlas value. `SCREENED` evidence is available to
atlas and triage reports but remains inadmissible to release/publication
reduction; those boundaries require at least `CERTIFIED` evidence.

Generated coefficients live under the managed runtime's source-contract-scoped
`generated\gsn\<contract-id>` directory (normally
`%LOCALAPPDATA%\Kerr-QNM_Windows-Solver\runtime-1\generated\gsn\`). The
`gsn-index.json` registry maps each scientific identity—spin weight, resolved
`a/M`, binary64 campaign value, `m`, normalization, equation convention, and
producer/consumer contract versions—to a short pair artifact such as
`gsn-000001.json`. Direct-spin leaves retain their exact rational `a/M`;
κ-derived leaves retain exact `Mκ` as origin metadata and use the exact integer
ratio of the resolved campaign binary64 `a/M`. Every reuse validates the status
and coefficient artifact itself. Missing or invalid records regenerate
independently; measured SHA-256 values are recorded as observations only during
development.

To discard the persistent managed runtime and explicitly reprovision it, use:

```powershell
.\m02.ps1 -RebuildRuntime
```

The launcher resolves the virtual environment declared by the validated runtime
receipt first, then its recorded interpreter source, an active `python` that is
3.12 or newer, and finally the runtime selected by the Windows `py -3`
launcher when that runtime is 3.12 or newer. Version probes report failure
through the exit code alone, so a candidate that writes to stderr — notably the
Windows App Execution Alias stub for `python.exe` — is skipped rather than
aborting the launcher, and probe output never reaches command JSON.

The equivalent Python commands are:

```text
python -m windows_solver plan examples/evidence-plan.json
python -m windows_solver run examples/problem-contract.json --store .solver-store
python -m windows_solver run examples/spectrum.json --store .solver-store
```

When running directly from a source checkout, set `PYTHONPATH=src` or install the package.

Study files are bounded to 4 MiB and 64 JSON nesting levels. Inputs beyond
those limits return the same structured invalid-input contract as other schema
errors.

## Commands

```text
solver plan STUDY.json
solver run STUDY.json [--store PATH]
solver verify RUN_ID [--store PATH] [--profile research|publication]
solver inspect RUN_ID [--store PATH]
solver export RUN_ID --output PACKAGE.json [--store PATH]
solver validate-evidence BUNDLE
solver response-plan SELECTION.json --checkpoint CHECKPOINT.json
solver response-run SELECTION.json --checkpoint CHECKPOINT.json
solver response-resume SELECTION.json --checkpoint CHECKPOINT.json
solver response-validate SELECTION.json --checkpoint CHECKPOINT.json
solver campaign-plan SELECTION.json [--profile survey|certify|validate]
solver campaign-run SELECTION.json --checkpoint CHECKPOINT.json [--profile survey] [--progress quiet|normal|trace]
solver campaign-resume SELECTION.json --checkpoint CHECKPOINT.json [--profile survey|certify|validate] [--progress quiet|normal|trace]
solver campaign-validate SELECTION.json --checkpoint CHECKPOINT.json [--profile survey|certify|validate] [--full]
solver campaign-merge MANIFEST.json --output CHECKPOINT.json
solver campaign-cache-import SELECTION.json --checkpoint CHECKPOINT.json [--store PATH]
solver campaign-reduce REDUCTION-BUNDLE.json --output REDUCTION.json
solver campaign-smoke
solver m02-validate ADMISSION-INPUT.json
solver m02-admit ADMISSION-INPUT.json --output ADMITTED.json
solver m02-export ADMITTED.json --admission-id ID --output EXPORTED.json
solver plan STUDY.json --linear-response-admission ADMITTED.json --linear-response-admission-id ID
solver run STUDY.json --linear-response-admission ADMITTED.json --linear-response-admission-id ID [--store PATH]
```

Every command emits one deterministic JSON value: successful results on stdout and failures on stderr. A provider execution failure returns exit code `1`, invalid input returns `2`, an unavailable provider returns `3`, failed verification returns `4`, and storage/output failure returns `5`. Failed runs include their sealed run record in the structured error and remain available to `inspect`.

`verify --profile research` checks a successful run's complete dependency
closure, artifact hashes, request identity, ordered lineage, provider contracts,
execution accounting, and evidence propagation. `--profile publication` adds
a hard requirement for a complete evidence-package run whose numerical and
scientific dimensions were evaluated. A publication check may still verify an
`UNRESOLVED` or `CONTRADICTED` conclusion: verification establishes intact
evidence, not a favorable scientific outcome.

## Evidence semantics

A result records independent state dimensions:

```text
execution = SUCCEEDED
numerical = CONVERGED
scientific = UNRESOLVED
```

An unresolved or contradicted scientific result may still be a valid, successfully produced artifact. Conversely, a successful process does not prove numerical convergence or a physical claim.

Artifact identities cover the capability-scoped study inputs, mechanism and convention identities, equations, provider implementation, runtime, relevant numerical policy, upstream artifacts, evidence, and payload. Repeating an identical request reuses the verified artifact and performs zero provider work. A numerical-policy key named for a capability applies only to that capability; other policy keys are global. Changing a detector-only policy therefore reuses unchanged spectral and response artifacts.

Run records are content-sealed and verification reconstructs the expected
capability closure rather than trusting the record's artifact list. Cache
bindings are accepted only when their key recomputes from the loaded artifact's
capability, provider, request, and ordered upstream identities.
The run record retains the complete user request, while each provider receives
only its canonical capability-scoped request. Upstream artifacts are exposed as
deeply immutable snapshots so a provider cannot change an input after its
identity was computed.

See [architecture.md](docs/architecture.md) for the dependency graph, provider admission rules, and artifact contract.

## Development

```text
python -m compileall -q src tests
python -m unittest discover -s tests -v
```

The core package requires Python 3.12 and has no required dependencies outside
the standard library. The offline lattice builder and native response kernel
use the pinned numerical extra; promoted M02 execution additionally uses the
solver-managed Julia environment. The installed spectral provider itself
selects exact rows from the hash-authenticated packaged result.

<!-- TASKPLANNER:ATTRIBUTION:START -->
This project uses [TaskPlanner](https://github.com/smekai/taskplanner) for task planning.
<!-- TASKPLANNER:ATTRIBUTION:END -->
