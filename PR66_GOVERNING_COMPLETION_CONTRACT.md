# **[PR #66](https://github.com/vbrodi23-lgtm/Kerr-QNM_Windows-Solver/pull/66) — Governing Completion Contract**

## Root-readout reuse, authenticated exterior-background reuse, and acceptance-governance repair

> **Authority:** This committed file is the sole authoritative source for PR #66. It is additive to the PR #65 governing contract and supersedes it wherever the two conflict on root-readout recovery, cross-mechanism Dω reuse, production integration evidence, acceptance receipts, draft status, or landing authority. The PR body must point here rather than maintain a second normative copy.
>
> **Starting point:** PR #65 was merged as commit `261fd3a371fcfbe83ada0e857625c1436ac357eb`. PR #66 is a forward repair from the current protected branch. Do not reset `main`, rewrite published history, force-push, or conceal the PR #65 merge.
>
> **Execution airgap:** Development agents may inspect, write, edit, statically validate, and run permitted non-production tests. They must not execute the production Kerr/GSN solver, the Julia numerical worker, the M02 PowerShell campaign, or mathematical acceptance canaries. Native execution belongs to the operator, who returns the logs and artifacts for review.
>
> **Merge rule:** Hosted CI, mocked tests, static checks, and agent assurances are not landing authority. PR #66 remains draft until the tested-code-head native acceptance receipt exists in its metadata-only finalisation commit, the operator reviews it, and the operator gives explicit external landing approval. No agent may infer approval, mark the PR ready, request merge, or merge autonomously.

---

## 0. Authoritative completion decisions

The following decisions close the governing ambiguities identified during review. They are normative and supersede any conflicting wording elsewhere in this contract.

1. **Root-seal reuse is exact-identity reuse, not leaf ownership.** After a root readout has been authenticated against its original request and converted into a durable root seal, the originating leaf remains provenance rather than an ownership boundary. Any selected leaf may reuse that seal when every field that determines the root solve matches exactly, including Kerr root/background, mode, branch, angular identity, equation/backend/runtime identity, numerical policy, and all other root-solving inputs. Mechanism ID or leaf ID participates only when it genuinely changes the root-solving identity. Root-seal reuse remains distinct from Dω reuse, which additionally requires the exact Dω reuse key and an admissible `background-equivalence/v1` receipt.
2. **Background equivalence is an exact structural construction identity.** `background-equivalence/v1` proves that the mechanism-specific exterior determinant at c = 0 reduces to the canonical unperturbed exterior determinant under the same root seal, branch, angular data, determinant family, convention, normalisation, controls, precision, frequency-step policy, and match/readout convention. The perturbing profile contributes identically zero at c = 0, so the resulting determinant operation is the canonical background operation. No numerical tolerance, ULP threshold, or five-sample discrepancy bound defines admission. Bit-for-bit equality may be recorded as a deterministic regression check only when both calculations traverse the same implementation and runtime. If the exact zero-coupling identity cannot be proven, cross-mechanism Dω reuse remains disabled.
3. **The ordinary nine-sample fallback generates first-use evidence.** For the first leaf under an exact reuse key without admissible equivalence evidence, execute the normal nine-sample calculation: five c = 0 samples for D₀/Dω and four mechanism-specific c samples for D_c. Seal the canonical background evidence and `background-equivalence/v1` proof from that already-required work. Do not schedule a separate five-sample equivalence job. A later leaf with the same exact reuse key and a valid receipt performs only the four D_c samples.
4. **Numerical reuse admission is exact-key scoped.** A reusable structural mechanism/contract proof may establish the general zero-coupling construction identity, but it cannot authorize a cached Dω at arbitrary numerical backgrounds. The durable admission receipt binds the exact reuse key, including root seal, root identity, branch, angular identity, determinant family, convention, normalisation, backend/runtime, controls, precision, step policy, and match/readout convention. Any change to those fields produces a different reuse key and requires a receipt bound to that key.
5. **Git provenance fields contain Git OIDs.** Store Git's actual 40-character commit object IDs under the unambiguous names `tested_code_head_git_oid`, `main_base_git_oid`, and `receipt_commit_git_oid`. Do not hash the textual Git OID or label it `*_sha256`. Separate artifact content digests remain SHA-256 values and must be named accordingly.
6. **Acceptance uses one metadata-only finalisation commit.** Let X be the exact tested code head on which the operator runs the native Canaries A–G and additive mathematical canaries. The final commit Y may add only the acceptance receipt and explicitly permitted completion metadata, with `parent(Y) = X`. The receipt records X as `tested_code_head_git_oid` and Y as `receipt_commit_git_oid`. A deterministic X→Y diff check must prove that Y changes no executable code, numerical policy, scientific configuration, tests, worker code, runtime code, campaign selection, or other solver-affecting material. Any substantive change voids the exception and requires the canaries to be rerun on the new code head. Y must not be represented as the numerically tested executable state.
7. **Landing approval remains external.** The committed acceptance receipt keeps `landing_approval_status` equal to `PENDING`. The authoritative approval event is the operator's explicit GitHub PR review or comment. Do not create an approval-only commit. If machine-readable approval provenance is later required, record the GitHub review/comment identifier or merge metadata outside the tested code tree.

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
→ tested-code-head acceptance receipt written in one metadata-only finalisation commit
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
15. **The first admitted reuse for each exact reuse key must be backed by a durable exact-key receipt.** A reusable structural mechanism/contract proof may be consumed as one component, but subsequent numerical reuse still requires the exact-key receipt that binds the numerical background.
16. **No survey pass performs inline promotion.**
17. **Binary64 survey launches zero Julia workers.**
18. **Promoted survey remains separate from certification and validation.**
19. **Unexpected programming, protocol, or integration defects abort before the next leaf and are never converted into terminal numerical science.**
20. **`FAILED` remains operational, not scientific.**
21. **PR #66 cannot be declared complete from hosted CI alone.**
22. **Any solver-affecting commit after native acceptance invalidates the tested-code-head receipt and requires affected canaries to be rerun.** The sole exception is the strictly metadata-only finalisation commit defined in authoritative decision 6.
23. **PR #66 remains draft until explicit operator landing approval is recorded.**
24. **No automated agent has landing authority.**

---

## 4. Required production architecture

### 4.1 Authenticated root-seal provider

Introduce one production-owned root-seal acquisition boundary used by both binary64 and promoted schema-11 survey passes.

The provider must search in this order:

