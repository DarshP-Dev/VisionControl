"""Short-lived trajectory evidence, not another event or action state machine."""

from collections import deque
from dataclasses import dataclass, replace
import math

from .events import SWIPE_LEFT, SWIPE_RIGHT, GestureState as S, SwipeId
from .features import HandFeatures
from .models import finite_number
from .motion import MotionMetrics, MotionSample, palm_sample, trajectory_metrics
from .pinch import MAX_HISTORY_GAP_MS


MAX_SAMPLES = 64


@dataclass(frozen=True, slots=True)
class SwipeSettings:
    min_distance: float = 1.5
    min_velocity: float = 3.
    dominance: float = 3.
    consistency: float = .85
    min_ms: int = 120
    max_ms: int = 600
    cooldown_ms: int = 800
    reset_ms: int = 250
    feedback_ms: int = 350
    max_scale_change: float = .25
    pose: str = "open-palm"

    def __post_init__(self):
        for name, low, high in (("min_distance", .25, 10), ("min_velocity", .1, 50),
                                ("dominance", 1, 10), ("consistency", .5, 1), ("max_scale_change", .05, .5)):
            value = finite_number(getattr(self, name), name)
            if not low <= value <= high:
                raise ValueError(f"{name} must be in [{low}, {high}]")
        for name, low, high in (("min_ms", 30, 1000), ("max_ms", 60, 2000),
                                ("cooldown_ms", 0, 5000), ("reset_ms", 0, 1500), ("feedback_ms", 0, 1000)):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
                raise ValueError(f"{name} must be an integer in [{low}, {high}] ms")
        if self.min_ms >= self.max_ms:
            raise ValueError("Swipe minimum duration must be less than maximum duration")
        if self.pose not in ("open-palm", "open-palm-or-fist"):
            raise ValueError("Swipe pose must be open-palm or open-palm-or-fist")


@dataclass(frozen=True, slots=True)
class SwipeObservation:
    timestamp_ms: int
    state: S = S.IDLE
    gesture: SwipeId | None = None
    confirmed: bool = False  # One observation of raw confirmation, not an emitted event.
    admitted: bool = False  # Resolved by the existing event manager.
    metrics: MotionMetrics | None = None
    reason: str = ""
    cooldown_ms: int = 0
    trajectory: tuple[tuple[float, float], ...] = ()  # Common-axis positions, only in debug mode.


