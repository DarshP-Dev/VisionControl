from argparse import Namespace
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import cv2

from camera import benchmark_delivery
from . import benchmark_capture


class CaptureBenchmarkTest(unittest.TestCase):
    def test_synthetic_both_modes_use_no_camera_gui_or_windows_backend(self):
        with patch.object(cv2, "VideoCapture") as camera, patch.object(cv2, "imshow") as gui, \
                patch("controls.windows.WindowsBackend") as windows:
            for mode in ("sync", "latest-thread"):
                report = benchmark_capture.measure(mode, frames=4, warmup=1, read_seconds=.002, processing_seconds=.004)
                self.assertEqual(report["frames"], 4)
                self.assertIn("frame_interval", report["timings"])
                self.assertGreater(report["synthetic_completed_iterations_per_second"], 0)
                if mode == "latest-thread":
                    self.assertEqual(report["capture"]["max_buffer_occupancy"], 1)
                    self.assertFalse(report["capture"]["worker_alive"])
                    self.assertTrue(report["capture"]["release_completed"])
            camera.assert_not_called()
            gui.assert_not_called()
            windows.assert_not_called()

    def test_camera_only_failure_report_has_no_images_and_releases(self):
        cap = MagicMock()
        cap.isOpened.return_value = False
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as directory, \
                patch.object(cv2, "VideoCapture", return_value=cap), redirect_stdout(io.StringIO()):
            path = Path(directory)/"failure.json"
            self.assertEqual(benchmark_delivery.main(["--duration", ".01", "--report", str(path)]), 1)
            report = json.loads(path.read_text())
            self.assertEqual(report["status"], "error")
            self.assertEqual(report["kind"], "camera_only_host_delivery")
            self.assertIsNone(report["sensor_exposure_age_ms"])
            self.assertIsNone(report["capture_only_consumer_fps"])
            cap.release.assert_called_once()

    def test_synthetic_cli_writes_numeric_report_and_preserves_existing_file(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as directory, redirect_stdout(io.StringIO()):
            path = Path(directory)/"synthetic.json"
            args = ["--frames", "2", "--warmup", "0", "--repeats", "1", "--read-ms", "1",
                    "--processing-ms", "1", "--report", str(path)]
            benchmark_capture.main(args)
            original = path.read_bytes()
            self.assertEqual(json.loads(original)["kind"], "synthetic_blocking_call_overlap")
            from contextlib import redirect_stderr
            with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                benchmark_capture.main(args)
            self.assertEqual(path.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
