# **[PR #66](https://github.com/vbrodi23-lgtm/Kerr-QNM_Windows-Solver/pull/66) — Governing Completion Contract**

## Root-readout reuse, authenticated exterior-background reuse, and acceptance-governance repair

> **Authority:** This document is the governing completion contract for PR #66. It is additive to the PR #65 governing contract and supersedes it wherever the two conflict on root-readout recovery, cross-mechanism Dω reuse, production integration evidence, acceptance receipts, draft status, or landing authority.
>
> **Starting point:** PR #65 was merged as commit `261fd3a371fcfbe83ada0e857625c1436ac357eb`. PR #66 is a forward repair from the current protected branch. Do not reset `main`, rewrite published history, force-push, or conceal the PR #65 merge.
>
> **Execution airgap:** Development agents may inspect, write, edit, statically validate, and run permitted non-production tests. They must not execute the production Kerr/GSN solver, the Julia numerical worker, the M02 PowerShell campaign, or mathematical acceptance canaries. Native execution belongs to the operator, who returns the logs and artifacts for review.
>
> **Merge rule:** Hosted CI, mocked tests, static checks, and agent assurances are not landing authority. PR #66 remains draft until the exact-head native acceptance receipt exists, the operator reviews it, and the operator gives explicit landing approval. No agent may infer approval, mark the PR ready, request merge, or merge autonomously.

---

## 1. Objective

PR #66 must close three confirmed defects left in the merged PR #65 architecture:

1. **Production schema-11 survey does not consume authenticated root-readout-store evidence.**
2. **Production binary64 survey disables authenticated cross-mechanism Dω/background reuse by passing no equivalence-receipt resolver.**
3. **PR #65 was merged without the mandatory exact-head acceptance artifact and operator-controlled landing sequence required by its own governing contract.**

The required end state is:

```text
available authenticated terminal numerical record
→ reuse exact record
→ zero numerical work

no terminal record, but exact authenticated root readout exists
→ recover/authenticate root seal
→ no root solve
→ fixed-root survey only

first cross-mechanism Dω reuse under one exact contract
→ exact reuse-key match
→ durable background-equivalence/v1 proof exists
→ reuse admitted

missing, stale, mismatched, ambiguous, or tampered proof
→ no reuse
→ execute the full permitted fixed-root background batch

all implementation and native gates pass
→ exact-head acceptance receipt written
→ PR remains draft
→ operator reviews receipt
→ operator explicitly approves landing
→ only then may PR leave draft and merge
```

PR #66 is not complete merely because the functions exist, scheduler unit tests pass, or CI is green. The production entry points must actually consume the repaired capabilities.

---

## 2. Verified defect register

The following defects were identified by static inspection of the merged PR #65 production paths. No production Kerr/GSN or Julia solve was executed during that inspection.

### D01 — Root-readout-store evidence is ignored by production root-seal resolution

**Verified current behavior**

- `src/windows_solver/campaign_runtime.py::_root_index()` builds its root-seal candidates from:
  - schema-11 checkpoint records; and
  - `SolvedLeafStore` terminal receipts.
- It does not query or import `RootReadoutStore`.
- `src/windows_solver/campaign_recovery.py::recover_campaign()` accepts `root_readout_stores`, but currently records only whether each supplied path is `AVAILABLE` or `MISSING`; it does not authenticate the entries or materialize reusable root seals from them.
- `src/windows_solver/root_readout_cache.py` explicitly exists to retain successful promoted root readouts across interrupted stages, yet the new schema-11 production survey cannot see those readouts unless they have already been transformed into another accepted record type.

**Failure consequence**

An expensive root readout may already exist, be valid, and be exactly compatible, but the binary64 survey can still report no root seal and enqueue `PROMOTION_PENDING_ROOT`. A later promoted pass may then repeat a root solve that should have been reused.

**Required repair**

The production schema-11 root-seal acquisition path must authenticate and consume exact compatible root-readout-store entries before authorizing any new root solve.

### D02 — Production Dω/background reuse is implemented but disabled

**Verified current behavior**

- The response layer defines:
  - `CanonicalExteriorBackground`;
  - `ExteriorBackgroundReuseKey`;
  - `BackgroundEquivalenceReceipt`;
  - `background-equivalence/v1` identity checks;
  - a 9-sample full fixed-root batch; and
  - a 4-sample reused-background batch.
