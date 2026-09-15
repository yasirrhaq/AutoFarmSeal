# Dependencies and implementation references

No Seal artwork, monster dataset or trained weights are bundled. Local user screenshots/templates are not uploaded by the app. The repository does not choose an open-source license for the owner's code; dependency licensing is independent.

A Windows distribution contains third-party Python/Qt components. Review their licenses and retain notices delivered with runtime/wheels before redistribution. This research prototype is not a completed distribution-license audit.

Primary references:

- Qt for Python: https://doc.qt.io/qtforpython-6/
- Qt thread ownership: https://doc.qt.io/qt-6/threads-qobject.html
- Qt style sheets: https://doc.qt.io/qt-6/stylesheet-examples.html
- Qt licensing: https://doc.qt.io/qt-6/licensing.html
- MSS capture: https://python-mss.readthedocs.io/latest/examples.html
- OpenCV matching: https://docs.opencv.org/4.x/d4/dc6/tutorial_py_template_matching.html
- OpenCV HSV: https://docs.opencv.org/4.x/da/d97/tutorial_threshold_inRange.html
- NumPy: https://numpy.org/doc/
- PyAutoGUI fail-safe/primary-monitor limits: https://pyautogui.readthedocs.io/en/latest/
- pynput: https://pynput.readthedocs.io/en/latest/keyboard.html
- pywin32: https://github.com/mhammond/pywin32
- Windows client coordinates: https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-clienttoscreen
- PyInstaller: https://pyinstaller.org/en/stable/operating-mode.html

Versions are bounded in `pyproject.toml`. Successful CI artifacts include `build-dependencies.txt` recording resolved versions. The design does not assume a dependency is the latest release.
