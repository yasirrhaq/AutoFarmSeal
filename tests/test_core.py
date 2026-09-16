from dataclasses import replace
import json

import cv2
import numpy as np
import pytest

from autofarmseal.engine import Engine, State
from autofarmseal.model import Profile, Rect
from autofarmseal.storage import Store
from autofarmseal.vision import Detection, Detector, Observation, fill_ratio


def profile():
    return Profile(width=320, height=200, regions={
        "world": Rect(0, 20, 320, 180), "hp": Rect(5, 5, 100, 5),
        "combat": Rect(200, 0, 20, 10), "defeat": Rect(250, 0, 20, 10),
    }, templates={"monster": ["templates/a.png"], "combat": ["templates/b.png"],
                  "defeat": ["templates/c.png"]}, input_verified=True, scales=[1.0])


def observation(now=1.0, **kw):
    return replace(Observation(now, (320, 200), hp=0.8, ap=0.9), **kw)


def engine():
    e = Engine(profile())
    e.arm(0, delay=0)
    return e


def begin_combat(e):
    target = Detection(Rect(50, 70, 30, 30), 0.99, (65, 88))
    action = e.tick(observation(1, detections=(target,)), 1)
    assert action.kind == "attack"
    e.ack(action, 1)
    e.tick(observation(1.2, combat=True), 1.2)
    e.tick(observation(1.4, combat=True), 1.4)
    assert e.state == State.COMBAT


def test_config_roundtrip():
    p = profile()
    assert Profile.from_dict(json.loads(json.dumps(p.to_dict()))) == p
    assert not p.validate(live=True)


@pytest.mark.parametrize("name,value", [
    ("threshold", float("nan")), ("threshold", float("inf")), ("threshold", 2),
    ("scan_hz", 99), ("scan_hz", 2.5), ("max_frame_age", 0),
    ("scales", []), ("scales", [1]*6), ("scales", [float("nan")]),
    ("id", "../../p"), ("hp_key", "f10"), ("pickup_key", "enter+ctrl"),
    ("hp_enabled", "yes"), ("hp_lower", [200, 1, 1]), ("hp_lower", [-1, 1, 1]),
    ("width", -1), ("name", ""), ("name", "a"*81),
])
def test_reject_invalid_config(name, value):
    p = profile()
    setattr(p, name, value)
    assert p.validate()
    with pytest.raises(ValueError):
        Profile.from_dict(p.to_dict())


def test_starter_profile_allowed_but_live_blocked():
    p = Profile()
    assert p.validate() == []
    assert p.validate(calibrated=True)
    assert p.validate(live=True)


def test_live_requires_pickup_and_ap_calibration():
    p = profile()
    p.loot_enabled = True
    p.ap_enabled = True
    errors = p.validate(live=True)
    assert any("pickup" in x for x in errors)
    assert any("AP" in x for x in errors)


def test_hsv_wrap_supported():
    p = profile()
    p.hp_lower, p.hp_upper = [170, 80, 60], [10, 255, 255]
    assert not p.validate()


def test_regions_and_overlap():
    assert Rect(0, 0, 10, 10).valid_in((10, 10))
    assert not Rect(-1, 0, 10, 10).valid_in((10, 10))
    assert not Rect(0, 0, 10, 10).contains(10, 5)
    assert not Rect(0, 0, 10, 10).intersects(Rect(10, 0, 5, 5))


def test_store_atomic_and_corruption_preserved(tmp_path):
    s = Store(tmp_path)
    p = profile()
    s.save(p)
    p.name = "Changed"
    s.save(p)
    assert s.list_profiles()[0][0].name == "Changed"
    path = tmp_path / "profiles" / f"{p.id}.json"
    path.write_text("not valid json")
    profiles, errors = s.list_profiles()
    assert not profiles and errors
    assert path.read_text() == "not valid json"
    assert not list((tmp_path / "profiles").glob("*.tmp"))


@pytest.mark.parametrize("path", ["../../etc/passwd", "/etc/passwd.png", "profiles/a.png", "templates/../a.png"])
def test_asset_path_escape_blocked(tmp_path, path):
    with pytest.raises(ValueError):
        Store(tmp_path).asset(path)


def test_shared_template_preserved_on_delete(tmp_path):
    s = Store(tmp_path)
    image = np.random.default_rng(1).integers(0, 255, (20, 20, 3), dtype=np.uint8)
    asset = s.image(image)
    p = Profile()
    p.templates["monster"].append(asset)
    s.save(p)
    s.delete(p)
    assert s.asset(asset).exists()