```text
1. exact current-checkpoint terminal record
2. exact SolvedLeafStore terminal receipt
3. exact recovered/authenticated RootReadoutStore entry
4. exact seal solved and published earlier in the current pass
5. no reusable root seal
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

The first cross-mechanism Dω reuse under an exact reuse key must create or consume a durable `background-equivalence/v1` receipt proving that:

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
- mechanism-specific zero-coupling batch SHA-256 when a distinct batch exists;
- exact structural zero-coupling proof identity and contract version;
- structural mechanism/contract proof SHA-256;
- optional bit-for-bit deterministic regression result when both routes traverse the same implementation and runtime, never as the mathematical admission criterion;
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
→ seal the canonical background evidence and exact-key background-equivalence proof from that ordinary batch when the structural zero-coupling identity is proven
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
docs/engineering/pr66-native-acceptance.md
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
- no committed acceptance receipt permits `landing_approval_status` to differ from `PENDING`.

---

## 7. Operator-run native canaries

All canaries bind to tested code head X. Any later solver-affecting commit invalidates affected results. The sole permitted successor is metadata-only finalisation commit Y defined in authoritative decision 6.

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

## 8. Mandatory tested-code-head acceptance artifact

Create `docs/engineering/pr66-native-acceptance.json` with a closed schema containing at least:

```text
schema
repository
pr_number
branch
base_branch
tested_code_head_git_oid
main_base_git_oid
receipt_commit_git_oid
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
operator_canary_executor_identity
landing_approval_status
receipt_sha256
```

Rules:

- `landing_approval_status` begins as `PENDING`.
- Agents cannot change it to `APPROVED` on their own.
- Operator approval remains external to the repository receipt and is tied to an explicit GitHub PR review or comment.
- The receipt validator recomputes all deterministic hashes.
- A tested-code-head Git OID mismatch invalidates the receipt.
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
9. Freeze tested code head X. Operator runs Canaries A–G and all mandatory additive canaries against X.
10. Create exactly one metadata-only finalisation commit Y with `parent(Y) = X`, containing only the acceptance receipt and explicitly permitted completion metadata.
11. Record X as `tested_code_head_git_oid`, Y as `receipt_commit_git_oid`, and the actual main-base Git OID as `main_base_git_oid`. Prove deterministically that X→Y changes no executable, scientific, runtime, worker, test, campaign-selection, or solver-affecting material. Any substantive change requires rerunning the canaries on the new tested code head.
12. Agent presents the completed receipt, whose landing status remains `PENDING`, and stops.
13. Operator reviews it and explicitly approves or rejects landing through a GitHub PR review or comment. No approval-only repository commit is permitted.
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
- omit the tested-code-head acceptance artifact or its metadata-only finalisation proof;
- infer operator approval;
- mark PR ready or merge autonomously;
- force-push, reset `main`, erase PR #65 history, or recreate PR #66 to bypass failed checks.

---

## 11. Required PR evidence

The PR description and completion report must state, with exact hashes where applicable:

```text
PR65 merged baseline SHA
tested code head Git OID X
receipt/finalisation commit Git OID Y
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
- [ ] `docs/engineering/pr66-native-acceptance.md` exists.
- [ ] Remaining limitations are explicit.
- [ ] PR remains draft after technical gates pass.
- [ ] Operator personally reviews the tested-code-head receipt and records any landing decision externally on GitHub.
- [ ] Operator gives explicit landing approval.
- [ ] Only then is the PR marked ready and merged through the protected path.

Until every applicable checkbox is satisfied, the only accurate status is:

```text
PR #66 — INCOMPLETE
```

<!-- PR66-ADDENDUM-01-START -->

---

# Addendum 01 — Expanded PR65 Defect Register and Mandatory PR66 Repair Gates

> **Status:** Binding additive update to the PR66 Governing Completion Contract.
>
> **Baseline inspected:** merged PR65 state at merge commit `261fd3a371fcfbe83ada0e857625c1436ac357eb`, whose PR head was `840be3d9d344de2393f48b8293c37a4c6be35889`.
>
> **Additive rule:** Nothing in this addendum relaxes, replaces, narrows, or postpones any requirement already present in the PR66 contract. Where two provisions overlap, the stricter provision governs.
>
> **Completion rule:** Every defect and gate below is mandatory unless explicitly marked as an optional incident-specific canary. An agent may not move a mandatory item into follow-up work, call it out of scope, or declare PR66 complete while it remains open.

## 1. Review determination

The second review materially expands the verified PR65 failure set.

The following findings are accepted as confirmed defects in the merged production state:

1. the release-evidence gate was removed from `campaign-reduce`;
2. binary64 fixed-root survey constructs an unapproved determinant-error surrogate from post-processing ULPs and stencil disagreement;
3. promoted fixed-root survey constructs an unapproved determinant-error surrogate from `predicted_reliable_digits`;
4. the promised deterministic schema-9 compatibility adapter is absent;
5. the PR63 incident oracle is not evaluated;
6. `VALIDATED` does not currently prove an independent validation route;
7. binary64 horizon failures are collapsed into an invented determinant-uncertainty promotion reason;
8. whole-atlas projective triage is not wired to actual projective results;
9. the schema-11 dashboard omits required evidence counts and does not reliably read the new fixed-root record shape;
10. PR65 merged without its mandatory exact-head acceptance artifact;
11. a giant PR-specific governing document was committed into the repository root;
12. the newest `.tasks/WORK_LOG.md` entry was deleted rather than superseded additively;
13. public CLI documentation and the implemented parser disagree;
14. `-NewCampaign` is implemented through zero-source recovery and therefore records false recovery semantics;
15. the recovery suite uses synthetic count tests but does not prove real schema-9 recovery.

One allegation requires narrower wording:

- `m02.ps1` validates `$SelectionPath` but later forwards `$Selection`. Under the current `Push-Location $PackageRoot` behaviour, ordinary relative paths are generally resolved against the same package-root base, so the claimed failure is not universal as stated. The implementation is nevertheless brittle and needlessly depends on an implicit current-directory equivalence. PR66 must forward the already-resolved absolute path everywhere and prove path identity from an external working directory. This is a mandatory hardening requirement, not evidence that every present relative-path invocation fails.

The three defects already recorded in the original PR66 contract remain mandatory:

- production schema-11 survey does not consume authenticated `RootReadoutStore` root seals;
- production binary64 survey passes `equivalence_receipt_lookup=None`, disabling authenticated cross-mechanism Dω reuse;
- PR65 landed without the mandatory commit-bound acceptance receipt and explicit operator-controlled landing gate.

## 2. Scientific-validity boundary

PR66 must restore this non-negotiable distinction:

