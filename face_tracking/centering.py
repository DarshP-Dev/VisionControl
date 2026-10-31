"""Read-only centering decisions from the locked track; no camera or input APIs."""

from collections import Counter
from dataclasses import asdict, dataclass
from enum import StrEnum
import math
from numbers import Integral
import time

from .centering_geometry import calculate_offsets, finite, point
from .face_geometry import dimensions
from .face_models import FaceDetection
from .track_models import TrackedFaces, TrackState


_BOUNDARY_EPSILON = 8*math.ulp(1.)  # Pixel/normalized round-trip noise, not a tunable dead zone.


class CenteringStatus(StrEnum):
    NO_TARGET = "NO_TARGET"
    WAITING_FOR_TARGET = "WAITING_FOR_TARGET"
    CENTERED = "CENTERED"
    CORRECTION_NEEDED = "CORRECTION_NEEDED"
    TARGET_LOST = "TARGET_LOST"
    TARGET_UNCERTAIN = "TARGET_UNCERTAIN"
    STALE_OBSERVATION = "STALE_OBSERVATION"
    INVALID_OBSERVATION = "INVALID_OBSERVATION"


class CorrectionDirection(StrEnum):
    NONE = "NONE"
    PAN_LEFT = "PAN_LEFT"
    PAN_RIGHT = "PAN_RIGHT"
    TILT_UP = "TILT_UP"
    TILT_DOWN = "TILT_DOWN"


@dataclass(frozen=True, slots=True)
class DeadZone:
    activation: float = .12
    deactivation: float = .07

    def __post_init__(self):
        if not all(finite(v) for v in (self.activation, self.deactivation)) or not 0 <= self.deactivation < self.activation <= 1:
            raise ValueError("Dead zone requires 0 <= deactivation < activation <= 1")


@dataclass(frozen=True, slots=True)
class CenteringConfig:
    horizontal: DeadZone = DeadZone()
    vertical: DeadZone = DeadZone()
    target: tuple[float, float] = (.5, .5)
    max_observation_age: float = .25

    def __post_init__(self):
        if not isinstance(self.horizontal, DeadZone) or not isinstance(self.vertical, DeadZone):
            raise ValueError("Each axis requires a DeadZone")
        if not isinstance(self.target, tuple):
            raise ValueError("Target must be an immutable normalized X/Y tuple")
        point(self.target, (1, 1))
        if not finite(self.max_observation_age) or not 0 < self.max_observation_age <= .25:
            raise ValueError("Freshness limit must be positive and at most 250 ms")


@dataclass(frozen=True, slots=True)
class AxisCorrection:
    error_px: float | None = None
    error: float | None = None
    raw_error: float | None = None
    active: bool = False
    direction: CorrectionDirection = CorrectionDirection.NONE
    demand: float = 0.


@dataclass(frozen=True, slots=True)
class CenteringResult:
    primary_id: int | None
    status: CenteringStatus
    source_timestamp_ms: int | None
    observation_timestamp: float | None
    observation_age: float | None
    evaluated_at: float | None
    max_observation_age: float
    frame_size: tuple[int, int] | None
    target_center: tuple[float, float] | None
    raw_center: tuple[float, float] | None = None
    smoothed_center: tuple[float, float] | None = None
    horizontal: AxisCorrection = AxisCorrection()
    vertical: AxisCorrection = AxisCorrection()

    @property
    def actionable(self):
        """Valid recommendation at evaluated_at, including an exactly zero hold."""
        return self.status in (CenteringStatus.CENTERED, CenteringStatus.CORRECTION_NEEDED)

    @property
    def is_centered(self):
        return self.status == CenteringStatus.CENTERED

    def fresh_at(self, now):
        """Consumers must recheck time before using a stored immutable result."""
        return (self.actionable and finite(now) and self.evaluated_at is not None
                and now >= self.evaluated_at and self.observation_timestamp is not None
                and 0 <= now-self.observation_timestamp <= self.max_observation_age)


def _axis(error_px, error, raw_error, old_sign, zone, negative, positive):
    sign = 1 if error > 0 else -1 if error < 0 else 0
    # Reversals require the opposite activation threshold, even if the old
    # direction was active. Insignificant reversal first becomes inactive.
    threshold = zone.deactivation if sign == old_sign and old_sign else zone.activation
    active = abs(error)-threshold > _BOUNDARY_EPSILON
    demand = min(1., max(0., (abs(error)-zone.deactivation)/(1-zone.deactivation))) * sign if active else 0.
    return AxisCorrection(error_px, error, raw_error, active,
                          positive if active and sign > 0 else negative if active else CorrectionDirection.NONE,
                          demand), sign if active else 0


