# Run only on a disposable, hosted Windows runner; never against a user's installation.
param([Parameter(Mandatory=$true)][string]$Installer)
$ErrorActionPreference = 'Stop'
if ($env:GITHUB_ACTIONS -ne 'true' -or $env:RUNNER_ENVIRONMENT -ne 'github-hosted') {
    throw 'Installer smoke tests require a disposable GitHub-hosted runner.'
}
$workspace = Join-Path $env:RUNNER_TEMP ('signum-smoke-' + [Guid]::NewGuid().ToString('N'))
$application = Join-Path $workspace 'Application'
$models = Join-Path $workspace 'External AI'
New-Item -ItemType Directory -Path $workspace,$models | Out-Null
$sentinel = Join-Path $models 'keep.txt'
Set-Content -LiteralPath $sentinel -Value 'External user data'
function Run-Checked([string]$Executable, [string[]]$Arguments, [int]$Expected = 0) {
    $process = Start-Process -FilePath $Executable -ArgumentList $Arguments `
        -PassThru -WindowStyle Hidden
    if (-not $process.WaitForExit(180000)) {
        $process.Kill()
        throw "Process timeout: $Executable"
    }
    if ($process.ExitCode -ne $Expected) {
        throw "Expected $Expected, got $($process.ExitCode): $Executable"
    }
}
$common = @('/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART','/ACKNOWLEDGERISKS=1',
    ('/DIR="{0}"' -f $application))
Run-Checked $Installer ($common + @('/COMPONENTS=app',('/AIDIR="{0}"' -f $models),
    ('/LOG="{0}"' -f (Join-Path $workspace 'install.log'))))
$exe = Join-Path $application 'Signum.exe'
Run-Checked $exe @('--self-test')
$upgradeLog = Join-Path $workspace 'upgrade.log'
Run-Checked $Installer ($common + @('/COMPONENTS=app',('/LOG="{0}"' -f $upgradeLog)))
if (-not (Select-String -LiteralPath $upgradeLog -SimpleMatch -Pattern ('AI storage: ' + $models))) {
    throw 'Upgrade forgot the selected AI storage directory.'
}
# A deterministic preparation failure before any model/network activity must reach the parent.
$blocked = Join-Path $workspace 'not-a-directory'
Set-Content -LiteralPath $blocked -Value 'file'
Run-Checked $Installer ($common + @('/COMPONENTS=app,ollama',('/AIDIR="{0}"' -f $blocked),
    ('/LOG="{0}"' -f (Join-Path $workspace 'partial-failure.log')))) 10
Run-Checked (Join-Path $application 'unins000.exe') @('/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART')
if (Test-Path -LiteralPath $exe) { throw 'Uninstaller left the executable behind.' }
if (-not (Test-Path -LiteralPath $sentinel)) { throw 'Uninstaller removed external AI data.' }
Write-Host "Installer smoke tests passed. Logs: $workspace"
