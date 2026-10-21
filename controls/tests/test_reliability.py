"""Phase 3.7 deterministic safety and extended-use regressions; virtual input only."""

from dataclasses import replace
import threading
import unittest

from controls.cursor import AbsoluteCursor, RelativeCursor
from controls.backends import SimulationBackend
from controls.controller import DesktopController
from controls.models import ControlSettings, Screen
from controls.windows import WindowsBackend
from gestures.events import SWIPE_RIGHT, EventType
from gestures.models import ImageSize
from .test_controls import Harness
from .test_windows import FakeAPI


class CursorReliabilityTest(unittest.TestCase):
    def test_relative_subpixel_steps_accumulate_in_both_directions_and_axes(self):
        size = ImageSize(1920, 1080)
        for invert in (False, True):
            for direction in (-1, 1):
                c = RelativeCursor(ControlSettings(alpha=1., sensitivity=1., invert_x=invert), Screen())
                c.update((.4, .4), size, (500, 500))
                for i in range(1, 101):
                    target = c.update((.4+direction*i*.00005, .4+i*.00005), size, (0, 0))
                sign = -direction if invert else direction
                self.assertEqual(target, (500+sign*12, 507))

    def test_relative_fractional_target_does_not_wind_up_at_an_edge(self):
        c = RelativeCursor(ControlSettings(alpha=1.), Screen())
        size = ImageSize(1920, 1080)
        c.update((.2, .3), size, (1918, 500))
        for i in range(1, 101):
            c.update((.2+i*.00005, .3), size, (0, 0))
        self.assertEqual(c.target[0], 1919)
        for i in range(1, 21):
            target = c.update((.205-i*.00005, .3), size, (0, 0))
        self.assertLess(target[0], 1919)

    def test_absolute_default_ema_settles_to_all_corners_without_offset_growth(self):
        screen = Screen(left=-1920, width=1920, height=1080)
        size = ImageSize(1920, 1080)
        c = AbsoluteCursor(ControlSettings(mapping="absolute"), screen)
        c.update((.5, .5), size, (-960, 540))
        for point, expected in (((.1, .1), (-1, 0)), ((.9, .1), (-1920, 0)),
                                ((.9, .9), (-1920, 1079)), ((.1, .9), (-1, 1079))):
            for _ in range(25):
                actual = c.update(point, size, (0, 0))
            self.assertEqual(actual, expected)
        self.assertIsNone(c.drag_offset)

    def test_absolute_drag_offset_is_constant_clamped_and_cleared_on_reset(self):
        c = AbsoluteCursor(ControlSettings(mapping="absolute"), Screen())
        size = ImageSize(1920, 1080)
        c.begin_drag((.6, .5), size, (900, 500))
        offset = c.drag_offset
        self.assertIsNone(c.update((.6, .5), size, (0, 0)))
        for _ in range(3000):
            target = c.update((.2, .8), size, (0, 0))
            self.assertEqual(c.drag_offset, offset)
            self.assertEqual(Screen().clamp(*target), target)
        c.reset()
        self.assertIsNone(c.drag_offset)
        self.assertIsNone(c.update((.1, .1), size, (900, 500)))


