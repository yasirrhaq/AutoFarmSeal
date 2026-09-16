"""Run the BAT through real cmd/PowerShell on Windows, without installing anything.

Temporary build.ps1 fixtures simulate success/failure, not an actual application
build. CI separately builds the real application using the same batch launcher.
"""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows cmd/PowerShell required")
BATCH = Path(__file__).resolve().parents[1] / "build.bat"


def fixture_repo(tmp_path: Path, script: str) -> Path:
    root = tmp_path / "Repo with spaces & (brackets)!"
    (root / "scripts").mkdir(parents=True)
    shutil.copyfile(BATCH, root / "build.bat")
    (root / "pyproject.toml").touch()
    (root / "AutoFarmSeal.spec").touch()
    (root / "scripts" / "build.ps1").write_text(script, encoding="utf-8")
    return root


def run_batch(root: Path, cwd: Path) -> subprocess.CompletedProcess:
    # Use cmd CALL to support the same quoted-path invocation as a terminal/CI.
    return subprocess.run(
        [os.environ.get("COMSPEC", "cmd.exe"), "/d", "/c",
         f'call "{root / "build.bat"}" --no-pause'],
        cwd=cwd, capture_output=True, text=True, errors="replace", timeout=30,
        stdin=subprocess.DEVNULL, check=False,
    )


def test_batch_runs_from_its_own_directory_and_checks_output(tmp_path):
    root = fixture_repo(tmp_path, r"""
$ErrorActionPreference = 'Stop'
if ((Get-Location).Path -ne (Split-Path $PSScriptRoot -Parent)) { exit 31 }
New-Item -ItemType Directory -Force 'dist/AutoFarmSeal/_internal' | Out-Null
Set-Content 'dist/AutoFarmSeal/AutoFarmSeal.exe' 'test fixture, not executable'
exit 0
""")
    result = run_batch(root, tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "BUILD BERHASIL" in result.stdout
    assert (root / "dist" / "AutoFarmSeal" / "AutoFarmSeal.exe").exists()


def test_batch_preserves_script_error_even_if_old_exe_exists(tmp_path):
    root = fixture_repo(tmp_path, "Write-Output 'SIMULATED FAILURE'; exit 23\n")
    (root / "dist" / "AutoFarmSeal" / "_internal").mkdir(parents=True)
    (root / "dist" / "AutoFarmSeal" / "AutoFarmSeal.exe").touch()
    result = run_batch(root, tmp_path)
    assert result.returncode == 23, result.stdout + result.stderr
    assert "BUILD GAGAL - kode 23" in result.stdout
    assert "BUILD BERHASIL" not in result.stdout


def test_batch_rejects_success_without_package(tmp_path):
    root = fixture_repo(tmp_path, "exit 0\n")
    result = run_batch(root, tmp_path)
    assert result.returncode != 0
    assert "BUILD GAGAL" in result.stdout


def test_batch_rejects_missing_source_before_running_script(tmp_path):
    root = fixture_repo(tmp_path, "Write-Output 'SHOULD NOT RUN'; exit 0\n")
    (root / "pyproject.toml").unlink()
    result = run_batch(root, tmp_path)
    assert result.returncode != 0
    assert "folder UTAMA" in result.stdout
    assert "SHOULD NOT RUN" not in result.stdout
