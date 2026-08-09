param(
    [string]$Selection = ".\examples\m02-campaign.json",
    [string]$Checkpoint = ".\m02-output\m02-campaign-checkpoint.json",
    [switch]$SkipBootstrap,
    [switch]$RebuildRuntime
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
$PackageRoot = $PSScriptRoot

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
    $BootstrapArguments = @("-WithM02")
    if ($RebuildRuntime) {
        $BootstrapArguments += "-Force"
    }
    & (Join-Path $PackageRoot "runtime\bootstrap.ps1") @BootstrapArguments
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
    Invoke-M02Command -Arguments @(
        $Command,
        $Selection,
        "--checkpoint",
        $Checkpoint
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
