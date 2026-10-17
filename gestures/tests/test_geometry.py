import math
from types import SimpleNamespace
import unittest

from gestures.geometry import (
    angle_degrees, distance_2d, distance_3d, dot, landmark_distance, magnitude,
    normalize, normalized_distance, palm_scale, vector_between,
)
from gestures.models import HandObservation, ImageSize, Landmark, LandmarkIndex
from .fixtures import synthetic_hand, transform


class GeometryTest(unittest.TestCase):
    def test_known_distances_and_dimension_choice(self):
        first, last = Landmark(0, 0, 0), Landmark(3, 4, 12)
        self.assertEqual(distance_2d(first, last), 5)
        self.assertEqual(distance_3d(first, last), 13)
        self.assertEqual(distance_3d(last, first), 13)
        self.assertEqual(distance_2d(first, first), 0)

    def test_vector_direction_magnitude_and_dot(self):
        first, last = Landmark(1, 2, 3), Landmark(4, 6, 15)
        self.assertEqual(vector_between(first, last), (3, 4))
        self.assertEqual(vector_between(first, last, dimensions=3), (3, 4, 12))
        self.assertEqual(vector_between(last, first), (-3, -4))
        self.assertEqual(magnitude((3, 4, 12)), 13)
        self.assertEqual(dot((1, 2, 3), (4, 5, 6)), 32)
        self.assertEqual(dot((1, 0), (0, 1)), 0)

    def test_unit_vector_and_zero_length(self):
        self.assertEqual(normalize((3, 4)), (.6, .8))
        self.assertAlmostEqual(magnitude(normalize((2, -4, 6))), 1)
        self.assertEqual(magnitude((0, 0)), 0)
        with self.assertRaises(ValueError):
            normalize((0, 0, 0))
        # Unit direction should not overflow or underflow just because units are extreme.
        for scale in (1e-300, 1e300):
            self.assertAlmostEqual(magnitude(normalize((scale, scale))), 1)

    def test_known_angles_degrees_and_return_range(self):
        origin = Landmark(0, 0, 0)
        right = Landmark(1, 0, 0)
        for last, expected in ((right, 0), (Landmark(1, 1, 0), 45),
                               (Landmark(0, 1, 0), 90), (Landmark(-1, 0, 0), 180)):
            self.assertAlmostEqual(angle_degrees(right, origin, last), expected)
        self.assertEqual(angle_degrees(right, origin, Landmark(0, 0, 1), dimensions=3), 90)

    def test_degenerate_angles_are_undefined(self):
        point, other = Landmark(.5, .5, 0), Landmark(.3, .4, 0)
        self.assertIsNone(angle_degrees(point, point, other))
        self.assertIsNone(angle_degrees(other, point, point))

    def test_index_distance_and_defined_palm_scale(self):
        hand = synthetic_hand()
        self.assertEqual(palm_scale(hand), 2)
        self.assertEqual(landmark_distance(hand, LandmarkIndex.WRIST, LandmarkIndex.MIDDLE_FINGER_TIP), 5)
        self.assertAlmostEqual(normalized_distance(hand, LandmarkIndex.THUMB_TIP,
                                                   LandmarkIndex.INDEX_FINGER_TIP), math.sqrt(34) / 2)
        with self.assertRaises(ValueError):
            landmark_distance(hand, -1, 0)

    def test_zero_palm_scale_is_explicit(self):
        hand = HandObservation((Landmark(0, 0, 0),) * 21)
        self.assertEqual(palm_scale(hand), 0)
        with self.assertRaisesRegex(ValueError, "zero palm scale"):
            normalized_distance(hand, LandmarkIndex.THUMB_TIP, LandmarkIndex.INDEX_FINGER_TIP)

    def test_translation_uniform_scale_and_normalized_ratio(self):
        hand = synthetic_hand()
        expected = normalized_distance(hand, LandmarkIndex.THUMB_TIP, LandmarkIndex.INDEX_FINGER_TIP)
        for scale in (.01, .5, 3):
            changed = transform(hand, scale, (5, -3, 8))
            self.assertAlmostEqual(palm_scale(changed), 2 * scale)
            self.assertAlmostEqual(normalized_distance(changed, LandmarkIndex.THUMB_TIP,
                                                       LandmarkIndex.INDEX_FINGER_TIP), expected)

    def test_image_aspect_correction_matches_common_pixel_units(self):
        size = ImageSize(1920, 1080)
        first, last = Landmark(0, 0, 0), Landmark(1, 1, 1)
        self.assertEqual(vector_between(first, last, image_size=size), (1, .5625))
        self.assertAlmostEqual(distance_2d(first, last, image_size=size) * 1920, math.hypot(1920, 1080))
        self.assertAlmostEqual(distance_3d(first, last, image_size=size), math.sqrt(2 + .5625 ** 2))
        self.assertEqual(distance_2d(first, last), math.sqrt(2))

    def test_image_geometry_is_resolution_independent_at_fixed_aspect(self):
        hand = synthetic_hand()
        values = [palm_scale(hand, image_size=size) for size in
                  (ImageSize(1920, 1080), ImageSize(1280, 720), ImageSize(640, 360))]
        self.assertEqual(values, [values[0]] * 3)

    def test_invalid_vectors_dimensions_and_nonfinite_coordinates(self):
        for invalid in ((), (1,), (1, 2, 3, 4), (float("nan"), 0), (0, float("inf")),
                        (True, 0), "12", None):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                magnitude(invalid)
        for dimensions in (0, 1, 4, 2.0, True, "2"):
            with self.assertRaises(ValueError):
                vector_between(Landmark(0, 0, 0), Landmark(1, 1, 1), dimensions=dimensions)
        with self.assertRaises(ValueError):
            dot((1, 2), (1, 2, 3))
        with self.assertRaises(ValueError):
            distance_2d(SimpleNamespace(x=float("nan"), y=0), Landmark(0, 0, 0))
        with self.assertRaises(ValueError):
            magnitude((1.7e308, 1.7e308))
        with self.assertRaises(ValueError):
            dot((1e308, 0), (1e308, 0))


if __name__ == "__main__":
    unittest.main()
