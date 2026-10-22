"""Projected fingertip proximity and a narrow, conservative pinch lifecycle.

No SDK, OpenCV, action dispatch or persistent identity assignment. Side labels
only associate consecutive, unique, confident observations; they are not IDs.
"""

from dataclasses import dataclass
from enum import StrEnum
import math

from .features import HandFeatures
from .association import MIN_SIDE_SCORE, WRIST_CONTINUITY_DISTANCE, reliable_side as _side, hands_overlap
from .models import MAX_HANDS, HandednessPrediction, HandSide, ImageSize, LandmarkIndex, finite_number
from .association import valid_track_keys


MAX_HISTORY_GAP_MS = 250


class PinchStatus(StrEnum):
    OPEN = "OPEN"
    STARTED = "STARTED"
    HELD = "HELD"
    RELEASED = "RELEASED"
    UNAVAILABLE = "UNAVAILABLE"


@dataclass(frozen=True, slots=True)
class PinchThresholds:
    activation: float = .25
    release: float = .40

    def __post_init__(self):
        activation = finite_number(self.activation, "Pinch activation threshold")
        release = finite_number(self.release, "Pinch release threshold")
        if not 0 < activation < release <= 2:
            raise ValueError("Pinch thresholds must satisfy 0 < activation < release <= 2 palm units")


@dataclass(frozen=True, slots=True)
class PinchMeasurement:
    normalized_distance: float | None
    valid: bool
    reason: str = ""


@dataclass(frozen=True, slots=True)
class PinchResult:
    status: PinchStatus
    measurement: PinchMeasurement
    timestamp_ms: int
    handedness: tuple[HandednessPrediction, ...] = ()
    reason: str = ""
    track_id: int | None = None

    def __post_init__(self):
        if self.track_id is not None and (isinstance(self.track_id, bool) or not isinstance(self.track_id, int)
                                          or self.track_id <= 0):
            raise ValueError("Track ID must be a positive integer or None")


def measure_pinch(features: HandFeatures | None) -> PinchMeasurement:
    """Reuse Phase 3.1 distance_2d / palm_scale, computed with ImageSize.

    Palm scale is mean(wrist-middle MCP length, index MCP-pinky MCP width).
    Pixel axes have already been corrected into image-width units. This is
    projected proximity, never evidence of physical contact or metric depth.
    """
    try:
        if not isinstance(features, HandFeatures) or not isinstance(features.image_size, ImageSize):
            raise ValueError("missing_aspect_correct_features")
        scale = finite_number(features.palm_scale, "Palm scale")
        distance = finite_number(features.thumb_index_distance, "Tip distance")
        ratio = finite_number(features.thumb_index_ratio, "Normalized tip distance")
        if scale <= 1e-9 or distance < 0 or ratio < 0:
            raise ValueError("degenerate_geometry")
        if not math.isclose(ratio, distance / scale, rel_tol=1e-9, abs_tol=1e-12):
            raise ValueError("inconsistent_geometry")
        # All geometry used by the bridge must remain finite, including the palm.
        for point in features.observation.landmarks:
            for value in (point.x, point.y, point.z):
                finite_number(value, "Landmark coordinate")
        return PinchMeasurement(ratio, True)
    except (ValueError, AttributeError, TypeError):
        return PinchMeasurement(None, False, "invalid_or_degenerate_geometry")


@dataclass(slots=True)
class _History:
    active: bool
    wrist: tuple[float, float]


