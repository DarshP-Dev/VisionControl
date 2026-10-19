"""Conservative association gates, shared by pinch and gesture state management.

These assess current predictions, not persistent identities or geometric matches.
"""

import math

from .features import HandFeatures
from .models import HandSide, LandmarkIndex


MIN_SIDE_SCORE = .8
WRIST_CONTINUITY_DISTANCE = .10  # Common-axis image-width units.


def reliable_side(features: HandFeatures | None) -> HandSide:
    try:
        predictions = features.observation.handedness if features is not None else ()
        if len(predictions) != 1:
            return HandSide.UNKNOWN
        prediction = predictions[0]
        return (prediction.side if prediction.score is not None and prediction.score >= MIN_SIDE_SCORE
                else HandSide.UNKNOWN)
    except (AttributeError, TypeError, ValueError):
        return HandSide.UNKNOWN


def hand_bounds(features: HandFeatures) -> tuple[float, float, float, float]:
    points = features.observation.landmarks
    aspect = features.image_size.height / features.image_size.width
    return (min(p.x for p in points), min(p.y * aspect for p in points),
            max(p.x for p in points), max(p.y * aspect for p in points))


def hands_overlap(first: HandFeatures, second: HandFeatures) -> bool:
    a, b = hand_bounds(first), hand_bounds(second)
    wa, wb = first.observation[LandmarkIndex.WRIST], second.observation[LandmarkIndex.WRIST]
    aspect = first.image_size.height / first.image_size.width
    return (math.hypot(wa.x - wb.x, (wa.y - wb.y) * aspect) < WRIST_CONTINUITY_DISTANCE
            or (min(a[2], b[2]) > max(a[0], b[0]) and min(a[3], b[3]) > max(a[1], b[1])))
