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