class SafetyReliabilityTest(unittest.TestCase):
    def test_completed_stop_during_arming_query_cannot_be_cleared_by_that_arm(self):
        h = Harness()
        h.step()
        original = h.backend.cursor_position
        def stop():
            h.controller.disarm("GLOBAL EMERGENCY STOP")
            return original()
        h.backend.cursor_position = stop
        self.assertFalse(h.controller.arm())
        self.assertFalse(h.controller.armed)
        self.assertEqual(h.backend.counts, {})
        h.backend.cursor_position = original
        self.assertTrue(h.controller.arm())  # A later, separate manual arm can proceed.

    def test_safety_failure_during_arming_query_cannot_enable_armed_status(self):
        h = Harness()
        h.step()
        original = h.backend.cursor_position
        def fail():
            h.controller.safety_failure("Emergency monitor unavailable")
            return original()
        h.backend.cursor_position = fail
        self.assertFalse(h.controller.arm())
        self.assertFalse(h.controller.armed)
        self.assertFalse(h.controller.safety_ready)
        h.backend.cursor_position = original
        self.assertFalse(h.controller.arm())

    def test_stop_during_foreground_query_prevents_shortcut_at_backend_boundary(self):
        api = FakeAPI()
        backend = WindowsBackend(api=api)
        h = Harness()
        h.controller = DesktopController(backend, ControlSettings(mode="live", tabs=True), clock=lambda: h.now)
        h.controller.safety_ready = True
        h.arm()
        def foreground():
            h.controller.disarm("GLOBAL EMERGENCY STOP")
            return 101, "chrome.exe"
        api.foreground.side_effect = foreground
        h.step(None, events=((SWIPE_RIGHT, EventType.GESTURE_STARTED, "confirmed"),))
        self.assertEqual(api.sent, [])
        self.assertFalse(h.controller.armed)
        self.assertEqual(h.controller.reason, "GLOBAL EMERGENCY STOP")

    def test_stop_during_physical_button_check_prevents_down(self):
        api = FakeAPI()
        backend = WindowsBackend(api=api)
        h = Harness()
        h.controller = DesktopController(backend, ControlSettings(mode="live", mouse=True), clock=lambda: h.now)
        h.controller.safety_ready = True
        h.arm()
        def key_state(_key):
            h.controller.disarm("GLOBAL EMERGENCY STOP")
            return 0
        api.user.GetAsyncKeyState.side_effect = key_state
        h.start()
        self.assertEqual(api.sent, [])
        self.assertFalse(backend.button_owned)
        self.assertEqual(h.controller.reason, "GLOBAL EMERGENCY STOP")

    def test_both_backends_block_normal_input_but_allow_owned_release(self):
        api = FakeAPI()
        for backend in (SimulationBackend(), WindowsBackend(api=api)):
            backend.left_down()
            backend.input_allowed = lambda: False
            before = len(api.sent)
            backend.move(200, 200)
            backend.left_down()
            self.assertFalse(backend.switch_tab(False, ("chrome.exe",)))
            self.assertEqual(len(api.sent), before)
            backend.left_up()
            if backend.is_live:
                self.assertEqual(api.sent[-1][0].mi.dwFlags, 4)
            else:
                self.assertFalse(backend.button_down)
                self.assertEqual(backend.counts["move"], 0)
                self.assertEqual(backend.counts["down"], 1)

    def test_absolute_cursor_query_failure_occurs_before_any_button_down(self):
        h = Harness(mapping="absolute", mouse=True)
        h.arm()
        def fail():
            raise OSError("fake cursor query failure")
        h.backend.cursor_position = fail
        with self.assertLogs("controls", level="ERROR"):
            h.start()
        self.assertEqual(h.backend.counts["down"], 0)
        self.assertFalse(h.backend.button_down)
        self.assertFalse(h.controller.armed)

    def test_emergency_during_blocked_drag_preparation_prevents_pending_down(self):
        h = Harness(mapping="absolute", mouse=True)
        h.arm()
        entered, resume = threading.Event(), threading.Event()
        original = h.backend.cursor_position
        def blocked():
            entered.set()
            if not resume.wait(2):
                raise TimeoutError("fake backend test timed out")
            return original()
        h.backend.cursor_position = blocked
        worker = threading.Thread(target=h.start)
        stop = threading.Thread(target=lambda: h.controller.disarm("GLOBAL EMERGENCY STOP"))
        worker.start()
        try:
            self.assertTrue(entered.wait(1))
            self.assertEqual(h.backend.counts["down"], 0)
            stop.start()
            self.assertTrue(h.controller._stop_requested.wait(1))
        finally:
            resume.set()
            worker.join(2)
            if stop.ident is not None:
                stop.join(2)
        self.assertFalse(worker.is_alive())
        self.assertFalse(stop.is_alive())
        self.assertEqual(h.backend.counts["down"], 0)
        self.assertEqual(h.backend.counts["move"], 0)
        self.assertFalse(h.controller.armed)

    def test_watchdog_during_blocked_query_prevents_pending_down(self):
        h = Harness(mapping="absolute", mouse=True)
        h.arm()
        original = h.backend.cursor_position
        def expire():
            h.now += .501
            h.controller.check_timeout()
            return original()
        h.backend.cursor_position = expire
        h.start()
        self.assertFalse(h.controller.armed)
        self.assertEqual(h.backend.counts["down"], 0)

    def test_safety_failure_during_query_prevents_pending_input_and_rearm(self):
        h = Harness(mapping="absolute", mouse=True)
        h.arm()
        original = h.backend.cursor_position
        def lost_monitor():
            h.controller.safety_failure("fake emergency monitor failure")
            return original()
        h.backend.cursor_position = lost_monitor
        h.start()
        self.assertFalse(h.controller.armed)
        self.assertFalse(h.controller.arm())
        self.assertEqual(h.backend.counts["down"], 0)

    def test_failed_mouse_up_recovers_on_bounded_cleanup_retry_while_disarmed(self):
        h = Harness(mouse=True)
        h.arm()
        h.start()
        original = h.backend.left_up
        attempts = 0
        def transient():
            nonlocal attempts
            attempts += 1
            if attempts <= 2:
                raise OSError("temporary mouse-up failure")
            original()
        h.backend.left_up = transient
        with self.assertLogs("controls", level="ERROR"):
            h.controller.disarm()
        self.assertTrue(h.backend.button_down)
        h.now += .101
        h.controller.check_timeout()
        self.assertFalse(h.backend.button_down)
        self.assertFalse(h.controller.button_down)
        self.assertEqual(h.controller.last_action, "LEFT_BUTTON_UP")
        self.assertFalse(h.controller.arm())  # The original backend fault stays latched.
        self.assertEqual(attempts, 3)

    def test_permanent_release_failure_retries_are_bounded_and_never_rearm(self):
        h = Harness(mouse=True)
        h.arm()
        h.start()
        attempts = 0
        def permanent():
            nonlocal attempts
            attempts += 1
            raise OSError("permanent release failure")
        h.backend.left_up = permanent
        with self.assertLogs("controls", level="ERROR"):
            h.controller.disarm()
            for _ in range(100):
                h.now += .101
                h.controller.check_timeout()
        self.assertEqual(attempts, 5)  # Initial release + close, then three watchdog retries.
        self.assertFalse(h.controller.armed)
        self.assertFalse(h.controller.arm())
        self.assertTrue(h.backend.button_down)  # Honest ownership: the OS/fake refused UP.

    def test_transient_primary_up_failure_retry_success_does_not_leave_stale_down(self):
        h = Harness(mouse=True)
        h.arm()
        h.start()
        original = h.backend.left_up
        first = True
        def release():
            nonlocal first
            if first:
                first = False
                raise OSError("one failure")
            original()
        h.backend.left_up = release
        with self.assertLogs("controls", level="ERROR"):
            h.controller.disarm()
        self.assertFalse(h.controller.button_down)
        self.assertFalse(h.backend.button_down)

    def test_no_pending_event_replay_after_disarm_and_new_frame(self):
        h = Harness(mouse=True)
        h.arm()
        frame, features, pinches = h.step()
        before = h.backend.counts.copy()
        h.controller.disarm()
        for i in range(100):
            stamp = frame.timestamp_ms+10*(i+1)
            h.controller.update(replace(frame, timestamp_ms=stamp), features,
                                tuple(replace(p, timestamp_ms=stamp) for p in pinches))
        self.assertEqual(h.backend.counts["down"], 0)
        self.assertEqual(h.backend.counts["move"], before["move"])


if __name__ == "__main__":
    unittest.main()
