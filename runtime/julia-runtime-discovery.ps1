function Get-JuliaCandidate(
    [string]$Executable,
    [string[]]$PrefixArguments = @(),
    [string]$Source
) {
    if ([string]::IsNullOrWhiteSpace($Executable) -or -not (Test-Path -LiteralPath $Executable -PathType Leaf)) {
        return $null
    }

    # A Juliaup WindowsApps command is a launcher alias. Validate through it,
    # then switch durable execution and hashing to Julia's real binary.
    $launcher = [IO.Path]::GetFullPath($Executable)
    $identity = Try-InvokeNativeCapture $launcher (@($PrefixArguments) + @("--version"))
    if ($identity -ne "julia version $($Policy.julia.version)") {
        return $null
    }
    $bits = Try-InvokeNativeCapture $launcher (@($PrefixArguments) + @(
        "--startup-file=no", "--history-file=no", "-e", "print(Sys.WORD_SIZE)"
    ))
    if ($bits -ne "64") {
        return $null
    }
    $bindir = Try-InvokeNativeCapture $launcher (@($PrefixArguments) + @(
        "--startup-file=no", "--history-file=no", "-e", "print(Sys.BINDIR)"
    ))
    if ([string]::IsNullOrWhiteSpace($bindir)) {
        return $null
    }
    try {
        $runtimeExecutable = [IO.Path]::GetFullPath((Join-Path $bindir "julia.exe"))
    }
    catch {
        return $null
    }
    if (-not (Test-Path -LiteralPath $runtimeExecutable -PathType Leaf)) {
        return $null
    }
    $runtimeIdentity = Try-InvokeNativeCapture $runtimeExecutable @("--version")
    $runtimeBits = Try-InvokeNativeCapture $runtimeExecutable @(
        "--startup-file=no", "--history-file=no", "-e", "print(Sys.WORD_SIZE)"
    )
    if ($runtimeIdentity -ne "julia version $($Policy.julia.version)" -or $runtimeBits -ne "64") {
        return $null
    }
    $launcherKind = if ($launcher -match '(?i)\\WindowsApps\\') {
        "windowsapps-juliaup-shim"
    }
    else {
        "direct"
    }
    return [ordered]@{
        executable = $runtimeExecutable
        executable_sha256 = Get-Sha256 $runtimeExecutable
        arguments = @()
        source = $Source
        launcher = $launcher
        launcher_arguments = @($PrefixArguments)
        launcher_kind = $launcherKind
        version = [string]$Policy.julia.version
        bits = [int]$runtimeBits
    }
}
