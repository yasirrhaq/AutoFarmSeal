"""Local-only data. Atomic replacement; no silent reset of corrupt user files."""
from __future__ import annotations

import json
import os
from pathlib import Path
from uuid import uuid4

import cv2
import numpy as np

from .model import Profile


def default_root() -> Path:
    if os.environ.get("AUTOFARMSEAL_DATA_DIR"):
        return Path(os.environ["AUTOFARMSEAL_DATA_DIR"]).expanduser().resolve()
    base = Path(os.environ.get("LOCALAPPDATA", Path.home() / ".local" / "share"))
    return base / "AutoFarmSeal"


class Store:
    def __init__(self, root: Path | None = None):
        self.root = (root or default_root()).resolve()
        for part in ("profiles", "templates", "logs", "diagnostics"):
            (self.root / part).mkdir(parents=True, exist_ok=True)

    def asset(self, relative: str) -> Path:
        path = (self.root / relative).resolve()
        if path.parent != (self.root / "templates").resolve() or path.suffix != ".png":
            raise ValueError("Path gambar tidak diizinkan.")
        return path

    def save(self, profile: Profile) -> None:
        errors = profile.validate()
        if errors:
            raise ValueError("\n".join(errors))
        path = self.root / "profiles" / f"{profile.id}.json"
        temp = path.with_suffix(f".{uuid4().hex}.tmp")
        try:
            with temp.open("w", encoding="utf-8") as f:
                json.dump(profile.to_dict(), f, ensure_ascii=False, indent=2, allow_nan=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp, path)
        finally:
            temp.unlink(missing_ok=True)

    def list_profiles(self) -> tuple[list[Profile], list[str]]:
        profiles, errors = [], []
        for path in sorted((self.root / "profiles").glob("*.json")):
            try:
                if path.stat().st_size > 1_000_000:
                    raise ValueError("File terlalu besar")
                p = Profile.from_dict(json.loads(path.read_text(encoding="utf-8")))
                if path.stem != p.id:
                    raise ValueError("Nama file dan ID profil berbeda")
                profiles.append(p)
            except (ValueError, OSError) as exc:
                errors.append(f"{path.name}: {exc}")
        return profiles, errors

    def delete(self, profile: Profile) -> None:
        if profile.validate():
            raise ValueError("Profil tidak valid.")
        (self.root / "profiles" / f"{profile.id}.json").unlink(missing_ok=True)
        # Assets can be shared by duplicated profiles; do not delete them here.

    def image(self, bgr: np.ndarray) -> str:
        if bgr.size == 0 or min(bgr.shape[:2]) < 6:
            raise ValueError("Pilih gambar sedikitnya 6 × 6 piksel.")
        if float(cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY).std()) < 3:
            raise ValueError("Potongan terlalu polos untuk template matching.")
        relative = f"templates/{uuid4().hex}.png"
        ok, data = cv2.imencode(".png", bgr)
        if not ok:
            raise ValueError("Gambar gagal dikodekan.")
        self.asset(relative).write_bytes(data.tobytes())
        return relative

    def read_image(self, relative: str) -> np.ndarray:
        path = self.asset(relative)
        if path.stat().st_size > 20_000_000:
            raise ValueError("Gambar referensi terlalu besar.")
        result = cv2.imdecode(np.frombuffer(path.read_bytes(), dtype=np.uint8), cv2.IMREAD_COLOR)
        if result is None or result.size == 0 or max(result.shape[:2]) > 7680:
            raise ValueError(f"Gambar tidak valid: {relative}")
        return result
