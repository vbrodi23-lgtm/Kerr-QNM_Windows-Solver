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

function Assert-HexDigest {
    param([object]$Value, [string]$Subject)
    if (($Value -isnot [string]) -or $Value -notmatch '^[0-9a-f]{64}$') {
        throw "$Subject is missing or is not a lowercase SHA-256 digest."
    }
}

function Assert-FiniteNumberText {
    param([object]$Value, [string]$Subject, [switch]$Optional)
    if ($null -eq $Value) {
        if ($Optional) { return }
        throw "$Subject is missing."
    }
    $Parsed = 0.0
    $Style = [Globalization.NumberStyles]::Float
    $Culture = [Globalization.CultureInfo]::InvariantCulture
    if (-not [double]::TryParse(
        [string]$Value, $Style, $Culture, [ref]$Parsed
    )) {
        throw "$Subject is not numeric."
    }
    if ([double]::IsNaN($Parsed) -or [double]::IsInfinity($Parsed)) {
        throw "$Subject is nonfinite."
    }
}

function Assert-CalibrationEventIdentity {
    param([object]$Event)
    if ($null -eq $Event.identity) {
        throw "Calibration event '$($Event.kind)' has no identity."
    }
    Assert-HexDigest $Event.identity.source_sha256 "Calibration source SHA"
    Assert-HexDigest $Event.identity.manifest_sha256 "Calibration manifest SHA"
    Assert-HexDigest $Event.identity.policy_sha256 "Calibration policy SHA"
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

# The bootstrap writes one runtime receipt, `python-runtime.json`, and records
# the Julia runtime inside it under `julia_runtime`. This script previously
# looked for an `m02-runtime.json` carrying `julia`/`project`/`depot` at the top
# level. No such file is written by anything in this repository and no such
# shape exists, so the harness could not run at all -- it failed on its own
# preflight before reaching a single determinant. `solver.ps1`,
# `julia_response_backend.py` and `gsn_cache_producer.py` all read the real
# receipt; this was the one consumer that had invented its own.
$ReceiptPath = Join-Path $ResolvedRuntimeRoot "python-runtime.json"
if (-not (Test-Path -LiteralPath $ReceiptPath -PathType Leaf)) {
    throw "M02 runtime receipt is absent: $ReceiptPath"
}
$Receipt = Get-Content -LiteralPath $ReceiptPath -Raw | ConvertFrom-Json
$JuliaRuntime = $Receipt.julia_runtime
if ($null -eq $JuliaRuntime -or $JuliaRuntime.requested -ne $true) {
    throw ("M02 Julia runtime is not provisioned; run " +
        ".\runtime\bootstrap.ps1 -WithM02")
}
$JuliaExecutable = [string]$JuliaRuntime.executable
$JuliaProject = [string]$JuliaRuntime.project
$JuliaDepot = [string]$JuliaRuntime.depot
foreach ($Field in @(
    @{ Name = "executable"; Value = $JuliaExecutable },
    @{ Name = "project"; Value = $JuliaProject },
    @{ Name = "depot"; Value = $JuliaDepot }
)) {
    if ([string]::IsNullOrWhiteSpace($Field.Value)) {
        throw "M02 runtime receipt julia_runtime is missing '$($Field.Name)'."
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
$Events = New-Object System.Collections.Generic.List[object]
Push-Location $PackageRoot
try {
    & $JuliaExecutable --startup-file=no --history-file=no `
        --project=$JuliaProject $Harness $PrecisionDigits 2>&1 |
        ForEach-Object {
            $Line = [string]$_
            if ($Line.StartsWith($CalibrationPrefix)) {
                $Payload = $Line.Substring($CalibrationPrefix.Length)
                try {
                    $Event = $Payload | ConvertFrom-Json
                }
                catch {
                    throw "Calibration harness emitted malformed JSON: $Payload"
                }
                $Lines.Add($Payload) | Out-Null
                $Events.Add($Event) | Out-Null
                Write-Host ("    {0}" -f $Event.kind) -ForegroundColor DarkCyan
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

if ($CalibrationExitCode -ne 0) {
    throw "Horizon control calibration failed with exit code $CalibrationExitCode."
}
if ($Lines.Count -eq 0) {
    throw "Horizon control calibration produced no receipt events."
}

$RequiredKinds = @(
    "calibration_started",
    "control_rung_measured",
    "control_response_measured",
    "derivative_ladder_measured",
    "calibration_completed"
)
foreach ($Kind in $RequiredKinds) {
    if (-not ($Events | Where-Object { $_.kind -eq $Kind })) {
        throw "Horizon control calibration omitted required event '$Kind'."
    }
}

$RungLabels = New-Object 'System.Collections.Generic.HashSet[string]'
foreach ($Event in $Events) {
    Assert-CalibrationEventIdentity $Event
    if ($Event.kind -ne "control_rung_measured") { continue }
    $Row = $Event.payload
    if ([string]::IsNullOrWhiteSpace([string]$Row.label)) {
        throw "Calibration control rung has no label."
    }
    if (-not $RungLabels.Add([string]$Row.label)) {
        throw "Calibration contains duplicate rung label '$($Row.label)'."
    }
    if ($Row.succeeded -eq $true) {
        $Evidence = $Row.determinant_error
        if ($null -eq $Evidence) {
            throw "Successful rung '$($Row.label)' has no determinant-error evidence."
        }
        Assert-FiniteNumberText $Evidence.central_determinant_re `
            "Rung '$($Row.label)' determinant real part"
        Assert-FiniteNumberText $Evidence.central_determinant_im `
            "Rung '$($Row.label)' determinant imaginary part"
        Assert-FiniteNumberText $Evidence.endpoint_disagreement_abs `
            "Rung '$($Row.label)' endpoint discrepancy"
        Assert-FiniteNumberText $Evidence.control_disagreement_abs `
            "Rung '$($Row.label)' control discrepancy" -Optional
        Assert-FiniteNumberText $Evidence.equivalence_disagreement_abs `
            "Rung '$($Row.label)' equivalence discrepancy" -Optional
        Assert-FiniteNumberText $Evidence.precision_disagreement_abs `
            "Rung '$($Row.label)' precision discrepancy" -Optional
        Assert-FiniteNumberText $Evidence.safety_factor `
            "Rung '$($Row.label)' determinant safety factor"
        Assert-FiniteNumberText $Evidence.numerical_error_abs `
            "Rung '$($Row.label)' determinant absolute error"
        if ([string]::IsNullOrWhiteSpace([string]$Evidence.error_model_id)) {
            throw "Successful rung '$($Row.label)' has no error-model identity."
        }
    }
    else {
        if (
            $null -eq $Row.failure -or
            [string]::IsNullOrWhiteSpace([string]$Row.failure.failure_code)
        ) {
            throw "Failed rung '$($Row.label)' has no typed failure code."
        }
    }
}

Set-Content -LiteralPath $ResolvedOutputPath -Value $Lines -Encoding UTF8

Write-Host "Horizon control calibration receipt written:" -ForegroundColor Green
Write-Host "    $ResolvedOutputPath"
Write-Host "Review this native evidence before replacing the UNMEASURED profile status."
