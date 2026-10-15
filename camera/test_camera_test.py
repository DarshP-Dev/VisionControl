"""Hardware-independent checks: python -m unittest discover -s camera -v."""

from contextlib import redirect_stderr
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, MagicMock

import cv2
import numpy as np

import camera_test as camera


class CameraTest(unittest.TestCase):
    def test_argument_defaults_and_overrides(self):
        args = camera.parse_args([])
        self.assertEqual((args.camera_index, args.width, args.height, args.fps),
                         (0, 1920, 1080, 60.0))
        self.assertEqual(args.backend, "msmf")
        args = camera.parse_args(["--camera-index", "2", "--width", "640",
                                  "--height", "480", "--fps", "29.97", "--backend", "dshow"])
        self.assertEqual((args.camera_index, args.width, args.height, args.fps),
                         (2, 640, 480, 29.97))
        self.assertEqual(args.backend, "dshow")

    def test_invalid_arguments(self):
        for option, value in [("--camera-index", "-1"), ("--width", "0"),
                              ("--height", "-2"), ("--fps", "0"),
                              ("--fps", "nan"), ("--fps", "inf"),
                              ("--fps", "-1"), ("--width", "abc")]:
            with self.subTest(option=option, value=value), redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as raised:
                    camera.parse_args([option, value])
                self.assertEqual(raised.exception.code, 2)

    def test_rates_windows_and_partial_window(self):
        stats = camera.CaptureStats(0.0)
        for index in range(1, 121):
            rate = stats.record(index / 60, 1920, 1080)
        self.assertAlmostEqual(rate, 60.0)
        for index in range(1, 61):
            rate = stats.record(2 + index / 30, 1920, 1080)
        self.assertAlmostEqual(rate, 30.0)
        stats.record(4.5, 640, 480)
        self.assertEqual(stats.window_rates, [60.0, 30.0])
        self.assertAlmostEqual(stats.average(5), 181 / 5)
        self.assertEqual(stats.resolutions[(640, 480)], 1)

    def test_driver_fps_and_empty_summary(self):
        for value in (0, -1, float("nan"), float("inf")):
            self.assertIn("unavailable", camera.fps_text(value))
        self.assertIn("driver claim", camera.fps_text(60))
        with self.assertLogs(camera.LOGGER, level="INFO") as logs:
            camera.print_summary(camera.parse_args([]), camera.CaptureStats(1), 0, 1.5)
        output = "\n".join(logs.output)
        self.assertIn("no frames captured", output)
        self.assertIn("min/max unavailable", output)
        self.assertIn("Frames captured: 0", output)

    def test_preview_and_full_resolution_screenshots(self):
        frame = np.full((1080, 1920, 3), 120, dtype=np.uint8)
        preview = camera.preview_frame(frame, camera.parse_args([]), 60, 45, True)
        self.assertLessEqual(preview.shape[1], 1100)
        self.assertLessEqual(preview.shape[0], 650)
        self.assertTrue(np.all(frame == 120))
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as directory:
            target = Path(directory) / "captures"
            first = camera.save_screenshot(frame, target)
            second = camera.save_screenshot(frame, target)
            self.assertNotEqual(first, second)
            saved = cv2.imread(str(first))
            np.testing.assert_array_equal(saved, frame)
        with patch.object(camera.cv2, "imencode", return_value=(False, None)):
            with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as directory:
                with self.assertRaises(OSError):
                    camera.save_screenshot(frame, Path(directory))

    def test_mocked_camera_lifecycle(self):
        for opened, read_success in [(False, False), (True, False), (True, True)]:
            with self.subTest(opened=opened, read_success=read_success):
                cap = MagicMock()
                cap.isOpened.return_value = opened
                cap.set.return_value = False
                cap.get.return_value = 0.0
                cap.read.return_value = (read_success, np.zeros((480, 640, 3), dtype=np.uint8))
                with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as directory, \
                        patch.object(camera, "CAPTURES", Path(directory) / "captures"), \
                        patch.object(camera.cv2, "VideoCapture", return_value=cap) as factory, \
                        patch.object(camera.cv2, "namedWindow"), \
                        patch.object(camera.cv2, "imshow"), \
                        patch.object(camera.cv2, "waitKey", return_value=ord("Q")), \
                        patch.object(camera.cv2, "destroyAllWindows") as cleanup, \
                        self.assertLogs(camera.LOGGER, level="INFO"):
                    code = camera.run(camera.parse_args([]))
                self.assertEqual(code, 0 if opened and read_success else 1)
                factory.assert_called_once_with(0, cv2.CAP_MSMF)
                cap.release.assert_called_once()
                cleanup.assert_called_once()


if __name__ == "__main__":
    unittest.main()