```text
floating-point representation error
≠ finite-difference truncation disagreement
≠ ODE integration error
≠ determinant numerical error
≠ rigorous response-disk radius
```

The following are diagnostic quantities unless and until a reviewed mathematical derivation proves otherwise:

```text
math.ulp of returned determinant values
coarse-versus-fine stencil disagreement
predicted_reliable_digits
scale × 10^(-predicted_reliable_digits)
```

None of those quantities, individually or in combination, may be represented as a bound on the underlying determinant calculation merely because they are finite, conservative-looking, or convenient to serialize.

A numerical disk may be called bounded only when every input radius is supplied by an approved error model whose scope, derivation, identities, controls, and review receipt are authenticated. A field named `not-claimed`, `unavailable`, `diagnostic`, `estimated`, or equivalent cannot support a `PRODUCED` bounded response.

Where the approved evidence is insufficient, the solver must do one of the following and nothing else:

```text
queue a permitted response promotion;
record UNRESOLVED after the permitted survey tiers are exhausted; or
halt with TODO: [HUMAN MATH REVIEW REQUIRED - exact blocker].
```

It must not invent the missing mathematics.

## 3. Mandatory defect repairs

### PR66-SCI-01 — Restore the release-evidence gate

**Defect**

PR65 deleted the `CERTIFIED`-or-stronger check from the public campaign reduction path. That allows SCREENED-only numerical centres to cross a boundary that the contract and README describe as release-inadmissible.

**Required correction**

1. `campaign-reduce` must fail before reduction if any selected component has no evidence-ledger entry or has evidence below `CERTIFIED`.
2. The evidence check must read the current schema-11 evidence ledger and must bind the exact numerical record and exact central stage.
3. A mixed set containing one SCREENED component must fail as a whole. Partial release reduction is forbidden.
4. A separate projective preview used for survey triage may consume SCREENED evidence only if it has a distinct non-release operation identity, a distinct output schema, an explicit `release_admissible: false`, and no path into admission.
5. `VALIDATED` remains stronger than `CERTIFIED`; it must not be downgraded or rewritten during reduction.

**Acceptance proof**

- SCREENED-only input is rejected with the exact release-evidence error.
- mixed CERTIFIED/SCREENED input is rejected before `reduce_projective_rows()` is called;
- all-CERTIFIED and all-VALIDATED inputs can reach reduction;
- changing only the evidence ledger to a weaker or detached centre fails authentication;
- the release-admission path independently rechecks the evidence level rather than trusting a reduction label.

### PR66-SCI-02 — Remove the fabricated binary64 determinant-error model

**Defect**

`screen_binary64_fixed_root_batch()` currently builds derivative radii from coarse/fine stencil disagreement plus ULPs of returned values, then uses a ULP-sized residual radius to produce a root-correction bound and response disk. This bounds parts of Python post-processing; it does not bound the numerical error of the ODE/determinant evaluations that produced those values.

**Required correction**

1. Remove every claim that ULP accumulation plus stencil disagreement is a determinant absolute-error model.
2. `determinant_certificate_status="not-claimed"` or equivalent must be structurally incompatible with `Binary64SurveyDisposition.PRODUCED`.
3. Without an approved binary64 determinant error model, the binary64 exterior survey may retain raw samples and a diagnostic point estimate, but it must not commit a bounded numerical record.
4. The required disposition is `PROMOTION_PENDING_RESPONSE` with one exact reviewed reason code for unavailable determinant-error evidence. That code must map to `RESPONSE`, never `ROOT`, in the closed promotion classifier.
5. If a binary64 determinant error model is proposed instead, implementation must stop at:

   `TODO: [HUMAN MATH REVIEW REQUIRED - binary64 exterior determinant absolute-error model and quotient propagation]`

   until the user supplies or explicitly approves the derivation and its receipt schema.
6. Higher precision is not permission to reinterpret the same unsupported formula as rigorous.

**Acceptance proof**

- a perfectly smooth analytic fake with no determinant-error evidence cannot produce a bounded record;
- ULPs of zero, subnormal, normal, large, and complex values never become a determinant certificate;
- coarse/fine agreement at machine precision still queues promotion when the underlying determinant error is unavailable;
- no `ComplexDisk` used for scientific production is created from unapproved radii;
- binary64 survey still launches zero Julia and performs no inline promotion.

### PR66-SCI-03 — Remove the fabricated promoted-survey error model

**Defect**

`screen_promoted_fixed_root_samples()` currently converts worker `predicted_reliable_digits` into an absolute determinant error approximately equal to `max(1, |D|) × 10⁻ᵈ`. That conversion is new production mathematics. No reviewed contract proves that the conditioning diagnostic is a rigorous determinant error bound.

**Required correction**

1. `predicted_reliable_digits` remains conditioning telemetry only.
2. No code may convert it into a determinant radius, derivative radius, root-correction radius, or response radius without an explicit human-reviewed mathematical receipt.
3. Promoted survey may produce a bounded result only from worker evidence carrying an approved absolute determinant-error model and exact per-sample error values.
4. The approved evidence must bind the worker operation, determinant family, convention, normalization, endpoint/control policy, precision tier, request SHA, runtime identity, sample role, and fixed root.
5. If the BF40 survey lacks the required evidence, it may proceed to BF80 only under a reviewed closed promotion rule.
6. If BF80 still lacks the required evidence, survey must stop at `UNRESOLVED` or the exact human-review blocker. BF120 remains forbidden in survey.
7. Certification may not be smuggled back into survey solely to obtain a radius. Survey and certification remain separate passes.

**Acceptance proof**

- changing `predicted_reliable_digits` alone cannot change a scientific response disk;
- a worker result with finite determinants and high predicted digits but no approved error evidence cannot become `PRODUCED`;
- a valid approved per-sample error receipt propagates through the derivative and quotient calculation without being replaced by a heuristic;
- the BF40→BF80 transition is bounded by the closed allowlist and BF80 terminates without BF120;
- the exact human-math blocker is durable and visible in the checkpoint/status surface.

### PR66-REC-01 — Implement deterministic `legacy-compatibility/v1`

**Defect**

The recovery implementation accepts schema 11, rejects poisoned schema 10, and labels schema 9 as incompatible without attempting the deterministic reconstruction required by the governing contract.

**Required correction**

