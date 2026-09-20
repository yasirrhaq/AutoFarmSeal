"""Bounded template matching. All returned coordinates are client pixels."""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable

import cv2
import numpy as np

from .model import Profile, Rect


@dataclass(frozen=True)
class Detection:
    box: Rect
    score: float
    point: tuple[int, int]


@dataclass(frozen=True)
class Observation:
    captured_at: float
    size: tuple[int, int]
    detections: tuple[Detection, ...] = ()
    hp: float | None = None
    ap: float | None = None
    target_hp: float | None = None
    combat: bool = False
    defeat: bool = False
    valid: bool = True
    elapsed_ms: float = 0.0


def fill_ratio(frame: np.ndarray, region: Rect | None, lower, upper) -> float | None:
    """Calibrated left-to-right bar. Empty/fragmented samples are UNKNOWN, not 0 HP."""
    if region is None or not region.valid_in((frame.shape[1], frame.shape[0])):
        return None
    hsv = cv2.cvtColor(region.crop(frame), cv2.COLOR_BGR2HSV)
    if lower[0] <= upper[0]:
        mask = cv2.inRange(hsv, np.array(lower), np.array(upper))
    else:
        mask = cv2.inRange(hsv, np.array([0, *lower[1:]]), np.array(upper))
        mask |= cv2.inRange(hsv, np.array(lower), np.array([179, *upper[1:]]))
    occupied = (mask > 0).mean(axis=0) >= 0.4
    positions = np.flatnonzero(occupied)
    if not len(positions) or positions[0] > max(2, region.w * 0.06):
        return None
    end = int(positions[-1]) + 1
    if occupied[:end].mean() < 0.85:
        return None
    return end / region.w


class Detector:
    def __init__(self, profile: Profile, read_image: Callable[[str], np.ndarray]):
        errors = profile.validate(calibrated=True)
        if errors:
            raise ValueError("\n".join(errors))
        self.p = profile.clone()
        world = self.p.regions["world"]
        self.factor = min(1.0, self.p.max_search_width / world.w)
        self.bank: dict[str, list[np.ndarray]] = {k: [] for k in self.p.templates}
        for kind, paths in self.p.templates.items():
            for path in paths:
                gray = cv2.cvtColor(read_image(path), cv2.COLOR_BGR2GRAY)
                if min(gray.shape) < 6 or float(gray.std()) < 3:
                    raise ValueError(f"Template {path} terlalu kecil atau polos.")
                scales = self.p.scales if kind == "monster" else [1.0]
                sources = [gray]
                if kind == "monster" and self.p.mirror_templates:
                    mirrored = cv2.flip(gray, 1)
                    if not np.array_equal(mirrored, gray):
                        sources.append(mirrored)
                for source in sources:
                    for scale in scales:
                        f = scale * (self.factor if kind == "monster" else 1.0)
                        h, w = max(6, round(source.shape[0] * f)), max(6, round(source.shape[1] * f))
                        resized = cv2.resize(source, (w, h), interpolation=cv2.INTER_AREA)
                        if resized.std() >= 3:
                            self.bank[kind].append(resized)
        if not self.bank["monster"]:
            raise ValueError("Tidak ada template monster yang dapat dipakai.")

    def signal(self, gray: np.ndarray, name: str) -> bool:
        region = self.p.regions.get(name)
        if region is None:
            return False
        sample = region.crop(gray)
        for template in self.bank[name]:
            if sample.shape[0] < template.shape[0] or sample.shape[1] < template.shape[1]:
                continue
            result = cv2.matchTemplate(sample, template, cv2.TM_CCOEFF_NORMED)
            if float(np.nan_to_num(result, nan=-1).max()) >= self.p.signal_threshold:
                return True
        return False

    def observe(self, frame: np.ndarray, captured_at: float, *, search: bool = True,
                cancelled: Callable[[], bool] = lambda: False) -> Observation:
        start = time.monotonic()
        p = self.p
        size = (frame.shape[1], frame.shape[0])
        if size != (p.width, p.height) or frame[::8, ::8].std() < 2:
            return Observation(captured_at, size, valid=False)
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        found: list[Detection] = []
        if search:
            world = p.regions["world"]
            sample = world.crop(gray)
            if self.factor < 1:
                sample = cv2.resize(sample, (round(world.w * self.factor),
                                            round(world.h * self.factor)))
            sx, sy = world.w / sample.shape[1], world.h / sample.shape[0]
            for template in self.bank["monster"]:
                if cancelled():
                    break
                h, w = template.shape
                if sample.shape[0] < h or sample.shape[1] < w:
                    continue
                result = np.nan_to_num(cv2.matchTemplate(
                    sample, template, cv2.TM_CCOEFF_NORMED), nan=-1)
                for _ in range(8):
                    _, score, _, (x, y) = cv2.minMaxLoc(result)
                    if score < p.threshold:
                        break
                    box = Rect(world.x + round(x * sx), world.y + round(y * sy),
                               max(1, round(w * sx)), max(1, round(h * sy)))
                    point = (box.x + int(box.w * p.click_x), box.y + int(box.h * p.click_y))
                    if (box.valid_in(size) and not any(box.intersects(r) for r in p.exclusions)
                            and not any(box.intersects(d.box) for d in found)):
                        found.append(Detection(box, float(score), point))
                    result[max(0, y-h//2):y+h//2+1, max(0, x-w//2):x+w//2+1] = -1
                if len(found) >= 24:
                    break
        found.sort(key=lambda d: d.score, reverse=True)
        return Observation(
            captured_at, size, tuple(found[:24]),
            fill_ratio(frame, p.regions.get("hp"), p.hp_lower, p.hp_upper),
            fill_ratio(frame, p.regions.get("ap"), p.ap_lower, p.ap_upper),
            fill_ratio(frame, p.regions.get("target_hp"), p.target_lower, p.target_upper),
            self.signal(gray, "combat"), self.signal(gray, "defeat"), True,
            (time.monotonic() - start) * 1000,
        )
