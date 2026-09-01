[CmdletBinding(PositionalBinding = $false)]
param(
    [ValidateSet("dry-run", "migrate", "resume")]
    [string]$Profile = "dry-run",
    [string]$Selection = ".\examples\m02-campaign.json",
    [string]$Checkpoint = ".\m02-output\m02-campaign-checkpoint.json",
    [string]$Binary64Lock,
    [string]$MigrationOutput,
    [string]$MigrationReceipt,
    [string]$MigrationSnapshot,
    [string]$Backup,
    [string]$SolvedLeafStore,
    [string]$FailureReceiptSha256,
    [string]$RepairCommit,
    [string]$ResolutionReason,
    [switch]$SkipBootstrap,
    [switch]$PortableRuntime,
    [string]$RuntimeRoot,
    [ValidateSet("quiet", "normal", "trace")]
    [string]$Progress = "normal"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
$PackageRoot = $PSScriptRoot

function Resolve-PackagePath([string]$Path) {
    if ([IO.Path]::IsPathRooted($Path)) {
        return [IO.Path]::GetFullPath($Path)
    }
    return [IO.Path]::GetFullPath((Join-Path $PackageRoot $Path))
}

function Invoke-Solver([string[]]$Arguments) {
    & (Join-Path $PackageRoot "solver.ps1") @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "M02 repair command failed with exit code $LASTEXITCODE."
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

$SelectionPath = Resolve-PackagePath $Selection
$CheckpointPath = Resolve-PackagePath $Checkpoint
$LockPath = if ([string]::IsNullOrWhiteSpace($Binary64Lock)) {
    "$CheckpointPath.binary64-lock.json"
}
else {
    Resolve-PackagePath $Binary64Lock
}
if (-not (Test-Path -LiteralPath $SelectionPath -PathType Leaf)) {
    throw "M02 selection is absent: $SelectionPath"
}
if (-not (Test-Path -LiteralPath $CheckpointPath -PathType Leaf)) {
    throw "M02 checkpoint is absent: $CheckpointPath"
}
if (-not (Test-Path -LiteralPath $LockPath -PathType Leaf)) {
    throw "M02 Binary64 lock is absent: $LockPath"
}

if ($Profile -eq "resume") {
    $ResumeParameters = @{
        Selection = $SelectionPath
        Checkpoint = $CheckpointPath
        Profile = "survey"
        SurveyPass = "promoted"
        Progress = $Progress
        SkipBootstrap = [bool]$SkipBootstrap
        PortableRuntime = [bool]$PortableRuntime
    }
    if (-not [string]::IsNullOrWhiteSpace($RuntimeRoot)) {
        $ResumeParameters.RuntimeRoot = $RuntimeRoot
    }
    & (Join-Path $PackageRoot "m02.ps1") @ResumeParameters
    exit $LASTEXITCODE
}

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
    if ($LASTEXITCODE -ne 0) {
        throw "M02 runtime bootstrap failed with exit code $LASTEXITCODE."
    }
}

$OutputPath = if (-not [string]::IsNullOrWhiteSpace($MigrationOutput)) {
    Resolve-PackagePath $MigrationOutput
}
elseif ($Profile -eq "migrate") {
    $CheckpointPath
}
else {
    "$CheckpointPath.endpoint-recovery-dry-run.json"
}
$ReceiptPath = if (-not [string]::IsNullOrWhiteSpace($MigrationReceipt)) {
    Resolve-PackagePath $MigrationReceipt
}
elseif ($Profile -eq "migrate") {
    "$CheckpointPath.endpoint-recovery-migration.json"
}
else {
    "$CheckpointPath.endpoint-recovery-dry-run.receipt.json"
}

if ($Profile -eq "migrate") {
    if (
        [string]::IsNullOrWhiteSpace($FailureReceiptSha256) -or
        [string]::IsNullOrWhiteSpace($RepairCommit) -or
        [string]::IsNullOrWhiteSpace($ResolutionReason)
    ) {
        throw "Live migration requires failure receipt SHA-256, repair commit, and resolution reason."
    }
    $BackupPath = if ([string]::IsNullOrWhiteSpace($Backup)) {
        "$CheckpointPath.pre-endpoint-recovery-migration.json"
    }
    else {
        Resolve-PackagePath $Backup
    }
    if (Test-Path -LiteralPath $BackupPath) {
        throw "M02 repair refuses an existing backup path: $BackupPath"
    }
    Copy-Item -LiteralPath $CheckpointPath -Destination $BackupPath
    $SourceDigest = Get-Sha256 $CheckpointPath
    $BackupDigest = Get-Sha256 $BackupPath
    if ($SourceDigest -ne $BackupDigest) {
        throw "M02 checkpoint backup authentication failed."
    }
}

$Arguments = @(
    "campaign-migrate-endpoint-recovery",
    $SelectionPath,
    "--checkpoint", $CheckpointPath,
    "--binary64-lock", $LockPath,
    "--output", $OutputPath,
    "--receipt", $ReceiptPath
)
if (-not [string]::IsNullOrWhiteSpace($SolvedLeafStore)) {
    $Arguments += @("--solved-leaf-store", (Resolve-PackagePath $SolvedLeafStore))
}
if ($Profile -eq "migrate") {
    $Arguments += "--replace-source"
}
Invoke-Solver -Arguments $Arguments

if ($Profile -eq "migrate") {
    $SnapshotPath = if ([string]::IsNullOrWhiteSpace($MigrationSnapshot)) {
        "$CheckpointPath.endpoint-recovery-migrated.json"
    }
    else {
        Resolve-PackagePath $MigrationSnapshot
    }
    if (Test-Path -LiteralPath $SnapshotPath) {
        throw "M02 repair refuses an existing migration snapshot: $SnapshotPath"
    }
    Copy-Item -LiteralPath $CheckpointPath -Destination $SnapshotPath
    $SnapshotDigest = Get-Sha256 $SnapshotPath
    $Migration = Get-Content -LiteralPath $ReceiptPath -Raw | ConvertFrom-Json
    if (
        $SnapshotDigest -ne [string]$Migration.output_checkpoint_sha256 -or
        $SnapshotDigest -ne (Get-Sha256 $CheckpointPath)
    ) {
        throw "M02 migrated-checkpoint snapshot authentication failed."
    }
    $ResolutionParameters = @{
        Selection = $SelectionPath
        Checkpoint = $CheckpointPath
        Profile = "resolve-system-failure"
        FailureReceiptSha256 = $FailureReceiptSha256
        RepairCommit = $RepairCommit
        ResolutionReason = $ResolutionReason
        SkipBootstrap = $true
        PortableRuntime = [bool]$PortableRuntime
    }
    if (-not [string]::IsNullOrWhiteSpace($RuntimeRoot)) {
        $ResolutionParameters.RuntimeRoot = $RuntimeRoot
    }
    & (Join-Path $PackageRoot "m02.ps1") @ResolutionParameters
    if ($LASTEXITCODE -ne 0) {
        throw "Superseding system-failure resolution failed."
    }
}
