@echo off
setlocal EnableExtensions DisableDelayedExpansion
title Build AutoFarmSeal

rem Double-click for normal use. --no-pause is for automated Windows builds.
rem Reuse scripts\build.ps1 so tests and packaging have one source of truth.
rem This does not install Python, change branches, or request administrator access.
set "EXIT_CODE=1"
set "DID_PUSHD="
set "NO_PAUSE="
if /I "%~1"=="--no-pause" set "NO_PAUSE=1"

pushd "%~dp0" >nul 2>&1
if errorlevel 1 goto bad_directory
set "DID_PUSHD=1"

if not exist "pyproject.toml" goto missing_repo
if not exist "AutoFarmSeal.spec" goto missing_repo
if not exist "scripts\build.ps1" goto missing_repo
set "POWERSHELL=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"
if not exist "%POWERSHELL%" goto missing_powershell

echo ============================================================
echo   BUILD AUTOFARMSEAL - WINDOWS
echo ============================================================
echo Folder repo: "%CD%"
echo.
echo Tutup AutoFarmSeal.exe yang sedang berjalan sebelum build.
echo Python 3.12 x64 dan Python Launcher harus sudah terpasang
echo bila belum ada environment .venv yang dapat digunakan.
echo Internet diperlukan untuk mengunduh dependency yang belum ada.
echo.
echo Proses: siapkan Python lokal, pasang dependency, tes, buat EXE.
echo Tunggu sampai proses selesai; jangan tutup jendela.
echo.

rem ExecutionPolicy applies to this child process only, not system settings.
"%POWERSHELL%" -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\build.ps1"
set "EXIT_CODE=%ERRORLEVEL%"
if not "%EXIT_CODE%"=="0" goto build_failed
if not exist "dist\AutoFarmSeal\AutoFarmSeal.exe" goto missing_output
if not exist "dist\AutoFarmSeal\_internal\" goto missing_output

echo.
echo ============================================================
echo   BUILD BERHASIL
echo ============================================================
echo Buka: "%CD%\dist\AutoFarmSeal\AutoFarmSeal.exe"
echo.
echo Untuk dibagikan, ZIP SELURUH folder dist\AutoFarmSeal.
echo Jangan memindahkan EXE tanpa folder _internal.
set "EXIT_CODE=0"
goto finish

:bad_directory
echo [ERROR] Folder build.bat tidak dapat dibuka.
goto finish

:missing_repo
echo [ERROR] Letakkan build.bat di folder UTAMA source repo AutoFarmSeal.
echo File ini harus sejajar dengan pyproject.toml dan AutoFarmSeal.spec.
echo Folder scripts dengan build.ps1 juga harus tersedia.
echo Ini bukan file untuk diletakkan di folder dist atau paket EXE saja.
goto finish

:missing_powershell
echo [ERROR] Windows PowerShell tidak ditemukan pada komputer ini.
echo Tidak ada perubahan pengaturan Windows yang dilakukan.
goto finish

:missing_output
set "EXIT_CODE=1"
echo [ERROR] Skrip selesai, tetapi EXE atau folder _internal tidak ditemukan.
goto build_failed

:build_failed
echo.
echo ============================================================
echo   BUILD GAGAL - kode %EXIT_CODE%
echo ============================================================
echo Baca pesan error di atas; hasil build lama bukan hasil build baru.
echo Bila Python tidak ditemukan, pasang Python 3.12 x64 dan Launcher.
echo Bila file terkunci, tutup AutoFarmSeal yang sedang berjalan.
echo Simpan screenshot pesan error sebelum menutup jendela ini.

:finish
echo.
if defined DID_PUSHD popd
if not defined NO_PAUSE pause
endlocal & exit /b %EXIT_CODE%
