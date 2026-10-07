param(
    [string]$Sample = '',
    [string]$File = '',
    [string]$Protocol = '',
    [switch]$List
)
$ErrorActionPreference = 'Stop'
$projectDirectory = Split-Path -Parent $PSScriptRoot
$pythonPath = 'C:\Users\B\AppData\Local\Programs\Python\Python313\python.exe'
$previousPythonPath = $env:PYTHONPATH
$previousPythonUtf8 = $env:PYTHONUTF8
try {
    $env:PYTHONPATH = "$projectDirectory\src;$projectDirectory\.venv\Lib\site-packages"
    $env:PYTHONUTF8 = '1'
    $demoArguments = @((Join-Path $PSScriptRoot 'venice_demo.py'))
    if ($List) { $demoArguments += '--list' }
    elseif ($File) { $demoArguments += @('--file', $File) }
    elseif ($Sample) { $demoArguments += @('--sample', $Sample) }
    if ($Protocol) { $demoArguments += @('--protocol', $Protocol) }
    & $pythonPath @demoArguments
    $demoExitCode = $LASTEXITCODE
} finally {
    $env:PYTHONPATH = $previousPythonPath
    $env:PYTHONUTF8 = $previousPythonUtf8
}
exit $demoExitCode
