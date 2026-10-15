"""Phase 2.1 checks without a physical camera or MediaPipe model execution."""

from contextlib import redirect_stderr
import io
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import cv2
import numpy as np

from . import hand_tracker as tracker
from .tracking_utils import (
    ApplicationFPS, FrameTimestamp, HAND_CONNECTIONS, landmark_pixels, make_preview,
)


class TrackingLogicTest(unittest.TestCase):
    def test_arguments_defaults_overrides_and_invalid_values(self):
        args = tracker.parse_args([])
        self.assertEqual((args.camera_index, args.width, args.height, args.fps, args.backend),
                         (0, 1920, 1080, 60.0, "msmf"))
        args = tracker.parse_args(["--camera-index", "2", "--width", "640", "--height", "480",
                                   "--fps", "30", "--backend", "dshow", "--model", "custom.task"])
        self.assertEqual((args.camera_index, args.width, args.height, args.fps, args.backend),
                         (2, 640, 480, 30.0, "dshow"))
        self.assertEqual(args.model, Path("custom.task"))
        for option, value in (("--camera-index", "-1"), ("--width", "0"), ("--height", "-1"),
                              ("--fps", "nan"), ("--fps", "inf"), ("--fps", "0"),
                              ("--backend", "bad"), ("--fourcc", "bad")):
            with self.subTest(option=option, value=value), redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    tracker.parse_args([option, value])

    def test_timestamp_collisions_and_clock_regression(self):
        clock = FrameTimestamp(10.0)
        values = [clock.next(now) for now in (10.0, 10.0, 10.0001, 10.020, 10.010)]
        self.assertEqual(values[:3], [0, 1, 2])
        self.assertTrue(all(b > a for a, b in zip(values, values[1:])))
        self.assertGreaterEqual(values[3], 19)  # tolerate binary floating point rounding

    def test_fps_uses_completed_loop_time(self):
        stats = ApplicationFPS(0.0)
        self.assertEqual(stats.average(0.0), 0)
        for index in range(1, 21):
            rate = stats.record(index / 10)
        self.assertAlmostEqual(rate, 10)
        self.assertAlmostEqual(stats.average(2.0), 10)
        self.assertIsNone(stats.record(2.1))

    def test_pixel_mapping_and_edge_clipping(self):
        landmarks = [SimpleNamespace(x=x, y=y) for x, y in ((0, 0), (1, 1), (.5, .5), (-.1, 1.2))]
        self.assertEqual(landmark_pixels(landmarks, 101, 51),
                         [(0, 0), (100, 50), (50, 25), (0, 50)])
        with self.assertRaises(ValueError):
            landmark_pixels([SimpleNamespace(x=float("nan"), y=0)], 100, 100)

    def test_preview_scales_skeleton_and_draws_all_twenty_one_points(self):
        frame = np.full((1080, 1920, 3), 120, dtype=np.uint8)
        landmarks = [SimpleNamespace(x=.5, y=.5)] * 21
        result = SimpleNamespace(hand_landmarks=[landmarks])
        with patch.object(cv2, "line") as line, patch.object(cv2, "circle") as circle:
            preview = make_preview(frame, result, 30, False)
        self.assertLessEqual(preview.shape[1], 1100)
        self.assertLessEqual(preview.shape[0], 650)
        self.assertEqual(line.call_count, len(HAND_CONNECTIONS))
        self.assertEqual(circle.call_count, 42)  # contrasting border + center per point
        expected = (round(.5 * (preview.shape[1] - 1)), round(.5 * (preview.shape[0] - 1)))
        self.assertEqual(line.call_args.args[1:3], (expected, expected))
        self.assertTrue(np.all(frame == 120))

    def test_no_hand_and_help_toggle(self):
        frame = np.full((480, 640, 3), 120, dtype=np.uint8)
        result = SimpleNamespace(hand_landmarks=[])
        normal = make_preview(frame, result, None, False)
        help_preview = make_preview(frame, result, None, True)
        self.assertTrue(np.all(normal[35:] == frame[35:]))
        self.assertFalse(np.array_equal(normal, help_preview))


