"""Absolute controls integration with fake camera/inference/GUI and virtual input."""

from contextlib import ExitStack, redirect_stderr
import io
import json
import unittest
from unittest.mock import patch

import cv2
import numpy as np

from controls import cli
from controls.backends import SimulationBackend
from controls.controller import DesktopController
from controls.models import ControlSettings
from gestures.tests.pinch_fixtures import pinch_hand
from gestures.tests.static_fixtures import as_result
from . import hand_tracker as tracker, test_controls as existing
from .tracking_utils import make_preview


FLAGS = ["--gestures", "--pinch", "--gesture-states", "--controls"]


class AbsoluteApplicationTest(unittest.TestCase):
    def test_cli_defaults_and_configurable_region_both_modes(self):
        args = tracker.parse_args([])
        self.assertEqual((args.control_mapping, args.control_region_width, args.control_region_height),
                         ("relative", .8, .8))
        self.assertFalse(args.control_invert_x)
        for mode in ("simulate", "live"):
            args = tracker.parse_args(FLAGS+["--control-mode", mode, "--control-mapping", "absolute",
                                            "--control-region-width", ".9", "--control-region-height", ".7",
                                            "--control-invert-x"])
            settings = cli.settings(args)
            self.assertEqual((settings.mapping, settings.region_width, settings.region_height), ("absolute", .9, .7))
            self.assertTrue(settings.invert_x)

    def test_invalid_cli_regions_mapping_and_missing_dependencies(self):
        invalid = [["--control-mapping", "absolute"], ["--control-region-height", ".7"],
                   FLAGS+["--control-mapping", "invalid"],
                   FLAGS+["--control-mapping", "absolute", "--headless", "--benchmark"],
                   FLAGS+["--control-mapping", "absolute", "--no-smoothing"]]
        for option in ("--control-region-width", "--control-region-height"):
            invalid += [FLAGS+[option, value] for value in ("0", "-.1", "1.01", "nan", "inf")]
        for flags in invalid:
            with self.subTest(flags=flags), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                tracker.parse_args(flags)

    def test_documented_launch_configurations_parse(self):
        for mode, mapping, height in (("simulate", "relative", ".8"), ("simulate", "absolute", ".8"),
                                      ("live", "absolute", ".8"), ("simulate", "absolute", ".7")):
            args = tracker.parse_args(FLAGS+["--control-mode", mode, "--control-mapping", mapping,
                                            "--control-region-width", ".8", "--control-region-height", height,
                                            "--control-hand", "right", "--control-mouse", "--control-debug"])
            self.assertEqual(cli.settings(args).mapping, mapping)

    def test_absolute_simulation_factory_never_loads_windows_input(self):
        with patch("controls.windows.WindowsBackend") as windows, ExitStack() as resources:
            controller = cli.create_controller(tracker.parse_args(FLAGS+["--control-mapping", "absolute"]), resources)
            self.assertFalse(controller.armed)
            self.assertEqual(controller.status().mapping, "absolute")
            self.assertEqual(controller.status().region.width, .8)
        windows.assert_not_called()

    def test_active_region_overlay_uses_preview_scale_and_preserves_capture(self):
        controller = DesktopController(SimulationBackend(), ControlSettings(mapping="absolute"))
        for width, height in ((1920, 1080), (640, 480), (1080, 1920)):
            image = np.full((height, width, 3), 120, np.uint8)
            with patch.object(cv2, "rectangle", wraps=cv2.rectangle) as rectangle, \
                    patch.object(cv2, "putText", wraps=cv2.putText) as text:
                preview = make_preview(image, as_result(), 36., False, control_status=controller.status())
            expected = controller.cursor.region.preview_bounds(preview.shape[1], preview.shape[0])
            self.assertEqual(rectangle.call_args_list[0].args[1:3], expected)
            self.assertEqual(rectangle.call_args_list[0].args[3], (0, 220, 255))
            self.assertTrue(any("ABSOLUTE" in call.args[1] for call in text.call_args_list))
            self.assertTrue(np.all(image == 120))

    def test_relative_and_disabled_controls_do_not_draw_region(self):
        image = np.full((480, 640, 3), 120, np.uint8)
        for status in (None, DesktopController(SimulationBackend()).status()):
            with patch.object(cv2, "rectangle", wraps=cv2.rectangle) as rectangle:
                make_preview(image, as_result(), 36., False, control_status=status)
            rectangle.assert_not_called()

    def test_real_pinch_pipeline_simulates_drag_without_extra_inference(self):
        frames = [as_result(pinch_hand(ratio, side="Right", offset=offset)) for ratio, offset in
                  ((.8, 0), (.8, 0), (.08, 0), (.08, .01), (.08, .02), (.8, .02))]
        helper = existing.ControlApplicationTest()
        controller, report, preview, extract, camera, detector = helper.pipeline(
            frames, [ord("a"), ord("h"), -1, -1, -1, ord("q")],
            ("--control-mapping", "absolute", "--control-mouse", "--control-invert-x"))
        self.assertEqual(controller.backend.counts["down"], 1)
        self.assertEqual(controller.backend.counts["up"], 1)
        self.assertGreater(controller.backend.counts["move"], 0)
        self.assertEqual(extract.call_count, len(frames))
        self.assertEqual(detector.detect_for_video.call_count, len(frames))
        self.assertEqual(report["timings"]["controller_processing"]["count"], len(frames))
        self.assertEqual(report["controls"]["settings"]["mapping"], "absolute")
        self.assertIn("absolute", report["controls"]["mapping"])
        self.assertEqual(preview.call_args.kwargs["control_status"].mapping, "absolute")
        self.assertTrue(np.all(camera == 120))
        json.dumps(report, allow_nan=False)

    def test_mapping_choice_does_not_change_recognition_events(self):
        frames = [as_result(pinch_hand(ratio, side="Right")) for ratio in (.8, .8, .08, .08, .8)]
        helper = existing.ControlApplicationTest()
        reports = []
        for mapping in ("relative", "absolute"):
            _, report, *_ = helper.pipeline(frames, [ord("a"), -1, -1, -1, ord("q")],
                                            ("--control-mapping", mapping, "--control-mouse"))
            reports.append(report["gesture_states"]["event_counts"])
        self.assertEqual(reports[0], reports[1])


if __name__ == "__main__":
    unittest.main()
