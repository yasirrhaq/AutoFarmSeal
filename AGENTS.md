# Project working rules

Read PRD.md, TRD.md and docs/TESTING.md before changing scope. Target Python 3.12 x64 and Windows. Keep the trainer UI compact; no web UI, cloud inference, injection or anti-cheat bypass.

Default is observation-only. Never remove input opt-in, foreground/identity/geometry/freshness guards, cancellation epochs or held-key cleanup to make a demo appear to work. No kill inference from a vanished monster. No acquisition counter inferred from a pickup key. No automatic resume on focus restoration.

Keep core/vision/engine independent of Qt and native input. Tests use synthetic fixtures/fake input; real client verification is a separate supervised checklist. Do not commit user screenshots, local profiles, logs, credentials, executables or virtual environments.

Run tests and compile checks. Run Qt offscreen and Windows source/packaged smoke tests when available. Report missing dependencies, skipped tests and unverified client behavior explicitly. Do not claim performance without measurement.