- Scheduler tests inject an `equivalence_receipt_lookup` callback and therefore demonstrate that the scheduler can reuse Dω when a resolver is supplied.
- The actual production adapter `src/windows_solver/campaign_runtime.py::run_native_binary64_pass()` calls the scheduler with:

```python
equivalence_receipt_lookup=None
```

**Failure consequence**

The production survey cannot admit cross-mechanism Dω reuse. Exterior leaves recompute canonical background/frequency-derivative work even when the exact reuse key and a valid durable equivalence proof should permit reuse.

**Required repair**

The production adapter must provide a real authenticated equivalence-receipt resolver. It must not fabricate a receipt in memory merely because the key matches.

### D03 — Acceptance governance failed at the PR #65 landing boundary

**Verified current behavior**

- The PR #65 governing contract required:
  - exact-head native Canaries A–G;
  - a commit-bound `docs/engineering/pr65-native-acceptance.json` artifact;
  - native log hashes and output hashes;
  - background-equivalence receipt hashes;
  - operator review; and
  - explicit operator landing approval before the PR could leave draft.
- PR #65 is merged.
- The merged repository does not contain the required `docs/engineering/pr65-native-acceptance.json` artifact.

**Failure consequence**

The statement “PR #65 was proven completely fixed” is unsupported under PR #65’s own acceptance standard. Passing hosted checks did not prove the operator-native production boundaries.

**Required repair**

PR #66 must restore the acceptance boundary as enforceable repository state, not prose that an agent may disregard.

---

## 3. Non-negotiable invariants

1. **Exact terminal record reuse precedes every backend construction.**
2. **Exact root-readout-store lookup precedes every promoted root solve.**
3. **A valid compatible root readout must prevent root recomputation.**
4. **Recovery performs no determinant evaluations, ODE solves, Julia launches, or root solves.**
5. **Root-readout authentication is fail-closed.** Request identity, runtime identity, worker receipt, branch identity, root identity, mechanism/request binding, and root-seal derivation must agree.
6. **A corrupt trusted root-readout candidate is not silently ignored as a normal miss.** It produces a durable system/recovery diagnostic and follows the declared corruption policy.
7. **An unrelated, off-selection, wrong-runtime, wrong-request, wrong-branch, stale, or non-reconstructable readout is never reused.**
8. **The number of reusable records or readouts is discovered, not prescribed.** Zero, one, seven, forty-two, forty-eight, or any other valid count must work without hard-coded expectations.
9. **A sealed root authorizes fixed-root response work only.** It does not authorize relabelling unrelated numerical evidence.
10. **Cross-mechanism Dω reuse requires both an exact reuse-key match and a valid durable `background-equivalence/v1` receipt.**
11. **An exact key alone is insufficient.**
12. **A receipt issued only from metadata without the required equivalence computation is insufficient.**
13. **Missing or invalid equivalence evidence disables reuse; it does not fail the whole survey if the full 9-sample route remains valid.**
14. **Production must exercise the same reuse path that tests exercise.** No test-only callback injection may stand in for missing production wiring.
15. **The first admitted reuse for each mechanism/contract version must be backed by a durable proof.** Subsequent exact-contract reuse may consume that proof without repeating the equivalence computation.
16. **No survey pass performs inline promotion.**
17. **Binary64 survey launches zero Julia workers.**
18. **Promoted survey remains separate from certification and validation.**
19. **Unexpected programming, protocol, or integration defects abort before the next leaf and are never converted into terminal numerical science.**
20. **`FAILED` remains operational, not scientific.**
21. **PR #66 cannot be declared complete from hosted CI alone.**
22. **Any commit after native acceptance invalidates the exact-head receipt and requires affected canaries to be rerun.**
23. **PR #66 remains draft until explicit operator landing approval is recorded.**
24. **No automated agent has landing authority.**

---

## 4. Required production architecture

### 4.1 Authenticated root-seal provider

Introduce one production-owned root-seal acquisition boundary used by both binary64 and promoted schema-11 survey passes.

The provider must search in this order:

```text
1. exact compatible terminal record already in the schema-11 checkpoint
2. exact compatible terminal record in SolvedLeafStore
3. exact compatible successful readout in RootReadoutStore
4. no reusable root seal
```

