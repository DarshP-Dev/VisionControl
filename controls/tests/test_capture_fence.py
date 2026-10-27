"""A capture fault must cancel in-flight input independently of inference."""

from dataclasses import replace
import threading
import unittest

from gestures.events import PINCH
from gestures.pinch import PinchStatus as P

from .test_controls import Harness


class CaptureFenceTest(unittest.TestCase):
    def test_fault_during_arm_position_query_cannot_commit_arming(self):
        run = Harness()
        run.step()
        fault = threading.Event()
        run.controller.pipeline_guard = lambda: not fault.is_set()
        def query():
            fault.set()
            return run.backend.position
        run.backend.cursor_position = query
        self.assertFalse(run.controller.arm())
        self.assertFalse(run.controller.armed)
        self.assertFalse(run.controller._manual_armed_once)

    def test_concurrent_fault_latches_before_waiting_for_inflight_drag_query(self):
        run = Harness(mouse=True)
        run.arm()
        run.start()
        self.assertTrue(run.backend.button_down)
        fault, entered, proceed = threading.Event(), threading.Event(), threading.Event()
        run.controller.pipeline_guard = lambda: not fault.is_set()
        run.controller.cursor.reset()
        def query():
            entered.set()
            if not proceed.wait(1):
                raise RuntimeError("test query deadline")
            return run.backend.position
        run.backend.cursor_position = query
        before = run.backend.counts.copy()
        updater = threading.Thread(target=lambda: run.step(PINCH, P.HELD))
        stopper = threading.Thread(target=run.controller.check_timeout)
        try:
            updater.start()
            self.assertTrue(entered.wait(1))
            fault.set()
            stopper.start()
            self.assertTrue(run.controller._stop_requested.wait(1))
        finally:
            proceed.set()
            updater.join(1)
            if stopper.ident is not None:
                stopper.join(1)
        self.assertFalse(updater.is_alive())
        self.assertFalse(stopper.is_alive())
        self.assertFalse(run.backend.button_down)
        self.assertFalse(run.controller.armed)
        self.assertEqual(run.backend.counts["move"], before["move"])
        self.assertEqual(run.backend.counts["down"], before["down"])

    def test_health_failure_releases_drag_through_independent_watchdog_path(self):
        run = Harness(mouse=True)
        run.arm()
        run.start()
        self.assertTrue(run.backend.button_down)
        failed = threading.Event()
        run.controller.pipeline_guard = lambda: not failed.is_set()
        failed.set()
        run.controller.check_timeout()  # Called by GlobalSafety without camera-loop progress.
        self.assertFalse(run.backend.button_down)
        self.assertFalse(run.controller.armed)
        self.assertTrue(run.controller._hard_stopped)
        self.assertFalse(run.controller.arm())

    def test_fault_during_cursor_query_cannot_be_followed_by_move(self):
        run = Harness()
        run.arm()
        failed = threading.Event()
        run.controller.pipeline_guard = lambda: not failed.is_set()
        run.controller.cursor.reset()
        def query():
            failed.set()
            return run.backend.position
        run.backend.cursor_position = query
        before = run.backend.counts.copy()
        run.step(dx=.02)
        self.assertEqual(run.backend.counts["move"], before["move"])
        self.assertFalse(run.controller._input_allowed())
        run.controller.check_timeout()
        self.assertFalse(run.controller.armed)

    def test_fault_during_pinch_anchor_query_cannot_send_down(self):
        run = Harness(mouse=True, mapping="absolute")
        run.arm()
        failed = threading.Event()
        run.controller.pipeline_guard = lambda: not failed.is_set()
        def query():
            failed.set()
            return run.backend.position
        run.backend.cursor_position = query
        before = run.backend.counts.copy()
        run.start()
        self.assertEqual(run.backend.counts["down"], before["down"])
        self.assertFalse(run.backend.button_down)
        run.controller.check_timeout()
        self.assertFalse(run.controller.arm())

    def test_manual_emergency_cancel_remains_latched_even_with_healthy_capture(self):
        run = Harness(mouse=True, gesture_rearm=True)
        run.arm()
        run.controller.pipeline_guard = lambda: True
        run.controller.disarm("GLOBAL EMERGENCY STOP")
        before = run.backend.counts.copy()
        run.step(dx=.01)
        self.assertFalse(run.controller.armed)
        self.assertFalse(run.controller._can_gesture_rearm())
        self.assertEqual(run.backend.counts["move"], before["move"])

    def test_stale_observation_is_rejected_even_when_producer_stays_healthy(self):
        run = Harness(mouse=True)
        run.arm()
        run.controller.pipeline_guard = lambda: True
        frame, features, pinches = run.step(dx=.01)
        run.now += .033
        stamp = frame.timestamp_ms+33
        before = run.backend.counts.copy()
        run.controller.update(replace(frame, timestamp_ms=stamp), features,
                              tuple(replace(p, timestamp_ms=stamp) for p in pinches), observed_at=run.now-.3)
        self.assertFalse(run.controller.armed)
        self.assertEqual(run.backend.counts["move"], before["move"])


if __name__ == "__main__":
    unittest.main()
