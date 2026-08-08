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
