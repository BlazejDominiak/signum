param([Parameter(Mandatory=$true)][string]$OutputPath)
$ErrorActionPreference = 'Stop'
# Read-only discovery: no fixed version, no starts, downloads or drive scans.
$candidates = [System.Collections.Generic.List[string]]::new()
function Add-Candidate([string]$value) {
    if ($value) { $candidates.Add([Environment]::ExpandEnvironmentVariables($value)) }
}
$config = $null
try { $config = Get-Content (Join-Path $env:APPDATA 'Signum\settings.json') -Raw | ConvertFrom-Json } catch {}
if ($config.ollama_runtime_dir) {
    Add-Candidate (Join-Path $config.ollama_runtime_dir 'ollama.exe')
    try {
        $manifest = Get-Content (Join-Path $config.ollama_runtime_dir 'runtime.json') -Raw | ConvertFrom-Json
        Add-Candidate $manifest.external_executable
    } catch {}
}
foreach ($command in @(Get-Command ollama.exe -CommandType Application -ErrorAction SilentlyContinue)) {
    Add-Candidate $command.Source
}
try {
    foreach ($process in @(Get-CimInstance Win32_Process -Filter "Name = 'ollama.exe' OR Name = 'ollama app.exe'")) {
        if ($process.ExecutablePath) { Add-Candidate (Join-Path (Split-Path $process.ExecutablePath) 'ollama.exe') }
    }
} catch {}
foreach ($registryRoot in @(
    'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*',
    'HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*',
    'HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*'
)) {
    foreach ($entry in @(Get-ItemProperty $registryRoot -ErrorAction SilentlyContinue)) {
        if ($entry.DisplayName -notlike '*Ollama*') { continue }
        if ($entry.InstallLocation) { Add-Candidate (Join-Path $entry.InstallLocation 'ollama.exe') }
        foreach ($value in @($entry.DisplayIcon, $entry.UninstallString)) {
            if ($value -match '^"([^"]+)"|^(.+?\.exe)') {
                $exe = if ($Matches[1]) { $Matches[1] } else { $Matches[2] }
                Add-Candidate (Join-Path (Split-Path $exe) 'ollama.exe')
            }
        }
    }
}
foreach ($root in @($env:LOCALAPPDATA, $env:ProgramFiles, ${env:ProgramFiles(x86)})) {
    if ($root) {
        Add-Candidate (Join-Path $root 'Ollama\ollama.exe')
        Add-Candidate (Join-Path $root 'Programs\Ollama\ollama.exe')
    }
}
$executable = ''
foreach ($candidate in $candidates) {
    if (Test-Path -LiteralPath $candidate -PathType Leaf) { $executable = $candidate; break }
}
$urls = [System.Collections.Generic.List[string]]::new()
function Add-LocalUrl([string]$value) {
    try {
        if ($value -notmatch '^https?://') { $value = 'http://' + $value }
        $uri = [Uri]$value
        if ($uri.IsLoopback -and -not $uri.UserInfo) { $urls.Add($value.TrimEnd('/')) }
    } catch {}
}
if ($config.ollama_url) { Add-LocalUrl $config.ollama_url }
if ($env:OLLAMA_HOST) { Add-LocalUrl $env:OLLAMA_HOST }
Add-LocalUrl 'http://127.0.0.1:11434'
$serviceUrl = ''
$models = @()
$modelsKnown = $false
# WebClient does not follow system proxy settings or send credentials.
foreach ($url in @($urls | Select-Object -Unique)) {
    try {
        $request = [Net.HttpWebRequest]::Create($url + '/api/tags')
        $request.Proxy = $null
        $request.AllowAutoRedirect = $false
        $request.Timeout = 1500
        $response = $request.GetResponse()
        try {
            $reader = [IO.StreamReader]::new($response.GetResponseStream())
            try { $data = $reader.ReadToEnd() | ConvertFrom-Json } finally { $reader.Dispose() }
        } finally { $response.Dispose() }
        if ($null -eq $data.models) { continue }
        $models = @($data.models | ForEach-Object { $_.name })
        $serviceUrl = $url
        $modelsKnown = $true
        break
    } catch {}
}
# A stopped installation can still have models. Read manifests and verify blobs.
$modelRoots = @($env:OLLAMA_MODELS,
    [Environment]::GetEnvironmentVariable('OLLAMA_MODELS', 'User'),
    [Environment]::GetEnvironmentVariable('OLLAMA_MODELS', 'Machine'),
    (Join-Path $env:USERPROFILE '.ollama\models'))
if ($config.ollama_runtime_dir) {
    $modelRoots += Join-Path (Split-Path $config.ollama_runtime_dir) 'models\ollama'
}
foreach ($root in @($modelRoots | Where-Object { $_ } | Select-Object -Unique)) {
    if (-not (Test-Path -LiteralPath (Join-Path $root 'manifests') -PathType Container)) { continue }
    $modelsKnown = $true
    foreach ($tag in @('e2b', '12b')) {
        try {
            $manifest = Get-Content (Join-Path $root "manifests\registry.ollama.ai\library\gemma4\$tag") -Raw | ConvertFrom-Json
            $complete = $true
            foreach ($layer in @($manifest.config) + @($manifest.layers)) {
                $blob = $layer.digest -replace ':', '-'
                if (-not $blob -or -not (Test-Path -LiteralPath (Join-Path $root "blobs\$blob") -PathType Leaf)) { $complete = $false }
            }
            if ($complete) { $models += "gemma4:$tag" }
        } catch {}
    }
}
$jevReady = $false
# Signum's saved runtime path is portable; do not require this computer's versions.
if ($config.vjev_runtime_dir) {
    try {
        $manifest = Get-Content (Join-Path $config.vjev_runtime_dir 'runtime.json') -Raw | ConvertFrom-Json
        $index = Get-Content (Join-Path $manifest.model_dir 'model.safetensors.index.json') -Raw | ConvertFrom-Json
        $required = @('config.json','processor_config.json','tokenizer.json','head.pt','vjev.json')
        $required += @($index.weight_map.PSObject.Properties.Value | Select-Object -Unique)
        $jevReady = (Test-Path -LiteralPath $manifest.python -PathType Leaf) -and
            (Test-Path -LiteralPath (Join-Path $manifest.packages 'vjev\server.py') -PathType Leaf)
        foreach ($name in $required) {
            if (-not (Test-Path -LiteralPath (Join-Path $manifest.model_dir $name) -PathType Leaf)) { $jevReady = $false }
        }
    } catch { $jevReady = $false }
}
$jevK5Ready = $false
if ($config.classification_jev_python -and $config.classification_jev_model_dir -and $config.classification_jev_runtime) {
    $jevK5Ready = (Test-Path -LiteralPath $config.classification_jev_python -PathType Leaf) -and
        (Test-Path -LiteralPath (Join-Path $config.classification_jev_runtime 'jevk5\__init__.py') -PathType Leaf) -and
        (Test-Path -LiteralPath (Join-Path $config.classification_jev_model_dir 'model.safetensors') -PathType Leaf) -and
        (Test-Path -LiteralPath (Join-Path $config.classification_jev_model_dir 'tokenizer.json') -PathType Leaf)
}
$result = @($executable, $serviceUrl, [string][int]($models -contains 'gemma4:e2b'),
    [string][int]($models -contains 'gemma4:12b'), [string][int]$jevReady, [string][int]$modelsKnown, [string][int]$jevK5Ready)
[IO.File]::WriteAllLines($OutputPath, $result, [Text.UTF8Encoding]::new($true))
