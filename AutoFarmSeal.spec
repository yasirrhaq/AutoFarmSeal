# Build on Windows with Python 3.12 x64. One-folder, no console, no WebEngine.
from pathlib import Path
import sys
from PyInstaller.utils.hooks import copy_metadata

if sys.platform != 'win32':
    raise SystemExit('Build Windows .exe harus dijalankan di Windows.')
root = Path(SPECPATH)
metadata = []
for package in ('PySide6-Essentials', 'shiboken6', 'numpy', 'opencv-python-headless', 'mss', 'PyAutoGUI', 'pynput', 'pywin32'):
    metadata += copy_metadata(package)
a = Analysis(
    [str(root / 'scripts' / 'launch.py')],
    pathex=[str(root / 'src')],
    binaries=[],
    datas=metadata + [(str(root / 'README.md'), '.'), (str(root / 'PRD.md'), '.'), (str(root / 'TRD.md'), '.'), (str(root / 'docs'), 'docs')],
    hiddenimports=['pynput.keyboard._win32', 'pynput.mouse._win32', 'win32timezone'],
    hookspath=[], hooksconfig={}, runtime_hooks=[],
    excludes=['PySide6.QtWebEngineCore', 'PySide6.QtWebEngineWidgets', 'tkinter', 'matplotlib'],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='AutoFarmSeal',
          debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
          console=False, disable_windowed_traceback=False)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='AutoFarmSeal')