1. Implement an explicit `legacy-compatibility/v1` adapter for authenticated schema-9 terminal records and compatible solved-leaf receipts.
2. The adapter may reconstruct a missing schema-11-only identity only when authenticated historical fields determine one unique current identity.
3. Ambiguous, incomplete, off-selection, policy-incompatible, or semantically changed records are ignored with exact reason codes. They are never guessed into compatibility.
4. Numerical record content must remain byte-identical whenever the schema permits direct preservation. Any unavoidable envelope translation must preserve every scientific value and must carry both source and translated digests in a compatibility receipt.
5. Evidence strength may only increase monotonically. Recovery may not weaken, replace, or reinterpret a terminal numerical record.
6. Schema 10 remains poisoned input and must not be repaired forward.
7. Recovery must remain zero-numerics: no backend construction, determinant evaluation, root solve, ODE solve, Julia launch, or worker import.
8. Source checkpoints and stores are immutable. Recovery writes a new destination only.

**Acceptance proof**

- use at least one real authenticated schema-9 checkpoint fixture from the project history, not a toy schema invented by the test;
- recover zero, one, seven, forty-two, forty-eight when supplied, and arbitrary N compatible records without count-specific code;
- preserve exact leaf IDs, states, stage mappings, scientific identities, and record hashes where historically defined;
- prove ambiguous reconstruction becomes an incompatible miss;
- prove schema 10 aborts or is quarantined as poisoned input;
- prove the source artifacts are byte-identical before and after recovery;
- prove zero numerical constructors and launches through the production CLI adapter.

### PR66-REC-02 — Make the incident oracle real

**Defect**

`oracle_path` currently changes only an `AVAILABLE`/`INCOMPLETE_FIXTURE` label. The oracle is not parsed and is not compared with recovered records.

**Required correction**

1. Parse the reviewed incident oracle through a closed, duplicate-rejecting schema.
2. Authenticate the oracle file hash and bind its campaign/selection identity.
3. Compare every oracle row against the recovered candidate by leaf ID, terminal state, record hash, and every other field declared authoritative by the oracle schema.
4. Report separate lists for missing rows, unexpected rows, state mismatches, hash mismatches, and malformed rows.
5. Oracle status is exactly one of:

```text
NOT_SUPPLIED
INCOMPLETE_FIXTURE
PASS
MISMATCH
```

6. `AVAILABLE` is not a scientific result and must not be used as an incident-canary success state.
7. The oracle never authorizes a record and never bypasses receipt validation.
8. With the complete matching PR63 fixture, the optional incident canary must prove 48 recovered / 45 PRODUCED / 3 UNRESOLVED / 0 fabricated.
9. Missing incident material remains non-blocking for generic product completion, but it blocks every exact PR63 recovery claim.

**Acceptance proof**

- exact fixture produces `PASS` and a row-by-row receipt;
- one removed row produces `INCOMPLETE_FIXTURE` or `MISMATCH` as defined by the supplied-material state;
- one changed state or hash produces `MISMATCH`;
- duplicate oracle keys or rows fail closed;
- the output receipt identifies every compared file and digest.

### PR66-EVD-01 — Make `VALIDATED` genuinely independent

**Defect**

Certification and validation currently execute the same promoted-horizon or promoted-exterior production machinery, with validation distinguished mainly by a refinement parameter. Agreement of the same computational route with itself is not independent validation.

**Required correction**

1. Certification and validation must have distinct operation identities, request schemas, execution functions, and receipts.
2. A validation request must be structurally unable to call the certification operation as its independent comparator.
3. Changing a refinement integer, tolerance, endpoint, or precision inside the same mathematical route is not sufficient independence by itself.
4. Exterior validation must use the reviewed finite-amplitude/root-displacement route or another explicitly approved independent formulation, not only the fixed-root derivative route used to produce the centre.
5. Horizon validation must use an explicitly reviewed independent finite-amplitude/scattering comparator or another independent formulation, not only the same analytic horizon formula and derivative evidence used to produce the centre.
6. The validation receipt must identify:

```text
central method and operation identity
independent method and operation identity
independent code path identity
independent request and runtime identities
comparison disk and discrepancy result
human-review receipt for the independence claim
```

7. If the independent route is unavailable or unreviewed, evidence remains `CERTIFIED`. It may not be relabelled `VALIDATED`.
8. Disagreement records a discrepancy and preserves the retained centre. It does not silently replace the centre.

**Acceptance proof**

- a test substitutes the certification function into validation and proves the request is rejected;
- validation and certification receipts have different authenticated operation identities;
- a same-route refinement agreement cannot upgrade to `VALIDATED`;
- a reviewed independent-route agreement can upgrade exactly the selected leaf;
- an independent-route disagreement leaves the prior evidence level unchanged and records the discrepancy.

### PR66-FLT-01 — Preserve the true binary64 horizon failure cause

**Defect**

`_horizon_outcome()` currently converts every unsuccessful or response-less binary64 horizon result into `DETERMINANT_UNCERTAINTY_TOO_LARGE` and queues response promotion. That can relabel geometry, order, resource, protocol, branch, or system failures as precision insufficiency.

**Required correction**

1. Preserve the exact typed failure code and complete diagnostics emitted by the horizon production result.
2. Route that exact report through the closed `classify_failure()` boundary.
3. Only the reviewed static promotion allowlist may create a promotion entry.
4. Leaf-local exhaustion remains `UNRESOLVED`; resource postponement remains `DEFERRED`; physical rejection remains `REJECTED`; system or contract defects abort immediately.
5. Unknown, malformed, incomplete, or detached failure evidence is a system failure.
6. No adapter may manufacture `DETERMINANT_UNCERTAINTY_TOO_LARGE` merely because `response is None` or `status != CONVERGED`.
7. The queue kind must follow the reviewed meaning of the failure. A response-bound failure cannot silently become a root replacement request.

**Acceptance proof**

- table-driven production-adapter tests cover every horizon failure code;
- geometry/order exhaustion does not promote;
- ODE resource limits defer rather than promote;
- approved arithmetic insufficiency promotes with the correct queue kind;
- MethodError, ValueError, malformed payloads, and unknown codes stop before the next leaf;
- no numerical `FAILED` record is created.

### PR66-TRI-01 — Complete whole-atlas projective triage

**Defect**

The schema-11 runtime configures triage without configuring the advanced projective projection. `write_schema11_triage()` then assigns `projective_angle_lower_bound=None` and `controls_projective_classification=False` to every leaf. The queue therefore cannot rank the smallest projective separations or the leaves that control projective classification.

**Required correction**

