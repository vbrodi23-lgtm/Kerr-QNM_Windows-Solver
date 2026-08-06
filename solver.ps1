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

$BundledPython = Join-Path $PSScriptRoot ".runtime\python\python.exe"
function Test-Python312 {
    param(
        [string]$Executable,
        [string[]]$PrefixArguments
    )
    & $Executable @PrefixArguments -c "import sys; raise SystemExit(sys.version_info < (3, 12))" *> $null
    return $LASTEXITCODE -eq 0
}

$PythonExecutable = $null
$PythonPrefixArguments = @()
if ((Test-Path $BundledPython) -and (Test-Python312 -Executable $BundledPython -PrefixArguments @())) {
    $PythonExecutable = $BundledPython
}
else {
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
    throw "Python 3.12 or newer is required and was not found."
}

& $PythonExecutable @PythonPrefixArguments -m windows_solver @SolverArguments
exit $LASTEXITCODE
