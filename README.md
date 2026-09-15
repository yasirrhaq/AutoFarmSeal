# AutoFarmSeal

A compact **Windows trainer-style desktop application** for a supervised computer-vision college project. Python + PySide6, packaged as a one-folder `.exe` using PyInstaller.

**Status: v0.1.0 research prototype, not a verified unattended Seal bot.** The repository contains application code and automated tests. Compatibility with your client, monster recognition, resource calibration, completion indicators, pickup bindings, and in-game performance still require supervised Windows testing.

The program observes visible screen pixels and sends bounded normal mouse/keyboard input. It does **not** access game memory, inject DLLs, manipulate packets, hook Direct3D, bypass protections, or provide game-stat cheats. Use only in an offline or explicitly permitted environment. A checkbox is not a substitute for the server owner's permission.

## What is included

- Compact dark trainer UI: window selection, monster profile, HP/AP toggles and thresholds, pickup binding, start/pause/stop, status, and local log.
- Create, edit, duplicate, and delete profiles without editing source code. JSON profiles and PNG templates live outside the executable.
- Screenshot calibration: drag world/HP/AP/target-HP/exclusion regions, crop multiple monster templates, and click a bar's fill to sample HSV color.
- Open screenshot files for offline observation, or capture the foreground game client after a four-second countdown.
- Multi-scale OpenCV template matching, bounded candidates, exclusion regions, duplicate suppression, and coordinate conversion back to client pixels.
- Default **observation-only** mode. It creates no action plan and sends no game input.
- Explicitly gated input mode: select, verify engagement, monitor combat, heal, verify completion, request bounded pickup, repeat.
- F8 start/resume, F9 pause, F10 stop; focus/identity/geometry/fresh-frame guards; limited retries, timeouts, and session limits.
- Rotating local JSONL logs; optional capped failure screenshots; tests, PRD, TRD, Windows build script and CI workflow.

**There are no bundled game screenshots, trained weights, or pre-calibrated monster profiles.** A name is not a classifier: add reference images from your own permitted gameplay. Templates may fail with changing camera angle, pose, scale, occlusion, or similar-looking monsters.

## Run from source on Windows

Install Python **3.12 x64**. Clone the implementation branch while the initial PR is open:

```powershell
git clone --branch feat/windows-trainer-mvp https://github.com/yasirrhaq/AutoFarmSeal.git
cd AutoFarmSeal
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m autofarmseal
```

Or use `scripts/run.ps1` once PowerShell permits locally reviewed scripts. Administrator access is not requested. If the client rejects ordinary synthetic input, stop at observation mode; do not disable the client's protections.

Linux/macOS can run the **offline screenshot UI and core tests**, but live adapters are Windows-only. The initial input adapter deliberately supports a visible window wholly on the **primary monitor**, with fixed client size, camera and UI scale. Minimized/background gameplay and multi-client operation are unsupported.

## First-run workflow

1. Keep **Aktifkan input nyata** unchecked. Choose the game window, then **Capture + Kalibrasi**. The app minimizes; activate the game within four seconds. Alternatively, use **Kalibrasi dari gambar** with a screenshot cropped to the exact client area, not the title bar/desktop.
2. Drag the permitted world region. Add exclusion regions for chat, minimap, hotbar, dialogs and other UI. Crop representative monster templates (up to 12, at most 5 scales each).
3. Select the inner HP bar without text/borders; click its colored fill with the HP color sampler. Do the same for AP when needed. Readings are estimates, not game telemetry. A fully empty/unrecognizable bar is UNKNOWN and pauses input.
4. Collect and calibrate **separate positive visual indicators** for `combat` and `defeat`, from appropriate gameplay moments. Opening another screenshot with the same resolution preserves existing regions. Both indicators are required for live input. Optional target-HP calibration adds a no-progress timeout.
5. Open **Pratinjau** and run observation. On Windows, the app waits four seconds before capturing so you can activate the game. Return to the app to inspect the last displayed frame; losing game focus pauses capture/input. Avoid putting the preview over the game. For offline testing, with no window selected, Start asks for a screenshot and performs one detection pass.
6. Test normal input bindings and all indicators manually on your client. In **Pengaturan**, confirm verification only after those tests. Configure potion and pickup keys yourself: **no universal pickup key is assumed**. `Ctrl + click` is an editable starting setting, not a client-compatibility guarantee.
7. For a supervised input test, explicitly enable input, confirm the environment permits it, start, and return to the game during the four-second countdown. Use F10 immediately if anything is wrong. Work up from one encounter to 5/15/30-minute supervised sessions.

**Do not use a disappearing monster as the defeat template.** The completion detector requires a distinct visible signal, a cleared baseline, and two fresh positive observations during a confirmed encounter. If your client has no reliably detectable completion signal, stay in observation mode until an appropriate verifier is implemented. Merely making calibration boxes is not validation.

**Stop means stop this program's future inputs and release inputs it holds. It cannot guarantee that a game-native auto-attack already started will stop.** Cancel that in the game manually as necessary. Do not use the keyboard/mouse for unrelated activities during a live session.

## Build the Windows `.exe`

On Windows, run `scripts/build.ps1`, or:

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev,build]"
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean AutoFarmSeal.spec
```

Output: `dist/AutoFarmSeal/AutoFarmSeal.exe`. **Distribute the whole `AutoFarmSeal` folder including `_internal`, not just the `.exe`.** User profiles stay in `%LOCALAPPDATA%/AutoFarmSeal`, not in the distribution folder. There is no installer, auto-updater, code-signing certificate, or cloud account in this prototype.

The GitHub Actions workflow runs tests, opens/closes the source UI without input, builds on Windows, and smoke-tests the packaged application. A successful run uploads `AutoFarmSeal-Windows-x64` with a resolved dependency manifest. A workflow definition is not proof of a successful build: inspect that run's actual status. Do not disable antivirus to run an unsigned build; review the source and investigate alerts.

## Developer commands

```powershell
python -m pytest -q
python -m ruff check .
python -m autofarmseal --self-check
python -m autofarmseal --smoke-test --data-dir .smoke-data --screenshot ui-smoke.png
```

Set `QT_QPA_PLATFORM=offscreen` for headless UI tests. Smoke mode does **not** create native capture/input adapters or register hotkeys. `--self-check` reads configuration only. Set `AUTOFARMSEAL_DATA_DIR`, or pass `--data-dir`, for independent development data.

## Documents

- [Product scope and acceptance criteria](PRD.md)
- [Architecture, state machine, and performance](TRD.md)
- [Testing and client validation checklist](docs/TESTING.md)
- [Third-party software and reference documentation](docs/THIRD_PARTY_NOTICES.md)

Out of v0.1: navigation across maps, town visits, potion purchasing, selling inventory, death recovery, complex combos, selective loot, OCR, YOLO/Roboflow integration, a Direct3D overlay, background operation, and multiple clients. No whole-game performance or farming accuracy claims are made before measurement.
