from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import cv2

from .benchmark_rendering import main, measure
from .hand_tracker import parse_args


class RenderingBenchmarkTest(unittest.TestCase):
    def test_minimized_policy_skips_all_drawing_and_visible_states_keep_it(self):
        with patch("hand_tracking.benchmark_rendering.make_preview") as draw:
            new = measure(4, "minimized", "phase3_9", frames=3, warmup=2)
            draw.assert_not_called()
            self.assertEqual(new["rendered"], 0)
            for state in ("focused", "unfocused", "restored"):
                self.assertEqual(measure(2, state, "phase3_9", frames=3, warmup=0)["rendered"], 3)
            old = measure(4, "minimized", "phase3_8", frames=3, warmup=0)
            self.assertEqual(old["rendered"], 3)

    def test_report_is_synthetic_only_and_uses_no_camera_or_highgui(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as directory, \
                patch.object(cv2, "VideoCapture") as camera, patch.object(cv2, "imshow") as display, \
                patch("controls.windows.WindowsBackend") as windows, redirect_stdout(io.StringIO()):
            path = Path(directory)/"report.json"
            main(["--frames", "1", "--warmup", "0", "--repeats", "1", "--report", str(path)])
            report = json.loads(path.read_text())
            self.assertEqual(report["kind"], "synthetic_render_policy_only")
            self.assertEqual(len(report["runs"]), 32)
            camera.assert_not_called()
            display.assert_not_called()
            windows.assert_not_called()

    def test_profile_flag_is_opt_in_and_does_not_alter_camera_or_control_defaults(self):
        default, profile = parse_args([]), parse_args(["--performance-profile"])
        self.assertFalse(default.performance_profile)
        self.assertTrue(profile.performance_profile)
        for name in ("width", "height", "fps", "backend", "inference_resolution", "smoothing_alpha", "max_hands"):
            self.assertEqual(getattr(default, name), getattr(profile, name))
        self.assertFalse(profile.controls)


if __name__ == "__main__":
    unittest.main()
