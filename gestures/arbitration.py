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
