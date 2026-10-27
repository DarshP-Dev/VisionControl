"""Window lifecycle and the real synchronous loop, with virtual input only."""

from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

import cv2
import numpy as np

from controls.backends import SimulationBackend
from controls.controller import DesktopController
from gestures.tests.static_fixtures import as_result
from . import hand_tracker as tracker
from .preview_window import PreviewWindow, Win32PreviewAPI


FLAGS = ["--gestures", "--pinch", "--gesture-states", "--controls", "--gui-mode", "waitkey"]


class WindowTest(unittest.TestCase):
    def test_native_minimize_restore_close_uses_one_owned_handle_and_latches_close(self):
        api = MagicMock()
        api.find.return_value = 9876543210  # No 32-bit handle truncation in wrapper.
        api.state.side_effect = ["focused", "unfocused", "minimized", "focused", "closed"]
        window = PreviewWindow("test", api=api)
        states = [window.state() for _ in range(6)]
        self.assertEqual(states, ["focused", "unfocused", "minimized", "focused", "closed", "closed"])
        self.assertEqual([window.should_render(s) for s in states], [True, True, False, True, False, False])
        api.find.assert_called_once_with("test")
        self.assertEqual(api.state.call_count, 5)
        self.assertTrue(all(call.args == (9876543210, "test") for call in api.state.call_args_list))

    def test_missing_owned_window_fails_closed(self):
        api = MagicMock()
        api.find.return_value = None
        with self.assertRaises(OSError):
            PreviewWindow("test", api=api)

    def test_native_checks_ownership_before_minimize_and_does_not_treat_minimize_as_close(self):
        api = object.__new__(Win32PreviewAPI)
        api.user = MagicMock()
        with patch.object(api, "owned", return_value=False):
            self.assertEqual(api.state(1, "test"), "closed")
        api.user.IsIconic.assert_not_called()
        with patch.object(api, "owned", return_value=True):
            api.user.IsIconic.return_value = True
            self.assertEqual(api.state(1, "test"), "minimized")
            api.user.IsIconic.return_value = False
            api.user.IsWindowVisible.return_value = False
            self.assertEqual(api.state(1, "test"), "hidden")
            api.user.IsWindowVisible.return_value = True
            api.user.GetForegroundWindow.return_value = 1
            self.assertEqual(api.state(1, "test"), "focused")
            api.user.GetForegroundWindow.return_value = 2
            self.assertEqual(api.state(1, "test"), "unfocused")

    def test_portable_fallback_reports_unknown_focus_and_handles_destroyed_window(self):
        window = PreviewWindow("test")
        with patch.object(cv2, "getWindowProperty", side_effect=[1, cv2.error("destroyed")]):
            self.assertEqual(window.state(), "visible_unknown")
            self.assertEqual(window.state(), "closed")
            self.assertEqual(window.state(), "closed")

    def test_window_identity_requires_current_pid_title_and_highgui_class(self):
        api = object.__new__(Win32PreviewAPI)
        api.pid = 123
        api.user = MagicMock()
        api.user.IsWindow.return_value = True
        def process(_hwnd, pid):
            pid._obj.value = 123
            return 1
        api.user.GetWindowThreadProcessId.side_effect = process
        api.user.GetWindowTextW.side_effect = lambda _h, text, _n: setattr(text, "value", "test") or 4
        api.user.GetClassNameW.side_effect = lambda _h, text, _n: setattr(text, "value", "Main HighGUI class") or 18
        self.assertTrue(api.owned(99, "test"))
        self.assertFalse(api.owned(99, "different"))
        api.pid = 456
        api.user.GetWindowTextW.reset_mock()
        self.assertFalse(api.owned(99, "test"))
        api.user.GetWindowTextW.assert_not_called()  # Never inspect foreign titles.

    def test_real_recognition_and_palm_controller_keep_running_across_preview_states(self):
        from controls import cli
        from gestures.tests.test_swipe import sample_hand
        clock = [0.]
        cap, detector = MagicMock(), MagicMock()
        def read():
            clock[0] += .05
            return True, np.zeros((90, 160, 3), np.uint8)
        cap.read.side_effect = read
        detector.detect_for_video.return_value = as_result(sample_hand(side="Right").observation)
        mp = SimpleNamespace(Image=lambda **kw: kw["data"], ImageFormat=SimpleNamespace(SRGB=1))
        args = tracker.parse_args(FLAGS+["--control-gesture-profile", "palm-cursor", "--control-mapping", "absolute", "--control-mouse"])
        controller = DesktopController(SimulationBackend(), cli.settings(args), clock=lambda: clock[0])
        window = MagicMock()
        window.state.side_effect = ["focused"]*7 + ["unfocused"]*3 + ["minimized"]*5 + ["focused"]*5 + ["closed"]
        window.should_render.side_effect = PreviewWindow.should_render
        snapshots = []
        update = controller.update
        def record(*a, **kw):
            update(*a, **kw)
            snapshots.append((controller.armed, controller.backend.counts.copy()))
        controller.update = record
        with patch.object(tracker.time, "perf_counter", side_effect=lambda: clock[0]), \
                patch.object(cv2, "waitKey", side_effect=[-1]*4+[ord("a")]+[-1]*16), \
                patch.object(cv2, "imshow"), self.assertLogs(tracker.LOGGER):
            tracker.process_frames(cap, detector, mp, args, {}, controller, preview_window=window)
        self.assertTrue(all(armed for armed, _ in snapshots[5:]))
        self.assertGreater(snapshots[14][1]["move"], snapshots[9][1]["move"])
        self.assertGreater(snapshots[19][1]["move"], snapshots[14][1]["move"])
        self.assertEqual(controller.backend.counts["down"], 0)
        self.assertFalse(controller.armed)
        self.assertFalse(controller.backend.button_down)


