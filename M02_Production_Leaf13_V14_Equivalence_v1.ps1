[CmdletBinding(PositionalBinding = $false)]
param(
    [string]$OutputRoot = ".\m02-output\leaf13-production-v14-equivalence-v1",
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

function Assert-ProductionCondition {
    param([bool]$Condition, [string]$Message)
    if (-not $Condition) {
        throw "M02 production v1.4 equivalence assertion failed: $Message"
    }
}

function Invoke-ProductionSolver {
    param([string[]]$Arguments)
    & (Join-Path $PackageRoot "solver.ps1") @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Production solver command failed with exit code $LASTEXITCODE."
    }
}

function Read-StrictJson {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "Expected production evidence is absent: $Path"
    }
    return Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json
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

$ResolvedOutputRoot = if ([IO.Path]::IsPathRooted($OutputRoot)) {
    [IO.Path]::GetFullPath($OutputRoot)
}
else {
    [IO.Path]::GetFullPath((Join-Path $PackageRoot $OutputRoot))
}
$SelectionPath = Join-Path $ResolvedOutputRoot "leaf13-selection.json"
$CheckpointPath = Join-Path $ResolvedOutputRoot "leaf13-checkpoint.json"
$ReportPath = Join-Path $ResolvedOutputRoot "leaf13-v14-equivalence-report.json"
$TracePath = Join-Path $ResolvedOutputRoot `
    "leaf13-checkpoint.json.progress\leaf-000001.jsonl"

foreach ($Path in @($SelectionPath, $CheckpointPath, $ReportPath)) {
    if (Test-Path -LiteralPath $Path) {
        throw "Cold production equivalence run refuses existing output: $Path"
    }
}
New-Item -ItemType Directory -Force -Path $ResolvedOutputRoot | Out-Null

$OriginalLocalAppData = $env:LOCALAPPDATA
$OriginalReadoutCacheRoot = $env:KERR_QNM_ROOT_READOUT_CACHE_ROOT
try {
    # Isolate operational caches without altering production code or requests.
    $env:LOCALAPPDATA = Join-Path $ResolvedOutputRoot "operator-local-app-data"
    $env:KERR_QNM_ROOT_READOUT_CACHE_ROOT = Join-Path `
        $ResolvedOutputRoot "root-readout-cache"
    Set-KerrQnmRuntimeRoot $ResolvedRuntimeRoot

    Push-Location $PackageRoot
    try {
        $PlanJson = & (Join-Path $PackageRoot "solver.ps1") `
            "campaign-plan" ".\examples\m02-campaign.json"
        if ($LASTEXITCODE -ne 0) {
            throw "Production campaign-plan failed with exit code $LASTEXITCODE."
        }
        $Plan = ($PlanJson -join "`n") | ConvertFrom-Json
        $Targets = @(
            $Plan.campaign.leaves | Where-Object {
                $_.role -eq "primary" -and
                $_.mode_label -eq "221" -and
                $_.mechanism_id -eq "horizon-admittance" -and
                $_.coordinate_exact.numerator -eq 19 -and
                $_.coordinate_exact.denominator -eq 20
            }
        )
        Assert-ProductionCondition ($Targets.Count -eq 1) `
            "the canonical Leaf 13 target was not unique"
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
        $Utf8NoBom = New-Object System.Text.UTF8Encoding($false)
        [IO.File]::WriteAllText(
            $SelectionPath,
            ($Selection | ConvertTo-Json -Depth 100),
            $Utf8NoBom
        )

        Invoke-ProductionSolver -Arguments @(
            "campaign-run",
            $SelectionPath,
            "--checkpoint",
            $CheckpointPath,
            "--progress",
            "trace"
        )
        Invoke-ProductionSolver -Arguments @(
            "campaign-validate",
            $SelectionPath,
            "--checkpoint",
            $CheckpointPath
        )
    }
    finally {
        Pop-Location
    }

    $Checkpoint = Read-StrictJson $CheckpointPath
    Assert-ProductionCondition ($Checkpoint.records.Count -eq 1) `
        "checkpoint must contain exactly Leaf 13"
    $Record = $Checkpoint.records[0]
    Assert-ProductionCondition ($Record.state -eq "PRODUCED") `
        "Leaf 13 did not produce a converged component"
    Assert-ProductionCondition ($Record.stages.Count -eq 2) `
        "successful equivalence run must stop after binary64 and Julia80"
    Assert-ProductionCondition ($Record.stages[0].digits -eq 64) `
        "first stage is not binary64"
    Assert-ProductionCondition `
        ($Record.stages[0].numerical_state -eq "NOT_CONVERGED") `
        "binary64 baseline did not trigger the promoted readout"
    Assert-ProductionCondition ($Record.stages[1].digits -eq 80) `
        "second stage is not Julia80"

    $Promoted = $Record.stages[1].component_result
    $Result = $Promoted.result
    $Baseline = $Result.baseline
    $Primary = $Baseline.primary_acceptance
    $Truncation = `
        $Baseline.diagnostic_readouts.truncation.fixed_root_evidence
    $Resolution = `
        $Baseline.diagnostic_readouts.resolution.fixed_root_evidence

    Assert-ProductionCondition `
        ($Promoted.evidence_kind -eq `
            "package-owned-julia-single-promoted-horizon-component") `
        "promoted stage used the wrong component engine"
    Assert-ProductionCondition `
        ($Result.component_scientific_identity -eq `
            "single-promoted-root-analytic-horizon-component/v1") `
        "promoted component scientific identity is wrong"
    Assert-ProductionCondition ($Result.status -eq "CONVERGED") `
        "promoted component is not converged"
    Assert-ProductionCondition ($Baseline.converged -eq $true) `
        "promoted baseline root is not converged"
    Assert-ProductionCondition ($Primary.accepted -eq $true) `
        "PRIMARY was not accepted"
    Assert-ProductionCondition `
        ($Primary.post_newton_determinant_count -eq 0) `
        "PRIMARY performed a post-Newton determinant"
    Assert-ProductionCondition ($Truncation.accepted -eq $true) `
        "TRUNCATION was not accepted"
    Assert-ProductionCondition ($Truncation.determinant_count -eq 1) `
        "TRUNCATION determinant count is not one"
    Assert-ProductionCondition `
        ($Truncation.derivative_source -eq "PRIMARY_COMPLEX") `
        "TRUNCATION did not reuse complex PRIMARY Dprime"
    Assert-ProductionCondition ($Resolution.accepted -eq $true) `
        "RESOLUTION was not accepted"
    Assert-ProductionCondition ($Resolution.determinant_count -eq 1) `
        "RESOLUTION determinant count is not one"
    Assert-ProductionCondition `
        ($Resolution.derivative_source -eq "PRIMARY_COMPLEX") `
        "RESOLUTION did not reuse complex PRIMARY Dprime"
    Assert-ProductionCondition ($Baseline.seed_path_required -eq $false) `
        "SEED-PATH is marked required"
    Assert-ProductionCondition ($Baseline.seed_path_executed -eq $false) `
        "SEED-PATH is marked executed"
    Assert-ProductionCondition `
        ($Baseline.seed_path_determinant_count -eq 0) `
        "SEED-PATH determinant count is not zero"

    Assert-ProductionCondition `
        ($Result.response_method -eq `
            "analytic-horizon-from-promoted-primary-derivative/v1") `
        "horizon response method is wrong"
    Assert-ProductionCondition `
        ($Result.finite_amplitude_ladder_executed -eq $false) `
        "finite-amplitude ladder was marked executed"
    Assert-ProductionCondition `
        ($Result.finite_amplitude_readout_count -eq 0) `
        "finite-amplitude readout count is not zero"
    Assert-ProductionCondition ($Result.levels.Count -eq 0) `
        "promoted result contains fake amplitude levels"
    Assert-ProductionCondition ($null -eq $Result.signed_root_crosscheck) `
        "promoted result contains a fake signed-root crosscheck"
    Assert-ProductionCondition ($null -eq $Promoted.self_refinement_result) `
        "promoted component contains a self-refinement result"
    Assert-ProductionCondition `
        ($Promoted.self_refinement_skipped_reason -eq `
            "NOT_REQUIRED_BY_V1_4_PROMOTED_ROOT_POLICY") `
        "self-refinement omission is not explicit"
    Assert-ProductionCondition `
        ($Promoted.scientific_runtime.refinement_level -eq 0) `
        "promoted request used a nonzero refinement level"
    Assert-ProductionCondition `
        ($Baseline.worker_response_receipt.request_binding.refinement_level -eq 0) `
        "retained Julia request used refinement_level=1"

    $ResponseReal = [double]$Result.response.real
    $ResponseImaginary = [double]$Result.response.imaginary
    Assert-ProductionCondition `
        (-not [double]::IsNaN($ResponseReal) -and `
         -not [double]::IsInfinity($ResponseReal) -and `
         -not [double]::IsNaN($ResponseImaginary) -and `
         -not [double]::IsInfinity($ResponseImaginary)) `
        "analytic horizon response is nonfinite"

    $Trace = @(
        Get-Content -LiteralPath $TracePath | ForEach-Object {
            $_ | ConvertFrom-Json
        }
    )
    $JuliaAmplitudeReadouts = @(
        $Trace | Where-Object {
            $_.kind -eq "amplitude_readout_started" -and
            $_.context.precision_digits -eq 80
        }
    )
    $JuliaSignedReadouts = @(
        $JuliaAmplitudeReadouts | Where-Object {
            $_.context.readout_role -ne "baseline"
        }
    )
    $SelfRefinementPasses = @(
        $Trace | Where-Object {
            $_.kind -eq "component_pass_started" -and
            $_.context.precision_digits -eq 80 -and
            $_.context.component_pass -eq "self-refinement"
        }
    )
    $JuliaRequests = @(
        $Trace | Where-Object {
            $_.kind -eq "request_started" -and
            $_.context.precision_digits -eq 80
        }
    )
    $RefinementLevelOneRequests = @(
        $Baseline.worker_response_receipt.request_binding.refinement_level |
            Where-Object { $_ -eq 1 }
    )

    Assert-ProductionCondition ($JuliaAmplitudeReadouts.Count -eq 1) `
        "Julia80 amplitude readout count is not one"
    Assert-ProductionCondition `
        ($JuliaAmplitudeReadouts[0].context.readout_role -eq "baseline") `
        "Julia80 readout role is not baseline"
    Assert-ProductionCondition `
        ($JuliaAmplitudeReadouts[0].context.readout_index -eq 1) `
        "Julia80 baseline readout index is not one"
    Assert-ProductionCondition `
        ([double]$JuliaAmplitudeReadouts[0].context.amplitude.real -eq 0.0 -and `
         [double]$JuliaAmplitudeReadouts[0].context.amplitude.imaginary -eq 0.0) `
        "Julia80 amplitude is not exactly zero"
    Assert-ProductionCondition ($JuliaSignedReadouts.Count -eq 0) `
        "a signed-amplitude Julia readout executed"
    Assert-ProductionCondition ($SelfRefinementPasses.Count -eq 0) `
        "a promoted self-refinement component pass executed"
    Assert-ProductionCondition ($JuliaRequests.Count -eq 1) `
        "Julia80 request count is not one"
    Assert-ProductionCondition ($RefinementLevelOneRequests.Count -eq 0) `
        "a refinement_level=1 Julia request executed"

    $Report = [ordered]@{
        schema = "windows-solver.m02-production-v14-equivalence/1"
        leaf_id = [string]$Target.leaf_id
        transport_pass = $true
        scientific_result_pass = $true
        root_converged = $true
        component_converged = $true
        julia_amplitude_readouts = $JuliaAmplitudeReadouts.Count
        julia_signed_amplitude_readouts = $JuliaSignedReadouts.Count
        component_self_refinement_passes = $SelfRefinementPasses.Count
        refinement_level_one_requests = $RefinementLevelOneRequests.Count
        primary_post_newton_determinants = `
            $Primary.post_newton_determinant_count
        truncation_determinants = $Truncation.determinant_count
        resolution_determinants = $Resolution.determinant_count
        seed_path_determinants = $Baseline.seed_path_determinant_count
        analytic_response = $Result.response
        response_uncertainty_status = $Result.response_uncertainty_status
        checkpoint = $CheckpointPath
        trace = $TracePath
    }
    [IO.File]::WriteAllText(
        $ReportPath,
        ($Report | ConvertTo-Json -Depth 100),
        (New-Object System.Text.UTF8Encoding($false))
    )
    $Report | ConvertTo-Json -Depth 100
}
finally {
    $env:LOCALAPPDATA = $OriginalLocalAppData
    $env:KERR_QNM_ROOT_READOUT_CACHE_ROOT = $OriginalReadoutCacheRoot
}

Write-Host "Production Leaf 13 v1.4-equivalence checks passed." `
    -ForegroundColor Green
Write-Host "    $ReportPath"
