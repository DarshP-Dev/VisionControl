"""Immutable in-process intent events; no bus, SDK, probability or OS actions."""

from dataclasses import dataclass
from enum import StrEnum
from typing import Literal, TypeAlias

from .models import HandSide, finite_number
from .static_gestures import Gesture


GestureId: TypeAlias = Gesture | Literal["PINCH"]
PINCH: Literal["PINCH"] = "PINCH"


class GestureState(StrEnum):
    IDLE = "IDLE"
    CANDIDATE = "CANDIDATE"
    ACTIVE = "ACTIVE"
    COOLDOWN = "COOLDOWN"


class EventType(StrEnum):
    GESTURE_STARTED = "GESTURE_STARTED"
    GESTURE_UPDATED = "GESTURE_UPDATED"
    GESTURE_ENDED = "GESTURE_ENDED"
    GESTURE_CANCELED = "GESTURE_CANCELED"


@dataclass(frozen=True, slots=True)
class EventMetadata:
    reason: str = ""
    normalized_pinch_distance: float | None = None
    association_current: bool = True  # False: cancellation references a former association.

    def __post_init__(self):
        if self.normalized_pinch_distance is not None:
            value = finite_number(self.normalized_pinch_distance, "Event pinch distance")
            if value < 0:
                raise ValueError("Event pinch distance must be nonnegative")


@dataclass(frozen=True, slots=True)
class GestureEvent:
    gesture: GestureId
    event_type: EventType
    timestamp_ms: int
    side: HandSide
    state: GestureState
    metadata: EventMetadata = EventMetadata()

    def __post_init__(self):
        if (self.gesture not in (Gesture.OPEN_PALM, Gesture.FIST, Gesture.POINTING, PINCH)
                or not isinstance(self.event_type, EventType) or not isinstance(self.state, GestureState)
                or self.side not in (HandSide.LEFT, HandSide.RIGHT)):
            raise ValueError("Events require a supported gesture, event/state type and reliable side")
        if isinstance(self.timestamp_ms, bool) or not isinstance(self.timestamp_ms, int) or self.timestamp_ms < 0:
            raise ValueError("Event timestamp must be a nonnegative integer in milliseconds")


@dataclass(frozen=True, slots=True)
class HandState:
    """Current resolved intent only; raw recognition stays in its original records."""
    side: HandSide
    state: GestureState = GestureState.IDLE
    confirmed: GestureId | None = None
    candidate: GestureId | None = None
    last_event: GestureEvent | None = None
    reason: str = ""


@dataclass(frozen=True, slots=True)
class StateFrame:
    timestamp_ms: int
    hands: tuple[HandState, ...]  # Current detection slots, not persistent IDs.
    events: tuple[GestureEvent, ...] = ()
