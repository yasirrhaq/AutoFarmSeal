"""Versioned configuration and platform-independent geometry."""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Any
from uuid import uuid4

RESERVED = {"f8", "f9", "f10"}
KEYS = set("abcdefghijklmnopqrstuvwxyz0123456789") | {
    "space", "tab", "shift", "ctrl", "alt", "up", "down", "left", "right",
} | {f"f{i}" for i in range(1, 13)}


@dataclass(frozen=True)
class Rect:
    x: int
    y: int
    w: int
    h: int

    @property
    def right(self) -> int:
        return self.x + self.w

    @property
    def bottom(self) -> int:
        return self.y + self.h

    def valid_in(self, size: tuple[int, int]) -> bool:
        return (self.w > 0 and self.h > 0 and self.x >= 0 and self.y >= 0
                and self.right <= size[0] and self.bottom <= size[1])

    def contains(self, x: int, y: int) -> bool:
        return self.x <= x < self.right and self.y <= y < self.bottom

    def intersects(self, other: Rect) -> bool:
        return (self.x < other.right and self.right > other.x
                and self.y < other.bottom and self.bottom > other.y)

    def crop(self, frame):
        return frame[self.y:self.bottom, self.x:self.right]

    @classmethod
    def parse(cls, value: Any) -> Rect:
        if not isinstance(value, dict) or set(value) != {"x", "y", "w", "h"}:
            raise ValueError("Format area tidak valid.")
        if any(type(v) is not int for v in value.values()):
            raise ValueError("Koordinat area harus bilangan bulat.")
        return cls(**value)


