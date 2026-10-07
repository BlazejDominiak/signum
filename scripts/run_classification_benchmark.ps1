param(
    [ValidateSet('venice', 'gemma', 'jevk5')]
    [string]$Model = 'venice',
    [ValidateRange(1, 100)]
    [int]$Repeats = 1
)
$ErrorActionPreference = 'Stop'
$projectDirectory = Split-Path -Parent $PSScriptRoot
$previousPythonPath = $env:PYTHONPATH
$previousPythonUtf8 = $env:PYTHONUTF8
try {
    $env:PYTHONUTF8 = '1'
    if ($Model -eq 'jevk5') {
        $pythonPath = 'C:\Users\B\AppData\Local\Programs\Python\Python311\python.exe'
        $env:PYTHONPATH = 'H:\Tools\SignumJev\packages;H:\Tools\JevK5'
    } else {
        $pythonPath = 'C:\Users\B\AppData\Local\Programs\Python\Python313\python.exe'
        $env:PYTHONPATH = "$projectDirectory\src;$projectDirectory\.venv\Lib\site-packages"
    }
    # Keep live-demo results apart from the recorded three-pass benchmark.
    $sourceDirectory = Join-Path $projectDirectory 'scratch\jevk5-classification-100x12'
    $demoDirectory = Join-Path $projectDirectory 'scratch\classification-live-demo'
    New-Item -ItemType Directory -Path $demoDirectory -Force | Out-Null
    Copy-Item -LiteralPath (Join-Path $sourceDirectory 'protocol.json') -Destination (Join-Path $demoDirectory 'protocol.json') -Force
    & $pythonPath (Join-Path $PSScriptRoot 'benchmark_jevk5_classification.py') $Model --output-dir $demoDirectory --repeats $Repeats
    $demoExitCode = $LASTEXITCODE
} finally {
    $env:PYTHONPATH = $previousPythonPath
    $env:PYTHONUTF8 = $previousPythonUtf8
}
exit $demoExitCode
