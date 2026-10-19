from contextlib import redirect_stderr
from copy import deepcopy
import io
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

import cv2
import numpy as np

from gestures.features import extract_features
from gestures.pinch import PinchStatus as S, PinchThresholds, PinchTracker
from gestures.tests.pinch_fixtures import pinch_hand
from gestures.tests.static_fixtures import SIZE, as_result
from . import gesture_preview, hand_tracker as tracker
from .performance import Profile
from .smoothing import LandmarkSmoother
from .tracking_utils import PINCH_COLORS, PreviewRenderer, hand_overlays, make_preview


def pair(distance):
    return as_result(pinch_hand(distance, offset=-.23), pinch_hand(distance, side="Right", offset=.23))


class PinchIntegrationTest(unittest.TestCase):
    def test_cli_opt_in_independent_and_validated(self):
        default = tracker.parse_args([])
        self.assertFalse(default.pinch)
        self.assertFalse(default.gestures)
        self.assertEqual(default.backend, "msmf")
        self.assertEqual((default.width, default.height, default.fps), (1920, 1080, 60))
        for switches in (["--pinch"], ["--pinch", "--no-gestures"], ["--pinch", "--gestures"],
                         ["--pinch", "--pinch-debug", "--pinch-activation", ".2", "--pinch-release", ".45"]):
            self.assertTrue(tracker.parse_args(switches).pinch)
        self.assertFalse(tracker.parse_args(["--gestures"]).pinch)
        for switches in (["--pinch-debug"], ["--pinch-activation", "0"], ["--pinch-release", ".1"],
                         ["--pinch-release", "nan"], ["--pinch-release", "inf"], ["--pinch-release", "3"],
                         ["--pinch-activation", ".4", "--pinch-release", ".4"]):
            with self.subTest(switches=switches), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                tracker.parse_args(switches)

    def test_features_extracted_once_for_both_channels_static_results_unchanged(self):
        raw = pair(.1)
        before = deepcopy(raw)
        expected = gesture_preview.classify_result(raw, 30, SIZE, Profile())
        cached = []
        with patch.object(gesture_preview, "extract_features", wraps=extract_features) as extract:
            actual = gesture_preview.classify_result(raw, 30, SIZE, Profile(), features_out=cached)
            pinches = PinchTracker().update(tuple(cached), 30)
        self.assertEqual(extract.call_count, 2)
        self.assertEqual(actual, expected)
        self.assertTrue(all(r.measurement.valid for r in pinches))
        self.assertEqual(raw, before)

    def test_malformed_slot_remains_aligned_and_unknown_available(self):
        raw = pair(.1)
        raw.hand_landmarks[0][0].x = float("nan")
        cached = []
        static = gesture_preview.classify_result(raw, 0, SIZE, Profile(), features_out=cached)
        self.assertIsNone(cached[0])
        self.assertEqual(static[0].gesture.value, "UNKNOWN")
        pinches = PinchTracker().update(tuple(cached), 0)
        self.assertEqual(len(pinches), 2)
        self.assertFalse(pinches[0].measurement.valid)
        self.assertTrue(pinches[1].measurement.valid)
        self.assertEqual([r.status for r in pinches], [S.UNAVAILABLE]*2)
        overlay = hand_overlays(raw, 1100, 619, static, pinches)
        self.assertEqual(len(overlay), 1)
        self.assertIs(overlay[0].pinch, pinches[1])

    def test_pinches_use_existing_smoothed_geometry(self):
        smoother = LandmarkSmoother()
        first, second = pair(.8), pair(.75)
        smoother.apply(first, 0, (1080, 1920))
        smoothed = smoother.apply(second, 30, (1080, 1920))
        before = deepcopy(second)
        cached = gesture_preview.prepare_features(smoothed, 30, SIZE)
        for feature, displayed in zip(cached, smoothed.hand_landmarks):
            self.assertEqual(feature.observation[4].x, displayed[4].x)
        self.assertNotEqual(smoothed.hand_landmarks[0][4].x, second.hand_landmarks[0][4].x)
        self.assertEqual(second, before)

    def test_preview_highlights_states_diagnostics_and_clears_overlays(self):
        frame = np.full((1080, 1920, 3), 120, dtype=np.uint8)
        detector = PinchTracker()
        renderer = PreviewRenderer()
        for n, (distance, status) in enumerate(((.8, S.OPEN), (.1, S.STARTED), (.1, S.HELD), (.8, S.RELEASED))):
            raw = pair(distance)
            cached = []
            static = gesture_preview.classify_result(raw, n*30, SIZE, Profile(), features_out=cached)
            pinches = detector.update(tuple(cached), n*30)
            with patch.object(cv2, "putText", wraps=cv2.putText) as texts, \
                    patch.object(cv2, "circle", wraps=cv2.circle) as circles:
                preview = make_preview(frame, raw, 36, False, renderer=renderer, gesture_results=static,
                                       pinch_results=pinches, pinch_thresholds=PinchThresholds())
            labels = [call.args[1] for call in texts.call_args_list]
            self.assertTrue(any(f"Pinch: {status.value}" in text for text in labels))
            self.assertTrue(any("d=" in text and "A<0.25 R>0.4 valid=yes" in text for text in labels))
            self.assertTrue(any(call.args[2:4] == (5, PINCH_COLORS[status.value]) for call in circles.call_args_list))
        fresh = make_preview(frame, as_result(), 36, False, renderer=renderer, pinch_results=())
        self.assertIs(preview, fresh)
        self.assertTrue(np.all(frame == 120))
        self.assertTrue(np.all(fresh[30:] == 120))

    def test_invalid_data_diagnostic_and_debug_off(self):
        raw = pair(.1)
        cached = gesture_preview.prepare_features(raw, 0, SIZE)
        pinches = PinchTracker().update(tuple(cached), 0)
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        with patch.object(cv2, "putText", wraps=cv2.putText) as texts:
            make_preview(frame, raw, 36, False, pinch_results=pinches)
        self.assertFalse(any("d=" in call.args[1] for call in texts.call_args_list))
        self.assertTrue(any("UNAVAILABLE" in call.args[1] for call in texts.call_args_list))
        # Finite points can still form a degenerate palm; display must say invalid.
        for point in raw.hand_landmarks[0]:
            point.x, point.y = .5, .5
        pinches = PinchTracker().update(gesture_preview.prepare_features(raw, 30, SIZE), 30)
        with patch.object(cv2, "putText", wraps=cv2.putText) as texts:
            make_preview(frame, raw, 36, True, pinch_results=pinches, pinch_thresholds=PinchThresholds())
        self.assertTrue(any("d=--" in call.args[1] and "valid=no" in call.args[1] for call in texts.call_args_list))

    def test_live_two_hand_lifecycle_native_polling_q_h_and_profiling(self):
        # Reversing the second frame must not switch histories between hands.
        raw = [pair(d) for d in (.8, .1, .1, .8, .8)]
        raw[1].hand_landmarks.reverse()
        raw[1].handedness.reverse()
        before = deepcopy(raw)
        cap, detector = MagicMock(), MagicMock()
        cap.read.return_value = (True, np.zeros((1080, 1920, 3), dtype=np.uint8))
        detector.detect_for_video.side_effect = raw
        mp = SimpleNamespace(Image=lambda **kw: kw["data"], ImageFormat=SimpleNamespace(SRGB=1))
        now = iter(i*.001 for i in range(1000))
        report = {}
        with patch.object(tracker.time, "perf_counter", side_effect=lambda: next(now)), \
                patch.object(cv2, "currentUIFramework", return_value="WIN32", create=True), \
                patch.object(cv2, "pollKey", side_effect=[ord("h"), -1, -1, -1, ord("q")], create=True), \
                patch.object(cv2, "waitKey") as wait, patch.object(cv2, "imshow"), \
                patch.object(cv2, "getWindowProperty", return_value=1), \
                patch.object(tracker, "make_preview", wraps=make_preview) as preview, \
                patch.object(gesture_preview, "extract_features", wraps=extract_features) as extract, \
                self.assertLogs(tracker.LOGGER):
            tracker.process_frames(cap, detector, mp, tracker.parse_args(["--gestures", "--pinch", "--no-smoothing"]), report)
        self.assertEqual(raw, before)
        self.assertEqual(extract.call_count, 10)
        self.assertEqual(detector.detect_for_video.call_count, 5)
        self.assertEqual(report["pinch"]["status_counts"], {"OPEN": 4, "STARTED": 2, "HELD": 2, "RELEASED": 2})
        self.assertEqual(report["timings"]["pinch_processing"]["count"], 5)
        self.assertEqual(report["timings_by_detected_hands"]["2"]["pinch_processing"]["count"], 5)
        self.assertNotIn("pinch_features", report["timings"])
        self.assertEqual(report["gui"]["effective"], "pollkey")
        self.assertFalse(preview.call_args_list[0].args[3])
        self.assertTrue(preview.call_args_list[1].args[3])
        wait.assert_not_called()

    def test_disabled_pinch_skips_tracker_and_features(self):
        cap, detector = MagicMock(), MagicMock()
        cap.read.return_value = (True, np.zeros((80, 100, 3), dtype=np.uint8))
        detector.detect_for_video.return_value = as_result()
        mp = SimpleNamespace(Image=lambda **kw: kw["data"], ImageFormat=SimpleNamespace(SRGB=1))
        report = {}
        with patch.object(tracker, "PinchTracker") as pinch, patch.object(tracker, "prepare_features") as prepare, \
                patch.object(cv2, "imshow"), patch.object(cv2, "waitKey", return_value=ord("q")), \
                self.assertLogs(tracker.LOGGER):
            tracker.process_frames(cap, detector, mp, tracker.parse_args(["--gui-mode", "waitkey"]), report)
        pinch.assert_not_called()
        prepare.assert_not_called()
        self.assertFalse(report["pinch"]["enabled"])
        self.assertNotIn("pinch_processing", report["timings"])

    def test_pinch_only_headless_benchmark_excludes_warmup_and_gui(self):
        now = 0.0
        cap, detector = MagicMock(), MagicMock()
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        def read():
            nonlocal now
            now += .05
            return True, frame
        cap.read.side_effect = read
        detector.detect_for_video.side_effect = lambda *_: pair(.8)
        mp = SimpleNamespace(Image=lambda **kw: kw["data"], ImageFormat=SimpleNamespace(SRGB=1))
        report = {}
        with patch.object(tracker.time, "perf_counter", side_effect=lambda: now), \
                patch.object(cv2, "imshow") as display, patch.object(tracker, "classify_result") as static, \
                self.assertLogs(tracker.LOGGER):
            tracker.process_frames(cap, detector, mp, tracker.parse_args(
                ["--pinch", "--no-gestures", "--benchmark", "--headless", "--warmup", ".1", "--duration", ".2"]), report)
        static.assert_not_called()
        display.assert_not_called()
        self.assertEqual(report["status"], "completed")
        self.assertLess(report["frames"], cap.read.call_count)
        self.assertEqual(report["timings"]["pinch_processing"]["count"], report["frames"])
        self.assertEqual(report["timings"]["pinch_features"]["count"], report["frames"])
        self.assertEqual(report["pinch"]["status_counts"], {"OPEN": report["frames"]*2})


if __name__ == "__main__":
    unittest.main()
