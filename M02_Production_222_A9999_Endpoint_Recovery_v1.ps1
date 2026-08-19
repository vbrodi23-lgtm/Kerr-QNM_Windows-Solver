[CmdletBinding(PositionalBinding = $false)]
param(
    [string]$OutputRoot = ".\m02-output\222-a9999-endpoint-recovery-v1",
    [string]$StoppedCheckpointPath,
    [switch]$SkipBootstrap,
    [switch]$PortableRuntime,
    [string]$RuntimeRoot,
    [string]$CalibrationReceiptPath,
    [string]$CalibrationReceiptSha256
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
$PackageRoot = $PSScriptRoot
. (Join-Path $PackageRoot "runtime\resolve-runtime-root.ps1")

function Assert-ProductionCondition {
    param([bool]$Condition, [string]$Message)
    if (-not $Condition) { throw "Cold endpoint recovery assertion failed: $Message" }
}

function Invoke-ProductionSolver {
    param([string[]]$Arguments, [switch]$AllowScientificFailure)
    $EffectiveArguments = @($Arguments)
    if ($EffectiveArguments[0] -in @("campaign-run", "campaign-resume")) {
        $EffectiveArguments += $CalibrationArguments
    }
    & (Join-Path $PackageRoot "solver.ps1") @EffectiveArguments
    $ExitCode = $LASTEXITCODE
    if ($ExitCode -ne 0 -and -not $AllowScientificFailure) {
        throw "Production solver command failed with exit code $ExitCode."
    }
    return $ExitCode
}

function Read-StrictJson {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "Expected production evidence is absent: $Path"
    }
    return Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json
}

$ResolvedOutputRoot = [IO.Path]::GetFullPath((Join-Path $PackageRoot $OutputRoot))
$HasCalibrationPath = -not [string]::IsNullOrWhiteSpace($CalibrationReceiptPath)
$HasCalibrationSha256 = -not [string]::IsNullOrWhiteSpace($CalibrationReceiptSha256)
if ($HasCalibrationPath -ne $HasCalibrationSha256) {
    throw "calibration receipt path and SHA-256 must be supplied together"
}
$CalibrationArguments = @()
if ($HasCalibrationPath) {
    $ResolvedCalibrationReceiptPath = if ([IO.Path]::IsPathRooted($CalibrationReceiptPath)) {
        [IO.Path]::GetFullPath($CalibrationReceiptPath)
    }
    else {
        [IO.Path]::GetFullPath((Join-Path $PackageRoot $CalibrationReceiptPath))
    }
    if (-not (Test-Path -LiteralPath $ResolvedCalibrationReceiptPath -PathType Leaf)) {
        throw "Calibration receipt is absent: $ResolvedCalibrationReceiptPath"
    }
    if ($CalibrationReceiptSha256 -notmatch '^[0-9A-Fa-f]{64}$') {
        throw "Calibration receipt SHA-256 is invalid."
    }
    $CalibrationArguments = @(
        "--calibration-receipt-path", $ResolvedCalibrationReceiptPath,
        "--calibration-receipt-sha256", $CalibrationReceiptSha256.ToLowerInvariant()
    )
}
$SelectionPath = Join-Path $ResolvedOutputRoot "selection.json"
$CheckpointPath = Join-Path $ResolvedOutputRoot "checkpoint.json"
$ReportPath = Join-Path $ResolvedOutputRoot "endpoint-recovery-report.json"
foreach ($Path in @($SelectionPath, $CheckpointPath, $ReportPath)) {
    if (Test-Path -LiteralPath $Path) {
        throw "Cold endpoint recovery refuses existing output: $Path"
    }
}

$StoppedCheckpointSha256Before = $null
if (-not [string]::IsNullOrWhiteSpace($StoppedCheckpointPath)) {
    $StoppedCheckpointSha256Before = (Get-FileHash -LiteralPath $StoppedCheckpointPath -Algorithm SHA256).Hash.ToLowerInvariant()
}

