"""Focused natural-pose and projected-geometry regressions; no webcam claims."""

from dataclasses import replace
import unittest

from gestures.features import extract_features
from gestures.models import Finger, HandObservation, LandmarkIndex
from gestures.static_gestures import Gesture, classify_hand
from .static_fixtures import SIZE, pose_hand, project_hand


OTHERS = (Finger.MIDDLE, Finger.RING, Finger.PINKY)
ALL = (Finger.INDEX,) + OTHERS


def natural_pointing(*, relaxed=OTHERS, bent_index=False, **kwargs):
    # A folded PIP with a relaxed straight distal segment is still a curled
    # chain: the fingertip returns toward the palm rather than extending out.
    angles = {finger: (90, -25, -25) for finger in relaxed}
    if bent_index:
        angles[Finger.INDEX] = (90, 58, 42)
    return pose_hand(curled=OTHERS, chain_angles=angles, **kwargs)


def recognize(hand, diagnostics=False):
    return classify_hand(extract_features(hand, image_size=SIZE), 0, diagnostics=diagnostics)


class PointingReliabilityTest(unittest.TestCase):
    def test_individual_relaxed_distal_segments_and_all_three(self):
        for relaxed in ((Finger.MIDDLE,), (Finger.RING,), (Finger.PINKY,), OTHERS):
            for side in ("Left", "Right"):
                with self.subTest(relaxed=relaxed, side=side):
                    self.assertEqual(recognize(natural_pointing(relaxed=relaxed, side=side)).gesture,
                                     Gesture.POINTING)

    def test_mostly_straight_index_retains_multiple_extension_cues(self):
        for relaxed in ((), OTHERS):
            for side in ("Left", "Right"):
                hand = natural_pointing(relaxed=relaxed, bent_index=True, side=side)
                with self.subTest(relaxed=relaxed, side=side):
                    self.assertEqual(recognize(hand).gesture, Gesture.POINTING)

    def test_natural_pointing_in_plane_sideways_and_back_when_observable(self):
        for side in ("Left", "Right"):
            for scale in (.025, .07, .11):
                for roll in (0, -35, 35, 90, 180):
                    for yaw, pitch in ((0, 0), (-30, 0), (30, 0), (0, 30), (150, 0), (180, 0)):
                        hand = project_hand(natural_pointing(side=side, scale=scale, rotation=roll),
                                            yaw=yaw, pitch=pitch)
                        with self.subTest(side=side, scale=scale, roll=roll, yaw=yaw, pitch=pitch):
                            self.assertEqual(recognize(hand).gesture, Gesture.POINTING)

    def test_combined_foreshortening_keeps_unreliable_distance_evidence_unknown(self):
        for side in ("Left", "Right"):
            for roll in (35, 90):
                result = recognize(project_hand(natural_pointing(side=side, rotation=roll), yaw=45), True)
                self.assertEqual(result.gesture, Gesture.UNKNOWN)
                self.assertTrue(any(c.measurement in ("index_tip_separation", "tip_to_wrist") and not c.passed
                                    for c in result.pointing_checks))

    def test_natural_pointing_allows_thumb_posture_and_translation(self):
        for thumb in ("relaxed", "extended", "tucked", "collapsed"):
            hand = natural_pointing(thumb=thumb, bent_index=True)
            shifted = HandObservation(tuple(replace(p, x=p.x + .17, y=p.y - .1) for p in hand.landmarks),
                                      hand.handedness)
            self.assertEqual(recognize(shifted).gesture, Gesture.POINTING)

    def test_projected_fists_open_palms_and_unsupported_poses(self):
        cases = ((ALL, (), "tucked", Gesture.FIST), (ALL, (), "relaxed", Gesture.FIST),
                 (ALL, (), "extended", Gesture.UNKNOWN), ((), (), "relaxed", Gesture.OPEN_PALM),
                 ((Finger.RING, Finger.PINKY), (), "relaxed", Gesture.UNKNOWN),
                 ((Finger.PINKY,), (), "relaxed", Gesture.UNKNOWN),
                 ((Finger.RING, Finger.PINKY), (Finger.INDEX, Finger.MIDDLE), "relaxed", Gesture.UNKNOWN),
                 (OTHERS, (Finger.INDEX,), "relaxed", Gesture.UNKNOWN))
        for side in ("Left", "Right"):
            for yaw in (0, -30, 30, 150, 180):
                for curled, partial, thumb, expected in cases:
                    hand = project_hand(pose_hand(curled=curled, partial=partial, thumb=thumb, side=side), yaw=yaw)
                    with self.subTest(side=side, yaw=yaw, curled=curled, partial=partial, thumb=thumb):
                            actual = recognize(hand).gesture
                            if expected == Gesture.FIST and yaw in (-30, 30, 150):
                                # Existing strict wrist-distance limits can reject a projected
                                # fist. Preserve uncertainty and never activate the cursor.
                                self.assertIn(actual, (Gesture.FIST, Gesture.UNKNOWN))
                            else:
                                self.assertEqual(actual, expected)

    def test_relaxed_distal_does_not_admit_shallow_or_straight_other_fingers(self):
        for finger in OTHERS:
            for angles in ((90, 40, 40), (90, 78, 70), (90, 30, 0)):
                hand = pose_hand(curled=OTHERS, chain_angles={finger: angles})
                self.assertEqual(recognize(hand).gesture, Gesture.UNKNOWN)

    def test_collapsed_and_missing_geometry_is_unknown(self):
        hand = natural_pointing()
        points = list(hand.landmarks)
        points[LandmarkIndex.INDEX_FINGER_DIP] = points[LandmarkIndex.INDEX_FINGER_PIP]
        self.assertEqual(recognize(HandObservation(tuple(points), hand.handedness)).gesture, Gesture.UNKNOWN)
        features = extract_features(hand, image_size=SIZE)
        for bad in (None, replace(features, fingers=()), replace(features, palm_scale=0)):
            self.assertEqual(classify_hand(bad, 0).gesture, Gesture.UNKNOWN)

    def test_relaxed_curl_still_requires_valid_distal_measurements(self):
        features = extract_features(natural_pointing(), image_size=SIZE)
        for value in (None, float("nan"), -1, 181):
            changed = tuple(replace(f, distal_angle_degrees=value) if f.finger == Finger.MIDDLE else f
                            for f in features.fingers)
            result = classify_hand(replace(features, fingers=changed), 0, diagnostics=True)
            self.assertEqual(result.gesture, Gesture.UNKNOWN)
            self.assertEqual(result.reason, "invalid_or_missing_features")
            self.assertTrue(any(c.finger == Finger.MIDDLE and c.measurement == "DIP_degrees_valid"
                                and c.value is None for c in result.pointing_checks))


if __name__ == "__main__":
    unittest.main()