class SwipeHistory:
    """Evidence/reset latch only. The Phase 3.4 manager owns cooldown and events.

    A neutral pose must follow every confirmation/failed motion; then eligible
    rest rearms. Continuing/returning with the same eligible pose cannot repeat.
    """

    def __init__(self, settings: SwipeSettings, diagnostics=False):
        self.settings, self.diagnostics = settings, diagnostics
        self.samples: deque[MotionSample] = deque(maxlen=MAX_SAMPLES)
        self.rest: deque[MotionSample] = deque(maxlen=MAX_SAMPLES)
        self.armed = self.candidate = self.needs_neutral = False
        self.last_timestamp = None
        self.feedback: SwipeObservation | None = None
        self.feedback_until = 0

    def consume(self):
        self.samples.clear()
        self.rest.clear()
        self.armed = self.candidate = False
        self.needs_neutral = True

    def outcome(self, result: SwipeObservation, admitted: bool, reason: str):
        self.feedback = replace(result, admitted=admitted, confirmed=False, reason=reason, trajectory=())
        self.feedback_until = result.timestamp_ms+self.settings.feedback_ms

    def _snapshot(self, timestamp, state=S.IDLE, reason="", metrics=None, blocked_until=0):
        if self.feedback is not None and timestamp < self.feedback_until:
            return replace(self.feedback, timestamp_ms=timestamp, state=state,
                           cooldown_ms=max(0, blocked_until-timestamp))
        self.feedback = None
        trail = tuple((p.x, p.y) for p in self.samples) if self.diagnostics else ()
        return SwipeObservation(timestamp, state, metrics=metrics, reason=reason,
                                cooldown_ms=max(0, blocked_until-timestamp), trajectory=trail)

    def observe(self, features: HandFeatures, timestamp_ms: int, eligible: bool, blocked_until=0) -> SwipeObservation:
        sample = palm_sample(features, timestamp_ms)
        if (sample is None or (self.last_timestamp is not None and
                              (timestamp_ms <= self.last_timestamp
                               or timestamp_ms-self.last_timestamp > MAX_HISTORY_GAP_MS))):
            self.consume()
            self.feedback = None
            if sample is not None:
                self.last_timestamp = max(self.last_timestamp or 0, timestamp_ms)
            return SwipeObservation(max(0, self.last_timestamp or 0), reason="invalid_geometry_or_time")
        self.last_timestamp = timestamp_ms
        if not eligible:
            self.consume()
            self.needs_neutral = False
            self.feedback = None
            return self._snapshot(timestamp_ms, S.COOLDOWN if blocked_until > timestamp_ms else S.IDLE,
                                  "ineligible_pose_or_pinch", blocked_until=blocked_until)
        if self.needs_neutral or blocked_until > timestamp_ms:
            self.samples.clear()
            self.rest.clear()
            return self._snapshot(timestamp_ms, S.COOLDOWN if blocked_until > timestamp_ms else S.IDLE,
                                  "change_pose_to_reset" if self.needs_neutral else "cooldown",
                                  blocked_until=blocked_until)
        if not self.armed:
            self.rest.append(sample)
            # Keep a bracket around reset_ms; storage is also capped at 64 samples.
            while len(self.rest) > 2 and self.rest[1].timestamp_ms <= timestamp_ms-self.settings.reset_ms:
                self.rest.popleft()
            if self.settings.reset_ms == 0:
                ready = True
            elif len(self.rest) > 1:
                rest = trajectory_metrics(tuple(self.rest))
                ready = (rest.duration_ms >= self.settings.reset_ms and rest.travel*1000/rest.duration_ms <= .5
                         and rest.travel <= .15 and rest.scale_change <= self.settings.max_scale_change)
            else:
                ready = False
            if ready:
                self.armed = True
                self.samples.append(sample)
                self.rest.clear()
            return self._snapshot(timestamp_ms, reason="ready" if ready else "hold_eligible_pose_still")
        if len(self.samples) == MAX_SAMPLES:
            self.consume()
            return self._snapshot(timestamp_ms, reason="sample_capacity_change_pose")
        self.samples.append(sample)
        if not self.candidate:
            while len(self.samples) > 2 and math.hypot(self.samples[1].x-self.samples[0].x,
                                                       self.samples[1].y-self.samples[0].y)/self.samples[0].scale <= .01:
                self.samples.popleft()
        metrics = trajectory_metrics(tuple(self.samples))
        if metrics.scale_change > self.settings.max_scale_change:
            self.consume()
            return self._snapshot(timestamp_ms, reason="scale_changed_change_pose", metrics=metrics)
        if not self.candidate:
            self.candidate = abs(metrics.dx) >= .15 or abs(metrics.dy) >= .15 or metrics.travel >= .25
            if not self.candidate:
                while len(self.samples) > 2 and self.samples[1].timestamp_ms <= timestamp_ms-100:
                    self.samples.popleft()
                return self._snapshot(timestamp_ms, reason="ready", metrics=metrics)
        if metrics.duration_ms > self.settings.max_ms:
            self.consume()
            return self._snapshot(timestamp_ms, reason="duration_exceeded_change_pose", metrics=metrics)
        conditions = ((metrics.duration_ms >= self.settings.min_ms, "too_short"),
                      (abs(metrics.dx) >= self.settings.min_distance, "insufficient_distance"),
                      (abs(metrics.velocity_x) >= self.settings.min_velocity, "too_slow"),
                      (abs(metrics.recent_velocity_x) >= self.settings.min_velocity
                       and metrics.recent_velocity_x*metrics.dx > 0, "not_moving_in_direction"),
                      (metrics.consistency >= self.settings.consistency, "direction_inconsistent"),
                      (metrics.dominance >= self.settings.dominance, "not_horizontal"))
        reason = next((reason for passed, reason in conditions if not passed), "")
        if reason:
            return self._snapshot(timestamp_ms, S.CANDIDATE, reason, metrics)
        direction = SWIPE_RIGHT if metrics.dx > 0 else SWIPE_LEFT
        result = SwipeObservation(timestamp_ms, S.ACTIVE, direction, True, metrics=metrics, reason="confirmed")
        self.consume()
        return result