class TrackingLifecycleTest(unittest.TestCase):
    def test_missing_model_does_not_open_camera(self):
        args = tracker.parse_args(["--model", "definitely-missing-model.task"])
        with patch.object(tracker.cv2, "VideoCapture") as capture, \
                self.assertLogs(tracker.LOGGER, level="ERROR") as logs:
            self.assertEqual(tracker.run(args), 1)
        capture.assert_not_called()
        self.assertIn("hand_tracking.download_model", "\n".join(logs.output))

    def test_rgb_inference_keys_errors_and_resource_cleanup(self):
        for scenario in ("quit", "no_camera", "bad_read", "infer_error", "interrupt", "bad_model"):
            with self.subTest(scenario=scenario), tempfile.TemporaryDirectory(
                    dir=Path(__file__).resolve().parent) as directory:
                model = Path(directory) / "model.task"
                model.write_bytes(b"test model stand-in")
                args = tracker.parse_args(["--model", str(model)])
                cap = MagicMock()
                cap.isOpened.return_value = scenario != "no_camera"
                cap.get.return_value = 0.0
                frame = np.full((80, 100, 3), (10, 20, 30), dtype=np.uint8)
                cap.read.return_value = (scenario != "bad_read", frame)
                detector = MagicMock()
                detector.detect_for_video.return_value = SimpleNamespace(hand_landmarks=[])
                if scenario == "infer_error":
                    detector.detect_for_video.side_effect = RuntimeError("inference failed")
                if scenario == "interrupt":
                    detector.detect_for_video.side_effect = KeyboardInterrupt()
                mp = MagicMock()
                constructor_error = ValueError("invalid bundle") if scenario == "bad_model" else None
                with patch.object(tracker, "create_landmarker", return_value=(mp, detector),
                                  side_effect=constructor_error), \
                        patch.object(tracker.cv2, "VideoCapture", return_value=cap) as factory, \
                        patch.object(tracker.cv2, "namedWindow"), \
                        patch.object(tracker.cv2, "imshow"), \
                        patch.object(tracker.cv2, "getWindowProperty", return_value=1), \
                        patch.object(tracker.cv2, "waitKey", side_effect=[ord("h"), ord("q")]), \
                        patch.object(tracker.cv2, "destroyAllWindows") as cleanup, \
                        self.assertLogs(level="INFO"):
                    self.assertEqual(tracker.run(args), 0 if scenario in ("quit", "interrupt") else 1)
                if scenario == "bad_model":
                    factory.assert_not_called()
                    continue
                factory.assert_called_once_with(0, cv2.CAP_MSMF)
                cap.release.assert_called_once()
                detector.close.assert_called_once()
                if scenario == "no_camera":
                    cleanup.assert_not_called()
                else:
                    cleanup.assert_called_once()
                if scenario == "quit":
                    rgb = mp.Image.call_args.kwargs["data"]
                    np.testing.assert_array_equal(rgb[0, 0], [30, 20, 10])
                    timestamps = [call.args[1] for call in detector.detect_for_video.call_args_list]
                    self.assertEqual(len(timestamps), 2)
                    self.assertGreater(timestamps[1], timestamps[0])

    def test_landmarker_options_are_video_cpu_and_two_hands(self):
        import mediapipe as mp

        with patch.object(mp.tasks.vision.HandLandmarker, "create_from_options") as factory:
            tracker.create_landmarker(Path("not-loaded-by-mock.task"))
        options = factory.call_args.args[0]
        self.assertEqual(options.running_mode, mp.tasks.vision.RunningMode.VIDEO)
        self.assertEqual(options.num_hands, 2)
        self.assertEqual(options.base_options.delegate, mp.tasks.BaseOptions.Delegate.CPU)


if __name__ == "__main__":
    unittest.main()
