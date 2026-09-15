"""Deterministic controller: observes facts, returns at most one bounded action.

No capture, sleeping, UI, OS input, or network in this module. The adapter must
recheck focus/geometry/freshness/cancellation immediately before EVERY input.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .model import Profile, Rect
from .vision import Observation


class State(StrEnum):
    IDLE = "Siap"
    ARMED = "Menunggu fokus game"
    SEARCH = "Mencari target"
    ENGAGE = "Memeriksa serangan"
    COMBAT = "Menyerang"
    LOOT = "Mengambil loot"
    PAUSED = "Dijeda"
    STOPPED = "Berhenti"


@dataclass(frozen=True)
class Action:
    kind: str
    point: tuple[int, int] | None = None


class Engine:
    def __init__(self, profile: Profile):
        self.p = profile.clone()
        self.state = State.IDLE
        self.reason = "Belum ada sesi."
        self.started: float | None = None
        self.entered = 0.0
        self.arm_until = 0.0
        self.target: Rect | None = None
        self.blacklist: list[tuple[Rect, float]] = []
        self.attempts = 0
        self.confirmed = 0
        self.unknown = 0
        self.consecutive_failures = 0
        self.sent = {"hp": 0, "ap": 0, "pickup": 0}
        self.pending: dict[str, tuple[float, float]] = {}
        self.ineffective = {"hp": 0, "ap": 0}
        self.last_use = {"hp": -1e9, "ap": -1e9}
        self.defeat_cleared = False
        self.defeat_hits = 0
        self.combat_hits = 0
        self.no_combat_since: float | None = None
        self.last_target_hp: float | None = None
        self.progress_at = 0.0
        self.loot_sent = 0
        self.last_loot = -1e9
        self.last_observation: Observation | None = None
        self.last_processed: float | None = None

    def change(self, state: State, now: float, reason: str):
        self.state, self.entered, self.reason = state, now, reason

    def arm(self, now: float, delay: float = 4.0):
        if self.state not in {State.IDLE, State.PAUSED, State.STOPPED}:
            return
        if self.started is None:
            self.started = now
        self.target = None
        self.arm_until = now + delay
        self.combat_hits = self.defeat_hits = 0
        self.defeat_cleared = False
        self.no_combat_since = None
        self.change(State.ARMED, now, "Kembali ke game; jangan biarkan menu menutupinya.")

    def pause(self, now: float, reason: str):
        if self.state in {State.ENGAGE, State.COMBAT}:
            self.unknown += 1
        self.target = None
        self.change(State.PAUSED, now, reason)

    def stop(self, now: float, reason: str = "Dihentikan pengguna."):
        if self.state in {State.ENGAGE, State.COMBAT}:
            self.unknown += 1
        self.target = None
        self.change(State.STOPPED, now, reason)

    def ack(self, action: Action, now: float):
        """Called only after the input adapter successfully finishes the action."""
        if action.kind == "attack":
            self.attempts += 1
        elif action.kind in {"hp", "ap"}:
            kind = action.kind
            value = getattr(self.last_observation, kind, None)
            self.sent[kind] += 1
            self.last_use[kind] = now
            if value is not None:
                self.pending[kind] = (value, now)
        elif action.kind == "pickup":
            self.sent["pickup"] += 1
            self.loot_sent += 1
            self.last_loot = now

    def _resources(self, obs: Observation, now: float) -> Action | None:
        for kind in ("hp", "ap"):
            enabled = getattr(self.p, f"{kind}_enabled")
            value = getattr(obs, kind)
            if (kind == "hp" and value is None) or (enabled and value is None):
                self.pause(now, f"{kind.upper()} tidak terbaca; periksa kalibrasi.")
                return None
            if not enabled:
                if kind == "hp" and value is not None and value < self.p.hp_threshold:
                    self.pause(now, "HP rendah dan Auto HP dimatikan.")
                    return None
                continue
            if kind in self.pending:
                before, sent_at = self.pending[kind]
                if value > before + 0.02:
                    del self.pending[kind]
                    self.ineffective[kind] = 0
                elif now - sent_at >= self.p.potion_response_timeout:
                    del self.pending[kind]
                    self.ineffective[kind] += 1
                    if self.ineffective[kind] >= self.p.max_ineffective_potions:
                        self.pause(now, f"Potion {kind.upper()} tidak memulihkan indikator; periksa stok/input.")
                        return None
            if (kind not in self.pending and value < getattr(self.p, f"{kind}_threshold")
                    and now - self.last_use[kind] >= self.p.potion_cooldown):
                return Action(kind)
        return None

    def tick(self, obs: Observation, now: float, *, focused: bool = True) -> Action | None:
        if self.state in {State.IDLE, State.PAUSED, State.STOPPED}:
            return None
        self.last_observation = obs
        if self.started is not None and now - self.started >= self.p.session_minutes * 60:
            self.stop(now, "Batas durasi sesi tercapai.")
            return None
        if self.state == State.ARMED and now < self.arm_until:
            return None
        if not focused:
            self.pause(now, "Window game tidak aktif. Kembali ke game, lalu F8.")
            return None
        if (not obs.valid or obs.size != (self.p.width, self.p.height)
                or not 0 <= now - obs.captured_at <= self.p.max_frame_age):
            self.pause(now, "Frame tidak valid, terlambat, atau ukuran window berubah.")
            return None
        if self.last_processed is not None and obs.captured_at <= self.last_processed:
            return None  # a repeated result is not independent temporal confirmation
        self.last_processed = obs.captured_at
        resource = self._resources(obs, now)
        if self.state == State.PAUSED:
            return None
        if resource:
            return resource
        if self.state == State.ARMED:
            if obs.combat or obs.defeat:
                self.pause(now, "Bersihkan target/indikator lama sebelum memulai kembali.")
                return None
            self.change(State.SEARCH, now, "Mencari kandidat dari profil aktif.")
        if self.state == State.SEARCH:
            if obs.combat:
                self.pause(now, "Pertarungan di luar kendali bot terdeteksi.")
                return None
            if now - self.entered > self.p.search_timeout:
                self.pause(now, "Tidak ada target yang memenuhi syarat.")
                return None
            if obs.hp is not None and obs.hp < self.p.hp_threshold:
                return None
            self.blacklist = [(box, until) for box, until in self.blacklist if until > now]
            candidate = next((d for d in obs.detections
                              if not any(d.box.intersects(b) for b, _ in self.blacklist)), None)
            if candidate:
                self.target = candidate.box
                self.combat_hits = 0
                self.defeat_cleared = not obs.defeat
                self.change(State.ENGAGE, now, "Input serangan diminta; menunggu bukti pertarungan.")
                return Action("attack", candidate.point)
        elif self.state == State.ENGAGE:
            self.combat_hits = self.combat_hits + 1 if obs.combat else 0
            if self.combat_hits >= 2:
                self.progress_at = now
                self.last_target_hp = obs.target_hp
                self.defeat_cleared = not obs.defeat
                self.defeat_hits = 0
                self.no_combat_since = None
                self.change(State.COMBAT, now, "Pertarungan terkonfirmasi; target dipertahankan.")
            elif now - self.entered > self.p.engage_timeout:
                self.consecutive_failures += 1
                self.unknown += 1
                if self.target:
                    self.blacklist.append((self.target, now + 8))
                self.target = None
                self.change(State.SEARCH, now, "Serangan belum terkonfirmasi.")
                if self.consecutive_failures >= self.p.max_attempts:
                    self.pause(now, "Batas kegagalan memilih/menyerang target tercapai.")
                else:
                    self.change(State.SEARCH, now, "Serangan belum terkonfirmasi; kandidat diabaikan sementara.")
        elif self.state == State.COMBAT:
            if not obs.defeat:
                self.defeat_cleared = True
                self.defeat_hits = 0
            elif self.defeat_cleared:
                self.defeat_hits += 1
            if self.defeat_hits >= 2:
                self.confirmed += 1
                self.consecutive_failures = 0
                self.target = None
                self.loot_sent = 0
                self.change(State.LOOT, now, "Sinyal selesai terkonfirmasi; bukan sekadar target hilang.")
                return None
            if obs.target_hp is not None:
                if self.last_target_hp is None or obs.target_hp < self.last_target_hp - 0.01:
                    self.progress_at = now
                    self.last_target_hp = obs.target_hp
            if "target_hp" in self.p.regions and now - self.progress_at > self.p.progress_timeout:
                self.pause(now, "Tidak ada kemajuan HP target yang terukur.")
            elif now - self.entered > self.p.combat_timeout:
                self.pause(now, "Batas waktu pertarungan; hasil belum diketahui.")
            elif not obs.combat:
                if self.no_combat_since is None:
                    self.no_combat_since = now
                elif now - self.no_combat_since > 2:
                    self.pause(now, "Indikator target hilang tanpa bukti kalah.")
            else:
                self.no_combat_since = None
        elif self.state == State.LOOT:
            if self.p.loot_enabled and self.loot_sent < self.p.loot_attempts:
                if now - self.last_loot >= 0.8:
                    return Action("pickup")
            elif not obs.defeat and not obs.combat:
                self.change(State.SEARCH, now, "Mencari target berikutnya.")
            if now - self.entered > 6:
                self.pause(now, "Indikator pertarungan belum bersih setelah loot.")
        return None

    def summary(self, now: float) -> dict:
        return {
            "state": str(self.state), "reason": self.reason,
            "seconds": max(0, int(now - self.started)) if self.started is not None else 0,
            "attempts": self.attempts, "confirmed": self.confirmed,
            "unknown": self.unknown, **self.sent,
        }
