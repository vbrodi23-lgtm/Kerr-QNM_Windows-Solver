param(
    [string]$Selection = ".\examples\m02-campaign.json",
    [string]$Checkpoint = ".\m02-output\m02-campaign-checkpoint.json",
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

function Invoke-M02Command([string[]]$Arguments) {
    & (Join-Path $PackageRoot "solver.ps1") @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "M02 command failed with exit code $LASTEXITCODE."
    }
}

if ($SkipBootstrap -and $RebuildRuntime) {
    throw "-SkipBootstrap and -RebuildRuntime cannot be used together."
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

Push-Location $PackageRoot
try {
    $Command = if (Test-Path -LiteralPath $CheckpointPath -PathType Leaf) {
        "campaign-resume"
    }
    else {
        "campaign-run"
    }
    Write-Host "M02 live progress status:" -ForegroundColor Cyan
    Write-Host "    $CheckpointPath.status.json"
    Invoke-M02Command -Arguments @(
        $Command,
        $Selection,
        "--checkpoint",
        $Checkpoint,
        "--progress",
        $Progress
    )
    Invoke-M02Command -Arguments @(
        "campaign-validate",
        $Selection,
        "--checkpoint",
        $Checkpoint,
        "--full"
    )
}
finally {
    Pop-Location
}

Write-Host "M02 campaign checkpoint is complete and structurally valid:" -ForegroundColor Green
Write-Host "    $CheckpointPath"
