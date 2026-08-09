<#
.SYNOPSIS
Provision the managed runtime for the Kerr QNM Windows solver.

.DESCRIPTION
The normal runtime is a versioned, per-user tree below LocalAppData so it
survives deleting or re-extracting a solver ZIP.  It never modifies a system
Python installation or system package set.  -PortableRuntime is an explicit
opt-in for the legacy checkout-local .runtime tree.

The bootstrap first validates an exact 64-bit CPython 3.12.13 and Julia 1.10.11
already available to the user.  It downloads a solver-managed runtime only
when no compatible executable is available.  The numerical packages always
live in the solver-managed virtual environment, regardless of where the base
Python came from.
#>
param(
    [switch]$WithNumericalKernel,
    [switch]$WithM02,
    [switch]$Force,
    [switch]$SkipSmokeTest,
    [switch]$PowerShell51Smoke,
    [switch]$PortableRuntime,
    [string]$RuntimeRoot
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$PackageRoot = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot "resolve-runtime-root.ps1")
$RuntimeRoot = Resolve-KerrQnmRuntimeRoot -PackageRoot $PackageRoot `
    -PortableRuntime:$PortableRuntime -OverrideRoot $RuntimeRoot
Set-KerrQnmRuntimeRoot $RuntimeRoot
$PolicyPath = Join-Path $PSScriptRoot "runtime_policy.json"

function Write-Step([string]$Message) {
    Write-Host "[bootstrap] $Message"
}

function Get-Sha256([string]$Path) {
    return (Get-FileHash -Algorithm SHA256 -LiteralPath $Path).Hash.ToLowerInvariant()
}

function Get-TextSha256([string]$Text) {
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($Text)
    try {
        $sha = [System.Security.Cryptography.SHA256]::Create()
        try {
            return ([BitConverter]::ToString($sha.ComputeHash($bytes))).Replace("-", "").ToLowerInvariant()
        }
        finally {
            $sha.Dispose()
        }
    }
    finally {
        [Array]::Clear($bytes, 0, $bytes.Length)
    }
}

function Get-ObjectSha256($Value) {
    return Get-TextSha256 ($Value | ConvertTo-Json -Depth 20 -Compress)
}

function Invoke-Native([string]$FilePath, [string[]]$Arguments) {
    # Native commands often emit harmless progress text to stderr.  Exit code,
    # rather than the stream, is the executable contract.
    $previous = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        & $FilePath @Arguments 2>&1 | ForEach-Object { Write-Host "    $_" }
        $code = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previous
    }
    if ($code -ne 0) {
        throw "Command failed with exit code ${code}: $FilePath $($Arguments -join ' ')"
    }
}

function Invoke-NativeCapture([string]$FilePath, [string[]]$Arguments) {
    $previous = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $output = (& $FilePath @Arguments 2>$null | Out-String).Trim()
        $code = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previous
    }
    if ($code -ne 0) {
        throw "Command failed with exit code ${code}: $FilePath $($Arguments -join ' ')"
    }
    return $output
}

function Try-InvokeNativeCapture([string]$FilePath, [string[]]$Arguments) {
    $previous = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        try {
            $output = (& $FilePath @Arguments 2>$null | Out-String).Trim()
            $code = $LASTEXITCODE
        }
        catch {
            return $null
        }
    }
    finally {
        $ErrorActionPreference = $previous
    }
    if ($code -ne 0) {
        return $null
    }
    return $output
}

function Get-File([string]$Url, [string]$Destination) {
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Destination) | Out-Null
    Invoke-WebRequest -UseBasicParsing -Uri $Url -OutFile $Destination
}

function Remove-ManagedDirectory([string]$Path, [string]$Label) {
    if (-not (Test-Path -LiteralPath $Path)) {
        return
    }
    $fullPath = [IO.Path]::GetFullPath($Path)
    $pathRoot = [IO.Path]::GetPathRoot($fullPath)
    if ($fullPath.TrimEnd([char[]]@(92, 47)) -eq $pathRoot.TrimEnd([char[]]@(92, 47))) {
        throw "Refusing to remove a filesystem root for ${Label}: $fullPath"
    }
    cmd.exe /c rd /s /q "\\?\$fullPath"
    if ($LASTEXITCODE -ne 0 -and (Test-Path -LiteralPath $fullPath)) {
        throw "Could not remove ${Label}: $fullPath"
    }
}

function Read-JsonOrNull([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        return $null
    }
    try {
        return Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json
    }
    catch {
        return $null
    }
}

function Get-ApplicationCommand([string[]]$Names) {
    foreach ($Name in $Names) {
        $command = Get-Command $Name -CommandType Application -ErrorAction SilentlyContinue |
            Select-Object -First 1
        if ($null -ne $command -and -not [string]::IsNullOrWhiteSpace($command.Source)) {
            return $command.Source
        }
    }
    return $null
}

function Get-PythonIdentity([string]$Executable, [string[]]$PrefixArguments = @()) {
    if ([string]::IsNullOrWhiteSpace($Executable) -or -not (Test-Path -LiteralPath $Executable -PathType Leaf)) {
        return $null
    }
    $identityText = Try-InvokeNativeCapture $Executable (@($PrefixArguments) + @(
        "-c",
        "import json,platform,struct,sys; print(json.dumps({'version':platform.python_version(),'implementation':platform.python_implementation(),'bits':struct.calcsize('P')*8,'executable':sys.executable}))"
    ))
    if ($null -eq $identityText) {
        return $null
    }
    try {
        $identity = $identityText | ConvertFrom-Json
    }
    catch {
        return $null
    }
    if ($identity.version -ne $PythonVersion `
        -or $identity.implementation -ne $Policy.python.implementation `
        -or $identity.bits -ne $Policy.python.bits `
        -or [string]::IsNullOrWhiteSpace($identity.executable)) {
        return $null
    }
    return [ordered]@{
        command = [IO.Path]::GetFullPath($Executable)
        arguments = @($PrefixArguments)
        executable = [IO.Path]::GetFullPath([string]$identity.executable)
        version = [string]$identity.version
        implementation = [string]$identity.implementation
        bits = [int]$identity.bits
    }
}

function Test-NumericalKernel([string]$Python) {
    foreach ($package in $Policy.numerical_kernel.packages) {
        $observed = Try-InvokeNativeCapture $Python @(
            "-c", "import importlib.metadata as m; print(m.version('$($package.name)'))"
        )
        if ($observed -ne $package.version) {
            return $false
        }
    }
    return $true
}

function Get-NumericalPackageReceipt([string]$Python) {
    $packages = @()
    foreach ($package in $Policy.numerical_kernel.packages) {
        $observed = Try-InvokeNativeCapture $Python @(
            "-c", "import importlib.metadata as m; print(m.version('$($package.name)'))"
        )
        if ($null -ne $observed) {
            $packages += [ordered]@{ name = [string]$package.name; version = [string]$observed }
        }
    }
    return @($packages)
}

