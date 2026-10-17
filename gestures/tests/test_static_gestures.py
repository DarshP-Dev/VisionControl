from dataclasses import FrozenInstanceError, replace
import math
import unittest

from gestures.features import extract_features, extract_frame_features
from gestures.models import Finger, FrameObservation, HandObservation, Landmark, LandmarkIndex
from gestures.static_gestures import (
    DEFAULT_THRESHOLDS, Gesture, StaticThresholds, classify_frame, classify_hand,
)
from .static_fixtures import SIZE, pose_hand


ALL = (Finger.INDEX, Finger.MIDDLE, Finger.RING, Finger.PINKY)
OTHERS = (Finger.MIDDLE, Finger.RING, Finger.PINKY)


def recognize(hand: HandObservation):
    return classify_hand(extract_features(hand, image_size=SIZE), 123)


class StaticGestureTest(unittest.TestCase):
    def test_open_palm_naturally_bent_fingers_both_hands_sizes_and_rotation(self):
        for side in ("Left", "Right"):
            for scale in (.025, .07, .11):
                for rotation in (0, 45, 90, 135, 180):
                    with self.subTest(side=side, scale=scale, rotation=rotation):
                        hand = pose_hand(side=side, scale=scale, rotation=rotation)
                        actual = recognize(hand)
                        self.assertEqual(actual.gesture, Gesture.OPEN_PALM)
                        self.assertEqual(actual.matched_rules, (Gesture.OPEN_PALM,))
                        self.assertTrue(actual.unique_rule_match)
                        self.assertEqual(actual.handedness, hand.handedness)
                        self.assertEqual(actual.timestamp_ms, 123)

    def test_fist_articulated_curled_chains_both_hands_and_sizes(self):
        for side in ("Left", "Right"):
            for scale in (.025, .07, .11):
                for rotation in (0, 45, 90, 180):
                    with self.subTest(side=side, scale=scale, rotation=rotation):
                        actual = recognize(pose_hand(curled=ALL, side=side, thumb="tucked",
                                                     scale=scale, rotation=rotation))
                        self.assertEqual(actual.gesture, Gesture.FIST)

    def test_pointing_both_hands_rotations_and_natural_thumb_variations(self):
        for side in ("Left", "Right"):
            for thumb in ("relaxed", "extended", "tucked", "collapsed"):
                for rotation in (0, 45, 90, 180):
                    with self.subTest(side=side, thumb=thumb, rotation=rotation):
                        actual = recognize(pose_hand(curled=OTHERS, side=side, thumb=thumb, rotation=rotation))
                        self.assertEqual(actual.gesture, Gesture.POINTING)

    def test_partial_closure_does_not_force_fist_or_open_palm(self):
        for partial, curled in ((ALL, ()), ((Finger.INDEX,), OTHERS),
                                 ((Finger.MIDDLE,), (Finger.INDEX, Finger.RING, Finger.PINKY))):
            actual = recognize(pose_hand(partial=partial, curled=curled))
            self.assertEqual(actual.gesture, Gesture.UNKNOWN)
            self.assertEqual(actual.reason, "ambiguous_or_unsupported_pose")
            self.assertFalse(actual.unique_rule_match)

    def test_clear_poses_with_moderate_synthetic_foreshortening(self):
        for curled, expected in (((), Gesture.OPEN_PALM), (ALL, Gesture.FIST), (OTHERS, Gesture.POINTING)):
            hand = pose_hand(curled=curled)
            wrist = hand[LandmarkIndex.WRIST]
            cosine, sine = math.cos(math.radians(20)), math.sin(math.radians(20))
            for axis in ("x", "y"):
                points = []
                for point in hand.landmarks:
                    displacement = (point.x - wrist.x if axis == "x" else
                                    (point.y - wrist.y) * SIZE.height / SIZE.width)
                    points.append(replace(
                        point, x=wrist.x + (point.x - wrist.x) * cosine if axis == "x" else point.x,
                        y=wrist.y + (point.y - wrist.y) * cosine if axis == "y" else point.y,
                        z=point.z + displacement * sine))
                with self.subTest(expected=expected, axis=axis):
                    self.assertEqual(recognize(HandObservation(points, hand.handedness)).gesture, expected)

    def test_unsupported_finger_combinations_are_unknown(self):
        for curled in ((Finger.RING, Finger.PINKY), (Finger.INDEX, Finger.MIDDLE, Finger.RING),
                        (Finger.INDEX,), (Finger.MIDDLE,)):
            self.assertEqual(recognize(pose_hand(curled=curled)).gesture, Gesture.UNKNOWN)

    def test_labels_do_not_drive_classification_and_prediction_is_not_identity(self):
        for side in (None, "Left", "Right", "unrecognized"):
            hand = pose_hand(curled=OTHERS, side=side)
            self.assertEqual(recognize(hand).gesture, Gesture.POINTING)
            self.assertEqual(recognize(hand).handedness, hand.handedness)

    def test_partially_missing_invalid_and_degenerate_features_are_unknown(self):
        base = extract_features(pose_hand(), image_size=SIZE)
        index = base.finger(Finger.INDEX)
        bad = [None, replace(base, palm_scale=0), replace(base, palm_scale=float("nan")),
               replace(base, fingers=base.fingers[:1]), replace(base, fingers=base.fingers + (index,))]
        for field, value in (("joint_angle_degrees", None), ("joint_angle_degrees", float("nan")),
                              ("distal_angle_degrees", float("inf")), ("straightness_ratio", -1),
                              ("straightness_ratio", 1.01), ("tip_to_wrist_ratio", None)):
            changed = replace(index, **{field: value})
            bad.append(replace(base, fingers=tuple(changed if f.finger == Finger.INDEX else f for f in base.fingers)))
        collapsed = HandObservation((Landmark(.5, .5, 0),) * 21)
        bad.append(extract_features(collapsed, image_size=SIZE))
        for features in bad:
            with self.subTest(features=features):
                result = classify_hand(features, 0)
                self.assertEqual(result.gesture, Gesture.UNKNOWN)
                self.assertEqual(result.reason, "invalid_or_missing_features")

    def test_conflicting_rules_with_overlapping_configuration_are_unknown(self):
        permissive = StaticThresholds(0, 0, 0, 0, 180, 180, 1, 100)
        result = classify_hand(extract_features(pose_hand(), image_size=SIZE), 0, thresholds=permissive)
        self.assertEqual(result.gesture, Gesture.UNKNOWN)
        self.assertGreater(len(result.matched_rules), 1)
        self.assertEqual(result.reason, "conflicting_rules")
        self.assertFalse(result.unique_rule_match)

    def test_multiple_measurements_reject_a_single_misleading_angle(self):
        features = extract_features(pose_hand(), image_size=SIZE)
        # One lowered joint angle alone must not turn this still-long, straight chain into a fist.
        changed = tuple(replace(f, joint_angle_degrees=60) if f.finger != Finger.THUMB else f
                        for f in features.fingers)
        actual = classify_hand(replace(features, fingers=changed), 0)
        self.assertEqual(actual.gesture, Gesture.UNKNOWN)

    def test_empty_frame_means_no_observation_and_order_stays_frame_local(self):
        opened = pose_hand()
        pointed = pose_hand(curled=OTHERS, side="Right")
        for hands, expected in (((), ()), ((opened,), (Gesture.OPEN_PALM,)),
                                ((opened, pointed), (Gesture.OPEN_PALM, Gesture.POINTING)),
                                ((pointed, opened), (Gesture.POINTING, Gesture.OPEN_PALM)), ((), ())):
            frame = FrameObservation(44, hands, SIZE)
            output = classify_frame(extract_frame_features(frame))
            self.assertEqual(tuple(item.gesture for item in output), expected)
            self.assertEqual(tuple(item.handedness for item in output), tuple(hand.handedness for hand in hands))

    def test_timestamp_and_threshold_validation_and_result_immutability(self):
        features = extract_features(pose_hand(), image_size=SIZE)
        for stamp in (-1, 1.5, True):
            with self.assertRaises(ValueError):
                classify_hand(features, stamp)
        for kwargs in ({"extended_joint_min_degrees": float("nan")},
                       {"extended_joint_min_degrees": 181}, {"curled_straightness_max": 1.1},
                       {"extended_tip_to_wrist_min": -1}, {"curled_distal_max_degrees": True}):
            with self.assertRaises(ValueError):
                StaticThresholds(**kwargs)
        with self.assertRaises(FrozenInstanceError):
            recognize(pose_hand()).gesture = Gesture.FIST
        self.assertLess(DEFAULT_THRESHOLDS.curled_joint_max_degrees,
                        DEFAULT_THRESHOLDS.extended_joint_min_degrees)


if __name__ == "__main__":
    unittest.main()
