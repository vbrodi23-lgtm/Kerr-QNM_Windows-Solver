param(
    [string]$Selection = ".\examples\m02-campaign.json",
    [string]$Checkpoint = ".\m02-output\m02-campaign-checkpoint.json",
    [switch]$SkipBootstrap,
    [switch]$RebuildRuntime,
    [switch]$PortableRuntime,
    [string]$RuntimeRoot,
    [string]$CalibrationReceiptPath,
    [string]$CalibrationReceiptSha256,
    [ValidateSet("survey", "certify", "validate")]
    [string]$Profile = "survey",
    [string]$TriageQueue,
    [int]$QueueLimit = 0,
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
$HasTriageQueue = -not [string]::IsNullOrWhiteSpace($TriageQueue)
if ($Profile -eq "survey" -and $HasTriageQueue) {
    throw "A triage queue is valid only for certify or validate."
}
if ($QueueLimit -lt 0 -or ($QueueLimit -gt 0 -and -not $HasTriageQueue)) {
    throw "A positive -QueueLimit requires -TriageQueue."
}
$TriageArguments = @()
if ($HasTriageQueue) {
    $ResolvedTriageQueue = if ([IO.Path]::IsPathRooted($TriageQueue)) {
        [IO.Path]::GetFullPath($TriageQueue)
    }
    else {
        [IO.Path]::GetFullPath((Join-Path $PackageRoot $TriageQueue))
    }
    if (-not (Test-Path -LiteralPath $ResolvedTriageQueue -PathType Leaf)) {
        throw "M02 triage queue is absent: $ResolvedTriageQueue"
    }
    $TriageArguments = @("--triage-queue", $ResolvedTriageQueue)
    if ($QueueLimit -gt 0) {
        $TriageArguments += @("--queue-limit", [string]$QueueLimit)
    }
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

if ($Profile -ne "survey" -and -not (Test-Path -LiteralPath $CheckpointPath -PathType Leaf)) {
    throw "The $Profile profile requires an existing screened campaign checkpoint."
}

Push-Location $PackageRoot
try {
    $Command = if (Test-Path -LiteralPath $CheckpointPath -PathType Leaf) {
        "campaign-resume"
    }
    else {
        "campaign-run"
    }
    $CampaignPlan = Invoke-M02Command -Arguments @(
        "campaign-plan",
        "--profile",
        $Profile,
        $Selection
    ) | ConvertFrom-Json
    if (
        $null -eq $CampaignPlan -or
        $null -eq $CampaignPlan.role_counts -or
        $null -eq $CampaignPlan.leaf_count
    ) {
        throw "M02 campaign plan did not report role and leaf counts."
    }
    Write-Host "M02 B′ campaign" -ForegroundColor Cyan
    Write-Host ("    Primary : {0}" -f $CampaignPlan.role_counts.primary)
    Write-Host ("    Control : {0}" -f $CampaignPlan.role_counts.control)
    Write-Host ("    Deep    : {0}" -f $CampaignPlan.role_counts.deep)
    Write-Host ("    Total   : {0}" -f $CampaignPlan.leaf_count)
    Write-Host "M02 live progress status:" -ForegroundColor Cyan
    Write-Host "    $CheckpointPath.status.json"
    Invoke-M02Command -Arguments (@(
        $Command,
        $Selection,
        "--checkpoint",
        $Checkpoint,
        "--progress",
        $Progress,
        "--profile",
        $Profile
    ) + $CalibrationArguments + $TriageArguments)
    Invoke-M02Command -Arguments @(
        "campaign-validate",
        $Selection,
        "--checkpoint",
        $Checkpoint,
        "--profile",
        $Profile,
        "--full"
    )
}
finally {
    Pop-Location
}

Write-Host "M02 campaign checkpoint is complete and structurally valid:" -ForegroundColor Green
Write-Host "    $CheckpointPath"
