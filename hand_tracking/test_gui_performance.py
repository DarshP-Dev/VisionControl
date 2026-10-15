"""Phase 2.5 event-pump compatibility, workload profiling and headless checks."""

from contextlib import ExitStack, redirect_stderr
import io
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import cv2
import numpy as np

from . import hand_tracker as tracker
from .gui import GuiEvents
from .performance import WorkloadProfile, process_cpu_usage
from .test_two_hands import category, landmarks, result


class GuiEventsTest(unittest.TestCase):
    def test_auto_uses_one_native_poll_and_preserves_keys(self):
        with patch.object(cv2, "currentUIFramework", return_value="WIN32", create=True), \
                patch.object(cv2, "pollKey", side_effect=[ord("H"), ord("q"), -1], create=True) as poll, \
                patch.object(cv2, "waitKey") as wait:
            gui = GuiEvents()
            self.assertEqual([gui.read_key() for _ in range(3)], [ord("H"), ord("q"), 255])
        self.assertEqual(poll.call_count, 3)
        wait.assert_not_called()
        self.assertEqual(gui.metadata()["effective"], "pollkey")

    def test_waitkey_baseline_remains_available_on_win32(self):
        with patch.object(cv2, "currentUIFramework", return_value="WIN32", create=True), \
                patch.object(cv2, "pollKey", create=True) as poll, \
                patch.object(cv2, "waitKey", return_value=ord("Q")) as wait:
            gui = GuiEvents("waitkey")
            self.assertEqual(gui.read_key(), ord("Q"))
        wait.assert_called_once_with(1)
        poll.assert_not_called()

    def test_unsupported_or_unknown_gui_uses_waitkey(self):
        for backend in ("QT", "GTK3", "", None):
            with self.subTest(backend=backend), \
                    patch.object(cv2, "currentUIFramework", return_value=backend, create=True), \
                    patch.object(cv2, "pollKey", create=True) as poll, \
                    patch.object(cv2, "waitKey", return_value=-1) as wait:
                gui = GuiEvents()
                gui.read_key()
                self.assertEqual(gui.mode, "waitkey")
                wait.assert_called_once_with(1)
                poll.assert_not_called()

    def test_missing_native_api_and_explicit_poll_fallback(self):
        with patch.object(cv2, "currentUIFramework", return_value="WIN32", create=True), \
                patch.object(cv2, "pollKey", None, create=True), \
                self.assertLogs("hand_tracking", level="WARNING"):
            gui = GuiEvents("pollkey")
        self.assertEqual(gui.mode, "waitkey")
        self.assertIsNotNone(gui.fallback_reason)
        with patch.object(cv2, "currentUIFramework", None, create=True):
            self.assertEqual(GuiEvents().mode, "waitkey")

    def test_backend_query_error_and_poll_runtime_error_fall_back(self):
        with patch.object(cv2, "currentUIFramework", side_effect=cv2.error("no GUI"), create=True):
            self.assertEqual(GuiEvents().mode, "waitkey")
        with patch.object(cv2, "currentUIFramework", return_value="WIN32", create=True), \
                patch.object(cv2, "pollKey", side_effect=cv2.error("poll failed"), create=True) as poll, \
                patch.object(cv2, "waitKey", return_value=ord("q")) as wait, \
                self.assertLogs("hand_tracking", level="WARNING"):
            gui = GuiEvents()
            self.assertEqual(gui.read_key(), ord("q"))
            self.assertEqual(gui.read_key(), ord("q"))
        self.assertEqual(poll.call_count, 1)
        self.assertEqual(wait.call_count, 2)
        self.assertEqual(gui.api, "waitKey")
        self.assertEqual(gui.metadata()["effective"], "waitkey")

    def test_invalid_mode(self):
        with self.assertRaises(ValueError):
            GuiEvents("spin")

    def test_polling_pipeline_handles_help_quit_and_window_close(self):
        for keys, visible, expected_frames in (([ord("h"), ord("Q")], 1, 2), ([-1], 0, 1)):
            cap, detector, mp = MagicMock(), MagicMock(), MagicMock()
            cap.read.return_value = (True, np.zeros((80, 100, 3), dtype=np.uint8))
            detector.detect_for_video.return_value = result()
            report = {}
            with self.subTest(visible=visible), \
                    patch.object(cv2, "currentUIFramework", return_value="WIN32", create=True), \
                    patch.object(cv2, "pollKey", side_effect=keys, create=True), \
                    patch.object(cv2, "waitKey") as wait, \
                    patch.object(cv2, "imshow"), \
                    patch.object(cv2, "getWindowProperty", return_value=visible), \
                    patch.object(tracker, "make_preview", wraps=tracker.make_preview) as preview, \
                    self.assertLogs(tracker.LOGGER):
                self.assertEqual(tracker.process_frames(cap, detector, mp, report=report), 0)
            self.assertEqual(report["frames"], expected_frames)
            self.assertFalse(preview.call_args_list[0].args[3])
            if expected_frames == 2:
                self.assertTrue(preview.call_args_list[1].args[3])
            self.assertIn("pollKey", report["timings"])
            self.assertNotIn("waitKey", report["timings"])
            wait.assert_not_called()


