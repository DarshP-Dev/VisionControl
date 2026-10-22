"""Experimental bridge, bounded IDs, independent gestures and observation-only UI."""

from contextlib import ExitStack, redirect_stderr
from copy import deepcopy
from dataclasses import replace
import io
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

import cv2
import numpy as np

from controls import cli as control_cli
from gestures.events import SWIPES, EventType as E
from gestures.pinch import PinchTracker, PinchThresholds
from gestures.state_machine import GestureStateManager
from gestures.static_gestures import Gesture as G
from gestures.tests.static_fixtures import SIZE, as_result
from . import hand_tracker as tracker, multi_hand, tracking_utils
from .benchmark_synthetic import measure
from .multi_hand import TrackedPipeline
from .multi_hand_fixtures import four, hand
from .performance import Profile, WorkloadProfile


FLAGS = ["--max-hands", "4", "--gestures", "--pinch", "--gesture-states", "--swipes"]
CONTROLS = ["--controls", "--gestures", "--pinch", "--gesture-states"]


def pipeline(flags=FLAGS):
    args = tracker.parse_args(flags)
    return TrackedPipeline(args, PinchTracker(PinchThresholds(args.pinch_activation, args.pinch_release)) if args.pinch else None,
                           GestureStateManager(tracker.state_settings(args), swipe_settings=tracker.swipe_settings(args)
                                               if args.swipes else None) if args.gesture_states else None)


class MultiHandConfigurationTest(unittest.TestCase):
    def test_maximum_is_validated_and_default_camera_inference_settings_preserved(self):
        args = tracker.parse_args([])
        self.assertEqual(args.max_hands, 2)
        self.assertFalse(args.track_ids or args.multi_hand_debug)
        self.assertEqual((args.backend, args.width, args.height, args.fps, args.inference_resolution),
                         ("msmf", 1920, 1080, 60., None))
        for value in ("0", "5", "2.5", "-1", "True"):
            with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                tracker.parse_args(["--max-hands", value])

    def test_model_options_use_exact_requested_maximum_without_loading_camera(self):
        import mediapipe as mp
        for maximum in (1, 2, 3, 4):
            with patch.object(mp.tasks.vision.HandLandmarker, "create_from_options") as factory:
                tracker.create_landmarker(Path("unused.task"), maximum)
            options = factory.call_args.args[0]
            self.assertEqual(options.num_hands, maximum)
            self.assertEqual(options.running_mode, mp.tasks.vision.RunningMode.VIDEO)
            self.assertEqual(options.base_options.delegate, mp.tasks.BaseOptions.Delegate.CPU)

    def test_invalid_factory_maximum_rejected(self):
        for maximum in (0, 5, 2., True, "4"):
            with self.assertRaises(ValueError):
                tracker.create_landmarker(Path("unused.task"), maximum)

    def test_multi_hand_controls_rejected_including_simulation_and_both_profiles(self):
        for maximum in (3, 4):
            for mode in ("simulate", "live"):
                for profile in ("legacy", "palm-cursor"):
                    with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                        tracker.parse_args(CONTROLS + ["--max-hands", str(maximum), "--control-mode", mode,
                                                       "--control-gesture-profile", profile])
        for flags in (CONTROLS + ["--track-ids"], CONTROLS + ["--max-hands", "1", "--control-gesture-rearm"]):
            with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                tracker.parse_args(flags)

    def test_single_and_two_hand_desktop_profiles_remain_valid(self):
        for maximum in (1, 2):
            for profile in ("legacy", "palm-cursor"):
                self.assertTrue(tracker.parse_args(CONTROLS + ["--max-hands", str(maximum),
                                                             "--control-gesture-profile", profile]).controls)

    def test_direct_controller_factory_cannot_bypass_observation_only_policy(self):
        args = tracker.parse_args(CONTROLS)
        args.max_hands = 4
        with patch("controls.windows.WindowsBackend") as windows, ExitStack() as resources, self.assertRaises(ValueError):
            control_cli.create_controller(args, resources)
        windows.assert_not_called()
        with self.assertRaises(ValueError):
            tracker.process_frames(None, None, None, args)

    def test_debug_needs_identity_mode_and_does_not_enable_recognition_or_actions(self):
        args = tracker.parse_args(["--max-hands", "4", "--multi-hand-debug"])
        self.assertFalse(args.controls or args.gestures or args.pinch or args.swipes)
        self.assertIsNotNone(pipeline(["--max-hands", "2", "--track-ids", "--multi-hand-debug"]).debug)
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            tracker.parse_args(["--multi-hand-debug"])


