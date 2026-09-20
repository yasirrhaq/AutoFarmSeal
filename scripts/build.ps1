$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
if (-not (Test-Path '.venv\Scripts\python.exe')) {
    py -3.12 -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Install Python 3.12 x64 terlebih dahulu.' }
}
$Python = '.\.venv\Scripts\python.exe'
& $Python -m pip install -e '.[dev,build]'
if ($LASTEXITCODE -ne 0) { throw 'Instalasi dependency gagal.' }
& $Python -m pytest -q
if ($LASTEXITCODE -ne 0) { throw 'Pengujian gagal; build dibatalkan.' }
& $Python -m PyInstaller --noconfirm --clean AutoFarmSeal.spec
if ($LASTEXITCODE -ne 0) { throw 'Build gagal.' }
Write-Host 'Hasil: dist\AutoFarmSeal\AutoFarmSeal.exe. Distribusikan seluruh folder, bukan exe saja.'
