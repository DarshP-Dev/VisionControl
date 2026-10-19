"""Small precedence policy; preserve raw static/pinch observations verbatim."""

from .events import PINCH, GestureId
from .pinch import PinchResult, PinchStatus
from .static_gestures import Gesture, GestureResult


def resolved_input(static: GestureResult | None, pinch: PinchResult | None) -> GestureId | None:
    """UNAVAILABLE/orphan HELD suppress static intents; UNKNOWN never qualifies.

    STARTED/HELD select PINCH, with lifecycle admission checked by the manager.
    OPEN/RELEASED permit a unique supported static classification. This function
    selects a candidate input, never emits actions or reclassifies a raw pose.
    """
    if pinch is not None:
        if pinch.status in (PinchStatus.STARTED, PinchStatus.HELD):
            return PINCH
        if pinch.status == PinchStatus.UNAVAILABLE:
            return None
    try:
        if (static is not None and static.gesture in (Gesture.OPEN_PALM, Gesture.FIST, Gesture.POINTING)
                and static.unique_rule_match):
            return static.gesture
    except (AttributeError, TypeError):
        pass  # Malformed rule metadata cannot produce an actionable candidate.
    return None


def swipe_eligible(static: GestureResult | None, pinch: PinchResult | None, pose: str) -> bool:
    """Require a recognized pose and an observed open/released pinch channel."""
    selected = resolved_input(static, pinch)
    return (pinch is not None and pinch.measurement.valid
            and pinch.status in (PinchStatus.OPEN, PinchStatus.RELEASED)
            and selected in ((Gesture.OPEN_PALM,) if pose == "open-palm" else (Gesture.OPEN_PALM, Gesture.FIST)))


def opposing_swipes(observations, recent=()) -> bool:
    """Suppress both when one confirms while the other has opposite motion evidence."""
    directions = {1 if item.metrics.dx > 0 else -1 for item in observations
                  if item is not None and item.metrics is not None
                  and (item.confirmed or item.state.value == "CANDIDATE") and abs(item.metrics.dx) >= .15}
    directions.update(1 if name == "SWIPE_RIGHT" else -1 for name in recent)
    return len(directions) > 1 and any(item is not None and item.confirmed for item in observations)
