# M02 Inner-Leaf Progress Instrumentation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add quiet, normal, and trace campaign progress that exposes every expensive inner-leaf phase without changing Kerr QNM mathematics or authenticated scientific artifacts.

**Architecture:** A context-scoped typed event bus carries out-of-band progress from campaign, component, root, determinant, and ODE seams. A human stderr renderer implements the three operator levels and a trace-only writer appends flushed per-leaf JSONL; the Julia worker streams reserved-prefix events through captured stdout, which Python forwards into the same bus.

**Tech Stack:** Python 3.12, Windows PowerShell 5.1, Julia 1.10.11, `unittest`, `contextvars`, `subprocess.Popen`, JSONL.

## Global Constraints

- Do not execute Julia, the GSN producer, `m02_worker.jl`, a physical determinant, or a Kerr solve in the developer environment.
- Do not change determinant equations, tolerances, iteration limits, damping values, amplitude ladders, ODE controls, endpoint orders, branch tests, or execution order.
- Do not add progress fields to Julia request/response documents, campaign checkpoints, checkpoint digests, evidence payloads, admission artifacts, or release identities.
- Keep the CLI success contract as exactly one canonical JSON object on stdout; write human progress only to stderr.
- `campaign-run` and `campaign-resume` default to `--progress normal`; valid values are exactly `quiet`, `normal`, and `trace`.
- Trace files are diagnostic sidecars at `<checkpoint>.progress/leaf-NNNNNN.jsonl`, append on resume, and flush every event.
- Emit checkpoint/stage/leaf completion only after the existing atomic checkpoint write succeeds.
- Use existing determinant, candidate, angular, endpoint, and ODE results for telemetry; never add a scientific evaluation for logging.
- Preserve the GSN producer/registry/cache architecture and the merged Windows bootstrap behavior.
- Treat the executor-reported one-leaf `COMPLETE`/`CONVERGED` checkpoint as the post-PR PowerShell comparison baseline, not as a new repository fixture.

---

### Task 1: Typed Progress Bus and Output Renderers

**Files:**
- Create: `src/windows_solver/progress.py`
- Create: `src/windows_solver/progress_output.py`
- Create: `tests/test_progress.py`

**Interfaces:**
- Produces: `ProgressMode`, `ProgressEventKind`, `ProgressContext`, `ProgressEvent`, `ProgressObserver`, `activate_progress(observer)`, `progress_scope(**values)`, `emit_progress(kind, **payload)`, `ingest_external_progress(value)`, and `CampaignProgressReporter(mode, checkpoint, stream)`.
- Preserves: no active observer is a no-op; progress output cannot enter canonical scientific mappings.

- [ ] **Step 1: Write failing event-bus and mode tests**

```python
def test_progress_scope_carries_the_complete_hierarchy_without_global_leakage():
    observer = RecordingObserver()
    with activate_progress(observer), progress_scope(
        leaf_index=1, leaf_count=1, leaf_id="leaf-1", role="primary",
        mode={"s": -2, "ell": 2, "m": 2, "n": 0}, spin=0.95,
        mechanism_id="horizon-admittance", precision_digits=64,
    ):
        emit_progress(ProgressEventKind.ROOT_PHASE_STARTED, phase="PRIMARY")
    emit_progress(ProgressEventKind.ROOT_PHASE_STARTED, phase="OUTSIDE")
    assert len(observer.events) == 1
    assert observer.events[0].context.leaf_id == "leaf-1"

def test_progress_modes_are_exact():
    assert [item.value for item in ProgressMode] == ["quiet", "normal", "trace"]
```

- [ ] **Step 2: Run red for the absent progress modules**

Run: `PYTHONPATH=src python -m unittest tests.test_progress -v`

Expected: import failure for `windows_solver.progress`.

- [ ] **Step 3: Implement the typed event bus**

