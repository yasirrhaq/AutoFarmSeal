"""Short, input-free visual learning for moving monster targets.

This is deliberately not a generative model. The user supplies one real crop,
then the learner follows that visual target for a short foreground capture,
keeps only sufficiently different real crops, and lets the runtime detector use
them as additional references. No game input is sent from this module.
"""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from .model import Rect


@dataclass(frozen=True)
class LearnProgress:
    frames: int
    samples: int
    confidence: float
    box: Rect


def _gray(image: np.ndarray) -> np.ndarray:
    if image.ndim == 2:
        return image
    return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)


def _descriptor(image: np.ndarray) -> np.ndarray:
    """Compact appearance descriptor used only for duplicate suppression.

    A center-weighted equalized grayscale view plus edges reduces the influence
    of surrounding grass/terrain without pretending to perform semantic
    segmentation. It is not used as a probability or identity classifier.
    """
    gray = _gray(image)
    gray = cv2.resize(gray, (48, 48), interpolation=cv2.INTER_AREA)
    gray = cv2.equalizeHist(gray)
    edge = cv2.Canny(gray, 60, 150)
    yy, xx = np.mgrid[-1:1:48j, -1:1:48j]
    weight = np.exp(-1.7 * (xx * xx + yy * yy)).astype(np.float32)
    a = gray.astype(np.float32) * weight
    b = edge.astype(np.float32) * weight
    vector = np.concatenate((a.ravel(), 0.65 * b.ravel()))
    vector -= float(vector.mean())
    norm = float(np.linalg.norm(vector))
    if norm <= 1e-6:
        return np.zeros_like(vector)
    return vector / norm


def _similarity(a: np.ndarray, b: np.ndarray) -> float:
    if not a.any() or not b.any():
        return 1.0
    return float(np.clip(np.dot(a, b), -1.0, 1.0))


def _clamp(rect: Rect, outer: Rect) -> Rect | None:
    left = max(rect.x, outer.x)
    top = max(rect.y, outer.y)
    right = min(rect.right, outer.right)
    bottom = min(rect.bottom, outer.bottom)
    if right - left < 8 or bottom - top < 8:
        return None
    return Rect(left, top, right-left, bottom-top)


def _expanded(rect: Rect, fraction: float, outer: Rect) -> Rect | None:
    px = max(2, round(rect.w * fraction))
    py = max(2, round(rect.h * fraction))
    return _clamp(Rect(rect.x-px, rect.y-py, rect.w+2*px, rect.h+2*py), outer)