1. Generate the authenticated advanced projective projection before whole-atlas triage whenever the required central records exist.
2. Triage must consume the exact projective output bound to the same checkpoint source receipt.
3. Populate each eligible leaf's minimum relevant projective angle lower bound and whether it controls any projective classification.
4. Projective rows with missing, unresolved, or evidence-inadmissible components remain explicit; they are not converted to zeros or silently dropped.
5. If projective projection fails, basic reports survive and triage reports `NOT_RUN_PROJECTIVE_BLOCKED`. It must not pretend to be a complete whole-atlas ranking.
6. The mixed-role certification queue must deterministically include projective controllers, smallest-angle rows, risk sentinels, disagreements, near-zero components, near-extremal support risks, and the existing mode/mechanism coverage requirements.
7. Queue order and identity must be deterministic under input permutation.

**Acceptance proof**

- an atlas fixture with known projective controllers populates both fields;
- the smallest angle lower bounds affect ranking in the required direction;
- forcing projective failure leaves basic CSVs intact and blocks complete triage;
- changing the checkpoint invalidates both projective and triage receipts;
- no queue can claim whole-atlas completeness while all projective fields are null/default false.

### PR66-UI-01 — Repair schema-11 dashboard evidence and response projection

**Defect**

The current schema-11 summary counts numerical/pass dispositions but omits campaign counts for `SCREENED`, `CERTIFIED`, and `VALIDATED`. The dashboard response reader searches historical `component_result` shapes and can miss fixed-root schema-11 records that store `retained_centre` and a stage-level `response_disk`. Some schema-11 progress scopes omit leaf ordinal/count/mode/mechanism context.

**Required correction**

1. The authoritative summary must include:

```text
selected
completed numerical records
queued
unresolved
deferred
rejected
system failures
no evidence
SCREENED
CERTIFIED
VALIDATED
```

2. Counts are derived directly from the checkpoint and evidence ledger, never inferred from CSV presence.
3. The dashboard and basic report projection must read every current numerical-record shape, including fixed-root records with `retained_centre` and stage `response_disk`.
4. When those fields exist and validate, `|RESPONSE|`, response-disk radius, and relative disk must not render as `-`.
5. Every leaf/pass progress scope must carry the available leaf ordinal, leaf count, role, mode, spin/source coordinate, mechanism, pass, precision tier, and leaf ID.
6. A live line may omit a field only when that field is genuinely unavailable, not because the adapter failed to propagate it.
7. The clean-tail contract remains: completed rows append once; live execution occupies one bounded physical line; no multi-line redraw.
8. Status JSON and the terminal view must agree on counts and active identity.

**Acceptance proof**

- one real fixed-root schema-11 record renders finite magnitude and relative radius;
- evidence-count transitions none→SCREENED→CERTIFIED→VALIDATED are reflected without rewriting the numerical record;
- a running leaf shows ordinal/count/mode/spin/mechanism/pass/precision;
- an advanced-report failure does not erase dashboard counts;
- compact and full renderers preserve the same scientific values.

### PR66-GOV-01 — Enforce the acceptance artifact and landing authority

**Defect**

PR65 merged without the required commit-bound acceptance artifact. Hosted green checks were treated as completion even though the governing contract required exact-head native evidence and explicit operator review.

**Required correction**

1. PR66 remains draft until every mandatory gate in the original contract and this addendum passes against tested code head X and the acceptance receipt is added by the sole metadata-only finalisation commit Y.
2. PR66 must contain:

   `docs/engineering/pr66-native-acceptance.json`

3. The artifact must bind at minimum:

```text
PR number, tested code head Git OID X, and receipt/finalisation commit Git OID Y
main-base Git OID and merged PR65 baseline Git OID
SHA-256 of the complete PR66 governing contract
selection artifact and tested-code-head campaign/selection IDs
leaf and role counts
focused and full permitted test commands and results
hosted workflow run IDs and job conclusions
operator-run native canary commands, exit codes, log hashes, and artifact hashes
root-readout reuse receipts
background-equivalence/v1 receipts
human-math review receipt status for every scientific error model
independent-validation route receipts
incident-canary status
known limitations
landing approval status
```

4. A schema validator must reject missing fields, a stale tested-code-head Git OID, a finalisation commit whose parent is not X, a non-metadata-only X→Y diff, a stale contract hash, unhashed logs, unapproved mathematical models, or any landing state other than `PENDING`.
5. Passing checks does not mark the PR ready. The implementing agent stops and presents the tested-code-head artifact from metadata-only finalisation commit Y.
6. Only the user may give landing approval. No agent may infer it from silence, green checks, prior frustration, urgency, or the existence of the artifact.
7. Any solver-affecting commit after acceptance invalidates the affected canaries and requires a new tested-code-head receipt. The sole exception is the strictly metadata-only finalisation commit defined in authoritative decision 6.

**Acceptance proof**

- missing artifact blocks completion;
- a stale tested-code-head Git OID blocks completion;
- a forged operator approval field blocks completion;
- all green hosted checks with missing native logs still block completion;
- the PR remains draft until an explicit operator instruction changes that state.

## 4. Mandatory operational and provenance repairs

### PR66-OPS-01 — Remove PR-specific debris from the active repository root

1. Remove `PR65_GOVERNING_PR_COMPLETION_RESTORED_ADDITIVE.md` from the active repository tree.
2. Preserve it through Git history; do not rewrite or erase history to hide the mistake.
3. Do not commit the PR66 governing contract into the repository root.
4. The PR66 front-page body is the governing review surface. Any durable machine-readable acceptance material belongs under `docs/engineering/` with an explicit current purpose.
5. Add a static public-surface test rejecting `PR[0-9]+_*GOVERNING*`, handover, scratch, or completion-contract debris at repository root unless explicitly allowlisted by the user.

### PR66-OPS-02 — Restore chronological work-log provenance

1. Restore the exact removed 2026-08-22 PR63 entry from parent commit `0be6dfcc8b5dbcfc402ec6856d29290b9e95c696`.
2. Do not alter its wording to make PR63 appear successful.
3. Add a new PR65 incident entry above it describing the merge, the missing acceptance gate, and the defects discovered after landing.
4. Add PR66 entries additively as work is completed.
5. Work-log cleanup may move superseded detail into Git history only through an explicit separately reviewed cleanup; it may not delete the newest historical milestone while retaining older entries.
6. Add a test that the newest known milestone entries remain present and ordered newest-first.

### PR66-OPS-03 — Reconcile the public CLI and documentation

The explicit schema-11 pass commands remain canonical:

```text
campaign-survey-binary64
campaign-survey-promoted
campaign-certify
campaign-evidence-validate
```

PR66 must not restore unsafe automatic profile chaining merely to preserve an obsolete flag.

