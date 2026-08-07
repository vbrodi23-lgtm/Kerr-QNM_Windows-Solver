# M01 Release Scope and Authenticated Evidence Baseline

**Status:** Closed for review on 2026-08-07. The machine-readable authority is
[`release_domain_manifest.json`](../src/windows_solver/data/release_domain_manifest.json),
whose packaged SHA-256 is
`697c92744e098fe409f481bcfa0ebeecfc61cd222291e36cd4158fbc5857b742`.

M01 freezes the completion domain before any downstream scientific provider is
migrated. It does not add or modify spectral rows. PR #2 remains the immutable
2,736-root numerical baseline. PR #3 delivers this scope and evidence boundary;
PR #4 begins the separate `linear-response` migration.

## Frozen release domain

| Coordinate | Required release scope |
|---|---|
| Theories | General relativity; parity-even cubic higher-curvature EFT |
| Evidence profiles | Research; publication |
| Platforms | Native Windows PowerShell 5.1 with CPython 3.12 x64; Ubuntu CPython 3.12 x64; OCI Linux amd64 with CPython 3.12 |
| Pure-Kerr spectrum | s=−2; ℓ∈{2,3,4}; every allowed m; n∈{0,1,2}; 63 modes; 2,736 exact roots on the accepted 46/46/40 spin grids |
| Linear modes | Primary: 220, 221, 222, 330, 331, 440, 441; controls: 210, 2−20, 320, 3−30 |
| Near-extremal coordinates | Direct a/M values 0.95, 0.97, 0.98, 0.99, 0.995, 0.997, 0.999, 0.9995, 0.9999; surface-gravity values 0.01, 0.005, 0.002, 0.001 |
| Response mechanisms | Horizon admittance; fixed-r3, light-ring, throat-κ, α=0, α=1/2, and α=1 exterior profiles; cubic EFT |
| Branch classes | Damped; zero-damping; unresolved; all tied to explicit Schwarzschild-overtone continuation records |
| Quadratic case | 220-plus × 220-plus; forced m=4; Ω=ω₁+ω₂; observable R-plus-plus-44; a/M∈{0,0.3,0.5,0.7,0.9,0.95} |
| Waveforms | Causal linear multimode; quadratic 220×220; Ψ₄-to-strain; tails and greybody quantities |
| Detector cases | `gw250114-h1-l1`; `lisa-equal-arm-tdi-x-reference` |

The exact arrays, mechanism IDs, detector inputs, output contracts, and
milestone mapping are validated from the machine-readable manifest. New values
cannot be introduced by narrative documentation or provider code alone.

## Claim reconciliation

| Claim | Classification | Strongest supported statement | Production dependency |
|---|---|---|---:|
| Public problem contract | Publicly admitted | Requests are strict, immutable, and content-addressed | Yes |
| Public pure-Kerr spectrum | Publicly admitted | All 2,736 stored roots pass the recorded numerical gates and 392 independent exact-coordinate comparisons | Yes |
| Spectral fields and genealogy | Missing | No normalized fields, co-modes, residues, or near-extremal genealogy are admitted | No |
| First-order ORG reference | Validated retained evidence | Reconstructions at a/M=0 and 0.7 pass their recorded local residual and overlap gates | No |
| Cubic-EFT 220 reference | Validated retained evidence | Eight plus/minus benchmark disks at a/M∈{0,0.3,0.5,0.7} reproduce the authenticated published disks | No |
| Public linear response | Framework only | No public provider or release-domain response evidence is admitted | No |
| Operator stability | Framework only | Retained code is not proof-bearing continuum evidence | No |
| Quadratic ringdown | Framework only | Retained code is not an authenticated physical source and forced solution | No |
| Response matrix | Framework only | No physical matrix with authenticated linear and quadratic blocks is admitted | No |
| Inverse inference | Framework only | Inference scaffolding is not evidence for a physical posterior | No |
| Signals | Framework only | Signal scaffolding is not an authenticated causal waveform | No |
| Ground and space detector evidence | Missing | Strain, PSD, response, likelihood, and independent-oracle receipts remain required | No |
| Canonical evidence package | Missing | Cross-platform cold-run, equivalence, cache-reuse, and license evidence remain required | No |

Only `problem-contract` and `spectral-core` have active production owners. The
validator compares those declared IDs with the actual provider registry and
rejects any mismatch.

## Authenticated source boundary

The public spectrum remains bound to the accepted PR #2 commit
`da313b60faa3f2c5fff93cf9f4669c8c0091dab5`:

| Artifact | SHA-256 |
|---|---|
| Pure-Kerr catalog | `9ebae4271309cd45a1b26c90d31155602ed8ef33bb79069adb5897e8afe7a564` |
| Catalog receipt | `61a428a858de1eb7e42fe4cbbda37bf1fddcc808d98be2a62fd33ef4b5b74379` |
| Offline generator | `6f9a4e7b82a01c14768ff431fbc55c8cdbf25641d909b34c204d80a54eceded9` |