class MultiHandRecognitionTest(unittest.TestCase):
    def test_four_hands_classify_independently_and_extract_features_once_each(self):
        p = pipeline()
        observations = (hand(.15, pose="open"), hand(.37, pose="fist"), hand(.59, pose="point"), hand(.81))
        raw = as_result(*observations)
        before = deepcopy(raw)
        with patch.object(multi_hand, "extract_features", wraps=multi_hand.extract_features) as extract:
            _, static, _, _ = p.update(raw, 0, SIZE, Profile())
        self.assertEqual([x.gesture for x in static], [G.OPEN_PALM, G.FIST, G.POINTING, G.OPEN_PALM])
        self.assertEqual(extract.call_count, 4)
        self.assertEqual(raw, before)

    def test_zero_through_four_and_reordering_are_slot_aligned(self):
        p = pipeline()
        for n in range(5):
            displayed, static, pinches, frame = p.update(as_result(*four()[:n]), n * 33, SIZE, Profile())
            self.assertEqual(tuple(map(len, (displayed.hand_landmarks, static, pinches, frame.hands))), (n,) * 4)
        ids = tuple(a.track_id for a in p.associations)
        _, _, _, frame = p.update(as_result(*reversed(four())), 165, SIZE, Profile())
        self.assertEqual(tuple(h.track_id for h in frame.hands), tuple(reversed(ids)))

    def test_closed_reacquisition_does_not_fabricate_pinch_release_or_start(self):
        p = pipeline()
        p.update(as_result(*four(ratio=.8)), 0, SIZE, Profile())
        p.update(as_result(*four(ratio=.08)), 50, SIZE, Profile())
        p.update(as_result(*four(ratio=.08)), 100, SIZE, Profile())
        ids = [a.track_id for a in p.associations]
        _, _, _, lost = p.update(as_result(*four(ratio=.08)[1:]), 150, SIZE, Profile())
        self.assertTrue(any(e.track_id == ids[0] and e.event_type == E.GESTURE_CANCELED for e in lost.events))
        _, _, pinches, returned = p.update(as_result(*four(ratio=.08)), 200, SIZE, Profile())
        self.assertEqual(p.associations[0].track_id, ids[0])
        self.assertEqual(pinches[0].status.value, "UNAVAILABLE")
        self.assertFalse(any(e.track_id == ids[0] and e.event_type in (E.GESTURE_STARTED, E.GESTURE_ENDED)
                             for e in returned.events))

    def test_only_moving_track_emits_swipe_and_histories_are_independent(self):
        p = pipeline()
        all_events = []
        for step in range(12):
            dx = max(0, step - 6) * .4 * .0385
            observations = tuple(hand(x + (dx if i == 2 else 0)) for i, x in enumerate((.15, .37, .59, .81)))
            _, _, _, frame = p.update(as_result(*observations), step * 50, SIZE, Profile())
            all_events.extend(frame.events)
        swipes = [e for e in all_events if e.gesture in SWIPES and e.event_type == E.GESTURE_STARTED]
        self.assertEqual(len(swipes), 1)
        self.assertEqual(swipes[0].track_id, 3)
        self.assertEqual(len(p.state_manager._tracks), 4)

    def test_malformed_or_occluded_slot_does_not_hide_other_hands(self):
        p = pipeline()
        p.update(as_result(*four()), 0, SIZE, Profile())
        raw = as_result(*four())
        raw.hand_landmarks[1] = raw.hand_landmarks[1][:10]
        displayed, static, pinches, frame = p.update(raw, 50, SIZE, Profile())
        self.assertEqual(len(displayed.hand_landmarks), 4)
        self.assertEqual(static[1].gesture, G.UNKNOWN)
        self.assertEqual(pinches[1].status.value, "UNAVAILABLE")
        self.assertTrue(all(p.associations[i].certain for i in (0, 2, 3)))

    def test_disabled_smoothing_and_raw_overlay_remain_separate(self):
        p = pipeline(FLAGS + ["--no-smoothing"])
        raw = as_result(*four())
        displayed, *_ = p.update(raw, 0, SIZE, Profile())
        self.assertEqual(displayed.hand_landmarks[0][0].x, raw.hand_landmarks[0][0].x)
        self.assertEqual(p.smoother._history, {})

    def test_more_than_requested_observations_refused_without_silent_downgrade(self):
        with self.assertRaises(ValueError):
            pipeline(["--max-hands", "3"]).update(as_result(*four()), 0, SIZE, Profile())