New-Item -ItemType Directory -Force -Path $ResolvedOutputRoot | Out-Null
$ResolvedRuntimeRoot = Resolve-KerrQnmRuntimeRoot -PackageRoot $PackageRoot `
    -PortableRuntime:$PortableRuntime -OverrideRoot $RuntimeRoot
Set-KerrQnmRuntimeRoot $ResolvedRuntimeRoot
if (-not $SkipBootstrap) {
    & (Join-Path $PackageRoot "runtime\bootstrap.ps1") -WithM02 -PortableRuntime:$PortableRuntime
    if ($LASTEXITCODE -ne 0) { throw "M02 runtime bootstrap failed." }
}

$OriginalLocalAppData = $env:LOCALAPPDATA
$OriginalReadoutCacheRoot = $env:KERR_QNM_ROOT_READOUT_CACHE_ROOT
$OriginalJournalRoot = $env:KERR_QNM_PARTIAL_COMPONENT_JOURNAL_ROOT
try {
    $env:LOCALAPPDATA = Join-Path $ResolvedOutputRoot "operator-local-app-data"
    $env:KERR_QNM_ROOT_READOUT_CACHE_ROOT = Join-Path $ResolvedOutputRoot "root-readout-cache"
    $env:KERR_QNM_PARTIAL_COMPONENT_JOURNAL_ROOT = Join-Path $ResolvedOutputRoot "partial-component-journal"

    $PlanJson = & (Join-Path $PackageRoot "solver.ps1") "campaign-plan" ".\examples\m02-campaign.json"
    if ($LASTEXITCODE -ne 0) { throw "Production campaign-plan failed." }
    $Plan = ($PlanJson -join "`n") | ConvertFrom-Json
    $Targets = @($Plan.campaign.leaves | Where-Object {
        $_.role -eq "primary" -and
        $_.mode_label -eq "222" -and
        $_.mechanism_id -eq "horizon-admittance" -and
        $_.coordinate_exact.numerator -eq 9999 -and
        $_.coordinate_exact.denominator -eq 10000
    })
    Assert-ProductionCondition ($Targets.Count -eq 1) "the canonical 222 target was not unique"
    $Target = $Targets[0]
    $Selection = [ordered]@{
        schema_version = 1
        backend_id = "vetted-native-gsn-determinant"
        precision_digits = @(64, 80, 120)
        precision_backend = $null
        role = "primary"
        leaf_ids = @([string]$Target.leaf_id)
        cohort_ids = $null
    }
    [IO.File]::WriteAllText($SelectionPath, ($Selection | ConvertTo-Json -Depth 100), (New-Object Text.UTF8Encoding($false)))

    $RunExitCode = Invoke-ProductionSolver -Arguments @(
        "campaign-run", $SelectionPath, "--checkpoint", $CheckpointPath, "--progress", "trace"
    ) -AllowScientificFailure
    if (Test-Path -LiteralPath $CheckpointPath) {
        Invoke-ProductionSolver -Arguments @("campaign-validate", $SelectionPath, "--checkpoint", $CheckpointPath)
    }

    $Checkpoint = Read-StrictJson $CheckpointPath
    Assert-ProductionCondition ($Checkpoint.records.Count -eq 1) "checkpoint must contain exactly the 222 leaf"
    $Record = $Checkpoint.records[0]
    $TracePath = Join-Path $ResolvedOutputRoot "checkpoint.json.progress\leaf-000001.jsonl"
    $Trace = if (Test-Path -LiteralPath $TracePath) { @(Get-Content -LiteralPath $TracePath | ForEach-Object { $_ | ConvertFrom-Json }) } else { @() }
    $EndpointCandidates = @($Trace | Where-Object { $_.kind -eq "horizon_endpoint_candidate" } | ForEach-Object { $_.payload })
    $Search = @($Trace | Where-Object { $_.kind -eq "horizon_endpoint_search_completed" } | Select-Object -Last 1)
    $Selected = @($Trace | Where-Object { $_.kind -eq "horizon_endpoints_verified" } | Select-Object -Last 1)
    $FinalTypedOutcome = if ($Search.Count -eq 1) { $Search[0].payload.outcome } else { "NO_ENDPOINT_SEARCH_EVIDENCE" }
    $DiagnosticOnly = -not ($Record.state -eq "PRODUCED")
    $Report = [ordered]@{
        schema = "windows-solver.m02-222-endpoint-recovery-report/1"
        leaf_id = [string]$Target.leaf_id
        semantic_precision_tiers = @("binary64", "bigfloat-40", "bigfloat-80", "bigfloat-120")
        endpoint_candidates = $EndpointCandidates
        endpoint_order = @($EndpointCandidates | ForEach-Object { $_.endpoint_order })
        ingoing_best_prefix_order = @($EndpointCandidates | ForEach-Object { $_.ingoing_best_prefix_order })
        outgoing_best_prefix_order = @($EndpointCandidates | ForEach-Object { $_.outgoing_best_prefix_order })
        predicted_reliable_digits = @($EndpointCandidates | ForEach-Object { @($_.ingoing_predicted_reliable_digits, $_.outgoing_predicted_reliable_digits) })
        selected_pair = if ($Selected.Count -eq 1) { $Selected[0].payload } else { $null }
        homogeneous_rhs_evaluations_before_pair = if ($Search.Count -eq 1) { $Search[0].payload.homogeneous_rhs_evaluations_before_pair } else { $null }
        final_typed_outcome = $FinalTypedOutcome
        diagnostic_only = $DiagnosticOnly
        scientific_success = ($Record.state -eq "PRODUCED")
        campaign_exit_code = $RunExitCode
    }
    [IO.File]::WriteAllText($ReportPath, ($Report | ConvertTo-Json -Depth 100), (New-Object Text.UTF8Encoding($false)))
}
finally {
    $env:LOCALAPPDATA = $OriginalLocalAppData
    $env:KERR_QNM_ROOT_READOUT_CACHE_ROOT = $OriginalReadoutCacheRoot
    $env:KERR_QNM_PARTIAL_COMPONENT_JOURNAL_ROOT = $OriginalJournalRoot
}

$StoppedCheckpointSha256After = $null
if (-not [string]::IsNullOrWhiteSpace($StoppedCheckpointPath)) {
    $StoppedCheckpointSha256After = (Get-FileHash -LiteralPath $StoppedCheckpointPath -Algorithm SHA256).Hash.ToLowerInvariant()
    Assert-ProductionCondition ($StoppedCheckpointSha256After -eq $StoppedCheckpointSha256Before) "stopped checkpoint bytes changed"
}
Write-Host "Endpoint recovery evidence written: $ReportPath"
