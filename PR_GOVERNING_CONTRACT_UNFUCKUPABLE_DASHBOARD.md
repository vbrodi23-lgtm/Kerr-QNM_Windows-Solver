# PR GOVERNING CONTRACT — UN-FUCKUPABLE APPEND-ONLY M02 OPERATOR DASHBOARD

## STATUS

This is a binding implementation contract for one standalone pull request.

It governs the M02 human dashboard only.

It is not permission to change:

```text
Kerr mathematics
numerical policy
response construction
root science
pass scheduling
promotion routing
evidence admission
checkpoint semantics
Julia requests
solver tolerances
```

The development agent may:

```text
inspect code
edit code
run Python unit tests
run Windows PowerShell parser tests
run compile/static checks
run deterministic mocked orchestration
push reviewable commits
```

The development agent must not:

```text
run m02.ps1
run a production campaign
launch a Julia worker
execute native Kerr or GSN numerical work
change scientific output to satisfy dashboard presentation
```

The operator performs PowerShell execution and scientific canaries.

---

# 1. CONTROLLING BASELINE

Implement from current merged `main`.

Controlling main head at contract regeneration:

```text
b5c6115f9a5da827492e37dad6eae971d7d815c5
```

Relevant current owners:

```text
src/windows_solver/progress_output.py
src/windows_solver/progress.py
src/windows_solver/cli.py
m02.ps1
tests/test_clean_tail_dashboard.py
```

The current source contains the right schema-11 event vocabulary, including:

```text
CAMPAIGN_PASS_STARTED
CAMPAIGN_PASS_COMPLETED
CAMPAIGN_PASS_INTERRUPTED
LEAF_PASS_STARTED
LEAF_PASS_DISPOSITION_RECORDED
PROMOTION_QUEUED
SYSTEM_FAILURE_RECORDED
CHECKPOINT_WRITTEN
```

The current human renderer still has two architectural defects.

First, the canonical dashboard projection constructs settled rows by iterating numerical records. A leaf with a durable binary64 pass disposition and a retained provisional stage, but no terminal numerical record, therefore disappears from the table.

Second, the human renderer uses a carriage-return live line. Repeated repainting causes visible flicker and is explicitly rejected by the operator.

The controlling binary64 result proves why the old model is wrong:

```text
selected leaves                    212
binary64 pass-ledger entries       212
pending RESPONSE promotions        212
final numerical records              0
SCREENED evidence entries            0
system failures                      0
```

That is a completed binary64 survey with 212 settled leaf tasks.

It is not `DONE 0`.

---

# 2. OPERATOR APPROVAL AND GOVERNING VISUAL FIXTURE

The operator approved the following layout.

Do not redesign it.

Do not simplify it.

Do not rename its fields.

Do not substitute another table.

Do not move the scientific counts into a different display.

The governing mid-run visual fixture is:

```text
======================================================================================================================
  M02 | OPERATOR DASHBOARD
======================================================================================================================
  PROFILE  SURVEY    PASS  BINARY64      CHECKPOINT  schema-11    LAYER-1 LOCK  NOT YET CREATED
----------------------------------------------------------------------------------------------------------------------
  BINARY64 PROCESSED    15/212     PRODUCED     0     PENDING    15     SYS FAIL     0
  PROMOTION ROUTES        BF40  12     BF80   3     RETAINED BINARY64 SAMPLES   63
  PROMOTED PROCESSED      0         DEFERRED   0     UNRESOLVED   0     REJECTED   0
  EVIDENCE             SCREENED   0     CERTIFIED   0     VALIDATED   0
----------------------------------------------------------------------------------------------------------------------
  RUNNING  |  16/212  |  220  |  a=0.9999  |  horizon  |  binary64  |  primary  |  Xup  |  227.2s
----------------------------------------------------------------------------------------------------------------------
  LAST SETTLED LEAVES

  LEAF      MODE  SPIN       MECHANISM        ROLE         TIME SAMPLES NEXT   STATE
  --------- ----- ---------- ---------------- -------- -------- ------- ------ ------------------
  2/212     220   0.95       ext-r3           primary     21.5s       9 BF40   QUEUED->BF40
  3/212     220   0.95       ext-alpha1/2     primary     12.3s       4 BF40   QUEUED->BF40
  4/212     220   0.95       ext-lightring    primary     12.1s       4 BF40   QUEUED->BF40
  5/212     220   0.95       ext-throatk      primary     11.3s       4 BF40   QUEUED->BF40
  6/212     220   0.99       horizon          primary     10.2s       0 BF80   QUEUED->BF80
  7/212     220   0.99       ext-r3           primary     19.6s       9 BF40   QUEUED->BF40
  8/212     220   0.99       ext-alpha1/2     primary     11.6s       4 BF40   QUEUED->BF40
  9/212     220   0.99       ext-lightring    primary     12.8s       4 BF40   QUEUED->BF40
  10/212    220   0.99       ext-throatk      primary     12.4s       4 BF40   QUEUED->BF40
  11/212    220   0.999      horizon          primary     11.5s       0 BF80   QUEUED->BF80
  12/212    220   0.999      ext-r3           primary     21.5s       9 BF40   QUEUED->BF40
  13/212    220   0.999      ext-alpha1/2     primary     11.5s       4 BF40   QUEUED->BF40
  14/212    220   0.999      ext-lightring    primary     11.9s       4 BF40   QUEUED->BF40
  15/212    220   0.999      ext-throatk      primary     15.3s       4 BF40   QUEUED->BF40
```

The table remains open while the pass is running.

The terminal-only footer and final summary are appended after the last settled row. This is the only logically valid placement under strict append-only rendering: printing a footer earlier would force later rows outside the table or require cursor movement.

---

# 3. ABSOLUTE APPEND-ONLY LAW

The schema-11 M02 human dashboard must obey this exact output state machine:

```text
OPEN
    print the dashboard frame once
    print one initial checkpoint snapshot once
    print at most the latest 14 already-settled rows once
    mark every already-settled leaf as known, including omitted older rows

RUNNING
    print nothing for heartbeats
    print nothing for ODE progress
    print nothing for determinant progress
    print nothing for suboperation progress
    print nothing for elapsed-time updates
    print nothing for a newly started leaf

SETTLED LEAF
    after one leaf disposition is durably committed
    append exactly one complete row
    never alter that row again

TERMINAL
    append any final committed leaf rows not yet printed
    append exactly one terminal summary
    append exactly one footer
    close
```

The dashboard must never:

```text
Clear-Host after opening
clear the terminal
clear a line
move the cursor
use carriage return to overwrite text
use ANSI cursor-control sequences
rewrite a count line
rewrite the RUNNING strip
redraw the table
reprint the header
reprint settled rows
animate
flicker
```

Prohibited output bytes or operations after opening include:

```text
\r used as an overwrite control
ESC [ 2 J
ESC [ H
ESC [ K
ESC [ n A
ESC [ n B
Clear-Host
Console.SetCursorPosition
```

Ordinary newline output is permitted.

One newly committed leaf task must produce one newly appended row and no other routine human output.

---

# 4. THE REFERENCE SCRIPT IS NORMATIVE

The complete PowerShell script in Appendix A is a governing acceptance oracle.

Its SHA-256 is:

```text
f36dcf3b8269cac037b3d51ed2388aecb9d4e94fef1b99863a21082bf4c5a54a
```

A standalone copy must be retained in this PR at a useful executable path, preferably:

```text
tools/M02_Operator_Dashboard_Append_Only_Reference.ps1
```

The implementation does not have to copy the script's polling architecture.

The production implementation must not use CSV reports as scientific state and must not poll when typed in-process state is available.

The production implementation must nevertheless match the reference script in:

```text
layout
labels
field order
column order
spacing intent
mechanism short names
spin precision
state names
initial last-14 behaviour
one-row append behaviour
terminal summary
lack of flicker
interactive-paste safety of the manual reference
```

The reference script is deliberately enclosed by:

```powershell
& {
    ...
}
```

This is mandatory for direct interactive paste. It prevents Windows PowerShell 5.1 from executing a completed top-level `if` block before the following `elseif` or `else` has arrived.

The previous broken manual script failed because `elseif` and `else` were submitted as separate interactive commands.

That failure must have a regression test.

---

# 5. PRODUCTION ARCHITECTURE

## 5.1 One canonical projection owner

Add one pure, side-effect-free owner, preferably:

```text
src/windows_solver/schema11_dashboard.py
```

Recommended public shape:

```python
@dataclass(frozen=True, slots=True)
class Schema11DashboardRow:
    ...

@dataclass(frozen=True, slots=True)
class Schema11DashboardSnapshot:
    ...

def project_schema11_dashboard(
    checkpoint: Mapping[str, object],
    *,
    selected_leaf_ids: Sequence[str],
    leaf_metadata: Mapping[str, Mapping[str, object]],
    active_pass: str,
) -> Schema11DashboardSnapshot:
    ...
```

The names may differ.

The ownership rule may not differ:

> Every human header, settled row, status receipt, terminal summary, startup summary, and test fixture consumes the same canonical projection.

No renderer may independently count records, queues, dispositions, or evidence.

## 5.2 Dashboard rows are pass-disposition rows

For the binary64 pass, one settled row exists for every selected leaf ID present in:

```text
checkpoint["survey_pass_ledger"]["binary64"]
```

A numerical record is not required.

For the promoted pass, one settled row exists for every applicable selected leaf ID present in:

```text
checkpoint["survey_pass_ledger"]["promoted"]
```

The current implementation's record-owned row loop must be removed from schema-11 dashboard projection.

Numerical records remain the source for response magnitude and response uncertainty only when those values exist.

## 5.3 Durable state versus live state

Durable values come only from the latest successfully parsed and validated committed checkpoint:

```text
processed count
produced count
pending promotions
BF40 route count
BF80 route count
retained binary64 sample count
promoted processed count
deferred count
unresolved count
rejected count
system failures
evidence counts
settled rows
```

Typed progress events may provide the initial RUNNING snapshot:

```text
active leaf
mode
spin
mechanism
tier
role
suboperation or phase
elapsed time
```

After the frame opens, live events continue to update status JSON and diagnostics but produce no routine human terminal output.

Events must never increment human durable counters in memory.

Forbidden:

```python
processed += 1
queued += 1
completed += 1
```

inside the renderer.

---

# 6. CANONICAL COUNT DEFINITIONS

For selected leaf set `S`, binary64 pass ledger `B`, promoted pass ledger `P`, promotion queue `Q`, numerical records `R`, evidence ledger `E`, and system-failure ledger `F`:

```text
selected
    = |S|

binary64_processed
    = number of selected leaf IDs present in B

promoted_processed
    = number of applicable selected leaf IDs present in P

produced
    = number of selected numerical records with state PRODUCED

pending
    = number of selected queue entries with disposition PENDING

pending_BF40
    = pending entries with minimum_requested_tier BF40

pending_BF80
    = pending entries with minimum_requested_tier BF80

retained_binary64_samples
    = sum of binary64 pass-ledger sample_count over selected leaves

deferred
    = active-pass dispositions equal to DEFERRED

unresolved
    = active-pass dispositions equal to UNRESOLVED

rejected
    = active-pass dispositions equal to REJECTED

system_failures
    = |F|

SCREENED / CERTIFIED / VALIDATED
    = exact evidence-ledger counts by evidence_level
```

Do not use `DONE` as a synonym for both processed and produced.

The required labels are:

```text
BINARY64 PROCESSED
PRODUCED
PENDING
SYS FAIL
PROMOTION ROUTES
RETAINED BINARY64 SAMPLES
PROMOTED PROCESSED
DEFERRED
UNRESOLVED
REJECTED
SCREENED
CERTIFIED
VALIDATED
```

---

# 7. OPENING AND RESUME SEMANTICS

## 7.1 Do not render in the reporter constructor