class WorkloadProfileTest(unittest.TestCase):
    def test_independent_hand_count_timings_and_bounded_percentiles(self):
        profile = WorkloadProfile(capacity=2)
        for hands, latency in ((0, .010), (1, .020), (2, .030), (1, .040), (1, .060)):
            profile.add("inference", latency)
            profile.add("end_to_end", latency + .005)
            profile.finish_frame(hands)
        groups = profile.workload_summary()
        self.assertEqual(set(groups), {"0", "1", "2"})
        self.assertEqual(groups["1"]["inference"]["count"], 3)
        self.assertEqual(groups["1"]["inference"]["percentile_samples"], 2)
        self.assertAlmostEqual(groups["1"]["inference"]["mean_ms"], 40)
        self.assertAlmostEqual(groups["1"]["inference"]["p95_ms"], 59)
        self.assertAlmostEqual(groups["2"]["inference"]["mean_ms"], 30)
        self.assertAlmostEqual(groups["0"]["end_to_end"]["mean_ms"], 15)
        self.assertEqual(profile.summary()["inference"]["count"], 5)

    def test_workload_warmup_excluded_and_unmeasured_gui_absent(self):
        profile = WorkloadProfile(enabled=False)
        profile.add("inference", 1)
        profile.finish_frame(2)
        self.assertEqual(profile.workload_summary(), {})
        profile.enabled = True
        profile.add("inference", .02)
        profile.finish_frame(0)
        self.assertNotIn("gui_total", profile.workload_summary()["0"])

    def test_cpu_is_process_time_normalized_to_one_core(self):
        stats = process_cpu_usage(2.5, 1.0, 100)
        self.assertEqual(stats["process_cpu_percent_of_one_core"], 250)
        self.assertEqual(stats["process_cpu_ms_per_frame"], 25)
        self.assertEqual(stats["process_wall_seconds"], 1)
        empty = process_cpu_usage(0, 0, 0)
        self.assertIsNone(empty["process_cpu_percent_of_one_core"])
        self.assertIsNone(empty["process_cpu_ms_per_frame"])


class HeadlessBenchmarkTest(unittest.TestCase):
    def test_cli_requires_timed_benchmark_and_visible_raw_overlay(self):
        args = tracker.parse_args(["--benchmark", "--headless"])
        self.assertTrue(args.headless)
        self.assertEqual(args.gui_mode, "auto")
        for argv in (["--headless"], ["--benchmark", "--headless", "--show-raw-landmarks"],
                     ["--gui-mode", "spin"]):
            with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                tracker.parse_args(argv)

    def test_headless_pipeline_uses_model_and_smoothing_without_any_gui(self):
        now = 0.0
        frame = np.full((1080, 1920, 3), (10, 20, 30), dtype=np.uint8)
        cap, detector = MagicMock(), MagicMock()
        seen_counts = []

        def read():
            nonlocal now
            now += .1
            return True, frame

        def infer(image, timestamp):
            nonlocal now
            now += .02
            np.testing.assert_array_equal(image[0, 0], [30, 20, 10])
            count = len(seen_counts) % 3
            seen_counts.append(count)
            return result([landmarks(.2), landmarks(.8)][:count],
                          [[category("Left")], [category("Right")]][:count])

        cap.read.side_effect = read
        cap.isOpened.return_value = True
        cap.get.return_value = 0.0
        detector.detect_for_video.side_effect = infer
        mp = SimpleNamespace(Image=lambda **kwargs: kwargs["data"],
                             ImageFormat=SimpleNamespace(SRGB=1), __version__="mock")
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as directory:
            model = Path(directory) / "test.task"
            model.write_bytes(b"model stand-in")
            args = tracker.parse_args(["--model", str(model), "--benchmark", "--headless",
                                       "--warmup", ".2", "--duration", ".5"])
            report = {}
            with ExitStack() as stack:
                mocks = [stack.enter_context(patch.object(cv2, name, create=True)) for name in
                         ("namedWindow", "imshow", "waitKey", "pollKey", "getWindowProperty",
                          "destroyAllWindows", "currentUIFramework")]
                preview = stack.enter_context(patch.object(tracker, "make_preview"))
                stack.enter_context(patch.object(tracker, "create_landmarker", return_value=(mp, detector)))
                factory = stack.enter_context(patch.object(cv2, "VideoCapture", return_value=cap))
                stack.enter_context(patch.object(tracker.time, "perf_counter", side_effect=lambda: now))
                stack.enter_context(self.assertLogs(tracker.LOGGER))
                self.assertEqual(tracker.run(args, report), 0)
            for mock in mocks + [preview]:
                mock.assert_not_called()
        factory.assert_called_once_with(0, cv2.CAP_MSMF)
        cap.release.assert_called_once()
        detector.close.assert_called_once()
        self.assertEqual(report["status"], "completed")
        self.assertEqual(report["execution_mode"], "headless_tracking")
        self.assertEqual(report["gui"]["effective"], "none")
        self.assertAlmostEqual(report["average_application_fps"], 1 / .12)
        self.assertLess(report["frames"], cap.read.call_count)
        self.assertEqual(set(report["timings_by_detected_hands"]), {"0", "1", "2"})
        self.assertIn("smoothing", report["timings"])
        self.assertIn("frame_interval", report["timings"])
        self.assertNotIn("gui_total", report["timings"])
        self.assertNotIn("landmark_drawing", report["timings"])
        self.assertEqual(report["timings"]["inference"]["count"], report["frames"])


if __name__ == "__main__":
    unittest.main()
