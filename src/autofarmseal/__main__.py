"""Entry point. DPI is configured before constructing Qt or importing input libraries."""
from __future__ import annotations

import argparse
import json
import sys
import traceback
from pathlib import Path

from . import __version__
from .storage import Store
from .windows import enable_dpi_awareness


def main() -> int:
    parser = argparse.ArgumentParser(description="AutoFarmSeal research prototype")
    parser.add_argument("--capture-self-test", type=Path, help="Windows-only capture of an owned test window, with JSON result; no OS inputs")
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--data-dir", type=Path, help="Optional independent local data directory")
    parser.add_argument("--self-check", action="store_true", help="Read local profiles; never capture or send input")
    parser.add_argument("--smoke-test", action="store_true", help="Open/close UI without native adapters or input")
    parser.add_argument("--guide-smoke", action="store_true", help="Preview setup UI; requires smoke-test")
    parser.add_argument("--screenshot", type=Path, help="UI screenshot for smoke test only")
    args = parser.parse_args()
    if args.guide_smoke and not args.smoke_test:
        parser.error("--guide-smoke requires --smoke-test")
    if args.screenshot and not args.smoke_test:
        parser.error("--screenshot requires --smoke-test")
    if args.capture_self_test and (args.smoke_test or not args.data_dir or sys.platform != "win32"):
        parser.error("--capture-self-test needs Windows and an explicit --data-dir; not --smoke-test")
    store = Store(args.data_dir)
    if args.self_check:
        profiles, errors = store.list_profiles()
        print(json.dumps({"version": __version__, "profiles": len(profiles), "errors": errors,
                          "input_sent": False}, ensure_ascii=False, indent=2))
        return 1 if errors else 0
    enable_dpi_awareness()
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication, QMessageBox
    from .ui import MainWindow
    app = QApplication(sys.argv[:1])
    app.setApplicationName("AutoFarmSeal")
    app.setOrganizationName("AutoFarmSeal")
    if args.capture_self_test:
        from .capture_selftest import run
        return run(app, store, args.capture_self_test)
    try:
        window = MainWindow(store, smoke=args.smoke_test)
    except Exception as exc:
        QMessageBox.critical(None, "AutoFarmSeal tidak dapat dibuka", str(exc))
        return 1

    def handle_error(exc_type, value, tb):
        window.worker.command("stop")
        text = "".join(traceback.format_exception(exc_type, value, tb))
        (store.root / "logs" / "last-crash.txt").write_text(text, encoding="utf-8")
        QMessageBox.critical(window, "Input dihentikan karena error", str(value))
    sys.excepthook = handle_error
    window.show()
    if args.smoke_test:
        if args.guide_smoke:
            from .guide import SetupGuide
            window.guide = SetupGuide(window.current(), store, parent=window)
            window.guide.show()
        def finish():
            if args.screenshot:
                args.screenshot.parent.mkdir(parents=True, exist_ok=True)
                target = window.guide if args.guide_smoke else window
                target.grab().save(str(args.screenshot))
            window.close()
        QTimer.singleShot(700, finish)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