def test_solid_template_rejected(tmp_path):
    with pytest.raises(ValueError):
        Store(tmp_path).image(np.full((20, 20, 3), 120, np.uint8))


def scene():
    rng = np.random.default_rng(10)
    img = rng.integers(0, 50, (200, 320, 3), dtype=np.uint8)
    template = rng.integers(50, 255, (30, 24, 3), dtype=np.uint8)
    img[60:90, 100:124] = template
    p = profile()
    p.templates["combat"] = p.templates["defeat"] = []
    return p, img, template


def test_detector_coordinates_and_no_duplicate_boxes():
    p, frame, template = scene()
    detector = Detector(p, lambda _: template)
    obs = detector.observe(frame, 1)
    assert len(obs.detections) == 1
    assert obs.detections[0].box == Rect(100, 60, 24, 30)
    assert obs.detections[0].point == (112, 79)
    assert obs.detections[0].score > 0.999


def test_detector_exclusion_rejects_entire_box():
    p, frame, template = scene()
    p.exclusions = [Rect(100, 60, 2, 2)]
    assert not Detector(p, lambda _: template).observe(frame, 1).detections


def test_detector_wrong_resolution_and_blank():
    p, frame, template = scene()
    d = Detector(p, lambda _: template)
    assert not d.observe(frame[:100], 1).valid
    assert not d.observe(np.zeros_like(frame), 1).valid


def test_detector_cancel_and_no_search():
    p, frame, template = scene()
    d = Detector(p, lambda _: template)
    assert not d.observe(frame, 1, cancelled=lambda: True).detections
    assert not d.observe(frame, 1, search=False).detections


def test_detector_downscaled_coordinate_mapping():
    p, small, template = scene()
    frame = cv2.resize(small, (1280, 800), interpolation=cv2.INTER_NEAREST)
    template = cv2.resize(template, (96, 120), interpolation=cv2.INTER_NEAREST)
    p.width, p.height = 1280, 800
    p.regions = {"world": Rect(0, 80, 1280, 720)}
    p.max_search_width = 640
    obs = Detector(p, lambda _: template).observe(frame, 1)
    assert obs.detections[0].box == Rect(400, 240, 96, 120)


def test_bar_fill_unknown_and_fragmentation():
    image = np.zeros((10, 100, 3), np.uint8)
    image[:, :40] = (0, 255, 0)
    r = Rect(0, 0, 100, 10)
    assert fill_ratio(image, r, [45, 80, 80], [85, 255, 255]) == pytest.approx(0.4)
    image[:, :] = 0
    assert fill_ratio(image, r, [45, 80, 80], [85, 255, 255]) is None
    image[:, 40:80] = (0, 255, 0)
    assert fill_ratio(image, r, [45, 80, 80], [85, 255, 255]) is None


def test_bar_hue_wrap():
    image = np.zeros((10, 100, 3), np.uint8)
    image[:, :80] = (0, 0, 255)
    assert fill_ratio(image, Rect(0, 0, 100, 10), [170, 80, 80], [10, 255, 255]) == 0.8


@pytest.mark.parametrize("change", [{"valid": False}, {"size": (100, 100)}, {"hp": None}])
def test_untrusted_observations_pause(change):
    e = engine()
    assert e.tick(observation(**change), 1) is None
    assert e.state == State.PAUSED


@pytest.mark.parametrize("stamp", [-2, 2])
def test_stale_or_future_frame_pause(stamp):
    e = engine()
    assert e.tick(observation(stamp), 1) is None
    assert e.state == State.PAUSED


def test_focus_lost_and_arm_delay():
    e = Engine(profile())
    e.arm(0, delay=4)
    e.tick(observation(1), 1, focused=False)
    assert e.state == State.ARMED
    e.tick(observation(5), 5, focused=False)
    assert e.state == State.PAUSED


def test_existing_target_blocks_new_session():
    e = engine()
    e.tick(observation(combat=True), 1)
    assert e.state == State.PAUSED


def test_target_lock_and_missing_not_counted_as_win():
    e = engine()
    begin_combat(e)
    other = Detection(Rect(200, 100, 30, 30), 1.0, (215, 115))
    assert e.tick(observation(2, combat=True, detections=(other,)), 2) is None
    assert e.state == State.COMBAT
    e.tick(observation(3), 3)
    e.tick(observation(5.1), 5.1)
    assert e.state == State.PAUSED
    assert e.confirmed == 0
    assert e.unknown == 1


