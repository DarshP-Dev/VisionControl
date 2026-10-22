"""Experimental observation IDs cannot acquire desktop ownership, even directly."""

from dataclasses import replace
import unittest

from gestures.events import PINCH, EventType as E, GestureEvent, GestureState as S
from gestures.models import HandSide
from gestures.pinch import PinchStatus as P
from gestures.static_gestures import Gesture
from .test_controls import Harness


class TrackIsolationTest(unittest.TestCase):
    def test_direct_track_state_during_drag_fails_closed_and_releases(self):
        h = Harness(mouse=True)
        h.arm()
        h.start()
        frame, features, pinches = h.step(PINCH, P.HELD)
        before = h.backend.counts["move"]
        stamp = frame.timestamp_ms + 1
        frame = replace(frame, timestamp_ms=stamp, hands=tuple(replace(s, track_id=1) for s in frame.hands))
        h.controller.update(frame, features, tuple(replace(p, timestamp_ms=stamp) for p in pinches))
        self.assertFalse(h.controller.armed)
        self.assertFalse(h.controller.button_down)
        self.assertEqual(h.backend.counts["move"], before)
        self.assertEqual(h.backend.counts["up"], 1)

    def test_direct_track_event_is_rejected_even_with_legacy_hand_states(self):
        h = Harness()
        h.arm()
        frame, features, pinches = h.step()
        stamp = frame.timestamp_ms + 1
        event = GestureEvent(Gesture.POINTING, E.GESTURE_STARTED, stamp, HandSide.RIGHT, S.ACTIVE, track_id=7)
        before = h.backend.counts["move"]
        h.controller.update(replace(frame, timestamp_ms=stamp, events=(event,)), features,
                            tuple(replace(p, timestamp_ms=stamp) for p in pinches))
        self.assertFalse(h.controller.armed)
        self.assertEqual(h.backend.counts["move"], before)


if __name__ == "__main__":
    unittest.main()
