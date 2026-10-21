"""Validate an existing Left pinch lifecycle; never arm or dispatch input here."""

import math

from gestures.association import WRIST_CONTINUITY_DISTANCE, hands_overlap, reliable_side
from gestures.events import PINCH, EventType, GestureState
from gestures.models import HandSide, finite_number
from gestures.pinch import MAX_HISTORY_GAP_MS, PinchStatus as P


INVALID_ASSOCIATION_REASONS = (
    "invalid_time", "ambiguous_handedness", "overlapping_hands", "tracking_gap", "image_size_changed",
    "invalid_geometry_or_channel", "wrist_jump", "conflicting_image_sizes", "invalid_channel_alignment",
)
MIN_REARM_CONFIDENCE = .90


class LeftPinchRearm:
    """Two current unique hands, continuous wrists, stable labels, fresh OPEN and held release.

    Constant-size state only. Label/continuity gates refuse uncertainty; they do
    not establish persistent identity. All times are monotonic observation ms.
    """

    def __init__(self, settings):
        self.hold_ms = settings.rearm_hold_ms
        self.stable_ms = settings.rearm_stable_ms
        self.reset()

    def reset(self, reason="LEFT HAND: OPEN TO START"):
        self.phase = "WAITING_FOR_OPEN"
        self.feedback = reason
        self.last_stamp = self.stable_since = self.hold_started = self.last_held = None
        self.positions = self.image_size = None
        self.rearmed_until = None

    def _cancel(self, reason):
        stamp = self.last_stamp
        self.reset(f"REARM CANCELED: {reason}; OPEN TO START")
        self.last_stamp = stamp  # Never lower the monotonic watermark after a bad observation.
        return False

    def _observations(self, frame, features, pinches):
        if not (len(features) == len(frame.hands) == len(pinches) == 2):
            raise ValueError("need distinct Left and Right hands")
        sides = tuple(reliable_side(item) for item in features)
        if set(sides) != {HandSide.LEFT, HandSide.RIGHT}:
            raise ValueError("ambiguous handedness")
        positions = {}
        size = features[0].image_size
        if size is None or features[1].image_size != size or hands_overlap(*features):
            raise ValueError("overlap or image geometry")
        for item, state, pinch, side in zip(features, frame.hands, pinches, sides):
            prediction = item.observation.handedness[0]
            if (prediction.score < MIN_REARM_CONFIDENCE or state.side != side
                    or state.reason in INVALID_ASSOCIATION_REASONS):
                raise ValueError("unstable hand association")
            if (finite_number(item.palm_scale, "Palm scale") <= 1e-9
                    or pinch.timestamp_ms != frame.timestamp_ms or pinch.handedness != item.observation.handedness
                    or pinch.measurement.valid is not True or not isinstance(pinch.status, P) or pinch.status == P.UNAVAILABLE
                    or finite_number(pinch.measurement.normalized_distance, "Pinch distance") < 0):
                raise ValueError("invalid pinch/geometry")
            for index in (0, 4, 5, 8, 9, 17):
                point = item.observation[index]
                if not all(math.isfinite(v) and 0 <= v <= 1 for v in (point.x, point.y)):
                    raise ValueError("invalid landmark position")
            wrist = item.observation[0]
            positions[side] = (wrist.x, wrist.y * size.height / size.width)
        if any(not event.metadata.association_current or
               event.gesture == PINCH and event.event_type == EventType.GESTURE_CANCELED
               for event in frame.events):
            raise ValueError("canceled/stale association")
        left = sides.index(HandSide.LEFT)
        status = pinches[left].status
        if status in (P.STARTED, P.HELD) and (frame.hands[left].confirmed != PINCH
                                             or frame.hands[left].state != GestureState.ACTIVE):
            raise ValueError("pinch not admitted by existing gesture manager")
        events = tuple(event for event in frame.events if event.side == HandSide.LEFT
                       and event.gesture == PINCH and event.timestamp_ms == frame.timestamp_ms)
        started = sum(event.event_type == EventType.GESTURE_STARTED for event in events) == 1
        ended = sum(event.event_type == EventType.GESTURE_ENDED for event in events) == 1
        return positions, size, status, started, ended

    def update(self, frame, features, pinches):
        stamp, previous = frame.timestamp_ms, self.last_stamp
        if isinstance(stamp, bool) or not isinstance(stamp, int) or stamp < 0:
            return self._cancel("invalid timestamp")
        self.last_stamp = max(stamp, previous) if previous is not None else stamp
        if previous is not None and not 0 < stamp - previous <= MAX_HISTORY_GAP_MS:
            return self._cancel("timestamp/gap")
        try:
            positions, size, status, started, ended = self._observations(frame, features, pinches)
            if self.positions is not None:
                # Common image-width axes. A small noise allowance plus a time-based
                # speed bound, capped by the existing pinch wrist-jump limit.
                limit = min(WRIST_CONTINUITY_DISTANCE, .015 + 1.5 * (stamp - previous) / 1000)
                if self.image_size != size or any(math.dist(positions[side], self.positions[side]) > limit
                                                   for side in positions):
                    raise ValueError("hand discontinuity")
        except (ValueError, AttributeError, TypeError, IndexError) as exc:
            return self._cancel(str(exc) if isinstance(exc, ValueError) else "association/geometry")
        self.positions, self.image_size = positions, size
        if self.stable_since is None:
            self.stable_since = stamp
        if stamp - self.stable_since < self.stable_ms:
            self.feedback = "REARM AVAILABLE: STABILIZE BOTH HANDS"
            return False
        if self.phase == "WAITING_FOR_OPEN":
            if status == P.OPEN:
                self.phase = "READY_FOR_PINCH"
                self.feedback = "LEFT PINCH: HOLD TO REARM"
            else:
                self.feedback = "LEFT HAND: OPEN TO START"
        elif self.phase == "READY_FOR_PINCH":
            if status == P.STARTED and started:
                self.phase, self.hold_started = "HOLDING", stamp
                self.feedback = f"REARM HOLD: 0.0 / {self.hold_ms / 1000:.1f} s"
            elif status != P.OPEN:
                return self._cancel("expected fresh pinch STARTED")
        elif self.phase == "HOLDING":
            if status == P.HELD:
                self.last_held = stamp
                duration = stamp - self.hold_started
                self.feedback = ("RELEASE LEFT PINCH TO CONFIRM" if duration >= self.hold_ms else
                                 f"REARM HOLD: {duration / 1000:.1f} / {self.hold_ms / 1000:.1f} s")
            elif (status == P.RELEASED and ended and self.last_held is not None
                  and self.last_held-self.hold_started >= self.hold_ms):
                self.reset("REARM REQUEST COMPLETED")  # Consume once, including if the controller refuses.
                self.last_stamp = stamp
                return True
            else:
                return self._cancel("short or interrupted pinch")
        return False

    def mark_rearmed(self, stamp):
        self.reset("REARMED")
        self.rearmed_until = stamp + 1000
