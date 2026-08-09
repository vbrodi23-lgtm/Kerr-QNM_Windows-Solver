<#
.SYNOPSIS
Resolve the managed runtime location for the Windows solver.

.DESCRIPTION
The normal public runtime is deliberately per-user and persists across source
ZIP downloads.  `-PortableRuntime` is the explicit opt-in for a checkout-local
`.runtime` tree.  `KERR_QNM_RUNTIME_ROOT` is an intentional override for
automation and advanced deployment; it must be an absolute path.
#>

function Resolve-KerrQnmRuntimeRoot {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$PackageRoot,
        [switch]$PortableRuntime,
        [string]$OverrideRoot
    )

    if ($PortableRuntime -and -not [string]::IsNullOrWhiteSpace($OverrideRoot)) {
        throw "-PortableRuntime and -RuntimeRoot cannot be used together."
    }

    $resolvedPackageRoot = [IO.Path]::GetFullPath($PackageRoot)
    if ($PortableRuntime) {
        return Join-Path $resolvedPackageRoot ".runtime"
    }

    $candidate = $OverrideRoot
    if ([string]::IsNullOrWhiteSpace($candidate)) {
        $candidate = $env:KERR_QNM_RUNTIME_ROOT
    }
    if ([string]::IsNullOrWhiteSpace($candidate)) {
        if ([string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) {
            throw "LOCALAPPDATA is unavailable; set KERR_QNM_RUNTIME_ROOT or use -PortableRuntime."
        }
        $candidate = Join-Path $env:LOCALAPPDATA "Kerr-QNM_Windows-Solver\runtime-1"
    }
    if (-not [IO.Path]::IsPathRooted($candidate)) {
        throw "KERR_QNM_RUNTIME_ROOT must be an absolute path: $candidate"
    }
    return [IO.Path]::GetFullPath($candidate)
}

function Set-KerrQnmRuntimeRoot([string]$RuntimeRoot) {
    $env:KERR_QNM_RUNTIME_ROOT = [IO.Path]::GetFullPath($RuntimeRoot)
}
