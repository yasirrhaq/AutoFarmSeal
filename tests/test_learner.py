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


def bat_patch(wings_up=True):
    image = np.zeros((50, 70, 3), np.uint8)
    cv2.ellipse(image, (35, 27), (7, 12), 0, 0, 360, (210, 210, 210), -1)
    cv2.circle(image, (35, 16), 6, (235, 235, 235), -1)
    cv2.circle(image, (33, 15), 1, (20, 20, 20), -1)
    cv2.circle(image, (37, 15), 1, (20, 20, 20), -1)
    if wings_up:
        left = np.array([[29, 22], [8, 4], [3, 18], [27, 31]], np.int32)
        right = np.array([[41, 22], [62, 4], [67, 18], [43, 31]], np.int32)
    else:
        left = np.array([[29, 22], [7, 36], [12, 48], [30, 33]], np.int32)
        right = np.array([[41, 22], [63, 36], [58, 48], [40, 33]], np.int32)
    cv2.fillConvexPoly(image, left, (150, 170, 190))
    cv2.fillConvexPoly(image, right, (150, 170, 190))
    cv2.line(image, (35, 27), (35, 41), (80, 80, 80), 2)
    return image


def bat_scene(patch):
    frame = np.random.default_rng(71).integers(0, 35, (180, 280, 3), np.uint8)
    frame[70:120, 120:190] = patch
    return frame


def bat_profile(animated):
    p = Profile(width=280, height=180, regions={"world": Rect(0, 0, 280, 180)},
                threshold=0.86, scales=[1.0], animated_target=animated,
                mirror_templates=False)
    p.templates["monster"] = ["templates/bat.png"]
    p.templates["combat"] = []
    p.templates["defeat"] = []
    return p


def test_animated_detector_reacquires_stable_body_when_wings_change_pose():
    seed = bat_patch(True)
    target = bat_patch(False)
    frame = bat_scene(target)
    strict = Detector(bat_profile(False), lambda _path: seed).observe(frame, 1)
    assert not strict.detections
    tolerant = Detector(bat_profile(True), lambda _path: seed).observe(frame, 1)
    assert tolerant.detections
    best = tolerant.detections[0]
    assert best.box == Rect(120, 70, 70, 50)
    assert not best.strong
    assert best.score >= 0.68


def test_temporal_mode_confirms_weak_deformable_match_on_second_frame():
    seed = bat_patch(True)
    frame = bat_scene(bat_patch(False))
    detector = Detector(bat_profile(True), lambda _path: seed)
    first = detector.observe(frame, 1, temporal=True)
    second = detector.observe(frame, 1.2, temporal=True)
    assert not first.detections
    assert second.detections
    assert second.detections[0].temporal
    assert not second.detections[0].strong


def test_temporal_mode_bridges_only_one_missing_scan():
    seed = bat_patch(True)
    detector = Detector(bat_profile(True), lambda _path: seed)
    strong = bat_scene(seed)
    blank = np.random.default_rng(99).integers(0, 35, (180, 280, 3), np.uint8)
    assert detector.observe(strong, 1, temporal=True).detections
    held = detector.observe(blank, 1.2, temporal=True)
    assert held.detections and held.detections[0].temporal
    assert not detector.observe(blank, 1.4, temporal=True).detections


def test_learning_samples_have_margin_for_fast_deforming_extremities():
    seed = monster_patch()
    first = frame_at(80, 90, seed)
    learner = MultiPoseLearner(first, seed, Rect(20, 40, 320, 180),
                               initial_box=Rect(80, 90, 42, 50), max_samples=3)
    learner.update(frame_at(83, 90, seed), 1.0)
    samples = learner.finalize()
    assert samples
    assert samples[0].shape[1] > seed.shape[1]
    assert samples[0].shape[0] > seed.shape[0]