For a root-readout-store candidate, the provider must validate at least:

- root-readout schema and canonical field set;
- filename/address identity;
- exact worker request SHA-256;
- exact runtime identity SHA-256;
- successful worker status;
- worker-response receipt integrity where present;
- requested leaf/root ownership;
- branch identity;
- angular/root identity and sampling-coordinate binding;
- precision tier and operation identity;
- root convergence/acceptance evidence required by the active policy;
- canonical `PromotedRootSeal` derivation;
- absence of conflicting distinct seals for the same requested root.

The provider returns either:

```text
authenticated exact root seal
or
no compatible root seal
or
typed corruption/conflict/system failure
```

It must never return “compatible” from path presence alone.

### 4.2 Recovery integration

`campaign-recover` must no longer treat root-readout stores as decorative source metadata.

It must do one of the following, with the choice documented and tested:

- authenticate and import reconstructable root seals into a durable schema-11 auxiliary root-seal ledger; or
- build a separately sealed root-readout recovery index referenced by the candidate checkpoint and consumed by later survey passes.

Whichever design is selected must preserve these properties:

- zero numerical work;
- source stores remain unmodified;
- every accepted readout is individually authenticated;
- ignored entries carry explicit reasons;
- conflicts abort without writing a destination;
- recovered numerical records remain byte-identical;
- root seals are not misrepresented as completed response records;
- a later survey can reuse the recovered root without solving it again.

### 4.3 Durable background-equivalence proof

The first cross-mechanism Dω reuse under a mechanism/contract version must create or consume a durable `background-equivalence/v1` receipt proving that:

```text
canonical zero-coupling exterior background operation
and
mechanism-specific c = 0 operation
```

represent the same determinant under the governing contract.

The proof must bind at least:

- root-seal SHA-256;
- root identity;
- branch identity;
- angular identity;
- canonical background operation identity;
- mechanism ID and mechanism contract version;
- determinant family;
- determinant convention;
- determinant normalisation;
- match/readout convention;
- backend identity;
- numerical-controls SHA-256;
- arithmetic tier and working precision;
- frequency-step policy;
- canonical background batch SHA-256;
- mechanism-specific zero-coupling batch SHA-256;
- comparison method;
- absolute discrepancy;
- admitted comparison bound;
- issuance timestamp as metadata only, never as scientific precedence;
- receipt SHA-256.

A receipt parser must recompute all deterministic fields and reject resealed tampering.

### 4.4 Production equivalence resolver

`run_native_binary64_pass()` must supply a production resolver instead of `None`.

The resolver must:

1. build the exact expected reuse key for the requested leaf;
2. look up a durable equivalence receipt by exact contract identity;
3. authenticate the receipt and its referenced background/equivalence evidence;
4. return the receipt only on exact agreement;
5. return no receipt on an ordinary absence or incompatible contract;
6. raise a typed system/evidence-corruption failure for a trusted receipt that is malformed or self-contradictory.

It must not call `BackgroundEquivalenceReceipt.issue(...)` as a substitute for obtaining the required proof.

### 4.5 Fallback behavior

When no valid reuse proof exists:

```text
reuse disabled
→ execute the full 9-sample fixed-root survey batch
→ screen normally
→ optionally produce the equivalence proof as a distinct durable side effect
→ do not alter the numerical centre merely to enable future reuse
```

When a valid proof exists:

```text
exact reusable canonical background
+ exact valid equivalence receipt
→ execute only the 4 mechanism-derivative samples
→ combine with the authenticated canonical Dω evidence
→ preserve all source hashes in the screening record
```

---

## 5. Required implementation sequence

### Task 1 — Freeze the defect with failing production-boundary tests

Add tests that call the production adapters, not only the generic scheduler:

- `run_native_binary64_pass()` with a compatible root existing only in a temporary root-readout store;
- `run_native_binary64_pass()` across two exterior mechanisms sharing an exact background contract;
- `campaign-recover` with a root-readout store containing valid, incompatible, corrupt, and conflicting entries.

The tests must fail on merged PR #65 before the repair is applied.

### Task 2 — Implement authenticated root-readout indexing

- Add the production root-seal provider.
- Wire it into binary64 survey.
- Wire it into promoted survey.
- Wire recovery outputs into the same provider.
- Preserve existing checkpoint and solved-leaf precedence.
- Do not broaden compatibility to make fixtures pass.

