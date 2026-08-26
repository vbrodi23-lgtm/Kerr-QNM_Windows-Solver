# PR GOVERNING CONTRACT — LOCK BINARY64 LAYER 1 AND CONTINUE INTO PROMOTED LAYER 2

## STATUS

This is a binding implementation contract for one standalone pull request.

It begins only after the dashboard PR is merged or otherwise separated cleanly.

It governs:

```text
Layer 1
    completed schema-11 BINARY64 SURVEY evidence

Layer 1 lock
    immutable authenticated handoff receipt

Layer 2
    promoted RESPONSE continuation
        172 exterior jobs beginning at BF40
         40 horizon jobs beginning at BF80
```

This PR must not redesign the dashboard.

It may emit existing typed progress events and expose lock metadata for the already-governed dashboard projection.

No production solver execution is permitted by the development agent.

No Julia worker may be launched by the development agent.

No M02 campaign may be run by the development agent.

---

# 1. CONTROLLING ARTIFACT

The completed operator-produced binary64 checkpoint is the controlling incident fixture.

Its scientific identity is:

```text
campaign ID
b-prime-campaign-ff79db99415efc7613df238129c2ad261380147d24723ea927f13ef749afd2d4

selection ID
campaign-selection-36872f8039df4fa7fa1986fa777624b6b9645f657acf87914e4058ffce925b9b

checkpoint schema
11

wiring-audit source head
1c952fa1e16fe1f41e55d8f527064dc141d5506b
```

Its observed Layer-1 inventory is:

```text
selected leaves                              212
binary64 pass-ledger entries                 212
pending promotion entries                    212
queue kind RESPONSE                          212
final numerical records                        0
system failures                                0
root reads                                     0
Julia worker launches                          0
```

The route partition is:

```text
exterior RESPONSE → BF40                     172
horizon RESPONSE  → BF80                      40
                                              ---
                                              212
```

The retained exterior binary64 work is:

```text
full 9-sample acquisitions                    48
4-sample mechanism acquisitions              124
                                               ---
                                               172

retained determinant evaluations
48 × 9 + 124 × 4 = 928
```

These identities are conservation laws for the controlling artifact.

They were independently checked:

```text
212 = 172 + 40
172 = 48 + 124
928 = 48 × 9 + 124 × 4
```

---

# 2. PURPOSE

Layer 1 must become an immutable scientific input to Layer 2.

Layer 2 must continue from Layer 1.

It must not recreate Layer 1.

The exact objective is:

```text
authenticate and freeze every binary64 source object
→ bind every pending promotion to that frozen source
→ consume the source at the correct next tier
→ add new promoted evidence
→ preserve every Layer-1 byte and digest
```

The performance promise is not “BF40 costs half as much.”

The enforceable promise is:

```text
binary64 numerical work repeated in Layer 2       0
binary64 worker launches in Layer 2               0
binary64 determinant evaluations in Layer 2       0
Layer-1 provisional stages mutated                0
```

BF40 and BF80 still require new arithmetic at their own precision.

---

# 3. ARCHITECTURE

## 3.1 New lock owner

Add one module, preferably:

```text
src/windows_solver/binary64_layer_lock.py
```

Recommended public operations:

```python
def project_binary64_layer(...): ...
def build_binary64_layer_lock(...): ...
def validate_binary64_layer_lock(...): ...
def assert_binary64_layer_unchanged(...): ...
```

The exact names may differ.

The ownership may not differ:

> One module owns the canonical Layer-1 projection, lock receipt, validation, and mutation check.

No scheduler, CLI, cache importer, or dashboard may reimplement the lock hash.

## 3.2 Sidecar receipt

Do not force a schema-11 checkpoint migration merely to lock an already completed operator artifact.

Use an atomic sidecar:

```text
<checkpoint>.binary64-lock.json
```

Recommended schema:

```text
windows-solver.binary64-layer-lock/1
```

The sidecar must be deterministic and digest-bound.

Do not include a timestamp in digest material.

---


# 3A. REQUIRED WIRING AND CONNECTIONS — ADDITIVE

This section is additive.

It does not replace, relax, reinterpret, or supersede any requirement elsewhere in this contract.

Do not redesign the solver.

Do not add a second promoted scheduler.

Do not add another checkpoint.

Do not duplicate queue, lock, cache, root, or evidence policy.

The implementation must extend the repository’s existing schema-11 production path.

## 3A.1 Wiring audit baseline

The wiring audit for this addendum was performed against:

```text
main head
1c952fa1e16fe1f41e55d8f527064dc141d5506b
```

The current production route is already:

```text
m02.ps1
→ solver.ps1
→ cli.py
→ _run_schema11_pass_with_diagnostics(...)
→ _campaign_schema11_pass(...)
→ campaign_runtime.run_native_promoted_pass(...)
→ campaign_survey.run_promoted_survey(...)
```

The current runtime adapter already connects:

```text
root_seal_lookup
provisional_stage_lookup
root_seal_publish
backend_factory
primary_root_runner
horizon_runner
promoted_horizon_runner
produced_record_builder
determinant_error_store
solved_leaf_store
record_validator
terminal_record_committed
checkpoint_committed
diagnostic_session
```

Extend this exact seam.

Do not bypass it.

The repository already has:

```text
src/windows_solver/production_wiring.py
```

Extend that guard to require every new capability introduced below.

## 3A.2 Required end-to-end call graph

```text
m02.ps1
│
├── campaign-survey-binary64
│     │
│     └── cli.py
│           │
│           └── run_native_binary64_pass(...)
│                 │
│                 ├── run_binary64_survey(...)
│                 ├── prove pass exhaustion
│                 ├── build Layer-1 lock
│                 └── atomically write:
│                       <checkpoint>.binary64-lock.json
│
├── campaign-lock-binary64
│     │
│     └── cli.py
│           │
│           ├── load plan/selection/checkpoint
│           ├── open root/background stores read-only
│           ├── project and authenticate Layer 1
│           └── write deterministic lock sidecar
│
└── campaign-survey-promoted
      │
      └── cli.py
            │
            ├── resolve lock path
            └── run_native_promoted_pass(...)
                  │
                  ├── validate lock before publication/backend construction
                  ├── build cache-first execution plan
                  ├── prove exterior admission capability
                  ├── construct lazy runtime capabilities
                  └── run_promoted_survey(...)
                        │
                        ├── cache supersession
                        ├── exterior → BF40 first
                        ├── horizon → BF80 only
                        ├── guarded checkpoint persistence
                        ├── terminal/root/background publication
                        └── queue conservation
```

There remains:

```text
one schema-11 checkpoint
one binary64 pass ledger
one promoted pass ledger
one promotion queue
one solved-leaf store
one root-evidence store
one Layer-1 lock projection
```

## 3A.3 Exact file ownership

| File | Wiring responsibility |
|---|---|
| `m02.ps1` | Command order and lock-path propagation only |
| `src/windows_solver/cli.py` | CLI command/argument surface and runtime handoff |
| `src/windows_solver/binary64_layer_lock.py` | Sole owner of Layer-1 projection, lock schema, load/write, validation, route bindings, and mutation diagnostics |
| `src/windows_solver/campaign_runtime.py` | Production composition root; validates lock and connects stores, issuers, providers, backends, and scheduler |
| `src/windows_solver/campaign_survey.py` | Queue order, cache-first decisions, route dispatch, tier ladder, one persist choke point, and conservation |
| `src/windows_solver/campaign_policy.py` | Idempotent/conflict-safe ledger and queue mutations |
| `src/windows_solver/response_engine.py` | Typed validation/parsing of locked binary64 provisional evidence |
| `src/windows_solver/julia_response_backend.py` | BF40/BF80 numerical production only |
| `src/windows_solver/background_evidence_store.py` | Binary64 background store and separate tier-bound promoted background store |
| `src/windows_solver/reviewed_determinant_error_issuance.py` | Sole owner of three-term empirical error issuance |
| `src/windows_solver/reviewed_determinant_error.py` | Claim/receipt validation and content-addressed publication |
| `src/windows_solver/root_evidence.py` | Root dependency and authenticated root evidence |
| `src/windows_solver/root_readout_cache.py` | Durable root-evidence store |
| `src/windows_solver/structural_diagnostics.py` | Append-only connection events |
| `src/windows_solver/production_wiring.py` | Static proof that production capabilities are connected |
| tests | Dynamic proof of call order and zero forbidden work |

## 3A.4 Lock path owner

Add one Python path owner:

```python
def binary64_layer_lock_path(checkpoint_path: Path) -> Path:
    return Path(f"{checkpoint_path}.binary64-lock.json")
```

Every Python caller uses it.

Do not independently reproduce the suffix in CLI, runtime, tests, diagnostics, or dashboard code.

## 3A.5 CLI wiring

Add:

```text
campaign-lock-binary64
```

Inputs:

```text
selection
--checkpoint
--output, optional
```

Default output:

```text
binary64_layer_lock_path(checkpoint)
```

Add:

```text
campaign-survey-promoted --binary64-lock <path>
campaign-schema11-validate --pass promoted --binary64-lock <path>
```

The lock path must flow through:

```text
main(...)
→ _run_schema11_pass_with_diagnostics(...)
→ _campaign_schema11_pass(...)
→ run_native_promoted_pass(...)
```

CLI validation is not sufficient by itself.

The runtime must validate the lock again because the runtime is the production boundary.

## 3A.6 PowerShell wiring

For:

```powershell
-Profile survey -SurveyPass promoted
```

`m02.ps1` must perform:

```text
1. Resolve checkpoint.
2. Resolve lock path.
3. Validate checkpoint.
4. If lock exists, continue.
5. If lock is absent, run campaign-lock-binary64.
6. If lock creation fails, stop.
7. Run campaign-survey-promoted with the same lock path.
8. Run promoted post-validation with the same lock path.
```

If the promoted ledger is nonempty and the lock is absent:

```text
do not regenerate
do not infer
do not continue
fail loudly
```

PowerShell does not hash or interpret scientific state.

## 3A.7 Automatic lock after binary64 exhaustion

Change `run_native_binary64_pass(...)` from a direct return to:

```python
survey = run_binary64_survey(...)

if survey.pass_exhausted:
    lock = build_binary64_layer_lock(
        plan=plan,
        selection=recovery_selection,
        checkpoint=survey.checkpoint,
        checkpoint_path=checkpoint_path,
        root_evidence_store=root_evidence_store,
        background_evidence_store=background_store,
    )
    write_binary64_layer_lock_atomic(
        binary64_layer_lock_path(checkpoint_path),
        lock,
    )

return survey
```

The lock is written only after the final binary64 checkpoint is durable.

A lock-write failure must not roll back the checkpoint.

It must fail the command and name the lock path.

## 3A.8 Promoted runtime signature

Extend:

```python
def run_native_promoted_pass(
    ...,
    binary64_lock_path: Path,
    promoted_background_store: PromotedCanonicalBackgroundEvidenceStore | None = None,
    determinant_error_issuer: ExteriorDeterminantErrorIssuer | None = None,
    ...
) -> PromotedSurveyRun:
    ...
```

Required internal order:

```text
1. Validate checkpoint.
2. Load lock.
3. Authenticate lock receipt.
4. Open store handles without mutation.
5. Recompute Layer-1 projection.
6. Compare against lock.
7. Build Layer1Guard.
8. Build locked route map.
9. Perform terminal-cache inventory without backend construction.
10. Resolve exterior determinant-error admission.
11. Only now permit store publication, backend construction, or worker launch.
12. Call run_promoted_survey exactly once.
```

Move the current call to:

```python
_publish_admissible_checkpoint_records(...)
```

after Steps 1–10.

It publishes to the solved-leaf store and therefore must not run before lock and admission preflight.

## 3A.9 Lazy construction rule

Keep the current holder pattern for:

```text
root_provider()
backend()
```

Closures may be defined early.

They may not be invoked before lock validation and admission preflight.

Tests must use sentinels that raise if invoked too early.

## 3A.10 Immutable promoted execution plan

Build one read-only plan from:

```text
validated lock
current checkpoint
central record intake
terminal-cache inventory
```

Recommended shape:

```python
@dataclass(frozen=True, slots=True)
class PromotedExecutionPlan:
    locked_routes_by_ordinal: Mapping[int, LockedPromotionRoute]
    cache_supersessions_by_ordinal: Mapping[int, Mapping[str, object]]
    numerical_ordinals: tuple[int, ...]
    exterior_bf40_ordinals: tuple[int, ...]
    horizon_bf80_ordinals: tuple[int, ...]
    input_pending_count: int
```

The plan prevents `campaign_survey.py` from independently re-deriving route ownership.

Required conservation:

```text
cache supersessions + numerical ordinals
= all locked pending ordinals
```

No ordinal may appear twice.

## 3A.11 Scheduler capability wiring

Extend `run_promoted_survey(...)` with typed capabilities:

```python
layer1_guard: Layer1Guard
locked_routes_by_ordinal: Mapping[int, LockedPromotionRoute]
promoted_background_store: PromotedCanonicalBackgroundEvidenceStore
determinant_error_issuer: ExteriorDeterminantErrorIssuer
```