Constructing `Schema11ProgressReporter` must not immediately print a frame before an active pass or terminal state is known.

Open the frame on the first of:

```text
LEAF_PASS_STARTED
CAMPAIGN_PASS_COMPLETED
CAMPAIGN_PASS_INTERRUPTED
SYSTEM_FAILURE_RECORDED
```

A cold binary64 start therefore opens with leaf 1 as the initial RUNNING snapshot.

A resumed pass opens with the current active leaf and current committed counts.

A terminal checkpoint opens directly in terminal form.

## 7.2 Initial settled rows

On opening:

```text
project the latest committed checkpoint
sort settled rows by stable selection ordinal
print at most the final 14 rows
mark all existing settled leaf IDs as already printed
```

Older rows omitted from the initial last-14 window must not be appended later.

## 7.3 Static opening summary

The top summary and RUNNING strip are an opening snapshot.

They are intentionally not repainted.

The growing table is the progress display.

The final terminal summary contains authoritative end-of-pass totals.

---

# 8. SETTLED-ROW COMMIT ORDER

A leaf row may be appended only after its pass disposition is durable.

Required order:

```text
build candidate checkpoint
validate candidate checkpoint
atomically write checkpoint
complete checkpoint callback
emit LEAF_PASS_DISPOSITION_RECORDED
project committed checkpoint
append newly discovered settled row
```

If an event arrives before the corresponding committed ledger entry is readable:

```text
print nothing
retain no fake row
retry on CHECKPOINT_WRITTEN or the next safe projection trigger
```

Before terminal summary:

```text
reload committed checkpoint
append every final settled row not yet printed
then append terminal summary
```

The last leaf must never disappear because the terminal event arrived immediately after commit.

## 8.1 Exactly-once identity

The renderer maintains a presentation-only set:

```text
printed_leaf_ids
```

This set is not scientific state.

It prevents duplicate human rows.

The identity key is the full leaf ID, not ordinal, mode, or mechanism.

## 8.2 Row state

For a binary64 pass entry with one pending promotion:

```text
minimum_requested_tier BF40
    → QUEUED->BF40

minimum_requested_tier BF80
    → QUEUED->BF80
```

Other allowed states:

```text
PRODUCED
CACHE_REUSED
DEFERRED
UNRESOLVED
REJECTED
SYSTEM_FAILURE
```

Do not invent response magnitude or relative error for a provisional queued row.

---

# 9. HUMAN ROW CONTRACT

Required columns and order:

```text
LEAF
MODE
SPIN
MECHANISM
ROLE
TIME
SAMPLES
NEXT
STATE
```

Required formatting:

```text
LEAF
    stable selection ordinal, for example 16/212

MODE
    compact mode label, for example 220

SPIN
    enough significant digits to distinguish the physical coordinate
    never truncate 0.9999 to 0.99~

MECHANISM
    approved human short name

ROLE
    primary, control, or deep

TIME
    committed pass timing

SAMPLES
    committed pass sample_count

NEXT
    BF40, BF80, or -

STATE
    full untruncated state
```

Approved mechanism short names:

```text
horizon-admittance      → horizon
exterior-fixed-r3       → ext-r3
exterior-alpha-zero     → ext-alpha0
exterior-alpha-half     → ext-alpha1/2
exterior-alpha-one      → ext-alpha1
exterior-light-ring     → ext-lightring
exterior-throat-kappa   → ext-throatk
```

Do not dump mappings, dictionaries, SHA prefixes, or Python representations into the human row.

---

# 10. TERMINAL SUMMARY

## 10.1 Completed binary64 pass

Append exactly once:

```text
----------------------------------------------------------------------------------------------------------------------
  BINARY64 SURVEY COMPLETE

  PROCESSED                  212/212
  PENDING PROMOTIONS         212
    EXTERIOR -> BF40         172
    HORIZON  -> BF80          40
  RETAINED BINARY64 SAMPLES  928
  SYSTEM FAILURES              0

  NEXT PASS: SURVEY / PROMOTED
----------------------------------------------------------------------------------------------------------------------
  Ctrl+C stops this preview. The solver in the other window is untouched.
======================================================================================================================
```

Production wording may replace the preview-only Ctrl+C sentence with an operator-appropriate completion sentence.

The scientific totals may not differ from the canonical projection.

## 10.2 Interrupted pass

Append exactly once:

```text
PASS INTERRUPTED
processed / selected
last durable leaf
active leaf at interruption
checkpoint path
resume command
```

## 10.3 System failure

Append exactly once:

```text
SYSTEM FAILURE
leaf ordinal and full leaf ID
failure code
checkpoint preservation status
diagnostic directory
postmortem path
```

A renderer failure must not masquerade as a scientific system failure.

---

# 11. STREAM SEPARATION

Human dashboard output and canonical CLI JSON must not share one stream.

Required contract:

```text
stdout
    canonical CLI JSON only

stderr or explicit human stream
    dashboard only
```

`m02.ps1` must capture and parse command JSON rather than dumping it below the dashboard.

Required PowerShell shape:

```powershell
$RunResult = Invoke-M02Command -Arguments $RunArguments |
    ConvertFrom-Json
```

Then print only the governed human terminal result.

Do not remove `_emit()` or break direct CLI callers.

---

# 12. STATUS RECEIPT

Human output is append-only.

Status JSON remains live and current.

Version the status schema if fields change, preferably:

```text
windows-solver.schema11-progress-status/3
```

Required fields:

```text
selected_leaf_count
binary64_processed_count
promoted_processed_count
produced_count
pending_count
pending_by_minimum_tier
retained_binary64_sample_count
deferred_count
unresolved_count
rejected_count
system_failure_count
evidence_counts
settled_leaf_ids
printed_leaf_ids or presentation state if persisted
active_leaf
last_committed_leaf
next_intended_leaf
terminal_event
terminal_failure
report_status
checkpoint_path
updated_at_utc
```

A legacy field named `completed_leaf_ids` may remain only if its meaning is explicitly numerical records.

