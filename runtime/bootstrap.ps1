<#
.SYNOPSIS
Provision a package-local CPython for the Kerr QNM Windows solver.

.DESCRIPTION
Installs a pinned CPython into .runtime\ inside this repository and creates a
virtual environment that solver.ps1 uses in preference to any system Python.
Nothing is installed system-wide, no registry entry is written, PATH is not
modified, and no administrator rights are required.

Two tiers are provisioned:

  * default            CPython only.  This is everything the public CLI needs:
                       plan, run, verify, inspect, export, campaign-plan,
                       campaign-merge, campaign-smoke.
  * -WithNumericalKernel
                       adds the pinned numpy and scipy used by the native
                       response kernel and by the packaged test suite.

Re-running is safe.  Work already done is detected and skipped unless -Force
is given.

.EXAMPLE
Set-ExecutionPolicy -Scope Process Bypass -Force; .\runtime\bootstrap.ps1

.EXAMPLE
.\runtime\bootstrap.ps1 -WithNumericalKernel

.EXAMPLE
.\runtime\bootstrap.ps1 -Force
#>
param(
    [switch]$WithNumericalKernel,
    [switch]$WithM02,
    [switch]$Force,
    [switch]$SkipSmokeTest
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$PackageRoot = Split-Path -Parent $PSScriptRoot
$RuntimeRoot = Join-Path $PackageRoot ".runtime"
$DownloadRoot = Join-Path $RuntimeRoot "downloads"
$TempRoot = Join-Path $RuntimeRoot "tmp"
$UvRoot = Join-Path $RuntimeRoot "uv"
$UvExe = Join-Path $UvRoot "uv.exe"
$PythonInstallRoot = Join-Path $RuntimeRoot "python"
$VenvRoot = Join-Path $RuntimeRoot "venv"
$VenvPython = Join-Path $VenvRoot "Scripts\python.exe"
$JuliaRoot = Join-Path $RuntimeRoot "julia"
$JuliaExe = Join-Path $JuliaRoot "bin\julia.exe"
$JuliaDepot = Join-Path $RuntimeRoot "julia-depot"
$JuliaProject = Join-Path $RuntimeRoot "m02-julia-project"
$JuliaVendorRoot = Join-Path $RuntimeRoot "vendor"
$JuliaDataRoot = Join-Path $PackageRoot "src\windows_solver\data\julia"
$ReceiptPath = Join-Path $RuntimeRoot "python-runtime.json"
$PolicyPath = Join-Path $PSScriptRoot "runtime_policy.json"

function Write-Step([string]$Message) {
    Write-Host "[bootstrap] $Message"
}

function Get-Sha256([string]$Path) {
    return (Get-FileHash -Algorithm SHA256 -LiteralPath $Path).Hash.ToLowerInvariant()
}

function Invoke-Native([string]$FilePath, [string[]]$Arguments) {
    # A native command that writes to stderr becomes a terminating
    # NativeCommandError while ErrorActionPreference is Stop, which would abort
    # the bootstrap on harmless progress output.  Exit codes are the contract.
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

function Get-File([string]$Url, [string]$Destination) {
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Destination) | Out-Null
    Invoke-WebRequest -UseBasicParsing -Uri $Url -OutFile $Destination
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
$PythonVersion = $Policy.python.python_version
if ($WithM02) {
    $WithNumericalKernel = $true
}

if ($Force -and (Test-Path -LiteralPath $RuntimeRoot)) {
    Write-Step "Removing existing .runtime for a clean reprovision"
    Remove-Item -LiteralPath $RuntimeRoot -Recurse -Force
}
foreach ($path in @($RuntimeRoot, $DownloadRoot, $TempRoot)) {
    New-Item -ItemType Directory -Force -Path $path | Out-Null
}
# Keep interpreter and wheel unpacking inside the package so a locked-down or
# full %TEMP% cannot fail the run halfway through.
$env:TEMP = $TempRoot
$env:TMP = $TempRoot

# ------------------------------------------------------------------------- uv

if (-not (Test-Path -LiteralPath $UvExe -PathType Leaf)) {
    Write-Step "Downloading uv $($Policy.uv.version)"
    $archive = Join-Path $DownloadRoot $Policy.uv.archive
    $checksum = "$archive.sha256"
    Get-File $Policy.uv.url $archive
    Get-File $Policy.uv.checksum_url $checksum

    # Verify against the checksum published beside the release asset rather than
    # a digest copied into this repository, so the policy file never has to be
    # edited in lockstep with a uv upgrade.
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
    if (Test-Path -LiteralPath $extract) { Remove-Item -LiteralPath $extract -Recurse -Force }
    Expand-Archive -LiteralPath $archive -DestinationPath $extract
    $found = Get-ChildItem -LiteralPath $extract -Filter "uv.exe" -File -Recurse | Select-Object -First 1
    if ($null -eq $found) { throw "Verified uv archive contains no uv.exe." }
    New-Item -ItemType Directory -Force -Path $UvRoot | Out-Null
    Copy-Item -LiteralPath $found.FullName -Destination $UvExe -Force
    Remove-Item -LiteralPath $extract -Recurse -Force
}

# uv prints "uv <version> (<triple> <date>)"; compare the version token only.
$uvIdentity = Invoke-NativeCapture $UvExe @("--version")
if ($uvIdentity -notmatch '^uv\s+([0-9][^\s\)]*)') {
    throw "uv identity could not be read: '$uvIdentity'."
}
$uvVersion = $Matches[1]
if ($uvVersion -ne $Policy.uv.version) {
    throw "uv version mismatch: expected $($Policy.uv.version); received $uvVersion."
}
$UvSha256 = Get-Sha256 $UvExe

# --------------------------------------------------------------------- CPython

$env:UV_PYTHON_INSTALL_DIR = $PythonInstallRoot
$env:UV_CACHE_DIR = Join-Path $RuntimeRoot "uv-cache"

Write-Step "Installing package-local CPython $PythonVersion"
Invoke-Native $UvExe @(
    "python", "install", $PythonVersion,
    "--install-dir", $PythonInstallRoot,
    "--no-bin", "--no-registry", "--no-config", "--system-certs"
)

$ManagedPython = Invoke-NativeCapture $UvExe @(
    "python", "find", $PythonVersion,
    "--managed-python", "--no-python-downloads", "--no-project", "--no-config"
)
if (-not (Test-Path -LiteralPath $ManagedPython -PathType Leaf)) {
    throw "uv could not resolve package-local CPython ${PythonVersion}: '$ManagedPython'"
}

if (-not (Test-Path -LiteralPath $VenvPython -PathType Leaf)) {
    Write-Step "Creating .runtime\venv"
    Invoke-Native $UvExe @(
        "venv", $VenvRoot, "--python", $ManagedPython,
        "--managed-python", "--no-python-downloads", "--no-project", "--no-config"
    )
}

$identityText = Invoke-NativeCapture $VenvPython @(
    "-c",
    "import json,platform,struct,sys; print(json.dumps({'version':platform.python_version(),'implementation':platform.python_implementation(),'bits':struct.calcsize('P')*8,'executable':sys.executable}))"
)
$identity = $identityText | ConvertFrom-Json
if ($identity.version -ne $PythonVersion `
    -or $identity.implementation -ne $Policy.python.implementation `
    -or $identity.bits -ne $Policy.python.bits) {
    throw "Python identity mismatch: $($identity | ConvertTo-Json -Compress)"
}
Write-Step "CPython $($identity.version) $($identity.bits)-bit ready"

# ------------------------------------------------------- optional numerical tier

$installed = @()
if ($WithNumericalKernel) {
    Write-Step "Installing the pinned numerical kernel"
    $specifiers = @()
    foreach ($package in $Policy.numerical_kernel.packages) {
        $specifiers += "$($package.name)==$($package.version)"
    }
    if ($Policy.numerical_kernel.wheels.Count -gt 0) {
        # A populated wheels array means the digests have been frozen; install
        # offline from verified local bytes instead of resolving from an index.
        $wheelhouse = Join-Path $RuntimeRoot "wheelhouse"
        New-Item -ItemType Directory -Force -Path $wheelhouse | Out-Null
        foreach ($wheel in $Policy.numerical_kernel.wheels) {
            $destination = Join-Path $wheelhouse $wheel.filename
            if (-not (Test-Path -LiteralPath $destination -PathType Leaf) `
                -or (Get-Sha256 $destination) -ne $wheel.sha256) {
                Get-File $wheel.url $destination
            }
            $actual = Get-Sha256 $destination
            if ($actual -ne $wheel.sha256.ToLowerInvariant()) {
                throw "Wheel SHA-256 mismatch for $($wheel.filename). Expected $($wheel.sha256); received $actual."
            }
        }
        Invoke-Native $UvExe (@(
            "pip", "install", "--python", $VenvPython,
            "--no-index", "--find-links", $wheelhouse
        ) + $specifiers)
    }
    else {
        Invoke-Native $UvExe (@("pip", "install", "--python", $VenvPython) + $specifiers)
    }
    foreach ($package in $Policy.numerical_kernel.packages) {
        $observed = Invoke-NativeCapture $VenvPython @(
            "-c", "import importlib.metadata as m; print(m.version('$($package.name)'))"
        )
        if ($observed -ne $package.version) {
            throw "$($package.name) version mismatch: expected $($package.version); received $observed."
        }
        $installed += [ordered]@{ name = $package.name; version = $observed }
    }
    Write-Step "Numerical kernel ready"
}

# ------------------------------------------------------- package-local Julia

$JuliaReceipt = [ordered]@{ requested = [bool]$WithM02 }
if ($WithM02) {
    $JuliaArchive = Join-Path $DownloadRoot $Policy.julia.archive
    $ExpectedJuliaSha256 = $Policy.julia.sha256.ToLowerInvariant()
    if (-not (Test-Path -LiteralPath $JuliaArchive -PathType Leaf) `
        -or (Get-Sha256 $JuliaArchive) -ne $ExpectedJuliaSha256) {
        Write-Step "Downloading portable Julia $($Policy.julia.version)"
        Get-File $Policy.julia.url $JuliaArchive
    }
    $ActualJuliaSha256 = Get-Sha256 $JuliaArchive
    if ($ActualJuliaSha256 -ne $ExpectedJuliaSha256) {
        throw "Julia archive SHA-256 mismatch. Expected $ExpectedJuliaSha256; received $ActualJuliaSha256."
    }
    Write-Step "Julia archive verified ($ActualJuliaSha256)"

    if (-not (Test-Path -LiteralPath $JuliaExe -PathType Leaf)) {
        $JuliaExtract = Join-Path $TempRoot "julia-extract"
        if (Test-Path -LiteralPath $JuliaExtract) {
            cmd.exe /c rd /s /q "\\?\$JuliaExtract"
            if ($LASTEXITCODE -ne 0 -and (Test-Path -LiteralPath $JuliaExtract)) {
                throw "Could not remove previous Julia extraction directory: $JuliaExtract"
            }
        }
        New-Item -ItemType Directory -Force -Path $JuliaExtract | Out-Null

        $Tar = Get-Command tar.exe -ErrorAction SilentlyContinue
        if ($null -eq $Tar) {
            throw "Windows tar.exe is required to extract the portable Julia runtime."
        }

        & $Tar.Source -xf $JuliaArchive -C $JuliaExtract
        if ($LASTEXITCODE -ne 0) {
            throw "Julia archive extraction failed with tar.exe exit code $LASTEXITCODE."
        }

        $FoundJulia = Get-ChildItem -LiteralPath $JuliaExtract -Filter "julia.exe" -File -Recurse |
            Select-Object -First 1
        if ($null -eq $FoundJulia) {
            throw "Verified Julia archive contains no julia.exe."
        }
        $ExtractedJuliaRoot = Split-Path -Parent (Split-Path -Parent $FoundJulia.FullName)
        if (Test-Path -LiteralPath $JuliaRoot) {
            cmd.exe /c rd /s /q "\\?\$JuliaRoot"
            if ($LASTEXITCODE -ne 0 -and (Test-Path -LiteralPath $JuliaRoot)) {
                throw "Could not remove previous Julia runtime directory: $JuliaRoot"
            }
        }
        Copy-Item -LiteralPath $ExtractedJuliaRoot -Destination $JuliaRoot -Recurse -Force
        cmd.exe /c rd /s /q "\\?\$JuliaExtract"
        if ($LASTEXITCODE -ne 0 -and (Test-Path -LiteralPath $JuliaExtract)) {
            throw "Could not remove Julia extraction directory after installation: $JuliaExtract"
        }
    }

    $JuliaIdentity = Invoke-NativeCapture $JuliaExe @("--version")
    if ($JuliaIdentity -ne "julia version $($Policy.julia.version)") {
        throw "Julia identity mismatch: expected $($Policy.julia.version); received '$JuliaIdentity'."
    }
    $SourceReceipts = @()
    foreach ($Source in $Policy.scientific_sources) {
        $SourcePath = Join-Path $PackageRoot $Source.path
        if (-not (Test-Path -LiteralPath $SourcePath -PathType Leaf)) {
            throw "Required scientific source is absent: $SourcePath"
        }
        $ActualSourceSha256 = Get-Sha256 $SourcePath
        $SourceReceipts += [ordered]@{
            id = [string]$Source.id
            path = [IO.Path]::GetFullPath($SourcePath)
            sha256 = $ActualSourceSha256
        }
    }

    Write-Step "Preparing the pinned M02 Julia project"
    if (Test-Path -LiteralPath $JuliaVendorRoot) {
        Remove-Item -LiteralPath $JuliaVendorRoot -Recurse -Force
    }
    New-Item -ItemType Directory -Force -Path $JuliaVendorRoot | Out-Null
    Copy-Item -LiteralPath (Join-Path $JuliaDataRoot "GeneralizedSasakiNakamura.jl") `
        -Destination $JuliaVendorRoot -Recurse -Force
    Copy-Item -LiteralPath (Join-Path $JuliaDataRoot "SpinWeightedSpheroidalHarmonics.jl") `
        -Destination $JuliaVendorRoot -Recurse -Force
    New-Item -ItemType Directory -Force -Path $JuliaProject | Out-Null
    Copy-Item -LiteralPath (Join-Path $JuliaDataRoot "m02_project\Project.toml") `
        -Destination (Join-Path $JuliaProject "Project.toml") -Force
    $RuntimeManifest = Join-Path $JuliaProject "Manifest.toml"
    if (-not (Test-Path -LiteralPath $RuntimeManifest -PathType Leaf)) {
        Copy-Item -LiteralPath (Join-Path $JuliaDataRoot "m02_project\Manifest.seed.toml") `
            -Destination $RuntimeManifest -Force
    }
    New-Item -ItemType Directory -Force -Path $JuliaDepot | Out-Null
    $env:JULIA_DEPOT_PATH = $JuliaDepot
    $env:JULIA_PKG_PRECOMPILE_AUTO = "0"
    $env:M02_GSN_SOURCE = Join-Path $JuliaVendorRoot "GeneralizedSasakiNakamura.jl"
    $env:M02_ANGULAR_SOURCE = Join-Path $JuliaVendorRoot "SpinWeightedSpheroidalHarmonics.jl"
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
    Invoke-Native $JuliaExe @(
        "--startup-file=no",
        "--history-file=no",
        "--project=$JuliaProject",
        $SetupScript
    )
    Remove-Item -LiteralPath $SetupScript -Force
    $WorkerPath = Join-Path $JuliaDataRoot "m02_worker.jl"
    Invoke-Native $JuliaExe @(
        "--startup-file=no",
        "--history-file=no",
        "--project=$JuliaProject",
        $WorkerPath,
        "--probe"
    )
    $JuliaReceipt = [ordered]@{
        requested = $true
        version = [string]$Policy.julia.version
        executable = [IO.Path]::GetFullPath($JuliaExe)
        executable_sha256 = Get-Sha256 $JuliaExe
        archive = [IO.Path]::GetFullPath($JuliaArchive)
        archive_sha256 = $ActualJuliaSha256
        sources = @($SourceReceipts)
        depot = [IO.Path]::GetFullPath($JuliaDepot)
        project = [IO.Path]::GetFullPath($JuliaProject)
        manifest_sha256 = Get-Sha256 (Join-Path $JuliaProject "Manifest.toml")
        worker_sha256 = Get-Sha256 $WorkerPath
    }
    Write-Step "Julia runtime, pinned GSN sources, and precision worker ready"
}

# -------------------------------------------------------------------- receipt

$receipt = [ordered]@{
    schema_version = 1
    policy_id = $Policy.policy_id
    policy_sha256 = $PolicySha256
    uv = [ordered]@{ version = $uvVersion; executable = $UvExe; sha256 = $UvSha256 }
    python = [ordered]@{
        version = [string]$identity.version
        implementation = [string]$identity.implementation
        bits = [int]$identity.bits
        executable = [string]$identity.executable
        venv = $VenvRoot
        managed_interpreter = $ManagedPython
    }
    numerical_kernel = [ordered]@{
        requested = [bool]$WithNumericalKernel
        packages = @($installed)
    }
    julia_runtime = $JuliaReceipt
}
$receipt | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $ReceiptPath -Encoding UTF8
Write-Step "Wrote $ReceiptPath"

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
    Write-Host "The physical M02 campaign additionally needs package-local Julia:"
    Write-Host "    .\runtime\bootstrap.ps1 -WithM02"
}
