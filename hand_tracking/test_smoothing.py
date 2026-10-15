"""Phase 2.4 EMA correctness, safe identity gates and disappearance/recovery."""

from contextlib import redirect_stderr
import io
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

import cv2
import numpy as np

from . import hand_tracker as tracker
from .smoothing import LandmarkSmoother, MAX_HISTORY_GAP_MS
from .test_two_hands import category, result
from .tracking_utils import hand_overlays, make_preview


def hand(x, y=.6, z=.0):
    return [SimpleNamespace(x=x, y=y, z=z) for _ in range(21)]


def one_hand(x, label="Left", score=.95, y=.6, z=.0):
    return result([hand(x, y, z)], [[category(label, score)]])


class SmoothingTest(unittest.TestCase):
    def test_default_cli_enable_disable_and_strength(self):
        args = tracker.parse_args([])
        self.assertTrue(args.smoothing)
        self.assertEqual(args.smoothing_alpha, .75)
        self.assertFalse(args.show_raw_landmarks)
        self.assertFalse(tracker.parse_args(["--no-smoothing"]).smoothing)
        args = tracker.parse_args(["--smoothing", "--smoothing-alpha", ".9", "--show-raw-landmarks"])
        self.assertTrue(args.smoothing and args.show_raw_landmarks)
        self.assertEqual(args.smoothing_alpha, .9)
        self.assertEqual((args.backend, args.width, args.height, args.inference_resolution),
                         ("msmf", 1920, 1080, None))

    def test_invalid_alpha(self):
        for value in (0, -.1, 1.01, "invalid", float("nan"), float("inf")):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    LandmarkSmoother(alpha=value)
                with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                    tracker.parse_args(["--smoothing-alpha", str(value)])

    def test_xyz_ema_and_raw_result_preservation(self):
        smoother = LandmarkSmoother(alpha=.75)
        first = one_hand(.50, y=.60, z=.10)
        self.assertIs(smoother.apply(first, 0), first)
        raw = one_hand(.52, y=.62, z=.14)
        filtered = smoother.apply(raw, 35)
        self.assertIsNot(filtered, raw)
        self.assertAlmostEqual(filtered.hand_landmarks[0][0].x, .515)
        self.assertAlmostEqual(filtered.hand_landmarks[0][0].y, .615)
        self.assertAlmostEqual(filtered.hand_landmarks[0][0].z, .130)
        self.assertEqual(raw.hand_landmarks[0][0].x, .52)
        self.assertIs(filtered.handedness, raw.handedness)
        self.assertEqual(len(filtered.hand_landmarks[0]), 21)

    def test_sudden_movement_is_immediate_and_reseeds_history(self):
        smoother = LandmarkSmoother(alpha=.5)
        smoother.apply(one_hand(.2), 0)
        jump = one_hand(.7)
        self.assertIs(smoother.apply(jump, 35), jump)
        next_frame = smoother.apply(one_hand(.72), 70)
        self.assertAlmostEqual(next_frame.hand_landmarks[0][0].x, .71)

    def test_single_fingertip_jump_bypasses_ema_even_if_wrist_stays_still(self):
        smoother = LandmarkSmoother(alpha=.5)
        smoother.apply(one_hand(.5), 0)
        raw = one_hand(.5)
        raw.hand_landmarks[0][8].x = .65
        self.assertIs(smoother.apply(raw, 35), raw)

    def test_real_mediapipe_result_container_is_copied_without_mutation(self):
        from mediapipe.tasks.python.components.containers.category import Category
        from mediapipe.tasks.python.components.containers.landmark import NormalizedLandmark
        from mediapipe.tasks.python.vision.hand_landmarker import HandLandmarkerResult

        def native_result(x):
            return HandLandmarkerResult(
                handedness=[[Category(index=1, score=.95, category_name="Left")]],
                hand_landmarks=[[NormalizedLandmark(x=x, y=.6, z=0)] * 21],
                hand_world_landmarks=[],
            )

        smoother = LandmarkSmoother(alpha=.75)
        smoother.apply(native_result(.5), 0)
        raw = native_result(.52)
        displayed = smoother.apply(raw, 35)
        self.assertIsInstance(displayed, HandLandmarkerResult)
        self.assertAlmostEqual(displayed.hand_landmarks[0][0].x, .515)
        self.assertEqual(raw.hand_landmarks[0][0].x, .52)
        self.assertIs(displayed.hand_world_landmarks, raw.hand_world_landmarks)

    def test_exactly_unchanged_measurement_snaps_to_raw_without_a_dead_zone(self):
        smoother = LandmarkSmoother(alpha=.5)
        smoother.apply(one_hand(.50), 0)
        smoother.apply(one_hand(.52), 35)
        same = one_hand(.52)
        self.assertIs(smoother.apply(same, 70), same)

    def test_loss_and_reappearance_do_not_hold_or_blend_missing_detections(self):
        smoother = LandmarkSmoother(alpha=.5)
        smoother.apply(one_hand(.50), 0)
        smoother.apply(one_hand(.52), 35)
        missing = result()
        self.assertIs(smoother.apply(missing, 70), missing)
        returned = one_hand(.53)
        self.assertIs(smoother.apply(returned, 105), returned)

    def test_independent_histories_survive_detection_order_changes(self):
        smoother = LandmarkSmoother(alpha=.5)
        smoother.apply(result([hand(.2), hand(.8)], [[category("Left")], [category("Right")]]), 0)
        swapped = result([hand(.78), hand(.22)], [[category("Right")], [category("Left")]])
        filtered = smoother.apply(swapped, 35)
        self.assertAlmostEqual(filtered.hand_landmarks[0][0].x, .79)
        self.assertAlmostEqual(filtered.hand_landmarks[1][0].x, .21)
        # Right disappears; Left's own history continues, and a returning Right is raw.
        left = smoother.apply(one_hand(.24), 70)
        self.assertAlmostEqual(left.hand_landmarks[0][0].x, .225)
        returned = result([hand(.76), hand(.26)], [[category("Right")], [category("Left")]])
        filtered = smoother.apply(returned, 105)
        self.assertEqual(filtered.hand_landmarks[0][0].x, .76)
        self.assertAlmostEqual(filtered.hand_landmarks[1][0].x, .2425)

    def test_unknown_duplicate_low_confidence_predictions_clear_history(self):
        ambiguous = [one_hand(.51, label="Unknown"), one_hand(.51, score=.7),
                     result([hand(.51), hand(.8)], [[category("Left")], [category("Left")]]),
                     result([hand(.51)], [])]
        for frame in ambiguous:
            with self.subTest(frame=frame):
                smoother = LandmarkSmoother(alpha=.5)
                smoother.apply(one_hand(.5), 0)
                self.assertIs(smoother.apply(frame, 35), frame)
                returned = one_hand(.52)
                self.assertIs(smoother.apply(returned, 70), returned)

    def test_large_jumps_after_confident_label_swap_do_not_blend_histories(self):
        smoother = LandmarkSmoother(alpha=.5)
        smoother.apply(result([hand(.2), hand(.8)], [[category("Left")], [category("Right")]]), 0)
        swapped_predictions = result([hand(.21), hand(.79)], [[category("Right")], [category("Left")]])
        displayed = smoother.apply(swapped_predictions, 35)
        self.assertIs(displayed, swapped_predictions)
        self.assertEqual([landmarks[0].x for landmarks in displayed.hand_landmarks], [.21, .79])

    def test_close_or_overlapping_hands_bypass_and_clear_history(self):
        for overlap in (False, True):
            with self.subTest(overlap=overlap):
                smoother = LandmarkSmoother(alpha=.5)
                smoother.apply(result([hand(.2), hand(.8)], [[category("Left")], [category("Right")]]), 0)
                first, second = hand(.48), hand(.52)
                if overlap:
                    # Far wrists but overlapping bounding boxes.
                    first, second = hand(.2), hand(.8)
                    first[1] = SimpleNamespace(x=.7, y=.8, z=0)
                    second[1] = SimpleNamespace(x=.3, y=.4, z=0)
                frame = result([first, second], [[category("Left")], [category("Right")]])
                self.assertIs(smoother.apply(frame, 35), frame)
                separated = result([hand(.21), hand(.79)], [[category("Left")], [category("Right")]])
                self.assertIs(smoother.apply(separated, 70), separated)

    def test_frame_gap_clock_regression_shape_change_and_explicit_reset(self):
        for reset in ("gap", "clock", "shape", "explicit"):
            with self.subTest(reset=reset):
                smoother = LandmarkSmoother(alpha=.5)
                smoother.apply(one_hand(.5), 0, (1080, 1920))
                smoother.apply(one_hand(.52), 35, (1080, 1920))
                if reset == "explicit":
                    smoother.reset()
                now = 35 + MAX_HISTORY_GAP_MS + 1 if reset == "gap" else (34 if reset == "clock" else 70)
                shape = (720, 1280) if reset == "shape" else (1080, 1920)
                current = one_hand(.53)
                self.assertIs(smoother.apply(current, now, shape), current)

    def test_disabled_and_alpha_one_return_the_original_object(self):
        for smoother in (LandmarkSmoother(enabled=False), LandmarkSmoother(alpha=1)):
            for index, x in enumerate((.5, .52, .53)):
                raw = one_hand(x)
                self.assertIs(smoother.apply(raw, index * 35), raw)
        smoother = LandmarkSmoother()
        smoother.apply(one_hand(.5), 0)
        smoother.enabled = False
        smoother.apply(one_hand(.52), 35)
        smoother.enabled = True
        current = one_hand(.53)
        self.assertIs(smoother.apply(current, 70), current)

    def test_invalid_landmarks_clear_state_and_leave_raw_data_untouched(self):
        for landmarks in ([], hand(.5)[:20], hand(float("nan")), hand(.5, z=float("inf"))):
            smoother = LandmarkSmoother()
            smoother.apply(one_hand(.5), 0)
            raw = result([landmarks], [[category("Left")]])
            self.assertIs(smoother.apply(raw, 35), raw)
            returned = one_hand(.52)
            self.assertIs(smoother.apply(returned, 70), returned)

    def test_preview_raw_comparison_uses_raw_locations_without_stale_markers(self):
        frame = np.full((480, 640, 3), 120, dtype=np.uint8)
        raw = one_hand(.52)
        smoother = LandmarkSmoother(alpha=.5)
        smoother.apply(one_hand(.50), 0)
        filtered = smoother.apply(raw, 35)
        with patch.object(cv2, "drawMarker") as markers:
            make_preview(frame, filtered, 28, True, raw_result=raw)
        self.assertEqual(markers.call_count, 21)
        self.assertEqual(markers.call_args.args[1], hand_overlays(raw, 640, 480)[0].points[0])
        self.assertNotEqual(markers.call_args.args[1], hand_overlays(filtered, 640, 480)[0].points[0])
        with patch.object(cv2, "drawMarker") as markers:
            make_preview(frame, result(), 28, False, raw_result=result())
        markers.assert_not_called()

    def test_pipeline_profiles_smoothing_and_preserves_raw_inference_result(self):
        cap, detector, mp = MagicMock(), MagicMock(), MagicMock()
        cap.read.return_value = (True, np.zeros((480, 640, 3), dtype=np.uint8))
        raw_first, raw_second = one_hand(.5), one_hand(.52)
        detector.detect_for_video.side_effect = [raw_first, raw_second]
        report = {}
        previews = []

        def preview(frame, result, fps, show_help, **kwargs):
            previews.append((result, kwargs["raw_result"]))
            return frame

        args = tracker.parse_args(["--show-raw-landmarks", "--gui-mode", "waitkey"])
        with patch.object(tracker.cv2, "imshow"), \
                patch.object(tracker.cv2, "waitKey", side_effect=[-1, ord("q")]), \
                patch.object(tracker.cv2, "getWindowProperty", return_value=1), \
                patch.object(tracker, "make_preview", side_effect=preview), \
                self.assertLogs(tracker.LOGGER):
            self.assertEqual(tracker.process_frames(cap, detector, mp, args, report), 0)
        self.assertEqual(report["timings"]["smoothing"]["count"], 2)
        self.assertIs(previews[1][1], raw_second)
        self.assertAlmostEqual(previews[1][0].hand_landmarks[0][0].x, .515)
        self.assertEqual(raw_second.hand_landmarks[0][0].x, .52)


if __name__ == "__main__":
    unittest.main()