It must not drive a human label called `DONE`.

---

# 13. ERROR HANDLING

Dashboard failure must never alter scientific state.

Dashboard failure must not be silent.

Required behaviour:

```text
preserve solver execution
record one renderer diagnostic
write status JSON if possible
print one concise DASHBOARD DEGRADED message
stop human rendering rather than fabricate counts
```

The renderer must not repeatedly print the same degraded message.

A transient checkpoint replacement race must be retried silently.

A persistent checkpoint validation failure must be named.

---

# 14. IMPLEMENTATION BOUNDARIES

Recommended production units:

```text
schema11_dashboard.py
    pure projection and row construction

progress_output.py
    append-only rendering and presentation state

progress.py
    typed events only

cli.py
    stream wiring and reporter lifecycle

m02.ps1
    machine JSON capture and operator summary
```

Do not place scientific decisions in `progress_output.py`.

Do not make the dashboard depend on report CSVs.

Do not make the solver depend on the standalone preview script.

The preview script is a visual oracle and operator tool, not a scientific dependency.

---

# 15. TEST-FIRST IMPLEMENTATION ORDER

## Commit A — freeze the visual oracle

Add:

```text
tools/M02_Operator_Dashboard_Append_Only_Reference.ps1
```

Add parser and static invariants before changing production code.

## Commit B — reproduce the real projection defect

Build a fixture with:

```text
selected leaves                 212
binary64 pass entries          212
records                          0
pending promotions             212
minimum tier BF40              172
minimum tier BF80               40
system failures                  0
```

Expected:

```text
binary64_processed == 212
produced == 0
pending == 212
pending_BF40 == 172
pending_BF80 == 40
settled binary64 rows == 212
```

## Commit C — central projection

Move all durable state derivation to one owner.

## Commit D — append-only renderer

Remove schema-11 carriage-return rendering and wire exactly-once rows.

## Commit E — stream and PowerShell wiring

Keep machine JSON parseable and human output clean.

---

# 16. MANDATORY TEST MATRIX

## 16.1 Reference-script tests

On Windows PowerShell 5.1:

```text
test_reference_script_parses_without_errors
test_reference_script_first_noncomment_token_is_ampersand_scriptblock
test_reference_script_interactive_paste_does_not_split_else_or_elseif
test_reference_script_contains_exactly_one_clear_host
test_reference_script_contains_no_cursor_movement_api
test_reference_script_contains_no_ansi_clear_sequence
test_reference_script_sha256_matches_contract
test_reference_script_visual_fixture_matches_approved_layout
```

Use the PowerShell parser:

```powershell
$Tokens = $null
$Errors = $null
[System.Management.Automation.Language.Parser]::ParseFile(
    $Path,
    [ref]$Tokens,
    [ref]$Errors
) | Out-Null

if ($Errors.Count -ne 0) {
    throw ($Errors | Out-String)
}
```

## 16.2 Projection tests

```text
test_binary64_212_dispositions_zero_records_projects_212_rows
test_binary64_pending_routes_partition_172_bf40_and_40_bf80
test_produced_is_not_processed
test_retained_samples_sum_from_pass_ledger
test_promoted_rows_use_promoted_ledger
test_report_failure_does_not_change_scientific_counts
test_system_failure_count_comes_only_from_failure_ledger
test_projection_is_deterministic
test_projection_rejects_off_selection_entries
```

## 16.3 Append-only output tests

```text
test_frame_prints_once
test_initial_snapshot_prints_last_14_rows
test_initial_snapshot_marks_all_existing_rows_known
test_heartbeat_prints_nothing
test_ode_progress_prints_nothing
test_suboperation_progress_prints_nothing
test_leaf_pass_started_prints_nothing_after_open
test_one_new_committed_leaf_appends_exactly_one_line
test_duplicate_disposition_event_appends_nothing
test_two_leaves_completed_between_events_append_in_ordinal_order
test_precommit_event_prints_nothing
test_checkpoint_written_retries_missing_row
test_terminal_event_flushes_final_leaf_before_summary
test_terminal_summary_prints_once
test_no_output_contains_carriage_return_overwrite
test_no_output_contains_ansi_cursor_control
test_no_output_calls_clear_after_open
test_no_header_reprint
test_no_settled_row_rewrite
```

A strong byte-level assertion is required:

```text
output_before_new_leaf
    is an exact prefix of
output_after_new_leaf
```

The only added bytes for a normal leaf completion must be:

```text
one complete row
one newline
```

## 16.4 Resume tests

```text
test_resume_prints_latest_14_settled_rows_once
test_resume_does_not_reappend_older_omitted_rows
test_resume_appends_next_new_leaf_once
test_resume_preserves_selection_ordinals
test_resume_uses_checkpoint_not_stale_status_counts
```

## 16.5 Stream tests

```text
test_schema11_cli_stdout_is_one_parseable_json_document
test_dashboard_uses_human_stream
test_m02_does_not_print_raw_command_json
test_quiet_mode_writes_status_without_human_output
```

## 16.6 Content tests

```text
test_approved_header_is_exact
test_approved_column_order_is_exact
test_spin_is_never_truncated
test_mechanism_is_never_mutilated
test_state_is_never_truncated
test_live_mapping_values_are_never_dumped
test_binary64_queued_row_has_no_fake_response
test_terminal_summary_contains_processed_produced_and_pending_semantics
```

## 16.7 Static ownership guards

Fail CI if schema-11 production code contains:

```text
Clear-Host
SetCursorPosition
carriage-return live rewriting
ANSI screen clearing
independent queue counting outside projection owner
in-memory durable count increments
record-only ownership of settled rows
raw CLI JSON streamed into the human PowerShell dashboard
```

Legacy non-schema-11 progress code may remain only if its ownership and call paths are isolated and tests prove M02 schema-11 cannot reach it.

---

# 17. FORBIDDEN FIXES

Do not fix this by:

```text
changing the approved layout
replacing the table with a progress bar
using a periodically refreshed TUI
using curses
using ANSI cursor movement
using carriage returns
clearing and redrawing
printing a RUNNING line for every heartbeat
printing a second summary after each leaf
counting progress events
using CSV reports as scientific truth
hard-coding 212, 172, 40, or 928 in production
creating fake numerical records
marking provisional work SCREENED
renaming DONE while retaining the wrong count
swallowing projection errors
breaking canonical CLI JSON
launching Julia
running M02
```

The official M02 regression may assert the known 212/172/40/928 fixture.

The production algorithm must derive all values.

---

# 18. PERMITTED VERIFICATION

Permitted:

```text
Windows PowerShell parser tests
Python unit tests
full Python suite
compileall
static AST/source guards
mocked schema-11 events
mocked checkpoint commits
hosted CI
```

Forbidden:

```text
m02.ps1
production binary64 survey
production promoted survey
Julia worker
native Kerr determinant evaluation
scientific canary
```

---

# 19. PR BOUNDARY

Recommended PR title:

```text
fix(dashboard): make M02 operator output append-only and ledger-driven
```

This PR must not include:

```text
Layer-1 locking
BF40/BF80 numerical promotion changes
Kerr mathematics
response uncertainty changes
root lifecycle changes
```

Required completion report:

```text
base SHA
head SHA
changed files
reference-script SHA-256
PowerShell parser result
targeted test names and counts
full-suite result
static-guard result
CI status
statement that no Julia or production solver was executed
```

Finish the implementation response with:

> Code written. Awaiting your PowerShell execution logs.

---

# APPENDIX A — COMPLETE NORMATIVE POWERSHELL REFERENCE SCRIPT

The following script must be retained verbatim unless the operator explicitly approves a visual or behavioural change.