def test_explicit_defeat_debounce_and_loot_then_next_search():
    e = engine()
    e.p.loot_enabled = True
    e.p.pickup_key = "space"
    begin_combat(e)
    e.tick(observation(2, defeat=True), 2)
    assert e.confirmed == 0
    e.tick(observation(2.2, defeat=True), 2.2)
    assert e.confirmed == 1 and e.state == State.LOOT
    a = e.tick(observation(2.3), 2.3)
    assert a.kind == "pickup"
    e.ack(a, 2.3)
    assert e.tick(observation(2.4), 2.4) is None
    a = e.tick(observation(3.2), 3.2)
    e.ack(a, 3.2)
    e.tick(observation(3.3), 3.3)
    assert e.state == State.SEARCH
    assert e.sent["pickup"] == 2


def test_old_defeat_does_not_count_twice():
    e = engine()
    begin_combat(e)
    e.defeat_cleared = False
    for t in [2, 2.2, 2.4]:
        e.tick(observation(t, combat=True, defeat=True), t)
    assert e.confirmed == 0
    e.tick(observation(3, combat=True), 3)
    e.tick(observation(4, defeat=True), 4)
    e.tick(observation(4.2, defeat=True), 4.2)
    assert e.confirmed == 1
    e.tick(observation(4.4, defeat=True), 4.4)
    assert e.confirmed == 1


def test_disabled_potion_low_hp_pauses():
    e = engine()
    e.tick(observation(hp=0.2), 1)
    assert e.state == State.PAUSED


def test_potion_ack_and_ineffective_limit():
    e = engine()
    e.p.hp_enabled = True
    a = e.tick(observation(1, hp=0.2), 1)
    assert a.kind == "hp"
    assert e.sent["hp"] == 0
    e.ack(a, 1)
    assert e.sent["hp"] == 1
    assert e.tick(observation(2, hp=0.2), 2) is None
    a = e.tick(observation(7, hp=0.2), 7)
    e.ack(a, 7)
    e.tick(observation(13, hp=0.2), 13)
    assert e.state == State.PAUSED
    assert e.sent["hp"] == 2


def test_ap_requires_reading_when_enabled():
    e = engine()
    e.p.ap_enabled = True
    e.tick(observation(ap=None), 1)
    assert e.state == State.PAUSED


def test_no_progress_and_combat_deadline():
    e = engine()
    begin_combat(e)
    e.tick(observation(50, combat=True), 50)
    assert e.state == State.PAUSED and e.confirmed == 0
    e = engine()
    e.p.regions["target_hp"] = Rect(100, 0, 20, 5)
    begin_combat(e)
    e.tick(observation(15, combat=True), 15)
    assert e.state == State.PAUSED


def test_session_limit_stop_and_stop_blocks_inputs():
    e = engine()
    e.p.session_minutes = 1
    e.tick(observation(61), 61)
    assert e.state == State.STOPPED
    assert e.tick(observation(62, hp=0.1), 62) is None


def test_resume_preserves_session_clock_and_cooldowns():
    e = engine()
    e.last_use["hp"] = 1
    e.pause(2, "manual")
    e.arm(5, delay=0)
    assert e.started == 0 and e.last_use["hp"] == 1


def test_search_timeout_and_bounded_attempts():
    e = engine()
    e.tick(observation(1), 1)
    e.tick(observation(32), 32)
    assert e.state == State.PAUSED
    e = engine()
    for i in range(3):
        t = 1 + i * 15
        d = Detection(Rect(40+i*50, 70, 20, 20), .99, (50+i*50, 80))
        a = e.tick(observation(t, detections=(d,)), t)
        assert a and a.kind == "attack"
        e.ack(a, t)
        e.tick(observation(t+6), t+6)
    assert e.state == State.PAUSED
    assert e.attempts == 3


def test_no_native_side_effect_on_core_import():
    import sys
    assert "pyautogui" not in sys.modules


def test_duplicate_observation_not_counted_as_two_confirmations():
    e = engine()
    begin_combat(e)
    obs = observation(2, defeat=True)
    e.tick(obs, 2)
    e.tick(obs, 2.1)
    assert e.confirmed == 0
    e.tick(observation(2.2, defeat=True), 2.2)
    assert e.confirmed == 1