Required behaviour:

1. Update README, architecture documentation, runbooks, examples, and help text in the same PR so every documented command parses on the exact head.
2. Remove the invalid documented `campaign-plan ... --profile survey` form unless `--profile` is intentionally restored for planning with defined semantics.
3. Old `campaign-run/resume --profile`, `--triage-queue`, and `--queue-limit` invocations must either:
   - remain supported through a safe compatibility adapter with exact equivalent semantics; or
   - fail with a specific migration message naming the replacement command.
4. Generic argparse “unknown argument” is insufficient for a deliberately retired public option.
5. Add a parser/documentation parity test that executes every fenced public command in dry-run/help mode.

### PR66-OPS-04 — Forward resolved path identities

This is a hardening requirement rather than a claim that every current relative path fails.

1. Once `m02.ps1` resolves `$SelectionPath`, every subsequent solver invocation must use `$SelectionPath`, never the original `$Selection` string.
2. Apply the same rule to checkpoint, queue, calibration receipt, recovery candidate, and other operator-supplied file paths.
3. Log the resolved absolute paths before execution.
4. Preserve spaces, Unicode, `..` normalization, and Windows drive semantics without reparsing after `Push-Location`.
5. A Windows canary must invoke the launcher from outside the repository directory using absolute and caller-relative paths and prove that validation and execution consume the same file hash.

### PR66-OPS-05 — Separate NEW from RECOVER

1. Add a dedicated new-campaign constructor/command that writes an empty schema-11 checkpoint with origin `NEW`.
2. `m02.ps1 -NewCampaign` must call that constructor, not zero-source `campaign-recover`.
3. A new campaign must not contain a recovery summary, recovery receipt, accepted recovery sources, or an `oracle_status` field.
4. `campaign-recover` remains explicit and writes origin `RECOVER` plus its authenticated recovery receipt, even when zero compatible records are recovered from supplied material.
5. NEW and RECOVER checkpoints may share the same numerical schema but must preserve distinct origin semantics.
6. Resume must accept either origin after validating the checkpoint.

### PR66-OPS-06 — Replace toy confidence with production-boundary evidence

1. Keep the useful synthetic 0/1/7/42/N tests, but stop treating them as proof of historical compatibility.
2. Add real schema-9 fixtures and exact expected compatibility receipts.
3. Add production-adapter tests for `run_native_binary64_pass()`, not only direct scheduler tests with injected root seals and equivalence functions.
4. Prove an exact `RootReadoutStore` hit prevents a promoted root queue entry and causes zero root solves.
5. Prove the production runtime supplies and persists `background-equivalence/v1` rather than passing `None`.
6. Add negative tests for every absent or detached scientific receipt.
7. Mocked tests may prove orchestration. They may not satisfy a named native, mathematical, or persistence boundary.

## 5. Required implementation order

Agents must implement PR66 in this order unless the user explicitly changes it:

1. Freeze the PR65 merged baseline and add failing regression tests for every confirmed defect.
2. Restore the release-evidence gate.
3. Remove both unapproved survey error models and establish the exact human-math blockers.
4. Implement real schema-9 compatibility and real oracle comparison.
5. Wire production root-readout reuse and authenticated Dω background reuse from the original PR66 contract.
6. Repair horizon failure classification.
7. Wire projective projection into triage and repair dashboard/report projections.
8. Implement genuinely independent validation with reviewed route identities.
9. Separate NEW from RECOVER and harden all path forwarding.
10. Restore work-log provenance, remove root debris, and reconcile public documentation.
11. Run the complete permitted static and software suite.
12. Stop for operator-run native and mathematical canaries.
13. Write and validate the tested-code-head PR66 acceptance artifact in the sole metadata-only finalisation commit.
14. Stop with landing approval `PENDING`.

An agent may work on independent items in parallel, but it may not present downstream green tests as meaningful while their upstream scientific or identity gate remains unimplemented.

## 6. Additive mandatory test matrix

| ID | Boundary | Required proof |
|---|---|---|
| `PR66-T01` | Release gate | SCREENED and mixed evidence fail before reduction; CERTIFIED/VALIDATED pass authentication |
| `PR66-T02` | Binary64 science | ULP/stencil agreement cannot produce a bounded record without approved determinant error evidence |
| `PR66-T03` | Promoted science | `predicted_reliable_digits` cannot alter a scientific radius; missing approved error evidence blocks |
| `PR66-T04` | Real legacy recovery | Authenticated schema-9 fixture recovers deterministically with zero numerics; schema 10 remains poisoned |
| `PR66-T05` | Incident oracle | Exact rows pass; missing, duplicate, changed, and unexpected rows are detected and receipted |
| `PR66-T06` | Root-readout integration | Production adapter consumes exact store hit and performs zero root solve/worker launch |
| `PR66-T07` | Dω integration | Production adapter supplies exact key plus durable `background-equivalence/v1`; missing receipt disables reuse |
| `PR66-T08` | Horizon failures | Every typed horizon failure retains its code and enters only its reviewed disposition |
| `PR66-T09` | Projective triage | Authenticated angle bounds/controllers feed deterministic mixed-role ranking |
| `PR66-T10` | Dashboard | Evidence counts and fixed-root response/disk values render from checkpoint; live identity is complete |
| `PR66-T11` | Independent validation | Same-route refinement cannot upgrade; distinct reviewed route can |
| `PR66-T12` | NEW versus RECOVER | NEW has no recovery semantics; RECOVER has exact source receipt; both resume safely |
| `PR66-T13` | CLI/docs parity | Every published command parses; retired flags return explicit migration guidance |
| `PR66-T14` | Path identity | External-working-directory invocation validates and executes the same absolute file SHA |
| `PR66-T15` | Provenance hygiene | PR63 work-log entry restored; PR65 incident appended; root PR document absent |
| `PR66-T16` | Acceptance gate | Stale/missing/forged tested-code-head acceptance artifact or non-metadata-only finalisation blocks completion and ready state |

The tests must assert production call counts and operation identities. Assertions that merely search source text, inject the missing production dependency directly, or test a toy record shape are not sufficient for the relevant production boundary.

## 7. Additive operator-run canaries

The development agent must not execute these canaries. The operator runs them under the existing execution airgap and returns logs.

### Canary X1 — Fresh NEW origin

```text
new non-existent checkpoint
empty solved-leaf store
empty root-readout store
-NewCampaign
→ schema 11 origin NEW
→ zero recovery receipts
→ binary64 pass only
→ no implicit promoted/certify/validate work
```