class PinchTracker:
    """Rearm only after observed separation; closed reacquisition emits no STARTED.

    Strict below/above thresholds; equality retains the current state. Histories
    expire immediately for absent/invalid hands and on gaps over 250 ms. Overlap,
    close wrists, duplicate/uncertain side predictions invalidate both histories.
    A large wrist jump also invalidates that side rather than matching by position.
    """

    def __init__(self, thresholds: PinchThresholds = PinchThresholds()):
        self.thresholds = thresholds
        self.reset()

    def reset(self):
        self._history: dict[HandSide | int, _History] = {}
        self._last_timestamp: int | None = None
        self._image_sizes = None

    def update(self, features: tuple[HandFeatures | None, ...], timestamp_ms: int,
               *, identities: tuple[int | None, ...] | None = None) -> tuple[PinchResult, ...]:
        """Default side safeguards remain; explicit IDs require an upstream associator.

        None keys are uncertain and cannot maintain history. The track namespace
        is for observation, and desktop controllers reject its results/events.
        """
        if (isinstance(timestamp_ms, bool) or not isinstance(timestamp_ms, int) or timestamp_ms < 0):
            self.reset()
            raise ValueError("Pinch timestamp must be a nonnegative integer in milliseconds")
        tracked = identities is not None
        if tracked and not valid_track_keys(identities, len(features)):
            self.reset()
            raise ValueError("Invalid per-track pinch identities")
        if len(features) > (4 if tracked else MAX_HANDS):
            self.reset()
            raise ValueError("Pinch supports at most two hand observations")
        measurements = tuple(measure_pinch(item) for item in features)
        sides = tuple(_side(item) for item in features)
        keys = identities if tracked else sides
        sizes = {item.image_size for item in features if item is not None}
        clock_invalid = self._last_timestamp is not None and timestamp_ms <= self._last_timestamp
        gap = self._last_timestamp is not None and timestamp_ms - self._last_timestamp > MAX_HISTORY_GAP_MS
        if clock_invalid or gap or sizes != self._image_sizes:
            self._history.clear()
        # A backward timestamp cannot lower the continuity watermark.
        self._last_timestamp = max(self._last_timestamp, timestamp_ms) if clock_invalid else timestamp_ms
        self._image_sizes = sizes
        ambiguous = (len(sizes) > 1 or not tracked and
                     (HandSide.UNKNOWN in sides or len(set(sides)) != len(sides)))
        overlap = False
        if not tracked and len(features) == 2 and all(item.valid for item in measurements):
            overlap = hands_overlap(*features)
        # Unknown/malformed identity cannot safely be assigned to either history.
        if ambiguous or overlap or clock_invalid:
            self._history.clear()
            reason = "non_monotonic_time" if clock_invalid else "overlapping_hands" if overlap else "ambiguous_handedness"
            return tuple(PinchResult(PinchStatus.UNAVAILABLE, measurement, timestamp_ms,
                                     item.observation.handedness if item is not None else (), reason)
                         for item, measurement in zip(features, measurements))
        self._history = {key: state for key, state in self._history.items() if key in keys}
        results = []
        for item, measurement, side in zip(features, measurements, keys):
            metadata = item.observation.handedness if item is not None else ()
            status, reason = PinchStatus.UNAVAILABLE, measurement.reason
            if side is None or not measurement.valid:
                self._history.pop(side, None)
                if side is None:
                    reason = "uncertain_track_association"
            else:
                wrist_point = item.observation[LandmarkIndex.WRIST]
                wrist = (wrist_point.x, wrist_point.y * item.image_size.height / item.image_size.width)
                previous = self._history.get(side)
                if previous is not None and math.dist(previous.wrist, wrist) > WRIST_CONTINUITY_DISTANCE:
                    self._history.pop(side, None)
                    previous = None
                distance = measurement.normalized_distance
                if previous is None:
                    if distance > self.thresholds.release:
                        status = PinchStatus.OPEN
                        self._history[side] = _History(False, wrist)
                    else:
                        reason = "open_to_rearm"
                elif previous.active:
                    status = PinchStatus.RELEASED if distance > self.thresholds.release else PinchStatus.HELD
                    self._history[side] = _History(status != PinchStatus.RELEASED, wrist)
                else:
                    status = PinchStatus.STARTED if distance < self.thresholds.activation else PinchStatus.OPEN
                    self._history[side] = _History(status == PinchStatus.STARTED, wrist)
            results.append(PinchResult(status, measurement, timestamp_ms, metadata, reason,
                                       side if tracked else None))
        return tuple(results)
