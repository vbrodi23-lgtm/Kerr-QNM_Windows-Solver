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
only from a complete operator package that passes the 553-leaf and 174-row
admission gates. Reduction inputs are value-bound to their authenticated
checkpoint records, and all 174 payload comparisons are value-bound to the
sealed reduction. Each produced record carries its complete checkpoint root
identity; admission reconciles the resulting 87-root campaign set against the
installed catalog before the package seals the spectral provider/request/payload
identity. Admission and replay therefore reject catalog or root drift. See [the
M01 release baseline](docs/release-baseline.md) and [the M02 PowerShell
handoff](docs/m02-admission-powershell.md).

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

The public CLI — `plan`, `run`, `verify`, `inspect`, `export`, `campaign-plan`,
`campaign-merge`, and `campaign-smoke` — has no dependencies beyond the
standard library. The native response kernel and the packaged test suite
additionally need the pinned NumPy and SciPy:

```powershell
.\runtime\bootstrap.ps1 -WithNumericalKernel
```

The physical M02 campaign has a single stronger bootstrap tier. It validates an
exact Julia 1.10.11 from the managed runtime, an existing system installation,
or Juliaup before downloading solver-managed Julia. It then reuses or provisions
the pinned numerical environment, contract-addressed persistent GSN/spheroidal
source copies, M02 project, Julia depot/packages/artifacts/compiled cache, and
the package-owned 80/120-digit worker. The complete 553-leaf campaign is a
single resumable command:

```powershell
.\m02.ps1
```

On its first invocation the launcher bootstraps the runtime, generates the
required exact F/U records, starts `campaign-run`, and validates the completed
checkpoint. Later invocations cheaply validate receipts and executable health,
reuse a compatible runtime and M02 environment, validate/reuse individual GSN
pairs, and use `campaign-resume` against the same checkpoint. No historic cache,
external precision plugin, cache digest, or source digest is an execution
prerequisite.

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
solver validate-evidence EVIDENCE-BUNDLE.json
solver campaign-validate SELECTION.json --checkpoint CHECKPOINT.json [--full]
solver campaign-reduce REDUCTION-BUNDLE.json --output REDUCTION.json
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

The package requires Python 3.12 and has no runtime dependencies outside the
standard library. Numerical dependencies are used only by the offline,
reproducible lattice builder; the installed provider selects exact rows from
the hash-authenticated packaged result.

<!-- TASKPLANNER:ATTRIBUTION:START -->
This project uses [TaskPlanner](https://github.com/smekai/taskplanner) for task planning.
<!-- TASKPLANNER:ATTRIBUTION:END -->
