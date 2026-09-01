[CmdletBinding(PositionalBinding = $false)]
param(
    [string]$Selection = ".\examples\m03-spectral-fields.json",
    [string]$Handoff = ".\m02-output\m02-m03-handoff.json",
    [string]$Checkpoint = ".\m03-output\m03-spectral-state-checkpoint.json",
    [ValidateSet("run", "validate", "admit")]
    [string]$Profile = "run",
    [switch]$NewCampaign,
    [switch]$SkipBootstrap,
    [switch]$RebuildRuntime,
    [switch]$PortableRuntime,
    [string]$RuntimeRoot,
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

function Resolve-PackagePath([string]$Path) {
    if ([IO.Path]::IsPathRooted($Path)) {
        return [IO.Path]::GetFullPath($Path)
    }
    return [IO.Path]::GetFullPath((Join-Path $PackageRoot $Path))
}

function Invoke-M03Command([string[]]$Arguments) {
    & (Join-Path $PackageRoot "solver.ps1") @Arguments
    $Code = $LASTEXITCODE
    if ($Code -eq -1073741510 -or $Code -eq 3221225786) {
        $Code = 130
    }
    if ($Code -eq 130) {
        exit 130
    }
    if ($Code -ne 0) {
        throw "M03 command failed with exit code $Code."
    }
}

if ($SkipBootstrap -and $RebuildRuntime) {
    throw "-SkipBootstrap and -RebuildRuntime cannot be used together."
}
if ($NewCampaign -and $Profile -ne "run") {
    throw "-NewCampaign applies only to -Profile run."
}

$SelectionPath = Resolve-PackagePath $Selection
$HandoffPath = Resolve-PackagePath $Handoff
$CheckpointPath = Resolve-PackagePath $Checkpoint
$M02SelectionPath = Resolve-PackagePath ".\examples\m02-campaign.json"
$M02CheckpointPath = Resolve-PackagePath ".\m02-output\m02-campaign-checkpoint.json"
if (-not (Test-Path -LiteralPath $SelectionPath -PathType Leaf)) {
    throw "M03 selection is absent: $SelectionPath"
}

# Existing handoff and manual reconstruction both use the same authenticated
# Python boundary.  This launcher never invokes m02.ps1 and can never start an
# M02 numerical campaign.
if (Test-Path -LiteralPath $HandoffPath -PathType Leaf) {
    Invoke-M03Command @("m03-handoff-validate", $HandoffPath) | Out-Null
}
else {
    if (-not (Test-Path -LiteralPath $M02CheckpointPath -PathType Leaf)) {
        throw (
            "M03 cannot start because the handoff is absent and completed M02 " +
            "terminal evidence is missing: $M02CheckpointPath"
        )
    }
    if (-not (Test-Path -LiteralPath $M02SelectionPath -PathType Leaf)) {
        throw "M03 cannot authenticate M02 because its frozen selection is absent: $M02SelectionPath"
    }
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $HandoffPath) | Out-Null
    Invoke-M03Command @(
        "m03-handoff-build", $M02SelectionPath,
        "--checkpoint", $M02CheckpointPath,
        "--output", $HandoffPath
    ) | Out-Null
}

$CheckpointExists = Test-Path -LiteralPath $CheckpointPath -PathType Leaf
if ($NewCampaign -and $CheckpointExists) {
    throw "-NewCampaign refuses an existing checkpoint: $CheckpointPath"
}
if ($Profile -in @("validate", "admit") -and -not $CheckpointExists) {
    throw "M03 $Profile requires an existing checkpoint: $CheckpointPath"
}
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $CheckpointPath) | Out-Null

# Validation and admission are checkpoint-only operations and intentionally do
# not bootstrap or launch Julia.
if ($Profile -eq "run" -and -not $SkipBootstrap) {
    $BootstrapParameters = @{
        WithM03 = $true
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
        throw "M03 runtime bootstrap failed with exit code $LASTEXITCODE."
    }
}

$Command = "m03-$Profile"
$Arguments = @(
    $Command,
    $SelectionPath,
    "--handoff", $HandoffPath,
    "--checkpoint", $CheckpointPath
)
if ($Profile -eq "run") {
    $RuntimeReceiptPath = Join-Path $ResolvedRuntimeRoot "python-runtime.json"
    if (-not (Test-Path -LiteralPath $RuntimeReceiptPath -PathType Leaf)) {
        throw "M03 installed runtime receipt is absent: $RuntimeReceiptPath"
    }
    $RuntimeReceipt = Get-Content -LiteralPath $RuntimeReceiptPath -Raw | ConvertFrom-Json
    $M03Runtime = $RuntimeReceipt.julia_runtime.m03
    if ($null -eq $M03Runtime -or [string]::IsNullOrWhiteSpace([string]$M03Runtime.contract_sha256)) {
        throw "M03 runtime is not staged; run .\runtime\bootstrap.ps1 -WithM03"
    }
    $Arguments += @(
        "--runtime-receipt", $RuntimeReceiptPath,
        "--source-revision", ([string]$M03Runtime.contract_sha256).ToLowerInvariant()
    )
    if ($NewCampaign) {
        $Arguments += "--new-campaign"
    }
}

Write-Host "M03 spectral-state campaign" -ForegroundColor Cyan
Write-Host ("    Profile             : {0}" -f $Profile)
Write-Host ("    Handoff             : {0}" -f $HandoffPath)
Write-Host ("    Checkpoint          : {0}" -f $CheckpointPath)
Write-Host ("    Startup             : {0}" -f $(if ($CheckpointExists) { "resume" } else { "cold" }))
Write-Host ("    Worker model        : one persistent Julia process")
Write-Host ("    Progress            : {0}" -f $Progress)

Invoke-M03Command $Arguments
