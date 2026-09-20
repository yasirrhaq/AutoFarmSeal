"""Conservative bounded screen recognition. Coordinates are client pixels.

Animated targets can tolerate deforming silhouettes, but weak matches never pass
because one tiny core happens to resemble the scene. In animated mode, a weak
or ordinary match needs independent support from multiple learned source crops
at the same location. Only an exceptionally strong, center-validated match can
stand alone. Temporal smoothing happens after this spatial/source consensus.
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
    votes: int = 1


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


@dataclass(frozen=True)
class _Variant:
    source_id: int
    image: np.ndarray
    mirrored: bool


@dataclass(frozen=True)
class _Proposal:
    detection: Detection
    source_id: int


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
    """Adaptive body core: de-emphasize likely deforming extremities."""
    h, w = shape
    if w >= h * 1.20:
        core_w, core_h = 0.30, 0.78
    elif h >= w * 1.20:
        core_w, core_h = 0.78, 0.30
    else:
        core_w = core_h = 0.50
    cw = max(5, min(w, round(w * core_w)))
    ch = max(5, min(h, round(h * core_h)))
    x = max(0, (w-cw)//2)
    y = max(0, (h-ch)//2)
    return slice(y, y+ch), slice(x, x+cw)


def _single_score(a: np.ndarray, b: np.ndarray) -> float:
    if a.shape != b.shape or min(a.shape) < 3 or float(a.std()) < 2 or float(b.std()) < 2:
        return -1.0
    value = cv2.matchTemplate(a, b, cv2.TM_CCOEFF_NORMED)[0, 0]
    return float(np.nan_to_num(value, nan=-1.0))


def _edge_score(a: np.ndarray, b: np.ndarray) -> float:
    return max(0.0, _single_score(cv2.Canny(a, 60, 150), cv2.Canny(b, 60, 150)))


def _compatible(a: Rect, b: Rect, *, loose: bool = False) -> bool:
    acx, acy = a.x + a.w/2, a.y + a.h/2
    bcx, bcy = b.x + b.w/2, b.y + b.h/2
    scale = max(12.0, (a.w+a.h+b.w+b.h) / 4)
    distance = ((acx-bcx)**2 + (acy-bcy)**2) ** 0.5
    area_a, area_b = max(1, a.w*a.h), max(1, b.w*b.h)
    ratio = max(area_a/area_b, area_b/area_a)
    return distance <= scale * (0.80 if loose else 0.48) and ratio <= (2.4 if loose else 2.0)


def _iou(a: Rect, b: Rect) -> float:
    left, top = max(a.x, b.x), max(a.y, b.y)
    right, bottom = min(a.right, b.right), min(a.bottom, b.bottom)
    inter = max(0, right-left) * max(0, bottom-top)
    if not inter:
        return 0.0
    return inter / max(1, a.w*a.h + b.w*b.h - inter)


class Detector:
    def __init__(self, profile: Profile, read_image: Callable[[str], np.ndarray]):
        errors = profile.validate(calibrated=True)
        if errors:
            raise ValueError("\n".join(errors))
        self.p = profile.clone()
        world = self.p.regions["world"]
        self.factor = min(1.0, self.p.max_search_width / world.w)
        self.source_count = len(self.p.templates["monster"])
        self.animated = self.p.animated_target or self.source_count >= 4
        self.bank: dict[str, list[np.ndarray]] = {k: [] for k in self.p.templates}
        self.monster_bank: list[_Variant] = []
        self.core_bank: list[_Variant] = []

        for kind, paths in self.p.templates.items():
            for source_id, path in enumerate(paths):
                image = read_image(path)
                gray = image if image.ndim == 2 else cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
                if min(gray.shape) < 6 or float(gray.std()) < 3:
                    raise ValueError(f"Template {path} terlalu kecil atau polos.")
                scales = self.p.scales if kind == "monster" else [1.0]
                sources = [(gray, False)]
                if kind == "monster" and self.p.mirror_templates:
                    mirrored = cv2.flip(gray, 1)
                    if not np.array_equal(mirrored, gray):
                        sources.append((mirrored, True))
                for source, mirrored in sources:
                    for scale in scales:
                        f = scale * (self.factor if kind == "monster" else 1.0)
                        h = max(6, round(source.shape[0] * f))
                        w = max(6, round(source.shape[1] * f))
                        resized = cv2.resize(source, (w, h), interpolation=cv2.INTER_AREA)
                        if resized.std() < 3:
                            continue
                        self.bank[kind].append(resized)
                        if kind == "monster":
                            variant = _Variant(source_id, resized, mirrored)
                            self.monster_bank.append(variant)
                            # The stable-body fallback does not need mirrored duplicates;
                            # keep normal scale variants so votes represent real source crops.
                            if not mirrored:
                                self.core_bank.append(variant)
        if not self.monster_bank:
            raise ValueError("Tidak ada template monster yang dapat dipakai.")

        # Balance the expensive fallback across source crops, not merely the first
        # N scale/mirror variants. At most three normal-scale variants per source.
        by_source: dict[int, list[_Variant]] = {}
        for variant in self.core_bank:
            by_source.setdefault(variant.source_id, []).append(variant)
        balanced: list[_Variant] = []
        for source_id in sorted(by_source):
            variants = by_source[source_id]
            if len(variants) <= 3:
                balanced.extend(variants)
            else:
                indexes = np.linspace(0, len(variants)-1, 3).round().astype(int)
                balanced.extend(variants[i] for i in indexes)
        self.core_bank = balanced[:36]
        self.required_votes = 1 if not self.animated else (3 if self.source_count >= 6 else 2)
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

    def _proposal(self, variant: _Variant, sample: np.ndarray, world: Rect,
                  size: tuple[int, int], x: int, y: int, raw: float,
                  *, center_hint: float | None = None) -> _Proposal | None:
        p = self.p
        template = variant.image
        h, w = template.shape
        if x < 0 or y < 0 or x+w > sample.shape[1] or y+h > sample.shape[0]:
            return None
        patch = sample[y:y+h, x:x+w]
        strong = raw >= p.threshold

        if self.animated:
            ys, xs = _center_slice(template.shape)
            center = center_hint if center_hint is not None else _single_score(
                patch[ys, xs], template[ys, xs])
            edge = _edge_score(patch, template)
            # A strict whole-crop score is not enough for learned animated crops:
            # surrounding grass/terrain can otherwise dominate the correlation.
            if strong:
                center_floor = max(0.64, p.threshold - 0.18)
                score = 0.58 * raw + 0.32 * max(0.0, center) + 0.10 * edge
                if center < center_floor or score < max(0.78, p.threshold - 0.06):
                    return None
            else:
                center_floor = max(0.76, p.threshold - 0.10)
                raw_floor = max(0.24, p.threshold - 0.60)
                score = 0.18 * max(0.0, raw) + 0.72 * max(0.0, center) + 0.10 * edge
                if raw < raw_floor or center < center_floor or score < max(0.74, p.threshold - 0.12):
                    return None
        else:
            if not strong:
                return None
            score = raw

        sx, sy = world.w / sample.shape[1], world.h / sample.shape[0]
        box = Rect(world.x + round(x * sx), world.y + round(y * sy),
                   max(1, round(w * sx)), max(1, round(h * sy)))
        point = (box.x + int(box.w * p.click_x), box.y + int(box.h * p.click_y))
        if not box.valid_in(size) or any(box.intersects(r) for r in p.exclusions):
            return None
        return _Proposal(Detection(box, float(score), point, strong=strong), variant.source_id)

    def _consensus(self, proposals: list[_Proposal]) -> list[Detection]:
        if not proposals:
            return []
        if not self.animated:
            result: list[Detection] = []
            for proposal in sorted(proposals, key=lambda x: x.detection.score, reverse=True):
                if any(_iou(proposal.detection.box, old.box) > 0.35 for old in result):
                    continue
                result.append(proposal.detection)
                if len(result) >= 24:
                    break
            return result

        clusters: list[list[_Proposal]] = []
        for proposal in sorted(proposals, key=lambda x: x.detection.score, reverse=True):
            for cluster in clusters:
                if _compatible(proposal.detection.box, cluster[0].detection.box):
                    cluster.append(proposal)
                    break
            else:
                clusters.append([proposal])

        accepted: list[Detection] = []
        for cluster in clusters:
            # One source may contribute mirror + scale variants, but it gets only
            # one vote. Animated profiles deliberately have NO single-source
            # bypass: a false background patch must not become a target merely
            # because it matches one learned crop extremely well.
            per_source: dict[int, _Proposal] = {}
            for proposal in cluster:
                old = per_source.get(proposal.source_id)
                if old is None or proposal.detection.score > old.detection.score:
                    per_source[proposal.source_id] = proposal
            unique = sorted(per_source.values(), key=lambda x: x.detection.score, reverse=True)
            votes = len(unique)
            best = unique[0].detection
            support_scores = [p.detection.score for p in unique[:self.required_votes]]
            mean_support = float(np.mean(support_scores)) if support_scores else 0.0
            consensus = votes >= self.required_votes and mean_support >= max(
                0.76, self.p.threshold - 0.10)
            if not consensus:
                continue
            det = Detection(
                best.box, mean_support, best.point,
                strong=all(p.detection.strong for p in unique[:self.required_votes]),
                votes=votes,
            )
            if any(_iou(det.box, old.box) > 0.35 for old in accepted):
                continue
            accepted.append(det)
            if len(accepted) >= 12:
                break
        accepted.sort(key=lambda d: (d.votes, d.score), reverse=True)
        return accepted

    def _monster_candidates(self, sample: np.ndarray, world: Rect, size: tuple[int, int],
                            cancelled: Callable[[], bool]) -> list[Detection]:
        p = self.p
        proposals: list[_Proposal] = []
        whole_floor = p.threshold if not self.animated else max(0.70, p.threshold - 0.16)

        # Pass 1: whole-shape proposals. Animated targets still require center
        # validation and later source consensus.
        for variant in self.monster_bank:
            if cancelled():
                break
            template = variant.image
            h, w = template.shape
            if sample.shape[0] < h or sample.shape[1] < w:
                continue
            result = np.nan_to_num(cv2.matchTemplate(
                sample, template, cv2.TM_CCOEFF_NORMED), nan=-1)
            for _ in range(4):
                _, raw, _, (x, y) = cv2.minMaxLoc(result)
                raw = float(raw)
                if raw < whole_floor:
                    break
                proposal = self._proposal(variant, sample, world, size, x, y, raw)
                if proposal is not None:
                    proposals.append(proposal)
                result[max(0, y-h//2):y+h//2+1,
                       max(0, x-w//2):x+w//2+1] = -1

        accepted = self._consensus(proposals)
        if accepted or not self.animated or cancelled() or self.source_count < 2:
            return accepted[:12]

        # Pass 2: stable-body fallback only when whole-shape consensus found
        # nothing. It is intentionally stricter and still needs multiple distinct
        # source crops to agree on the same location.
        center_floor = max(0.76, p.threshold - 0.10)
        core_proposals: list[_Proposal] = []
        for variant in self.core_bank:
            if cancelled():
                break
            template = variant.image
            h, w = template.shape
            if sample.shape[0] < h or sample.shape[1] < w:
                continue
            ys, xs = _center_slice(template.shape)
            core = template[ys, xs]
            if min(core.shape) < 5 or float(core.std()) < 3:
                continue
            core_result = np.nan_to_num(cv2.matchTemplate(
                sample, core, cv2.TM_CCOEFF_NORMED), nan=-1)
            oy, ox = ys.start or 0, xs.start or 0
            ch, cw = core.shape
            for _ in range(3):
                _, center, _, (cx, cy) = cv2.minMaxLoc(core_result)
                center = float(center)
                if center < center_floor:
                    break
                x, y = cx-ox, cy-oy
                if 0 <= x <= sample.shape[1]-w and 0 <= y <= sample.shape[0]-h:
                    patch = sample[y:y+h, x:x+w]
                    raw = _single_score(patch, template)
                    proposal = self._proposal(
                        variant, sample, world, size, x, y, raw, center_hint=center)
                    if proposal is not None:
                        core_proposals.append(proposal)
                core_result[max(0, cy-ch//2):cy+ch//2+1,
                            max(0, cx-cw//2):cx+cw//2+1] = -1
        return self._consensus(core_proposals)[:12]

    def _temporal(self, raw: list[Detection]) -> list[Detection]:
        """Smooth only candidates that already passed source consensus."""
        previous_raw = [d for frame in self._raw_history for d in frame]
        previous_confirmed = [d for d, misses in self._held if misses <= 1]
        confirmed: list[Detection] = []
        for d in raw:
            supported = d.strong or d.votes >= self.required_votes or any(
                _compatible(d.box, old.box, loose=True)
                for old in (*previous_raw, *previous_confirmed))
            if supported:
                confirmed.append(Detection(d.box, d.score, d.point, d.strong,
                                           temporal=not d.strong, votes=d.votes))
        new_held: list[tuple[Detection, int]] = [(d, 0) for d in confirmed]
        # Bridge one missing scan only for something already accepted by source
        # consensus; never create a target from temporal persistence alone.
        for old, misses in self._held:
            if any(_compatible(old.box, d.box, loose=True) for d in raw):
                continue
            next_miss = misses + 1
            if next_miss <= 1 and old.votes >= self.required_votes:
                held = Detection(old.box, max(0.0, old.score * 0.82), old.point,
                                 strong=False, temporal=True, votes=old.votes)
                if not any(_compatible(held.box, d.box) for d in confirmed):
                    confirmed.append(held)
                    new_held.append((held, next_miss))
        self._held = new_held[:12]
        self._raw_history.append(tuple(raw))
        confirmed.sort(key=lambda d: (d.votes, d.score), reverse=True)
        return confirmed[:12]

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
            captured_at, size, tuple(found[:12]),
            fill_ratio(frame, p.regions.get("hp"), p.hp_lower, p.hp_upper),
            fill_ratio(frame, p.regions.get("ap"), p.ap_lower, p.ap_upper),
            fill_ratio(frame, p.regions.get("target_hp"), p.target_lower, p.target_upper),
            self.signal(gray, "combat"), self.signal(gray, "defeat"), True,
            (time.monotonic() - start) * 1000,
        )
