"""Numerical/recognition parity with the original geometry composition."""

import math
import random
import unittest
from unittest.mock import patch

from gestures import features as f
from gestures.geometry import angle_degrees, distance_2d, dot, magnitude, normalize, vector_between
from gestures.models import ImageSize, Landmark
from gestures.static_gestures import classify_hand
from .test_swipe import sample_hand


def original_distance(a, b, *, image_size=None):
    return magnitude(vector_between(a, b, image_size=image_size))


def original_angle(first, vertex, last, *, dimensions=2, image_size=None):
    a = vector_between(vertex, first, dimensions=dimensions, image_size=image_size)
    b = vector_between(vertex, last, dimensions=dimensions, image_size=image_size)
    if magnitude(a) == 0 or magnitude(b) == 0:
        return None
    return math.degrees(math.acos(max(-1., min(1., dot(normalize(a), normalize(b))))))


class GeometryParityTest(unittest.TestCase):
    def test_distances_and_angles_match_original_for_seeded_points_aspects_and_units(self):
        rng = random.Random(3701)
        for size in (None, ImageSize(1920, 1080), ImageSize(640, 480), ImageSize(540, 960)):
            for _ in range(150):
                scale = 10**rng.uniform(-20, 20)
                points = [Landmark(*(rng.uniform(-2, 2)*scale for _ in range(3))) for _ in range(3)]
                self.assertTrue(math.isclose(distance_2d(*points[:2], image_size=size),
                                            original_distance(*points[:2], image_size=size), rel_tol=1e-14))
                for dimensions in (2, 3):
                    self.assertAlmostEqual(angle_degrees(*points, dimensions=dimensions, image_size=size),
                                           original_angle(*points, dimensions=dimensions, image_size=size), places=10)

    def test_feature_and_classifier_parity_across_poses_rotation_and_resolution(self):
        for size in (ImageSize(1920, 1080), ImageSize(640, 480), ImageSize(540, 960)):
            for pose in ("open", "point", "fist"):
                for rotation in (-150, -60, 0, 35, 90, 170):
                    for side in ("Left", "Right"):
                        hand = sample_hand(pose=pose, rotation=rotation, side=side, image_size=size).observation
                        actual = f.extract_features(hand, image_size=size)
                        with patch.object(f, "angle_degrees", original_angle), patch.object(f, "distance_2d", original_distance):
                            expected = f.extract_features(hand, image_size=size)
                        for a, b in zip(actual.fingers, expected.fingers):
                            for name in ("joint_angle_degrees", "distal_angle_degrees", "straightness_ratio", "tip_to_wrist_ratio"):
                                av, bv = getattr(a, name), getattr(b, name)
                                if av is None or bv is None:
                                    self.assertIs(av, bv)
                                else:
                                    self.assertAlmostEqual(av, bv, places=10)
                        self.assertEqual(classify_hand(actual, 0), classify_hand(expected, 0))

    def test_invalid_types_dimensions_and_overflow_remain_rejected(self):
        origin, huge = Landmark(0, 0, 0), Landmark(1.7e308, 1.7e308, 0)
        for fn in (distance_2d, original_distance):
            with self.assertRaises(ValueError):
                fn(origin, huge)
        for fn in (angle_degrees, original_angle):
            with self.assertRaises(ValueError):
                fn(huge, origin, huge)
            for dimensions in (True, 0, 2., "2"):
                with self.assertRaises(ValueError):
                    fn(origin, origin, origin, dimensions=dimensions)
            self.assertIsNone(fn(origin, origin, huge))
        for scale in (1e-300, 1e300):
            self.assertEqual(angle_degrees(Landmark(scale, 0, 0), origin, Landmark(0, scale, 0)), 90.)


if __name__ == "__main__":
    unittest.main()