Do not pass the raw lock mapping into the scheduler.

Extend `production_wiring.py` so `run_native_promoted_pass → run_promoted_survey` must supply all four capabilities.

## 3A.12 Guard the single persist choke point

The existing local `persist(...)` closure is the only promoted checkpoint writer.

Keep one writer and extend it:

```python
def persist(value):
    candidate = validate_schema11_checkpoint(value)

    layer1_guard.assert_unchanged(candidate, phase="PRE_WRITE")

    _atomic_json(path, candidate)

    durable = load_and_validate_schema11_checkpoint(path)

    layer1_guard.assert_unchanged(durable, phase="POST_WRITE")

    if checkpoint_committed is not None:
        durable = validate_schema11_checkpoint(
            checkpoint_committed(durable)
        )

    layer1_guard.assert_unchanged(durable, phase="POST_CALLBACK")

    return durable
```

Every promoted mutation uses this same closure:

```text
initial promoted normalization
cache supersession
completed outcome
unresolved outcome
deferred outcome
rejected outcome
system failure
report refresh
```

No special unguarded writer is permitted.

## 3A.13 Report callback connection

Keep the existing:

```python
checkpoint_committed=lambda value: _refresh_runtime_reports(...)
```

Required order:

```text
guard candidate
write checkpoint
guard durable checkpoint
refresh reports
guard returned checkpoint
```

Report status is excluded from the Layer-1 projection.

Report refresh must therefore pass without changing the lock hash.

## 3A.14 Cache-first connection

Retain the current central record intake:

```text
checkpoint terminal record
→ solved-leaf terminal record
→ authenticate
→ conflict check
→ SUPERSEDED_BY_CACHE
→ numerical route only on genuine miss
```

Cache supersession must:

```text
finish queue entry
record promoted disposition
use guarded persist
perform zero backend work
preserve Layer 1
```

Forensic or stale responses remain ineligible.

## 3A.15 Typed exterior predecessor

Replace the receipt-only handoff.

Current shape:

```python
provisional_predecessor_receipt = (
    consume_authenticated_binary64_provisional_predecessor(...)
)
```

Required shape:

```python
predecessor = (
    consume_authenticated_binary64_provisional_predecessor(...)
)
```

Recommended type:

```python
@dataclass(frozen=True, slots=True)
class AuthenticatedBinary64ExteriorPredecessor:
    stage: Mapping[str, object]
    stage_sha256: str
    reuse_receipt: Mapping[str, object]
    raw_batch: Binary64FixedRootBatch | Binary64ReusedBackgroundBatch
    combined_batch: Binary64FixedRootBatch
    canonical_background: CanonicalExteriorBackground
    background_receipt: BackgroundEquivalenceReceipt
    unique_evaluation_count: int
    combined_role_count: int
```

Required distinction:

```text
unique_evaluation_count
    contributes to the 928 retained-evaluation total

combined_role_count
    supplies the canonical nine roles needed for BF40 comparison
```

For a four-sample sibling:

```text
unique_evaluation_count = 4
combined_role_count      = 9
```

The five shared values come from the authenticated Layer-1 background.

They are not counted again as new evaluations.

## 3A.16 Exterior data flow

For each exterior numerical miss:

```text
locked route by queue ordinal
→ prove EXTERIOR_BF40
→ validate queue source binding
→ consume typed predecessor
→ BF40 background lookup/acquisition
→ BF40 determinant work
→ three-term error issuance
→ screening
→ commit or approved BF80 escalation
```

Pass the typed object into:

```python
_run_promoted_exterior_queue_entry(
    ...,
    predecessor=predecessor,
    promoted_background_store=promoted_background_store,
    determinant_error_issuer=determinant_error_issuer,
)
```

Do not pass only a digest or boolean.

## 3A.17 Separate promoted background store

Do not put BF40/BF80 values into the binary64 background envelope.

Add a sibling owner in:

```text
src/windows_solver/background_evidence_store.py
```

Recommended:

```python
class PromotedCanonicalBackgroundEvidenceStore:
    ...
```

Root:

```text
<checkpoint>.promoted-canonical-backgrounds
```

The key must bind:

```text
locked Layer-1 background-group identity
root seal
precision tier
working precision
determinant family/convention/normalisation
scientific runtime SHA
control-profile SHA
```

Publication:

```text
atomic
idempotent for exact equality
conflict-failing for different content
```

## 3A.18 Same-tier BF40 reuse connection

For each locked exterior group:

```text
first BF40 member
    lookup MISS
    request five background roles
    request four mechanism roles
    publish BF40 background immediately
    total new samples = 9

later BF40 member
    lookup HIT
    request only four mechanism roles
    combine with five durable BF40 background roles
    total new samples = 4
```

The backend already accepts `sample_roles`.

Do not request all nine roles unconditionally.

The same pattern applies at BF80 only for escalated members.

## 3A.19 Determinant-error issuer connection

The current issuance function is a no-op and the current store is load-only.

Wire:

```python
class ExteriorDeterminantErrorIssuer:
    @classmethod
    def from_calibration_receipt(...): ...
    def require_authorized(self) -> None: ...
    def issue_for_batch(...) -> AuthenticatedDeterminantErrorBundle: ...
```

Ownership:

```text
Julia backend
    produces authenticated comparisons

reviewed_determinant_error_issuance.py
    owns term interpretation and 64 × max(...)

reviewed_determinant_error.py
    owns receipt validation and publication

campaign_survey.py
    requests issuance and passes the bundle to screening
```

The scheduler must not implement the multiplier.

## 3A.20 Error-store publication

Add:

```python
ReviewedDeterminantErrorStore.publish(receipt)
```

Semantics:

```text
missing address
    write atomically

identical address
    return existing

different content
    SYSTEM_FAILURE DETERMINANT_ERROR_EVIDENCE_CONFLICT

corrupt trusted address
    fail closed
```

After issuance:

```text
publish all required role receipts
resolve_required(...)
pass bundle to screen_promoted_fixed_root_samples(...)
```

Do not screen from an unpersisted transient disk.

## 3A.21 Exact three-term wiring

For BF40:

```text
delta_cross_precision
    BF40 centre versus locked binary64 centre
    at matching canonical role/frequency/amplitude

delta_same_point
    BF40 base controls versus BF40 tightened controls
    at the same point

delta_endpoint_series
    BF40 base versus approved endpoint/series refinement
    at the same point
```

For BF80 exterior escalation:

```text
delta_cross_precision
    BF80 centre versus retained BF40 centre
```

Every term must bind:

```text
leaf
sample role
root seal
frequency
amplitude
tier
working precision
runtime
control profile
request SHA
response SHA
```

Mismatched points fail.

## 3A.22 Admission preflight before any worker

Compute:

```text
locked exterior routes
minus exact terminal-cache supersessions
= exterior numerical misses
```

If that set is nonempty:

```python
determinant_error_issuer.require_authorized()
```

must pass before:

```text
CAMPAIGN_PASS_STARTED
NativeCampaignStageBackend.from_selection
JuliaPrecisionRootBackend construction
any horizon worker
any exterior worker
any checkpoint mutation
```

If blocked:

```text
return exact human-review blocker
launch zero workers
mutate zero scientific state
```

## 3A.23 Exterior tier ladder

Do not start from a hard-coded `(40, 80)` loop.

Start from the locked route.

Required flow:

```python
for digits in locked_route.permitted_digits:
    background = promoted_background_store.lookup(...)

    sample_roles = (
        FOUR_DC_ROLES
        if background.status == HIT
        else ALL_NINE_ROLES
    )

    batch = backend.fixed_root_survey_batch(
        ...,
        sample_roles=sample_roles,
    )

    combined = combine_with_background_if_required(...)

    error_bundle = determinant_error_issuer.issue_for_batch(
        predecessor=(
            binary64_predecessor
            if digits == 40
            else retained_bf40_predecessor
        ),
        current_batch=combined,
        ...
    )

    screening = screen_promoted_fixed_root_samples(
        ...,
        determinant_error_evidence=error_bundle,
    )

    if produced:
        return COMPLETED

    if digits == 40 and approved numerical insufficiency:
        continue

    return terminal disposition
```

BF40 success stops immediately.

BF80 exterior work occurs only after an approved BF40 numerical insufficiency.

## 3A.24 Horizon connection

For each horizon queue entry:

```text
locked route by queue ordinal
→ prove HORIZON_BF80
→ prove minimum tier BF80
→ validate v3 provisional/source record
→ validate source root seal
→ construct BF80 backend
→ run promoted_horizon_runner
→ prove precision_tiers == ("BF80",)
→ commit
```

No BF40 backend.

No exterior predecessor parser.

No promoted exterior background lookup.

The binary64 provisional stage remains byte-identical inside the resulting record.

## 3A.25 Root-evidence connection

Keep:

```text
RootEvidenceStore.for_checkpoint(checkpoint_path)
```

The lock binds all required Layer-1 root evidence.

Runtime order:

```text
validate lock
lookup exact root dependency
validate branch/seal
run BF80 if required
publish new bounded root evidence immediately
make it available to later compatible leaves
```

New BF80 bounded root evidence is Layer-2 evidence and is excluded from the Layer-1 projection.

## 3A.26 Terminal publication order

Required order:

```text
1. Build promoted outcome.
2. Commit queue disposition, promoted ledger, record, and evidence.
3. Guard Layer 1.
4. Publish terminal record to SolvedLeafStore.
5. Publish new bounded root/background evidence.
6. Emit diagnostics.
7. Advance.
```

If publication fails after checkpoint commit:

```text
preserve committed checkpoint
record system failure against current checkpoint
do not roll back the queue
```

## 3A.27 Mutator connections

### `record_survey_disposition(...)`

```text
missing
    insert

byte-identical existing
    return unchanged

different existing
    fail conflict
```

### `append_promotion(...)`

Index by:

```text
leaf
source pass
queue kind
scientific identity
source record/stage identity
```

Then:

```text
missing
    append

exact existing
    return unchanged

conflicting existing
    fail
```

### `finish_promotion(...)`

Before and after mutation, prove the immutable queue-source fingerprint is unchanged.

Only these fields may change:

```text
disposition
disposition_receipt_sha256
provisional_reuse_receipt
provisional_reuse_receipt_sha256
```

Queue ordinals are never renumbered.

## 3A.28 Structural diagnostics wiring

Record:

```text
BINARY64_LAYER_LOCK_CREATED
BINARY64_LAYER_LOCK_VALIDATED
BINARY64_PREDECESSOR_CONSUMED
PROMOTED_BACKGROUND_ACQUIRED
PROMOTED_BACKGROUND_REUSED
PROMOTED_TIER_ESCALATED
PROMOTED_LEAF_DISPOSITION_RECORDED
BINARY64_LAYER_LOCK_VIOLATION
```

Each event must carry applicable connection digests:

```text
lock receipt
Layer-1 projection
queue ordinal
binary64 disposition receipt
provisional stage
root seal
background group/key
runtime
control profile
source/target tier
reason code
```

A lock violation must include:

```text
expected projection SHA
actual projection SHA
first differing canonical path
phase:
    STARTUP
    PRE_WRITE
    POST_WRITE
    POST_CALLBACK
```

## 3A.29 Production wiring guard extension

Extend `production_wiring.py` to require:

```text
run_native_binary64_pass
    run_binary64_survey exactly once
    lock writer on exhausted success

run_native_promoted_pass
    lock validation
    run_promoted_survey exactly once
    layer1_guard
    locked_routes_by_ordinal
    promoted_background_store
    determinant_error_issuer
    existing root/cache/backend/report/diagnostic capabilities

campaign_survey.persist
    guard before and after write
```

AST checks are not enough for call order.

Add dynamic sentinel tests that fail if any of these occurs before lock validation:

```text
SolvedLeafStore publication
RootEvidenceStore publication
background publication
NativeCampaignStageBackend construction
Julia backend construction
worker launch
```

## 3A.30 No parallel-path rule

Repository search must show one production owner for each:

```text
Layer-1 projection
lock write
lock validation
predecessor parsing
error issuance
promoted background publication
queue disposition
promoted checkpoint persistence
```

Any duplicate production implementation fails CI.

## 3A.31 Wiring implementation order

```text
1. Add lock module/path owner.
2. Add CLI lock command.
3. Propagate lock path through CLI and PowerShell.
4. Auto-lock after binary64 exhaustion.
5. Validate lock before any mutation/backend.
6. Guard the single promoted persist closure.
7. Harden ledger/queue mutators.
8. Add typed exterior predecessor.
9. Add tier-bound promoted background store.
10. Add reviewed-error receipt publication.
11. Resolve admission Branch A or Branch B.
12. Wire BF40 continuation and same-tier reuse.
13. Wire approved BF80 exterior escalation.
14. Wire horizon BF80 isolation.
15. Add queue conservation.
16. Extend diagnostics.
17. Extend production_wiring.py.
18. Run mocked/static/CI verification only.
```

Start at the lock and production composition root.

Do not start by editing Julia.

---

