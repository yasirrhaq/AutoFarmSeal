"""Bounded screen recognition. All returned coordinates are client pixels.

Normal targets keep strict template matching. Targets learned from several real
poses can additionally use a center-weighted deformable check and (only when
explicitly requested by observation mode) short temporal confirmation. The
latter is never required by, or automatically enabled for, live input.
"""
from __future__ import annotations

import time
from collections import deque
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
    strong: bool = True
    temporal: bool = False


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


def _center_slice(shape: tuple[int, int]) -> tuple[slice, slice]:
    """Adaptive stable-body core for deformable silhouettes.

    A wide target such as a bat is likely to deform mostly at the left/right
    extremities, while a tall target can deform at top/bottom. Square targets
    get a balanced central core. This is a soft heuristic, not segmentation.
    """
    h, w = shape
    if w >= h * 1.20:
        core_w, core_h = 0.30, 0.80
    elif h >= w * 1.20:
        core_w, core_h = 0.80, 0.30
    else:
        core_w = core_h = 0.52
    cw = max(4, min(w, round(w * core_w)))
    ch = max(4, min(h, round(h * core_h)))
    x = max(0, (w-cw)//2)
    y = max(0, (h-ch)//2)
    return slice(y, y+ch), slice(x, x+cw)


def _single_score(a: np.ndarray, b: np.ndarray) -> float:
    if a.shape != b.shape or min(a.shape) < 3 or float(a.std()) < 2 or float(b.std()) < 2:
        return -1.0
    return float(np.nan_to_num(cv2.matchTemplate(a, b, cv2.TM_CCOEFF_NORMED)[0, 0], nan=-1.0))


def _deformable_score(patch: np.ndarray, template: np.ndarray, raw: float) -> float:
    """Re-score one same-size candidate while tolerating animated extremities.

    This is intentionally a conservative soft-mask analogue, not semantic
    segmentation. The center body gets more weight; edges are only supporting
    evidence. A weak whole-template match alone is never enough.
    """
    ys, xs = _center_slice(template.shape)
    center = _single_score(patch[ys, xs], template[ys, xs])
    edge_patch = cv2.Canny(patch, 60, 150)
    edge_template = cv2.Canny(template, 60, 150)
    edge = max(0.0, _single_score(edge_patch, edge_template))
    center = max(-1.0, center)
    return float(0.18 * max(0.0, raw) + 0.72 * center + 0.10 * edge)


def _compatible(a: Rect, b: Rect) -> bool:
    acx, acy = a.x + a.w/2, a.y + a.h/2
    bcx, bcy = b.x + b.w/2, b.y + b.h/2
    scale = max(12.0, (a.w+a.h+b.w+b.h) / 4)
    distance = ((acx-bcx)**2 + (acy-bcy)**2) ** 0.5
    area_a, area_b = max(1, a.w*a.h), max(1, b.w*b.h)
    ratio = max(area_a/area_b, area_b/area_a)
    return distance <= scale * 0.95 and ratio <= 2.4


class Detector:
    def __init__(self, profile: Profile, read_image: Callable[[str], np.ndarray]):
        errors = profile.validate(calibrated=True)
        if errors:
            raise ValueError("\n".join(errors))
        self.p = profile.clone()
        world = self.p.regions["world"]
        self.factor = min(1.0, self.p.max_search_width / world.w)
        # Profiles created before animated_target existed still benefit when a
        # substantial multi-pose bank is already present.
        self.animated = self.p.animated_target or len(self.p.templates["monster"]) >= 4
        self.bank: dict[str, list[np.ndarray]] = {k: [] for k in self.p.templates}
        for kind, paths in self.p.templates.items():
            for path in paths:
                image = read_image(path)
                if image.ndim == 2:
                    gray = image
                else:
                    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
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
                        h = max(6, round(source.shape[0] * f))
                        w = max(6, round(source.shape[1] * f))
                        resized = cv2.resize(source, (w, h), interpolation=cv2.INTER_AREA)
                        if resized.std() >= 3:
                            self.bank[kind].append(resized)
        if not self.bank["monster"]:
            raise ValueError("Tidak ada template monster yang dapat dipakai.")
        # Core-search is a fallback for deformable frames, not a second full scan
        # across an arbitrarily large bank. Keep representative variants bounded
        # so animated mode remains usable beside the game.
        if len(self.bank["monster"]) <= 30:
            self.core_bank = list(self.bank["monster"])
        else:
            stride = max(1, len(self.bank["monster"]) // 30)
            self.core_bank = self.bank["monster"][::stride][:30]
        self._raw_history: deque[tuple[Detection, ...]] = deque(maxlen=2)
        self._held: list[tuple[Detection, int]] = []

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

    def _monster_candidates(self, sample: np.ndarray, world: Rect, size: tuple[int, int],
                            cancelled: Callable[[], bool]) -> list[Detection]:
        p = self.p
        sx, sy = world.w / sample.shape[1], world.h / sample.shape[0]
        found: list[Detection] = []
        weak_threshold = max(0.58, p.threshold - 0.26) if self.animated else p.threshold
        deformable_threshold = max(0.68, p.threshold - 0.18)
        center_floor = max(0.66, p.threshold - 0.20)

        def register(template: np.ndarray, x: int, y: int, raw: float,
                     *, center_hint: float | None = None):
            h, w = template.shape
            if x < 0 or y < 0 or x+w > sample.shape[1] or y+h > sample.shape[0]:
                return
            patch = sample[y:y+h, x:x+w]
            strong = raw >= p.threshold
            score = raw
            if self.animated and not strong:
                ys, xs = _center_slice(template.shape)
                center = center_hint if center_hint is not None else _single_score(
                    patch[ys, xs], template[ys, xs])
                edge_patch = cv2.Canny(patch, 60, 150)
                edge_template = cv2.Canny(template, 60, 150)
                edge = max(0.0, _single_score(edge_patch, edge_template))
                # Center-search candidates may have very different wing outlines,
                # so the stable body dominates while full-frame appearance remains
                # a guard against matching arbitrary UI/background blobs.
                score = float(0.18 * max(0.0, raw) + 0.72 * center + 0.10 * edge)
                if center < center_floor or score < deformable_threshold:
                    return
            box = Rect(world.x + round(x * sx), world.y + round(y * sy),
                       max(1, round(w * sx)), max(1, round(h * sy)))
            point = (box.x + int(box.w * p.click_x), box.y + int(box.h * p.click_y))
            if (box.valid_in(size) and not any(box.intersects(r) for r in p.exclusions)
                    and not any(box.intersects(d.box) for d in found)):
                found.append(Detection(box, float(score), point, strong=strong))

        # Pass 1: ordinary whole-shape matching. This is the fast/common path.
        for template in self.bank["monster"]:
            if cancelled():
                break
            h, w = template.shape
            if sample.shape[0] < h or sample.shape[1] < w:
                continue
            result = np.nan_to_num(
                cv2.matchTemplate(sample, template, cv2.TM_CCOEFF_NORMED), nan=-1)
            for _ in range(6):
                _, raw, _, (x, y) = cv2.minMaxLoc(result)
                raw = float(raw)
                if raw < weak_threshold:
                    break
                register(template, x, y, raw)
                result[max(0, y-h//2):y+h//2+1,
                       max(0, x-w//2):x+w//2+1] = -1
            if len(found) >= 24:
                break

        # Pass 2 only when no strict pose matched. Search a bounded stable-body
        # core to reacquire bats/slimes whose outer silhouette changed heavily.
        if self.animated and not any(d.strong for d in found) and not cancelled():
            for template in self.core_bank:
                if cancelled() or len(found) >= 24:
                    break
                h, w = template.shape
                if sample.shape[0] < h or sample.shape[1] < w:
                    continue
                ys, xs = _center_slice(template.shape)
                core = template[ys, xs]
                if min(core.shape) < 4 or float(core.std()) < 3:
                    continue
                core_result = np.nan_to_num(
                    cv2.matchTemplate(sample, core, cv2.TM_CCOEFF_NORMED), nan=-1)
                oy, ox = ys.start or 0, xs.start or 0
                ch, cw = core.shape
                for _ in range(5):
                    _, center, _, (cx, cy) = cv2.minMaxLoc(core_result)
                    center = float(center)
                    if center < center_floor:
                        break
                    x, y = cx-ox, cy-oy
                    if 0 <= x <= sample.shape[1]-w and 0 <= y <= sample.shape[0]-h:
                        patch = sample[y:y+h, x:x+w]
                        raw = _single_score(patch, template)
                        register(template, x, y, raw, center_hint=center)
                    core_result[max(0, cy-ch//2):cy+ch//2+1,
                                max(0, cx-cw//2):cx+cw//2+1] = -1
        found.sort(key=lambda d: d.score, reverse=True)
        return found[:24]

    def _temporal(self, raw: list[Detection]) -> list[Detection]:
        """Confirm weak animated matches across frames and bridge one missed scan.

        This is only called by explicit observation-only sessions. Strong strict
        matches still appear immediately. A weak candidate needs spatial support
        from a recent raw/confirmed frame. One previously confirmed box may be
        held for a single missed scan to avoid flicker from a wing-beat frame.
        """
        previous_raw = [d for frame in self._raw_history for d in frame]
        previous_confirmed = [d for d, misses in self._held if misses <= 1]
        confirmed: list[Detection] = []
        for d in raw:
            supported = d.strong or any(_compatible(d.box, old.box)
                                        for old in (*previous_raw, *previous_confirmed))
            if supported:
                confirmed.append(Detection(d.box, d.score, d.point, d.strong,
                                           temporal=not d.strong))
        new_held: list[tuple[Detection, int]] = [(d, 0) for d in confirmed]
        # If a known target completely misses one scan, keep only one stale box.
        for old, misses in self._held:
            if any(_compatible(old.box, d.box) for d in raw):
                continue
            next_miss = misses + 1
            if next_miss <= 1 and not any(_compatible(old.box, d.box) for d in confirmed):
                held = Detection(old.box, max(0.0, old.score * 0.82), old.point,
                                 strong=False, temporal=True)
                confirmed.append(held)
                new_held.append((held, next_miss))
        self._held = new_held[:24]
        self._raw_history.append(tuple(raw))
        confirmed.sort(key=lambda d: d.score, reverse=True)
        return confirmed[:24]

    def observe(self, frame: np.ndarray, captured_at: float, *, search: bool = True,
                cancelled: Callable[[], bool] = lambda: False,
                temporal: bool = False) -> Observation:
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
            found = self._monster_candidates(sample, world, size, cancelled)
            if temporal and self.animated:
                found = self._temporal(found)
        return Observation(
            captured_at, size, tuple(found[:24]),
            fill_ratio(frame, p.regions.get("hp"), p.hp_lower, p.hp_upper),
            fill_ratio(frame, p.regions.get("ap"), p.ap_lower, p.ap_upper),
            fill_ratio(frame, p.regions.get("target_hp"), p.target_lower, p.target_upper),
            self.signal(gray, "combat"), self.signal(gray, "defeat"), True,
            (time.monotonic() - start) * 1000,
        )
