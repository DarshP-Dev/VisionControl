"""Localized interpretation of existing recognition results; no recognition rules."""

from dataclasses import dataclass
import math

from gestures.models import LandmarkIndex
from gestures.motion import PALM_ANCHORS, palm_sample
from gestures.static_gestures import Gesture


@dataclass(frozen=True, slots=True)
class GestureProfile:
    name: str
    cursor_gesture: Gesture
    swipe_pose: str
    palm_anchor: bool = False

    def anchor(self, features, stamp):
        if not self.palm_anchor:
            point = features.observation[LandmarkIndex.INDEX_FINGER_TIP]
            result = (point.x, point.y)
        else:
            # Validate each source, not just the average of possibly off-frame points.
            if any(not math.isfinite(value) or not 0 <= value <= 1
                   for index in PALM_ANCHORS for value in
                   (features.observation[index].x, features.observation[index].y)):
                raise ValueError("Invalid palm anchor landmarks")
            sample = palm_sample(features, stamp)
            if sample is None:
                raise ValueError("Invalid palm geometry")
            result = (sample.x, sample.y * features.image_size.width / features.image_size.height)
        if not all(math.isfinite(v) and 0 <= v <= 1 for v in result):
            raise ValueError("Invalid cursor anchor")
        return result


PROFILES = {
    "legacy": GestureProfile("legacy", Gesture.POINTING, "open-palm"),
    "palm-cursor": GestureProfile("palm-cursor", Gesture.OPEN_PALM, "pointing", True),
}