# 4. CANONICAL LAYER-1 PROJECTION

The lock must hash the scientific content that Layer 2 is forbidden to change.

## 4.1 Include

Include:

```text
checkpoint schema version
campaign ID
selection ID
ordered selected leaf IDs
exact binary64 pass ledger
exact binary64 disposition receipts
immutable source portion of every promotion entry
all provisional stage bytes
all provisional stage SHA-256 values
all provisional operation identities
all source stage SHA-256 values
all source root-seal SHA-256 values
all source binary64 disposition receipt SHA-256 values
all scientific computation identities
all source records referenced by binary64 or queue entries
all evidence entries attached to those source records
required canonical-background evidence manifests
required root-evidence manifests
```

The immutable promotion-entry source projection includes:

```text
leaf_id
queue_kind
source_pass
reason_code
minimum_requested_tier
source_record_sha256
source_stage_sha256
source_root_seal_sha256
scientific_computation_identity
provisional_stage
provisional_stage_sha256
provisional_operation_identity
source_binary64_disposition_receipt_sha256
queue_ordinal
```

## 4.2 Exclude Layer-2 mutable fields

Exclude:

```text
queue disposition
queue disposition receipt SHA-256
provisional reuse receipt
provisional reuse receipt SHA-256
promoted pass ledger
new promoted numerical records
new promoted evidence
new promoted attempts
system-failure entries appended after lock
report-status receipt
checkpoint state PARTIAL/COMPLETE
operational timestamps
```

Exclusion means those fields may change without changing the Layer-1 projection.

It does not mean they are unauthenticated.

Their existing schema-11 validators still apply.

## 4.3 Source-record set

Do not hash every future checkpoint record.

Define the Layer-1 source-record set from hashes referenced by:

```text
binary64 result_record_sha256
promotion source_record_sha256
```

Hash only those exact records and their attached evidence.

This allows Layer 2 to append new records while preventing replacement of Layer-1 source records.

## 4.4 Auxiliary stores

For every external object needed by Layer 2:

```text
root evidence
canonical background evidence
root readout evidence, if referenced
```

include a canonical manifest entry:

```text
logical key
object schema
object SHA-256
content-addressed path or store identity
```

Missing required evidence fails the lock.

Do not silently regenerate it from a centre value.

---

# 5. LOCK RECEIPT

The sidecar must contain at least:

```text
schema
campaign_id
selection_id
checkpoint_schema_version
ordered_leaf_ids
source_checkpoint_sha256
binary64_layer_projection_sha256
binary64_pass_ledger_sha256
promotion_source_projection_sha256
source_record_projection_sha256
auxiliary_evidence_manifest_sha256
selected_leaf_count
binary64_processed_count
pending_promotion_count
route_counts
retained_sample_counts
per_leaf_route_bindings
receipt_sha256
```

`per_leaf_route_bindings` must bind:

```text
leaf ID
leaf ordinal
mechanism
queue ordinal
queue kind
reason code
minimum requested tier
scientific identity
source stage digest
source root-seal digest
binary64 disposition receipt digest
provisional operation identity
raw sample count
combined sample count
background reuse key or null
```

Repeated lock generation over the same Layer-1 state must produce byte-identical output.

---

# 6. LOCK CREATION

## 6.1 New command

Add a zero-numerical-work command:

```text
campaign-lock-binary64
```

Inputs:

```text
selection
--checkpoint
--output, optional default <checkpoint>.binary64-lock.json
```

The command may:

```text
read
validate
hash
write the lock atomically
```

It must not:

```text
construct a numerical backend
launch Julia
evaluate a determinant
read a root numerically
mutate the checkpoint
mutate any evidence store
```

## 6.2 Automatic normal path

After a future binary64 pass reaches authenticated exhaustion, write the lock after the final checkpoint commit.

For the existing completed checkpoint:

```text
promoted ledger empty
binary64 exhausted
lock absent
```

`m02.ps1 -Profile survey -SurveyPass promoted` may invoke the zero-work lock command once before starting Layer 2.

After any promoted disposition exists, a missing lock is fatal.

Do not recreate a lost lock from a partially promoted checkpoint.

Recover it from the operator’s preserved lock or diagnostic bundle.

---

# 7. LOCK ADMISSION GATE

A lock may be issued only when all conditions pass.

## 7.1 General conditions

```text
schema-11 checkpoint valid
campaign and selection match
every selected leaf has exactly one binary64 disposition
no off-selection binary64 disposition
no selected leaf is missing
binary64 pass is exhausted
no pending ROOT promotion unless explicitly allowed by another reviewed contract
every pending RESPONSE entry has one authenticated source
promoted ledger is empty for first lock creation
system-failure ledger is empty for the controlling clean handoff
```

## 7.2 Per-entry conditions

For every pending RESPONSE entry:

```text
queue source pass is binary64
queue scientific identity matches selected leaf
source binary64 disposition receipt matches ledger
source stage digest matches provisional stage digest
source root seal is present and valid
queue ordinal is unique and ordered
provisional stage validates under its owning schema
```

## 7.3 Route derivation

Derive route from authenticated science fields.

Do not route merely from mechanism name.

### Exterior route

Required combination:

```text
provisional operation
    binary64-fixed-root-provisional/v1

queue kind
    RESPONSE

reason
    BLOCKED_BY_REVIEWED_ERROR_EVIDENCE
    or the exact reviewed successor code

minimum tier
    BF40
```

### Horizon route

Required combination:

```text
provisional operation
    binary64-horizon-production/v3

queue kind
    RESPONSE

reason
    ROOT_UNCERTAINTY_EVIDENCE_UNAVAILABLE

minimum tier
    BF80
```

Unknown combinations fail closed.

## 7.4 Official M02 canary

The general lock algorithm must remain cardinality-agnostic.

The official M02 selection regression must assert:

```text
212 selected
212 binary64 dispositions
212 pending RESPONSE entries
172 exterior BF40 routes
40 horizon BF80 routes
48 full exterior 9-sample acquisitions
124 reused-background 4-sample acquisitions
928 retained binary64 determinant evaluations
0 binary64 Julia launches
0 binary64 root reads
```

---

# 8. IMMUTABILITY ENFORCEMENT

## 8.1 Promoted preflight

Before constructing any Layer-2 backend:

```text
load lock
authenticate lock digest
recompute Layer-1 projection
compare projection digest
validate all per-leaf bindings
validate route inventory
```

Any mismatch must raise a durable system failure:

```text
BINARY64_LAYER_LOCK_VIOLATION
```

No worker may launch first.

## 8.2 Every promoted checkpoint commit

Wrap every promoted `persist()` boundary:

```text
pre-write Layer-1 projection digest == lock digest
write candidate checkpoint atomically
post-write Layer-1 projection digest == lock digest
checkpoint callback result projection == lock digest
```

If the callback changes Layer 1, fail closed and identify the changed projection path.

## 8.3 Policy mutators

Harden state owners.

### `record_survey_disposition`

For an existing pass entry:

```text
exact same entry
    return idempotently

different entry
    raise conflict
```

Do not overwrite.

### `append_promotion`

For an existing leaf/source binding:

```text
exact same entry
    return idempotently

duplicate or conflicting entry
    fail
```

Do not append a second queue entry.

### `finish_promotion`

Before and after mutation, verify the immutable queue-source fingerprint.

It may change only:

```text
disposition
disposition_receipt_sha256
provisional_reuse_receipt
provisional_reuse_receipt_sha256
```

## 8.4 Binary64 command after lock

Running the binary64 command against a valid exhausted locked checkpoint must be zero-work.

It may validate and report:

```text
LAYER 1 ALREADY LOCKED
```

It must not revisit numerical leaves.

If current code cannot guarantee this, fail and instruct the operator to use the promoted command.

---

# 9. LAYER-2 ROUTING

## 9.1 Exact partition

Layer 2 consumes the locked queue as:

```text
172 exterior RESPONSE entries
    first tier BF40

40 horizon RESPONSE entries
    first and only normal tier BF80
```

Do not run all 212 at BF40.

Do not run all 212 at BF80.

Do not allow BF40 for a horizon-v3 root-uncertainty route.

## 9.2 Cache-first rule

Before any backend:

```text
check exact authenticated terminal cache
```

An exact current terminal record may supersede the pending promotion with zero work.

Conflicting exact sources are a system failure.

A stale or forensic response cannot supersede promotion.

---

# 10. EXTERIOR BINARY64 → BF40 HANDOFF

## 10.1 Compatibility is not consumption

The current predecessor receipt proves:

```text
stage is authentic
stage binds the leaf
stage binds the root seal
target tier is BF40
```

That is necessary.

It is not sufficient to claim the binary64 numerical values were consumed.

Add a typed predecessor object, for example:

```python
@dataclass(frozen=True, slots=True)
class AuthenticatedBinary64ExteriorPredecessor:
    ...
```

It must expose authenticated:

```text
raw sample roles
raw determinant values
combined sample roles
fixed root
root seal
frequency step
coordinate step
support
canonical background
background reuse receipt
D0 evidence
Dω evidence
Dc evidence
reason code
stage digest
```

## 10.2 No relabelling

Binary64 samples remain binary64 evidence.

They must never be copied into a BF40 batch or labelled BF40.

Their valid Layer-2 uses are:

```text
cross-precision comparison
predecessor lineage
background-group topology
continuation predictor information where approved
duplicate-work prevention
diagnostic comparison
```

## 10.3 No binary64 execution in promoted path

Add executable alarms.

The promoted path must fail tests if it:

```text
requests digits == 64
constructs the binary64 native backend
calls binary64 fixed-root sampling
launches a binary64 worker
creates a new binary64 provisional stage
```

Required counters:

```text
binary64_predecessor_stages_consumed
binary64_predecessor_samples_consumed
binary64_samples_recomputed
```

For the controlling full run:

```text
stages consumed       172 exterior
samples retained      928
samples recomputed      0
```

---

# 11. EXTERIOR DETERMINANT-ERROR ADMISSION GATE

## 11.1 Controlling blocker

Current `main` contains an intentional no-op:

```text
retain_uncalibrated_determinant_error_evidence(...)
    returns 0
    issues no determinant-error receipt
```

Do not run 172 promoted exterior jobs through a path that is structurally incapable of admitting them.

## 11.2 Required preflight decision

Before any exterior worker launch, resolve one of these two branches.

### Branch A — current receipt authorises production issuance

Prove from the exact canonical receipt and its admission boundary that current-run empirical evidence may issue the approved exterior determinant-error certificate.

Then implement exactly:

```text
delta_same_point
delta_cross_precision
delta_endpoint_series
```

and:

```text
determinant_error_abs
    = 64 × max(
        delta_same_point,
        delta_cross_precision,
        delta_endpoint_series
      )
```

All three terms must be finite, nonnegative, authenticated, and bound to:

```text
leaf
root seal
determinant family
precision tier
working precision
request SHA
response SHA
calibration receipt SHA
```

The certificate must be labelled:

```text
empirical
operator-approved
not interval arithmetic
not independent mathematical proof
```

### Branch B — current receipt is test-only or does not authorise issuance

Do not reinterpret it.

Do not weaken the evidence requirement.

Add:

```text
TODO: [HUMAN NUMERICAL CALIBRATION REQUIRED —
the current promoted-control receipt does not authorize production
exterior determinant-error issuance for the locked BF40 handoff]
```

Fail promoted preflight before the first exterior worker launch.

Ship the partial implementation and halt.

## 11.3 Term ownership

Required meaning:

```text
delta_same_point
    same precision, same determinant point,
    base controls versus tightened controls

delta_cross_precision
    BF40 versus locked binary64 at matching canonical points
    BF80 versus retained BF40 when BF80 escalation occurs

delta_endpoint_series
    approved endpoint depth/order or series refinement comparison
```

Do not substitute one term for another.

Missing any term yields:

```text
EXTERIOR_DETERMINANT_CERTIFICATE_UNAVAILABLE
```

Whether that condition may escalate to the next tier must be decided by whether the missing term can actually be generated there.

Do not burn BF80 merely to repeat the same permanently missing evidence.

---

# 12. SAME-TIER EXTERIOR BACKGROUND REUSE

This is mandatory for the performance objective.

The locked Layer-1 topology identifies exact exterior background groups.

At each promoted tier, create one canonical background per exact reuse key.

## 12.1 BF40

For each exact group:

```text
first member
    5 background D0/Dω samples
    + 4 mechanism Dc samples
    = 9 samples

subsequent members
    reuse authenticated BF40 background
    + 4 mechanism Dc samples
    = 4 samples
```

For the controlling 172 exterior routes:

```text
48 first-use groups × 9
+ 124 reused members × 4
= 928 maximum BF40 determinant samples
```

The forbidden no-reuse budget is:

```text
172 × 9 = 1548
```

Tests must fail if the full mocked route consumes 1548.

## 12.2 BF80 exterior escalations

For the subset that legitimately escalates:

```text
publish one BF80 canonical background per exact group
reuse it for later escalated siblings
```

Do not use BF40 determinant values as BF80 values.

## 12.3 Durable same-pass publication

