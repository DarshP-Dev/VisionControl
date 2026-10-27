"""Dropped observations use elapsed capture time; never interpolate events."""

import unittest

from controls.tests.profile_fixtures import ProfileRun
from gestures.events import PINCH, SWIPES, EventType as E
from gestures.tests.static_fixtures import as_result, SIZE
from gestures.tests.test_swipe import Run
from .test_multi_hand import pipeline, four
from .performance import Profile


class SkippedObservationTest(unittest.TestCase):
    def test_variable_capture_intervals_preserve_single_pinch_down_up(self):
        r = ProfileRun(mouse=True)
        r.controller.pipeline_guard = lambda: True
        r.arm()
        before = r.backend.counts.copy()
        for dt in (40, 80, 120):
            r.step(right=.08, dt=dt)
        self.assertTrue(r.backend.button_down)
        r.step(right=.8, dt=90)
        self.assertFalse(r.backend.button_down)
        self.assertEqual(r.backend.counts["down"]-before["down"], 1)
        self.assertEqual(r.backend.counts["up"]-before["up"], 1)

    def test_gap_during_drag_cancels_instead_of_completing_or_restarting_pinch(self):
        r = ProfileRun(mouse=True)
        r.controller.pipeline_guard = lambda: True
        r.arm()
        r.step(right=.08)
        r.step(right=.08)
        self.assertTrue(r.backend.button_down)
        before = r.backend.counts.copy()
        frame = r.step(right=.08, dt=300)
        self.assertFalse(r.backend.button_down)
        self.assertFalse(r.controller.armed)
        self.assertTrue(any(e.gesture == PINCH and e.event_type == E.GESTURE_CANCELED for e in frame.events))
        self.assertFalse(any(e.gesture == PINCH and e.event_type == E.GESTURE_ENDED for e in frame.events))
        r.step(right=.08, dt=80)
        self.assertEqual(r.backend.counts["down"], before["down"])

    def test_entire_unobserved_pinch_cannot_be_fabricated_from_open_endpoints(self):
        r = ProfileRun(mouse=True)
        r.arm()
        before = r.backend.counts.copy()
        r.step(dt=120)  # No closed sample was delivered from the camera slot.
        self.assertEqual(r.backend.counts["down"], before["down"])
        self.assertEqual(r.backend.counts["up"], before["up"])

    def test_variable_intervals_preserve_one_swipe_but_long_gap_cannot_complete_one(self):
        r = Run()
        r.arm()
        for stamp, dx in ((300, .4), (380, 1.), (460, 1.8)):
            r.single(stamp, dx)
        self.assertEqual([e.event_type for e in r.swipe_events()], [E.GESTURE_STARTED, E.GESTURE_ENDED])
        r = Run()
        r.arm()
        r.single(300, .4)
        r.single(700, 1.8)
        self.assertEqual(r.swipe_events(), [])

    def test_four_track_ids_survive_short_skips_and_reordering_with_independent_history(self):
        p = pipeline()
        p.update(as_result(*four()), 0, SIZE, Profile(False))
        ids = tuple(a.track_id for a in p.associations)
        for stamp in (40, 130, 210):
            p.update(as_result(*reversed(four())), stamp, SIZE, Profile(False))
            self.assertEqual(tuple(a.track_id for a in p.associations), tuple(reversed(ids)))
            self.assertEqual(len(p.smoother._history), 4)
            self.assertEqual(len(p.state_manager._tracks), 4)

    def test_long_four_hand_gap_discards_smoothing_and_cannot_release_closed_pinch(self):
        p = pipeline()
        p.update(as_result(*four(ratio=.8)), 0, SIZE, Profile(False))
        p.update(as_result(*four(ratio=.08)), 50, SIZE, Profile(False))
        p.update(as_result(*four(ratio=.08)), 150, SIZE, Profile(False))
        ids = {a.track_id for a in p.associations}
        _, _, pinches, frame = p.update(as_result(*four(ratio=.08)), 600, SIZE, Profile(False))
        self.assertTrue(ids.isdisjoint(p.smoother._history))
        self.assertTrue(all(p.status.value == "UNAVAILABLE" for p in pinches))
        self.assertFalse(any(e.gesture in set(SWIPES) | {PINCH} and e.event_type in
                             (E.GESTURE_STARTED, E.GESTURE_ENDED) for e in frame.events))


if __name__ == "__main__":
    unittest.main()