@dataclass
class Profile:
    schema_version: int = 1
    id: str = field(default_factory=lambda: uuid4().hex)
    name: str = "Monster baru"
    width: int = 0
    height: int = 0
    regions: dict[str, Rect] = field(default_factory=dict)
    exclusions: list[Rect] = field(default_factory=list)
    templates: dict[str, list[str]] = field(
        default_factory=lambda: {"monster": [], "combat": [], "defeat": []})
    threshold: float = 0.86
    signal_threshold: float = 0.93
    scales: list[float] = field(default_factory=lambda: [0.85, 1.0, 1.15])
    mirror_templates: bool = True
    learn_seconds: int = 15
    learn_samples: int = 10
    click_x: float = 0.5
    click_y: float = 0.65
    scan_hz: int = 6
    max_search_width: int = 960
    hp_lower: list[int] = field(default_factory=lambda: [20, 90, 70])
    hp_upper: list[int] = field(default_factory=lambda: [45, 255, 255])
    ap_lower: list[int] = field(default_factory=lambda: [85, 90, 70])
    ap_upper: list[int] = field(default_factory=lambda: [125, 255, 255])
    target_lower: list[int] = field(default_factory=lambda: [0, 100, 70])
    target_upper: list[int] = field(default_factory=lambda: [10, 255, 255])
    hp_enabled: bool = False
    ap_enabled: bool = False
    loot_enabled: bool = False
    hp_threshold: float = 0.4
    ap_threshold: float = 0.25
    hp_key: str = "1"
    ap_key: str = "2"
    pickup_key: str = ""
    attack_key: str = ""
    ctrl_click: bool = True
    potion_cooldown: float = 3.0
    potion_response_timeout: float = 5.0
    max_ineffective_potions: int = 2
    max_attempts: int = 3
    engage_timeout: float = 5.0
    combat_timeout: float = 45.0
    progress_timeout: float = 12.0
    search_timeout: float = 30.0
    loot_attempts: int = 2
    session_minutes: int = 15
    max_frame_age: float = 0.5
    input_verified: bool = False
    screenshot_failures: bool = False

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> Profile:
        if (not isinstance(data, dict) or type(data.get("schema_version")) is not int
                or data.get("schema_version") != 1):
            raise ValueError("Versi profil tidak didukung; file asli tidak diubah.")
        raw = dict(data)
        raw["regions"] = {k: Rect.parse(v) for k, v in raw.get("regions", {}).items()}
        raw["exclusions"] = [Rect.parse(v) for v in raw.get("exclusions", [])]
        try:
            profile = cls(**raw)
            errors = profile.validate()
        except (TypeError, AttributeError, KeyError) as exc:
            raise ValueError("Struktur profil tidak valid.") from exc
        if errors:
            raise ValueError("\n".join(errors))
        return profile

    def clone(self) -> Profile:
        return self.from_dict(self.to_dict())

    def validate(self, *, calibrated: bool = False, live: bool = False) -> list[str]:
        errors: list[str] = []
        if not isinstance(self.id, str) or len(self.id) != 32 or any(
                c not in "0123456789abcdef" for c in self.id):
            errors.append("ID profil tidak valid.")
        if not isinstance(self.name, str) or not 1 <= len(self.name.strip()) <= 80:
            errors.append("Nama profil harus 1–80 karakter.")
        numeric = {
            "threshold": (0.5, 0.999), "signal_threshold": (0.5, 0.999),
            "click_x": (0.05, 0.95), "click_y": (0.05, 0.95),
            "scan_hz": (1, 12), "max_search_width": (320, 1280),
            "hp_threshold": (0.05, 0.95), "ap_threshold": (0.05, 0.95),
            "potion_cooldown": (1, 60), "potion_response_timeout": (1, 30),
            "max_ineffective_potions": (1, 5), "max_attempts": (1, 5),
            "engage_timeout": (1, 20), "combat_timeout": (5, 180),
            "progress_timeout": (2, 60), "search_timeout": (3, 120),
            "loot_attempts": (1, 5), "session_minutes": (1, 120),
            "max_frame_age": (0.1, 1.0), "width": (0, 7680), "height": (0, 4320),
            "learn_seconds": (5, 30), "learn_samples": (2, 11),
        }
        integer_fields = {"scan_hz", "max_search_width", "max_ineffective_potions",
                          "max_attempts", "loot_attempts", "session_minutes", "width", "height",
                          "learn_seconds", "learn_samples"}
        for key, (low, high) in numeric.items():
            v = getattr(self, key)
            if type(v) not in (int, float) or not math.isfinite(v) or not low <= v <= high:
                errors.append(f"Nilai {key} harus di antara {low}–{high}.")
            elif key in integer_fields and type(v) is not int:
                errors.append(f"{key} harus bilangan bulat.")
        for key in ("hp_enabled", "ap_enabled", "loot_enabled", "ctrl_click",
                    "input_verified", "screenshot_failures", "mirror_templates"):
            if type(getattr(self, key)) is not bool:
                errors.append(f"{key} harus true/false.")
        if not isinstance(self.scales, list) or not 1 <= len(self.scales) <= 5 or any(
                type(v) not in (int, float) or not math.isfinite(v) or not 0.5 <= v <= 1.6
                for v in self.scales):
            errors.append("Gunakan 1–5 skala template antara 0.5 dan 1.6.")
        for name in ("hp", "ap", "target"):
            for suffix in ("lower", "upper"):
                value = getattr(self, f"{name}_{suffix}")
                if (not isinstance(value, list) or len(value) != 3 or any(
                        type(x) is not int or not 0 <= x <= cap
                        for x, cap in zip(value, (179, 255, 255)))):
                    errors.append(f"HSV {name} {suffix} tidak valid.")
            lo, hi = getattr(self, f"{name}_lower"), getattr(self, f"{name}_upper")
            if len(lo) == len(hi) == 3 and (lo[1] > hi[1] or lo[2] > hi[2]):
                errors.append(f"Batas S/V {name} terbalik.")
        for key in ("hp_key", "ap_key", "pickup_key", "attack_key"):
            v = getattr(self, key)
            if not isinstance(v, str) or (v and (v not in KEYS or v in RESERVED)):
                errors.append(f"Tombol {key} tidak valid atau memakai hotkey F8/F9/F10.")
        if set(self.templates) != {"monster", "combat", "defeat"}:
            errors.append("Jenis template tidak valid.")
        for kind, paths in self.templates.items():
            if not isinstance(paths, list) or len(paths) > (12 if kind == "monster" else 3):
                errors.append(f"Terlalu banyak template {kind}.")
            elif any(not isinstance(p, str) or not p.startswith("templates/")
                     or not p.endswith(".png") or ".." in p or "\\" in p
                     or p.count("/") != 1 for p in paths):
                errors.append("Path template harus templates/<id>.png.")
        size = (self.width, self.height)
        for r in [*self.regions.values(), *self.exclusions]:
            if not r.valid_in(size):
                errors.append("Area berada di luar ukuran kalibrasi.")
        if len(self.exclusions) > 20:
            errors.append("Maksimal 20 area pengecualian.")
        if calibrated or live:
            if "world" not in self.regions or not self.templates.get("monster"):
                errors.append("Kalibrasikan area dunia dan tambahkan template monster.")
        if live:
            for name in ("hp", "combat", "defeat"):
                if name not in self.regions:
                    errors.append(f"Area {name} wajib untuk mode input.")
            for name in ("combat", "defeat"):
                if not self.templates.get(name):
                    errors.append(f"Template indikator {name} wajib untuk mode input.")
            if self.ap_enabled and "ap" not in self.regions:
                errors.append("Auto AP memerlukan area AP.")
            if self.loot_enabled and not self.pickup_key:
                errors.append("Isi tombol pickup yang sudah diuji; jangan menebak shortcut.")
            if self.hp_enabled and not self.hp_key:
                errors.append("Isi tombol potion HP.")
            if self.ap_enabled and not self.ap_key:
                errors.append("Isi tombol potion AP.")
            if not self.input_verified:
                errors.append("Uji input secara manual dan konfirmasikan di pengaturan.")
        return list(dict.fromkeys(errors))
