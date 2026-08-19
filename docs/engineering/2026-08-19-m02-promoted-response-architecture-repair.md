# M02 promoted-response architecture repair

This note records the implementation boundary for the PR #55 repair. It is
derived from the operator-supplied architecture specification. No Kerr
determinant, Julia worker, radial or coordinate ODE, angular solve, QNM root
solve, M02 campaign, or production PowerShell script was run while preparing
this change. All evidence cited here is synthetic Python, canonical
serialization/migration, compilation, or static Julia/PowerShell inspection.

## Calculation identities

- Ordinary promoted exterior response:
  `fixed-root-exterior-derivative-component/v1`, using one authenticated
  zero-amplitude root and fixed-root determinant samples at real `h` and `h/2`.
- Exterior uncertainty:
  `exterior-derivative-response-disk/v1`, with `g = -D_c/D_omega` and a typed
  unusable outcome whenever the denominator disk contains zero.
- Optional fixed-root axis validation:
  `fixed-root-holomorphic-axis-validation/v1`. The historical perturbed-root
  ladder remains separate as `full-complex-ladder-validation/v1` and requires
  `RISK_SELECTED_SENTINEL`, `DERIVATIVE_DISAGREEMENT`, or
  `PUBLICATION_VALIDATION`.
- Promoted horizon response:
  `single-promoted-root-bounded-analytic-horizon-component/v2`, with explicit
  disks for `p_H` and `Dprime` and analytic inversion only after the product
  disk excludes zero.
- Horizon endpoint recovery: deterministic depth-first-per-order search,
  independent ingoing/outgoing best prefixes, cached geometry, two verified
  endpoints, and policy-bound canonical evidence. Successful searches are
  persisted in worker wire schema 9 and sealed into response-receipt schema 3;
  wire schema 8/receipt schema 2 and wire schemas 3--7/receipt schema 1 remain
  read-only historical evidence. The old five order-28 rows for mode 222 at
  `a/M=0.9999` remain an exact regression fixture.
- Precision order is semantic:
  `binary64 -> bigfloat-40 -> bigfloat-80 -> bigfloat-120`. Decimal digits and
  MPFR bits are recorded separately; integer 40 is not inserted into the
  historical `64/80/120` presentation set.

## Recovery and evidence boundaries

Safe-window recovery enumerates every consecutive window containing at least
four amplitude levels. A candidate must pass both-axis signal, branch,
real/imaginary Richardson-order, even-remainder, axis-consistency, and
diagnostic gates. The deterministic winner is the finest admissible window;
every finer exclusion carries its reason. When no window exists, mode 220 and
330 request `0.008, 0.016`, while mode 440 requests `0.008, 0.016, 0.032`,
before any precision promotion. Promotion names only the failing signed axis
pair and begins at `bigfloat-40`.

`PartialComponentJournal` authenticates and atomically records baseline roots,
fixed-root determinant samples, variational/direct stencil work, signed
validation roots, and diagnostic readouts. Resume validates the complete
journal, reuses exact entries, schedules only missing identities, rejects a
conflicting receipt, and preserves terminal journals as provenance.

Promoted fixed-root determinant coordinates, values, and absolute-error bounds
are parsed from the sealed worker decimal text. Finite differences are formed
with `Decimal` arithmetic at a precision derived from the worker tier, and the
resulting derivative and analytic-horizon disks are converted to binary64 only
through an outward-rounding containment step. A long BigFloat decimal therefore
cannot be silently collapsed before the response centre or radius is derived.

Checkpoint migration authenticates the exact source SHA-256 and canonical
bytes, parses real `CampaignLeafRecord` and `CampaignExecutionAttempt`
structures under the historical schema-7 bindings, refuses an existing
destination, and emits a normal loadable/resumable schema-8 checkpoint plus a
separate authenticated migration receipt. Only nested evidence whose endpoint
policy identity changed is invalidated; compatible binary64 evidence is
retained and the stopped source checkpoint is never rewritten. The live
scientific identity binds
`single-promoted-root-bounded-analytic-horizon-component/v2` and the fixed-root
exterior derivative/disk/validation policies; schema 7 retains its historical
`single-promoted-root-analytic-horizon-component/v1` contract.

The nearest-adequate outer endpoint policy records the complete monotone
candidate schedule ending at the existing cap, all rejection reasons, and the
selected candidate. A promoted ODE request must consume an authenticated
request-level error budget. Every calibrated budget reachable by a leaf is
bound into that leaf's scientific execution contract and solved-leaf identity;
checkpoint resume, cache lookup, cache publication, promoted runtime evidence,
and nested journal/request evidence are revalidated against the active
contract. A budget-free predecessor cache entry is historical evidence only
and is not migrated into a calibrated identity. Operational runtime provenance
continues to exclude the budget fields, while the complete scientific-runtime
digest includes them. The repository still lacks a justified conversion from
determinant/root error to local ODE tolerances:

`TODO: [HUMAN MATH REVIEW REQUIRED - calibrated conversion from determinant/root error budget to ODE local tolerances is not yet established]`

No fixed tolerance table is renamed or treated as calibration. Variational
exterior differentiation is likewise not called independent while it shares
the production equation and transport implementation; the admitted production
fallback remains direct fixed-root determinant differentiation.

## Operator-only commands

Run these only in the native operator environment after reviewing the output
and cache destinations:

```powershell
.\M02_Production_222_A9999_Endpoint_Recovery_v1.ps1
.\M02_Production_LightRing_A9999_Response_Recovery_v1.ps1 -ExerciseInterruptionResume
```

The first command selects only the primary 222, `a/M=0.9999`,
`horizon-admittance` leaf and reports either a genuinely produced row or a
richer typed diagnostic; a diagnostic-only result is not success. The second
selects only the three exact 220/330/440 light-ring leaf IDs and can deliberately
stop after one journaled readout, resume, and prove that exact work unit was
reused rather than recomputed. Both scripts use isolated output, root-readout
cache, and partial-journal roots and validate their resulting checkpoints. The
interruption path terminates and waits for the process tree, resumes only when
a valid campaign checkpoint exists, and otherwise cold-starts the campaign so
the already committed partial-journal entry is reused.

## Acceptance boundary

Repository tests establish software contracts only. Mathematical correctness,
the winning 222 endpoint pair/order, performance, native PowerShell behavior,
and physical M02 results remain operator evidence. TASK-079 and the M02
milestone must remain open until those receipts and the required human
mathematics review exist.