### Canary X2 — Real schema-9 recovery

```text
authenticated historical schema-9 input
→ new schema-11 candidate
→ exact compatible terminal record count N
→ lost 0
→ fabricated 0
→ determinant/root/ODE/Julia counts 0
→ source hashes unchanged
```

### Canary X3 — Survey error-model fail-closed boundary

```text
binary64 exterior samples without approved determinant-error receipt
→ no bounded PRODUCED record
→ exact response-promotion reason

BF80 promoted samples without approved determinant-error receipt
→ no heuristic radius
→ UNRESOLVED or exact HUMAN MATH REVIEW blocker
→ no BF120 survey
```

### Canary X4 — Root-readout-store consumption

```text
root seal exists only in authenticated root-readout store
→ binary64 exterior survey finds it
→ zero root solve
→ zero promoted-root queue entry
→ exact reuse receipt recorded
```

### Canary X5 — Authenticated Dω reuse

```text
first exterior mechanism produces canonical background
second compatible mechanism has exact reuse key
valid durable background-equivalence/v1 receipt exists
→ four mechanism samples only
→ Dω reused
→ receipt hash present in checkpoint/acceptance artifact
```

Repeat with the receipt missing or tampered:

```text
→ reuse disabled
→ full independent batch or typed block
→ no unauthenticated four-sample shortcut
```

### Canary X6 — Evidence and independent validation

```text
SCREENED centre
→ campaign-reduce rejected
CERTIFIED centre
→ release reduction authentication allowed
same-route validation attempt
→ VALIDATED upgrade rejected
reviewed independent-route agreement
→ exact selected leaf upgraded to VALIDATED
```

### Canary X7 — Projective triage and dashboard

```text
committed central atlas fixture
→ projective projection completed
→ non-null angle bounds/controllers for eligible rows
→ deterministic mixed-role queue
→ dashboard shows SCREENED/CERTIFIED/VALIDATED counts
→ fixed-root |RESPONSE| and relative disk visible
→ live line carries leaf ordinal/count/mode/spin/mechanism/pass/precision
```

### Canary X8 — Path and documentation surface

```text
invoke m02.ps1 from outside repository root
paths include spaces
resolved selection hash disclosed
same selection hash consumed by campaign-plan and requested pass
all README/runbook command examples parse on exact head
```

### Optional Canary X9 — Exact PR63 incident recovery

This canary is mandatory only when the complete matching incident fixture and oracle are supplied.

```text
oracle status PASS
recovered 48
PRODUCED 45
UNRESOLVED 3
fabricated 0
lost 0
record/hash mismatch 0
numerical work 0
```

If the fixture is incomplete, record `INCOMPLETE_FIXTURE`. Do not fabricate the missing evidence, do not claim the exact incident canary passed, and do not block unrelated generic completion gates.

## 8. Prohibitions added by this addendum

PR66 must not:

- restore release admission by changing labels while leaving `campaign-reduce` permissive;
- call a heuristic “conservative” and thereby promote it into a rigorous error bound;
- use ULPs of returned values as a proxy for ODE or determinant error;
- turn `predicted_reliable_digits` into `10⁻ᵈ` error without a reviewed derivation;
- let `determinant_certificate_status=not-claimed` support `PRODUCED`;
- run certificate-heavy work inside survey merely to hide the missing survey error model;
- use BF120 in survey;
- label the same mathematical/code route as independent because a refinement flag changed;
- ignore schema 9 and still claim generic historical recovery is complete;
- treat oracle-file existence as oracle success;
- collapse every horizon failure into determinant uncertainty;
- generate triage with permanent null projective evidence and call it whole-atlas;
- show `-` for response evidence that exists in the authenticated fixed-root record;
- delete historical work-log entries to make the active history look cleaner;
- commit another PR-specific governing document into repository root;
- leave README or runbooks showing commands the parser rejects;
- create a NEW campaign by forging a zero-source recovery event;
- satisfy production integration with a unit test that injects the missing integration dependency;
- mark PR66 ready, enable auto-merge, request merge, or merge before explicit operator landing approval.

## 9. Completion statement

PR66 is complete only when all of the following are simultaneously true:

```text
original PR66 defects                                  fixed
addendum PR66-SCI-01 through PR66-GOV-01              fixed
operational/provenance repairs                         fixed
unapproved error-model paths                           absent or human-approved
real schema-9 recovery                                 proven
release gate                                           fail-closed
independent VALIDATED route                            proven
projective triage                                      populated and authenticated
dashboard evidence/response projection                 correct
root-readout and Dω production reuse                   proven
NEW and RECOVER semantics                              distinct
CLI and documentation                                  reconciled
full permitted suite                                   PASS
hosted checks                                          PASS
mandatory original canaries                            PASS
additive Canaries X1–X8                                PASS
optional incident Canary X9                            PASS / INCOMPLETE_FIXTURE / NOT_SUPPLIED
tested-code-head acceptance artifact                    present and valid in metadata-only finalisation commit
known unresolved mandatory defects                     0
landing approval                                       PENDING until explicit operator review
```

The implementing agent then stops and states:

> Code and tested-code-head acceptance evidence written in the metadata-only finalisation commit. Awaiting operator review and explicit external landing decision.

It must not state that the solver is “completely fixed” merely because the software suite is green.

<!-- PR66-ADDENDUM-01-END -->
---

## 10. Corrective implementation directives

This section records the final corrective implementation directive. It tightens the earlier requirements without creating a second architecture. Where any earlier sentence conflicts, this section and the seven authoritative decisions in section 0 control.

### 10.1 Governing implementation sequence and airgap

Implementation proceeds as coherent, normally fast-forwarded blocks from the current remote PR66 head. Published history is preserved. PR66 remains draft. No agent may run the production Kerr/GSN solver, launch the Julia numerical worker, run the M02 PowerShell campaign, run mathematical/native acceptance canaries, infer native acceptance from hosted CI, create the final native-acceptance receipt, mark the PR ready, or merge it.

The production order remains:

```text
NEW / RESUME / RECOVER
→ SURVEY / BINARY64
→ durable promotion queue
→ SURVEY / PROMOTED
→ whole-atlas projective reduction
→ TRIAGE
→ CERTIFY
→ VALIDATE
→ RELEASE ADMISSION
```

NEW and RECOVER remain distinct. There is no automatic transition between passes.

### 10.2 Projective science must reach schema-11 triage

The required production sequence is:

```text
authenticated schema-11 checkpoint
→ projective row plans
→ authenticated projective reduction/preview
→ deterministic row-to-leaf triage projection
→ whole-atlas triage
→ certification queue
```