### Task 3 — Implement durable equivalence receipt storage and lookup

- Define the durable store/index.
- Bind every governing identity and numerical comparison term.
- Support exact lookup independent of source ordering.
- Reject tampering and conflicting receipts.
- Preserve the full-batch fallback.

### Task 4 — Wire production Dω reuse

- Replace `equivalence_receipt_lookup=None` in the production binary64 adapter.
- Confirm the actual M02 command path reaches the resolver.
- Confirm reuse is visible in the pass ledger and timing ledger.
- Confirm the record binds both the canonical background source and the equivalence receipt.

### Task 5 — Add production integration and negative tests

Cover:

- exact root-readout hit;
- wrong runtime;
- wrong request;
- wrong branch;
- stale worker receipt;
- conflicting root seals;
- corrupt trusted entry;
- exact Dω reuse;
- missing receipt fallback;
- mismatched key fallback;
- tampered receipt failure;
- changed support/readout/backend/control identity disabling reuse;
- resume after interruption;
- zero backend construction on exact terminal-record hits;
- zero root solve on exact root-readout hits;
- zero Julia launch during binary64 survey;
- no inline promotion;
- no numerical mutation during recovery.

### Task 6 — Add enforceable PR66 acceptance state

Create:

```text
docs/engineering/pr66-native-acceptance.json
docs/engineering/pr66-completion-report.md
```

The JSON receipt is mandatory and machine-validated. The Markdown report is the human-readable projection.

### Task 7 — Operator native canaries

The operator runs Canaries A–G against the exact PR head. The development agent reviews returned logs, fixes defects, and stops after presenting the complete receipt. The operator alone decides whether to approve landing.

---

## 6. Required hosted and static tests

At minimum, add tests equivalent to the following contracts.

### 6.1 Root-readout production wiring

```text
test_native_binary64_uses_exact_root_readout_store_hit
    root exists only in RootReadoutStore
    result uses fixed-root survey
    root queue count = 0
    root solve count = 0
    Julia launch count = 0


test_native_binary64_rejects_wrong_runtime_root_readout
    same apparent root, different runtime identity
    no reuse
    no false root seal


test_native_binary64_aborts_on_conflicting_authenticated_root_seals
    two distinct valid seals for the same exact requested root
    durable system failure
    no next-leaf execution


test_recovery_authenticates_root_readout_store_entries
    valid reconstructable entries indexed
    incompatible entries ignored with reason
    corrupt trusted entries fail closed
    zero numerical work
```

### 6.2 Production Dω reuse wiring

```text
test_native_binary64_production_supplies_equivalence_resolver
    production adapter does not pass None


test_first_cross_mechanism_reuse_requires_durable_proof
    exact key without receipt
    full 9-sample fallback


test_second_cross_mechanism_reuses_authenticated_background
    exact key + valid durable receipt
    only 4 mechanism samples
    canonical background/Dω not recomputed


test_tampered_equivalence_receipt_fails_closed
    recomputed outer digest is insufficient
    semantic mismatch rejected


test_changed_governing_identity_disables_reuse
    mutate each key field one at a time
    no 4-sample route
```

### 6.3 Test-quality gate

The following does not count as proof of production integration:

```text
calling run_binary64_survey(...) directly
and injecting
root_seal_lookup=lambda ...
equivalence_receipt_lookup=lambda ...
```

Such unit tests may remain, but PR #66 must additionally call the real production adapters and public command path.

### 6.4 Static prohibitions

Add static assertions or equivalent review checks proving:

- production code no longer contains `equivalence_receipt_lookup=None` at the native binary64 call site;
- `root_readout_stores` are not merely logged as available/missing;
- no hard-coded receipt count exists;
- no test-only fake resolver is imported by production;
- no survey path invokes certification functions;
- no binary64 path imports or launches Julia;
- no acceptance validator permits `landing_approval_status = APPROVED` without an operator-authored approval field.

---

## 7. Operator-run native canaries

All canaries bind to the exact PR #66 head SHA. Any later commit invalidates affected results.

### Canary A — Fresh-machine start

```powershell
.\m02.ps1 -NewCampaign -Checkpoint <new-empty-path>
```

Required evidence:

- empty prior checkpoint;
- empty solved-leaf store;
- empty root-readout store;
- schema-11 checkpoint created;
- binary64 pass only;
- zero Julia launches;
- no automatic promoted/certify/validate transition.

### Canary B — Count-agnostic recovery

Run recovery against controlled stores containing several valid counts, including zero and a non-special arbitrary N.

Required evidence:

```text
valid compatible supplied     N
recovered                     N
lost valid                    0
fabricated                    0
numerical work                0
```

### Canary C — Root-readout-only reuse

Prepare a campaign state where the exact compatible root exists only in the authenticated root-readout store.

Required evidence:

- root seal recovered;
- fixed-root survey proceeds;
- root solve count = 0;
- worker launch count for root solving = 0;
- no `PROMOTION_PENDING_ROOT` for that leaf;
- source readout receipt hash recorded.

### Canary D — Authenticated cross-mechanism Dω reuse

Run two exterior mechanisms sharing the exact governing background contract.

Required evidence:

- first mechanism produces or consumes canonical background evidence;
- durable `background-equivalence/v1` receipt exists;
- second mechanism executes four samples, not nine;
- canonical Dω is not recomputed;
- exact reuse key and receipt hashes appear in the record/pass ledger.

### Canary E — Missing and tampered proof behavior

Required evidence:

- missing receipt causes full 9-sample fallback, not false reuse;
- mismatched key causes fallback;
- tampered trusted receipt fails closed with a typed diagnostic;
- no numerical centre is fabricated or silently replaced.

### Canary F — Interruption and resume

Interrupt after a successful expensive root readout but before the leaf response becomes terminal.

Required evidence on resume:

- completed readout reused;
- root not solved again;
- checkpoint and timing ledgers remain valid;
- no duplicated terminal record;
- no loss of source receipt identity.

### Canary G — Exact-head public-path acceptance

Run the public PR #66 commands and validators against `examples/m02-campaign.json`.

Required evidence:

- exact-head plan reports 212 leaves: Primary 140, Control 24, Deep 48;
- public launcher path reaches repaired production adapters;
- binary64 pass remains Julia-free;
- pass separation remains explicit;
- reports and status sidecars remain valid;
- all output/log hashes are captured in the acceptance receipt.

---

## 8. Mandatory exact-head acceptance artifact

Create `docs/engineering/pr66-native-acceptance.json` with a closed schema containing at least:

```text
schema
repository
pr_number
branch
base_branch
pr_head_sha256
main_base_sha256
selection_path
selection_file_sha256
campaign_id
selection_id
leaf_count
role_counts
runtime_receipts
script_sha256s
hosted_workflow_run_ids
hosted_job_conclusions
focused_test_command
focused_test_result
full_test_command
full_test_result
static_check_results
canaries
    A ... G
    command
    start_utc
    end_utc
    exit_code
    stdout_sha256
    stderr_sha256
    artifact_sha256s
    outcome
root_readout_reuse_receipts
background_equivalence_receipts
known_limitations
incident_fixture_status
operator_identity
operator_review_timestamp
landing_approval_status
landing_approval_text_sha256
receipt_sha256
```

Rules:

- `landing_approval_status` begins as `PENDING`.
- Agents cannot change it to `APPROVED` on their own.
- Approval must be tied to explicit operator text and timestamp.
- The receipt validator recomputes all deterministic hashes.
- A head-SHA mismatch invalidates the receipt.
- A missing canary log or artifact hash is a failed gate, not “not applicable,” unless this contract explicitly marks it optional.
- Known limitations must be stated. Empty or omitted limitations cannot be used to imply none exist.

---

## 9. Branch and landing procedure

1. Create PR #66 from current `main` without rewriting PR #65 history.
2. Keep PR #66 draft.
3. Commit this governing contract first or as the first reviewable contract commit.
4. Add failing production-boundary regressions.
5. Implement root-readout integration.
6. Implement durable background-equivalence storage and production lookup.
7. Run hosted and permitted non-production tests.
8. Present code review evidence, but do not claim native completion.
9. Operator runs Canaries A–G against the exact head.
10. Commit the exact-head acceptance receipt and completion report.
11. If committing the receipt changes the PR head, rerun or structure the receipt commit according to an explicitly documented self-binding procedure that preserves exact-head validity. Do not hand-wave this circularity.
12. Agent presents the completed receipt and stops.
13. Operator reviews it and explicitly approves or rejects landing.
14. Only after explicit approval may the PR leave draft and the protected merge path be requested.