The first-order ORG evidence is bound to retained merged-PR bytes. For each of
a/M=0 and 0.7, the manifest records the parent NPZ, reconstructed NPZ, output
receipt, Git blob identity, SHA-256, generator blob, tests, MIT license,
runtime, and convention. These bytes are golden comparison evidence and are
not imported by the installed solver.

The cubic-EFT evidence records five retained output artifacts, the exact
external potential and plus/minus published-table hashes, the source commit,
generator blob, merged PR, tests, runtime, and conventions. The authenticated
external source is GPL-3.0. It is restricted to offline comparison and
must not be copied into or linked by the proprietary public runtime without a
separate license decision.

Unavailable inputs carry null content identities, an owner, and an explicit
unblock action. The validator rejects a missing receipt if it is rewritten as
available without immutable bytes, or if an admitted claim refers to it.

## Module ownership

| Role | Public responsibility |
|---|---|
| Active provider | `ProblemContractProvider`; `SpectralCatalogProvider` |
| Validator | Study contracts, untrusted payload boundary, release manifest and command, offline angular/continued-fraction backends, offline lattice builder |
| Infrastructure | Artifact envelope, provider registry, dependency planner, engine, CLI, module entry point, native Windows launcher |
| Retired fixture | Retained first-order ORG evidence bundle |
| Comparator | Retained cubic-EFT calculation and authenticated external source |

There is exactly one active owner for each admitted capability. Comparator,
extension, and retired-fixture records are forbidden from production
dependency closure. Any replacement must pass the record-specific golden,
identity, numerical, and adverse-input gate first.

## Equations and conventions

The manifest treats these as artifact identity, not explanatory metadata:

- pure-Kerr roots use the coupled angular/Leaver equations, exp(−iωt+imφ),
  ingoing horizon and outgoing infinity conditions, Mω, a/M, s=−2, and explicit
  branch continuation;
- first-order retained evidence uses regular Hertz reconstruction in outgoing
  radiation gauge with a Kinnersley tetrad and its recorded parent
  normalization;
- the cubic 220 comparator uses the authenticated mode-conditioned separated
  potential, both polarizations, order-18 spin source, 17-over-1 Padé
  resummation, Mω, and shift per unit cubic coupling;
- the quadratic requirement uses outgoing radiation gauge parents, a
  Kinnersley tetrad, unit parent strain at future null infinity, Ω=ω₁+ω₂, and
  m=m₁+m₂;
- waveforms retain field identity through causal evolution, Ψ₄-to-strain
  conversion, propagation, and detector projection; those operations cannot be
  collapsed into one unsupported amplitude.

Disputed or absent conventions are blockers. The validator does not infer
gauge, tetrad, sign, units, branch, or normalization from a filename.

## Evidence ceilings

Numerical acceptance and scientific support remain independent:

| Evidence class | Numerical ceiling | Scientific ceiling | Formal enclosure |
|---|---|---|---:|
| Problem contract | ACCEPTED | NOT_EVALUATED | No |
| Public pure-Kerr roots | ACCEPTED | NOT_EVALUATED | No |
| Retained first-order ORG | ACCEPTED | NOT_EVALUATED | No |
| Retained cubic-EFT benchmark | ACCEPTED | CONDITIONALLY_SUPPORTED | No |
| Framework only | NOT_EVALUATED | NOT_EVALUATED | No |
| Missing input | NOT_EVALUATED | NOT_EVALUATED | No |

The cubic benchmark ceiling is limited to the eight mode-conditioned 220
disks. It does not establish a universal two-dimensional EFT operator, a
seven-mode physical response, quadratic amplitudes, waveforms, or detector
evidence.

## Governance decisions and blockers

- PR #2 is immutable accepted spectral evidence.
- PR #3 is M01. PR #4 begins linear response.
- Retained and external evidence never owns a public provider.
- Pole shifts, quadratic amplitudes, response matrices, waveforms, and detector
  evidence are separate artifact layers.
- Missing inputs block their associated capabilities without blocking M01
  closure.

The unresolved ledger covers linear-response disks; spectral fields and
genealogy; operator continuum evidence; physical quadratic evidence; the
response matrix; inverse and waveform evidence; ground- and space-detector
inputs; containers; and cross-platform publication evidence. Each item has a
named programme milestone and unblock action in the manifest.

## Verification

Run from a source checkout:

```text
python -m unittest tests.test_release_manifest -v
python tools/validate_release_manifest.py
python -m unittest discover -s tests -v
```

The focused suite covers complete scope, exact hashes, provider ownership,
missing-receipt promotion, non-production dependency quarantine, duplicate
JSON keys, and immutable in-memory access. The command validates the packaged
byte hash and prints one machine-readable summary.

M01 is complete when this human reconciliation and the automated validator
agree on the same manifest bytes. Future missing science is expected and
blocks the corresponding later capability; it does not authorize a weaker
substitute and it does not reopen the accepted spectrum.
