# Verification and handoff checklist

## Automated tests

Run `python -m pytest -q`, `python -m ruff check .`, and `python -m compileall -q src scripts tests`.

Core tests use synthetic NumPy images and fake window/input objects, never a live game. Coverage includes configuration/storage, coordinate reversal, exclusion regions, matching, HSV fill, uncertain/duplicate completion, potion timeouts, stale frames, identity/focus/movement guards, cancellation ordering and release after exceptions.

UI tests are skipped if PySide6 is absent. Do not report that skip as a UI pass. Windows CI installs Qt and runs offscreen tests. Source/package smoke mode registers no hotkeys and creates no native capture/input adapters.

## Real client checks — not completed by CI

| Test | Procedure | Required evidence |
|---|---|---|
| Capture | Foreground primary-monitor client | No black frame/title bar/desktop/overlay mismatch |
| Calibration | Select known regions at actual Windows scaling | Correct original pixel coordinates |
| Monster negatives | Trees, wrong monsters, empty regions | False-positive rate measured without input |
| Monster positives | Held-out distances/poses | Measured detection quality, not self-template success only |
| HP/AP | Multiple fill levels and covered HUD | Valid estimates; unknown/occluded reading stops input |
| Engagement | Before selection, moving, fighting | Correct discriminating indicator |
| Completion | Death, occlusion, offscreen movement, other monster dying | Only correct positive completion qualifies |
| Input | Supervised normal action in permitted client | Configured click/modifier/key accepted; no bypass |
| Stop | F10 during countdown, detection, input | No new program inputs; held inputs released |
| Focus | Alt-tab during search/combat | Inhibition on next guard; explicit resume only |
| Geometry | Move/resize between capture/action | Old coordinate input rejected |
| Potion | Controlled unavailable/unresponsive potion | Bounded requests then pause; no invented stock count |
| Loot | Verified pickup key and inaccessible item | Bounded requests; no fabricated acquired-item counter |
| Close | Close during observation/input | Worker exits and owned inputs release |

Keep gameplay unobstructed with fixed UI/camera/client size. Stop future program input does not necessarily stop game-native auto-attack; cancel that manually. Use an offline or explicitly permitted environment; do not treat administrator access or disabled protections as the solution to rejected inputs.

## Session progression and performance

One verified encounter, then supervised 5/15/30-minute sessions. Record profile/reference/scales, frame dimensions, thresholds, machine specs, Windows scaling, detection average/p95 latency, FPS/frame-time change, confirmed/unknown outcomes, bad clicks and manual interventions. Keep failures in the denominator.

Compare game-only, idle application, observation without preview, observation with unobstructed preview, and finally gated live input. Do not lower quality thresholds simply to increase apparent success. If templates are inadequate, evaluate an alternative detector as a separate milestone.

## Known limitations

No provided dataset or prevalidated calibration. Combat/completion templates are generic and not Seal-client-verified. Pickup success is not verified. Empty/noisy bars can be ambiguous. Session time includes pauses to limit exposure. Returning to the app pauses a foreground game session. No guaranteed FPS/latency, installer/signing, background/minimized support, map navigation, town/inventory/death recovery or cancellation of native actions already accepted by the game.
