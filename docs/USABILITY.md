# Usability revision 0.2 — 2026-09-15

The user found the first setup incomprehensible. The default entry point is now a four-step visual guide: screenshot, permitted world area, one monster example and input-free preview. Advanced options are collapsed, not removed. A one-shot check captures the game after the existing four-second delay and returns to an image preview automatically.

Separate preparation tasks guide HP/AP rectangle selection and color sampling, engagement/completion examples, and normal attack bindings. Basic settings avoid HSV numbers and raw match scores. Stored configuration does not establish correct client behavior. An unknown completion signal remains a blocker for live farming, not an excuse to remove verification.

## Technical contract

`guide.py` never creates a Native adapter or Engine. New template crops remain in a draft dictionary until explicit Save. Cancel keeps the original JSON and does not write draft PNGs. Failed save rolls back newly created PNG files. Changed calibration always clears `input_verified`. Fixed-position combat/defeat reconfiguration replaces that draft signal's references, not its original file until Save. Profile schema 1 stays compatible with 0.1.

The guide's explicitly requested detector test runs on a bounded background thread with cancellation. It processes an immutable profile/frame snapshot and only publishes visual results. It does not create an input plan. The existing worker handles game capture. The UI routes captures by purpose and epoch, returns on failure/cancellation, and ignores F8 while a guide exists even when minimized. Final native guards and explicit opt-in remain unchanged.

The trainer uses a scrollable central panel so expanded controls remain reachable on short displays. There are no new frameworks, cloud calls, decorative loops or always-on previews. Actual game FPS and native capture integration remain separate validation tasks.

## Regression evidence required

Existing core/input tests plus beginner-screen defaults, guide cancellation, all four monster setup steps, different-resolution rejection, empty names, monster region boundaries, bar sampling boundaries, no inherited verification in simple controls, no native plan for one-shot preview, and F8 inhibition during minimized setup. Windows tests and native source/packaged startup are gates; they do not prove actual gameplay accuracy.

User instructions: `docs/MULAI_DI_SINI.md`. Product and architecture baseline: `PRD.md`, `TRD.md`. This revision changes usability, not the out-of-scope list or the verified status of live client mechanics.
