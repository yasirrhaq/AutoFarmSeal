import cv2
import numpy as np

from autofarmseal.learner import MultiPoseLearner
from autofarmseal.model import Profile, Rect
from autofarmseal.vision import Detector


def monster_patch(width=42, height=50):
    patch = np.zeros((height, width, 3), np.uint8)
    cv2.circle(patch, (width//2, 14), 9, (220, 220, 220), -1)
    cv2.rectangle(patch, (11, 23), (31, 44), (160, 210, 90), -1)
    cv2.line(patch, (8, 28), (1, 39), (250, 80, 40), 4)
    cv2.circle(patch, (27, 12), 2, (10, 10, 10), -1)
    return patch


def frame_at(x, y, patch=None, *, width=360, height=240):
    rng = np.random.default_rng(123)
    frame = rng.integers(15, 55, (height, width, 3), dtype=np.uint8)
    patch = monster_patch() if patch is None else patch
    h, w = patch.shape[:2]
    frame[y:y+h, x:x+w] = patch
    return frame


def test_multi_pose_learner_tracks_real_motion_and_keeps_bounded_samples():
    seed = monster_patch()
    first = frame_at(80, 90, seed)
    learner = MultiPoseLearner(first, seed, Rect(20, 40, 320, 180),
                               initial_box=Rect(80, 90, 42, 50), max_samples=6)
    now = 0.0
    for i in range(1, 20):
        now += 0.6
        patch = seed.copy()
        cv2.line(patch, (12+i % 8, 42), (5+i % 5, 49), (80+i*4, 160, 230), 2)
        progress = learner.update(frame_at(80+i*3, 90+i//3, patch), now)
        assert progress.box.valid_in((360, 240))
        assert 0 <= progress.confidence <= 1
    samples = learner.finalize()
    assert 1 <= len(samples) <= 6
    assert learner.frames == 19


def test_learner_rejects_seed_that_cannot_be_reacquired():
    seed = monster_patch()
    blank = np.random.default_rng(4).integers(0, 40, (240, 360, 3), dtype=np.uint8)
    try:
        MultiPoseLearner(blank, seed, Rect(0, 0, 360, 240), initial_box=Rect(80, 90, 42, 50))
    except ValueError as exc:
        assert "berubah terlalu jauh" in str(exc)
    else:
        raise AssertionError("unrelated frame must not be accepted as the seed target")


def test_detector_can_use_horizontal_mirror_without_extra_saved_template():
    template = monster_patch(34, 44)
    flipped = cv2.flip(template, 1)
    frame = np.random.default_rng(9).integers(0, 35, (160, 240, 3), np.uint8)
    frame[60:104, 110:144] = flipped
    p = Profile(width=240, height=160, regions={"world": Rect(0, 0, 240, 160)})
    p.templates["monster"] = ["templates/a.png"]
    p.templates["combat"] = []
    p.templates["defeat"] = []
    p.scales = [1.0]
    p.threshold = 0.92
    p.mirror_templates = True
    assert Detector(p, lambda _path: template).observe(frame, 1).detections
    p.mirror_templates = False
    assert not Detector(p, lambda _path: template).observe(frame, 1).detections
