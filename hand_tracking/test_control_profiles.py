"""CLI, shared smoothed geometry, profile preview and application integration."""

from contextlib import ExitStack, redirect_stderr
import io
import unittest
from unittest.mock import patch

import cv2
import numpy as np

from controls import cli
from controls.models import ControlSettings
from controls.profiles import PROFILES
from controls.tests.profile_fixtures import ProfileRun
from gestures.tests.static_fixtures import as_result
from . import gesture_preview, hand_tracker as tracker, tracking_utils
from . import test_controls as application_tests
from .smoothing import LandmarkSmoother
from .performance import Profile


PALM = ["--control-gesture-profile", "palm-cursor"]
FLAGS = application_tests.FLAGS


class ProfileConfigurationTest(unittest.TestCase):
    def test_defaults_leave_legacy_and_existing_swipe_settings_unchanged(self):
        for flags in ([], FLAGS, FLAGS + ["--control-mode", "live"]):
            args = tracker.parse_args(flags)
            self.assertEqual(args.control_gesture_profile, "legacy")
            self.assertEqual(args.control_cursor_resume, "automatic")
            self.assertEqual(tracker.swipe_settings(args).pose, "open-palm")
        self.assertEqual(cli.settings(tracker.parse_args([])), ControlSettings())

    def test_palm_profile_selects_pointing_but_enables_no_extra_actions(self):
        args = tracker.parse_args(FLAGS + PALM)
        settings = cli.settings(args)
        self.assertEqual(settings.gesture_profile, "palm-cursor")
        self.assertEqual(tracker.swipe_settings(args).pose, "pointing")
        self.assertFalse(args.swipes)
        self.assertFalse(settings.mouse)
        self.assertFalse(settings.tabs)
        self.assertFalse(settings.gesture_rearm)

    def test_invalid_cli_combinations_fail_clearly(self):
        invalid = (PALM, FLAGS + ["--control-cursor-resume", "left-pinch"],
                   FLAGS + PALM + ["--control-cursor-resume", "left-pinch"],
                   FLAGS + PALM + ["--control-hand", "left"],
                   FLAGS + PALM + ["--swipe-pose", "open-palm"],
                   FLAGS + PALM + ["--swipe-pose", "open-palm-or-fist"],
                   FLAGS + ["--swipe-pose", "pointing"],
                   FLAGS + PALM + ["--control-cursor-resume", "invalid"],
                   FLAGS + PALM + ["--control-tabs"])
        for flags in invalid:
            with self.subTest(flags=flags), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                tracker.parse_args(flags)

    def test_all_documented_configuration_modes_validate_and_keep_mapping_defaults(self):
        for mode in ("simulate", "live"):
            for resume in ("automatic", "left-pinch"):
                flags = FLAGS + PALM + ["--control-mode", mode, "--control-cursor-resume", resume,
                        "--control-mapping", "absolute", "--control-region-width", ".80",
                        "--control-region-height", ".80", "--control-hand", "right",
                        "--control-gesture-rearm", "--control-rearm-hold-ms", "800",
                        "--control-emergency-hotkey", "ctrl+shift+f10", "--swipes", "--control-tabs"]
                settings = cli.settings(tracker.parse_args(flags))
                self.assertEqual(settings.cursor_resume, resume)
                self.assertTrue(settings.invert_x)
                self.assertEqual((settings.region_width, settings.region_height), (.8, .8))
                self.assertEqual((settings.rearm_hold_ms, settings.rearm_stable_ms), (800, 300))
                self.assertEqual(settings.emergency_hotkey, "ctrl+shift+f10")

    def test_simulation_factory_does_not_load_windows_backend(self):
        with patch("controls.windows.WindowsBackend") as windows, ExitStack() as resources:
            controller = cli.create_controller(tracker.parse_args(FLAGS + PALM), resources)
            self.assertIsNotNone(controller.interaction)
            self.assertFalse(controller.armed)
        windows.assert_not_called()