class MultiHandPreviewTest(unittest.TestCase):
    def test_all_four_skeletons_labels_and_handedness_scores_are_visible(self):
        p = pipeline()
        raw = as_result(*four())
        shown, static, pinches, frame = p.update(raw, 0, SIZE, Profile())
        source = np.full((1080, 1920, 3), 120, np.uint8)
        with patch.object(cv2, "putText", wraps=cv2.putText) as text:
            tracking_utils.make_preview(source, shown, 30., False, gesture_results=static, pinch_results=pinches,
                                        gesture_states=frame.hands, swipe_results=frame.motion,
                                        max_hands=4, track_associations=p.associations)
        labels = [c.args[1] for c in text.call_args_list]
        for key in range(1, 5):
            self.assertTrue(any(f"TRACK {key}" in label and "93%" in label for label in labels))
        self.assertTrue(any("HANDS: 4 / 4" in label for label in labels))
        self.assertTrue(np.all(source == 120))

    def test_uncertainty_is_explicit_and_stale_overlays_are_cleared(self):
        p, renderer = pipeline(), tracking_utils.PreviewRenderer()
        raw = as_result(hand(.49), hand(.51))
        shown, *_ = p.update(raw, 0, SIZE, Profile())
        source = np.full((1080, 1920, 3), 100, np.uint8)
        with patch.object(cv2, "putText", wraps=cv2.putText) as text:
            tracking_utils.make_preview(source, shown, 30., False, renderer=renderer,
                                        max_hands=4, track_associations=p.associations)
        self.assertTrue(any("UNCERTAIN" in c.args[1] for c in text.call_args_list))
        fresh = tracking_utils.make_preview(source, as_result(), 30., False, renderer=renderer,
                                            max_hands=4, track_associations=())
        self.assertTrue(np.all(fresh[27:] == 100))

    def test_raw_comparison_draws_all_84_landmarks(self):
        p = pipeline()
        raw = as_result(*four())
        shown, *_ = p.update(raw, 0, SIZE, Profile())
        with patch.object(cv2, "drawMarker", wraps=cv2.drawMarker) as marker:
            tracking_utils.make_preview(np.zeros((1080, 1920, 3), np.uint8), shown, 30., False,
                                        raw_result=raw, max_hands=4, track_associations=p.associations)
        self.assertEqual(marker.call_count, 84)

    def test_debug_is_sampled_and_disabled_mode_has_no_logger(self):
        p = pipeline(FLAGS + ["--multi-hand-debug"])
        with self.assertLogs(tracker.LOGGER, level="INFO") as output:
            for stamp in (0, 50, 1999, 2000):
                p.update(as_result(*four()), stamp, SIZE, Profile())
        self.assertEqual(len(output.output), 2)
        self.assertIsNone(pipeline().debug)