```python
class ProgressMode(StrEnum):
    QUIET = "quiet"
    NORMAL = "normal"
    TRACE = "trace"

@dataclass(frozen=True, slots=True)
class ProgressEvent:
    kind: ProgressEventKind
    context: ProgressContext
    payload: Mapping[str, object]
    monotonic_seconds: float
```

Use one `ContextVar` for the active observer and one immutable context value.
`emit_progress` constructs one event and invokes the observer without changing
caller return values or scientific objects.

- [ ] **Step 4: Write failing renderer and JSONL tests**

```python
def test_quiet_renders_only_leaf_and_terminal_events(): ...
def test_normal_renders_identity_phase_newton_and_in_place_determinant_status(): ...
def test_trace_appends_session_marker_and_flushes_each_leaf_jsonl_event(): ...
def test_external_event_rejects_unknown_schema_or_kind(): ...
```

Assert that trace JSON objects contain schema, kind, session, sequence,
timestamps, hierarchy, and payload; assert that a second reporter session
appends rather than replaces the first file.

- [ ] **Step 5: Implement human and trace renderers**

`CampaignProgressReporter.publish(event)` must:

1. add session/sequence/timing metadata;
2. maintain per-leaf, per-phase Newton and determinant counters;
3. render the event set allowed by the selected mode to stderr;
4. in trace mode, append the full event to the current leaf file and flush;
5. close an in-place status line before ordinary summaries or terminal errors.

- [ ] **Step 6: Run focused green and mutation checks**

Run: `PYTHONPATH=src python -m unittest tests.test_progress -v`

Expected: every progress-core test passes. Confirm that removing context reset,
trace append mode, or flush causes a specific test failure.

- [ ] **Step 7: Commit the progress core**

```text
Add typed campaign progress events
```

### Task 2: Campaign Lifecycle, CLI, Checkpoint, and PowerShell Wiring

**Files:**
- Modify: `src/windows_solver/cli.py`
- Modify: `src/windows_solver/response_batches.py`
- Modify: `solver.ps1`
- Modify: `m02.ps1`
- Modify: `.github/workflows/ci.yml`
- Modify: `tests/test_linear_response_batches.py`
- Modify: `tests/test_public_surface.py`
- Modify: `.tasks/IN_PROGRESS.md`

**Interfaces:**
- Consumes: Task 1 event bus and `CampaignProgressReporter`.
- Produces: `campaign-run|campaign-resume ... --progress quiet|normal|trace`, normal default, durable post-checkpoint events, and `m02.ps1 -Progress` forwarding.

- [ ] **Step 1: Put the approved feature under TASK-075 control**

Add this exact plan item to TASK-075 without moving any task or changing its ID:

```text
- Add out-of-band quiet/normal/trace inner-leaf progress while preserving scientific execution and checkpoint/evidence bytes.
```

- [ ] **Step 2: Write failing parser and stream-contract tests**

```python
def test_campaign_progress_defaults_to_normal_and_accepts_exact_modes(): ...
def test_quiet_campaign_run_preserves_single_stdout_json_and_only_coarse_stderr(): ...
def test_normal_campaign_run_keeps_stdout_canonical_and_writes_human_stderr(): ...
def test_invalid_progress_mode_returns_one_structured_invalid_input_error(): ...
```

Use `tests/fixtures/campaign_precision_backend.py`; do not load the physical
backend.

- [ ] **Step 3: Observe parser red**

Run: `PYTHONPATH=src python -m unittest tests.test_linear_response_batches -v`

Expected: `--progress` is unrecognized and default normal stderr is absent.

- [ ] **Step 4: Add CLI session construction and exact argument forwarding**

Add `choices=tuple(mode.value for mode in ProgressMode)` and
`default=ProgressMode.NORMAL.value` to run/resume only. Construct the reporter
before backend loading, activate it across backend preparation and campaign
execution, close its status line before CLI error JSON, and leave the final
summary on stdout.

- [ ] **Step 5: Write failing durable-order and resume tests**

