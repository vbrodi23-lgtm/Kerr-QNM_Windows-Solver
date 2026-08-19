[CmdletBinding(PositionalBinding = $false)]
param(
    [string]$OutputRoot = ".\m02-output\light-ring-a9999-response-recovery-v1",
    [switch]$ExerciseInterruptionResume,
    [switch]$SkipBootstrap,
    [switch]$PortableRuntime,
    [string]$RuntimeRoot
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
$PackageRoot = $PSScriptRoot
$SolverPath = Join-Path $PackageRoot "solver.ps1"
$CurrentPowerShellExecutable = (Get-Process -Id $PID).Path
. (Join-Path $PackageRoot "runtime\resolve-runtime-root.ps1")
$ExactLeafIds = @(
    "b-prime-leaf-7a86c1116062be2b0b9f06493cc5b3bec77cc7202b4f924531c4d965db4b539c",
    "b-prime-leaf-7d002095206ac650d4b8eca866ce403983284f47615943f819c3611f101bd4d5",
    "b-prime-leaf-3897345b92e3a31b02d9551b40e31efc70156c532526a7c2dfe79ec8bdad2d8c"
)

function Assert-ProductionCondition {
    param([bool]$Condition, [string]$Message)
    if (-not $Condition) { throw "Light-ring recovery assertion failed: $Message" }
}
function Invoke-ProductionSolver {
    param([string[]]$Arguments)
    & (Join-Path $PackageRoot "solver.ps1") @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Production solver command failed with exit code $LASTEXITCODE." }
}
function Get-OptionalProperty {
    param([object]$Object, [string]$Name)
    if ($null -eq $Object) { return $null }
    $Property = $Object.PSObject.Properties[$Name]
    if ($null -eq $Property) { return $null }
    return $Property.Value
}
function Stop-ProductionProcessTree {
    param([Diagnostics.Process]$Process)
    if (-not $Process.HasExited) {
        & taskkill.exe /PID $Process.Id /T /F | Out-Null
    }
    Wait-Process -Id $Process.Id -ErrorAction SilentlyContinue
    $Process.WaitForExit()
}

$ResolvedOutputRoot = [IO.Path]::GetFullPath((Join-Path $PackageRoot $OutputRoot))
$SelectionPath = Join-Path $ResolvedOutputRoot "selection.json"
$CheckpointPath = Join-Path $ResolvedOutputRoot "checkpoint.json"
$ReportPath = Join-Path $ResolvedOutputRoot "response-recovery-report.json"
foreach ($Path in @($SelectionPath, $CheckpointPath, $ReportPath)) {
    if (Test-Path -LiteralPath $Path) { throw "Cold response recovery refuses existing output: $Path" }
}
New-Item -ItemType Directory -Force -Path $ResolvedOutputRoot | Out-Null
$ResolvedRuntimeRoot = Resolve-KerrQnmRuntimeRoot -PackageRoot $PackageRoot -PortableRuntime:$PortableRuntime -OverrideRoot $RuntimeRoot
Set-KerrQnmRuntimeRoot $ResolvedRuntimeRoot
if (-not $SkipBootstrap) {
    & (Join-Path $PackageRoot "runtime\bootstrap.ps1") -WithM02 -PortableRuntime:$PortableRuntime
    if ($LASTEXITCODE -ne 0) { throw "M02 runtime bootstrap failed." }
}

$OriginalLocalAppData = $env:LOCALAPPDATA
$OriginalReadoutCacheRoot = $env:KERR_QNM_ROOT_READOUT_CACHE_ROOT
$OriginalJournalRoot = $env:KERR_QNM_PARTIAL_COMPONENT_JOURNAL_ROOT
try {
    $env:LOCALAPPDATA = Join-Path $ResolvedOutputRoot "operator-local-app-data"
    $env:KERR_QNM_ROOT_READOUT_CACHE_ROOT = Join-Path $ResolvedOutputRoot "root-readout-cache"
    $env:KERR_QNM_PARTIAL_COMPONENT_JOURNAL_ROOT = Join-Path $ResolvedOutputRoot "partial-component-journal"

    $PlanJson = & (Join-Path $PackageRoot "solver.ps1") "campaign-plan" ".\examples\m02-campaign.json"
    if ($LASTEXITCODE -ne 0) { throw "Production campaign-plan failed." }
    $Plan = ($PlanJson -join "`n") | ConvertFrom-Json
    $Targets = @($Plan.campaign.leaves | Where-Object { $ExactLeafIds -contains $_.leaf_id })
    Assert-ProductionCondition ($Targets.Count -eq 3) "the three canonical light-ring targets were not unique"
    Assert-ProductionCondition (@($Targets | Where-Object { $_.mechanism_id -ne "exterior-light-ring" }).Count -eq 0) "a selected leaf is not exterior-light-ring"
    $Selection = [ordered]@{
        schema_version = 1; backend_id = "vetted-native-gsn-determinant"
        precision_digits = @(64, 80, 120); precision_backend = $null
        role = "primary"; leaf_ids = $ExactLeafIds; cohort_ids = $null
    }
    [IO.File]::WriteAllText($SelectionPath, ($Selection | ConvertTo-Json -Depth 100), (New-Object Text.UTF8Encoding($false)))

    $FirstCompletedWorkUnitId = $null
    $PreResumeWorkUnits = @{}
    $ReusedWorkUnitIds = @()
    $ExecutedWorkUnitIds = @()
    if ($ExerciseInterruptionResume) {
        $CampaignArguments = @(
            "-NoProfile",
            "-File",
            ("`"{0}`"" -f $SolverPath),
            "campaign-run",
            ("`"{0}`"" -f $SelectionPath),
            "--checkpoint",
            ("`"{0}`"" -f $CheckpointPath),
            "--progress",
            "trace"
        )
        $CampaignProcess = Start-Process -FilePath $CurrentPowerShellExecutable `
            -ArgumentList $CampaignArguments -PassThru
        $CompletedReadoutCount = 0
        while (-not $CampaignProcess.HasExited -and $CompletedReadoutCount -lt 1) {
            Start-Sleep -Milliseconds 250
            $JournalFiles = @(Get-ChildItem -LiteralPath $env:KERR_QNM_PARTIAL_COMPONENT_JOURNAL_ROOT -Filter "*.json" -Recurse -ErrorAction SilentlyContinue)
            foreach ($JournalFile in $JournalFiles) {
                $Journal = Get-Content -LiteralPath $JournalFile.FullName -Raw | ConvertFrom-Json
                $CompletedReadoutCount += @($Journal.entries.psobject.Properties).Count
                if ($null -eq $FirstCompletedWorkUnitId -and $CompletedReadoutCount -ge 1) {
                    $FirstCompletedWorkUnitId = [string]@($Journal.entries.psobject.Properties)[0].Name
                }
                foreach ($Entry in @($Journal.entries.psobject.Properties)) {
                    $PreResumeWorkUnits[[string]$Entry.Name] = ($Entry.Value | ConvertTo-Json -Depth 100 -Compress)
                }
            }
        }
        Assert-ProductionCondition ($CompletedReadoutCount -ge 1) "no completed readout was journaled before deliberate stop"
        Stop-ProductionProcessTree -Process $CampaignProcess
        if (Test-Path -LiteralPath $CheckpointPath -PathType Leaf) {
            Invoke-ProductionSolver -Arguments @("campaign-validate", $SelectionPath, "--checkpoint", $CheckpointPath)
            Invoke-ProductionSolver -Arguments @("campaign-resume", $SelectionPath, "--checkpoint", $CheckpointPath, "--progress", "trace")
        }
        else {
            # A journal entry may commit before the campaign checkpoint. Start
            # cold at the campaign layer so the journal reuses that exact work.
            Invoke-ProductionSolver -Arguments @("campaign-run", $SelectionPath, "--checkpoint", $CheckpointPath, "--progress", "trace")
        }
    }
    else {
        Invoke-ProductionSolver -Arguments @("campaign-run", $SelectionPath, "--checkpoint", $CheckpointPath, "--progress", "trace")
    }
    Invoke-ProductionSolver -Arguments @("campaign-validate", $SelectionPath, "--checkpoint", $CheckpointPath)

    $Checkpoint = Get-Content -LiteralPath $CheckpointPath -Raw | ConvertFrom-Json
    Assert-ProductionCondition ($Checkpoint.records.Count -eq 3) "checkpoint does not contain exactly three records"
    $JournalFiles = @(Get-ChildItem -LiteralPath $env:KERR_QNM_PARTIAL_COMPONENT_JOURNAL_ROOT -Filter "*.json" -Recurse -ErrorAction SilentlyContinue)
    $DurableResume = @($JournalFiles | ForEach-Object { Get-Content -LiteralPath $_.FullName -Raw | ConvertFrom-Json })
    $FinalWorkUnits = @{}
    foreach ($Journal in $DurableResume) {
        foreach ($Entry in @($Journal.entries.psobject.Properties)) {
            $FinalWorkUnits[[string]$Entry.Name] = ($Entry.Value | ConvertTo-Json -Depth 100 -Compress)
        }
    }
    $ReusedWorkUnitIds = @($PreResumeWorkUnits.Keys | Where-Object {
        $FinalWorkUnits.ContainsKey($_) -and $FinalWorkUnits[$_] -ceq $PreResumeWorkUnits[$_]
    })
    $ExecutedWorkUnitIds = @($FinalWorkUnits.Keys | Where-Object {
        -not $PreResumeWorkUnits.ContainsKey($_)
    })
    if ($ExerciseInterruptionResume) {
        Assert-ProductionCondition ($ReusedWorkUnitIds -contains $FirstCompletedWorkUnitId) "completed readout was not reused"
        Assert-ProductionCondition ($ExecutedWorkUnitIds -notcontains $FirstCompletedWorkUnitId) "completed readout was recomputed"
    }
    $Rows = @($Checkpoint.records | ForEach-Object {
        $Result = $_.stages[-1].component_result.result
        $ResolvedWindow = Get-OptionalProperty $Result "resolved_window"
        $DerivativeEvidence = Get-OptionalProperty $Result "derivative_evidence"
        $ResponseUncertaintyStatus = Get-OptionalProperty $Result "response_uncertainty_status"
        [ordered]@{
            leaf_id = $_.leaf_id
            old_and_added_epsilons = @($Result.levels | ForEach-Object { $_.epsilon })
            signed_roots_by_precision_tier = @($Result.levels)
            signal_noise_ratios = Get-OptionalProperty $ResolvedWindow "signal_noise_ratios"
            safe_windows_considered = Get-OptionalProperty $ResolvedWindow "candidate_windows"
            selected_window = Get-OptionalProperty $ResolvedWindow "selected_window"
            excluded_fine_levels = Get-OptionalProperty $ResolvedWindow "excluded_fine_levels"
            axis_and_order_diagnostics = Get-OptionalProperty $ResolvedWindow "window_diagnostics"
            promoted_readout_count_by_tier = Get-OptionalProperty $ResolvedWindow "promoted_readout_count_by_tier"
            branch_margins = Get-OptionalProperty $ResolvedWindow "branch_margins"
            exact_added_epsilons = Get-OptionalProperty $ResolvedWindow "exact_added_epsilons"
            readout_specific_promotion_plan = Get-OptionalProperty $ResolvedWindow "readout_specific_promotion_plan"
            response_disk = Get-OptionalProperty $DerivativeEvidence "response_disk"
            finite_amplitude_validation_status = if ($null -eq $ResponseUncertaintyStatus) { "NOT_REPORTED_BY_COMPONENT" } else { $ResponseUncertaintyStatus }
            durable_resume_evidence = $DurableResume
        }
    })
    $Report = [ordered]@{
        schema = "windows-solver.m02-light-ring-response-recovery-report/1"
        semantic_precision_tiers = @("binary64", "bigfloat-40", "bigfloat-80", "bigfloat-120")
        rows = $Rows
        interruption_resume_exercised = [bool]$ExerciseInterruptionResume
        first_completed_work_unit_id = $FirstCompletedWorkUnitId
        reused_work_unit_ids = $ReusedWorkUnitIds
        executed_work_unit_ids = $ExecutedWorkUnitIds
    }
    [IO.File]::WriteAllText($ReportPath, ($Report | ConvertTo-Json -Depth 100), (New-Object Text.UTF8Encoding($false)))
}
finally {
    $env:LOCALAPPDATA = $OriginalLocalAppData
    $env:KERR_QNM_ROOT_READOUT_CACHE_ROOT = $OriginalReadoutCacheRoot
    $env:KERR_QNM_PARTIAL_COMPONENT_JOURNAL_ROOT = $OriginalJournalRoot
}
Write-Host "Light-ring recovery evidence written: $ReportPath"
