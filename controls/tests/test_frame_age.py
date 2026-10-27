"""Capture-age rejection and existing cancellation paths; no Windows input."""

from dataclasses import replace
import math
import unittest
from unittest.mock import Mock

from .test_controls import Harness


class FrameAgeTest(unittest.TestCase):
    def fresh_frame(self, run):
        frame, features, pinches = run.step(dx=.01)
        run.now += .033
        stamp = frame.timestamp_ms + 33
        return replace(frame, timestamp_ms=stamp), features, tuple(replace(p, timestamp_ms=stamp) for p in pinches)

    def test_delayed_or_invalid_observation_never_dispatches(self):
        for age in (.251, .5, -.01, math.inf, math.nan):
            with self.subTest(age=age):
                r = Harness(mouse=True)
                r.arm()
                frame = self.fresh_frame(r)
                before = r.backend.counts.copy()
                r.controller.update(*frame, observed_at=r.now-age)
                self.assertFalse(r.controller.armed)
                self.assertIsNone(r.controller.last_good)
                self.assertEqual(r.backend.counts["move"], before["move"])
                self.assertEqual(r.backend.counts["down"], before["down"])

    def test_fresh_observation_preserves_mapping_and_reports_actual_move(self):
        r = Harness()
        r.arm()
        frame = self.fresh_frame(r)
        observer = Mock()
        r.controller.move_observer = observer
        before = r.backend.counts["move"]
        r.controller.update(*frame, observed_at=r.now-.020)
        self.assertTrue(r.controller.armed)
        self.assertGreater(r.backend.counts["move"], before)
        observer.assert_called_once()
        start, end = observer.call_args.args
        self.assertGreaterEqual(end, start)

    def test_stale_drag_is_released_and_cannot_auto_rearm(self):
        r = Harness(mouse=True, gesture_rearm=True)
        r.arm()
        r.start()
        self.assertTrue(r.backend.button_down)
        frame = self.fresh_frame(r)
        r.controller.update(*frame, observed_at=r.now-.3)
        self.assertFalse(r.backend.button_down)
        self.assertFalse(r.controller.armed)
        self.assertTrue(r.controller._hard_stopped)
        self.assertFalse(r.controller._routine_rearm)

    def test_age_expiring_in_cursor_query_blocks_move_and_releases_drag(self):
        r = Harness(mouse=True)
        r.arm()
        frame = self.fresh_frame(r)
        r.controller.cursor.reset()  # force fallible acquisition query
        def slow_position():
            r.now += .3
            return r.backend.position
        r.backend.cursor_position = slow_position
        before = r.backend.counts.copy()
        r.controller.update(*frame, observed_at=r.now)
        self.assertFalse(r.controller.armed)
        self.assertEqual(r.backend.counts["move"], before["move"])
        self.assertFalse(r.backend.button_down)

    def test_suppressed_backend_move_is_not_counted(self):
        r = Harness()
        r.arm()
        frame = self.fresh_frame(r)
        observer = Mock()
        r.controller.move_observer = observer
        r.backend.move = Mock(return_value=False)
        r.controller.update(*frame, observed_at=r.now)
        r.backend.move.assert_called_once()
        observer.assert_not_called()

    def test_emergency_during_query_still_cancels_input_with_age_gate(self):
        r = Harness(mouse=True)
        r.arm()
        frame = self.fresh_frame(r)
        r.controller.cursor.reset()
        def stop():
            r.controller.disarm("Emergency stop")
            return r.backend.position
        r.backend.cursor_position = stop
        before = r.backend.counts.copy()
        r.controller.update(*frame, observed_at=r.now)
        self.assertFalse(r.controller.armed)
        self.assertEqual(r.backend.counts["move"], before["move"])
        self.assertEqual(r.backend.counts["down"], before["down"])

    def test_malformed_host_timestamp_fails_closed_and_releases_owned_input(self):
        for timestamp in ("invalid", True, 10**1000):
            r = Harness(mouse=True)
            r.arm()
            r.start()
            frame = self.fresh_frame(r)
            r.controller.update(*frame, observed_at=timestamp)
            self.assertFalse(r.controller.armed)
            self.assertFalse(r.backend.button_down)


if __name__ == "__main__":
    unittest.main()
