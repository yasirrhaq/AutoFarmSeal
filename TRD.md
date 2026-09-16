# TRD — AutoFarmSeal

Implementation baseline 0.1.0 / 2026-09-15.

## Stack

Python 3.12 x64 Windows build target; core also supports 3.13. PySide6-Essentials (Qt Widgets/Core/Gui without WebEngine), MSS, NumPy and opencv-python-headless. Windows-only: PyAutoGUI, pywin32, pynput. PyInstaller one-folder distribution built on Windows.

Local-only: no API credentials, downloaded weights, remote commands or telemetry. No C# layer. Ordinary desktop window, not a Direct3D hook or injected overlay.

## Modules

| Module | Responsibility |
|---|---|
| `model.py` | Versioned profile, geometry, validation, key policy |
| `storage.py` | Atomic JSON, contained PNG paths, user-data lifecycle |
| `vision.py` | Cached scale variants, bounded matching, resource fill, immutable observations |
| `engine.py` | Pure observation-to-action state machine and acknowledged counters |
| `windows.py` | DPI, window identity/geometry/focus, guarded input and global control hotkeys |
| `runtime.py` | Capture/vision worker, epochs, cancellation, latest mailbox, orchestration and logs |
| `dialogs.py` | Screenshot calibration, letterbox coordinate selection and settings |
| `ui.py` | Compact trainer and optional preview/log dialogs |
| `__main__.py` | Startup, CLI, input-free self-check/smoke mode |

## Concurrency

Qt main thread owns all widgets, preview conversion and a 150 ms status poller. A non-daemon Python worker owns MSS, Detector and Engine. It uses a bounded command queue, Events and locked latest-value mailbox rather than slots needing a separate Qt event loop.

MSS is instantiated/closed in the worker. Capture and processing are sequential: no frame backlog. Resource ROIs are sampled each observation; world matching is skipped in committed combat. Freshness checks pause slow processing instead of authorizing stale clicks. This is not a hard real-time scheduler or independent priority HP loop.

The pynput listener exposes F8/F9/F10 only. F9/F10 inhibit/release input before the Qt event loop processes a notification. Listener failure stops live operation. Every command has an epoch; superseded queued Starts cannot undo a newer Stop. Countdown lives inside the worker/engine, not an uncancellable delayed GUI start callback.

## Coordinate contract

Rectangles and click points are original physical client pixels. Convert to desktop only for input. Request DPI awareness before Qt/input imports. Resolution mismatch inhibits live actions, not silent scaling.

World ROI is optionally resized to a default maximum width of 960. Template scales use the same factor; inverse mapping uses actual resized dimensions to account for rounding. Candidate boxes intersecting exclusions are rejected. The final input guard checks the point against allowed world/exclusions again.

Calibration canvas letterboxes the screenshot and maps selections to original pixels. Outside-image clicks do not select regions. Imported screenshots must equal client dimensions without title bar/decorations. Initial live support is primary-monitor-only; reject negative origins, spanning monitors, hidden/minimized clients and changed process identities.

## Perception contract

`Observation` contains capture time, original size, candidate `Detection`s, estimated HP/AP/optional target HP, combat/defeat booleans, validity and elapsed processing time. Match scores are similarity measures, not probabilities.

Monster matching: grayscale `TM_CCOEFF_NORMED`, cached scales, bounded peaks, exclusion checks and overlap suppression. Reject flat/small templates. Check cancellation between templates and limit OpenCV to one internal thread.

Combat/defeat checks are separate fixed-position visual templates, not pretrained classifiers. They require appropriate actual-client examples and negative tests. A game with no reliable positive completion indicator cannot use the generic live loop just by naming a profile.

Resource reading uses calibrated HSV on the inner bar; a column needs sufficient matching pixels, fill must begin near the left edge and gaps must be limited. Hue wrap is supported. Empty, unrecognizable or fragmented fills return `None`, not fabricated zero/full. Text, overlays, gradients and changing bar color may invalidate readings.

