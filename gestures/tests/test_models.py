from dataclasses import FrozenInstanceError
import unittest

from gestures.models import (
    Finger, FrameObservation, HandednessPrediction, HandObservation, HandSide, ImageSize,
    Landmark, LandmarkIndex,
)
from .fixtures import synthetic_hand


class ModelTest(unittest.TestCase):
    def test_official_index_sequence_and_key_points(self):
        names = ("WRIST", "THUMB_CMC", "THUMB_MCP", "THUMB_IP", "THUMB_TIP",
                 "INDEX_FINGER_MCP", "INDEX_FINGER_PIP", "INDEX_FINGER_DIP", "INDEX_FINGER_TIP",
                 "MIDDLE_FINGER_MCP", "MIDDLE_FINGER_PIP", "MIDDLE_FINGER_DIP", "MIDDLE_FINGER_TIP",
                 "RING_FINGER_MCP", "RING_FINGER_PIP", "RING_FINGER_DIP", "RING_FINGER_TIP",
                 "PINKY_MCP", "PINKY_PIP", "PINKY_DIP", "PINKY_TIP")
        self.assertEqual([(index.name, index.value) for index in LandmarkIndex],
                         [(name, index) for index, name in enumerate(names)])
        self.assertEqual([LandmarkIndex.WRIST, LandmarkIndex.THUMB_TIP, LandmarkIndex.INDEX_FINGER_TIP,
                          LandmarkIndex.MIDDLE_FINGER_TIP, LandmarkIndex.RING_FINGER_TIP,
                          LandmarkIndex.PINKY_TIP], [0, 4, 8, 12, 16, 20])
        self.assertEqual(len(Finger), 5)

    def test_complete_set_named_access_and_immutable_snapshot(self):
        points = list(synthetic_hand().landmarks)
        predictions = [HandednessPrediction("Left", .51)]
        hand = HandObservation(points, predictions)
        points.clear()
        predictions.clear()
        self.assertEqual(len(hand.landmarks), 21)
        self.assertEqual(hand[LandmarkIndex.THUMB_TIP], Landmark(-4, 0, 0))
        self.assertEqual(hand.handedness[0].score, .51)
        for target, name, value in ((hand, "landmarks", ()), (hand[0], "x", 3),
                                     (hand.handedness[0], "score", 1)):
            with self.assertRaises(FrozenInstanceError):
                setattr(target, name, value)

    def test_missing_extra_and_malformed_points_are_rejected(self):
        points = synthetic_hand().landmarks
        for invalid in ((), points[:-1], points + (points[0],), [None] * 21, None, "", {}):
            with self.subTest(invalid=type(invalid)), self.assertRaises(ValueError):
                HandObservation(invalid)
        with self.assertRaises(ValueError):
            HandObservation(points, ["Left"])

    def test_invalid_and_negative_landmark_indices_are_rejected(self):
        hand = synthetic_hand()
        for index in (-1, 21, 1.0, True, "WRIST", None):
            with self.subTest(index=index), self.assertRaises(ValueError):
                hand[index]

    def test_coordinate_validation_keeps_finite_outside_values_and_depth(self):
        self.assertEqual(Landmark(-.01, 1.02, -.3), Landmark(-.01, 1.02, -.3))
        for field in ("x", "y", "z", "visibility", "presence"):
            for invalid in (float("nan"), float("inf"), -float("inf"), "1", True):
                values = dict(x=0, y=0, z=0)
                values[field] = invalid
                with self.subTest(field=field, invalid=invalid), self.assertRaises(ValueError):
                    Landmark(**values)
        for field in ("x", "y", "z"):
            values = dict(x=0, y=0, z=0)
            values[field] = None
            with self.assertRaises(ValueError):
                Landmark(**values)

    def test_optional_confidence_is_not_invented(self):
        point = Landmark(0, 0, 0)
        self.assertIsNone(point.visibility)
        self.assertIsNone(point.presence)
        self.assertEqual(Landmark(0, 0, 0, .9, .8).presence, .8)
        self.assertEqual(HandednessPrediction("Left", .2).side, HandSide.LEFT)
        self.assertEqual(HandednessPrediction("Right").side, HandSide.RIGHT)
        self.assertEqual(HandednessPrediction("other", .3).side, HandSide.UNKNOWN)
        self.assertEqual(HandednessPrediction().side, HandSide.UNKNOWN)
        self.assertEqual(synthetic_hand().handedness, ())
        for score in (-.01, 1.01, float("nan"), "0.9", True):
            with self.assertRaises(ValueError):
                HandednessPrediction("Left", score)
        with self.assertRaises(ValueError):
            HandednessPrediction(3)

    def test_frame_cardinality_timestamp_and_image_validation(self):
        hand = synthetic_hand()
        for count in range(3):
            frame = FrameObservation(123, [hand] * count, ImageSize(1920, 1080))
            self.assertEqual(len(frame.hands), count)
            self.assertIsInstance(frame.hands, tuple)
            self.assertEqual(frame.timestamp_ms, 123)
            with self.assertRaises(FrozenInstanceError):
                frame.timestamp_ms = 0
        for hands in ([hand] * 3, [None], None, "", {}):
            with self.assertRaises(ValueError):
                FrameObservation(0, hands)
        for timestamp in (-1, .1, float("inf"), None, True):
            with self.assertRaises(ValueError):
                FrameObservation(timestamp)
        with self.assertRaises(ValueError):
            FrameObservation(0, image_size=(1920, 1080))
        for width, height in ((0, 1), (1, -1), (True, 1), (1.5, 1)):
            with self.assertRaises(ValueError):
                ImageSize(width, height)


if __name__ == "__main__":
    unittest.main()
