from copy import deepcopy
from types import SimpleNamespace
import unittest

from gestures.landmarks import from_mediapipe, to_image_coordinates
from gestures.models import HandSide, ImageSize, Landmark, LandmarkIndex
from .fixtures import category, mediapipe_result, synthetic_hand, transform


class AdapterTest(unittest.TestCase):
    def test_zero_one_two_hands_and_landmark_order(self):
        first, second = synthetic_hand(), transform(synthetic_hand(), .5, (2, 0, 0))
        for count in range(3):
            hands = (first, second)[:count]
            frame = from_mediapipe(mediapipe_result(hands), 50, ImageSize(1920, 1080))
            self.assertEqual(frame.hands, hands)
            self.assertEqual(frame.timestamp_ms, 50)
            self.assertEqual(frame.image_size, ImageSize(1920, 1080))

    def test_detection_order_changes_do_not_reassociate_handedness(self):
        left, right = synthetic_hand(), transform(synthetic_hand(), .2, (1, 0, 0))
        first = from_mediapipe(mediapipe_result((left, right), [[category("Left")], [category("Right")]]), 0)
        second = from_mediapipe(mediapipe_result((right, left), [[category("Right")], [category("Left")]]), 1)
        by_prediction = lambda frame: {hand.handedness[0].side: hand.landmarks for hand in frame.hands}
        self.assertEqual(by_prediction(first), by_prediction(second))
        self.assertEqual(second.hands[0].landmarks, right.landmarks)

    def test_missing_partial_unknown_low_confidence_and_duplicate_handedness(self):
        hand = synthetic_hand()
        raw = SimpleNamespace(hand_landmarks=mediapipe_result((hand,)).hand_landmarks)
        self.assertEqual(from_mediapipe(raw, 0).hands[0].handedness, ())
        cases = (None, [], [None], [[category("Left", .1)]],
                 [[category("other", .4)]], [[category("Left")], [category("Left")]])
        for predictions in cases:
            with self.subTest(predictions=predictions):
                frame = from_mediapipe(mediapipe_result((hand, hand), predictions), 0)
                self.assertEqual(len(frame.hands), 2)
                if predictions and predictions[0]:
                    self.assertEqual(frame.hands[0].handedness[0].score, predictions[0][0].score)
        frame = from_mediapipe(mediapipe_result((hand,), [[category("unknown", .1)]]), 0)
        self.assertEqual(frame.hands[0].handedness[0].side, HandSide.UNKNOWN)

    def test_preserves_all_valid_categories_without_identity_or_threshold_decision(self):
        predictions = [category("Left", .51), category("Right", .49), category("unrecognized", None)]
        frame = from_mediapipe(mediapipe_result((synthetic_hand(),), [predictions]), 0)
        self.assertEqual([p.category_name for p in frame.hands[0].handedness],
                         ["Left", "Right", "unrecognized"])
        self.assertIsNone(frame.hands[0].handedness[-1].score)

    def test_bad_optional_metadata_is_discarded_without_losing_geometry(self):
        raw = mediapipe_result((synthetic_hand(),), [[category("Left", float("nan")),
                                                    category("Right", 2), category("Left", .9)]])
        frame = from_mediapipe(raw, 0)
        self.assertEqual(len(frame.hands[0].handedness), 1)
        self.assertEqual(frame.hands[0].handedness[0].score, .9)
        self.assertEqual(frame.hands[0].landmarks, synthetic_hand().landmarks)

    def test_input_is_unchanged_and_snapshot_is_independent(self):
        raw = mediapipe_result((synthetic_hand(),), [[category("Left")]])
        raw.hand_landmarks[0][0].visibility = .8
        raw.hand_landmarks[0][0].presence = .7
        before = deepcopy(raw)
        frame = from_mediapipe(raw, 0)
        self.assertEqual(raw, before)
        raw.hand_landmarks[0][0].x = 99
        raw.handedness[0][0].score = .01
        raw.hand_landmarks[0].clear()
        self.assertEqual(frame.hands[0][LandmarkIndex.WRIST].x, 0)
        self.assertEqual(frame.hands[0][LandmarkIndex.WRIST].visibility, .8)
        self.assertEqual(frame.hands[0][LandmarkIndex.WRIST].presence, .7)
        self.assertEqual(frame.hands[0].handedness[0].score, .95)

    def test_missing_invalid_nonfinite_and_extra_geometry_fail_explicitly(self):
        bad_results = [None, SimpleNamespace(), SimpleNamespace(hand_landmarks=None),
                       SimpleNamespace(hand_landmarks=""), mediapipe_result((synthetic_hand(),) * 3)]
        raw = mediapipe_result((synthetic_hand(),))
        raw.hand_landmarks[0].pop()
        bad_results.append(raw)
        for value in (None, float("nan"), "0.1"):
            raw = mediapipe_result((synthetic_hand(),))
            raw.hand_landmarks[0][0].x = value
            bad_results.append(raw)
        raw = mediapipe_result((synthetic_hand(),))
        del raw.hand_landmarks[0][0].z
        bad_results.append(raw)
        for raw in bad_results:
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                from_mediapipe(raw, 0)

    def test_continuous_image_coordinates_are_unmirrored_and_explicitly_clipped(self):
        size = ImageSize(1920, 1080)
        self.assertEqual(to_image_coordinates(Landmark(.25, .75, -.2), size), (480, 810))
        self.assertEqual(to_image_coordinates(Landmark(1, 1, 0), size), (1920, 1080))
        point = Landmark(-.01, 1.02, 0)
        x, y = to_image_coordinates(point, size)
        self.assertLess(x, 0)
        self.assertGreater(y, 1080)
        self.assertEqual(to_image_coordinates(point, size, clip=True), (0, 1079))
        self.assertEqual(to_image_coordinates(Landmark(1, 1, 0), ImageSize(1, 1), clip=True), (0, 0))
        self.assertEqual(point, Landmark(-.01, 1.02, 0))
        for bad_point, bad_size, clip in ((None, size, False), (point, None, False),
                                           (point, size, "false")):
            with self.assertRaises(ValueError):
                to_image_coordinates(bad_point, bad_size, clip=clip)


if __name__ == "__main__":
    unittest.main()