Publish the promoted canonical background immediately after its authenticated acquisition.

Resume must reuse it.

Conflicting authenticated backgrounds for the same exact key fail closed.

---

# 13. EXTERIOR TIER LADDER

For each exterior RESPONSE entry:

```text
exact terminal cache hit?
    → SUPERSEDED_BY_CACHE
    → zero worker work

else
    validate Layer-1 predecessor
    consume BF40 predecessor receipt
    acquire/reuse BF40 canonical background
    run BF40 mechanism work
    build all three error terms
    screen
```

If BF40 produces a bounded response:

```text
COMPLETED
stop
do not run BF80
```

BF80 may run only for an allowlisted, typed BF40 numerical insufficiency.

Corruption, missing immutable source data, scientific identity mismatch, lock mismatch, or impossible certificate policy is not precision insufficiency.

Those are system failures or human-review blockers.

BF120 remains forbidden unless a separate reviewed policy explicitly admits it.

---

# 14. HORIZON BINARY64 → BF80 HANDOFF

For each of the 40 horizon entries:

```text
skip BF40
validate v3 binary64 provisional stage
validate root seed and root seal
run approved BF80 horizon route
obtain authenticated nonzero root-uncertainty evidence
propagate root uncertainty into p_H
compute bounded D_R, Dω, denominator, and response disks
```

Do not invent:

```text
zero root radius
zero determinant residual
zero root correction
one-ULP pseudo-enclosure
```

If a bounded root disk cannot be produced, return the correct typed disposition.

Do not call an unbounded centre a bounded response.

## 14.1 Record construction

On successful BF80 production, the terminal horizon record must retain:

```text
original binary64 provisional stage, byte-identical
new BF80 stage
current v3 mathematical identity
retained centre from the bounded BF80 response
```

Layer 1 remains source evidence.

Layer 2 appends evidence.

## 14.2 Root publication

Publish authenticated bounded root evidence by exact root dependency key.

Compatible exterior siblings and later passes may consume it.

A horizon response failure must not delete or hide valid background-root evidence.

---

# 15. CONSERVATION AND ACCOUNTING

At promoted-pass start:

```text
locked pending total
    = locked exterior BF40
    + locked horizon BF80
```

At promoted-pass end, every applicable queue ordinal must appear in exactly one terminal class:

```text
COMPLETED
SUPERSEDED_BY_CACHE
UNRESOLVED
DEFERRED
REJECTED
```

No loss.

No duplication.

No still-PENDING entry when the pass claims exhaustion.

Required conservation receipt:

```text
input_pending
completed
cache_superseded
unresolved
deferred
rejected
remaining_pending
duplicate_count
off_lock_count
```

With:

```text
input_pending
= completed
+ cache_superseded
+ unresolved
+ deferred
+ rejected
+ remaining_pending
```

For exhausted pass:

```text
remaining_pending = 0
duplicate_count   = 0
off_lock_count    = 0
```

---

# 16. STRUCTURAL DIAGNOSTICS

Record at least:

```text
BINARY64_LAYER_LOCK_CREATED
BINARY64_LAYER_LOCK_VALIDATED
BINARY64_PREDECESSOR_CONSUMED
PROMOTED_BACKGROUND_ACQUIRED
PROMOTED_BACKGROUND_REUSED
PROMOTED_TIER_ESCALATED
PROMOTED_LEAF_DISPOSITION_RECORDED
BINARY64_LAYER_LOCK_VIOLATION
```

Required session counters:

```text
layer1_lock_sha256
locked_selected_count
locked_exterior_bf40_count
locked_horizon_bf80_count
binary64_predecessor_stages_consumed
binary64_predecessor_samples_retained
binary64_samples_recomputed
bf40_exterior_attempted
bf40_exterior_completed
bf80_exterior_escalated
bf80_horizon_attempted
bf80_horizon_completed
bf40_backgrounds_acquired
bf40_backgrounds_reused
bf80_backgrounds_acquired
bf80_backgrounds_reused
promoted_worker_launches
queue_conservation_status
```

A postmortem must be able to distinguish:

```text
new promoted work
retained Layer-1 work
reused same-tier work
recomputed forbidden work
```

---

# 17. M02 OPERATOR SURFACE

For a promoted start, print before any worker launch:

```text
LAYER 1 LOCK
    status                    VALID
    lock SHA-256              <digest>
    binary64 processed        212 / 212
    pending promotions        212
    exterior → BF40           172
    horizon  → BF80            40
    retained binary64 samples 928
    binary64 recomputation    FORBIDDEN

LAYER 2 PLAN
    exterior first tier       BF40
    horizon first tier        BF80
    BF80 exterior             only on approved BF40 escalation
```

If calibration admission is blocked, print the blocker and exit before worker launch.

Do not print “promoted survey started” if the production evidence policy has already proved the run futile.

---

# 18. TEST-FIRST IMPLEMENTATION ORDER

## Commit A — freeze the real Layer-1 fixture

Add a compact deterministic fixture representing the controlling inventory.

Test the conservation equalities and per-entry authentication.

## Commit B — add lock projection and zero-work lock command

Verify red/green with mutation tests.

## Commit C — harden schema-11 mutators and promoted persist boundaries

Make Layer-1 replacement impossible.

## Commit D — implement authenticated predecessor consumption

Prove zero binary64 recomputation.

## Commit E — resolve the determinant-error admission gate

Either wire the exact approved three-term certificate or stop with the required human-review TODO.

## Commit F — add same-tier BF40/BF80 background reuse

Prove the 928 versus 1548 budget.

## Commit G — wire horizon BF80 and full 212 mocked orchestration

No production solver.

---

# 19. MANDATORY TEST MATRIX

## Lock tests

```text
test_completed_binary64_checkpoint_builds_deterministic_lock
test_repeated_lock_generation_is_byte_identical
test_lock_creation_constructs_no_backend
test_lock_creation_launches_no_worker
test_lock_rejects_incomplete_binary64_pass
test_lock_rejects_off_selection_disposition
test_lock_rejects_duplicate_queue_leaf
test_lock_rejects_root_queue_in_controlling_response_handoff
test_lock_rejects_source_stage_digest_mismatch
test_lock_rejects_binary64_disposition_receipt_mismatch
test_lock_rejects_missing_auxiliary_root_evidence
```

## Mutation matrix

Each mutation must fail before backend construction:

```text
binary64 disposition changed
binary64 reason changed
sample count changed
tier timing changed
provisional determinant changed
provisional stage SHA changed
source root seal changed
scientific identity changed
minimum requested tier changed
queue ordinal changed
source record replaced
locked background receipt changed
```

