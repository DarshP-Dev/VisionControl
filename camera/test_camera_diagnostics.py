"""Diagnostic tests with a synthetic camera and controlled monotonic clock."""

from contextlib import redirect_stderr
import io
import unittest
from unittest.mock import MagicMock, patch

import cv2
import numpy as np

import camera_diagnostics as diagnostics
import camera_test as camera


class DiagnosticTest(unittest.TestCase):
    def setUp(self):
        self.frame = np.zeros((480, 640, 3), dtype=np.uint8)
        self.now = 0.0

    def clock(self):
        return self.now

    def fake_camera(self):
        cap = MagicMock()
        cap.isOpened.return_value = True
        cap.set.return_value = True
        cap.getBackendName.return_value = "MSMF"
        properties = {cv2.CAP_PROP_FRAME_WIDTH: 640, cv2.CAP_PROP_FRAME_HEIGHT: 480,
                      cv2.CAP_PROP_FPS: 60,
                      cv2.CAP_PROP_FOURCC: cv2.VideoWriter_fourcc(*"MJPG")}
        cap.get.side_effect = lambda prop: properties[prop]

        def read():
            self.now += 0.2
            return True, self.frame

        cap.read.side_effect = read
        return cap

    def args(self):
        return camera.parse_args(["--benchmark", "--warmup", "0.4", "--duration", "0.5"])

    def test_diagnostic_arguments(self):
        args = camera.parse_args(["--backend", "msmf", "--fourcc", "YUY2", "--compare-modes"])
        self.assertEqual((args.backend, args.fourcc, args.compare_modes), ("msmf", "YUY2", True))
        for argv in (["--warmup", "0"], ["--duration", "nan"], ["--backend", "bad"],
                     ["--fourcc", "bad"], ["--benchmark", "--compare-modes"]):
            with self.subTest(argv=argv), redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    camera.parse_args(argv)

    def test_fourcc_decoding_and_invalid_readbacks(self):
        self.assertEqual(diagnostics.fourcc_text(cv2.VideoWriter_fourcc(*"YUY2")), "YUY2")
        for value in (0, -1, float("nan"), float("inf"), 2**32):
            self.assertEqual(diagnostics.fourcc_text(value), "unavailable")

    def test_acceptance_does_not_hide_mismatched_readbacks(self):
        cap = self.fake_camera()
        args = self.args()
        args.fourcc = "YUY2"
        with self.assertLogs(diagnostics.LOGGER, level="INFO") as logs:
            accepted = diagnostics.configure_capture(cap, args)
            snapshot = diagnostics.capture_snapshot(cap, args, "Test", (640, 480))
        self.assertTrue(all(accepted.values()))
        self.assertEqual(snapshot["fourcc"], "MJPG")
        self.assertIn("differs from readback", "\n".join(logs.output))
        self.assertIn("Actual frame dimensions differ", "\n".join(logs.output))
        cap.set.side_effect = cv2.error("unsupported setting")
        with self.assertLogs(diagnostics.LOGGER):
            self.assertFalse(any(diagnostics.configure_capture(cap, args).values()))

    def test_timing_aggregation(self):
        timings = diagnostics.StageTimings()
        timings.add("read", 0.1)
        timings.add("read", 0.3)
        with self.assertLogs(diagnostics.LOGGER, level="INFO") as logs:
            timings.report()
        self.assertIn("mean 200.000 ms / max 300.000 ms / 2 calls", logs.output[0])

    def test_unavailable_properties_do_not_abort_diagnostics(self):
        cap = self.fake_camera()
        cap.get.side_effect = cv2.error("unsupported readback")
        cap.getBackendName.side_effect = cv2.error("backend unknown")
        with self.assertLogs(diagnostics.LOGGER) as logs:
            snapshot = diagnostics.capture_snapshot(cap, self.args(), "Test", (640, 480))
        self.assertEqual(snapshot["fourcc"], "unavailable")
        self.assertIn("Driver FPS is unavailable", "\n".join(logs.output))

    def test_preview_profiles_resize_and_overlay_without_changing_capture(self):
        frame = np.full((480, 640, 3), 120, dtype=np.uint8)
        timings = diagnostics.StageTimings()
        preview = camera.preview_frame(frame, self.args(), 60, 5, True, timings)
        self.assertEqual(set(timings.stages), {"resize", "overlay"})
        self.assertTrue(np.all(frame == 120))
        self.assertTrue(np.all(preview[0, :] == 0))
        self.assertTrue(np.any(preview[:200] == 255))

    def test_mode_status_marks_fallbacks(self):
        args = self.args()
        result = diagnostics.BenchmarkResult(
            dimensions=(args.width, args.height), accepted={"FPS": True},
            snapshot={"fps": args.fps, "backend": "MSMF", "fourcc": "MJPG"})
        self.assertEqual(result.mode_status(args), "readbacks agree (unverified)")
        result.snapshot["fourcc"] = "YUY2"
        self.assertIn("MISMATCH", result.mode_status(args))
        self.assertIn("UNKNOWN", diagnostics.BenchmarkResult().mode_status(args))

    def test_headless_excludes_warmup_and_never_uses_gui(self):
        cap = self.fake_camera()
        with patch.object(diagnostics.cv2, "VideoCapture", return_value=cap) as factory, \
                patch.object(diagnostics.time, "perf_counter", side_effect=self.clock), \
                patch.object(diagnostics.cv2, "namedWindow") as window, \
                patch.object(diagnostics.cv2, "resize") as resize, \
                patch.object(diagnostics.cv2, "putText") as overlay, \
                patch.object(diagnostics.cv2, "imshow") as show, \
                patch.object(diagnostics.cv2, "waitKey") as wait, \
                patch.object(camera, "save_screenshot") as save, \
                self.assertLogs(diagnostics.LOGGER):
            result = diagnostics.benchmark(self.args())
        self.assertIsNone(result.error)
        factory.assert_called_once_with(0, cv2.CAP_MSMF)
        self.assertEqual(result.frames, 3)
        self.assertEqual(cap.read.call_count, 5)  # two discarded warm-up frames
        self.assertAlmostEqual(result.duration, 0.6)
        self.assertAlmostEqual(result.fps, 5.0)
        for operation in (window, resize, overlay, show, wait, save):
            operation.assert_not_called()
        cap.release.assert_called_once()

    def test_release_on_open_failure_read_failure_and_interrupt(self):
        for failure in ("open", "read", "interrupt"):
            with self.subTest(failure=failure):
                cap = self.fake_camera()
                cap.isOpened.return_value = failure != "open"
                if failure != "open":
                    cap.read.side_effect = KeyboardInterrupt() if failure == "interrupt" else cv2.error("read failed")
                with patch.object(diagnostics.cv2, "VideoCapture", return_value=cap), \
                        patch.object(diagnostics.time, "perf_counter", side_effect=self.clock), \
                        self.assertLogs(diagnostics.LOGGER):
                    if failure == "interrupt":
                        with self.assertRaises(KeyboardInterrupt):
                            diagnostics.benchmark(self.args())
                    else:
                        self.assertIsNotNone(diagnostics.benchmark(self.args()).error)
                cap.release.assert_called_once()

    def test_comparison_is_sequential_and_covers_twenty_requests(self):
        opened = False
        handles = []

        def factory(index, backend):
            nonlocal opened
            self.assertFalse(opened, "Previous handle must be released before opening another")
            opened = True
            cap = self.fake_camera()

            def release():
                nonlocal opened
                opened = False

            cap.release.side_effect = release
            handles.append(cap)
            return cap

        args = self.args()
        original = vars(args).copy()
        with patch.object(diagnostics.cv2, "VideoCapture", side_effect=factory) as create, \
                patch.object(diagnostics.time, "perf_counter", side_effect=self.clock), \
                self.assertLogs(diagnostics.LOGGER):
            self.assertEqual(diagnostics.compare_modes(args), 0)
        self.assertFalse(opened)
        self.assertEqual(len(handles), 20)
        self.assertEqual(vars(args), original)
        requests = set()
        for call, cap in zip(create.call_args_list, handles):
            values = [entry.args[1] for entry in cap.set.call_args_list]
            requests.add((call.args[1], *values))
            cap.release.assert_called_once()
        self.assertEqual(len(requests), 20)


if __name__ == "__main__":
    unittest.main()
