"""Conservative per-handedness EMA; discard history rather than guess identities."""

from copy import copy
from dataclasses import dataclass
import math

import numpy as np

from .tracking_utils import MAX_HANDS, handedness_label


DEFAULT_ALPHA = 0.75  # Weight of the current measured point, not of history.
MIN_IDENTITY_SCORE = 0.8
RAPID_MOTION_DISTANCE = 0.06  # Euclidean distance in normalized image x/y.
NEAR_WRIST_DISTANCE = 0.10
MAX_HISTORY_GAP_MS = 250


def valid_alpha(value):
    value = float(value)
    if not math.isfinite(value) or not 0 < value <= 1:
        raise ValueError("smoothing alpha must be finite and in (0, 1]; higher is more responsive")
    return value


@dataclass(frozen=True)
class DisplayLandmark:
    x: float
    y: float
    z: float


@dataclass
class HandHistory:
    raw: np.ndarray
    filtered: np.ndarray


def hands_are_close(first, second):
    """A bypass gate only, never a position-based assignment of identity."""
    if np.linalg.norm(first[0, :2] - second[0, :2]) < NEAR_WRIST_DISTANCE:
        return True
    low = np.maximum(first[:, :2].min(axis=0), second[:, :2].min(axis=0))
    high = np.minimum(first[:, :2].max(axis=0), second[:, :2].max(axis=0))
    return bool(np.all(high > low))


class LandmarkSmoother:
    """Smooth only unique, confident Left/Right results in consecutive frames.

    Raw results are never mutated. Only normalized display landmarks change;
    handedness and world landmarks remain raw. No predicted positions, missing-frame hold,
    sorting by detection order, or speculative persistent identity matching.
    """

    def __init__(self, enabled=True, alpha=DEFAULT_ALPHA):
        self.enabled = enabled
        self.alpha = valid_alpha(alpha)
        self.reset()

    def reset(self):
        self._history = {}
        self._last_timestamp = None
        self._frame_shape = None

    def apply(self, result, timestamp_ms, frame_shape=None):
        hands = getattr(result, "hand_landmarks", None) or []
        if not self.enabled or self.alpha == 1 or not hands:
            self.reset()
            return result
        if (self._last_timestamp is not None
                and (timestamp_ms <= self._last_timestamp
                     or timestamp_ms - self._last_timestamp > MAX_HISTORY_GAP_MS)):
            self.reset()
        if frame_shape != self._frame_shape:
            self.reset()

        predictions = getattr(result, "handedness", None) or []
        records = []
        for index, landmarks in enumerate(hands[:MAX_HANDS]):
            categories = predictions[index] if index < len(predictions) else []
            label = handedness_label(categories or [])
            scores = [category.score for category in (categories or [])
                      if getattr(category, "score", None) is not None
                      and math.isfinite(category.score)]
            if label == "Unknown" or max(scores, default=0) < MIN_IDENTITY_SCORE:
                self.reset()
                return result
            try:
                coordinates = np.asarray([(point.x, point.y, getattr(point, "z", 0.0))
                                          for point in (landmarks or [])], dtype=np.float64)
            except (TypeError, ValueError, AttributeError):
                self.reset()
                return result
            if coordinates.shape != (21, 3) or not np.isfinite(coordinates).all():
                self.reset()
                return result
            records.append((label, coordinates))

        labels = {label for label, _ in records}
        if (len(labels) != len(records)
                or (len(records) == 2 and hands_are_close(records[0][1], records[1][1]))):
            self.reset()
            return result

        # Remove absent hands immediately. A returning hand starts from its raw measurement.
        self._history = {label: state for label, state in self._history.items() if label in labels}
        self._last_timestamp = timestamp_ms
        self._frame_shape = frame_shape
        displayed = list(hands)
        changed = False
        for index, (label, raw) in enumerate(records):
            previous = self._history.get(label)
            filtered = raw
            if previous is not None:
                movement = np.linalg.norm(raw[:, :2] - previous.raw[:, :2], axis=1).max()
                if movement <= RAPID_MOTION_DISTANCE and not np.array_equal(raw, previous.raw):
                    filtered = self.alpha * raw + (1.0 - self.alpha) * previous.filtered
                    displayed[index] = [DisplayLandmark(float(x), float(y), float(z))
                                        for x, y, z in filtered]
                    changed = True
            # New, rapidly moved or exactly unchanged measurements bypass the EMA.
            self._history[label] = HandHistory(raw=raw, filtered=filtered)

        if not changed:
            return result
        displayed_result = copy(result)
        displayed_result.hand_landmarks = displayed
        return displayed_result