```python
def test_stage_and_leaf_completion_follow_successful_atomic_checkpoint_write(): ...
def test_failed_checkpoint_write_emits_no_false_completion(): ...
def test_interrupted_resume_appends_a_new_trace_session_without_recomputing(): ...
def test_complete_resume_reports_zero_work_without_loading_the_backend(): ...
```

The write-order observer must read and validate the replaced checkpoint inside
the completion callback. A forced `_atomic_json` failure must leave no
`checkpoint_written`, `stage_completed`, or `leaf_completed` event.

- [ ] **Step 6: Instrument campaign, precision, checkpoint, and leaf lifecycle**

In `run_campaign_selection`, scope each selected leaf with its exact scientific
identity. Emit stage start before `_execute_campaign_stage`, emit
`checkpoint_writing` before `_atomic_json`, and emit checkpoint/stage completion
only after it returns. Terminal leaf completion includes record/stage digests
and a compact scientific summary; reused terminal records never execute.

- [ ] **Step 7: Write failing PowerShell 5.1 surface tests**

```python
def test_m02_launcher_forwards_validated_progress_mode_to_run_or_resume_only(): ...
def test_launchers_decide_successful_stderr_writing_children_by_exit_code(): ...
```

- [ ] **Step 8: Implement PowerShell forwarding and native stderr guards**

Add:

```powershell
[ValidateSet("quiet", "normal", "trace")]
[string]$Progress = "normal"
```

to `m02.ps1`, forward `--progress $Progress` only to run/resume, and wrap the
final native invocations in both launchers with a local
`$ErrorActionPreference = "Continue"`, immediate exit-code capture, and
`finally` restoration. Do not merge streams with `2>&1`.

- [ ] **Step 9: Extend Windows CI parity with a successful stderr-progress case**

Use an authenticated synthetic one-leaf backend and compare direct module versus
`solver.ps1` for return code, canonical stdout, and nonempty progress stderr.
Do not invoke Julia or the native determinant.

- [ ] **Step 10: Run campaign/CLI/PowerShell green**

Run:

```text
PYTHONPATH=src python -m unittest tests.test_linear_response_batches tests.test_public_surface tests.test_cli -v
python .tasks/validate_board.py
```

- [ ] **Step 11: Commit lifecycle wiring**

```text
Expose campaign progress modes
```

### Task 3: Native Python Readout, Newton, Determinant, and ODE Events

**Files:**
- Modify: `src/windows_solver/response_engine.py`
- Modify: `src/windows_solver/native_response_kernel.py`
- Modify: `src/windows_solver/_native_sn_standard.py`
- Create: `tests/test_native_progress.py`
- Modify: `tests/test_linear_response_provider.py`

**Interfaces:**
- Consumes: Task 1 event bus and Task 2 leaf/stage scopes.
- Produces: amplitude-readout, four-phase, Newton, determinant-purpose, damping, angular, endpoint, ODE, and Wronskian events for binary64 execution.

- [ ] **Step 1: Write failing amplitude hierarchy tests with `AnalyticKernel`**

```python
def test_component_labels_baseline_then_each_signed_readout_without_reordering(): ...
def test_early_unresolved_component_closes_the_active_readout_without_false_success(): ...
```

Assert the existing successful order: baseline, then `real-plus`, `real-minus`,
`imaginary-plus`, `imaginary-minus` for each ε. Assert 17 readout completions for
the existing four-level analytic fixture.

- [ ] **Step 2: Implement a single readout wrapper in `run_component`**

The wrapper opens `progress_scope` with readout index, role, amplitude, and ε,
emits start, calls `backend.read_root` exactly once, and emits completion from
the returned `RootReadout`. Replace each direct call without changing ordering
or convergence branches.

- [ ] **Step 3: Write failing four-phase tests around the scripted kernel**

Extend the existing `ScriptedKernel` test to require exact phase order
`PRIMARY`, `TRUNCATION`, `RESOLUTION`, `SEED-PATH`, distinct policy summaries,
and phase completion values.