```powershell
& {

# ============================================================================
# M02 OPERATOR DASHBOARD — APPEND-ONLY / INTERACTIVE-PASTE SAFE
#
# Visual layout: the operator-approved M02 dashboard.
#
# Behaviour:
#   - the entire paste parses before execution
#   - Clear-Host executes ONCE to remove PowerShell paste prompts
#   - dashboard header prints ONCE
#   - latest settled rows print ONCE
#   - while a leaf runs: NOTHING repaints or flickers
#   - each newly settled B64 leaf appends ONE row
#   - pass completion appends ONE final summary
#
# READ ONLY.
# Ctrl+C stops this dashboard only.
# ============================================================================

$Repo = "$HOME\Downloads\Kerr-QNM_Windows-Solver-main\Kerr-QNM_Windows-Solver-main"

$Checkpoint = Join-Path $Repo "m02-output\m02-campaign-checkpoint.json"
$StatusPath = "$Checkpoint.status.json"
$LeavesCsv = Join-Path $Repo "m02-output\m02-campaign-checkpoint.reports\m02-leaves.csv"
$LockPath = "$Checkpoint.binary64-lock.json"

$PollMilliseconds = 250
$InitialRowsToShow = 14

$Host.UI.RawUI.WindowTitle = "M02 — Operator Dashboard"


function Read-JsonSafe {
    param([string]$Path)

    for ($i = 0; $i -lt 5; $i++) {
        try {
            if (Test-Path -LiteralPath $Path -PathType Leaf) {
                $Raw = Get-Content -LiteralPath $Path -Raw -ErrorAction Stop

                if (-not [string]::IsNullOrWhiteSpace($Raw)) {
                    return ($Raw | ConvertFrom-Json -ErrorAction Stop)
                }
            }
        }
        catch {}

        Start-Sleep -Milliseconds 30
    }

    return $null
}


function Get-MapEntries {
    param($Object)

    if ($null -eq $Object) {
        return @()
    }

    return @(
        $Object.PSObject.Properties | ForEach-Object {
            [pscustomobject]@{
                Key   = $_.Name
                Value = $_.Value
            }
        }
    )
}


function Short-Mechanism {
    param([string]$Mechanism)

    switch ($Mechanism) {
        "horizon-admittance"     { return "horizon" }
        "exterior-fixed-r3"      { return "ext-r3" }
        "exterior-alpha-zero"    { return "ext-alpha0" }
        "exterior-alpha-half"    { return "ext-alpha1/2" }
        "exterior-alpha-one"     { return "ext-alpha1" }
        "exterior-light-ring"    { return "ext-lightring" }
        "exterior-throat-kappa"  { return "ext-throatk" }

        default {
            if ([string]::IsNullOrWhiteSpace($Mechanism)) {
                return "-"
            }

            return $Mechanism
        }
    }
}


function Format-Spin {
    param($Value)

    try {
        return ("{0:G8}" -f [double]$Value)
    }
    catch {
        return "-"
    }
}


function Format-Time {
    param($Seconds)

    if ($null -eq $Seconds) {
        return "-"
    }

    try {
        $N = [double]$Seconds

        if ($N -lt 10) {
            return ("{0:0.00}s" -f $N)
        }

        if ($N -lt 1000) {
            return ("{0:0.0}s" -f $N)
        }

        return ("{0:0}s" -f $N)
    }
    catch {
        return "-"
    }
}


function Sum-TierTime {
    param($PassEntry)

    $Total = 0.0
    $Found = $false

    foreach ($Tier in @($PassEntry.tier_timing)) {
        if ($null -ne $Tier -and $null -ne $Tier.elapsed_seconds) {
            try {
                $Total += [double]$Tier.elapsed_seconds
                $Found = $true
            }
            catch {}
        }
    }

    if ($Found) {
        return $Total
    }

    return $null
}


function Get-EvidenceCount {
    param(
        $Ledger,
        [string]$Level
    )

    $Count = 0

    foreach ($Entry in @(Get-MapEntries $Ledger)) {
        if ($Entry.Value.evidence_level -eq $Level) {
            $Count++
        }
    }

    return $Count
}


function Write-Line {
    param(
        [string]$Text = "",
        [ConsoleColor]$Color = [ConsoleColor]::Gray
    )

    Write-Host $Text -ForegroundColor $Color
}


function Rule {
    param([string]$Character = "=")

    return ($Character * 118)
}


function Get-QueueByLeaf {
    param($CheckpointData)

    $Result = @{}

    foreach ($Entry in @($CheckpointData.promotion_queue.entries)) {
        $Result[[string]$Entry.leaf_id] = $Entry
    }

    return $Result
}


# ============================================================================
# STATIC HUMAN METADATA
# ============================================================================

$Metadata = @{}

if (Test-Path -LiteralPath $LeavesCsv -PathType Leaf) {
    try {
        foreach ($Row in @(Import-Csv -LiteralPath $LeavesCsv)) {
            if (-not [string]::IsNullOrWhiteSpace([string]$Row.leaf_id)) {
                $Metadata[[string]$Row.leaf_id] = $Row
            }
        }
    }
    catch {}
}


function Get-LeafOrdinal {
    param([string]$LeafId)

    if ($Metadata.ContainsKey($LeafId)) {
        try {
            return [int]$Metadata[$LeafId].leaf_ordinal
        }
        catch {}
    }

    return [int]::MaxValue
}


function Build-SettledRow {
    param(
        [string]$LeafId,
        $PassEntry,
        $QueueEntry,
        [int]$SelectedCount
    )

    $Meta = $null

    if ($Metadata.ContainsKey($LeafId)) {
        $Meta = $Metadata[$LeafId]
    }

    $Ordinal = Get-LeafOrdinal $LeafId

    if ($Ordinal -eq [int]::MaxValue) {
        $LeafLabel = "?/$SelectedCount"
    }
    else {
        $LeafLabel = "$Ordinal/$SelectedCount"
    }

    if ($null -ne $Meta) {
        $Mode = [string]$Meta.mode
        $Spin = Format-Spin $Meta.spin_or_Mkappa
        $Mechanism = Short-Mechanism ([string]$Meta.mechanism)
        $Role = [string]$Meta.role
    }
    else {
        $Mode = "-"
        $Spin = "-"
        $Mechanism = "-"
        $Role = "-"
    }

    $Seconds = Sum-TierTime $PassEntry

    try {
        $Samples = [int]$PassEntry.sample_count
    }
    catch {
        $Samples = 0
    }

    $Next = "-"
    $State = [string]$PassEntry.disposition

    if ($null -ne $QueueEntry -and $QueueEntry.disposition -eq "PENDING") {
        $Next = [string]$QueueEntry.minimum_requested_tier
        $State = "QUEUED->$Next"
    }

    return [pscustomobject]@{
        Ordinal   = $Ordinal
        Leaf      = $LeafLabel
        Mode      = $Mode
        Spin      = $Spin
        Mechanism = $Mechanism
        Role      = $Role
        Time      = Format-Time $Seconds
        Samples   = $Samples
        Next      = $Next
        State     = $State
    }
}


function Write-SettledRow {
    param($Row)

    switch -Wildcard ($Row.State) {
        "QUEUED*"      { $Color = [ConsoleColor]::Yellow; break }
        "COMPLETED"    { $Color = [ConsoleColor]::Green; break }
        "CACHE_REUSED" { $Color = [ConsoleColor]::Green; break }
        "PRODUCED"     { $Color = [ConsoleColor]::Green; break }
        "UNRESOLVED"   { $Color = [ConsoleColor]::Magenta; break }
        "DEFERRED"     { $Color = [ConsoleColor]::DarkYellow; break }
        "REJECTED"     { $Color = [ConsoleColor]::Red; break }
        default        { $Color = [ConsoleColor]::Gray }
    }

    Write-Line (
        "  {0,-9} {1,-5} {2,-10} {3,-16} {4,-8} {5,8} {6,7} {7,-6} {8}" -f
        $Row.Leaf,
        $Row.Mode,
        $Row.Spin,
        $Row.Mechanism,
        $Row.Role,
        $Row.Time,
        $Row.Samples,
        $Row.Next,
        $Row.State
    ) $Color
}


# ============================================================================
# WAIT FOR FIRST VALID CHECKPOINT
# ============================================================================

$CheckpointData = $null

while ($null -eq $CheckpointData) {
    $CheckpointData = Read-JsonSafe $Checkpoint

    if ($null -eq $CheckpointData) {
        Start-Sleep -Milliseconds 200
    }
}

$Status = Read-JsonSafe $StatusPath


# ============================================================================
# REMOVE ALL POWERSHELL PASTE PROMPTS ONCE
# ============================================================================

Clear-Host


# ============================================================================
# INITIAL DURABLE SNAPSHOT
# ============================================================================

$BinaryEntries = @(Get-MapEntries $CheckpointData.survey_pass_ledger.binary64)
$PromotedEntries = @(Get-MapEntries $CheckpointData.survey_pass_ledger.promoted)

$Queue = @($CheckpointData.promotion_queue.entries)
$Records = @($CheckpointData.records)
$Failures = @($CheckpointData.system_failures)


if ($Metadata.Count -gt 0) {
    $SelectedCount = $Metadata.Count
}
elseif (
    $null -ne $Status -and
    $null -ne $Status.next_intended_leaf -and
    $null -ne $Status.next_intended_leaf.leaf_count
) {
    $SelectedCount = [int]$Status.next_intended_leaf.leaf_count
}
else {
    $SelectedCount = [math]::Max($BinaryEntries.Count, $Queue.Count)
}


$BinaryProcessed = $BinaryEntries.Count
$PromotedProcessed = $PromotedEntries.Count


$Produced = @(
    $Records |
        Where-Object { $_.state -eq "PRODUCED" }
).Count


$Pending = @(
    $Queue |
        Where-Object { $_.disposition -eq "PENDING" }
)


$PendingBF40 = @(
    $Pending |
        Where-Object { $_.minimum_requested_tier -eq "BF40" }
).Count


$PendingBF80 = @(
    $Pending |
        Where-Object { $_.minimum_requested_tier -eq "BF80" }
).Count


$AllDispositions = @()

foreach ($Entry in $BinaryEntries) {
    $AllDispositions += $Entry.Value
}

foreach ($Entry in $PromotedEntries) {
    $AllDispositions += $Entry.Value
}


$Deferred = @(
    $AllDispositions |
        Where-Object { $_.disposition -eq "DEFERRED" }
).Count


$Unresolved = @(
    $AllDispositions |
        Where-Object { $_.disposition -eq "UNRESOLVED" }
).Count


$Rejected = @(
    $AllDispositions |
        Where-Object { $_.disposition -eq "REJECTED" }
).Count


$Screened = Get-EvidenceCount $CheckpointData.evidence_ledger "SCREENED"
$Certified = Get-EvidenceCount $CheckpointData.evidence_ledger "CERTIFIED"
$Validated = Get-EvidenceCount $CheckpointData.evidence_ledger "VALIDATED"


$RetainedSamples = 0

foreach ($Entry in $BinaryEntries) {
    try {
        $RetainedSamples += [int]$Entry.Value.sample_count
    }
    catch {}
}


if (
    $PromotedProcessed -gt 0 -or
    (
        $null -ne $Status -and
        $Status.survey_pass -eq "promoted"
    )
) {
    $ActivePass = "PROMOTED"
}
else {
    $ActivePass = "BINARY64"
}


if (Test-Path -LiteralPath $LockPath -PathType Leaf) {
    $LockStatus = "PRESENT"
}
else {
    $LockStatus = "NOT YET CREATED"
}


# ============================================================================
# OPERATOR-APPROVED LAYOUT
# ============================================================================

Write-Line (Rule) DarkCyan
Write-Line "  M02 | OPERATOR DASHBOARD" Cyan
Write-Line (Rule) DarkCyan

Write-Line (
    "  PROFILE  SURVEY    PASS  {0,-10}    CHECKPOINT  schema-{1}    LAYER-1 LOCK  {2}" -f
    $ActivePass,
    $CheckpointData.schema_version,
    $LockStatus
) White

Write-Line (Rule "-") DarkGray

Write-Line (
    "  BINARY64 PROCESSED   {0,3}/{1,-3}     PRODUCED   {2,3}     PENDING   {3,3}     SYS FAIL   {4,3}" -f
    $BinaryProcessed,
    $SelectedCount,
    $Produced,
    $Pending.Count,
    $Failures.Count
) White

Write-Line (
    "  PROMOTION ROUTES        BF40 {0,3}     BF80 {1,3}     RETAINED BINARY64 SAMPLES {2,4}" -f
    $PendingBF40,
    $PendingBF80,
    $RetainedSamples
) Yellow

Write-Line (
    "  PROMOTED PROCESSED    {0,3}         DEFERRED {1,3}     UNRESOLVED {2,3}     REJECTED {3,3}" -f
    $PromotedProcessed,
    $Deferred,
    $Unresolved,
    $Rejected
) Gray

Write-Line (
    "  EVIDENCE             SCREENED {0,3}     CERTIFIED {1,3}     VALIDATED {2,3}" -f
    $Screened,
    $Certified,
    $Validated
) DarkGray

Write-Line (Rule "-") DarkGray


# ============================================================================
# RUNNING STRIP — INITIAL SNAPSHOT ONLY
#
# It does NOT repaint afterward.
# ============================================================================

$HasLiveLeaf = (
    $null -ne $Status -and
    $null -ne $Status.live_execution -and
    -not [string]::IsNullOrWhiteSpace(
        [string]$Status.live_execution.leaf
    )
)


if ($HasLiveLeaf) {

    $Live = $Status.live_execution

    $LiveParts = @("RUNNING")

    if (-not [string]::IsNullOrWhiteSpace([string]$Live.leaf)) {
        $LiveParts += [string]$Live.leaf
    }

    if (-not [string]::IsNullOrWhiteSpace([string]$Live.mode)) {
        $LiveParts += [string]$Live.mode
    }

    if ($null -ne $Live.spin) {
        $LiveParts += ("a={0}" -f (Format-Spin $Live.spin))
    }

    if (-not [string]::IsNullOrWhiteSpace([string]$Live.mechanism)) {
        $LiveParts += Short-Mechanism ([string]$Live.mechanism)
    }

    if (-not [string]::IsNullOrWhiteSpace([string]$Live.tier)) {
        $LiveParts += [string]$Live.tier
    }

    if (-not [string]::IsNullOrWhiteSpace([string]$Live.role)) {
        $LiveParts += [string]$Live.role
    }

    if (-not [string]::IsNullOrWhiteSpace([string]$Live.suboperation)) {
        $LiveParts += [string]$Live.suboperation
    }
    elseif (-not [string]::IsNullOrWhiteSpace([string]$Live.phase)) {
        $LiveParts += [string]$Live.phase
    }

    if (-not [string]::IsNullOrWhiteSpace([string]$Live.elapsed)) {
        $LiveParts += [string]$Live.elapsed
    }

    Write-Line (
        "  " + ($LiveParts -join "  |  ")
    ) Cyan
}
elseif (
    $null -ne $Status -and
    $null -ne $Status.terminal_event -and
    $Status.terminal_event.kind -eq "campaign_pass_completed"
) {
    Write-Line "  PASS COMPLETE — no active leaf" Green
}
else {
    Write-Line "  WAITING FOR ACTIVE LEAF..." DarkGray
}


Write-Line (Rule "-") DarkGray
Write-Line "  LAST SETTLED LEAVES" White
Write-Line ""

Write-Line (
    "  {0,-9} {1,-5} {2,-10} {3,-16} {4,-8} {5,8} {6,7} {7,-6} {8}" -f
    "LEAF",
    "MODE",
    "SPIN",
    "MECHANISM",
    "ROLE",
    "TIME",
    "SAMPLES",
    "NEXT",
    "STATE"
) DarkCyan

Write-Line (
    "  {0,-9} {1,-5} {2,-10} {3,-16} {4,-8} {5,8} {6,7} {7,-6} {8}" -f
    ("-" * 9),
    ("-" * 5),
    ("-" * 10),
    ("-" * 16),
    ("-" * 8),
    ("-" * 8),
    ("-" * 7),
    ("-" * 6),
    ("-" * 18)
) DarkGray


# ============================================================================
# INITIAL SETTLED ROWS
# ============================================================================

$QueueByLeaf = Get-QueueByLeaf $CheckpointData

$InitialRows = @()

foreach ($Entry in $BinaryEntries) {

    $LeafId = [string]$Entry.Key

    if ($QueueByLeaf.ContainsKey($LeafId)) {
        $QueueEntry = $QueueByLeaf[$LeafId]
    }
    else {
        $QueueEntry = $null
    }

    $InitialRows += Build-SettledRow `
        -LeafId $LeafId `
        -PassEntry $Entry.Value `
        -QueueEntry $QueueEntry `
        -SelectedCount $SelectedCount
}


$InitialRows = @(
    $InitialRows |
        Sort-Object Ordinal
)


foreach (
    $Row in @(
        $InitialRows |
            Select-Object -Last $InitialRowsToShow
    )
) {
    Write-SettledRow $Row
}


# Mark ALL existing settled leaves known.
# Older rows intentionally omitted from the initial last-14 display must not
# suddenly reappear.

$KnownLeafIds = @{}

foreach ($Entry in $BinaryEntries) {
    $KnownLeafIds[[string]$Entry.Key] = $true
}


$TerminalSummaryWritten = $false


# ============================================================================
# APPEND-ONLY WATCH
#
# THE SCREEN IS NEVER CLEARED AGAIN.
# NO HEADER IS EVER REPRINTED.
# NO COUNT LINE IS EVER REPAINTED.
# NO CARRIAGE-RETURN LIVE LINE IS USED.
#
# ONE NEW DURABLE B64 DISPOSITION = ONE NEW TABLE ROW.
# ============================================================================

while ($true) {

    $CurrentCheckpoint = Read-JsonSafe $Checkpoint

    if ($null -eq $CurrentCheckpoint) {
        Start-Sleep -Milliseconds $PollMilliseconds
        continue
    }

    $CurrentStatus = Read-JsonSafe $StatusPath

    $CurrentBinary = @(
        Get-MapEntries `
            $CurrentCheckpoint.survey_pass_ledger.binary64
    )

    $CurrentQueueByLeaf = Get-QueueByLeaf $CurrentCheckpoint


    $NewEntries = @(
        $CurrentBinary |
            Where-Object {
                -not $KnownLeafIds.ContainsKey(
                    [string]$_.Key
                )
            } |
            Sort-Object {
                Get-LeafOrdinal ([string]$_.Key)
            }
    )


    foreach ($Entry in $NewEntries) {

        $LeafId = [string]$Entry.Key

        if ($CurrentQueueByLeaf.ContainsKey($LeafId)) {
            $QueueEntry = $CurrentQueueByLeaf[$LeafId]
        }
        else {
            $QueueEntry = $null
        }

        $Row = Build-SettledRow `
            -LeafId $LeafId `
            -PassEntry $Entry.Value `
            -QueueEntry $QueueEntry `
            -SelectedCount $SelectedCount

        Write-SettledRow $Row

        $KnownLeafIds[$LeafId] = $true
    }


    # ========================================================================
    # PASS COMPLETION — APPEND ONCE
    #
    # The footer is terminal-only. Printing a footer before completion would
    # force later rows outside the table or require cursor rewrites, both of
    # which violate append-only rendering.
    # ========================================================================

    $PassComplete = (
        $null -ne $CurrentStatus -and
        $null -ne $CurrentStatus.terminal_event -and
        $CurrentStatus.terminal_event.kind -eq "campaign_pass_completed"
    )


    if (
        $PassComplete -and
        -not $TerminalSummaryWritten
    ) {

        $CurrentQueue = @(
            $CurrentCheckpoint.promotion_queue.entries
        )

        $CurrentPending = @(
            $CurrentQueue |
                Where-Object {
                    $_.disposition -eq "PENDING"
                }
        )

        $CurrentBF40 = @(
            $CurrentPending |
                Where-Object {
                    $_.minimum_requested_tier -eq "BF40"
                }
        ).Count

        $CurrentBF80 = @(
            $CurrentPending |
                Where-Object {
                    $_.minimum_requested_tier -eq "BF80"
                }
        ).Count

        $CurrentRetainedSamples = 0

        foreach ($Entry in $CurrentBinary) {
            try {
                $CurrentRetainedSamples +=
                    [int]$Entry.Value.sample_count
            }
            catch {}
        }

        Write-Line ""
        Write-Line (Rule "-") DarkGray
        Write-Line "  BINARY64 SURVEY COMPLETE" Green
        Write-Line ""

        Write-Line (
            "  PROCESSED                  {0,3}/{1}" -f
            $CurrentBinary.Count,
            $SelectedCount
        ) White

        Write-Line (
            "  PENDING PROMOTIONS         {0,3}" -f
            $CurrentPending.Count
        ) White

        Write-Line (
            "    EXTERIOR -> BF40         {0,3}" -f
            $CurrentBF40
        ) Yellow

        Write-Line (
            "    HORIZON  -> BF80         {0,3}" -f
            $CurrentBF80
        ) Yellow

        Write-Line (
            "  RETAINED BINARY64 SAMPLES {0,4}" -f
            $CurrentRetainedSamples
        ) White

        Write-Line (
            "  SYSTEM FAILURES            {0,3}" -f
            @($CurrentCheckpoint.system_failures).Count
        ) White

        Write-Line ""
        Write-Line "  NEXT PASS: SURVEY / PROMOTED" Cyan
        Write-Line (Rule "-") DarkGray
        Write-Line "  Ctrl+C stops this preview. The solver in the other window is untouched." DarkGray
        Write-Line (Rule) DarkCyan

        $TerminalSummaryWritten = $true
        break
    }


    Start-Sleep -Milliseconds $PollMilliseconds
}

}
```
