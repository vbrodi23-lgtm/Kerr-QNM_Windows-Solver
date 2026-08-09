# M02 Inner-Leaf Progress Instrumentation Design

**Status:** Approved for implementation on 2026-08-09.

## Goal

Make every M02 campaign leaf observable from the interactive PowerShell console
without changing determinant mathematics, numerical controls, solver ordering,
authenticated request/response bytes, campaign checkpoints, or scientific
evidence objects.

The operator must be able to distinguish a healthy expensive solve from a
stalled or repeating solve while it is still inside a leaf.

## Executor baseline protected by this change

The first clean one-leaf M02 execution completed through the declared production
path:

`GSN request → exact F/U generation → accepted indexed artifact → assembled selection cache → native solve → converged checkpoint`

The returned checkpoint reported `state: COMPLETE`, `computed: true`,
`numerical_state: CONVERGED`, and `usable: true`. Its baseline root was
approximately `0.7463199987 − 0.0531490080i`, determinant residual approximately
`1.42e−11`, Newton correction estimate approximately `1.82e−12`, and response
approximately `−0.0117695630 − 0.1158019721i`.

These values are executor-reported acceptance evidence. They are not copied into
a fixture or promoted into a new authenticated artifact by this PR. The user will
rerun the same path after implementation and compare the resulting scientific
checkpoint.

## Progress levels

`campaign-run` and `campaign-resume` accept:

- `--progress quiet`: leaf start, durable leaf finish, final status, and errors.
- `--progress normal`: the default. Adds leaf scientific identity, precision
  stage, amplitude readout, root phase, Newton state, current determinant
  purpose/count, current ω, residual, best residual, and elapsed time.
- `--progress trace`: adds every determinant evaluation, candidate point and
  result, damping decision, angular/endpoint/integration/Wronskian transition,
  operation timing, and a flushed per-leaf JSONL trace.

`m02.ps1` exposes the same three values and defaults to `normal`.

## Scientific hierarchy

Every event is correlated through this hierarchy:

`campaign session → leaf → precision stage → component pass → amplitude readout → root phase → Newton iteration → determinant evaluation → sub-operation`

A normal component uses one baseline readout and four signed readouts for each
accepted amplitude level. It therefore executes 17–25 readouts, not one. Each
readout runs `PRIMARY`, `TRUNCATION`, `RESOLUTION`, and `SEED-PATH`. The progress
labels must make repeated phases unambiguous.

## Event contract

Progress is a typed, out-of-band event stream. A common event contains:

- schema version, event kind, session ID, monotonically increasing sequence,
  UTC timestamp, and elapsed seconds;
- leaf index/count, leaf ID, role, mode, spin, exact sampling coordinate,
  mechanism, and bound background ω;
- precision digits and component pass (`primary` or `self-refinement`);
- amplitude-readout index, role, ε where applicable, and complex amplitude;
- root phase, Newton index/limit, determinant index within the phase and leaf,
  and determinant purpose;
- event-specific finite scientific values and durations.

Complex values are represented as `{real, imaginary}`. Non-finite intermediate
values are rendered as explicit strings in progress only; canonical scientific
JSON continues to reject non-finite values under its existing rules.

Progress counters, timestamps, and events never enter request hashes, response
hashes, checkpoint digests, evidence payloads, release admission, or scientific
result mappings.

## Output contracts

The CLI retains exactly one canonical JSON object on stdout. Human progress is
written only to stderr. Structured CLI failures remain the terminal stderr JSON
object after the progress renderer closes any in-place status line.

Normal mode renders determinant activity as an in-place status line where the
stream supports it, then emits durable phase and leaf summaries as ordinary
lines. This supplies the current determinant purpose without turning every
full-campaign run into a permanent determinant transcript.

Trace mode emits exhaustive human-readable lines and writes:

`<checkpoint>.progress/leaf-NNNNNN.jsonl`

Each JSONL line is flushed after writing. A resumed leaf appends a new
`session_started` marker with a new session ID; prior trace bytes are retained.
Trace files are diagnostic sidecars and are not admitted scientific evidence.

## Campaign and checkpoint lifecycle

Leaf identity is printed once before any stage work. Reused terminal leaves are
reported without re-execution. Precision-stage start and finish events surround
the existing 64/80/120-digit dispatch.

A stage or leaf is described as checkpointed only after the existing atomic
checkpoint replacement succeeds. `checkpoint_writing` may precede the write;
`checkpoint_written`, `stage_completed`, and terminal `leaf_completed` must
follow it.

If execution fails inside a leaf, progress emits the current hierarchy and error
without constructing a false leaf-completion event. The existing exception and
checkpoint recovery behavior remains authoritative.

## Native Python instrumentation

`run_component` labels the baseline and every signed-amplitude readout without
changing their order or early-return rules.

The native kernel labels the four existing root phases. Newton instrumentation
reuses every existing determinant value. It records:

- current and best ω/residual;
- centered derivative points and derivative magnitude;
- raw step, applied step, and whether the existing `6e−3` cap clipped it;
- each existing damping trial and its accepted/rejected decision;
- final centered derivative evaluations;
- iterations, determinant evaluations, and elapsed time.

No determinant call may be added for telemetry.

Trace sub-operations surround existing angular solves, endpoint construction,
complete ODE integrations, support-boundary segments, and Wronskian assembly.
ODE right-hand-side calls are never logged. Adaptive integrations report actual
solver segments, saved-step/RHS counts where already exposed, and configured
support resolution. They do not fabricate a fixed `subinterval i/N` model.

## Julia promoted-precision instrumentation

The package-owned Julia worker emits reserved-prefix JSON events through its
captured stdout. Julia warnings and errors remain on stderr. Python drains both
pipes concurrently, parses only the reserved prefix, forwards typed events to
the common reporter, and preserves bounded stdout/stderr diagnostics on failure.

The existing request document and response document are unchanged. Events carry
the existing `request_sha256` for content correlation and a Python-generated
ephemeral invocation ID for repeated identical requests. Progress mode and the
invocation ID travel through process-local environment variables, outside the
authenticated request.

Julia emits the same four root phases, Newton/determinant purposes, damping
decisions, and trace-only angular/endpoint/ODE/Wronskian boundaries. It reuses
computed candidate determinants and ODE results. It does not add callbacks,
manual stepping, evaluations, or altered integrator controls.

## PowerShell 5.1 behavior

`solver.ps1` and `m02.ps1` temporarily use non-terminating native-command error
handling around the Python child and decide success strictly from the captured
exit code. This permits valid stderr progress under Windows PowerShell 5.1 while
preserving nonzero failure propagation and distinct stdout/stderr streams.

## Testing and execution airgap

Developer verification uses synthetic campaign backends, fake determinants,
fake ODE results, fake Julia process streams, event ordering, stdout/stderr
contract checks, JSONL append/flush checks, checkpoint-write failure checks, and
PowerShell surface/parity tests.

The developer does not execute Julia, the GSN producer, the worker, a physical
determinant, or a Kerr solve. The user runs the PowerShell acceptance path and
returns logs. Julia syntax and live streaming remain explicitly executor-gated.

## Out of scope

- determinant equations, root tolerances, iteration limits, damping schedule,
  amplitude ladder, angular resolution, ODE tolerances, endpoint order, or
  branch criteria;
- GSN pair production, registry identity, coefficient artifacts, and selection
  cache architecture;
- checkpoint/evidence schemas, hashes, reduction, admission, or release claims;
- the separate `campaign-plan` 4.9 MB interactive-output usability change;
- manuscript and literature files supplied outside the repository.