function Ensure-Uv {
    if (Test-Path -LiteralPath $UvExe -PathType Leaf) {
        $uvIdentity = Try-InvokeNativeCapture $UvExe @("--version")
        if ($null -ne $uvIdentity -and $uvIdentity -match '^uv\s+([0-9][^\s\)]*)' `
            -and $Matches[1] -eq $Policy.uv.version) {
            return
        }
        Remove-ManagedDirectory $UvRoot "incompatible uv runtime"
    }

    Write-Step "Downloading uv $($Policy.uv.version) to provision CPython"
    $archive = Join-Path $DownloadRoot $Policy.uv.archive
    $checksum = "$archive.sha256"
    Get-File $Policy.uv.url $archive
    Get-File $Policy.uv.checksum_url $checksum
    $checksumText = Get-Content -LiteralPath $checksum -Raw
    if ($checksumText -notmatch "([0-9a-fA-F]{64})") {
        throw "uv checksum response is malformed: $checksumText"
    }
    $expected = $Matches[1].ToLowerInvariant()
    $actual = Get-Sha256 $archive
    if ($actual -ne $expected) {
        throw "uv SHA-256 mismatch. Expected $expected; received $actual."
    }
    Write-Step "uv archive verified ($actual)"

    $extract = Join-Path $TempRoot "uv-extract"
    Remove-ManagedDirectory $extract "previous uv extraction"
    Expand-Archive -LiteralPath $archive -DestinationPath $extract
    $found = Get-ChildItem -LiteralPath $extract -Filter "uv.exe" -File -Recurse | Select-Object -First 1
    if ($null -eq $found) {
        throw "Verified uv archive contains no uv.exe."
    }
    New-Item -ItemType Directory -Force -Path $UvRoot | Out-Null
    Copy-Item -LiteralPath $found.FullName -Destination $UvExe -Force
    Remove-ManagedDirectory $extract "uv extraction"

    $uvIdentity = Invoke-NativeCapture $UvExe @("--version")
    if ($uvIdentity -notmatch '^uv\s+([0-9][^\s\)]*)' -or $Matches[1] -ne $Policy.uv.version) {
        throw "uv version mismatch: expected $($Policy.uv.version); received $uvIdentity."
    }
}

function Set-JuliaUtf8Console {
    $Utf8NoBom = [System.Text.UTF8Encoding]::new($false)
    $Chcp = Get-Command chcp.com -ErrorAction SilentlyContinue
    if ($null -eq $Chcp) {
        throw "Windows chcp.com is required to configure UTF-8 console output."
    }
    & $Chcp.Source 65001 | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Could not switch the active console code page to UTF-8 (65001)."
    }
    [Console]::InputEncoding = $Utf8NoBom
    [Console]::OutputEncoding = $Utf8NoBom
    $OutputEncoding = $Utf8NoBom
}

. (Join-Path $PSScriptRoot "julia-runtime-discovery.ps1")

function Invoke-Julia([string[]]$Arguments) {
    Invoke-Native $JuliaCandidate.executable (@($JuliaCandidate.arguments) + $Arguments)
}

function Invoke-JuliaCapture([string[]]$Arguments) {
    return Invoke-NativeCapture $JuliaCandidate.executable (@($JuliaCandidate.arguments) + $Arguments)
}

function Get-SourceReceipts {
    $receipts = @()
    $sourceRoot = [IO.Path]::GetFullPath($JuliaDataRoot).TrimEnd([char[]]@(92, 47))
    foreach ($Source in $Policy.scientific_sources) {
        $SourcePath = Join-Path $PackageRoot $Source.path
        if (-not (Test-Path -LiteralPath $SourcePath -PathType Leaf)) {
            throw "Required scientific source is absent: $SourcePath"
        }
        $resolvedSourcePath = [IO.Path]::GetFullPath($SourcePath)
        if (-not $resolvedSourcePath.StartsWith($sourceRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
            throw "Scientific source is outside the packaged Julia source root: $resolvedSourcePath"
        }
        $receipts += [ordered]@{
            id = [string]$Source.id
            lifecycle = [string]$Source.lifecycle
            checkout_path = $resolvedSourcePath
            relative_path = $resolvedSourcePath.Substring($sourceRoot.Length).TrimStart([char[]]@(92, 47))
            sha256 = Get-Sha256 $resolvedSourcePath
        }
    }
    return @($receipts)
}

function Get-SourceReceipt([string]$Id) {
    $matches = @($SourceReceipts | Where-Object { $_.id -eq $Id })
    if ($matches.Count -ne 1) {
        throw "Scientific source policy must contain exactly one source with ID ${Id}."
    }
    return $matches[0]
}

function Get-TreeSha256([string]$Root) {
    if (-not (Test-Path -LiteralPath $Root -PathType Container)) {
        throw "Required source directory is absent: $Root"
    }
    $resolvedRoot = [IO.Path]::GetFullPath($Root).TrimEnd([char[]]@(92, 47))
    $entries = @()
    foreach ($file in (Get-ChildItem -LiteralPath $resolvedRoot -File -Recurse | Sort-Object FullName)) {
        if (($file.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw "Runtime source tree must not contain a reparse point: $($file.FullName)"
        }
        $relative = $file.FullName.Substring($resolvedRoot.Length).TrimStart([char[]]@(92, 47))
        $entries += "$relative`t$(Get-Sha256 $file.FullName)"
    }
    return Get-TextSha256 ($entries -join "`n")
}

function Get-M02EnvironmentRejectionReason([string]$ContractSha256) {
    $receipt = Read-JsonOrNull $M02ReceiptPath
    if ($null -eq $receipt) {
        return "dependency receipt is absent"
    }
    if ($receipt.schema_version -ne 2 `
        -or $receipt.dependency_contract_sha256 -ne $ContractSha256 `
        -or $receipt.dependency_contract_id -ne $M02DependencyId) {
        return "dependency receipt identity changed"
    }
    if (-not (Test-PersistentDependencySources)) {
        return "dependency source contract is absent or invalid"
    }
    if (-not (Test-Path -LiteralPath (Join-Path $JuliaProject "Project.toml") -PathType Leaf)) {
        return "dependency Project.toml is absent"
    }
    if (-not (Test-Path -LiteralPath (Join-Path $JuliaProject "Manifest.toml") -PathType Leaf)) {
        return "dependency Manifest.toml is absent"
    }
    if (-not (Test-Path -LiteralPath $JuliaDepot -PathType Container)) {
        return "dependency depot is absent"
    }
    $projectShaProperty = $receipt.PSObject.Properties["project_sha256"]
    $manifestShaProperty = $receipt.PSObject.Properties["manifest_sha256"]
    if ($null -eq $projectShaProperty `
        -or $null -eq $manifestShaProperty) {
        return "dependency receipt lacks Project/Manifest digests"
    }
    $manifest = Get-Content -LiteralPath (Join-Path $JuliaProject "Manifest.toml") -Raw
    $checkoutRoot = [IO.Path]::GetFullPath($PackageRoot)
    $persistentSourceRoot = ([IO.Path]::GetFullPath($M02DependencySourceRoot)).Replace('\', '/')
    if ($manifest.IndexOf($checkoutRoot, [System.StringComparison]::OrdinalIgnoreCase) -ge 0 `
        -or $manifest.IndexOf("../vendor/", [System.StringComparison]::OrdinalIgnoreCase) -ge 0) {
        return "dependency Manifest contains a checkout-relative or environment-local source path"
    }
    if ($manifest.Replace('\', '/').IndexOf($persistentSourceRoot, [System.StringComparison]::OrdinalIgnoreCase) -lt 0) {
        return "dependency Manifest is not bound to the authenticated dependency source root"
    }
    if ($projectShaProperty.Value -ne (Get-Sha256 (Join-Path $JuliaProject "Project.toml"))) {
        return "dependency Project changed"
    }
    if ($manifestShaProperty.Value -ne (Get-Sha256 (Join-Path $JuliaProject "Manifest.toml"))) {
        return "dependency Manifest changed"
    }
    return $null
}

function Test-M02Environment([string]$ContractSha256) {
    return $null -eq (Get-M02EnvironmentRejectionReason $ContractSha256)
}

function Set-M02JuliaEnvironment {
    $env:JULIA_DEPOT_PATH = $JuliaDepot
    $env:JULIA_PKG_PRECOMPILE_AUTO = "0"
    $env:M02_GSN_SOURCE = Join-Path $M02DependencySourceRoot "GeneralizedSasakiNakamura.jl"
    $env:M02_ANGULAR_SOURCE = Join-Path $M02DependencySourceRoot "SpinWeightedSpheroidalHarmonics.jl"
}

function Test-PersistentDependencySources {
    if (-not (Test-Path -LiteralPath $M02DependencySourceRoot -PathType Container) `
        -or -not (Test-Path -LiteralPath (Join-Path $M02DependencySourceRoot "GeneralizedSasakiNakamura.jl") -PathType Container) `
        -or -not (Test-Path -LiteralPath (Join-Path $M02DependencySourceRoot "SpinWeightedSpheroidalHarmonics.jl") -PathType Container)) {
        return $false
    }
    if ((Get-TreeSha256 (Join-Path $M02DependencySourceRoot "GeneralizedSasakiNakamura.jl")) `
        -ne $M02DependencyContract.vendor_trees.generalized_sasaki_nakamura `
        -or (Get-TreeSha256 (Join-Path $M02DependencySourceRoot "SpinWeightedSpheroidalHarmonics.jl")) `
        -ne $M02DependencyContract.vendor_trees.spin_weighted_spheroidal_harmonics) {
        return $false
    }
    foreach ($source in @($SourceReceipts | Where-Object { $_.lifecycle -eq "dependency" })) {
        $persistentPath = Join-Path $M02DependencySourceRoot $source.relative_path
        if (-not (Test-Path -LiteralPath $persistentPath -PathType Leaf) `
            -or (Get-Sha256 $persistentPath) -ne $source.sha256) {
            return $false
        }
    }
    return $true
}

function Install-PersistentDependencySources {
    if (Test-Path -LiteralPath $M02DependencySourceRoot) {
        Remove-ManagedDirectory $M02DependencySourceRoot "invalid persistent dependency source contract"
    }
    New-Item -ItemType Directory -Force -Path $M02DependencySourceRoot | Out-Null
    Copy-Item -LiteralPath (Join-Path $JuliaDataRoot "GeneralizedSasakiNakamura.jl") `
        -Destination $M02DependencySourceRoot -Recurse -Force
    Copy-Item -LiteralPath (Join-Path $JuliaDataRoot "SpinWeightedSpheroidalHarmonics.jl") `
        -Destination $M02DependencySourceRoot -Recurse -Force
    foreach ($source in @($SourceReceipts | Where-Object { $_.lifecycle -eq "dependency" })) {
        $destination = Join-Path $M02DependencySourceRoot $source.relative_path
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $destination) | Out-Null
        Copy-Item -LiteralPath $source.checkout_path -Destination $destination -Force
    }
    if (-not (Test-PersistentDependencySources)) {
        throw "Persistent dependency source copy failed contract validation: $M02DependencySourceRoot"
    }
}

