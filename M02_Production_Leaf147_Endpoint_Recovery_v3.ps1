[CmdletBinding(PositionalBinding = $false)]
param(
    [string]$OutputRoot = ".\m02-output\leaf147-endpoint-recovery-v3",
    [string]$StoppedCheckpointPath,
    [switch]$SkipBootstrap,
    [switch]$PortableRuntime,
    [string]$RuntimeRoot,
    [ValidateSet("quiet", "normal", "trace")]
    [string]$Progress = "trace"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
$PackageRoot = $PSScriptRoot
$ExpectedLeafId = "b-prime-leaf-e6c649ba56795de2c7c4d992fc92652914622017bbd0a0443ab75de34057c1f0"

function Assert-Canary([bool]$Condition, [string]$Message) {
    if (-not $Condition) {
        throw "Leaf-147 endpoint recovery canary failed: $Message"
    }
}

function Get-Sha256([string]$Path) {
    $Sha256 = [Security.Cryptography.SHA256]::Create()
    try {
        return (
            [BitConverter]::ToString(
                $Sha256.ComputeHash([IO.File]::ReadAllBytes($Path))
            ) -replace "-", ""
        ).ToLowerInvariant()
    }
    finally {
        $Sha256.Dispose()
    }
}

function Find-Receipt([object]$Value, [string]$Schema) {
    $Found = @()
    if ($null -eq $Value) { return $Found }
    if ($Value -is [string] -or $Value -is [ValueType]) { return $Found }
    if ($Value -is [Collections.IEnumerable] -and -not ($Value -is [Management.Automation.PSCustomObject])) {
        foreach ($Item in $Value) { $Found += @(Find-Receipt $Item $Schema) }
        return $Found
    }
    $SchemaProperty = $Value.PSObject.Properties["schema"]
    if ($null -ne $SchemaProperty -and [string]$SchemaProperty.Value -eq $Schema) {
        $Found += $Value
    }
    foreach ($Property in $Value.PSObject.Properties) {
        if ($Property.Name -ne "schema") {
            $Found += @(Find-Receipt $Property.Value $Schema)
        }
    }
    return $Found
}

$ResolvedOutputRoot = [IO.Path]::GetFullPath((Join-Path $PackageRoot $OutputRoot))
$SelectionPath = Join-Path $ResolvedOutputRoot "selection.json"
$CheckpointPath = Join-Path $ResolvedOutputRoot "checkpoint.json"
$EvidencePath = Join-Path $ResolvedOutputRoot "leaf147-canary-evidence.json"
foreach ($Path in @($SelectionPath, $CheckpointPath, $EvidencePath)) {
    if (Test-Path -LiteralPath $Path) {
        throw "Leaf-147 canary refuses existing output: $Path"
    }
}
$StoppedCheckpointSha256 = $null
if (-not [string]::IsNullOrWhiteSpace($StoppedCheckpointPath)) {
    $StoppedCheckpointSha256 = Get-Sha256 $StoppedCheckpointPath
}
New-Item -ItemType Directory -Force -Path $ResolvedOutputRoot | Out-Null
. (Join-Path $PackageRoot "runtime\resolve-runtime-root.ps1")
$ResolvedRuntimeRoot = Resolve-KerrQnmRuntimeRoot -PackageRoot $PackageRoot `
    -PortableRuntime:$PortableRuntime -OverrideRoot $RuntimeRoot
Set-KerrQnmRuntimeRoot $ResolvedRuntimeRoot
if (-not $SkipBootstrap) {
    $BootstrapParameters = @{
        WithM02 = $true
        PortableRuntime = [bool]$PortableRuntime
    }
    if (-not [string]::IsNullOrWhiteSpace($RuntimeRoot)) {
        $BootstrapParameters.RuntimeRoot = $RuntimeRoot
    }
    & (Join-Path $PackageRoot "runtime\bootstrap.ps1") @BootstrapParameters
    Assert-Canary ($LASTEXITCODE -eq 0) "managed runtime bootstrap failed"
}

$OriginalLocalAppData = $env:LOCALAPPDATA
$OriginalReadoutCacheRoot = $env:KERR_QNM_ROOT_READOUT_CACHE_ROOT
$OriginalJournalRoot = $env:KERR_QNM_PARTIAL_COMPONENT_JOURNAL_ROOT
try {
    $env:LOCALAPPDATA = Join-Path $ResolvedOutputRoot "operator-local-app-data"
    $env:KERR_QNM_ROOT_READOUT_CACHE_ROOT = Join-Path $ResolvedOutputRoot "root-readout-cache"
    $env:KERR_QNM_PARTIAL_COMPONENT_JOURNAL_ROOT = Join-Path $ResolvedOutputRoot "partial-component-journal"

    $PlanJson = & (Join-Path $PackageRoot "solver.ps1") `
        "campaign-plan" ".\examples\m02-campaign.json"
    Assert-Canary ($LASTEXITCODE -eq 0) "campaign plan failed"
    $Plan = ($PlanJson -join "`n") | ConvertFrom-Json
    $Targets = @($Plan.campaign.leaves | Where-Object {
        [string]$_.leaf_id -eq $ExpectedLeafId
    })
    Assert-Canary ($Targets.Count -eq 1) "the authenticated leaf ID was not unique"
    $Target = $Targets[0]
    Assert-Canary ([string]$Target.role -eq "control") "role is not control"
    Assert-Canary ([string]$Target.mode_label -eq "2-minus-2-0") "mode is not 2-minus-2-0"
    Assert-Canary ([string]$Target.mechanism_id -eq "exterior-fixed-r3") "mechanism is not ext-r3"
    Assert-Canary (
        [int]$Target.coordinate_exact.numerator -eq 19 -and
        [int]$Target.coordinate_exact.denominator -eq 20
    ) "spin is not the authenticated exact 19/20 coordinate"

    $Selection = [ordered]@{
        schema_version = 1
        backend_id = "vetted-native-gsn-determinant"
        precision_digits = @(64, 80, 120)
        precision_backend = $null
        role = "control"
        leaf_ids = @($ExpectedLeafId)
        cohort_ids = $null
    }
    [IO.File]::WriteAllText(
        $SelectionPath,
        ($Selection | ConvertTo-Json -Depth 100),
        (New-Object Text.UTF8Encoding($false))
    )
    $RunParameters = @{
        Selection = $SelectionPath
        Checkpoint = $CheckpointPath
        Profile = "survey"
        SurveyPass = "full"
        NewCampaign = $true
        Progress = $Progress
        SkipBootstrap = $true
        PortableRuntime = [bool]$PortableRuntime
    }
    if (-not [string]::IsNullOrWhiteSpace($RuntimeRoot)) {
        $RunParameters.RuntimeRoot = $RuntimeRoot
    }
    & (Join-Path $PackageRoot "m02.ps1") @RunParameters
    Assert-Canary ($LASTEXITCODE -eq 0) "one-leaf M02 execution failed"

    $Checkpoint = Get-Content -LiteralPath $CheckpointPath -Raw | ConvertFrom-Json
    $Queue = @($Checkpoint.promotion_queue.entries)
    Assert-Canary ($Queue.Count -eq 1) "checkpoint does not contain one promotion"
    $Entry = $Queue[0]
    Assert-Canary ([string]$Entry.leaf_id -eq $ExpectedLeafId) "queue leaf identity changed"
    Assert-Canary ([string]$Entry.disposition -eq "AWAITING_ADMISSION") "leaf did not reach AWAITING_ADMISSION"
    $Binary64Properties = @($Checkpoint.survey_pass_ledger.binary64.PSObject.Properties)
    Assert-Canary ($Binary64Properties.Count -eq 1) "Binary64 did not complete"
    Assert-Canary ([int]$Binary64Properties[0].Value.sample_count -eq 9) "Binary64 did not retain nine samples"
    Assert-Canary (@($Checkpoint.system_failures).Count -eq 0) "system failure was retained"

    $Stage = $Checkpoint.promoted_stage_ledger."0".$ExpectedLeafId
    Assert-Canary ($null -ne $Stage) "promoted stage is absent"
    Assert-Canary (@($Stage.precision_tiers) -contains "BF40") "BF40 was not used"
    Assert-Canary (-not (@($Stage.precision_tiers) -contains "BF80")) "BF80 was invoked"
    $Receipts = @(Find-Receipt $Stage "windows-solver.exterior-endpoint-recovery-receipt/3")
    $InfinityReceipts = @($Receipts | Where-Object {
        [string]$_.endpoint_branch -eq "infinity-outgoing"
    })
    Assert-Canary ($InfinityReceipts.Count -ge 1) "v3 infinity receipt is absent"
    $Infinity = $InfinityReceipts[-1]
    $Attempts = @($Infinity.attempts)
    $Coordinates = @($Attempts | ForEach-Object {
        "{0}:{1}" -f $_.attempted_endpoint_order, $_.attempted_geometry
    })
    Assert-Canary ($Coordinates -contains "112:100") "order 112 at geometry 100 was not attempted"
    Assert-Canary ($Coordinates -contains "28:250") "geometry did not advance and reset to order 28"
    Assert-Canary (
        @($Attempts | Where-Object { [decimal]$_.attempted_geometry -gt 100 }).Count -gt 0
    ) "no geometry beyond 100 was attempted"
    Assert-Canary ([int]$Infinity.factored_homogeneous_rhs_evaluations -eq 0) "homogeneous RHS ran before endpoint adequacy"
    Assert-Canary (-not [string]::IsNullOrWhiteSpace([string]$Entry.source_root_seal_sha256)) "authenticated root seal is absent"
    $RootPayload = $Checkpoint.promoted_root_ledger."0".$ExpectedLeafId.payload
    Assert-Canary (
        [string]$RootPayload.root_seal_sha256 -eq [string]$Entry.source_root_seal_sha256
    ) "promoted calculation replaced the authenticated root"

    $Evidence = [ordered]@{
        schema = "windows-solver.m02-leaf147-endpoint-recovery-canary/1"
        leaf_id = $ExpectedLeafId
        role = [string]$Target.role
        mode = [string]$Target.mode_label
        spin_exact = "19/20"
        mechanism = [string]$Target.mechanism_id
        promoted_tier = "BF40"
        disposition = [string]$Entry.disposition
        endpoint_coordinates = $Coordinates
        endpoint_receipt_schema = [string]$Infinity.schema
        endpoint_policy_identity = [string]$Infinity.recovery_policy_identity
        endpoint_policy_sha256 = [string]$Infinity.recovery_policy_sha256
        promoted_stage_sha256 = [string]$Stage.stage_sha256
        root_seal_sha256 = [string]$Entry.source_root_seal_sha256
        checkpoint_sha256 = Get-Sha256 $CheckpointPath
        binary64_completed = $true
        binary64_sample_count = 9
        bf80_invoked = $false
        system_failure_count = 0
    }
    [IO.File]::WriteAllText(
        $EvidencePath,
        ($Evidence | ConvertTo-Json -Depth 100),
        (New-Object Text.UTF8Encoding($false))
    )
}
finally {
    $env:LOCALAPPDATA = $OriginalLocalAppData
    $env:KERR_QNM_ROOT_READOUT_CACHE_ROOT = $OriginalReadoutCacheRoot
    $env:KERR_QNM_PARTIAL_COMPONENT_JOURNAL_ROOT = $OriginalJournalRoot
}

if (-not [string]::IsNullOrWhiteSpace($StoppedCheckpointPath)) {
    $After = Get-Sha256 $StoppedCheckpointPath
    Assert-Canary ($After -eq $StoppedCheckpointSha256) "live checkpoint bytes changed"
}
Write-Host "Leaf-147 endpoint recovery evidence: $EvidencePath"
