from contextlib import redirect_stderr
from copy import deepcopy
import io
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

import cv2
import numpy as np

from gestures.features import extract_features
from gestures.static_gestures import Gesture, StaticThresholds, classify_hand
from gestures.tests.static_fixtures import SIZE, as_result, pose_hand
from gestures.tests.test_pointing_calibration import ALL, OTHERS, relaxed_pointing
from . import hand_tracker as tracker
from .gesture_debug import GestureDebug
from .gesture_preview import classify_result
from .performance import Profile


class GestureDebugTest(unittest.TestCase):
    def test_assessments_distinguish_index_curl_unsupported_invalid_and_conflict(self):
        index = extract_features(pose_hand(curled=OTHERS, partial=(ALL[0],)), image_size=SIZE)
        others = extract_features(pose_hand(curled=(ALL[2], ALL[3])), image_size=SIZE)
        thumb = extract_features(pose_hand(curled=ALL, thumb="extended"), image_size=SIZE)
        opened = extract_features(pose_hand(), image_size=SIZE)
        results = (classify_hand(index, 0, diagnostics=True), classify_hand(others, 0, diagnostics=True),
                   classify_hand(thumb, 0, diagnostics=True), classify_hand(None, 0, diagnostics=True),
                   classify_hand(opened, 0, thresholds=StaticThresholds(0, 0, 0, 0, 180, 180, 1, 100),
                                 diagnostics=True))
        with self.assertLogs(tracker.LOGGER, level="INFO") as captured:
            GestureDebug().log(results, 0)
        text = "\n".join(captured.output)
        for expected in ("index_not_confidently_extended", "other_fingers_not_confidently_curled",
                         "unsupported_hand_configuration", "invalid_or_unreliable_measurements",
                         "conflicting_gesture_rules", "depth/occlusion not assessed", "index extension:",
                         "middle curl:"):
            self.assertIn(expected, text)

    def test_cli_debug_requires_opt_in_recognition(self):
        self.assertFalse(tracker.parse_args([]).gesture_debug)
        self.assertTrue(tracker.parse_args(["--gestures", "--gesture-debug"]).gesture_debug)
        for options in (["--gesture-debug"], ["--gestures", "--no-gestures", "--gesture-debug"]):
            with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                tracker.parse_args(options)

    def test_log_sampling_is_rate_limited_without_debouncing_results(self):
        debug = GestureDebug()
        self.assertEqual([debug.due(stamp) for stamp in (0, 1, 1999, 2000, 2001, 4500)],
                         [True, False, False, True, False, True])
        for invalid in (0, -1, True, 1.5):
            with self.assertRaises(ValueError):
                GestureDebug(invalid)

    def test_numeric_logs_explain_failed_requirements_and_invalid_features(self):
        partial = pose_hand(chain_angles={f: (90, 20, -20) for f in OTHERS})
        results = (classify_hand(extract_features(partial, image_size=SIZE), 0, diagnostics=True),
                   classify_hand(None, 0, diagnostics=True))
        with self.assertLogs(tracker.LOGGER, level="INFO") as captured:
            GestureDebug().log(results, 0)
        text = "\n".join(captured.output)
        for expected in ("UNKNOWN", "index", "middle", "ring", "pinky", "PIP_degrees", "DIP_degrees",
                         "straightness", "tip_to_wrist", "PASS", "FAIL", "INVALID", "POINTING blockers"):
            self.assertIn(expected, text)
        for prohibited in ("hand_landmarks", "data:image", "array(", "camera image", "x=", "y="):
            self.assertNotIn(prohibited, text)

    def test_invalid_hand_does_not_shift_debug_or_classification_slots(self):
        raw = as_result(pose_hand(), relaxed_pointing(side="Right"))
        raw.hand_landmarks[0][0].x = float("nan")
        result = classify_result(raw, 0, SIZE, Profile(), diagnostics=True)
        self.assertEqual([r.gesture for r in result], [Gesture.UNKNOWN, Gesture.POINTING])
        self.assertTrue(result[0].pointing_checks)
        self.assertEqual(result[1].handedness[0].category_name, "Right")

    def test_live_debug_samples_only_selected_frames_and_preserves_two_hand_results(self):
        now = 0.0
        cap, detector = MagicMock(), MagicMock()
        raw = as_result(relaxed_pointing(), pose_hand(curled=ALL, thumb="tucked", side="Right"))
        before = deepcopy(raw)

        def read():
            nonlocal now
            now += .1
            return True, np.zeros((1080, 1920, 3), dtype=np.uint8)

        cap.read.side_effect = read
        detector.detect_for_video.return_value = raw
        mp = SimpleNamespace(Image=lambda **kw: kw["data"], ImageFormat=SimpleNamespace(SRGB=1))
        report = {}
        with patch.object(tracker.time, "perf_counter", side_effect=lambda: now), \
                patch.object(cv2, "imshow"), patch.object(cv2, "getWindowProperty", return_value=1), \
                patch.object(cv2, "waitKey", side_effect=[-1] * 24 + [ord("q")]), \
                patch.object(tracker, "classify_result", wraps=classify_result) as classify, \
                patch.object(tracker, "make_preview", return_value=np.zeros((1, 1, 3), dtype=np.uint8)), \
                self.assertLogs(tracker.LOGGER) as logs:
            tracker.process_frames(cap, detector, mp,
                                   tracker.parse_args(["--gestures", "--gesture-debug", "--gui-mode", "waitkey"]), report)
        self.assertEqual(sum(call.kwargs["diagnostics"] for call in classify.call_args_list), 2)
        self.assertEqual(report["gestures"]["classification_counts"], {"POINTING": 25, "FIST": 25})
        self.assertTrue(report["gestures"]["debug_enabled"])
        self.assertEqual(raw, before)
        self.assertEqual(sum("Gesture debug t=" in text for text in logs.output), 4)  # two hands, two samples

    def test_disabled_debug_allocates_no_sampler_or_diagnostic_records(self):
        cap, detector = MagicMock(), MagicMock()
        cap.read.return_value = (True, np.zeros((1080, 1920, 3), dtype=np.uint8))
        detector.detect_for_video.return_value = as_result(relaxed_pointing())
        mp = SimpleNamespace(Image=lambda **kw: kw["data"], ImageFormat=SimpleNamespace(SRGB=1))
        with patch.object(tracker, "GestureDebug") as debug, \
                patch.object(tracker, "classify_result", wraps=classify_result) as classify, \
                patch.object(cv2, "imshow"), patch.object(cv2, "waitKey", return_value=ord("q")), \
                patch.object(tracker, "make_preview") as preview, self.assertLogs(tracker.LOGGER):
            tracker.process_frames(cap, detector, mp,
                                   tracker.parse_args(["--gestures", "--gui-mode", "waitkey"]))
        debug.assert_not_called()
        self.assertFalse(classify.call_args.kwargs["diagnostics"])
        self.assertEqual(preview.call_args.kwargs["gesture_results"][0].pointing_checks, ())


if __name__ == "__main__":
    unittest.main()