function Install-PersistentSourceFile($Source, [string]$Destination, [string]$Label) {
    if (Test-Path -LiteralPath (Split-Path -Parent $Destination)) {
        Remove-ManagedDirectory (Split-Path -Parent $Destination) "invalid persistent $Label contract"
    }
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Destination) | Out-Null
    Copy-Item -LiteralPath $Source.checkout_path -Destination $Destination -Force
    if (-not (Test-Path -LiteralPath $Destination -PathType Leaf) `
        -or (Get-Sha256 $Destination) -ne $Source.sha256) {
        throw "Persistent $Label copy failed contract validation: $Destination"
    }
}

function Test-PersistentSourceFile($Source, [string]$Destination) {
    return (
        (Test-Path -LiteralPath $Destination -PathType Leaf) `
        -and (Get-Sha256 $Destination) -eq $Source.sha256
    )
}

function Get-PersistentM02ManifestText([string]$SeedPath, [string]$SourceRoot) {
    $manifest = Get-Content -LiteralPath $SeedPath -Raw
    foreach ($name in @("GeneralizedSasakiNakamura.jl", "SpinWeightedSpheroidalHarmonics.jl")) {
        $persistentPath = ([IO.Path]::GetFullPath((Join-Path $SourceRoot $name))).Replace('\', '/')
        $seedPath = "path = `"../vendor/$name`""
        if (-not $manifest.Contains($seedPath)) {
            throw "M02 seed manifest lacks the expected path dependency: $seedPath"
        }
        $manifest = $manifest.Replace($seedPath, "path = `"$persistentPath`"")
    }
    if ($manifest.IndexOf("../vendor/", [System.StringComparison]::OrdinalIgnoreCase) -ge 0) {
        throw "Persistent M02 manifest still contains an environment-local vendor path."
    }
    return $manifest
}

function Write-PersistentM02Manifest([string]$SeedPath, [string]$Destination) {
    $manifest = Get-PersistentM02ManifestText $SeedPath $M02DependencySourceRoot
    [IO.File]::WriteAllText($Destination, $manifest, [System.Text.UTF8Encoding]::new($false))
}

function Test-ManagedRuntimePath([string]$Path) {
    if ([string]::IsNullOrWhiteSpace($Path)) {
        return $false
    }
    $managedRoot = [IO.Path]::GetFullPath($RuntimeRoot).TrimEnd([char[]]@(92, 47)) + [IO.Path]::DirectorySeparatorChar
    $candidate = [IO.Path]::GetFullPath($Path)
    return $candidate.StartsWith($managedRoot, [System.StringComparison]::OrdinalIgnoreCase)
}

function Get-CompatibleLegacyM02Environment {
    if ($null -eq $ExistingReceipt) {
        return $null
    }
    $juliaProperty = $ExistingReceipt.PSObject.Properties["julia_runtime"]
    if ($null -eq $juliaProperty) {
        return $null
    }
    $legacy = $juliaProperty.Value
    foreach ($name in @("source_root", "project", "depot", "manifest_sha256")) {
        $property = $legacy.PSObject.Properties[$name]
        if ($null -eq $property -or [string]::IsNullOrWhiteSpace([string]$property.Value)) {
            return $null
        }
    }
    if ($legacy.requested -ne $true `
        -or $legacy.version -ne $JuliaCandidate.version `
        -or $legacy.bits -ne $JuliaCandidate.bits `
        -or $legacy.executable_sha256 -ne $JuliaCandidate.executable_sha256 `
        -or -not (Test-ManagedRuntimePath ([string]$legacy.source_root)) `
        -or -not (Test-ManagedRuntimePath ([string]$legacy.project)) `
        -or -not (Test-ManagedRuntimePath ([string]$legacy.depot))) {
        return $null
    }
    $legacySourcesProperty = $legacy.PSObject.Properties["sources"]
    if ($null -eq $legacySourcesProperty) {
        return $null
    }
    foreach ($requiredSource in @($ProjectSource, $ManifestSeedSource)) {
        $matches = @($legacySourcesProperty.Value | Where-Object {
            $_.id -eq $requiredSource.id -and $_.sha256 -eq $requiredSource.sha256
        })
        if ($matches.Count -ne 1) {
            return $null
        }
    }
    $sourceRoot = [IO.Path]::GetFullPath([string]$legacy.source_root)
    $project = [IO.Path]::GetFullPath([string]$legacy.project)
    $depot = [IO.Path]::GetFullPath([string]$legacy.depot)
    if (-not (Test-Path -LiteralPath $sourceRoot -PathType Container) `
        -or -not (Test-Path -LiteralPath $project -PathType Container) `
        -or -not (Test-Path -LiteralPath $depot -PathType Container)) {
        return $null
    }
    if ((Get-TreeSha256 (Join-Path $sourceRoot "GeneralizedSasakiNakamura.jl")) `
        -ne $M02DependencyContract.vendor_trees.generalized_sasaki_nakamura `
        -or (Get-TreeSha256 (Join-Path $sourceRoot "SpinWeightedSpheroidalHarmonics.jl")) `
        -ne $M02DependencyContract.vendor_trees.spin_weighted_spheroidal_harmonics) {
        return $null
    }
    $projectPath = Join-Path $project "Project.toml"
    $manifestPath = Join-Path $project "Manifest.toml"
    if (-not (Test-Path -LiteralPath $projectPath -PathType Leaf) `
        -or -not (Test-Path -LiteralPath $manifestPath -PathType Leaf) `
        -or (Get-Sha256 $projectPath) -ne $ProjectSource.sha256 `
        -or (Get-Sha256 $manifestPath) -ne [string]$legacy.manifest_sha256) {
        return $null
    }
    $actualManifest = Get-Content -LiteralPath $manifestPath -Raw
    $checkoutRoot = [IO.Path]::GetFullPath($PackageRoot)
    $persistentSourceRoot = $sourceRoot.Replace('\', '/')
    if ($actualManifest.IndexOf($checkoutRoot, [System.StringComparison]::OrdinalIgnoreCase) -ge 0 `
        -or $actualManifest.IndexOf("../vendor/", [System.StringComparison]::OrdinalIgnoreCase) -ge 0 `
        -or $actualManifest.Replace('\', '/').IndexOf($persistentSourceRoot, [System.StringComparison]::OrdinalIgnoreCase) -lt 0) {
        return $null
    }
    return [ordered]@{
        source_root = $sourceRoot
        project = $project
        depot = $depot
    }
}

if ($PowerShell51Smoke) {
    $smokeRoot = Join-Path ([IO.Path]::GetTempPath()) ("Kerr-QNM-bootstrap-smoke-" + [Guid]::NewGuid().ToString("N"))
    try {
        New-Item -ItemType Directory -Force -Path (Join-Path $smokeRoot "child") | Out-Null
        Remove-ManagedDirectory $smokeRoot "PowerShell compatibility smoke"
        if (Test-Path -LiteralPath $smokeRoot) {
            throw "PowerShell compatibility smoke could not remove its temporary directory."
        }
        $M02DependencySourceRoot = Join-Path $smokeRoot "scientific-sources\smoke-contract"
        $smokeProject = Join-Path $smokeRoot "m02-environments\smoke-contract\project"
        foreach ($name in @("GeneralizedSasakiNakamura.jl", "SpinWeightedSpheroidalHarmonics.jl")) {
            $package = Join-Path $M02DependencySourceRoot $name
            New-Item -ItemType Directory -Force -Path $package | Out-Null
            Set-Content -LiteralPath (Join-Path $package "Project.toml") -Value "name = '$name'" -Encoding UTF8
        }
        New-Item -ItemType Directory -Force -Path $smokeProject | Out-Null
        $smokeSeed = Join-Path $smokeRoot "Manifest.seed.toml"
        @'
[[deps.GeneralizedSasakiNakamura]]
path = "../vendor/GeneralizedSasakiNakamura.jl"
[[deps.SpinWeightedSpheroidalHarmonics]]
path = "../vendor/SpinWeightedSpheroidalHarmonics.jl"
'@ | Set-Content -LiteralPath $smokeSeed -Encoding UTF8
        $smokeManifest = Join-Path $smokeProject "Manifest.toml"
        Write-PersistentM02Manifest $smokeSeed $smokeManifest
        if ((Get-Content -LiteralPath $smokeManifest -Raw).IndexOf("../vendor/", [System.StringComparison]::OrdinalIgnoreCase) -ge 0) {
            throw "PowerShell compatibility smoke left an environment-local vendor path in the manifest."
        }
        Write-Host "PowerShell 5.1 compatibility smoke passed"
    }
    finally {
        if (Test-Path -LiteralPath $smokeRoot) {
            Remove-Item -LiteralPath $smokeRoot -Force -Recurse
        }
    }
    exit 0
}

# ---------------------------------------------------------------- preconditions

if ($PSVersionTable.PSVersion.Major -lt 5) {
    throw "Windows PowerShell 5.1 or newer is required; this host is $($PSVersionTable.PSVersion)."
}
if (-not [Environment]::Is64BitProcess) {
    throw "Run this from a 64-bit PowerShell host; the pinned CPython and wheels are x86_64."
}
if (-not (Test-Path -LiteralPath $PolicyPath -PathType Leaf)) {
    throw "Runtime policy is absent: $PolicyPath"
}

$Policy = Get-Content -LiteralPath $PolicyPath -Raw | ConvertFrom-Json
$PolicySha256 = Get-Sha256 $PolicyPath
$PythonVersion = [string]$Policy.python.python_version
$JuliaVersion = [string]$Policy.julia.version
$NumericalEnvironmentParts = @()
foreach ($package in $Policy.numerical_kernel.packages) {
    $safeName = ([string]$package.name).ToLowerInvariant() -replace '[^a-z0-9]+', '-'
    $safeVersion = ([string]$package.version).ToLowerInvariant() -replace '[^a-z0-9]+', '-'
    $NumericalEnvironmentParts += "$safeName-$safeVersion"
}
$NumericalEnvironmentId = $NumericalEnvironmentParts -join "-"
if ($WithM02) {
    $WithNumericalKernel = $true
}

$DownloadRoot = Join-Path $RuntimeRoot "downloads"
$TempRoot = Join-Path $RuntimeRoot "tmp"
$MetadataRoot = Join-Path $RuntimeRoot "metadata"
$UvRoot = Join-Path $RuntimeRoot "tools\uv-$($Policy.uv.version)"
$UvExe = Join-Path $UvRoot "uv.exe"
$PythonInstallRoot = Join-Path $RuntimeRoot "cpython\$PythonVersion"
$ManagedPythonHint = Join-Path $PythonInstallRoot "python.exe"
$VenvRoot = Join-Path $RuntimeRoot "python-env\$($Policy.policy_id)-cpython-$PythonVersion-$NumericalEnvironmentId"
$VenvPython = Join-Path $VenvRoot "Scripts\python.exe"
$ManagedJuliaRoot = Join-Path $RuntimeRoot "julia\$JuliaVersion"
$ManagedJuliaExe = Join-Path $ManagedJuliaRoot "bin\julia.exe"
$JuliaDataRoot = Join-Path $PackageRoot "src\windows_solver\data\julia"
$ReceiptPath = Join-Path $RuntimeRoot "python-runtime.json"
$IdentityPath = Join-Path $MetadataRoot "runtime-identity.json"
$ExistingReceipt = Read-JsonOrNull $ReceiptPath

if ($Force -and (Test-Path -LiteralPath $RuntimeRoot)) {
    Write-Step "Removing managed runtime for an explicit clean reprovision: $RuntimeRoot"
    Remove-ManagedDirectory $RuntimeRoot "existing managed runtime directory"
    $ExistingReceipt = $null
}
foreach ($path in @($RuntimeRoot, $DownloadRoot, $TempRoot, $MetadataRoot)) {
    New-Item -ItemType Directory -Force -Path $path | Out-Null
}
$env:TEMP = $TempRoot
$env:TMP = $TempRoot

# --------------------------------------------------------------------- CPython

$PriorManagedPython = $null
if ($null -ne $ExistingReceipt) {
    $pythonProperty = $ExistingReceipt.PSObject.Properties["python"]
    $existingPython = if ($null -ne $pythonProperty) { $pythonProperty.Value } else { $null }
    $managedProperty = if ($null -ne $existingPython) {
        $existingPython.PSObject.Properties["managed_interpreter"]
    }
    else {
        $null
    }
    if ($null -ne $managedProperty -and -not [string]::IsNullOrWhiteSpace([string]$managedProperty.Value)) {
        $PriorManagedPython = [string]$managedProperty.Value
    }
}
$VenvIdentity = Get-PythonIdentity $VenvPython
$PythonSource = $null
$PythonSourceKind = $null
$ManagedPython = $PriorManagedPython
if ($null -ne $VenvIdentity) {
    $PythonSource = $VenvIdentity
    $PythonSourceKind = "managed-venv"
    Write-Step "Reusing validated CPython $PythonVersion virtual environment"
}
else {
    $ManagedIdentity = Get-PythonIdentity $ManagedPythonHint
    if ($null -eq $ManagedIdentity -and $null -ne $PriorManagedPython) {
        $ManagedIdentity = Get-PythonIdentity $PriorManagedPython
    }
    if ($null -ne $ManagedIdentity) {
        $PythonSource = $ManagedIdentity
        $PythonSourceKind = "managed-cpython"
        $ManagedPython = $ManagedIdentity.command
    }
    if ($null -eq $PythonSource) {
        foreach ($candidatePath in @((Get-ApplicationCommand @("python.exe", "python")))) {
            if ($null -eq $candidatePath) { continue }
            $candidate = Get-PythonIdentity $candidatePath
            if ($null -ne $candidate) {
                $PythonSource = $candidate
                $PythonSourceKind = "system"
                break
            }
        }
    }
    if ($null -eq $PythonSource) {
        $pyCommand = Get-ApplicationCommand @("py.exe", "py")
        if ($null -ne $pyCommand) {
            $candidate = Get-PythonIdentity $pyCommand @("-3.12")
            if ($null -ne $candidate) {
                $PythonSource = $candidate
                $PythonSourceKind = "py-launcher"
            }
        }
    }
    if ($null -eq $PythonSource) {
        Ensure-Uv
        $env:UV_PYTHON_INSTALL_DIR = $PythonInstallRoot
        $env:UV_CACHE_DIR = Join-Path $RuntimeRoot "uv-cache"
        Write-Step "No compatible CPython found; provisioning managed CPython $PythonVersion"
        Invoke-Native $UvExe @(
            "python", "install", $PythonVersion,
            "--install-dir", $PythonInstallRoot,
            "--no-bin", "--no-registry", "--no-config", "--system-certs"
        )
        $ManagedPython = Invoke-NativeCapture $UvExe @(
            "python", "find", $PythonVersion,
            "--managed-python", "--no-python-downloads", "--no-project", "--no-config"
        )
        $candidate = Get-PythonIdentity $ManagedPython
        if ($null -eq $candidate) {
            throw "uv could not resolve a compatible managed CPython ${PythonVersion}: '$ManagedPython'"
        }
        $PythonSource = $candidate
        $PythonSourceKind = "managed-cpython"
    }

    Remove-ManagedDirectory $VenvRoot "incompatible Python virtual environment"
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $VenvRoot) | Out-Null
    Write-Step "Creating isolated numerical environment from $PythonSourceKind Python"
    Invoke-Native $PythonSource.command (@($PythonSource.arguments) + @("-m", "venv", $VenvRoot))
    $VenvIdentity = Get-PythonIdentity $VenvPython
    if ($null -eq $VenvIdentity) {
        throw "Created virtual environment does not satisfy the pinned CPython contract: $VenvPython"
    }
}

if ($WithNumericalKernel) {
    if (Test-NumericalKernel $VenvPython) {
        Write-Step "Pinned NumPy/SciPy environment is already valid"
    }
    else {
        $pipProbe = Try-InvokeNativeCapture $VenvPython @("-m", "pip", "--version")
        if ($null -eq $pipProbe) {
            Invoke-Native $VenvPython @("-m", "ensurepip", "--upgrade")
        }
        $specifiers = @()
        foreach ($package in $Policy.numerical_kernel.packages) {
            $specifiers += "$($package.name)==$($package.version)"
        }
        $pipArguments = @("-m", "pip", "install", "--disable-pip-version-check", "--upgrade", "--only-binary=:all:")
        if ($Policy.numerical_kernel.wheels.Count -gt 0) {
            $wheelhouse = Join-Path $RuntimeRoot "wheelhouse"
            New-Item -ItemType Directory -Force -Path $wheelhouse | Out-Null
            foreach ($wheel in $Policy.numerical_kernel.wheels) {
                $destination = Join-Path $wheelhouse $wheel.filename
                if (-not (Test-Path -LiteralPath $destination -PathType Leaf) `
                    -or (Get-Sha256 $destination) -ne $wheel.sha256) {
                    Get-File $wheel.url $destination
                }
                if ((Get-Sha256 $destination) -ne $wheel.sha256.ToLowerInvariant()) {
                    throw "Wheel SHA-256 mismatch for $($wheel.filename)."
                }
            }
            $pipArguments += @("--no-index", "--find-links", $wheelhouse)
        }
        Write-Step "Installing pinned NumPy/SciPy only inside the managed virtual environment"
        Invoke-Native $VenvPython ($pipArguments + $specifiers)
        if (-not (Test-NumericalKernel $VenvPython)) {
            throw "Pinned NumPy/SciPy environment failed post-install validation."
        }
    }
}
$InstalledPackages = Get-NumericalPackageReceipt $VenvPython

# ------------------------------------------------------------------------- M02

$existingJuliaProperty = if ($null -ne $ExistingReceipt) {
    $ExistingReceipt.PSObject.Properties["julia_runtime"]
}
else {
    $null
}
$JuliaReceipt = if ($null -ne $existingJuliaProperty) {
    $existingJuliaProperty.Value
}
else {
    [ordered]@{ requested = $false }
}
if ($WithM02) {
    Set-JuliaUtf8Console
    $JuliaCandidate = Get-JuliaCandidate $ManagedJuliaExe @() "managed"
    if ($null -eq $JuliaCandidate) {
        $juliaup = Get-ApplicationCommand @("juliaup.exe", "juliaup")
        $juliaShim = Get-ApplicationCommand @("julia.exe", "julia")
        if ($null -ne $juliaup -and $null -ne $juliaShim) {
            $JuliaCandidate = Get-JuliaCandidate $juliaShim @("+$JuliaVersion") "juliaup"
        }
    }
    if ($null -eq $JuliaCandidate) {
        $systemJulia = Get-ApplicationCommand @("julia.exe", "julia")
        if ($null -ne $systemJulia) {
            $JuliaCandidate = Get-JuliaCandidate $systemJulia @() "system"
        }
    }
    $JuliaArchive = $null
    $ActualJuliaSha256 = $null
    if ($null -eq $JuliaCandidate) {
        $JuliaArchive = Join-Path $DownloadRoot $Policy.julia.archive
        $ExpectedJuliaSha256 = $Policy.julia.sha256.ToLowerInvariant()
        if (-not (Test-Path -LiteralPath $JuliaArchive -PathType Leaf) `
            -or (Get-Sha256 $JuliaArchive) -ne $ExpectedJuliaSha256) {
            Write-Step "No compatible Julia found; downloading managed Julia $JuliaVersion"
            Get-File $Policy.julia.url $JuliaArchive
        }
        $ActualJuliaSha256 = Get-Sha256 $JuliaArchive
        if ($ActualJuliaSha256 -ne $ExpectedJuliaSha256) {
            throw "Julia archive SHA-256 mismatch. Expected $ExpectedJuliaSha256; received $ActualJuliaSha256."
        }
        Write-Step "Julia archive verified ($ActualJuliaSha256)"
        $JuliaExtract = Join-Path $TempRoot "julia-extract"
        Remove-ManagedDirectory $JuliaExtract "previous Julia extraction directory"
        New-Item -ItemType Directory -Force -Path $JuliaExtract | Out-Null
        $Tar = Get-Command tar.exe -ErrorAction SilentlyContinue
        if ($null -eq $Tar) {
            throw "Windows tar.exe is required to extract the managed Julia runtime."
        }
        & $Tar.Source -xf $JuliaArchive -C $JuliaExtract
        if ($LASTEXITCODE -ne 0) {
            throw "Julia archive extraction failed with tar.exe exit code $LASTEXITCODE."
        }
        $FoundJulia = Get-ChildItem -LiteralPath $JuliaExtract -Filter "julia.exe" -File -Recurse | Select-Object -First 1
        if ($null -eq $FoundJulia) {
            throw "Verified Julia archive contains no julia.exe."
        }
        $ExtractedJuliaRoot = Split-Path -Parent (Split-Path -Parent $FoundJulia.FullName)
        Remove-ManagedDirectory $ManagedJuliaRoot "previous managed Julia runtime directory"
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $ManagedJuliaRoot) | Out-Null
        Move-Item -LiteralPath $ExtractedJuliaRoot -Destination $ManagedJuliaRoot
        Remove-ManagedDirectory $JuliaExtract "Julia extraction directory"
        $JuliaCandidate = Get-JuliaCandidate $ManagedJuliaExe @() "managed"
        if ($null -eq $JuliaCandidate) {
            throw "Installed managed Julia runtime is absent or incompatible: $ManagedJuliaExe"
        }
    }

    $SourceReceipts = Get-SourceReceipts
    foreach ($source in $SourceReceipts) {
        if ($source.lifecycle -notin @("dependency", "worker", "gsn-cache")) {
            throw "Scientific source '$($source.id)' has an unsupported lifecycle '$($source.lifecycle)'."
        }
    }
    $GsnTreeSha256 = Get-TreeSha256 (Join-Path $JuliaDataRoot "GeneralizedSasakiNakamura.jl")
    $AngularTreeSha256 = Get-TreeSha256 (Join-Path $JuliaDataRoot "SpinWeightedSpheroidalHarmonics.jl")
    $ProjectSource = Get-SourceReceipt "m02-julia-project"
    $ManifestSeedSource = Get-SourceReceipt "m02-julia-manifest-seed"
    $WorkerSource = Get-SourceReceipt "m02-julia-worker"
    $ProducerSource = Get-SourceReceipt "gsn-cache-producer"

    $M02DependencyContract = [ordered]@{
        schema_version = 1
        julia = [ordered]@{
            version = $JuliaCandidate.version
            bits = $JuliaCandidate.bits
            executable_sha256 = $JuliaCandidate.executable_sha256
        }
        project_sha256 = $ProjectSource.sha256
        manifest_seed_sha256 = $ManifestSeedSource.sha256
        vendor_trees = [ordered]@{
            generalized_sasaki_nakamura = $GsnTreeSha256
            spin_weighted_spheroidal_harmonics = $AngularTreeSha256
        }
    }
    $M02DependencySha256 = Get-ObjectSha256 $M02DependencyContract
    $M02DependencyId = "m02-deps-" + $M02DependencySha256.Substring(0, 24)

    $M02WorkerContract = [ordered]@{
        schema_version = 1
        worker_sha256 = $WorkerSource.sha256
    }
    $M02WorkerSha256 = Get-ObjectSha256 $M02WorkerContract
    $M02WorkerId = "m02-worker-" + $M02WorkerSha256.Substring(0, 24)

    $M02GsnCacheContract = [ordered]@{
        schema_version = 1
        julia = [ordered]@{
            version = $JuliaCandidate.version
            bits = $JuliaCandidate.bits
            executable_sha256 = $JuliaCandidate.executable_sha256
        }
        producer_sha256 = $ProducerSource.sha256
        generalized_sasaki_nakamura_tree_sha256 = $GsnTreeSha256
    }
    $M02GsnCacheSha256 = Get-ObjectSha256 $M02GsnCacheContract
    $M02GsnCacheId = "m02-gsn-" + $M02GsnCacheSha256.Substring(0, 24)

    $M02Contract = [ordered]@{
        schema_version = 2
        dependency_contract_id = $M02DependencyId
        worker_contract_id = $M02WorkerId
        gsn_cache_contract_id = $M02GsnCacheId
    }
    $M02ContractSha256 = Get-ObjectSha256 $M02Contract
    $M02ContractId = "m02-" + $M02ContractSha256.Substring(0, 24)

    $M02DependencySourceRoot = Join-Path $RuntimeRoot "scientific-sources\$M02DependencyId"
    $M02Root = Join-Path $RuntimeRoot "m02-environments\$M02DependencyId"
    $JuliaProject = Join-Path $M02Root "project"
    $JuliaDepot = Join-Path $RuntimeRoot "julia-depot\$M02DependencyId"
    $M02ReceiptDirectory = Join-Path $MetadataRoot "m02-environments"
    $M02ReceiptPath = Join-Path $M02ReceiptDirectory "$M02DependencyId.json"
    $PersistentWorkerPath = Join-Path (Join-Path $RuntimeRoot "m02-workers\$M02WorkerId") "m02_worker.jl"
    $PersistentProducerPath = Join-Path (Join-Path $RuntimeRoot "gsn-producers\$M02GsnCacheId") "generate_gsn_cache.jl"
    New-Item -ItemType Directory -Force -Path $M02ReceiptDirectory | Out-Null

    $DependencyReceipt = Read-JsonOrNull $M02ReceiptPath
    if ($null -ne $DependencyReceipt) {
        $dependencySourceProperty = $DependencyReceipt.PSObject.Properties["dependency_source_root"]
        $projectProperty = $DependencyReceipt.PSObject.Properties["project"]
        $depotProperty = $DependencyReceipt.PSObject.Properties["depot"]
        if ($null -ne $dependencySourceProperty `
            -and (Test-ManagedRuntimePath ([string]$dependencySourceProperty.Value))) {
            $M02DependencySourceRoot = [IO.Path]::GetFullPath([string]$dependencySourceProperty.Value)
        }
        if ($null -ne $projectProperty -and (Test-ManagedRuntimePath ([string]$projectProperty.Value))) {
            $JuliaProject = [IO.Path]::GetFullPath([string]$projectProperty.Value)
            $M02Root = Split-Path -Parent $JuliaProject
        }
        if ($null -ne $depotProperty -and (Test-ManagedRuntimePath ([string]$depotProperty.Value))) {
            $JuliaDepot = [IO.Path]::GetFullPath([string]$depotProperty.Value)
        }
    }

    $LegacyEnvironment = $null
    if ($null -eq $DependencyReceipt) {
        $LegacyEnvironment = Get-CompatibleLegacyM02Environment
        if ($null -ne $LegacyEnvironment) {
            $M02DependencySourceRoot = $LegacyEnvironment.source_root
            $JuliaProject = $LegacyEnvironment.project
            $JuliaDepot = $LegacyEnvironment.depot
            $M02Root = Split-Path -Parent $JuliaProject
            Write-Step "M02 dependency environment reused from authenticated legacy aggregate contract"
        }
    }

    if (-not (Test-PersistentDependencySources)) {
        Write-Step "Installing dependency source contract $M02DependencyId"
        Install-PersistentDependencySources
    }

    $PriorWorkerId = $null
    $PriorWorkerSha256 = $null
    if ($null -ne $ExistingReceipt) {
        $priorJuliaProperty = $ExistingReceipt.PSObject.Properties["julia_runtime"]
        if ($null -ne $priorJuliaProperty) {
            $priorWorkerProperty = $priorJuliaProperty.Value.PSObject.Properties["worker_contract_id"]
            if ($null -ne $priorWorkerProperty) {
                $PriorWorkerId = [string]$priorWorkerProperty.Value
            }
            $priorWorkerShaProperty = $priorJuliaProperty.Value.PSObject.Properties["worker_sha256"]
            if ($null -ne $priorWorkerShaProperty) {
                $PriorWorkerSha256 = [string]$priorWorkerShaProperty.Value
            }
        }
    }
    if (-not (Test-PersistentSourceFile $WorkerSource $PersistentWorkerPath)) {
        if (($null -ne $PriorWorkerId -and $PriorWorkerId -ne $M02WorkerId) `
            -or ($null -ne $PriorWorkerSha256 -and $PriorWorkerSha256 -ne $WorkerSource.sha256)) {
            Write-Step "M02 worker source changed; refreshing worker only"
        }
        else {
            Write-Step "Installing M02 worker source contract $M02WorkerId"
        }
        Install-PersistentSourceFile $WorkerSource $PersistentWorkerPath "M02 worker source"
    }
    if (-not (Test-PersistentSourceFile $ProducerSource $PersistentProducerPath)) {
        Write-Step "Installing GSN producer source contract $M02GsnCacheId"
        Install-PersistentSourceFile $ProducerSource $PersistentProducerPath "GSN producer source"
    }

    $DependencyRejectionReason = Get-M02EnvironmentRejectionReason $M02DependencySha256
    $M02Ready = $null -eq $DependencyRejectionReason
    if ($null -ne $LegacyEnvironment -and -not $M02Ready) {
        $manifestPath = Join-Path $JuliaProject "Manifest.toml"
        $M02Receipt = [ordered]@{
            schema_version = 2
            dependency_contract_sha256 = $M02DependencySha256
            dependency_contract_id = $M02DependencyId
            dependency_contract = $M02DependencyContract
            dependency_source_root = [IO.Path]::GetFullPath($M02DependencySourceRoot)
            project = [IO.Path]::GetFullPath($JuliaProject)
            depot = [IO.Path]::GetFullPath($JuliaDepot)
            project_sha256 = Get-Sha256 (Join-Path $JuliaProject "Project.toml")
            manifest_sha256 = Get-Sha256 $manifestPath
            storage_layout = "legacy-aggregate-v1"
            created_utc = [DateTime]::UtcNow.ToString("o")
        }
        $M02Receipt | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $M02ReceiptPath -Encoding UTF8
        $DependencyRejectionReason = Get-M02EnvironmentRejectionReason $M02DependencySha256
        $M02Ready = $null -eq $DependencyRejectionReason
    }

    if ($M02Ready) {
        Set-M02JuliaEnvironment
        try {
            Invoke-Julia @(
                "--startup-file=no",
                "--history-file=no",
                "--project=$JuliaProject",
                $PersistentWorkerPath,
                "--probe"
            )
        }
        catch {
            Write-Step "M02 worker probe failed; retaining the authenticated dependency environment"
            throw
        }
        Write-Step "M02 dependency environment reused"
        Write-Step "M02 Julia project/depot receipt and probe are valid"
    }
    else {
        $PriorManifestSeedSha256 = $null
        if ($null -ne $ExistingReceipt) {
            $priorJuliaProperty = $ExistingReceipt.PSObject.Properties["julia_runtime"]
            if ($null -ne $priorJuliaProperty) {
                $priorDependencyProperty = $priorJuliaProperty.Value.PSObject.Properties["dependency_contract"]
                if ($null -ne $priorDependencyProperty) {
                    $priorManifestProperty = $priorDependencyProperty.Value.PSObject.Properties["manifest_seed_sha256"]
                    if ($null -ne $priorManifestProperty) {
                        $PriorManifestSeedSha256 = [string]$priorManifestProperty.Value
                    }
                }
            }
        }
        if (($null -ne $PriorManifestSeedSha256 -and $PriorManifestSeedSha256 -ne $ManifestSeedSource.sha256) `
            -or $DependencyRejectionReason -eq "dependency Manifest changed") {
            Write-Step "M02 dependency Manifest changed; rebuilding Julia environment"
        }
        else {
            Write-Step "M02 dependency environment reuse rejected: $DependencyRejectionReason; rebuilding Julia environment"
        }
        Remove-ManagedDirectory $M02Root "incompatible M02 Julia project"
        Remove-ManagedDirectory $JuliaDepot "incompatible M02 Julia depot"
        New-Item -ItemType Directory -Force -Path $JuliaProject | Out-Null
        Copy-Item -LiteralPath (Join-Path $M02DependencySourceRoot "m02_project\Project.toml") `
            -Destination (Join-Path $JuliaProject "Project.toml") -Force
        Write-PersistentM02Manifest `
            (Join-Path $M02DependencySourceRoot "m02_project\Manifest.seed.toml") `
            (Join-Path $JuliaProject "Manifest.toml")
        New-Item -ItemType Directory -Force -Path $JuliaDepot | Out-Null
        Set-M02JuliaEnvironment
        $SetupExpression = @'
using Pkg
Pkg.develop(PackageSpec(path=ENV["M02_ANGULAR_SOURCE"]))
Pkg.develop(PackageSpec(path=ENV["M02_GSN_SOURCE"]))
Pkg.resolve()
Pkg.instantiate()
Pkg.precompile()
'@
        $SetupScript = Join-Path $TempRoot "m02-setup.jl"
        [IO.File]::WriteAllText(
            $SetupScript,
            $SetupExpression,
            [System.Text.UTF8Encoding]::new($false)
        )
        Write-Step "Instantiating and precompiling the pinned M02 Julia project"
        try {
            Invoke-Julia @(
                "--startup-file=no",
                "--history-file=no",
                "--project=$JuliaProject",
                $SetupScript
            )
        }
        finally {
            if (Test-Path -LiteralPath $SetupScript -PathType Leaf) {
                Remove-Item -LiteralPath $SetupScript -Force
            }
        }
        $WorkerPath = $PersistentWorkerPath
        Invoke-Julia @(
            "--startup-file=no",
            "--history-file=no",
            "--project=$JuliaProject",
            $WorkerPath,
            "--probe"
        )
        $M02Receipt = [ordered]@{
            schema_version = 2
            dependency_contract_sha256 = $M02DependencySha256
            dependency_contract_id = $M02DependencyId
            dependency_contract = $M02DependencyContract
            dependency_source_root = [IO.Path]::GetFullPath($M02DependencySourceRoot)
            project = [IO.Path]::GetFullPath($JuliaProject)
            depot = [IO.Path]::GetFullPath($JuliaDepot)
            project_sha256 = Get-Sha256 (Join-Path $JuliaProject "Project.toml")
            manifest_sha256 = Get-Sha256 (Join-Path $JuliaProject "Manifest.toml")
            storage_layout = "dependency-v2"
            created_utc = [DateTime]::UtcNow.ToString("o")
        }
        $M02Receipt | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $M02ReceiptPath -Encoding UTF8
        Write-Step "M02 Julia project, depot, and precision worker are ready"
    }
    $WorkerPath = $PersistentWorkerPath

    $JuliaReceipt = [ordered]@{
        requested = $true
        version = [string]$JuliaCandidate.version
        bits = [int]$JuliaCandidate.bits
        executable = [string]$JuliaCandidate.executable
        executable_sha256 = [string]$JuliaCandidate.executable_sha256
        arguments = @($JuliaCandidate.arguments)
        source = [string]$JuliaCandidate.source
        launcher = [string]$JuliaCandidate.launcher
        launcher_arguments = @($JuliaCandidate.launcher_arguments)
        launcher_kind = [string]$JuliaCandidate.launcher_kind
        archive = $JuliaArchive
        archive_sha256 = $ActualJuliaSha256
        sources = @($SourceReceipts)
        source_root = [IO.Path]::GetFullPath($M02DependencySourceRoot)
        dependency_source_root = [IO.Path]::GetFullPath($M02DependencySourceRoot)
        worker = [IO.Path]::GetFullPath($PersistentWorkerPath)
        gsn_producer = [IO.Path]::GetFullPath($PersistentProducerPath)
        gsn_source_root = [IO.Path]::GetFullPath((Join-Path $M02DependencySourceRoot "GeneralizedSasakiNakamura.jl"))
        angular_source_root = [IO.Path]::GetFullPath((Join-Path $M02DependencySourceRoot "SpinWeightedSpheroidalHarmonics.jl"))
        depot = [IO.Path]::GetFullPath($JuliaDepot)
        project = [IO.Path]::GetFullPath($JuliaProject)
        manifest_sha256 = Get-Sha256 (Join-Path $JuliaProject "Manifest.toml")
        worker_sha256 = Get-Sha256 $WorkerPath
        dependency_contract = $M02DependencyContract
        dependency_contract_sha256 = $M02DependencySha256
        dependency_contract_id = $M02DependencyId
        worker_contract = $M02WorkerContract
        worker_contract_sha256 = $M02WorkerSha256
        worker_contract_id = $M02WorkerId
        gsn_cache_contract = $M02GsnCacheContract
        gsn_cache_contract_sha256 = $M02GsnCacheSha256
        gsn_cache_id = $M02GsnCacheId
        contract_sha256 = $M02ContractSha256
        contract_id = $M02ContractId
        scientific_source_contract_id = $M02ContractId
    }
}

# -------------------------------------------------------------------- receipt

$runtimeMode = if ($PortableRuntime) { "portable" } else { "per-user" }
$receipt = [ordered]@{
    schema_version = 2
    policy_id = $Policy.policy_id
    policy_sha256 = $PolicySha256
    runtime_root = [IO.Path]::GetFullPath($RuntimeRoot)
    runtime_mode = $runtimeMode
    python = [ordered]@{
        version = [string]$VenvIdentity.version
        implementation = [string]$VenvIdentity.implementation
        bits = [int]$VenvIdentity.bits
        executable = [string]$VenvIdentity.executable
        venv = [IO.Path]::GetFullPath($VenvRoot)
        source_kind = $PythonSourceKind
        source_command = [string]$PythonSource.command
        source_arguments = @($PythonSource.arguments)
        source_executable = [string]$PythonSource.executable
        source_executable_sha256 = Get-Sha256 $PythonSource.executable
        managed_interpreter = $ManagedPython
    }
    numerical_kernel = [ordered]@{
        requested = [bool]$WithNumericalKernel
        packages = @($InstalledPackages)
    }
    julia_runtime = $JuliaReceipt
}
$receiptText = $receipt | ConvertTo-Json -Depth 20
$receiptText | Set-Content -LiteralPath $ReceiptPath -Encoding UTF8
$receiptText | Set-Content -LiteralPath $IdentityPath -Encoding UTF8
Write-Step "Wrote runtime receipt: $ReceiptPath"

# ------------------------------------------------------------------ smoke test

if (-not $SkipSmokeTest) {
    Write-Step "Verifying the solver launches"
    $env:PYTHONPATH = Join-Path $PackageRoot "src"
    $plan = Join-Path $PackageRoot "examples\evidence-plan.json"
    Invoke-NativeCapture $VenvPython @("-m", "windows_solver", "plan", $plan) | Out-Null
    Write-Step "solver plan succeeded"
}

Write-Host ""
Write-Host "Bootstrap complete. Run the solver with:" -ForegroundColor Green
Write-Host "    .\solver.ps1 plan .\examples\evidence-plan.json"
Write-Host "    .\solver.ps1 run .\examples\spectrum.json --store .\.solver-store"
if (-not $WithNumericalKernel) {
    Write-Host ""
    Write-Host "The native response kernel and the test suite additionally need numpy/scipy:"
    Write-Host "    .\runtime\bootstrap.ps1 -WithNumericalKernel"
}
if (-not $WithM02) {
    Write-Host ""
    Write-Host "The physical M02 campaign additionally needs Julia 1.10.11:"
    Write-Host "    .\runtime\bootstrap.ps1 -WithM02"
}