Projective reduction occurs before triage. The projection and triage bind the same scientific checkpoint receipt. Missing rows remain explicitly incomplete; they are never converted into zero angles or safe classifications. `controls_projective_classification` derives from actual selected-row participation. `projective_angle_lower_bound` derives from authenticated reducer output under the reviewed row-to-leaf aggregation rule. The non-release preview remains `release_admissible: false`.

TODO: [HUMAN MATH REVIEW REQUIRED - approve the deterministic projective row-to-leaf aggregation rule if it is not already specified by reviewed project mathematics]

### 10.3 Reviewed determinant-error evidence boundary

The removed binary64 and promoted self-certifying uncertainty models remain prohibited. An exterior sample may contribute to a bounded response disk only through an authenticated, human-approved determinant-error receipt binding the leaf/job and operation, root seal and fixed root, branch and angular identities, determinant family/convention/normalisation, backend/runtime, arithmetic tier and working precision, numerical controls, sample role/frequency/amplitude, determinant centre, absolute error bound, derivation identity/version, human-mathematics approval receipt SHA-256, and receipt SHA-256.

Absence remains `DETERMINANT_ERROR_EVIDENCE_UNAVAILABLE`. Malformed, mismatched, or tampered trusted evidence is a typed corruption/system failure. Complete compatible approved evidence may be propagated through Dω, D_c, and −D_c/Dω to produce a bounded SCREENED result.

TODO: [HUMAN MATH REVIEW REQUIRED - approve the fixed-root exterior determinant absolute-error construction and issue the governing derivation receipt]

### 10.4 One live authenticated root-seal provider

Binary64 and promoted survey use one production-owned live provider. Every solve authorization performs a fresh exact lookup in the section 4.1 order. A promoted ROOT queue entry records a prior miss; it is never solve authority. ROOT and RESPONSE promotions re-query current evidence. A newly authenticated promoted PRIMARY root is persisted and published immediately before fixed-root response work or the next leaf. Exact-compatible later leaves in the same pass reuse it. Conflicting authenticated seals produce `SYSTEM_FAILURE ROOT_SEAL_CONFLICT`; no newest-wins rule exists.

### 10.5 Durable production Dω/background reuse

One durable canonical-background store and one durable exact-key `background-equivalence/v1` receipt store serve the existing scheduler. First use without admissible evidence performs the ordinary nine samples, then atomically seals the canonical five-sample background and exact-key structural admission even when determinant-error evidence prevents the response from becoming PRODUCED. Later exact-compatible mechanisms authenticate both objects and perform only four mechanism samples. Missing or incompatible evidence takes the nine-sample fallback. Trusted corruption fails closed. Restart does not erase reusable evidence. The production adapter must never pass `equivalence_receipt_lookup=None`.

### 10.6 Per-record legacy compatibility

Schema-9 envelope authentication and `legacy-compatibility/v1` provenance remain. Each terminal legacy record is assessed individually: locate the selected leaf, reconstruct every available scientific identity field, compare it with the current computation identity, and import only when compatibility is uniquely and completely proven. Campaign-ID or selection-ID inequality alone is not a blanket decision. Imported records retain original numerical bytes where the schema permits and receive no inferred schema-11 evidence level. Off-selection records remain historical provenance. Insufficient identity yields `CURRENT_SCIENTIFIC_IDENTITY_UNRECONSTRUCTABLE`. Duplicate or conflicting candidates abort before destination replacement.

Recovery and every discovery/reuse boundary are cardinality-agnostic for any N ≥ 0 and report exact discovered, compatible, reused, rejected, empty, miss, corrupt, and conflict outcomes where applicable. Zero prior records is a normal NEW-campaign state and never creates false recovery provenance.

### 10.7 VALIDATED requires an independently admitted route

Evidence policy, not caller convention, enforces:

```text
independently defined calculation-route identity
+ approved human-mathematics review receipt
+ authenticated route-specific output
+ agreement with the retained centre
→ VALIDATED eligibility
```

Same-backend refinement may retain a comparator receipt and discrepancy information but cannot raise evidence above CERTIFIED. Forged route labels and missing approvals are rejected.

TODO: [HUMAN MATH REVIEW REQUIRED - approve a genuinely independent validation route before VALIDATED can be awarded]

### 10.8 Typed horizon failures and zero-Julia binary64 execution

The horizon adapter preserves the typed underlying failure. Only allowlisted arithmetic/precision insufficiency queues RESPONSE promotion. Resource exhaustion is DEFERRED, reviewed physical/algebraic rejection is REJECTED, reviewed leaf-local exhaustion is UNRESOLVED, and malformed/unknown/protocol/software failure is durable SYSTEM_FAILURE with immediate abort.

Resource generation belongs to bootstrap. Bootstrap may materialise and seal GSN resources. Binary64 campaign execution is load-only and has no Julia-launch path. Missing, stale, or corrupt resources fail before the first leaf with `GSN_BOOTSTRAP_REQUIRED` or the reviewed resource-preflight failure, with zero Julia launches and zero determinant evaluations.

### 10.9 Exact pass-completion predicates

Pass exhaustion, scientific resolution, and release admission are distinct. Binary64 exhaustion requires exactly one authenticated binary64 disposition for every selected leaf and authenticated queue entries for every promotion. Promoted exhaustion requires every promotion pending at pass start to have a terminal promoted disposition or authenticated cache supersession, with queue and promoted ledgers agreeing. Survey completion requires the applicable exhaustion predicates, a valid checkpoint, and no dangling in-progress state. UNRESOLVED, DEFERRED, or REJECTED leaves may coexist with exhaustion but never imply scientific completion or release admission. A partial or interrupted pass must report exact missing and dangling identities and must not emit `CAMPAIGN_PASS_COMPLETED`.

### 10.10 Final tested-code head and metadata-only finalisation

After all permitted software work, X is the exact tested implementation Git OID. The operator, not an agent, runs native acceptance against X. Only after the operator supplies and the project reviews that evidence may finalisation commit Y be created with `parent(Y) = X`.

The exact Y allowlist is:

```text
docs/engineering/pr66-native-acceptance.json
docs/engineering/pr66-native-acceptance.md
```

No other file may change in Y. The deterministic X→Y checker is implemented and software-tested before native acceptance. The receipt binds X and the native evidence and retains `landing_approval_status = PENDING`. Any later executable, test, scientific, policy, runtime, orchestration, or documentation-authority change invalidates X and requires the affected canaries to be rerun. No approval-only commit is permitted.
