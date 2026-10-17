from dataclasses import FrozenInstanceError
import math
import unittest

from gestures.features import extract_features, extract_frame_features
from gestures.models import (
    Finger, FrameObservation, HandednessPrediction, HandObservation, ImageSize, Landmark, LandmarkIndex,
)
from .fixtures import synthetic_hand, transform


I = LandmarkIndex


class FeatureTest(unittest.TestCase):
    def test_known_palm_fingertip_distances_and_thumb_index_ratio(self):
        hand = synthetic_hand()
        features = extract_features(hand)
        self.assertEqual(features.palm_scale, 2)
        self.assertAlmostEqual(features.thumb_index_distance, math.sqrt(34))
        self.assertAlmostEqual(features.thumb_index_ratio, math.sqrt(34) / 2)
        self.assertAlmostEqual(features.finger(Finger.INDEX).tip_to_wrist_ratio, math.sqrt(26) / 2)
        self.assertEqual(features.finger(Finger.THUMB).tip_to_wrist_ratio, 2)
        self.assertEqual(features.finger(Finger.MIDDLE).tip_to_wrist_ratio, 2.5)
        self.assertIs(features.observation, hand)

    def test_each_finger_has_named_angles_and_straightness_measurements(self):
        features = extract_features(synthetic_hand())
        self.assertEqual({finger.finger for finger in features.fingers}, set(Finger))
        for finger in features.fingers:
            self.assertAlmostEqual(finger.joint_angle_degrees, 180)
            self.assertAlmostEqual(finger.distal_angle_degrees, 180)
            self.assertAlmostEqual(finger.straightness_ratio, 1)

    def test_bent_chain_has_known_angles_and_continuous_extension_measure(self):
        points = list(synthetic_hand().landmarks)
        points[I.INDEX_FINGER_DIP] = Landmark(0, 3, 0)
        points[I.INDEX_FINGER_TIP] = Landmark(0, 4, 0)
        finger = extract_features(HandObservation(points)).finger(Finger.INDEX)
        self.assertEqual(finger.joint_angle_degrees, 90)
        self.assertEqual(finger.distal_angle_degrees, 90)
        self.assertAlmostEqual(finger.straightness_ratio, math.sqrt(5) / 3)
        self.assertEqual(finger.tip_to_wrist_ratio, 2)

    def test_translation_and_uniform_scaling_preserve_dimensionless_features(self):
        hand = synthetic_hand()
        base = extract_features(hand)
        for scale in (.01, .5, 3):
            features = extract_features(transform(hand, scale, (5, 3, 1)))
            self.assertAlmostEqual(features.palm_scale, scale * base.palm_scale)
            self.assertAlmostEqual(features.thumb_index_distance, scale * base.thumb_index_distance)
            self.assertAlmostEqual(features.thumb_index_ratio, base.thumb_index_ratio)
            for finger in Finger:
                actual, expected = features.finger(finger), base.finger(finger)
                self.assertAlmostEqual(actual.tip_to_wrist_ratio, expected.tip_to_wrist_ratio)
                self.assertAlmostEqual(actual.joint_angle_degrees, expected.joint_angle_degrees)
                self.assertAlmostEqual(actual.distal_angle_degrees, expected.distal_angle_degrees)
                self.assertAlmostEqual(actual.straightness_ratio, expected.straightness_ratio)

    def test_planar_rotation_in_same_units_preserves_distances_and_angles(self):
        hand = synthetic_hand()
        base = extract_features(hand)
        for degrees in (45, 90, 180):
            radians = math.radians(degrees)
            cosine, sine = math.cos(radians), math.sin(radians)
            rotated = HandObservation(tuple(Landmark(p.x * cosine - p.y * sine,
                                                       p.x * sine + p.y * cosine, p.z)
                                             for p in hand.landmarks))
            actual = extract_features(rotated)
            self.assertAlmostEqual(actual.thumb_index_ratio, base.thumb_index_ratio)
            self.assertAlmostEqual(actual.palm_scale, base.palm_scale)
            self.assertAlmostEqual(actual.finger(Finger.INDEX).joint_angle_degrees, 180, places=5)

    def test_aspect_correct_features_match_common_axis_reference(self):
        hand = synthetic_hand()
        size = ImageSize(1920, 1080)
        # Encode the same plane with y normalized by image height instead of width.
        normalized = HandObservation(tuple(Landmark(p.x, p.y * size.width / size.height, p.z)
                                             for p in hand.landmarks))
        expected, actual = extract_features(hand), extract_features(normalized, image_size=size)
        self.assertAlmostEqual(actual.palm_scale, expected.palm_scale)
        self.assertAlmostEqual(actual.thumb_index_ratio, expected.thumb_index_ratio)
        self.assertEqual(actual.image_size, size)
        self.assertNotAlmostEqual(extract_features(normalized).thumb_index_ratio, expected.thumb_index_ratio)

    def test_foreshortening_changes_2d_features_and_is_not_rotation_invariance(self):
        hand = synthetic_hand()
        tilted_projection = HandObservation(tuple(Landmark(p.x, .25 * p.y, p.z) for p in hand.landmarks))
        self.assertNotAlmostEqual(extract_features(hand).thumb_index_ratio,
                                  extract_features(tilted_projection).thumb_index_ratio)

    def test_degenerate_hand_and_joint_return_none_without_stale_state(self):
        collapsed = HandObservation((Landmark(.5, .5, 0),) * 21)
        features = extract_features(collapsed)
        self.assertEqual(features.palm_scale, 0)
        self.assertEqual(features.thumb_index_distance, 0)
        self.assertIsNone(features.thumb_index_ratio)
        for finger in features.fingers:
            self.assertIsNone(finger.tip_to_wrist_ratio)
            self.assertIsNone(finger.joint_angle_degrees)
            self.assertIsNone(finger.distal_angle_degrees)
            self.assertIsNone(finger.straightness_ratio)
        points = list(synthetic_hand().landmarks)
        points[I.INDEX_FINGER_PIP] = points[I.INDEX_FINGER_MCP]
        self.assertIsNone(extract_features(HandObservation(points)).finger(Finger.INDEX).joint_angle_degrees)
        self.assertIsNotNone(extract_features(synthetic_hand()).finger(Finger.INDEX).joint_angle_degrees)

    def test_independent_hands_order_changes_and_missing_detections(self):
        left = synthetic_hand()
        right = HandObservation(transform(left, .5).landmarks, (HandednessPrediction("Right", .9),))
        for hands in ((), (left,), (left, right), (right, left), (), (right,)):
            frame = FrameObservation(50, hands, ImageSize(1920, 1080))
            features = extract_frame_features(frame)
            self.assertIs(features.observation, frame)
            self.assertEqual(len(features.hands), len(hands))
            for actual, expected_hand in zip(features.hands, hands):
                self.assertIs(actual.observation, expected_hand)
                self.assertEqual(actual, extract_features(expected_hand, image_size=frame.image_size))

    def test_outputs_are_immutable_and_input_observations_untouched(self):
        hand = synthetic_hand()
        points = hand.landmarks
        features = extract_features(hand)
        self.assertIs(hand.landmarks, points)
        for target, field, value in ((features, "palm_scale", 99),
                                      (features.finger(Finger.INDEX), "straightness_ratio", 0)):
            with self.assertRaises(FrozenInstanceError):
                setattr(target, field, value)
        with self.assertRaises(ValueError):
            features.finger("not-a-finger")


if __name__ == "__main__":
    unittest.main()