---

## 10. Prohibitions

PR #66 must not:

- treat root-readout-store path availability as evidence consumption;
- ignore authenticated root readouts because no terminal response record exists;
- solve a root again when an exact compatible successful readout is available;
- convert a root readout directly into a fabricated completed response record;
- accept a root seal from filename, path, timestamp, or approximate frequency alone;
- choose between conflicting valid seals by newest timestamp;
- hard-code the current 212-leaf count or any incident receipt count into the recovery algorithm;
- pass `equivalence_receipt_lookup=None` in the production native binary64 survey;
- fabricate `background-equivalence/v1` by calling an in-memory issuer without the required proof;
- claim cross-mechanism equivalence from an exact key alone;
- weaken the reuse key to make more leaves share background work;
- silently fall back to reuse after a trusted receipt is corrupt;
- make the 4-sample route the default without authenticated reuse evidence;
- recompute the canonical Dω during a claimed reused-background batch;
- alter the retained numerical centre during certification or validation;
- merge because CI is green;
- merge because mocked scheduler tests pass;
- merge because an agent says the code “looks fixed”;
- omit the exact-head acceptance artifact;
- infer operator approval;
- mark PR ready or merge autonomously;
- force-push, reset `main`, erase PR #65 history, or recreate PR #66 to bypass failed checks.

---

## 11. Required PR evidence

The PR description and completion report must state, with exact hashes where applicable:

```text
PR65 merged baseline SHA
PR66 head SHA
changed production files
changed test files
root-readout provider design
root-readout authentication fields
recovery root-readout behavior
zero-numerics recovery proof
exact-root reuse proof
zero-root-recompute proof
background-equivalence proof design
first-reuse receipt hashes
4-sample reuse proof
9-sample fallback proof
missing/tampered receipt outcomes
binary64 zero-Julia proof
no-inline-promotion proof
focused test results
full permitted suite results
hosted workflow results
native Canary A–G results
native log hashes
artifact hashes
known limitations
operator review timestamp
landing approval status
```

A statement without a corresponding test, artifact, log, or deterministic code reference must be labelled **UNVERIFIED**.

---

## 12. Definition of done

PR #66 is complete only when every item below is satisfied.

### Architecture

- [ ] Production schema-11 survey consumes exact authenticated root-readout-store evidence.
- [ ] Recovery authenticates root-readout entries rather than merely listing store availability.
- [ ] Exact compatible root readout prevents root recomputation.
- [ ] Conflicting or corrupt trusted readouts fail closed.
- [ ] Production binary64 survey supplies a real equivalence-receipt resolver.
- [ ] First cross-mechanism reuse requires exact key plus durable `background-equivalence/v1` proof.
- [ ] Missing proof executes the 9-sample fallback.
- [ ] Valid proof executes the 4-sample reused-background route.
- [ ] Claimed reused Dω is not recomputed.

### Tests

- [ ] Failing regressions demonstrate both PR #65 production-wiring defects.
- [ ] Production-adapter integration tests pass.
- [ ] Negative authentication and tamper tests pass.
- [ ] Recovery remains zero-numerics.
- [ ] Binary64 remains zero-Julia.
- [ ] No inline promotion is reintroduced.
- [ ] Full permitted Python suite passes.
- [ ] Hosted Windows, Ubuntu, and Julia jobs pass.

### Native acceptance

- [ ] Canary A passes.
- [ ] Canary B passes.
- [ ] Canary C passes.
- [ ] Canary D passes.
- [ ] Canary E passes.
- [ ] Canary F passes.
- [ ] Canary G passes.
- [ ] All canaries bind to the exact PR head.
- [ ] All required log and artifact hashes are recorded.

### Governance

- [ ] `docs/engineering/pr66-native-acceptance.json` exists and validates.
- [ ] `docs/engineering/pr66-completion-report.md` exists.
- [ ] Remaining limitations are explicit.
- [ ] PR remains draft after technical gates pass.
- [ ] Operator personally reviews the exact-head receipt.
- [ ] Operator gives explicit landing approval.
- [ ] Only then is the PR marked ready and merged through the protected path.

Until every applicable checkbox is satisfied, the only accurate status is:

```text
PR #66 — INCOMPLETE
```