- [ ] **Step 4: Instrument the existing four `_solve_once` calls**

Use context scopes around the calls so subclasses keep the current
`_solve_once(*, sn, job, perturbation, policy, guess)` signature.

- [ ] **Step 5: Write failing fake-determinant Newton tests**

```python
def test_newton_events_label_initial_residual_derivatives_damping_and_final_derivative(): ...
def test_logging_adds_no_determinant_evaluations(): ...
def test_newton_reports_raw_and_clipped_step_without_changing_the_applied_step(): ...
```

For a hand-derived linear determinant, compare the callable's count to emitted
determinant completions and assert the exact existing call sequence. Include an
accepted damping candidate and a rejected-candidate fallback case.

- [ ] **Step 6: Add one labeled determinant evaluator inside `_solve_once`**

The evaluator increments root/leaf counters and emits start/complete around the
single existing call. `_bounded_newton` supplies purposes `initial best`,
`residual`, `derivative +h`, `derivative −h`, and `damping <value>`; the final
centered derivative uses `final derivative +h|−h`. Bind each candidate result
once before comparing it.

- [ ] **Step 7: Write failing trace sub-operation tests with fake SN/ODE results**

Exercise horizon and exterior determinant paths without SciPy work. Require
angular, endpoint, branch integration, support segment, and Wronskian
start/complete pairs; require actual fake `nfev` and saved-step counts.

- [ ] **Step 8: Instrument existing complete operations only**

Add trace-only boundaries around `lambda_phys`, endpoint seed construction,
`solve_ivp` calls, and Wronskian assembly. Never emit from an ODE RHS or radial
coefficient callback. Exterior segments use their actual boundary list and
index/count.

- [ ] **Step 9: Run native progress green plus existing scientific-control tests**

Run:

```text
PYTHONPATH=src python -m unittest tests.test_native_progress tests.test_linear_response_provider -v
```

These tests use analytic/scripted doubles only; do not run a physical kernel.

- [ ] **Step 10: Commit native instrumentation**

```text
Instrument native inner-leaf solves
```

### Task 4: Julia Side-Band Streaming and Promoted-Precision Events

**Files:**
- Modify: `src/windows_solver/julia_response_backend.py`
- Modify: `src/windows_solver/data/julia/m02_worker.jl`
- Modify: `tests/test_julia_response_backend.py`
- Create: `tests/test_julia_progress_transport.py`

**Interfaces:**
- Consumes: Task 1 external-event ingestion and current readout/phase context.
- Produces: `_run_streaming_worker(...) -> WorkerProcessResult`, reserved-prefix worker events, request digest plus invocation correlation, and unchanged strict response fields.

- [ ] **Step 1: Write failing streaming transport tests**

```python
def test_worker_runner_drains_stdout_and_stderr_concurrently_and_forwards_only_prefixed_events(): ...
def test_worker_progress_environment_does_not_change_request_digest_or_response_fields(): ...
def test_malformed_prefixed_event_fails_transport_without_masking_worker_stderr(): ...
def test_timeout_terminates_the_child_and_retains_bounded_diagnostics(): ...
```

Use a short Python child process or injected pipe process; never invoke Julia.

- [ ] **Step 2: Observe transport red**

Run: `PYTHONPATH=src python -m unittest tests.test_julia_progress_transport -v`

Expected: streaming runner and prefix parser are absent.

- [ ] **Step 3: Replace buffered `subprocess.run` with an injectable streaming runner**

Use `subprocess.Popen` with stdout/stderr pipes and two reader threads. Parse only
the reserved progress prefix from stdout, retain bounded non-progress stdout and
stderr, enforce the existing timeout, terminate/kill on timeout, join readers,
and return one immutable result object. Forward validated mappings through
`ingest_external_progress`.

- [ ] **Step 4: Preserve request and response authentication tests**

Update fake runners to the streaming signature. Assert the request digest is
still computed before adding `request_sha256`; assert progress mode and
invocation ID exist only in the child environment; retain the exact 13-field
successful response contract.

