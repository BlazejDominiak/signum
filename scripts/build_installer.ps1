# Buduje aplikację (PyInstaller) i instalator Windows (Inno Setup).
# Użycie (z katalogu głównego repozytorium):
#   powershell -ExecutionPolicy Bypass -File scripts\build_installer.ps1

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root ".venv\Scripts\python.exe"

# Wersja z jednego źródła prawdy: src/signum/__init__.py
$version = & $python -c "import signum; print(signum.__version__)"
Write-Host "=== Signum $version ===" -ForegroundColor Cyan

& $python (Join-Path $root "scripts\check_local_documents.py")
if ($LASTEXITCODE -ne 0) { throw "Lokalne dokumenty nie mogą trafić do wydania" }

Write-Host "[1/3] PyInstaller (dist\Signum)..." -ForegroundColor Cyan
# Budowanie z terminala z dodatkowymi narzędziami w PATH może spakować obce DLL
# (np. UCRT z Windows 11), które uniemożliwiają start programu na Windows 10.
$pythonBaseDir = & $python -c "import sys; print(sys.base_prefix)"
$signumOriginalPath = $env:PATH
try {
    $env:PATH = @(
        (Split-Path -Parent $python),
        $pythonBaseDir,
        (Join-Path $pythonBaseDir "DLLs"),
        (Join-Path $env:SystemRoot "System32"),
        $env:SystemRoot
    ) -join ";"
    & $python -m PyInstaller (Join-Path $root "packaging\signum.spec") `
        --clean --noconfirm --distpath (Join-Path $root "dist") --workpath (Join-Path $root "build")
} finally {
    $env:PATH = $signumOriginalPath
}
if ($LASTEXITCODE -ne 0) { throw "PyInstaller zakończył się błędem" }

& $python (Join-Path $root "scripts\check_local_documents.py") --bundle (Join-Path $root "dist\Signum")
if ($LASTEXITCODE -ne 0) { throw "Pakiet zawiera lokalne dokumenty — przerwano budowę instalatora" }

Write-Host "[2/3] Test dymny zbudowanego exe..." -ForegroundColor Cyan
$exe = Join-Path $root "dist\Signum\Signum.exe"
if (-not (Test-Path $exe)) { throw "Brak $exe" }
$smoke = Start-Process -FilePath $exe -ArgumentList "--self-test" -PassThru -WindowStyle Hidden
if (-not $smoke.WaitForExit(60000)) {
    $smoke.Kill()
    $smoke.WaitForExit()
    throw "Test spakowanego runtime'u nie zakończył się w ciągu 60 sekund"
}
if ($smoke.ExitCode -ne 0) {
    throw "Test spakowanego runtime'u zakończył się kodem $($smoke.ExitCode)"
}

Write-Host "[3/3] Inno Setup..." -ForegroundColor Cyan
$iscc = @(
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) { throw "Nie znaleziono ISCC.exe — zainstaluj Inno Setup 6" }

& $iscc (Join-Path $root "installer\signum.iss") /DMyAppVersion=$version
if ($LASTEXITCODE -ne 0) { throw "ISCC zakończył się błędem" }

$setup = Join-Path $root "installer\output\Signum-Setup-$version.exe"
Write-Host "Gotowe: $setup" -ForegroundColor Green
$hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $setup).Hash
Write-Host "SHA-256: $hash" -ForegroundColor Green
$signature = Get-AuthenticodeSignature -LiteralPath $setup
if ($signature.Status -ne "Valid") {
    Write-Warning "Instalator nie ma ważnego podpisu Authenticode. Nie publikuj go jako oficjalnego wydania bez podpisania certyfikatem wydawcy."
}
