"""Targeted regressions from articulated chains, not overridden classification features."""

from dataclasses import replace
import unittest

from gestures import Finger, HandObservation, LandmarkIndex
from gestures.features import extract_features
from gestures.static_gestures import DEFAULT_THRESHOLDS as T, Gesture, classify_hand
from .static_fixtures import SIZE, pose_hand


OTHERS = (Finger.MIDDLE, Finger.RING, Finger.PINKY)
ALL = (Finger.INDEX,) + OTHERS


def relaxed_pointing(**kwargs) -> HandObservation:
    angles = {finger: (90, 10, -55) for finger in OTHERS}
    return pose_hand(curled=OTHERS, chain_angles=angles, **kwargs)


class PointingCalibrationTest(unittest.TestCase):
    def test_relaxed_curled_fingers_expose_original_distance_gate(self):
        features = extract_features(relaxed_pointing(), image_size=SIZE)
        for finger in OTHERS:
            item = features.finger(finger)
            self.assertLessEqual(item.joint_angle_degrees, T.curled_joint_max_degrees)
            self.assertLessEqual(item.distal_angle_degrees, T.curled_distal_max_degrees)
            self.assertLessEqual(item.straightness_ratio, T.curled_straightness_max)
            self.assertGreater(item.tip_to_wrist_ratio, T.curled_tip_to_wrist_max)
        self.assertEqual(classify_hand(features, 0).gesture, Gesture.POINTING)

    def test_relaxed_pointing_both_sides_scales_and_rotations(self):
        for side in ("Left", "Right"):
            for scale in (.025, .07, .11):
                for rotation in (0, 45, 90, 135, 180):
                    with self.subTest(side=side, scale=scale, rotation=rotation):
                        hand = relaxed_pointing(side=side, scale=scale, rotation=rotation)
                        self.assertEqual(classify_hand(extract_features(hand, image_size=SIZE), 0).gesture,
                                         Gesture.POINTING)

    def test_slight_index_bend_is_pointing_with_tight_or_relaxed_other_fingers(self):
        for relaxed in (False, True):
            angles = {finger: (90, 10, -55) for finger in OTHERS} if relaxed else {}
            angles[Finger.INDEX] = (90, 62, 45)  # PIP=152 degrees: clearly almost straight.
            for side in ("Left", "Right"):
                for rotation in (0, 45, 90, 180):
                    hand = pose_hand(curled=OTHERS, chain_angles=angles, side=side, rotation=rotation)
                    features = extract_features(hand, image_size=SIZE)
                    index = features.finger(Finger.INDEX)
                    self.assertLess(index.joint_angle_degrees, T.extended_joint_min_degrees)
                    self.assertGreater(index.joint_angle_degrees, T.pointing_index_joint_min_degrees)
                    self.assertEqual(classify_hand(features, 0).gesture, Gesture.POINTING)

    def test_peace_three_fingers_and_partial_poses_remain_unknown(self):
        for side in ("Left", "Right"):
            for rotation in (0, 45, 90):
                for curled in ((Finger.RING, Finger.PINKY), (Finger.PINKY,)):
                    features = extract_features(pose_hand(curled=curled, side=side, rotation=rotation), image_size=SIZE)
                    self.assertEqual(classify_hand(features, 0).gesture, Gesture.UNKNOWN)
                partial = pose_hand(curled=OTHERS, partial=(Finger.INDEX,), side=side, rotation=rotation)
                self.assertEqual(classify_hand(extract_features(partial, image_size=SIZE), 0).gesture, Gesture.UNKNOWN)
                partial_others = pose_hand(chain_angles={f: (90, 20, -20) for f in OTHERS},
                                          side=side, rotation=rotation)
                self.assertEqual(classify_hand(extract_features(partial_others, image_size=SIZE), 0).gesture,
                                 Gesture.UNKNOWN)

    def test_short_index_cannot_win_by_relaxing_other_finger_distances(self):
        hand = relaxed_pointing()
        points = list(hand.landmarks)
        base = hand[LandmarkIndex.INDEX_FINGER_MCP]
        for index in (LandmarkIndex.INDEX_FINGER_PIP, LandmarkIndex.INDEX_FINGER_DIP,
                      LandmarkIndex.INDEX_FINGER_TIP):
            point = hand[index]
            points[index] = replace(point, x=base.x + .65 * (point.x - base.x),
                                    y=base.y + .65 * (point.y - base.y))
        features = extract_features(HandObservation(points, hand.handedness), image_size=SIZE)
        result = classify_hand(features, 0, diagnostics=True)
        self.assertEqual(result.gesture, Gesture.UNKNOWN)
        self.assertTrue(any(c.measurement == "index_tip_separation" and not c.passed
                            for c in result.pointing_checks))

    def test_thumbs_up_unknown_and_ordinary_fists_and_open_palms_preserved(self):
        for side in ("Left", "Right"):
            for rotation in (0, 45, 90, 180):
                for thumb in ("tucked", "relaxed"):
                    fist = pose_hand(curled=ALL, thumb=thumb, side=side, rotation=rotation)
                    self.assertEqual(classify_hand(extract_features(fist, image_size=SIZE), 0).gesture, Gesture.FIST)
                thumb_up = pose_hand(curled=ALL, thumb="extended", side=side, rotation=rotation)
                result = classify_hand(extract_features(thumb_up, image_size=SIZE), 0)
                self.assertEqual(result.gesture, Gesture.UNKNOWN)
                self.assertEqual(result.reason, "unsupported_thumb_extension")
                opened = pose_hand(side=side, rotation=rotation)
                self.assertEqual(classify_hand(extract_features(opened, image_size=SIZE), 0).gesture, Gesture.OPEN_PALM)

    def test_diagnostics_share_the_pointing_decision_and_are_opt_in(self):
        hands = (relaxed_pointing(), pose_hand(), pose_hand(curled=ALL),
                 pose_hand(curled=(Finger.RING, Finger.PINKY)))
        for hand in hands:
            features = extract_features(hand, image_size=SIZE)
            ordinary = classify_hand(features, 33)
            sampled = classify_hand(features, 33, diagnostics=True)
            self.assertEqual(ordinary.pointing_checks, ())
            self.assertEqual(ordinary.gesture, sampled.gesture)
            self.assertEqual(all(check.passed for check in sampled.pointing_checks),
                             Gesture.POINTING in sampled.matched_rules)
            self.assertEqual(len(sampled.pointing_checks), 19)

    def test_missing_nonfinite_and_zero_scale_features_have_numeric_diagnostics(self):
        base = extract_features(relaxed_pointing(), image_size=SIZE)
        index = base.finger(Finger.INDEX)
        invalid_index = replace(index, joint_angle_degrees=float("nan"))
        invalid = replace(base, fingers=tuple(invalid_index if f.finger == Finger.INDEX else f
                                               for f in base.fingers))
        for features in (None, invalid, replace(base, palm_scale=0), replace(base, fingers=())):
            result = classify_hand(features, 0, diagnostics=True)
            self.assertEqual(result.gesture, Gesture.UNKNOWN)
            self.assertTrue(any(not check.passed for check in result.pointing_checks))
        result = classify_hand(invalid, 0, diagnostics=True)
        self.assertTrue(any(c.finger == Finger.INDEX and c.measurement == "PIP_degrees"
                            and c.value is None for c in result.pointing_checks))


if __name__ == "__main__":
    unittest.main()