class ProfileApplicationTest(unittest.TestCase):
    def test_palm_anchor_uses_existing_ema_output_and_single_feature_extraction(self):
        r = ProfileRun()
        smoother = LandmarkSmoother()
        initial = as_result(*(f.observation for f in r.features()))
        moved = as_result(*(f.observation for f in r.features(dx=.03)))
        smoother.apply(initial, 10, (1080, 1920))
        displayed = smoother.apply(moved, 60, (1080, 1920))
        prepared = []
        with patch.object(gesture_preview, "extract_features", wraps=gesture_preview.extract_features) as extract:
            gesture_preview.classify_result(displayed, 60, r.features()[0].image_size, Profile(), features_out=prepared)
        anchor = PROFILES["palm-cursor"].anchor(prepared[1], 60)
        raw_anchor = PROFILES["palm-cursor"].anchor(r.features(dx=.03)[1], 60)
        self.assertNotEqual(anchor, raw_anchor)
        self.assertEqual(extract.call_count, 2)

    def test_application_pointing_swipe_and_open_return_use_existing_events_and_reports(self):
        r = ProfileRun()
        values = [("open", 0)] * 8 + [("point", 0)] * 8 + \
                 [("point", dx) for dx in (.4, .8, 1.2, 1.6, 2.)] + \
                 [("open", dx) for dx in (1.6, 1.2, .8, .4, 0)] + [("open", 0)] * 8
        frames = [as_result(*(f.observation for f in r.features(pose, dx))) for pose, dx in values]
        controller, report, preview, extract, _, detector = application_tests.ControlApplicationTest().pipeline(
            frames, [ord("a")] + [-1] * (len(frames) - 2) + [ord("q")],
            PALM + ["--control-mapping", "absolute", "--swipes", "--control-tabs"])
        self.assertEqual(controller.backend.counts["tab"], 1)
        self.assertEqual(controller.backend.counts["down"], 0)
        self.assertEqual(extract.call_count, 2 * len(frames))
        self.assertEqual(detector.detect_for_video.call_count, len(frames))
        self.assertEqual(report["controls"]["settings"]["gesture_profile"], "palm-cursor")
        self.assertEqual(report["controls"]["settings"]["cursor_resume"], "automatic")
        statuses = [call.kwargs["control_status"] for call in preview.call_args_list]
        self.assertTrue(any(s.armed and "SWIPE" in s.cursor_state for s in statuses))
        self.assertTrue(any(s.armed and s.cursor_state == "ACTIVE" for s in statuses[-8:]))
        self.assertFalse(report["controls"]["final_status"]["armed"])

    def test_manual_resume_in_full_fake_camera_pipeline_has_no_clicks(self):
        r = ProfileRun()
        observations = [("open", .8)] * 8 + [("point", .8)] * 5 + [("open", .8)] * 10 + \
                       [("open", .08)] * 20 + [("open", .8)] * 8
        frames = [as_result(*(f.observation for f in r.features(pose, left=left))) for pose, left in observations]
        controller, report, preview, *_ = application_tests.ControlApplicationTest().pipeline(
            frames, [ord("a")] + [-1] * (len(frames) - 2) + [ord("q")],
            PALM + ["--control-cursor-resume", "left-pinch", "--control-gesture-rearm", "--control-mouse"])
        states = [call.kwargs["control_status"] for call in preview.call_args_list]
        self.assertTrue(any(s.armed and "WAITING FOR LEFT PINCH" in s.cursor_state for s in states))
        self.assertTrue(any(s.armed and "RESUMING" in s.cursor_state for s in states))
        self.assertEqual(controller.backend.counts["down"], 0)
        self.assertEqual(controller.backend.counts["up"], 0)
        self.assertTrue(report["controls"]["settings"]["gesture_rearm"])

    def test_preview_shows_system_and_cursor_state_separately_without_mutating_source(self):
        r = ProfileRun(cursor_resume="left-pinch", gesture_rearm=True,
                       mode="live", emergency_hotkey="ctrl+shift+f10")
        r.arm()
        r.pause()
        source = np.full((480, 640, 3), 120, np.uint8)
        with patch.object(cv2, "putText", wraps=cv2.putText) as text:
            tracking_utils.make_preview(source, as_result(), 36., False, control_status=r.controller.status())
        labels = [call.args[1] for call in text.call_args_list]
        self.assertTrue(any("ARMED" in label for label in labels))
        self.assertTrue(any("PROFILE: PALM CURSOR" in label and "WAITING FOR LEFT PINCH" in label for label in labels))
        self.assertTrue(any("Ctrl+Shift+F10" in label for label in labels))
        self.assertTrue(np.all(source == 120))


if __name__ == "__main__":
    unittest.main()