class BackgroundLoopTest(unittest.TestCase):
    def pipeline(self, states, *, control=True, fault=False, profiling=True, held=False):
        clock = [0.]
        cap, detector = MagicMock(), MagicMock()
        def read():
            clock[0] += .033
            return True, np.full((90, 160, 3), cap.read.call_count, np.uint8)
        cap.read.side_effect = read
        detector.detect_for_video.return_value = as_result()
        mp = SimpleNamespace(Image=lambda **kw: kw["data"], ImageFormat=SimpleNamespace(SRGB=1))
        window = MagicMock()
        window.state.side_effect = states
        window.should_render.side_effect = PreviewWindow.should_render
        args = tracker.parse_args(FLAGS if control else ["--gui-mode", "waitkey"])
        c = DesktopController(SimulationBackend(), clock=lambda: clock[0]) if control else None
        seen = []
        if c:
            # Observe whether lifecycle alone disarms; no fake gesture validity.
            c.armed = True
            c.button_down = c.backend.button_down = held
            c.update = lambda *a, **kw: seen.append((window.state.call_count, c.armed, kw["observed_at"]))
        report = {}
        with patch.object(tracker.time, "perf_counter", side_effect=lambda: clock[0]), \
                patch.object(cv2, "waitKey", return_value=-1) as poll, \
                patch.object(cv2, "imshow", side_effect=RuntimeError("display fault") if fault else None) as display, \
                patch.object(tracker, "make_preview", wraps=tracker.make_preview) as draw, \
                self.assertLogs(tracker.LOGGER):
            if fault:
                c.button_down = c.backend.button_down = True
                with self.assertRaises(RuntimeError):
                    tracker.process_frames(cap, detector, mp, args, report, c, preview_window=window)
            else:
                tracker.process_frames(cap, detector, mp, args, report, c, preview_window=window, profile_enabled=profiling)
        return cap, detector, c, seen, report, poll, display, draw

    def test_focused_unfocused_minimized_restored_keep_tracking_and_controls_until_close(self):
        cap, detector, c, seen, report, poll, display, draw = self.pipeline(
            ["focused", "unfocused", "minimized", "minimized", "focused", "closed"])
        self.assertEqual(cap.read.call_count, 6)
        self.assertEqual(detector.detect_for_video.call_count, 6)
        self.assertEqual(poll.call_count, 6)  # Includes both minimized iterations.
        self.assertEqual(display.call_count, 3)
        self.assertEqual(draw.call_count, 3)
        self.assertEqual(draw.call_args.args[0][0, 0, 0], 5)  # Restore draws current frame, not frame 2.
        self.assertTrue(all(armed for _, armed, _ in seen))
        self.assertEqual(len(seen), 5)  # Closed frame cannot reach controller.
        self.assertFalse(c.armed)
        cap.release.assert_not_called()  # run() owns release; minimize never does.
        detector.close.assert_not_called()
        self.assertEqual(report["status"], "preview_closed")
        self.assertEqual(report["pacing"]["preview_frames_skipped"], 2)
        self.assertEqual(report["pacing"]["transitions"]["minimized->focused"], 1)
        self.assertEqual(report["timings_by_preview_state"]["minimized"]["inference"]["count"], 2)
        self.assertNotIn("landmark_drawing", report["timings_by_preview_state"]["minimized"])

    def test_close_before_dispatch_releases_owned_mouse(self):
        # Failure cleanup includes input owned before this iteration.
        cap, detector, c, seen, report, *_ = self.pipeline(["closed"], held=True)
        self.assertEqual(seen, [])
        self.assertFalse(c.button_down)
        self.assertFalse(c.armed)
        self.assertEqual(c.backend.counts["up"], 1)

    def test_restored_display_fault_releases_drag_and_exits(self):
        _, _, c, _, _, *_ = self.pipeline(["minimized", "focused"], fault=True)
        self.assertFalse(c.backend.button_down)
        self.assertFalse(c.armed)

    def test_disabled_profiling_collects_no_samples_or_move_callback(self):
        *_, report, poll, display, draw = self.pipeline(["minimized", "focused", "closed"], profiling=False)
        self.assertEqual(report["timings"], {})
        self.assertEqual(report["timings_by_preview_state"], {})
        self.assertEqual(report["pacing"]["timings"], {})
        self.assertEqual(report["pacing"]["cursor_updates"], 0)


if __name__ == "__main__":
    unittest.main()
