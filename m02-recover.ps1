[CmdletBinding()]
param(
    [string]$Selection = ".\examples\m02-campaign.json",
    [string]$OutputCheckpoint = ".\m02-output\m02-campaign-checkpoint.schema11.candidate.json",
    [string]$Receipt = ".\m02-output\m02-recovery-receipt.json",
    [string[]]$SourceCheckpoint = @(),
    [string[]]$SolvedLeafStore = @(),
    [string[]]$RootReadoutStore = @(),
    [string]$Oracle,
    [switch]$CommitCutover,
    [string]$CandidateCheckpoint,
    [string]$RecoveryReceipt,
    [string]$ProductionCheckpoint,
    [switch]$SkipBootstrap,
    [switch]$RebuildRuntime,
    [switch]$PortableRuntime,
    [string]$RuntimeRoot
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
$PackageRoot = $PSScriptRoot
. (Join-Path $PackageRoot "runtime\resolve-runtime-root.ps1")
$ResolvedRuntimeRoot = Resolve-KerrQnmRuntimeRoot -PackageRoot $PackageRoot `
    -PortableRuntime:$PortableRuntime -OverrideRoot $RuntimeRoot
Set-KerrQnmRuntimeRoot $ResolvedRuntimeRoot

function Resolve-OperatorPath([string]$Value) {
    if ([string]::IsNullOrWhiteSpace($Value)) {
        throw "A required path was empty."
    }
    if ([IO.Path]::IsPathRooted($Value)) {
        return [IO.Path]::GetFullPath($Value)
    }
    return [IO.Path]::GetFullPath((Join-Path $PackageRoot $Value))
}

function Invoke-RecoveryCommand([string[]]$Arguments) {
    & (Join-Path $PackageRoot "solver.ps1") @Arguments
    $CommandExitCode = $LASTEXITCODE
    if ($CommandExitCode -ne 0) {
        throw "Recovery command failed with exit code $CommandExitCode."
    }
}

if ($SkipBootstrap -and $RebuildRuntime) {
    throw "-SkipBootstrap and -RebuildRuntime cannot be used together."
}
if (-not $SkipBootstrap) {
    $BootstrapParameters = @{
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
        throw "Recovery runtime bootstrap failed with exit code $LASTEXITCODE."
    }
}

$SelectionPath = Resolve-OperatorPath $Selection
if (-not (Test-Path -LiteralPath $SelectionPath -PathType Leaf)) {
    throw "M02 selection is absent: $SelectionPath"
}

if (-not $CommitCutover) {
    $OutputPath = Resolve-OperatorPath $OutputCheckpoint
    $ReceiptPath = Resolve-OperatorPath $Receipt
    if (Test-Path -LiteralPath $OutputPath) {
        throw "Recovery candidate already exists: $OutputPath"
    }
    if (Test-Path -LiteralPath $ReceiptPath) {
        throw "Recovery receipt already exists: $ReceiptPath"
    }
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $OutputPath) |
        Out-Null
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $ReceiptPath) |
        Out-Null

    $Arguments = @(
        "campaign-recover",
        $SelectionPath,
        "--output", $OutputPath,
        "--receipt", $ReceiptPath
    )
    foreach ($Path in $SourceCheckpoint) {
        $Arguments += @("--source-checkpoint", (Resolve-OperatorPath $Path))
    }
    foreach ($Path in $SolvedLeafStore) {
        $Arguments += @("--solved-leaf-store", (Resolve-OperatorPath $Path))
    }
    foreach ($Path in $RootReadoutStore) {
        $Arguments += @("--root-readout-store", (Resolve-OperatorPath $Path))
    }
    if (-not [string]::IsNullOrWhiteSpace($Oracle)) {
        $Arguments += @("--oracle", (Resolve-OperatorPath $Oracle))
    }

    Push-Location $PackageRoot
    try {
        Invoke-RecoveryCommand -Arguments $Arguments
    }
    finally {
        Pop-Location
    }
    Write-Host "Recovery candidate written:" -ForegroundColor Green
    Write-Host "    $OutputPath"
    Write-Host "Recovery receipt written:" -ForegroundColor Green
    Write-Host "    $ReceiptPath"
    exit 0
}

if (
    [string]::IsNullOrWhiteSpace($CandidateCheckpoint) -or
    [string]::IsNullOrWhiteSpace($RecoveryReceipt) -or
    [string]::IsNullOrWhiteSpace($ProductionCheckpoint)
) {
    throw "-CommitCutover requires -CandidateCheckpoint, -RecoveryReceipt, and -ProductionCheckpoint."
}

$CandidatePath = Resolve-OperatorPath $CandidateCheckpoint
$RecoveryReceiptPath = Resolve-OperatorPath $RecoveryReceipt
$ProductionPath = Resolve-OperatorPath $ProductionCheckpoint
foreach ($RequiredPath in @($CandidatePath, $RecoveryReceiptPath, $ProductionPath)) {
    if (-not (Test-Path -LiteralPath $RequiredPath -PathType Leaf)) {
        throw "Cutover input is absent: $RequiredPath"
    }
}
if ($CandidatePath -eq $ProductionPath) {
    throw "The recovery candidate and production checkpoint must be different files."
}

Push-Location $PackageRoot
try {
    Invoke-RecoveryCommand -Arguments @(
        "campaign-recovery-validate",
        $SelectionPath,
        "--checkpoint", $CandidatePath,
        "--receipt", $RecoveryReceiptPath
    )
}
finally {
    Pop-Location
}

$ProductionDirectory = Split-Path -Parent $ProductionPath
$Timestamp = [DateTime]::UtcNow.ToString("yyyyMMdd-HHmmss-fffffff")
$BackupPath = Join-Path $ProductionDirectory (
    "m02-campaign-checkpoint.pre-pr65-recovery.{0}.json" -f $Timestamp
)
if (Test-Path -LiteralPath $BackupPath) {
    throw "Recovery backup path already exists: $BackupPath"
}
[IO.File]::Copy($ProductionPath, $BackupPath, $false)

$OriginalLength = (Get-Item -LiteralPath $ProductionPath).Length
$BackupLength = (Get-Item -LiteralPath $BackupPath).Length
$OriginalHash = (Get-FileHash -LiteralPath $ProductionPath -Algorithm SHA256).Hash.ToLowerInvariant()
$BackupHash = (Get-FileHash -LiteralPath $BackupPath -Algorithm SHA256).Hash.ToLowerInvariant()
if ($OriginalLength -ne $BackupLength -or $OriginalHash -ne $BackupHash) {
    throw "The permanent pre-recovery backup failed byte-for-byte verification."
}

$CandidateHash = (Get-FileHash -LiteralPath $CandidatePath -Algorithm SHA256).Hash.ToLowerInvariant()
$StagePath = Join-Path $ProductionDirectory (
    ".m02-pr65-cutover-{0}.tmp" -f ([Guid]::NewGuid().ToString("N"))
)
try {
    [IO.File]::Copy($CandidatePath, $StagePath, $false)
    $StageStream = [IO.File]::Open(
        $StagePath,
        [IO.FileMode]::Open,
        [IO.FileAccess]::ReadWrite,
        [IO.FileShare]::None
    )
    try {
        $StageStream.Flush($true)
    }
    finally {
        $StageStream.Dispose()
    }
    [IO.File]::Replace($StagePath, $ProductionPath, $null)
}
finally {
    if (Test-Path -LiteralPath $StagePath) {
        Remove-Item -LiteralPath $StagePath -Force
    }
}

$InstalledHash = (Get-FileHash -LiteralPath $ProductionPath -Algorithm SHA256).Hash.ToLowerInvariant()
if ($InstalledHash -ne $CandidateHash) {
    throw "The installed production checkpoint does not match the validated candidate."
}

$RecoveryReceiptHash = (
    Get-FileHash -LiteralPath $RecoveryReceiptPath -Algorithm SHA256
).Hash.ToLowerInvariant()
$CutoverReceiptPath = "$RecoveryReceiptPath.cutover.json"
if (Test-Path -LiteralPath $CutoverReceiptPath) {
    throw "Cutover receipt already exists: $CutoverReceiptPath"
}
$CutoverReceipt = [ordered]@{
    schema = "windows-solver.campaign-recovery-cutover/v1"
    selection_path = $SelectionPath
    old_production_sha256 = $OriginalHash
    backup_path = $BackupPath
    backup_sha256 = $BackupHash
    candidate_path = $CandidatePath
    candidate_sha256 = $CandidateHash
    recovery_receipt_path = $RecoveryReceiptPath
    recovery_receipt_sha256 = $RecoveryReceiptHash
    production_path = $ProductionPath
    installed_sha256 = $InstalledHash
    atomic_replace = $true
}
$CutoverJson = $CutoverReceipt | ConvertTo-Json -Depth 8 -Compress
[IO.File]::WriteAllText($CutoverReceiptPath, $CutoverJson + "`n", [Text.UTF8Encoding]::new($false))

Write-Host "Recovery cutover completed." -ForegroundColor Green
Write-Host "    Production: $ProductionPath"
Write-Host "    Backup:     $BackupPath"
Write-Host "    Receipt:    $CutoverReceiptPath"
