"""Phase 3.6 application integration: virtual input sink, fake camera/model/GUI."""

from contextlib import ExitStack, redirect_stderr
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

import cv2
import numpy as np

from controls import cli
from controls.backends import SimulationBackend
from controls.controller import DesktopController
from controls.models import ControlSettings
from gestures.models import HandSide
from gestures.tests.pinch_fixtures import pinch_hand
from gestures.tests.static_fixtures import as_result
from gestures.tests.test_swipe import sample_hand
from . import hand_tracker as tracker, gesture_preview
from .tracking_utils import make_preview


FLAGS = ["--gestures", "--pinch", "--gesture-states", "--controls"]


class ControlApplicationTest(unittest.TestCase):
    def test_horizontal_inversion_cli_defaults_and_both_modes(self):
        self.assertFalse(tracker.parse_args([]).control_invert_x)
        self.assertFalse(cli.settings(tracker.parse_args(FLAGS)).invert_x)
        for mode in ("simulate", "live"):
            args = tracker.parse_args(FLAGS+["--control-mode", mode, "--control-invert-x"])
            self.assertTrue(cli.settings(args).invert_x)
            self.assertEqual(cli.settings(args).mode, mode)
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            tracker.parse_args(["--control-invert-x"])

    def test_defaults_do_not_change_tracking_or_enable_controls(self):
        args = tracker.parse_args([])
        self.assertFalse(args.controls)
        self.assertEqual(args.control_mode, "simulate")
        self.assertFalse(args.control_mouse)
        self.assertFalse(args.control_tabs)
        self.assertEqual((args.backend, args.width, args.height, args.fps, args.gui_mode),
                         ("msmf", 1920, 1080, 60., "auto"))
        self.assertEqual(cli.settings(args), ControlSettings())

    def test_cli_dependencies_and_bounds(self):
        invalid = (["--controls"], ["--control-mode", "live"], ["--control-mouse"], ["--control-tabs"],
                   ["--control-debug"], FLAGS+["--no-smoothing"], FLAGS+["--no-gestures"],
                   FLAGS+["--benchmark", "--headless"], FLAGS+["--control-tabs"],
                   FLAGS+["--control-alpha", "0"], FLAGS+["--control-alpha", "nan"],
                   FLAGS+["--control-alpha", "1", "--smoothing-alpha", "1"],
                   FLAGS+["--control-sensitivity", "6"], FLAGS+["--control-margin", ".5"],
                   FLAGS+["--control-monitor", "-1"], FLAGS+["--control-monitor", "1"],
                   FLAGS+["--control-sim-size", "1920"], FLAGS+["--control-sim-size", "0x1080"],
                   FLAGS+["--control-browser", "C:\\chrome.exe"], FLAGS+["--control-hand", "any"])
        for flags in invalid:
            with self.subTest(flags=flags), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                tracker.parse_args(flags)
        args = tracker.parse_args(FLAGS+["--control-mode", "live", "--control-mouse", "--swipes", "--control-tabs",
                                        "--control-hand", "left", "--control-monitor", "1",
                                        "--control-browser", "CHROME.EXE", "--control-browser", "firefox.exe"])
        self.assertEqual(cli.settings(args).hand, HandSide.LEFT)
        self.assertEqual(cli.settings(args).browsers, ("chrome.exe", "firefox.exe"))

    def test_simulation_factory_never_constructs_windows_backend(self):
        with patch("controls.windows.WindowsBackend") as windows, ExitStack() as resources:
            c = cli.create_controller(tracker.parse_args(FLAGS+["--control-sim-size", "2560x1440"]), resources)
            self.assertEqual(c.backend.screen.width, 2560)
            self.assertFalse(c.armed)
        windows.assert_not_called()
        self.assertTrue(c.closed)

    def test_live_factory_initializes_stop_before_returning_and_fails_closed(self):
        backend = MagicMock(is_live=True)
        backend.screen = cli.simulation_screen(tracker.parse_args([]))
        with patch("controls.windows.WindowsBackend", return_value=backend), \
                patch("controls.safety.GlobalSafety") as safety:
            safety.return_value.start.side_effect = OSError("hotkey registration failed")
            with self.assertRaises(OSError), ExitStack() as resources:
                cli.create_controller(tracker.parse_args(FLAGS+["--control-mode", "live"]), resources)
            backend.move.assert_not_called()
            backend.left_down.assert_not_called()
            safety.return_value.close.assert_called_once()
            self.assertGreaterEqual(backend.close.call_count, 1)

    def test_default_pipeline_skips_mapper_and_extra_timing(self):
        cap, detector = MagicMock(), MagicMock()
        cap.read.return_value = True, np.zeros((480, 640, 3), np.uint8)
        detector.detect_for_video.return_value = as_result()
        mp = SimpleNamespace(Image=lambda **kw: kw["data"], ImageFormat=SimpleNamespace(SRGB=1))
        report = {}
        with patch.object(cli, "create_controller") as factory, patch.object(cv2, "imshow"), \
                patch.object(cv2, "waitKey", return_value=ord("q")), self.assertLogs(tracker.LOGGER):
            tracker.process_frames(cap, detector, mp, tracker.parse_args(["--gui-mode", "waitkey"]), report)
        factory.assert_not_called()
        self.assertFalse(report["controls"]["enabled"])
        self.assertNotIn("controller_processing", report["timings"])

    def pipeline(self, frames, keys, extra=(), controller=None):
        now = 0.
        cap, detector = MagicMock(), MagicMock()
        camera = np.full((1080, 1920, 3), 120, np.uint8)
        def read():
            nonlocal now
            now += .05
            return True, camera
        cap.read.side_effect = read
        detector.detect_for_video.side_effect = frames
        mp = SimpleNamespace(Image=lambda **kw: kw["data"], ImageFormat=SimpleNamespace(SRGB=1))
        configured = tracker.parse_args(FLAGS+["--gui-mode", "waitkey"]+list(extra))
        backend = SimulationBackend()
        c = controller or DesktopController(backend, cli.settings(configured), clock=lambda: now)
        report = {}
        with patch.object(tracker.time, "perf_counter", side_effect=lambda: now), \
                patch.object(cv2, "waitKey", side_effect=keys), patch.object(cv2, "imshow"), \
                patch.object(cv2, "getWindowProperty", return_value=1), \
                patch.object(tracker, "make_preview", wraps=make_preview) as preview, \
                patch.object(gesture_preview, "extract_features", wraps=gesture_preview.extract_features) as extract, \
                self.assertLogs(tracker.LOGGER):
            tracker.process_frames(cap, detector, mp, configured, report, c)
        return c, report, preview, extract, camera, detector

    def test_real_pinch_engine_drives_simulated_click_drag_release_and_profiles(self):
        frames = [as_result(pinch_hand(ratio, side="Right", offset=offset)) for ratio, offset in
                  ((.8, 0), (.8, 0), (.08, 0), (.08, .01), (.08, .02), (.8, .02))]
        c, report, preview, extract, camera, detector = self.pipeline(
            frames, [ord("a"), ord("h"), -1, -1, -1, ord("q")], ("--control-mouse",))
        self.assertEqual(c.backend.counts["down"], 1)
        self.assertEqual(c.backend.counts["up"], 1)
        self.assertGreater(c.backend.counts["move"], 0)
        self.assertEqual(report["gesture_states"]["event_counts"]["GESTURE_STARTED:PINCH"], 1)
        self.assertEqual(report["gesture_states"]["event_counts"]["GESTURE_ENDED:PINCH"], 1)
        self.assertEqual(extract.call_count, len(frames))
        self.assertEqual(detector.detect_for_video.call_count, len(frames))
        self.assertEqual(report["timings"]["controller_processing"]["count"], len(frames))
        self.assertEqual(report["timings_by_detected_hands"]["1"]["controller_processing"]["count"], len(frames))
        self.assertFalse(preview.call_args_list[0].kwargs["control_status"].armed)
        self.assertTrue(preview.call_args_list[1].kwargs["control_status"].armed)
        self.assertTrue(preview.call_args_list[2].args[3])
        self.assertFalse(report["controls"]["final_status"]["armed"])
        self.assertTrue(np.all(camera == 120))
        json.dumps(report, allow_nan=False)

    def test_real_swipe_engine_maps_once_without_changing_recognition(self):
        values = [0]*6+[.4, .8, 1.2, 1.6, 2., 2.]
        frames = [as_result(sample_hand(x, side="Right").observation) for x in values]
        c, report, *_ = self.pipeline(frames, [ord("a")]+[-1]*10+[ord("q")], ("--swipes", "--control-tabs"))
        self.assertEqual(c.backend.counts["tab"], 1)
        self.assertEqual(c.backend.last_keys, ("CTRL", "TAB"))
        self.assertEqual(report["swipes"]["confirmation_counts"], {"SWIPE_RIGHT": 1})

    def test_d_key_and_q_release_drag_without_fabricating_pinch_release(self):
        frames = [as_result(pinch_hand(r, side="Right")) for r in (.8, .8, .08, .08, .08)]
        c, report, *_ = self.pipeline(frames, [ord("a"), -1, -1, ord("d"), ord("q")], ("--control-mouse",))
        self.assertFalse(c.backend.button_down)
        self.assertEqual(c.backend.counts["up"], 1)
        self.assertNotIn("GESTURE_ENDED:PINCH", report["gesture_states"]["event_counts"])

    def test_missing_hand_releases_drag_and_requires_manual_rearm(self):
        frames = [as_result(pinch_hand(r, side="Right")) for r in (.8, .8, .08)]+[as_result(), as_result(pinch_hand(.08, side="Right"))]
        c, report, *_ = self.pipeline(frames, [ord("a"), -1, -1, -1, ord("q")], ("--control-mouse",))
        self.assertFalse(c.armed)
        self.assertFalse(c.backend.button_down)
        self.assertEqual(c.backend.counts["down"], 1)
        self.assertEqual(c.backend.counts["up"], 1)
        self.assertNotIn("GESTURE_ENDED:PINCH", report["gesture_states"]["event_counts"])

    def test_inference_exception_and_keyboard_interrupt_release_in_finally(self):
        for error in (RuntimeError("fake inference"), KeyboardInterrupt()):
            backend = SimulationBackend()
            c = DesktopController(backend)
            c.armed = c.button_down = backend.button_down = True
            with self.assertRaises(type(error)):
                self.pipeline([error], [-1], controller=c)
            self.assertFalse(c.armed)
            self.assertFalse(backend.button_down)

    def test_window_close_releases_and_returns(self):
        cap, detector = MagicMock(), MagicMock()
        cap.read.return_value = True, np.zeros((480, 640, 3), np.uint8)
        detector.detect_for_video.return_value = as_result()
        backend = SimulationBackend()
        c = DesktopController(backend)
        c.armed = c.button_down = backend.button_down = True
        mp = SimpleNamespace(Image=lambda **kw: kw["data"], ImageFormat=SimpleNamespace(SRGB=1))
        with patch.object(cv2, "imshow"), patch.object(cv2, "waitKey", return_value=-1), \
                patch.object(cv2, "getWindowProperty", return_value=0), self.assertLogs(tracker.LOGGER):
            self.assertEqual(tracker.process_frames(cap, detector, mp,
                             tracker.parse_args(FLAGS+["--gui-mode", "waitkey"]), controller=c), 0)
        self.assertFalse(backend.button_down)

    def test_status_overlay_is_white_on_black_clears_and_preserves_frame(self):
        backend = SimulationBackend()
        c = DesktopController(backend)
        image = np.full((1080, 1920, 3), 120, np.uint8)
        with patch.object(cv2, "putText", wraps=cv2.putText) as text:
            preview = make_preview(image, as_result(), 36., False, control_status=c.status())
        labels = [call.args[1] for call in text.call_args_list]
        self.assertTrue(any("SIMULATE" in s and "DISARMED" in s and "Right" in s for s in labels))
        self.assertTrue(any("LEFT UP" in s for s in labels))
        self.assertTrue(np.all(preview[27:81, :5] == 0))
        self.assertTrue(np.all(preview[90:] == 120))
        self.assertTrue(np.all(image == 120))
        fresh = make_preview(image, as_result(), 36., False)
        self.assertTrue(np.all(fresh[30:] == 120))

    def test_run_safety_failure_does_not_open_camera_or_model(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as temp:
            model = Path(temp)/"model.task"
            model.write_bytes(b"fake")
            args = tracker.parse_args(FLAGS+["--control-mode", "live", "--model", str(model)])
            with patch.object(cli, "create_controller", side_effect=OSError("global stop unavailable")), \
                    patch.object(tracker, "create_landmarker") as model_factory, \
                    patch.object(cv2, "VideoCapture") as camera, self.assertLogs(tracker.LOGGER, level="ERROR"):
                self.assertEqual(tracker.run(args), 1)
            model_factory.assert_not_called()
            camera.assert_not_called()


if __name__ == "__main__":
    unittest.main()
