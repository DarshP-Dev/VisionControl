"""Optional track IDs namespace existing recognition; no new event engine."""

from dataclasses import replace
import unittest

from gestures.events import PINCH, EventType as E, GestureEvent, GestureState as S
from gestures.models import HandednessPrediction, HandSide as H
from gestures.pinch import PinchStatus as P, PinchTracker
from gestures.state_machine import GestureStateManager
from gestures.static_gestures import Gesture as G, classify_hand
from hand_tracking.multi_hand_fixtures import four, features, hand


class TrackNamespaceTest(unittest.TestCase):
    def setUp(self):
        self.pinch, self.manager = PinchTracker(), GestureStateManager()

    def observe(self, observations, stamp, identities=(1, 2, 3, 4)):
        items = features(observations)
        pinches = self.pinch.update(items, stamp, identities=identities)
        static = tuple(classify_hand(item, stamp, track_id=key) for item, key in zip(items, identities))
        return self.manager.update(items, stamp, static, pinches, identities=identities), pinches

    def test_four_duplicate_right_labels_have_independent_open_palm_events(self):
        self.observe(four(), 0)
        frame, _ = self.observe(four(), 100)
        self.assertEqual({e.track_id for e in frame.events if e.event_type == E.GESTURE_STARTED}, {1, 2, 3, 4})
        self.assertTrue(all(e.side == H.RIGHT for e in frame.events))

    def test_reordering_independent_pinch_lifecycles_do_not_leak(self):
        self.observe(four(ratio=.8), 0)
        closing = tuple(hand(x, ratio=.08 if i in (0, 2) else .8)
                        for i, x in enumerate((.15, .37, .59, .81)))
        frame, pinches = self.observe(closing, 50)
        self.assertEqual([p.status for p in pinches], [P.STARTED, P.OPEN, P.STARTED, P.OPEN])
        self.assertEqual({e.track_id for e in frame.events if e.gesture == PINCH and e.event_type == E.GESTURE_STARTED}, {1, 3})
        frame, pinches = self.observe(tuple(reversed(closing)), 100, (4, 3, 2, 1))
        self.assertEqual([p.track_id for p in pinches], [4, 3, 2, 1])
        self.assertEqual([p.status for p in pinches], [P.OPEN, P.HELD, P.OPEN, P.HELD])
        release = tuple(hand(x, ratio=.08 if i == 2 else .8) for i, x in enumerate((.15, .37, .59, .81)))
        frame, _ = self.observe(release, 150)
        self.assertEqual({e.track_id for e in frame.events if e.gesture == PINCH and e.event_type == E.GESTURE_ENDED}, {1})

    def test_unknown_or_flipped_handedness_does_not_change_track_history(self):
        self.observe((hand(ratio=.8),), 0, (7,))
        frame, _ = self.observe((hand(ratio=.08),), 50, (7,))
        original = hand(ratio=.08)
        changed = replace(original, handedness=(HandednessPrediction("Left", .1),))
        frame, pinches = self.observe((changed,), 100, (7,))
        self.assertEqual(pinches[0].status, P.HELD)
        self.assertEqual(frame.hands[0].confirmed, PINCH)
        self.assertEqual(frame.hands[0].track_id, 7)
        frame, _ = self.observe((replace(hand(ratio=.8), handedness=()),), 150, (7,))
        ended = [e for e in frame.events if e.gesture == PINCH and e.event_type == E.GESTURE_ENDED]
        self.assertEqual((ended[0].side, ended[0].track_id), (H.UNKNOWN, 7))

    def test_missing_track_cancels_without_release_and_closed_return_cannot_start(self):
        self.observe(four(ratio=.8), 0)
        self.observe(four(ratio=.08), 50)
        frame, _ = self.observe(four(ratio=.08)[1:], 100, (2, 3, 4))
        missing = [e for e in frame.events if e.track_id == 1]
        self.assertEqual([e.event_type for e in missing], [E.GESTURE_CANCELED])
        self.assertFalse(missing[0].metadata.association_current)
        frame, pinches = self.observe(four(ratio=.08), 150)
        self.assertEqual(pinches[0].status, P.UNAVAILABLE)
        self.assertFalse(any(e.track_id == 1 and e.event_type in (E.GESTURE_STARTED, E.GESTURE_ENDED) for e in frame.events))

    def test_uncertain_key_cancels_only_that_track_and_requires_fresh_open(self):
        self.observe(four(ratio=.8), 0)
        self.observe(four(ratio=.08), 50)
        frame, pinches = self.observe(four(ratio=.08), 100, (1, None, 3, 4))
        self.assertEqual(pinches[1].status, P.UNAVAILABLE)
        self.assertIsNone(frame.hands[1].track_id)
        self.assertEqual({e.track_id for e in frame.events if e.event_type == E.GESTURE_CANCELED}, {2})
        self.assertEqual(frame.hands[2].confirmed, PINCH)
        frame, pinches = self.observe(four(ratio=.08), 150)
        self.assertEqual(pinches[1].status, P.UNAVAILABLE)

    def test_invalid_track_keys_fail_closed_and_duplicate_keys_never_combine(self):
        items = features(four())
        for keys in ((1, 1, 2, 3), (1, 2), (1, 2, 3, True), (0, 2, 3, 4), (1, 2, 3, -1)):
            with self.assertRaises(ValueError):
                self.pinch.update(items, 0, identities=keys)
            static = tuple(classify_hand(item, 0) for item in items)
            frame = GestureStateManager().update(items, 0, static, identities=keys)
            self.assertTrue(all(h.reason == "invalid_channel_alignment" for h in frame.hands))
            self.assertEqual(frame.events, ())

    def test_legacy_duplicate_labels_still_fail_closed(self):
        items = features(four()[:2])
        self.assertTrue(all(p.status == P.UNAVAILABLE for p in self.pinch.update(items, 0)))
        frame = self.manager.update(items, 0, tuple(classify_hand(item, 0) for item in items))
        self.assertTrue(all(h.reason == "ambiguous_handedness" for h in frame.hands))

    def test_swapped_same_label_static_or_pinch_channels_are_rejected_by_track_id(self):
        for swap in ("static", "pinch"):
            self.setUp()
            self.observe(four(), 0)
            self.observe(four(), 100)
            items = features(four())
            pinches = self.pinch.update(items, 150, identities=(1, 2, 3, 4))
            static = tuple(classify_hand(item, 150, track_id=key) for key, item in enumerate(items, 1))
            if swap == "static":
                static = (static[1], static[0], *static[2:])
            else:
                pinches = (pinches[1], pinches[0], *pinches[2:])
            frame = self.manager.update(items, 150, static, pinches, identities=(1, 2, 3, 4))
            self.assertEqual(frame.hands[0].reason, "invalid_geometry_or_channel")
            self.assertEqual(frame.hands[1].reason, "invalid_geometry_or_channel")
            self.assertEqual({e.track_id for e in frame.events if e.event_type == E.GESTURE_CANCELED}, {1, 2})
            self.assertEqual(frame.hands[2].confirmed, G.OPEN_PALM)

    def test_unknown_side_event_requires_an_explicit_valid_track_id(self):
        with self.assertRaises(ValueError):
            GestureEvent(PINCH, E.GESTURE_STARTED, 0, H.UNKNOWN, S.ACTIVE)
        event = GestureEvent(PINCH, E.GESTURE_STARTED, 0, H.UNKNOWN, S.ACTIVE, track_id=9)
        self.assertEqual(event.track_id, 9)
        for key in (True, 0, -1, "9"):
            with self.assertRaises(ValueError):
                GestureEvent(PINCH, E.GESTURE_STARTED, 0, H.UNKNOWN, S.ACTIVE, track_id=key)


if __name__ == "__main__":
    unittest.main()
