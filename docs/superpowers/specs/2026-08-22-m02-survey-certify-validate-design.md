# M02 Atlas Production and Evidence Profiles Design

**Date:** 2026-08-22
**Status:** Approved for implementation
**Scope:** PR #63

## Decision

M02 will use one mechanism-general numerical engine governed by an explicit
execution profile:

- `survey` obtains bounded central responses for the provisional atlas;
- `certify` adds the existing heavy local uncertainty evidence to retained
  survey results;
- `validate` adds the existing independent and full-ladder publication
  evidence.

The numerical terminal state and the evidence level remain independent. A
leaf can be numerically `PRODUCED` while its evidence level is only
`SCREENED`. Evidence progresses monotonically through `SCREENED`, `CERTIFIED`,
and `VALIDATED`; stronger evidence is never overwritten or downgraded.

`survey` is the default profile used by `m02.ps1`.

## Domain model

`ExecutionProfile` is a closed enum with `SURVEY`, `CERTIFY`, and `VALIDATE`.
`EvidenceLevel` is a closed ordered enum with `SCREENED`, `CERTIFIED`, and
`VALIDATED`. A versioned additive evidence record binds:

- the leaf ID;
- the execution profile that produced the evidence;
- the achieved evidence level;
- the retained central-response stage digest;
- the evidence receipt digests accumulated by later profiles;
- any certification discrepancy requiring review.

The evidence record is persisted separately from the numerical terminal state
so `PRODUCED`, `UNRESOLVED`, `REJECTED`, and failure states keep their existing
meaning.

Historical schema-9 completed evidence migrates without numerical execution.
Canonical completed records map to at least `CERTIFIED`. A historical record
maps to `VALIDATED` only when its stored component evidence proves an explicit
independent/full-ladder validation route. Migration is monotone and additive.

## One policy, one solver

The campaign runner receives one `CampaignExecutionPolicy` selected from the
profile. The policy controls which existing numerical operations are allowed;
it does not introduce new equations, tolerances, derivative formulas, or
uncertainty formulas.

The policy exposes explicit operation permissions:

| Operation | survey | certify | validate |
| --- | ---: | ---: | ---: |
| shared authenticated root acquisition | yes | reuse | reuse |
| fixed-root Dω and D_c | yes | yes | yes |
| one cheap derivative refinement | yes | yes | yes |
| truncation/resolution/seed-path root solves | no | existing policy | existing policy |
| 2h/ih derivative ladders | no | existing policy | yes when selected |
| full signed finite-amplitude root ladder | no | no | yes |
| independent publication validation | no | no | yes |
| automatic maximum-tier escalation | no | existing policy | existing policy |

Calls reach the existing numerical components through this policy field. There
are no profile-specific solver copies.

## Survey execution

### Shared background seal

Survey root work is owned by a background identity rather than a mechanism
leaf. A `BackgroundRootKey` contains every field required for safe reuse:

- authenticated spectral-root identity and branch;
- equation and determinant family;
- determinant normalisation;
- backend identity;
- numerical-control identity;
- precision tier and working precision;
- spin and mode identity;
- zero-coupling background identity.

The cache requires exact key equality. A mismatch in any field fails closed and
causes independent evidence acquisition; it never falls back to approximate or
partial matching. A mechanism-bound `PromotedRootSeal` is derived from the
shared authenticated background evidence without calling `read_root()`.

The fixed-root Dω cache uses the same exact key plus the derivative method and
step identity. Consequently, exterior mechanisms may share Dω only when the
root seal, determinant family, normalisation, controls, precision, derivative
method, and background identity match exactly.

### Horizon

The horizon survey retains the efficient existing route:

authenticated root → retained Dω → analytic horizon response → bounded
response disk.

No new work is added to this path.

### Exterior mechanisms

Every exterior mechanism registered in the campaign domain follows the same
route:

authenticated shared background root → mechanism-bound `PromotedRootSeal` →
fixed-root Dω → mechanism-specific fixed-root D_c → −D_c/Dω → one existing
cheap refinement → existing bounded response disk.

The path accepts any registered exterior mechanism and does not branch on
light ring or on a fixed list of mode labels. Once a valid background seal is
supplied, the survey response executor has no root-read API in its interface;
therefore it cannot make a new `read_root()` call.

Survey uses binary64 first. It selects the lowest configured promoted tier only
when the current tier cannot yield a bounded response. It records an unresolved
leaf and advances after a contained precision, resource, branch, or control
failure. Survey never requests 120 digits merely because 120 is available.

## Certification and validation

`certify` requires an existing `SCREENED` (or stronger) central response. It
runs the current heavy local uncertainty machinery and appends its evidence.
The retained survey centre remains authoritative. If the certification centre
falls outside the screened disk, the evidence record gains a discrepancy and
the leaf does not silently advance to `CERTIFIED`.

`validate` requires an existing `CERTIFIED` (or stronger) leaf. It owns full
signed finite-amplitude root ladders, independent derivative routes, and other
publication-selected checks. Successful validation appends evidence and raises
the level to `VALIDATED`.

Release admission and publication reduction require at least `CERTIFIED`, and
publication validation outputs may require `VALIDATED`. `SCREENED` results are
available to atlas and triage projections only.

## Whole-atlas triage

After survey, a deterministic triage projection ranks:

1. unresolved and failed leaves;
2. disks containing or approaching zero;
3. largest relative response disks;
4. binary64/promoted disagreements;
5. derivative disagreements;
6. branch-risk leaves;
7. smallest projective-angle rows;
8. leaves controlling projective classification;
9. at least one sentinel from every mechanism and mode family.

The result contains an explicit, ordered certification queue with machine-
readable reasons. Mode and mechanism coverage is derived from the plan; no
present seven-mode table is embedded in the policy or triage logic.

## Persistence and reporting

Checkpoint schema 10 adds the execution profile and evidence ledger while
retaining all historical numerical stages and attempts. Loading a schema-9
checkpoint performs an in-place, computation-free migration at the normal
atomic checkpoint boundary. Existing solved-leaf receipts remain valid and
gain monotone inferred evidence on import/reuse.

CSV and dashboard rows report both terminal state and evidence state. Summary
counts are separate for `SCREENED`, `CERTIFIED`, `VALIDATED`, `UNRESOLVED`,
`REJECTED`, and `FAILED`. Atlas progress is the count of leaves with at least
screened evidence; certification and validation progress are shown
independently.

## Compatibility and exclusions

- The Kerr/GSN equations, branch rules, tolerances, derivative formulas, and
  uncertainty formulas do not change.
- Existing heavy machinery remains present behind `certify` and `validate`.
- No K2 modes are added in this PR.
- Mode ordering, cache keys, and sentinel coverage are derived from the plan,
  so later modes such as 332 and 442 enter the same pipeline.
- No production solver, Julia numerical worker, Kerr/QNM campaign, or
  PowerShell numerical execution is part of development verification.

## Regression proof

Static, contract, migration, and mocked orchestration tests must prove all
twelve requirements in the PR specification, including zero post-seal root
calls, forbidden survey operations, exact Dω reuse, fail-closed mismatches,
continue-on-failure, computation-free migration, monotone evidence, admission
separation, retained heavy paths, reporting separation, and coverage of every
registered exterior mechanism.