## State machine

`IDLE -> ARMED -> SEARCH -> ENGAGE -> COMBAT -> LOOT -> SEARCH`

PAUSED/STOPPED inhibit actions. Resume is explicit, clears target selection and checks a clean combat/defeat baseline. Resume of identical window/config preserves start time and potion cooldowns; a terminal stop or changed configuration creates a new engine.

ARMED waits four seconds, then requires trusted foreground frame, readable HP and clean indicators. SEARCH selects one non-blacklisted candidate and requests a single attack; there is no navigation. ENGAGE requires two fresh positive matches, otherwise records an unconfirmed attempt and retries within limits with an eight-second screen-region blacklist. COMBAT holds the target, monitors resources and deadline/optional target HP, and treats target disappearance as unknown. Defeat requires a cleared baseline plus two fresh matches; the same timestamp cannot satisfy both. LOOT issues at most the configured pickup requests with spacing and waits for old indicators to clear; no acquired-item count.

HP/AP checks precede ordinary actions. Potion requests are acknowledged after adapter completion. Pending potions await improvement or timeout; bounded ineffectiveness pauses. `Engine.tick()` returns at most one `Action` (`attack`, `hp`, `ap`, `pickup`). The runtime guards/executes, then acknowledges. Core never sleeps, invokes OS APIs or writes UI state.

## Safety

Every input-down operation rechecks inhibitor, timestamp budget, HWND/PID, foreground, primary-monitor visibility, unchanged client geometry/calibrated size, and allowed click coordinates. Short bounded press/click only. Track and release owned modifiers/keys/mouse in `finally`.

PyAutoGUI corner fail-safe remains enabled for input-down paths. Cleanup temporarily bypasses it ONLY to release owned inputs after a corner fail-safe, and restores it immediately. No alternative injection or protection-bypass fallback.

Focus checking and OS event delivery are not atomic. Do not interact with unrelated apps during live operation. Stop cannot undo a game-native action already accepted or cancel native auto-attack without a separately verified cancellation mechanism.

## Storage

Default `%LOCALAPPDATA%/AutoFarmSeal`; offline platforms use local-share directory. `--data-dir` / `AUTOFARMSEAL_DATA_DIR` override it.

```text
profiles/<uuid>.json
templates/<uuid>.png
logs/events.jsonl              # 2 MB, 3 rotated backups
logs/last-crash.txt            # last uncaught GUI error
diagnostics/failure-<time>.png # opt-in, maximum 10
```

Schema 1; canonical fields/bounds are `Profile`. No pickle or executable config. Reject invalid schemas; never silently overwrite corrupt files. Atomic JSON: temp file, flush/fsync, replace. Template paths must remain in the local template directory. Duplicate profiles share immutable assets; deleting a profile retains PNGs. Garbage collection/import-export UI is not part of v0.1.

Local screenshots/logs can contain account/game UI: review before sharing. User images are not committed or uploaded by this application.

## UI and lifecycle

One trainer window plus dialogs; no sidebar, wallpaper, animation or permanent preview. Preview is latest-only and deduplicated by capture timestamp; log viewer caps 1000 blocks. Editing controls or selecting another window/profile inhibits current inputs. Runtime clones config. Changed profiles reset live opt-in. Closing cancels and waits for worker cleanup rather than destroying an active thread.

## Verification and packaging

Core/fake-adapter tests have no real inputs. Qt tests run offscreen and smoke mode disables native adapters/hotkeys. Windows CI runs source tests, builds and smoke-tests the resulting one-folder `.exe`. Bounded dependency ranges and resolved dependency manifest are provided; this is not yet a fully pinned reproducible release process.

A package smoke pass proves startup/exit, not game capture, input acceptance, detection quality or game FPS. Use `docs/TESTING.md` for client acceptance. Distinguish failures and unknown results from success.
