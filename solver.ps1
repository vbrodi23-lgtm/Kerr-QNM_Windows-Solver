param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$SolverArguments
)

$ErrorActionPreference = "Stop"
$SourceDirectory = Join-Path $PSScriptRoot "src"
if ($env:PYTHONPATH) {
    $env:PYTHONPATH = "$SourceDirectory;$env:PYTHONPATH"
}
else {
    $env:PYTHONPATH = $SourceDirectory
}

$BootstrapPython = Join-Path $PSScriptRoot ".runtime\venv\Scripts\python.exe"
$BundledPython = Join-Path $PSScriptRoot ".runtime\python\python.exe"
function Test-Python312 {
    param(
        [string]$Executable,
        [string[]]$PrefixArguments
    )
    # A candidate that writes to stderr — notably the Windows App Execution
    # Alias stub for python.exe — raises a terminating NativeCommandError while
    # ErrorActionPreference is Stop.  That would abort the launcher inside the
    # probe instead of moving on to the next candidate, so the probe owns its
    # own preference and reports failure through the exit code alone.
    $previous = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        & $Executable @PrefixArguments -c "import sys; raise SystemExit(sys.version_info < (3, 12))" *> $null
        return $LASTEXITCODE -eq 0
    }
    catch {
        return $false
    }
    finally {
        $ErrorActionPreference = $previous
    }
}

$PythonExecutable = $null
$PythonPrefixArguments = @()
foreach ($Candidate in @($BootstrapPython, $BundledPython)) {
    if ((Test-Path $Candidate) -and (Test-Python312 -Executable $Candidate -PrefixArguments @())) {
        $PythonExecutable = $Candidate
        break
    }
}
if (-not $PythonExecutable) {
    $PythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if ($PythonCommand -and (Test-Python312 -Executable $PythonCommand.Source -PrefixArguments @())) {
        $PythonExecutable = $PythonCommand.Source
    }
    else {
        $PyCommand = Get-Command py -ErrorAction SilentlyContinue
        if ($PyCommand -and (Test-Python312 -Executable $PyCommand.Source -PrefixArguments @("-3"))) {
            $PythonExecutable = $PyCommand.Source
            $PythonPrefixArguments = @("-3")
        }
    }
}

if (-not $PythonExecutable) {
    throw @"
Python 3.12 or newer is required and was not found.

Provision a package-local runtime without installing anything system-wide:

    .\runtime\bootstrap.ps1

If 'python' on PATH prints "Python was not found; run without arguments to
install from the Microsoft Store", that is the Windows App Execution Alias
stub rather than a real interpreter.  The bootstrap above does not depend on
it.  To stop it shadowing a real install, turn off python.exe and python3.exe
under Settings > Apps > Advanced app settings > App execution aliases.
"@
}

& $PythonExecutable @PythonPrefixArguments -m windows_solver @SolverArguments
exit $LASTEXITCODE
