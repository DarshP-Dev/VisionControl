"""Phase 2.3 checks for image preparation, profiling and timed synchronous runs."""

from contextlib import redirect_stderr
import io
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import cv2
import numpy as np

from . import hand_tracker as tracker
from .performance import InferenceInput, Profile, fit_size, write_report
from .tracking_utils import PreviewRenderer, hand_overlays, make_preview
from .test_two_hands import category, landmarks, result


class PerformanceTest(unittest.TestCase):
    def test_resolution_defaults_and_supported_configurations(self):
        self.assertIsNone(tracker.parse_args([]).inference_resolution)
        for value, expected in (("full", None), ("1280x720", (1280, 720)),
                                ("960x540", (960, 540)), ("640x360", (640, 360))):
            args = tracker.parse_args(["--inference-resolution", value])
            self.assertEqual(args.inference_resolution, expected)
            self.assertEqual((args.width, args.height, args.fps, args.backend),
                             (1920, 1080, 60, "msmf"))

    def test_invalid_resolutions_and_benchmark_values(self):
        for value in ("0x360", "-1x360", "960x0", "640", "960x540x3", "nanx360", "1.5x2"):
            with self.subTest(value=value), redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    tracker.parse_args(["--inference-resolution", value])
        for option, value in (("--warmup", "0"), ("--duration", "inf"), ("--duration", "-1")):
            with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                tracker.parse_args([option, value])

    def test_fit_preserves_aspect_without_upscaling(self):
        self.assertEqual(fit_size(1920, 1080, (960, 540)), (960, 540))
        self.assertEqual(fit_size(640, 480, (960, 540)), (640, 480))
        self.assertEqual(fit_size(1920, 1440, (960, 540)), (720, 540))
        self.assertEqual(fit_size(1080, 1920, (960, 540)), (304, 540))
        with self.assertRaises(ValueError):
            fit_size(0, 1080, None)

    def test_preparation_rgb_resolution_buffers_and_input_preservation(self):
        frame = np.full((1080, 1920, 3), (10, 20, 30), dtype=np.uint8)
        for bounds in (None, (1280, 720), (960, 540), (640, 360)):
            with self.subTest(bounds=bounds):
                converter = InferenceInput(bounds)
                profile = Profile()
                first = converter.prepare(frame, profile)
                self.assertEqual((first.shape[1], first.shape[0]), bounds or (1920, 1080))
                np.testing.assert_array_equal(first[0, 0], [30, 20, 10])
                self.assertIs(converter.prepare(frame, profile), first)
                self.assertEqual(profile.summary()["bgr_to_rgb"]["count"], 2)
                self.assertTrue(np.all(frame == (10, 20, 30)))
                if bounds is None:
                    self.assertIsNone(converter.resized)
        changed = converter.prepare(np.zeros((120, 160, 3), dtype=np.uint8), Profile())
        self.assertEqual(changed.shape, (120, 160, 3))

    def test_landmarks_do_not_depend_on_inference_pixel_dimensions(self):
        # Resize keeps the whole image and its aspect; model coordinates remain normalized.
        detection = result([landmarks(.25), landmarks(.75)], [[category("Left")], [category("Right")]])
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        expected = hand_overlays(detection, 1100, 619)
        for bounds in (None, (1280, 720), (960, 540), (640, 360)):
            InferenceInput(bounds).prepare(frame, Profile())
            self.assertEqual(hand_overlays(detection, 1100, 619), expected)

    def test_profile_percentiles_bounded_samples_and_all_run_totals(self):
        profile = Profile(capacity=3)
        for value in (1, 2, 3, 4, 5):
            profile.add("read", value / 1000)
        stage = profile.summary()["read"]
        self.assertEqual((stage["count"], stage["percentile_samples"]), (5, 3))
        self.assertAlmostEqual(stage["mean_ms"], 3)
        self.assertAlmostEqual(stage["p50_ms"], 4)
        self.assertAlmostEqual(stage["p95_ms"], 4.9)
        self.assertAlmostEqual(stage["max_ms"], 5)
        disabled = Profile(enabled=False)
        disabled.add("warmup", .1)
        self.assertEqual(disabled.summary(), {})
        for invalid in (-1, float("inf"), float("nan")):
            with self.assertRaises(ValueError):
                profile.add("invalid", invalid)

    def test_reused_preview_is_refreshed_when_hands_disappear(self):
        renderer = PreviewRenderer()
        frame = np.full((480, 640, 3), 120, dtype=np.uint8)
        detection = result([landmarks(.5)], [[category("Left")]])
        profile = Profile()
        drawn = make_preview(frame, detection, 30, False, renderer=renderer, timings=profile)
        self.assertFalse(np.all(drawn[30:] == 120))
        fresh = make_preview(frame, result(), 30, False, renderer=renderer, timings=profile)
        self.assertIs(fresh, drawn)
        self.assertTrue(np.all(fresh[30:] == 120))
        self.assertTrue(np.all(frame == 120))
        self.assertEqual(set(profile.summary()), {"preview_resize", "landmark_drawing", "text_overlay"})

    def test_json_sanitizes_invalid_readbacks_and_preserves_old_reports(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as directory:
            path = Path(directory) / "benchmarks" / "run.json"
            write_report(path, {"fps": float("nan"), "timings": {}})
            self.assertIsNone(json.loads(path.read_text())["fps"])
            with self.assertRaises(FileExistsError):
                write_report(path, {"overwritten": True})

    def test_timed_resized_tracking_excludes_warmup_and_counts_both_hands(self):
        now = 0.0
        frame = np.full((1080, 1920, 3), (10, 20, 30), dtype=np.uint8)
        cap, detector = MagicMock(), MagicMock()
        images, timestamps = [], []
        detection = result([landmarks(.2), landmarks(.8)], [[category("Left")], [category("Right")]])

        def read():
            nonlocal now
            now += .1
            return True, frame

        def infer(image, timestamp):
            nonlocal now
            now += .02
            images.append(image.copy())
            timestamps.append(timestamp)
            return detection

        def wait(delay):
            nonlocal now
            now += .005
            return -1

        cap.read.side_effect = read
        detector.detect_for_video.side_effect = infer
        mp = SimpleNamespace(Image=lambda **kwargs: kwargs["data"], ImageFormat=SimpleNamespace(SRGB=1))
        args = tracker.parse_args(["--benchmark", "--warmup", ".25", "--duration", ".5",
                                   "--inference-resolution", "640x360", "--gui-mode", "waitkey"])
        report = {}
        with patch.object(tracker.time, "perf_counter", side_effect=lambda: now), \
                patch.object(tracker.cv2, "imshow"), \
                patch.object(tracker.cv2, "waitKey", side_effect=wait), \
                patch.object(tracker.cv2, "getWindowProperty", return_value=1), \
                self.assertLogs(tracker.LOGGER):
            self.assertEqual(tracker.process_frames(cap, detector, mp, args, report), 0)
        self.assertEqual(report["status"], "completed")
        self.assertLess(report["frames"], cap.read.call_count)
        self.assertAlmostEqual(report["average_application_fps"], 8)
        self.assertEqual(report["detected_hands_frames"], {"2": report["frames"]})
        self.assertEqual(report["capture_resolution_frames"], {"1920x1080": report["frames"]})
        self.assertEqual(report["inference_resolution_frames"], {"640x360": report["frames"]})
        self.assertTrue(all(image.shape == (360, 640, 3) for image in images))
        np.testing.assert_array_equal(images[0][0, 0], [30, 20, 10])
        self.assertTrue(all(b > a for a, b in zip(timestamps, timestamps[1:])))
        self.assertEqual(report["timings"]["inference"]["count"], report["frames"])
        self.assertAlmostEqual(report["timings"]["inference"]["mean_ms"], 20)

    def test_quit_during_warmup_has_no_fabricated_fps(self):
        cap, detector, mp = MagicMock(), MagicMock(), MagicMock()
        cap.read.return_value = (True, np.zeros((80, 100, 3), dtype=np.uint8))
        detector.detect_for_video.return_value = result()
        report = {}
        with patch.object(tracker.cv2, "imshow"), \
                patch.object(tracker.cv2, "waitKey", return_value=ord("q")), \
                self.assertLogs(tracker.LOGGER):
            tracker.process_frames(cap, detector, mp,
                                   tracker.parse_args(["--benchmark", "--gui-mode", "waitkey"]), report)
        self.assertEqual(report["status"], "stopped")
        self.assertIsNone(report["average_application_fps"])
        self.assertEqual(report["timings"], {})

    def test_existing_report_is_rejected_before_camera_setup(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as directory:
            path = Path(directory) / "existing.json"
            path.write_text("{}", encoding="utf-8")
            with patch.object(tracker, "run") as run, self.assertLogs(tracker.LOGGER):
                self.assertEqual(tracker.main(["--report", str(path)]), 1)
            run.assert_not_called()
            self.assertEqual(path.read_text(), "{}")

    def test_interrupted_benchmark_saves_report_and_returns_nonzero(self):
        def interrupted(args, report):
            report.update(status="interrupted", frames=0)
            return 0

        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as directory:
            path = Path(directory) / "interrupted.json"
            with patch.object(tracker, "run", side_effect=interrupted), self.assertLogs(tracker.LOGGER):
                self.assertEqual(tracker.main(["--benchmark", "--report", str(path)]), 130)
            self.assertEqual(json.loads(path.read_text())["status"], "interrupted")


if __name__ == "__main__":
    unittest.main()