class MultiPoseLearner:
    """Track one seed appearance and harvest diverse real crops.

    Optical flow handles ordinary movement between adjacent frames. If flow
    quality drops, the seed is searched again inside the calibrated world ROI.
    This is intentionally bounded and transparent; callers should surface a
    failure instead of silently learning unrelated scenery.
    """

    def __init__(self, first_frame: np.ndarray, seed_image: np.ndarray, world: Rect,
                 *, initial_box: Rect | None = None, max_samples: int = 10):
        if first_frame.ndim != 3 or first_frame.shape[2] < 3:
            raise ValueError("Frame belajar tidak valid.")
        size = (first_frame.shape[1], first_frame.shape[0])
        if not world.valid_in(size):
            raise ValueError("Area pencarian berada di luar gambar belajar.")
        if seed_image.size == 0 or min(seed_image.shape[:2]) < 8:
            raise ValueError("Contoh monster terlalu kecil untuk belajar otomatis.")
        if not 2 <= max_samples <= 11:
            raise ValueError("Jumlah contoh otomatis harus 2–11.")
        self.world = world
        self.seed = seed_image[:, :, :3].copy()
        self.max_samples = max_samples
        self.samples: list[np.ndarray] = []
        self.descriptors = [_descriptor(self.seed)]
        self.sample_sizes = [(self.seed.shape[1], self.seed.shape[0])]
        self.frames = 0
        self.last_sample_time = -1e9
        self.prev_gray = _gray(first_frame)
        self.last_gray_crop = _gray(self.seed)
        self.box, score = self._initial_location(first_frame, initial_box)
        if score < 0.38:
            raise ValueError(
                "Monster awal sudah berubah terlalu jauh sebelum belajar dimulai. "
                "Ambil gambar terbaru, kotaki monster, lalu segera tekan Belajar otomatis.")
        self.confidence = score
        self.points = self._features(self.prev_gray, self.box)
        self._consider(first_frame, 0.0, force=False)

    def _initial_location(self, frame: np.ndarray, initial_box: Rect | None) -> tuple[Rect, float]:
        if initial_box and initial_box.valid_in((frame.shape[1], frame.shape[0])):
            direct = initial_box.crop(frame)
            score = self._crop_similarity(direct, self.seed)
            if score >= 0.50:
                return initial_box, score
        return self._locate(frame, self.seed, self.world)

    @staticmethod
    def _crop_similarity(a: np.ndarray, b: np.ndarray) -> float:
        ga, gb = _gray(a), _gray(b)
        if ga.size == 0 or gb.size == 0:
            return -1.0
        ga = cv2.resize(ga, (48, 48), interpolation=cv2.INTER_AREA)
        gb = cv2.resize(gb, (48, 48), interpolation=cv2.INTER_AREA)
        ga = cv2.equalizeHist(ga)
        gb = cv2.equalizeHist(gb)
        return float(cv2.matchTemplate(ga, gb, cv2.TM_CCOEFF_NORMED)[0, 0])

    @staticmethod
    def _locate(frame: np.ndarray, template: np.ndarray, world: Rect) -> tuple[Rect, float]:
        search = _gray(world.crop(frame))
        base = _gray(template)
        best_score = -1.0
        best_box = None
        for scale in (0.55, 0.70, 0.85, 1.0, 1.15, 1.30, 1.45):
            h = max(8, round(base.shape[0] * scale))
            w = max(8, round(base.shape[1] * scale))
            if h >= search.shape[0] or w >= search.shape[1]:
                continue
            templ = cv2.resize(base, (w, h), interpolation=cv2.INTER_AREA)
            if float(templ.std()) < 3:
                continue
            result = np.nan_to_num(cv2.matchTemplate(search, templ, cv2.TM_CCOEFF_NORMED), nan=-1)
            _, score, _, point = cv2.minMaxLoc(result)
            if score > best_score:
                best_score = float(score)
                best_box = Rect(world.x + point[0], world.y + point[1], w, h)
        if best_box is None:
            raise ValueError("Contoh monster tidak muat di area pencarian.")
        return best_box, best_score

    @staticmethod
    def _features(gray: np.ndarray, box: Rect) -> np.ndarray:
        mask = np.zeros_like(gray, dtype=np.uint8)
        # Prefer the more stable center body over highly deformable extremities.
        margin_x = max(1, round(box.w * 0.16))
        margin_y = max(1, round(box.h * 0.16))
        x1, y1 = box.x + margin_x, box.y + margin_y
        x2, y2 = box.right - margin_x, box.bottom - margin_y
        if x2 <= x1 or y2 <= y1:
            x1, y1, x2, y2 = box.x, box.y, box.right, box.bottom
        mask[y1:y2, x1:x2] = 255
        points = cv2.goodFeaturesToTrack(gray, mask=mask, maxCorners=80,
                                         qualityLevel=0.015, minDistance=3, blockSize=5)
        if points is None:
            return np.empty((0, 1, 2), dtype=np.float32)
        return points.astype(np.float32)

    def _flow_box(self, gray: np.ndarray) -> tuple[Rect | None, float]:
        if len(self.points) < 5:
            return None, 0.0
        new, status, _ = cv2.calcOpticalFlowPyrLK(
            self.prev_gray, gray, self.points, None,
            winSize=(21, 21), maxLevel=3,
            criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 20, 0.02),
        )
        if new is None or status is None:
            return None, 0.0
        good_old = self.points[status.reshape(-1) == 1].reshape(-1, 2)
        good_new = new[status.reshape(-1) == 1].reshape(-1, 2)
        if len(good_new) < 5:
            return None, 0.0
        transform, inliers = cv2.estimateAffinePartial2D(
            good_old, good_new, method=cv2.RANSAC, ransacReprojThreshold=3.0,
            maxIters=100, confidence=0.95)
        if transform is None:
            delta = np.median(good_new-good_old, axis=0)
            candidate = Rect(round(self.box.x+float(delta[0])), round(self.box.y+float(delta[1])),
                             self.box.w, self.box.h)
            inlier_ratio = min(1.0, len(good_new)/20)
        else:
            corners = np.array([[[self.box.x, self.box.y]],
                                [[self.box.right, self.box.y]],
                                [[self.box.right, self.box.bottom]],
                                [[self.box.x, self.box.bottom]]], dtype=np.float32)
            moved = cv2.transform(corners, transform).reshape(-1, 2)
            left, top = np.min(moved, axis=0)
            right, bottom = np.max(moved, axis=0)
            candidate = Rect(round(float(left)), round(float(top)),
                             max(8, round(float(right-left))), max(8, round(float(bottom-top))))
            inlier_ratio = float(inliers.mean()) if inliers is not None and len(inliers) else 0.0
        candidate = _clamp(candidate, self.world)
        if candidate is None:
            return None, 0.0
        area_ratio = (candidate.w*candidate.h) / max(1, self.box.w*self.box.h)
        if not 0.45 <= area_ratio <= 2.2:
            return None, 0.0
        point_score = min(1.0, len(good_new)/25)
        return candidate, 0.45*point_score + 0.55*inlier_ratio

    def _consider(self, frame: np.ndarray, now: float, *, force: bool = False) -> bool:
        if len(self.samples) >= self.max_samples or (not force and now-self.last_sample_time < 0.55):
            return False
        # Animated/deformable targets (bat wings, slime, cloth) need breathing room.
        # The detector later down-weights this outer context, so the margin does not
        # become the primary identity signal.
        padded = _expanded(self.box, 0.18, self.world) or self.box
        crop = padded.crop(frame).copy()
        if min(crop.shape[:2]) < 10:
            return False
        sharpness = float(cv2.Laplacian(_gray(crop), cv2.CV_64F).var())
        if sharpness < 10:
            return False
        desc = _descriptor(crop)
        similarities = [_similarity(desc, old) for old in self.descriptors]
        w, h = crop.shape[1], crop.shape[0]
        size_novel = all(max(w/max(1, ow), ow/max(1, w), h/max(1, oh), oh/max(1, h)) >= 1.20
                         for ow, oh in self.sample_sizes)
        if not force and similarities and max(similarities) >= 0.93 and not size_novel:
            return False
        self.samples.append(crop)
        self.descriptors.append(desc)
        self.sample_sizes.append((w, h))
        self.last_sample_time = now
        return True

    def update(self, frame: np.ndarray, now: float) -> LearnProgress:
        if (frame.shape[1], frame.shape[0]) != (self.prev_gray.shape[1], self.prev_gray.shape[0]):
            raise ValueError("Ukuran jendela game berubah saat belajar.")
        gray = _gray(frame)
        candidate, confidence = self._flow_box(gray)
        if candidate is None or confidence < 0.24:
            last = self.last_gray_crop if self.last_gray_crop.size else _gray(self.seed)
            candidate, match = self._locate(frame, last, self.world)
            if match < 0.32:
                candidate, match = self._locate(frame, self.seed, self.world)
            if match < 0.34:
                raise ValueError("Tracking kehilangan monster. Pastikan monster masih terlihat dan tidak tertutup.")
            confidence = match
        self.box = candidate
        self.confidence = float(np.clip(confidence, 0.0, 1.0))
        self.frames += 1
        self._consider(frame, now)
        self.prev_gray = gray
        self.last_gray_crop = self.box.crop(gray).copy()
        self.points = self._features(gray, self.box)
        return LearnProgress(self.frames, len(self.samples), self.confidence, self.box)

    def finalize(self) -> list[np.ndarray]:
        return [sample.copy() for sample in self.samples]
