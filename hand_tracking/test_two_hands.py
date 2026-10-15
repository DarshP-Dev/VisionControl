"""Phase 2.2 tests: per-result hand pairing, rendering and performance warnings."""

from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

import cv2
import numpy as np

from . import hand_tracker as tracker
from .tracking_utils import (
    ALTERNATE_COLOR, HAND_COLORS, HAND_CONNECTIONS, ONE_HAND_REFERENCE_FPS,
    hand_overlays, handedness_label, make_preview, significant_fps_drop,
)


def landmarks(x, y=.65):
    return [SimpleNamespace(x=x, y=y) for _ in range(21)]


def category(name, score=.95):
    return SimpleNamespace(category_name=name, score=score)


def result(hands=(), predictions=()):
    return SimpleNamespace(hand_landmarks=list(hands), handedness=list(predictions))


class TwoHandTest(unittest.TestCase):
    def test_zero_one_and_two_hands_preserve_all_landmarks(self):
        self.assertEqual(hand_overlays(result(), 101, 101), [])
        for count in (1, 2):
            with self.subTest(count=count):
                detection = result([landmarks(.2), landmarks(.8)][:count],
                                   [[category("Left")], [category("Right")]][:count])
                data = hand_overlays(detection, 101, 101)
                self.assertEqual(len(data), count)
                self.assertTrue(all(len(hand.points) == 21 for hand in data))
                self.assertEqual(data[0].label, "Left")
                self.assertEqual(data[0].color, HAND_COLORS["Left"])
                if count == 2:
                    self.assertEqual(data[1].label, "Right")
                    self.assertEqual(data[1].color, HAND_COLORS["Right"])
                    self.assertNotEqual(data[0].color, data[1].color)

    def test_handedness_is_paired_per_frame_despite_order_changes(self):
        left, right = landmarks(.2), landmarks(.8)
        first = hand_overlays(result([left, right], [[category("Left")], [category("Right")]]), 101, 101)
        second = hand_overlays(result([right, left], [[category("Right")], [category("Left")]]), 101, 101)
        self.assertEqual({hand.label: (hand.color, hand.points) for hand in first},
                         {hand.label: (hand.color, hand.points) for hand in second})
        # Crossing changes screen position, not the association with the prediction.
        crossed = hand_overlays(result([right, left], [[category("Left")], [category("Right")]]), 101, 101)
        self.assertEqual([(hand.label, hand.points[0]) for hand in crossed],
                         [("Left", (80, 65)), ("Right", (20, 65))])

    def test_missing_handedness_and_top_score_handling(self):
        self.assertEqual(handedness_label([category("Left", .7), category("Right", .9)]), "Right")
        for categories in ([], [category("invalid")], [category("Left", float("nan"))]):
            self.assertEqual(handedness_label(categories), "Unknown")
        data = hand_overlays(result([landmarks(.2), landmarks(.8)], [[category("Left")]]), 101, 101)
        self.assertEqual([hand.label for hand in data], ["Left", "Unknown"])
        data = hand_overlays(SimpleNamespace(hand_landmarks=[landmarks(.5)]), 101, 101)
        self.assertEqual(data[0].label, "Unknown")

    def test_duplicate_predictions_do_not_drop_a_hand(self):
        data = hand_overlays(result([landmarks(.2), landmarks(.8)],
                                    [[category("Left")], [category("Left")]]), 101, 101)
        self.assertEqual([hand.label for hand in data], ["Left", "Left"])
        self.assertNotEqual(data[0].color, data[1].color)
        self.assertEqual(data[1].color, ALTERNATE_COLOR)

    def test_rendering_draws_both_hands_and_wrist_labels(self):
        frame = np.full((480, 640, 3), 120, dtype=np.uint8)
        detection = result([landmarks(.2), landmarks(.8)], [[category("Left")], [category("Right")]])
        with patch.object(cv2, "line") as line, patch.object(cv2, "circle") as circle, \
                patch.object(cv2, "putText") as text:
            make_preview(frame, detection, 30, False)
        self.assertEqual(line.call_count, 2 * len(HAND_CONNECTIONS))
        self.assertEqual(circle.call_count, 84)
        calls = text.call_args_list
        self.assertEqual([call.args[1] for call in calls[:2]], ["Left hand", "Right hand"])
        self.assertEqual(calls[0].args[5], HAND_COLORS["Left"])
        self.assertEqual(calls[1].args[5], HAND_COLORS["Right"])
        self.assertIn("Hands: 2", calls[-1].args[1])
        self.assertEqual(line.call_args_list[0].args[1], (128, 311))
        self.assertEqual(line.call_args_list[-1].args[1], (511, 311))
        self.assertTrue(np.all(frame == 120))

    def test_loss_reentry_and_rapid_position_changes_leave_no_stale_overlays(self):
        frame = np.full((480, 640, 3), 120, dtype=np.uint8)
        empty = make_preview(frame, result(), 30, False)
        sequences = (
            result([landmarks(.1), landmarks(.9)], [[category("Left")], [category("Right")]]),
            result([landmarks(.9)], [[category("Left")]]),
            result(),
            result([landmarks(.1)], [[category("Right")]]),
            result(),
        )
        for detection in sequences:
            preview = make_preview(frame, detection, 30, False)
            if not detection.hand_landmarks:
                np.testing.assert_array_equal(preview, empty)
            else:
                self.assertFalse(np.array_equal(preview[30:], empty[30:]))
        self.assertEqual(hand_overlays(SimpleNamespace(hand_landmarks=None), 640, 480), [])

    def test_malformed_detection_does_not_hide_valid_other_hand(self):
        for invalid in (None, [], landmarks(.2)[:20], landmarks(float("nan"))):
            data = hand_overlays(result([invalid, landmarks(.8)],
                                        [[category("Left")], [category("Right")]]), 101, 101)
            self.assertEqual([hand.label for hand in data], ["Right"])

    def test_significant_performance_drop_threshold(self):
        self.assertTrue(significant_fps_drop(20))
        self.assertFalse(significant_fps_drop(ONE_HAND_REFERENCE_FPS * .75))
        self.assertFalse(significant_fps_drop(35.81))
        self.assertFalse(significant_fps_drop(None))

    def test_loop_logs_two_hands_and_reports_slow_windows(self):
        detection = result([landmarks(.2), landmarks(.8)], [[category("Left")], [category("Right")]])
        cap, detector, mp = MagicMock(), MagicMock(), MagicMock()
        cap.read.return_value = (True, np.zeros((80, 100, 3), dtype=np.uint8))
        detector.detect_for_video.return_value = detection
        with patch.object(tracker, "ApplicationFPS") as fps, \
                patch.object(tracker.cv2, "imshow"), \
                patch.object(tracker.cv2, "waitKey", return_value=ord("q")), \
                self.assertLogs(tracker.LOGGER, level="INFO") as logs:
            fps.return_value.current = 20.0
            fps.return_value.frames = 0
            fps.return_value.record.return_value = 20.0
            fps.return_value.average.return_value = 20.0
            self.assertEqual(tracker.process_frames(cap, detector, mp), 0)
        output = "\n".join(logs.output)
        self.assertIn("hands: 2", output)
        self.assertIn("Significant application FPS decrease", output)


if __name__ == "__main__":
    unittest.main()