class FaceCentering:
    """One small state object per session; does not retain frames or track objects."""

    def __init__(self, config=None):
        self.config = config or CenteringConfig()
        self._primary_id = self._size = None
        self._x = self._y = 0
        self._last_now = self._last_source = self._last_detection = None
        self._previous_status = None
        self._previous_directions = (CorrectionDirection.NONE, CorrectionDirection.NONE)
        self.states = Counter()
        self.transitions = Counter()
        self.counts = Counter()

    def reset(self):
        self._primary_id = self._size = self._last_detection = None
        self._x = self._y = 0
        self.counts["resets"] += 1
        # Retain monotonic/replay fences within this session, like FaceTracker.

    def metadata(self):
        return {"enabled": True, "config": asdict(self.config), "states": dict(self.states),
                "transitions": dict(self.transitions), "counters": dict(self.counts),
                "counter_scope": "whole session including warmup; one calculation per consumed face frame",
                "units": "original image pixels; normalized half-frame errors; unitless demand, not degrees/speed",
                "output": "read-only recommendations; no camera, motor or desktop input"}

    @staticmethod
    def _center(face, size):
        if not isinstance(face, FaceDetection):
            raise ValueError("Missing current FaceDetection")
        center = point((face.center_x, face.center_y), size)
        normalized = point((face.normalized_center_x, face.normalized_center_y), (1, 1))
        if not all(math.isclose(p, n*dimension, rel_tol=1e-9, abs_tol=1e-6)
                   for p, n, dimension in zip(center, normalized, size)):
            raise ValueError("Face center is not expressed in original-frame pixels")
        return center

    def update(self, observation, *, now, profile=None):
        profiled = profile is not None and profile.enabled
        started = time.perf_counter() if profiled else None
        size = target = stamp = primary_id = detected_at = age = None
        valid_now = finite(now) and now >= 0 and (self._last_now is None or now >= self._last_now)
        if valid_now:
            self._last_now = now

        def emit(status, raw=None, smooth=None, axes=None):
            if axes is None:
                self._x = self._y = 0
                axes = AxisCorrection(), AxisCorrection()
            result = CenteringResult(primary_id, status, stamp, detected_at, age, now if valid_now else None,
                                     self.config.max_observation_age, size, target, raw, smooth, *axes)
            self.states[str(status)] += 1
            if self._previous_status is not None and status != self._previous_status:
                self.transitions[f"{self._previous_status}->{status}"] += 1
            directions = result.horizontal.direction, result.vertical.direction
            self.counts["direction_reversals"] += sum(
                a != b and a != CorrectionDirection.NONE and b != CorrectionDirection.NONE
                for a, b in zip(self._previous_directions, directions))
            self._previous_status, self._previous_directions = status, directions
            if profiled:
                profile.add("face_centering", time.perf_counter()-started)
                if age is not None:
                    profile.add("centering_observation_age", age)
            return result

        if observation is None:
            self._primary_id = self._last_detection = None
            return emit(CenteringStatus.NO_TARGET if valid_now else CenteringStatus.INVALID_OBSERVATION)
        if not isinstance(observation, TrackedFaces):
            return emit(CenteringStatus.INVALID_OBSERVATION)
        try:
            size = dimensions(observation.frame_size)
            target = self.config.target[0]*size[0], self.config.target[1]*size[1]
        except (TypeError, ValueError, OverflowError):
            return emit(CenteringStatus.INVALID_OBSERVATION)
        primary_id = observation.primary_id
        if primary_id is not None and (not isinstance(primary_id, Integral) or isinstance(primary_id, bool) or primary_id < 1):
            primary_id = None
            return emit(CenteringStatus.INVALID_OBSERVATION)
        if primary_id != self._primary_id or size != self._size:
            self._x = self._y = 0
            self._last_detection = None
        self._primary_id, self._size = primary_id, size
        source = observation.timestamp_ms
        if (not valid_now or not isinstance(source, Integral) or isinstance(source, bool)
                or not 0 <= source <= 2**63-1 or self._last_source is not None and source < self._last_source):
            return emit(CenteringStatus.INVALID_OBSERVATION)
        stamp = int(source)
        self._last_source = stamp
        primary = observation.primary
        if primary is not None and finite(primary.last_detected) and 0 <= primary.last_detected <= now:
            detected_at = primary.last_detected
            age = now-detected_at
        if observation.status == "stale_frame":
            return emit(CenteringStatus.STALE_OBSERVATION)
        if observation.status not in ("valid", "uncertain"):
            return emit(CenteringStatus.INVALID_OBSERVATION)
        if primary_id is None:
            candidates = observation.unassigned or any(t.state != TrackState.EXPIRED for t in observation.tracks)
            return emit(CenteringStatus.WAITING_FOR_TARGET if candidates else CenteringStatus.NO_TARGET)
        if primary is None:
            return emit(CenteringStatus.TARGET_LOST)
        if primary.uncertain:
            return emit(CenteringStatus.TARGET_UNCERTAIN)
        if primary.state == TrackState.TENTATIVE:
            return emit(CenteringStatus.WAITING_FOR_TARGET)
        if primary.state != TrackState.TRACKED or not primary.detected:
            return emit(CenteringStatus.TARGET_LOST)
        if not primary.primary or detected_at is None or self._last_detection is not None and detected_at < self._last_detection:
            return emit(CenteringStatus.INVALID_OBSERVATION)
        if age > self.config.max_observation_age:
            return emit(CenteringStatus.STALE_OBSERVATION)
        try:
            raw = self._center(primary.raw, size)
            smooth = self._center(primary.smoothed, size)
            raw_offsets = calculate_offsets(raw, size, target=self.config.target)
            offsets = calculate_offsets(smooth, size, target=self.config.target)
        except (AttributeError, TypeError, ValueError, OverflowError):
            return emit(CenteringStatus.INVALID_OBSERVATION)
        if (self._last_detection is not None and detected_at-self._last_detection > self.config.max_observation_age
                or primary.consecutive_matches == 1 and detected_at != self._last_detection):
            self._x = self._y = 0
        self._last_detection = detected_at
        horizontal, self._x = _axis(offsets.pixel_error[0], offsets.normalized_error[0], raw_offsets.normalized_error[0],
                                   self._x, self.config.horizontal, CorrectionDirection.PAN_LEFT, CorrectionDirection.PAN_RIGHT)
        vertical, self._y = _axis(offsets.pixel_error[1], offsets.normalized_error[1], raw_offsets.normalized_error[1],
                                 self._y, self.config.vertical, CorrectionDirection.TILT_UP, CorrectionDirection.TILT_DOWN)
        status = CenteringStatus.CORRECTION_NEEDED if horizontal.active or vertical.active else CenteringStatus.CENTERED
        return emit(status, raw, smooth, (horizontal, vertical))
