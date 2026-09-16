# PRD — AutoFarmSeal

Version: 0.1 implementation baseline / proposed 1.0 product scope. Date: 2026-09-15.

## Product goal

A configurable Windows desktop utility for a supervised, permitted college research task: observe a Seal-like game through screen pixels, choose an eligible monster, initiate normal game actions, inspect the result, and stop when confidence or safety is inadequate.

The user should not edit Python or retrain a model merely to add a target. A profile contains a name, local PNG references, detection parameters, region calibration and input settings. New references still need evaluation; zero training does not mean zero examples or guaranteed recognition.

UI: a small conventional trainer window, not a business dashboard or an imitation of WeMod. Dark neutral colors, one accent, clear feature rows; no wallpaper, glass/blur, decorative animations or permanent preview. Settings and logs are secondary dialogs.

## User journeys

### Initial setup

Choose window; capture its client pixels after a countdown or import an equivalent image. Define world/exclusion areas, resource-bar regions and reference colors. Crop monster examples. Capture distinct engagement and completion indicators from separate gameplay moments. Configure actual bindings and limits. Observe without input, then validate all readings before explicitly enabling supervised input.

Missing or invalid calibration must produce actionable errors, not a partially armed session. The default empty profile must never be sufficient to start real inputs.

### Daily use

Place character in the area manually. Select the window/profile, verify camera/scale and visual results, choose observation or explicitly permitted live input, start, and activate the game during the countdown.

F8 starts/resumes with checks; F9 pauses; F10 stops. Focus loss, moved/resized window between observation and action, stale frames, unknown HP, repeated ineffective actions and time limits inhibit inputs. Restoring focus alone must not resume.

### Change monster

Pause, move manually, select/create another profile, supply and verify references, then observe again. Switching profile resets live opt-in. Duplicates share immutable PNGs but have independent configuration and reset verification.

## Functional requirements

| ID | Target | v0.1 implementation / qualification |
|---|---|---|
| UI-01 | Compact trainer | Window/profile selectors, feature rows, controls, status and counters |
| UI-02 | Optional tools | Calibration/template dialog, settings tabs, preview and bounded log |
| PF-01 | Profile CRUD | Atomic JSON save; create/edit/duplicate/delete; no source editing |
| PF-02 | Preserve data | Report corrupt files; do not silently overwrite originals or delete shared assets |
| CV-01 | Regions | Original client-pixel world/exclusions; resolution change requires recalibration |
| CV-02 | Templates | In-app PNG crop; reject small/flat samples; cap references and scales |
| CV-03 | Detection | Active-profile multi-scale matching, bounded peaks and overlap suppression |
| CV-04 | Observe first | Screen/offline-image detection without an input plan |
| CT-01 | Initiate encounter | Configured Ctrl-click and optional single attack key; client acceptance unverified |
| CT-02 | Verify engagement | Two fresh positive observations and bounded failed selections |
| CT-03 | Maintain encounter | No retargeting in combat; deadline and optional target-HP progress |
| CT-04 | Verify completion | Separate positive template, cleared baseline and two fresh matches; absence is not victory |
| RS-01 | Read HP/AP | Calibrated HSV left-to-right fill; unknown is not fabricated 0%/100% |
| RS-02 | Potion rules | Toggles, thresholds, key, cooldown, response window and bounded ineffective uses |
| LT-01 | Basic pickup | Only verified user-configured keyboard pickup; bounded requests |
| LT-02 | Pickup evidence | Requests counted; actual acquired items NOT verified/reported in v0.1 |
| SF-01 | Input gate | Windows, environment permission, verified profile, window and functioning hotkeys |
| SF-02 | Immediate inhibition | Out-of-band cancellation; held-input release on pause/stop/errors |
| SF-03 | Final input checks | HWND/PID, foreground, primary monitor, geometry, frame age and click ROI |
| SF-04 | Session limits | Configurable 1–120 minutes (default 15); bounded search/engage/combat/loot |
| OB-01 | Honest counters | Inputs acknowledged after adapter success; confirmed and unknown outcomes separate |
| OB-02 | Local diagnostics | Rotating JSONL, capped UI log, opt-in failure screenshots (max 10) |
| PK-01 | Distribution | Windows one-folder PyInstaller; retain the entire folder |

Code existence does not prove that a client's indicators, inputs or templates work. UI/packaging tests and real-game acceptance are separate gates. v0.1 is not a declaration that all version-1.0 acceptance criteria have passed.

## Configuration boundaries

One active target profile and one visible primary-monitor window per session. Relatively fixed resolution, UI scale, camera and zoom. Similar-looking monsters may still be confused; a profile name is not a semantic classifier.

Up to 12 monster templates, 5 scales and 20 exclusions bound the initial work. Up to 3 references per fixed-position combat/completion indicator; use the same calibrated region for an indicator. Live mode always requires readable HP. Auto AP requires AP calibration. F8/F9/F10 are reserved and rejected as action bindings. No arbitrary executable configuration, shell commands or user scripts.

## Failure semantics

Unverified engagement is an unconfirmed attempt; limited retries may temporarily blacklist its last screen area. A missing monster is not proof of defeat. Unknown outcomes pause rather than increment the success counter.

A potion key is not proof of healing; bounded unsuccessful responses pause, and inventory counts are unknown. Pickup requests are not collection/ownership evidence; no item, rarity or profit counts are inferred.

Pause/stop prevents new program inputs but cannot cancel a native game action already latched internally. The UI must explain that auto-attack may need manual cancellation. Require unobstructed gameplay: no guaranteed compositor-level occlusion detection.

## Performance requirements

Qt Widgets, local data, no cloud inference. Capture/detection outside the GUI thread; latest-value mailbox rather than queued video; bounded template work, resized world ROI, cached scales and no world scan during committed combat. Default search target is 6 checks/s, not a measured guarantee. Stale results must pause rather than drive clicks. Optional preview and bounded logs.

Measure game-only, idle UI, observation with/without preview and live runs on the intended PC. Record CPU/RAM, detection timings and frame-time impact. Do not promise universal FPS, latency or RAM before measurement.

## Acceptance gates

A. Core: schema/storage, coordinates/exclusions, matching, ambiguous HP, transitions, stale frames, retries, input guards and cancellation ordering.

B. UI/build: source startup, profile/calibration workflows, intended Windows scaling, clean worker shutdown, one-folder Windows build and input-free packaged smoke test.

C. Client: visible capture, coordinates, accepted normal inputs, HP/AP across fill levels, engagement/completion positive AND negative examples, actual pickup binding. A headless runner cannot prove these.

D. One verified encounter, then supervised 5/15/30-minute sessions, including focus loss, resize, unavailable potion, blocked targets, inaccessible loot and emergency stop. Keep unknown outcomes in the evaluation; no unattended recommendation before these gates pass.

## Out of scope

Map-wide navigation, town visits, inventory selling, buying potions, death recovery, adaptive combos, loot valuation, multi-target priorities, OCR/YOLO/Roboflow, background/minimized gameplay, multiple clients, cloud accounts, remote control, auto-update, D3D injection and protection bypass. Replacing an inadequate detector is a separate evaluated milestone.
