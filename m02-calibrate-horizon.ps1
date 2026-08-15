param(
    [ValidateSet(80, 120)]
    [int]$PrecisionDigits = 80,
    [string]$OutputPath = ".\m02-output\horizon-control-calibration.jsonl",
    [switch]$SkipBootstrap,
    [switch]$PortableRuntime,
    [string]$RuntimeRoot
)

# Measure how the horizon determinant responds to its numerical controls.
#
# This exists because the previous 120-digit controls were never measured. They
# came from a formula over the stored digit count -- 10^-(digits - 18) -- which
# demanded a 1e-102 root target and handed the same tolerance to the coordinate
# map. Leaf 13's coordinate leg then pinned at 8.1e-17 steps: 2,000,002 RHS
# evaluations and 87.8 s to cover 1.01e-11 of a 5000 span.
#
# Replacing one guessed table with another would not be progress, so the profile
# committed to the repository is expected to carry the receipt this script
# produces. The harness reports; the choice of profile stays a human decision.
#
# Evidence ceiling: numerical response and internal consistency only. This is
# not a mathematical validation of the GSN representation and it does not open
# the production-readiness gate.

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
$PackageRoot = $PSScriptRoot
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

$ReceiptPath = Join-Path $ResolvedRuntimeRoot "m02-runtime.json"
if (-not (Test-Path -LiteralPath $ReceiptPath -PathType Leaf)) {
    throw "M02 runtime receipt is absent: $ReceiptPath"
}
$Receipt = Get-Content -LiteralPath $ReceiptPath -Raw | ConvertFrom-Json
$JuliaExecutable = [string]$Receipt.julia
$JuliaProject = [string]$Receipt.project
$JuliaDepot = [string]$Receipt.depot
foreach ($Field in @(
    @{ Name = "julia"; Value = $JuliaExecutable },
    @{ Name = "project"; Value = $JuliaProject },
    @{ Name = "depot"; Value = $JuliaDepot }
)) {
    if ([string]::IsNullOrWhiteSpace($Field.Value)) {
        throw "M02 runtime receipt is missing '$($Field.Name)'."
    }
}

$ResolvedOutputPath = if ([IO.Path]::IsPathRooted($OutputPath)) {
    [IO.Path]::GetFullPath($OutputPath)
}
else {
    [IO.Path]::GetFullPath((Join-Path $PackageRoot $OutputPath))
}
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $ResolvedOutputPath) |
    Out-Null

$Harness = Join-Path $PackageRoot "tools\calibrate_leaf13_horizon_controls.jl"
if (-not (Test-Path -LiteralPath $Harness -PathType Leaf)) {
    throw "Horizon control calibration harness is absent: $Harness"
}

Write-Host "Horizon numerical-control calibration" -ForegroundColor Cyan
Write-Host ("    Precision digits : {0}" -f $PrecisionDigits)
Write-Host ("    Receipt          : {0}" -f $ResolvedOutputPath)
Write-Host "    Evidence ceiling : numerical response only, not math validation"

$env:JULIA_DEPOT_PATH = $JuliaDepot
$env:JULIA_PKG_OFFLINE = "true"
$env:KERR_QNM_PROGRESS = "0"

$CalibrationPrefix = "@@LEAF13_HORIZON_CONTROL_CALIBRATION@@"
$Lines = New-Object System.Collections.Generic.List[string]
Push-Location $PackageRoot
try {
    & $JuliaExecutable --startup-file=no --history-file=no `
        --project=$JuliaProject $Harness $PrecisionDigits 2>&1 |
        ForEach-Object {
            $Line = [string]$_
            if ($Line.StartsWith($CalibrationPrefix)) {
                $Payload = $Line.Substring($CalibrationPrefix.Length)
                $Lines.Add($Payload) | Out-Null
                try {
                    $Event = $Payload | ConvertFrom-Json
                    Write-Host ("    {0}" -f $Event.kind) -ForegroundColor DarkCyan
                }
                catch {
                    # A line that does not parse is still retained verbatim in
                    # the receipt; the run is not failed for a display problem.
                    Write-Host "    (unparsed calibration event)" -ForegroundColor DarkYellow
                }
            }
            else {
                Write-Host $Line
            }
        }
    $CalibrationExitCode = $LASTEXITCODE
}
finally {
    Pop-Location
}

Set-Content -LiteralPath $ResolvedOutputPath -Value $Lines -Encoding UTF8

if ($CalibrationExitCode -ne 0) {
    throw "Horizon control calibration failed with exit code $CalibrationExitCode."
}
if ($Lines.Count -eq 0) {
    throw "Horizon control calibration produced no receipt events."
}

Write-Host "Horizon control calibration receipt written:" -ForegroundColor Green
Write-Host "    $ResolvedOutputPath"
Write-Host "Select a control profile from this evidence and commit it with the receipt."
