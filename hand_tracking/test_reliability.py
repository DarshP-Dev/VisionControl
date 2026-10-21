"""Profiling and safe failure handling without camera/model/Windows input."""

from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

import cv2
import numpy as np

from controls.backends import SimulationBackend
from controls.controller import DesktopController
from . import hand_tracker as tracker
from .benchmark_synthetic import measure, main as synthetic_main
from .performance import WorkloadProfile
from gestures.tests.static_fixtures import as_result


class ProfilingReliabilityTest(unittest.TestCase):
    def test_missing_stage_does_not_leak_prior_frame_into_another_hand_count(self):
        profile = WorkloadProfile()
        profile.add("controller_processing", .010)
        profile.finish_frame(2)
        profile.add("camera_read", .001)
        profile.finish_frame(0)
        self.assertNotIn("controller_processing", profile.workload_summary()["0"])
        self.assertEqual(profile.workload_summary()["2"]["controller_processing"]["count"], 1)

    def test_same_frame_calls_sum_and_finished_frame_cannot_be_counted_twice(self):
        profile = WorkloadProfile()
        profile.add("camera_read", .001)
        profile.add("camera_read", .002)
        profile.finish_frame(1)
        profile.finish_frame(1)
        result = profile.workload_summary()["1"]["camera_read"]
        self.assertEqual(result["count"], 1)
        self.assertAlmostEqual(result["mean_ms"], 3.)

    def test_warmup_and_disabled_frame_do_not_contaminate_measurements(self):
        profile = WorkloadProfile(enabled=False)
        profile.add("inference", 1.)
        profile.finish_frame(2)
        profile.enabled = True
        profile.add("inference", .002)
        profile.finish_frame(0)
        self.assertEqual(set(profile.workload_summary()), {"0"})
        self.assertEqual(profile.workload_summary()["0"]["inference"]["mean_ms"], 2.)

    def test_long_run_profile_memory_is_bounded_and_counts_are_complete(self):
        profile = WorkloadProfile(capacity=64)
        for i in range(10000):
            profile.add("frame_interval", .02+(i % 5)*.01)
            if i % 2:
                profile.add("controller_processing", .0001)
            profile.finish_frame(i % 3)
        self.assertEqual(profile.summary()["frame_interval"]["count"], 10000)
        self.assertEqual(profile.summary()["frame_interval"]["percentile_samples"], 64)
        self.assertEqual(profile._frame_stages, {})
        self.assertEqual(set(profile.by_hands), {0, 1, 2})
        self.assertEqual(sum(p.summary().get("controller_processing", {}).get("count", 0)
                             for p in profile.by_hands.values()), 5000)
        for group in profile.by_hands.values():
            self.assertTrue(all(len(stage["samples"]) <= 64 for stage in group.stages.values()))

    def test_synthetic_benchmark_is_virtual_only_and_reuses_report_schema(self):
        with patch("controls.windows.WindowsBackend") as windows, patch.object(cv2, "VideoCapture") as camera:
            for workload in ("static", "pinch", "swipes", "simulate-relative", "simulate-absolute"):
                for count in (0, 1, 2):
                    result = measure(workload, count, frames=4, warmup=2)
                    self.assertEqual(result["timings"]["gesture_features"]["count"], 4)
                    self.assertNotIn("average_application_fps", result)
            camera.assert_not_called()
            windows.assert_not_called()

    def test_synthetic_benchmark_refuses_invalid_parameters(self):
        for kwargs in ({"frames": 0}, {"warmup": -1}):
            with self.assertRaises(ValueError):
                measure("static", 1, **kwargs)
        with self.assertRaises(ValueError):
            measure("live", 1)

    def test_synthetic_cli_validates_arguments_and_preserves_existing_reports(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            path = Path(directory)/"synthetic.json"
            with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                synthetic_main(["--frames", "0", "--report", str(path)])
            with redirect_stdout(io.StringIO()):
                synthetic_main(["--frames", "4", "--warmup", "0", "--repeats", "1", "--report", str(path)])
            report = json.loads(path.read_text())
            self.assertEqual(report["kind"], "synthetic_only")
            self.assertEqual(len(report["runs"]), 15)
            original = path.read_bytes()
            with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                synthetic_main(["--report", str(path)])
            self.assertEqual(path.read_bytes(), original)


class FailureCleanupTest(unittest.TestCase):
    def test_read_inference_and_gui_failures_release_owned_button(self):
        for scenario in ("read", "inference", "gui", "window_close"):
            with self.subTest(scenario=scenario):
                cap, detector = MagicMock(), MagicMock()
                cap.read.return_value = scenario != "read", np.zeros((80, 100, 3), np.uint8)
                detector.detect_for_video.return_value = as_result()
                if scenario == "inference":
                    detector.detect_for_video.side_effect = RuntimeError("temporary inference failure; fail closed")
                backend = SimulationBackend()
                controller = DesktopController(backend)
                controller.button_down = backend.button_down = True
                mp = SimpleNamespace(Image=lambda **kw: kw["data"], ImageFormat=SimpleNamespace(SRGB=1))
                report = {}
                args = tracker.parse_args(["--gestures", "--pinch", "--gesture-states", "--controls", "--gui-mode", "waitkey"])
                with patch.object(cv2, "imshow", side_effect=RuntimeError("GUI failed") if scenario == "gui" else None), \
                        patch.object(cv2, "waitKey", return_value=-1), \
                        patch.object(cv2, "getWindowProperty", return_value=0), self.assertLogs(tracker.LOGGER):
                    if scenario == "window_close":
                        tracker.process_frames(cap, detector, mp, args, report, controller)
                    else:
                        with self.assertRaises((OSError, RuntimeError)):
                            tracker.process_frames(cap, detector, mp, args, report, controller)
                self.assertFalse(backend.button_down)
                self.assertFalse(controller.armed)
                self.assertNotIn("RELEASED", report["pinch"]["status_counts"])


if __name__ == "__main__":
    unittest.main()