class MultiHandApplicationTest(unittest.TestCase):
    def test_four_hand_timed_headless_benchmark_excludes_warmup_and_gui(self):
        now = 0.
        cap, detector = MagicMock(), MagicMock()
        source = np.zeros((1080, 1920, 3), np.uint8)
        def read():
            nonlocal now
            now += .05
            return True, source
        def infer(image, stamp):
            nonlocal now
            now += .005
            return as_result(*four())
        cap.read.side_effect = read
        detector.detect_for_video.side_effect = infer
        mp = SimpleNamespace(Image=lambda **kw: kw["data"], ImageFormat=SimpleNamespace(SRGB=1))
        report = {}
        args = tracker.parse_args(FLAGS + ["--benchmark", "--headless", "--warmup", ".15", "--duration", ".3"])
        with patch.object(tracker.time, "perf_counter", side_effect=lambda: now), \
                patch.object(cv2, "imshow") as display, patch.object(cv2, "pollKey") as events, self.assertLogs(tracker.LOGGER):
            tracker.process_frames(cap, detector, mp, args, report)
        self.assertEqual(report["status"], "completed")
        self.assertLess(report["frames"], cap.read.call_count)
        self.assertEqual(report["timings"]["association"]["count"], report["frames"])
        self.assertEqual(report["detected_hands_frames"], {"4": report["frames"]})
        self.assertEqual(set(report["timings_by_detected_hands"]), {"4"})
        display.assert_not_called()
        events.assert_not_called()

    def test_fake_camera_pipeline_observes_four_and_profiles_by_actual_count_without_input(self):
        cap, detector = MagicMock(), MagicMock()
        source = np.full((1080, 1920, 3), 30, np.uint8)
        cap.read.return_value = (True, source)
        observations = [as_result(*four()[:n]) for n in (0, 1, 2, 3, 4, 4)]
        detector.detect_for_video.side_effect = observations
        mp = SimpleNamespace(Image=lambda **kw: kw["data"], ImageFormat=SimpleNamespace(SRGB=1))
        report = {}
        with patch.object(cv2, "waitKey", side_effect=[-1] * 5 + [ord("q")]), patch.object(cv2, "imshow"), \
                patch.object(cv2, "getWindowProperty", return_value=1), \
                patch.object(control_cli, "create_controller") as factory, \
                patch("controls.windows.WindowsBackend") as windows, self.assertLogs(tracker.LOGGER):
            tracker.process_frames(cap, detector, mp, tracker.parse_args(FLAGS + ["--gui-mode", "waitkey"]), report)
        factory.assert_not_called()
        windows.assert_not_called()
        self.assertEqual(detector.detect_for_video.call_count, 6)
        self.assertEqual(report["detected_hands_frames"], {"0": 1, "1": 1, "2": 1, "3": 1, "4": 2})
        self.assertEqual(set(report["timings_by_detected_hands"]), {"0", "1", "2", "3", "4"})
        self.assertEqual(report["timings"]["association"]["count"], 6)
        self.assertEqual(report["max_hands_requested"], 4)
        self.assertFalse(report["controls"]["enabled"])
        json.dumps(report, allow_nan=False)

    def test_synthetic_benchmark_supports_2_3_4_id_observation_only(self):
        for count in (2, 3, 4):
            result = measure("swipes", count, frames=6, warmup=2, track_ids=True)
            self.assertEqual(result["timings"]["association"]["count"], 6)
            self.assertEqual(result["virtual_actions"], {})
            self.assertNotIn("average_application_fps", result)
        for count in (3, 4):
            with self.assertRaises(ValueError):
                measure("simulate-absolute", count, frames=4)

    def test_profiler_accepts_all_observed_counts_and_rejects_invalid_values(self):
        p = WorkloadProfile()
        for count in range(5):
            p.add("association", .001)
            p.finish_frame(count)
        self.assertEqual(set(p.workload_summary()), {"0", "1", "2", "3", "4"})
        for count in (-1, 5, True, 2.):
            with self.assertRaises(ValueError):
                p.finish_frame(count)


if __name__ == "__main__":
    unittest.main()
