"""Static gesture integration without a physical camera, inference or GUI window."""

from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

import cv2
import numpy as np

from gestures.models import Finger, HandObservation
from gestures.static_gestures import Gesture
from gestures.tests.static_fixtures import SIZE, as_result, pose_hand
from . import gesture_preview, hand_tracker as tracker
from .performance import Profile
from .smoothing import LandmarkSmoother
from .tracking_utils import HAND_COLORS, PreviewRenderer, hand_overlays, make_preview


OTHERS = (Finger.MIDDLE, Finger.RING, Finger.PINKY)


class GestureIntegrationTest(unittest.TestCase):
    def test_cli_is_opt_in_and_preserves_working_defaults(self):
        for options, expected in (([], False), (["--gestures"], True), (["--no-gestures"], False),
                                   (["--gestures", "--no-gestures"], False)):
            args = tracker.parse_args(options)
            self.assertEqual(args.gestures, expected)
            self.assertEqual((args.width, args.height, args.fps, args.backend), (1920, 1080, 60, "msmf"))
            self.assertTrue(args.smoothing)
            self.assertEqual(args.smoothing_alpha, .75)
            self.assertEqual(args.gui_mode, "auto")
            self.assertIsNone(args.inference_resolution)

    def test_zero_one_two_hands_order_changes_and_disappearance(self):
        left, right = pose_hand(), pose_hand(curled=OTHERS, side="Right")
        timings = Profile()
        for hands, expected in (((), ()), ((left,), (Gesture.OPEN_PALM,)),
                                ((left, right), (Gesture.OPEN_PALM, Gesture.POINTING)),
                                ((right, left), (Gesture.POINTING, Gesture.OPEN_PALM)), ((), ())):
            raw = as_result(*hands)
            before = deepcopy(raw)
            actual = gesture_preview.classify_result(raw, 123, SIZE, timings)
            self.assertEqual(tuple(item.gesture for item in actual), expected)
            self.assertEqual(tuple(item.handedness for item in actual), tuple(h.handedness for h in hands))
            self.assertEqual(raw, before)
        for name in ("gesture_features", "gesture_classification", "gesture_total"):
            self.assertEqual(timings.summary()[name]["count"], 5)

    def test_malformed_hand_keeps_unknown_slot_and_other_hand_classification(self):
        raw = as_result(pose_hand(), pose_hand(curled=OTHERS, side="Right"))
        raw.hand_landmarks[0][0].x = float("nan")
        results = gesture_preview.classify_result(raw, 0, SIZE, Profile())
        self.assertEqual([r.gesture for r in results], [Gesture.UNKNOWN, Gesture.POINTING])
        overlays = hand_overlays(raw, 1100, 619, results)
        self.assertEqual([(hand.label, hand.gesture) for hand in overlays], [("Right", "POINTING")])
        self.assertEqual(overlays[0].color, HAND_COLORS["Right"])

    def test_existing_ema_coordinates_are_used_without_mutating_raw_results(self):
        initial = as_result(pose_hand())
        shifted = deepcopy(initial)
        for point in shifted.hand_landmarks[0]:
            point.x += .002
        before = deepcopy(shifted)
        smoother = LandmarkSmoother()
        smoother.apply(initial, 1, (1080, 1920))
        smoothed = smoother.apply(shifted, 34, (1080, 1920))
        self.assertIsNot(smoothed, shifted)
        with patch.object(gesture_preview, "extract_features", wraps=gesture_preview.extract_features) as extract:
            results = gesture_preview.classify_result(smoothed, 34, SIZE, Profile())
        observation = extract.call_args.args[0]
        self.assertEqual(observation.landmarks[0].x, smoothed.hand_landmarks[0][0].x)
        self.assertNotEqual(observation.landmarks[0].x, shifted.hand_landmarks[0][0].x)
        self.assertEqual(results[0].gesture, Gesture.OPEN_PALM)
        self.assertEqual(shifted, before)

    def test_labels_colors_black_background_and_buffer_refresh(self):
        raw = as_result(pose_hand(), pose_hand(curled=OTHERS, side="Right"))
        classifications = gesture_preview.classify_result(raw, 1, SIZE, Profile())
        frame = np.full((1080, 1920, 3), 120, dtype=np.uint8)
        renderer = PreviewRenderer()
        with patch.object(cv2, "putText", wraps=cv2.putText) as text, \
                patch.object(cv2, "rectangle", wraps=cv2.rectangle) as rectangle:
            preview = make_preview(frame, raw, 38, False, renderer=renderer, gesture_results=classifications)
        labels = [call.args[1] for call in text.call_args_list]
        self.assertIn("Left - OPEN_PALM", labels)
        self.assertIn("Right - POINTING", labels)
        self.assertEqual([call.args[4] for call in rectangle.call_args_list], [-1, -1])
        self.assertTrue(all(call.args[3] == (0, 0, 0) for call in rectangle.call_args_list))
        self.assertTrue(np.all(frame == 120))
        fresh = make_preview(frame, as_result(), 38, False, renderer=renderer, gesture_results=())
        self.assertIs(preview, fresh)
        self.assertTrue(np.all(fresh[30:] == 120))

    def test_ambiguous_detected_hand_shows_unknown_and_disabled_overlay_stays_original(self):
        raw = as_result(pose_hand(partial=(Finger.INDEX, Finger.MIDDLE, Finger.RING, Finger.PINKY)))
        actual = gesture_preview.classify_result(raw, 1, SIZE, Profile())
        self.assertEqual(actual[0].gesture, Gesture.UNKNOWN)
        self.assertEqual(hand_overlays(raw, 1100, 619, actual)[0].gesture, "UNKNOWN")
        self.assertIsNone(hand_overlays(raw, 1100, 619)[0].gesture)

    def test_live_loop_preserves_native_polling_keys_and_frame_association(self):
        left = pose_hand()
        right = pose_hand(curled=OTHERS, side="Right")
        # Separate palms so this also exercises independent EMA histories.
        left = HandObservation(tuple(replace(p, x=p.x - .2) for p in left.landmarks), left.handedness)
        right = HandObservation(tuple(replace(p, x=p.x + .2) for p in right.landmarks), right.handedness)
        detections = [as_result(left, right), as_result(right, left), as_result(), as_result(right)]
        before = deepcopy(detections)
        cap, detector = MagicMock(), MagicMock()
        cap.read.return_value = (True, np.zeros((1080, 1920, 3), dtype=np.uint8))
        detector.detect_for_video.side_effect = detections
        mp = SimpleNamespace(Image=lambda **kwargs: kwargs["data"], ImageFormat=SimpleNamespace(SRGB=1))
        report = {}
        with patch.object(cv2, "currentUIFramework", return_value="WIN32", create=True), \
                patch.object(cv2, "pollKey", side_effect=[ord("h"), -1, -1, ord("q")], create=True), \
                patch.object(cv2, "waitKey") as wait, patch.object(cv2, "imshow"), \
                patch.object(cv2, "getWindowProperty", return_value=1), \
                patch.object(tracker, "make_preview", wraps=tracker.make_preview) as preview, \
                self.assertLogs(tracker.LOGGER):
            self.assertEqual(tracker.process_frames(cap, detector, mp, tracker.parse_args(["--gestures"]), report), 0)
        self.assertEqual(detections, before)
        expected = [(Gesture.OPEN_PALM, Gesture.POINTING), (Gesture.POINTING, Gesture.OPEN_PALM),
                    (), (Gesture.POINTING,)]
        for call, gestures in zip(preview.call_args_list, expected):
            self.assertEqual(tuple(r.gesture for r in call.kwargs["gesture_results"]), gestures)
        self.assertFalse(preview.call_args_list[0].args[3])
        self.assertTrue(preview.call_args_list[1].args[3])
        wait.assert_not_called()
        self.assertEqual(report["gui"]["effective"], "pollkey")
        self.assertEqual(report["gestures"]["classification_counts"], {"OPEN_PALM": 2, "POINTING": 3})
        self.assertEqual(report["timings"]["gesture_total"]["count"], 4)
        self.assertIn("gesture_classification", report["timings_by_detected_hands"]["2"])

    def test_disabled_recognition_skips_all_new_work(self):
        cap, detector = MagicMock(), MagicMock()
        cap.read.return_value = (True, np.zeros((80, 100, 3), dtype=np.uint8))
        detector.detect_for_video.return_value = as_result(pose_hand())
        mp = SimpleNamespace(Image=lambda **kwargs: kwargs["data"], ImageFormat=SimpleNamespace(SRGB=1))
        report = {}
        with patch.object(tracker, "classify_result") as classify, patch.object(cv2, "imshow"), \
                patch.object(cv2, "waitKey", return_value=ord("q")), self.assertLogs(tracker.LOGGER):
            tracker.process_frames(cap, detector, mp,
                                   tracker.parse_args(["--no-gestures", "--gui-mode", "waitkey"]), report)
        classify.assert_not_called()
        self.assertFalse(report["gestures"]["enabled"])
        self.assertNotIn("gesture_total", report["timings"])

    def test_headless_benchmark_excludes_warmup_gesture_samples_and_counts(self):
        now = 0.0
        cap, detector = MagicMock(), MagicMock()
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)

        def read():
            nonlocal now
            now += .1
            return True, frame

        def infer(image, stamp):
            nonlocal now
            now += .02
            return as_result(pose_hand(), pose_hand(curled=OTHERS, side="Right"))

        cap.read.side_effect, detector.detect_for_video.side_effect = read, infer
        mp = SimpleNamespace(Image=lambda **kwargs: kwargs["data"], ImageFormat=SimpleNamespace(SRGB=1))
        args = tracker.parse_args(["--gestures", "--benchmark", "--headless", "--warmup", ".25", "--duration", ".5"])
        report = {}
        with patch.object(tracker.time, "perf_counter", side_effect=lambda: now), \
                patch.object(cv2, "imshow") as display, patch.object(cv2, "pollKey") as pump, \
                self.assertLogs(tracker.LOGGER):
            tracker.process_frames(cap, detector, mp, args, report)
        display.assert_not_called()
        pump.assert_not_called()
        self.assertEqual(report["status"], "completed")
        self.assertLess(report["frames"], cap.read.call_count)
        self.assertEqual(report["timings"]["gesture_total"]["count"], report["frames"])
        self.assertEqual(report["gestures"]["classification_counts"],
                         {"OPEN_PALM": report["frames"], "POINTING": report["frames"]})


if __name__ == "__main__":
    unittest.main()
