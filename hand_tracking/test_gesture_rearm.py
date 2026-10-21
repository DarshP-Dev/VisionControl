"""Opt-in CLI, preview and full recognition pipeline with fake camera/GUI/input."""

from contextlib import ExitStack, redirect_stderr
import io
import unittest
from unittest.mock import patch

import cv2
import numpy as np

from controls import cli
from controls.controller import DesktopController
from controls.backends import SimulationBackend
from controls.models import ControlSettings
from controls.tests.rearm_fixtures import feature
from gestures.models import HandSide
from gestures.tests.static_fixtures import as_result
from . import hand_tracker as tracker, test_controls as application_tests, tracking_utils


FLAGS = ["--gestures", "--pinch", "--gesture-states", "--controls"]


class GestureRearmConfigurationTest(unittest.TestCase):
    def test_defaults_preserve_existing_commands_and_no_validator(self):
        for flags in ([], FLAGS, FLAGS+["--control-mode", "live"]):
            args = tracker.parse_args(flags)
            self.assertFalse(args.control_gesture_rearm)
            self.assertEqual(args.control_rearm_hold_ms, 800)
            self.assertEqual(args.control_rearm_stable_ms, 300)
            self.assertFalse(args.control_rearm_debug)
        c = DesktopController(SimulationBackend())
        self.assertIsNone(c.rearm)
        self.assertEqual(len(c.status().lines()), 2)

    def test_rearm_requires_controls_and_existing_gesture_dependencies(self):
        invalid = (["--control-gesture-rearm"], ["--controls", "--control-gesture-rearm"],
                   ["--controls", "--gestures", "--pinch", "--control-gesture-rearm"],
                   ["--controls", "--gestures", "--gesture-states", "--control-gesture-rearm"],
                   FLAGS+["--control-hand", "left", "--control-gesture-rearm"],
                   FLAGS+["--control-rearm-hold-ms", "1000"], FLAGS+["--control-rearm-stable-ms", "500"],
                   FLAGS+["--control-rearm-debug"])
        for flags in invalid:
            with self.subTest(flags=flags), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                tracker.parse_args(flags)

    def test_invalid_timing_bounds_and_types_rejected(self):
        for name, values in (("hold", ("0", "499", "3001", "nan", "800.0")),
                             ("stable", ("0", "149", "2001", "nan", "300.5"))):
            for value in values:
                with self.subTest(name=name, value=value), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                    tracker.parse_args(FLAGS+["--control-gesture-rearm", f"--control-rearm-{name}-ms", value])
        for settings in ({"rearm_hold_ms": True}, {"rearm_hold_ms": 800.}, {"rearm_stable_ms": False},
                         {"gesture_rearm": 1}, {"rearm_debug": 1},
                         {"gesture_rearm": True, "hand": HandSide.LEFT}):
            with self.subTest(settings=settings), self.assertRaises(ValueError):
                ControlSettings(**settings)

    def test_safe_boundaries_and_configuration_reach_controller(self):
        for hold, stable in ((500, 150), (800, 300), (3000, 2000)):
            args = tracker.parse_args(FLAGS+["--control-gesture-rearm", "--control-rearm-hold-ms", str(hold),
                                            "--control-rearm-stable-ms", str(stable), "--control-rearm-debug"])
            configured = cli.settings(args)
            self.assertTrue(configured.gesture_rearm)
            self.assertEqual(configured.rearm_hold_ms, hold)
            self.assertEqual(configured.rearm_stable_ms, stable)
            self.assertTrue(configured.rearm_debug)

    def test_full_live_command_parses_and_preserves_mapping_and_hotkey(self):
        args = tracker.parse_args(FLAGS+["--control-mode", "live", "--control-mapping", "absolute",
                                        "--control-region-width", "0.80", "--control-region-height", "0.80",
                                        "--control-hand", "right", "--control-mouse", "--control-gesture-rearm",
                                        "--control-rearm-hold-ms", "800", "--control-emergency-hotkey", "ctrl+shift+f10"])
        configured = cli.settings(args)
        self.assertEqual((configured.mapping, configured.region_width, configured.region_height), ("absolute", .8, .8))
        self.assertTrue(configured.invert_x)
        self.assertEqual(configured.emergency_hotkey, "ctrl+shift+f10")
        self.assertTrue(configured.mouse)

    def test_simulation_factory_never_constructs_live_safety_or_input(self):
        with patch("controls.windows.WindowsBackend") as windows, patch("controls.safety.GlobalSafety") as safety, \
                ExitStack() as resources:
            c = cli.create_controller(tracker.parse_args(FLAGS+["--control-gesture-rearm"]), resources)
            self.assertFalse(c.armed)
            self.assertIsNotNone(c.rearm)
            self.assertEqual(c.backend.counts, {})
        windows.assert_not_called()
        safety.assert_not_called()


class GestureRearmApplicationTest(unittest.TestCase):
    def test_full_pipeline_uses_existing_pinch_states_smoothing_and_features_while_disarmed(self):
        both = as_result(feature().observation, feature("Right").observation)
        lost = as_result(feature().observation)
        closed_left = as_result(feature(ratio=.08).observation, feature("Right").observation)
        frames = [both]*10+[lost]+[both]*12+[closed_left]*26+[both]*4
        keys = [ord("a"), ord("h")]+[-1]*(len(frames)-3)+[ord("q")]
        c, report, preview, extract, source, detector = application_tests.ControlApplicationTest().pipeline(
            frames, keys, ("--control-gesture-rearm", "--control-mouse", "--control-mapping", "absolute",
                           "--control-emergency-hotkey", "ctrl+shift+f10"))
        states = [call.kwargs["control_status"] for call in preview.call_args_list]
        self.assertFalse(states[0].armed)
        self.assertTrue(states[1].armed)
        self.assertTrue(any(not state.armed and "REARM" in state.rearm_status for state in states[12:]))
        self.assertTrue(any(state.armed and state.rearm_status == "REARMED" for state in states[24:]))
        self.assertEqual(c.backend.counts, {})  # Left pinch never clicks, moves or sends tabs.
        self.assertEqual(extract.call_count, sum(len(frame.hand_landmarks) for frame in frames))
        self.assertEqual(detector.detect_for_video.call_count, len(frames))
        self.assertEqual(report["timings"]["gesture_rearm"]["count"], len(frames))
        self.assertTrue(report["controls"]["settings"]["gesture_rearm"])
        self.assertFalse(report["controls"]["final_status"]["armed"])
        self.assertTrue(np.all(source == 120))

    def test_preview_reserves_one_feedback_row_without_stale_text_or_source_mutation(self):
        c = DesktopController(SimulationBackend(), ControlSettings(gesture_rearm=True))
        source = np.full((480, 640, 3), 120, np.uint8)
        result = as_result(feature().observation, feature("Right").observation)
        with patch.object(cv2, "putText", wraps=cv2.putText) as text, \
                patch.object(tracking_utils, "draw_hand", wraps=tracking_utils.draw_hand) as draw:
            preview = tracking_utils.make_preview(source, result, 36., False, control_status=c.status())
        self.assertTrue(any("GESTURE REARM BLOCKED" in call.args[1] for call in text.call_args_list))
        self.assertTrue(all(call.kwargs["top_margin"] == 108 for call in draw.call_args_list))
        self.assertTrue(np.all(preview[81:108, :5] == 0))
        self.assertTrue(np.all(source == 120))
        fresh = tracking_utils.make_preview(source, as_result(), 36., False)
        self.assertTrue(np.all(fresh[30:] == 120))


if __name__ == "__main__":
    unittest.main()
