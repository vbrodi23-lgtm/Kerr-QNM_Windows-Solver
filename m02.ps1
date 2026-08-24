param(
    [string]$Selection = ".\examples\m02-campaign.json",
    [string]$Checkpoint = ".\m02-output\m02-campaign-checkpoint.json",
    [ValidateSet("survey", "certify", "validate")]
    [string]$Profile = "survey",
    [ValidateSet("binary64", "promoted")]
    [string]$SurveyPass = "binary64",
    [string]$QueuePath,
    [switch]$NewCampaign,
    [switch]$SkipBootstrap,
    [switch]$RebuildRuntime,
    [switch]$PortableRuntime,
    [string]$RuntimeRoot,
    [string]$CalibrationReceiptPath,
    [string]$CalibrationReceiptSha256,
    [ValidateSet("quiet", "normal", "trace")]
    [string]$Progress = "normal"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
$PackageRoot = $PSScriptRoot
. (Join-Path $PackageRoot "runtime\resolve-runtime-root.ps1")
$ResolvedRuntimeRoot = Resolve-KerrQnmRuntimeRoot -PackageRoot $PackageRoot `
    -PortableRuntime:$PortableRuntime -OverrideRoot $RuntimeRoot
Set-KerrQnmRuntimeRoot $ResolvedRuntimeRoot

function Invoke-M02Command([string[]]$Arguments) {
    try {
        & (Join-Path $PackageRoot "solver.ps1") @Arguments
        $CommandExitCode = $LASTEXITCODE
    }
    catch [System.Management.Automation.PipelineStoppedException] {
        exit 130
    }
    catch {
        if ($LASTEXITCODE -eq 130 -or $LASTEXITCODE -eq -1073741510 -or $LASTEXITCODE -eq 3221225786) {
            exit 130
        }
        throw
    }
    if ($CommandExitCode -eq -1073741510 -or $CommandExitCode -eq 3221225786) {
        $CommandExitCode = 130
    }
    if ($CommandExitCode -eq 130) {
        exit 130
    }
    if ($CommandExitCode -ne 0) {
        throw "M02 command failed with exit code $CommandExitCode."
    }
}

if ($SkipBootstrap -and $RebuildRuntime) {
    throw "-SkipBootstrap and -RebuildRuntime cannot be used together."
}
if ($Profile -ne "survey" -and $SurveyPass -ne "binary64") {
    throw "-SurveyPass applies only to -Profile survey."
}
if ($Profile -eq "survey" -and -not [string]::IsNullOrWhiteSpace($QueuePath)) {
    throw "-QueuePath applies only to certify or validate."
}
if ($Profile -eq "validate" -and [string]::IsNullOrWhiteSpace($QueuePath)) {
    throw "-Profile validate requires -QueuePath."
}
if ($NewCampaign -and ($Profile -ne "survey" -or $SurveyPass -ne "binary64")) {
    throw "-NewCampaign starts only the binary64 survey."
}
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

if (-not $SkipBootstrap) {
    $BootstrapParameters = @{
        WithM02 = $true
        PortableRuntime = [bool]$PortableRuntime
    }
    if ($RebuildRuntime) {
        $BootstrapParameters.Force = $true
    }
    if (-not [string]::IsNullOrWhiteSpace($RuntimeRoot)) {
        $BootstrapParameters.RuntimeRoot = $RuntimeRoot
    }
    & (Join-Path $PackageRoot "runtime\bootstrap.ps1") @BootstrapParameters
    if ($LASTEXITCODE -ne 0) {
        throw "M02 runtime bootstrap failed with exit code $LASTEXITCODE."
    }
}

$SelectionPath = if ([IO.Path]::IsPathRooted($Selection)) {
    [IO.Path]::GetFullPath($Selection)
}
else {
    [IO.Path]::GetFullPath((Join-Path $PackageRoot $Selection))
}
$CheckpointPath = if ([IO.Path]::IsPathRooted($Checkpoint)) {
    [IO.Path]::GetFullPath($Checkpoint)
}
else {
    [IO.Path]::GetFullPath((Join-Path $PackageRoot $Checkpoint))
}
if (-not (Test-Path -LiteralPath $SelectionPath -PathType Leaf)) {
    throw "M02 selection is absent: $SelectionPath"
}
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $CheckpointPath) |
    Out-Null

$CheckpointExists = Test-Path -LiteralPath $CheckpointPath -PathType Leaf
if ($NewCampaign -and $CheckpointExists) {
    throw "-NewCampaign refuses an existing checkpoint: $CheckpointPath"
}
if (-not $NewCampaign -and -not $CheckpointExists) {
    throw "Resume requires an existing checkpoint. Use -NewCampaign with a new path for a cold start: $CheckpointPath"
}

$ResolvedQueuePath = $null
if (-not [string]::IsNullOrWhiteSpace($QueuePath)) {
    $ResolvedQueuePath = if ([IO.Path]::IsPathRooted($QueuePath)) {
        [IO.Path]::GetFullPath($QueuePath)
    }
    else {
        [IO.Path]::GetFullPath((Join-Path $PackageRoot $QueuePath))
    }
    if (-not (Test-Path -LiteralPath $ResolvedQueuePath -PathType Leaf)) {
        throw "Queue is absent: $ResolvedQueuePath"
    }
}

Push-Location $PackageRoot
try {
    Invoke-M02Command -Arguments @(
        "campaign-prepare-resources",
        $SelectionPath
    ) | Out-Null
    if ($NewCampaign) {
        Invoke-M02Command -Arguments @(
            "campaign-new",
            $SelectionPath,
            "--output", $CheckpointPath
        ) | Out-Null
    }
    $Command = if ($Profile -eq "survey" -and $SurveyPass -eq "binary64") {
        "campaign-survey-binary64"
    }
    elseif ($Profile -eq "survey") {
        "campaign-survey-promoted"
    }
    elseif ($Profile -eq "certify") {
        "campaign-certify"
    }
    else {
        "campaign-evidence-validate"
    }
    $CampaignPlan = Invoke-M02Command -Arguments @(
        "campaign-plan",
        $SelectionPath
    ) | ConvertFrom-Json
    if (
        $null -eq $CampaignPlan -or
        $null -eq $CampaignPlan.role_counts -or
        $null -eq $CampaignPlan.leaf_count
    ) {
        throw "M02 campaign plan did not report role and leaf counts."
    }
    $CheckpointStatus = Invoke-M02Command -Arguments @(
        "campaign-schema11-validate",
        $SelectionPath,
        "--checkpoint", $CheckpointPath
    ) | ConvertFrom-Json
    Write-Host "M02 campaign startup" -ForegroundColor Cyan
    Write-Host ("    Resolved checkpoint      : {0}" -f $CheckpointPath)
    Write-Host ("    Selected command         : {0}" -f $Command)
    Write-Host ("    Execution profile        : {0}" -f $Profile)
    $SelectedSurveyPass = if ($Profile -eq "survey") {
        $SurveyPass
    }
    else {
        "not-applicable"
    }
    Write-Host ("    Survey pass              : {0}" -f $SelectedSurveyPass)
    Write-Host ("    Selection ID             : {0}" -f $CheckpointStatus.selection_id)
    Write-Host ("    Checkpoint schema        : {0}" -f $CheckpointStatus.schema_version)
    Write-Host ("    Recovered terminal count : {0}" -f $CheckpointStatus.recovered_terminal_count)
    Write-Host ("    Binary64 pass count      : {0}" -f $CheckpointStatus.binary64_pass_count)
    Write-Host ("    Promotion queue count    : {0}" -f $CheckpointStatus.promotion_queue_count)
    Write-Host ("    Evidence counts          : {0}" -f ($CheckpointStatus.evidence_counts | ConvertTo-Json -Compress))
    Write-Host ("    Basic report directory   : {0}" -f $CheckpointStatus.basic_report_directory)
    Write-Host ("    Status path              : {0}" -f "$CheckpointPath.status.json")
    $RunArguments = @(
        $Command,
        $SelectionPath,
        "--checkpoint", $CheckpointPath,
        "--progress", $Progress
    ) + $CalibrationArguments
    if ($null -ne $ResolvedQueuePath) {
        $RunArguments += @("--queue", $ResolvedQueuePath)
    }
    Invoke-M02Command -Arguments $RunArguments
    $ValidationPass = if ($Profile -eq "survey") {
        $SurveyPass
    }
    else {
        $Profile
    }
    Invoke-M02Command -Arguments @(
        "campaign-schema11-validate",
        $SelectionPath,
        "--checkpoint", $CheckpointPath,
        "--pass", $ValidationPass
    ) | Out-Null
}
finally {
    Pop-Location
}

Write-Host "M02 requested pass finished; checkpoint is structurally valid:" -ForegroundColor Green
Write-Host "    $CheckpointPath"