- [ ] **Step 5: Add Julia event helpers without executing them**

The worker reads process-local progress mode and invocation ID. Its helper emits
one-line reserved-prefix JSON to stdout and flushes. Scientific BigFloat values
are serialized as text. Unknown or quiet modes emit no events.

- [ ] **Step 6: Instrument existing Julia operations without extra work**

Emit request, four root phases, Newton iterations, determinant purposes,
damping decisions, and phase summaries. In trace mode add angular, contour
endpoint/Xin/Xup, real-radius ODE, and Wronskian boundaries. Bind existing
damping candidate determinants and retained ODE results before emitting; do not
add callbacks, manual stepping, or new evaluations.

- [ ] **Step 7: Run Python-side Julia adapter/transport green**

Run:

```text
PYTHONPATH=src python -m unittest tests.test_julia_response_backend tests.test_julia_progress_transport -v
```

Record explicitly that Julia source execution remains user-gated.

- [ ] **Step 8: Commit promoted-precision instrumentation**

```text
Stream Julia precision progress events
```

### Task 5: Operator Documentation, Integrated Verification, and PR Handoff

**Files:**
- Modify: `README.md`
- Modify: `docs/response-replay-powershell.md`
- Modify: `docs/superpowers/plans/2026-08-09-campaign-progress-instrumentation.md`
- Modify: `.tasks/IN_PROGRESS.md`
- Modify: `.tasks/WORK_LOG.md` only if TASK-075 itself reaches every acceptance criterion; otherwise leave it unchanged.

**Interfaces:**
- Consumes: Tasks 1–4.
- Produces: operator syntax/examples, fresh non-scientific proof, draft PR, and exact PowerShell acceptance handoff.

- [ ] **Step 1: Document the three modes and trace location**

Document:

```powershell
.\m02.ps1
.\m02.ps1 -Progress quiet
.\m02.ps1 -Progress trace
```

State that normal is default, stdout remains canonical JSON, trace sidecars are
diagnostic/non-evidence, and `campaign-plan` output remains a separate deferred
usability issue.

- [ ] **Step 2: Run focused and broad non-scientific verification**

Run:

```text
PYTHONPATH=src python -m unittest tests.test_progress tests.test_native_progress tests.test_julia_progress_transport tests.test_julia_response_backend tests.test_linear_response_provider tests.test_linear_response_batches tests.test_public_surface tests.test_cli -v
PYTHONPATH=src python -m unittest discover -s tests -v
python -m compileall -q src tests tools
python .tasks/validate_board.py
python tools/validate_release_manifest.py
git diff --check
```

Do not run `solver`, `m02.ps1`, Julia, or any mathematical integration.

- [ ] **Step 3: Inspect the requirement diff**

Confirm all progress writes are outside scientific mappings; request/response
field sets are unchanged; the native/Julia determinant-call sequences contain
no telemetry-only evaluation; bootstrap and GSN registry files are unchanged;
and every completion event follows atomic checkpoint replacement.

- [ ] **Step 4: Request independent whole-branch review**

Supply the approved design, this plan, full diff, verification output, execution
airgap, and the protected one-leaf baseline. Classify findings as blocker or
non-blocker and fix all blockers before publishing the final head.

- [ ] **Step 5: Publish a draft PR rooted at merged `main`**

The PR body must list the three modes, event hierarchy, stdout/stderr contract,
trace sidecars, Julia side-band transport, exact scientific exclusions,
developer verification, and pending PowerShell acceptance.

- [ ] **Step 6: Hand off executor commands**

Ask the user to run one leaf first with normal, then the same one leaf with
trace, returning the console transcript, one JSONL file, and resulting
checkpoint. Compare the checkpoint state, root, residual, Newton correction,
response, and GSN identity to the executor baseline before recommending a full
campaign.

- [ ] **Step 7: Commit documentation and handoff state**

```text
Document campaign progress operation
```