Allowed Layer-2 mutations must preserve the lock:

```text
queue terminal disposition
queue terminal receipt
provisional reuse receipt
promoted pass entry
new promoted record
new promoted evidence
new promoted attempt
report status
```

## Route tests

```text
test_official_m02_lock_routes_172_exterior_to_bf40
test_official_m02_lock_routes_40_horizon_to_bf80
test_horizon_route_never_constructs_bf40_backend
test_exterior_route_begins_at_bf40
test_unknown_route_fails_closed
test_all_bf40_policy_is_rejected
test_all_bf80_policy_is_rejected
```

## Predecessor tests

```text
test_exterior_predecessor_exposes_authenticated_numerical_samples
test_predecessor_receipt_binds_stage_and_sample_set_digest
test_bf40_cross_precision_term_consumes_locked_binary64_values
test_binary64_values_are_not_relabeled_bf40
test_promoted_path_never_requests_digits_64
test_promoted_path_recomputes_zero_binary64_samples
```

## Error-certificate tests

```text
test_all_three_empirical_term_classes_are_required
test_certificate_is_64_times_maximum_term
test_certificate_binds_exact_calibration_receipt
test_missing_term_returns_typed_unavailable
test_test_only_receipt_blocks_before_worker_launch
test_bf80_does_not_repeat_permanently_missing_policy_evidence
```

## Background-reuse tests

```text
test_bf40_first_group_member_uses_9_samples
test_bf40_later_group_member_uses_4_samples
test_full_172_mocked_bf40_budget_is_928_not_1548
test_bf40_background_is_published_before_next_sibling
test_resume_reuses_durable_bf40_background
test_conflicting_bf40_background_fails_closed
test_bf80_escalated_siblings_reuse_bf80_background
```

## Tier-ladder tests

```text
test_bf40_success_stops_without_bf80
test_allowlisted_bf40_insufficiency_escalates_once_to_bf80
test_nonprecision_failure_does_not_escalate
test_bf120_is_not_constructed
```

## Horizon tests

```text
test_horizon_bf80_consumes_binary64_v3_source
test_horizon_bf80_requires_nonzero_authenticated_root_radius
test_horizon_record_retains_binary64_stage_byte_identical
test_horizon_record_appends_bf80_stage
test_horizon_failure_preserves_root_evidence
```

## Full mocked production shape

Build:

```text
212 selected leaves
212 locked pending RESPONSE entries
172 exterior BF40
40 horizon BF80
48 exterior background groups
928 retained binary64 samples
mocked BF40/BF80 backends
no Julia
```

Assert:

```text
lock valid before first backend
no Layer-1 byte changed
no binary64 backend constructed
no binary64 sample recomputed
all queue ordinals accounted
same-tier background reuse enforced
route partition conserved
```


## Wiring and connection tests

```text
test_m02_promoted_creates_missing_clean_lock_before_promoted_command
test_m02_promoted_passes_same_lock_to_run_and_post_validation
test_cli_lock_command_is_zero_work
test_cli_promoted_passes_resolved_lock_path_to_runtime
test_runtime_revalidates_lock_even_when_cli_validated_it
test_runtime_validates_lock_before_checkpoint_record_publication
test_runtime_validates_lock_before_root_provider_construction
test_runtime_validates_lock_before_native_backend_construction
test_runtime_validates_lock_before_julia_backend_construction
test_runtime_calls_run_promoted_survey_exactly_once
test_scheduler_receives_typed_locked_routes
test_scheduler_persist_guards_pre_write_post_write_and_post_callback
test_system_failure_uses_same_guarded_persist
test_cache_supersession_uses_same_guarded_persist
test_report_refresh_preserves_layer1_projection
test_exterior_route_passes_typed_predecessor
test_exterior_route_passes_promoted_background_store
test_exterior_route_passes_determinant_error_issuer
test_horizon_route_does_not_touch_exterior_predecessor
test_reviewed_error_store_publish_is_atomic_idempotent_conflict_closed
test_production_wiring_guard_requires_new_capabilities
test_dynamic_sentinel_proves_no_prelock_mutation_or_backend
```

## Static guards

Fail CI if promoted code contains:

```text
backend_factory(..., 64)
a call to binary64 numerical runner
direct mutation of binary64 pass ledger
direct replacement of provisional_stage
duplicate lock policy outside binary64_layer_lock.py
hard-coded all-BF40 or all-BF80 routing
```

---

# 20. FORBIDDEN FIXES

Do not fix this by:

```text
deleting the checkpoint
deleting solved-leaf cache
deleting root evidence
rerunning binary64
copying binary64 values into BF40 objects
calling compatibility receipt proof numerical consumption
running every exterior leaf with 9 samples at every tier
running all 212 at BF80
running all 212 at BF40
inventing a root uncertainty radius
weakening the empirical certificate
dropping one of the three error terms
treating an empirical certificate as interval arithmetic
catching lock errors and continuing
regenerating a lost lock after promoted work begins
rewriting source stages
renumbering queue ordinals
overwriting pass ledger entries
launching Julia during development verification
running M02 during development verification
```

---

# 21. PERMITTED VERIFICATION

Permitted:

```text
targeted Python unit tests
full Python test suite
compileall
static AST/source guards
mocked Layer-1 fixture
mocked BF40/BF80 backends
hosted CI
```

Forbidden:

```text
production M02
production binary64
production promoted survey
Julia worker
native determinant canary
PowerShell scientific canary
```

---

# 22. PR BOUNDARY

Recommended PR title:

```text
feat(m02): lock binary64 evidence and continue promoted work
```

This PR must not redesign dashboard projection or layout.

Required completion report:

```text
base SHA
head SHA
changed files
lock schema and lock path
official M02 fixture counts
proof of zero binary64 recomputation
BF40/BF80 route test results
same-tier background reuse sample budget
calibration admission decision
targeted and full-suite results
static-guard result
CI status
statement that no Julia or production solver was executed
```


Additional wiring completion evidence:

```text
exact m02.ps1 command order
exact CLI lock-path propagation
exact runtime-to-scheduler capability map
production_wiring.py CONNECTED receipt
dynamic sentinel proof of no pre-lock mutation/backend
PRE_WRITE / POST_WRITE / POST_CALLBACK guard proof
typed predecessor consumption proof
promoted background acquisition/reuse proof
determinant-error issuance/publication proof
horizon BF80 isolation proof
```


If the calibration blocker remains unresolved, do not claim completion.

Ship the partial branch with the required TODO and exact blocker.

When the implementation is genuinely ready for operator execution, finish with:

> Code written. Awaiting your PowerShell execution logs.
