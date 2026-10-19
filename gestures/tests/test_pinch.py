from dataclasses import replace
import unittest

from gestures.features import extract_features
from gestures.models import HandednessPrediction, HandObservation, ImageSize, Landmark
from gestures.pinch import PinchStatus as S, PinchThresholds, PinchTracker, measure_pinch
from .pinch_fixtures import pinch_hand
from .static_fixtures import SIZE


def features(ratio=.8, **kwargs):
    return extract_features(pinch_hand(ratio, **kwargs), image_size=kwargs.get("image_size", SIZE))


def observed(tracker, ratio, stamp, **kwargs):
    return tracker.update((features(ratio, **kwargs),), stamp)[0]


class PinchGeometryTest(unittest.TestCase):
    def test_known_distance_uses_existing_palm_mean(self):
        item = features(.2)
        measured = measure_pinch(item)
        self.assertTrue(measured.valid)
        self.assertAlmostEqual(measured.normalized_distance, .2)
        self.assertAlmostEqual(item.thumb_index_distance, item.palm_scale*.2)

    def test_sides_scales_rotations_and_aspect_ratios(self):
        for side in ("Left", "Right"):
            for scale in (.025, .07, .12):
                for rotation in (0, 35, 90, 180):
                    for size in (SIZE, ImageSize(640, 480), ImageSize(500, 1000)):
                        with self.subTest(side=side, scale=scale, rotation=rotation, size=size):
                            self.assertAlmostEqual(measure_pinch(features(.18, side=side, scale=scale,
                                                                        rotation=rotation, image_size=size))
                                                   .normalized_distance, .18)

    def test_contact_zero_is_valid_but_not_verified_physical_contact(self):
        measurement = measure_pinch(features(0))
        self.assertTrue(measurement.valid)
        self.assertEqual(measurement.normalized_distance, 0)

    def test_invalid_missing_nonfinite_and_degenerate_measurements(self):
        base = features()
        collapsed = HandObservation((Landmark(.5, .5, 0),)*21, base.observation.handedness)
        invalid = (None, replace(base, image_size=None), replace(base, palm_scale=0),
                   replace(base, palm_scale=1e-12), replace(base, thumb_index_ratio=float("nan")),
                   replace(base, thumb_index_distance=float("inf")), replace(base, thumb_index_ratio=-1),
                   replace(base, thumb_index_ratio=.9), extract_features(collapsed, image_size=SIZE))
        for item in invalid:
            with self.subTest(item=item):
                measurement = measure_pinch(item)
                self.assertFalse(measurement.valid)
                self.assertIsNone(measurement.normalized_distance)

    def test_threshold_range_and_order_validation(self):
        self.assertEqual(PinchThresholds(), PinchThresholds(.25, .4))
        for activation, release in ((0, .4), (-1, .4), (.4, .4), (.5, .4), (.2, 2.1),
                                    (.2, float("nan")), (True, .4), (".2", .4)):
            with self.subTest(activation=activation, release=release), self.assertRaises(ValueError):
                PinchThresholds(activation, release)


class PinchLifecycleTest(unittest.TestCase):
    def test_approach_hold_and_deliberate_release_once(self):
        tracker = PinchTracker()
        distances = (.9, .6, .35, .2, .1, .05, .30, .39, .5, .8)
        actual = [observed(tracker, d, n*30).status for n, d in enumerate(distances)]
        self.assertEqual(actual, [S.OPEN, S.OPEN, S.OPEN, S.STARTED, S.HELD, S.HELD,
                                  S.HELD, S.HELD, S.RELEASED, S.OPEN])

    def test_hysteresis_strict_boundaries_and_hover(self):
        tracker = PinchTracker()
        base = features()
        # Exact cached ratios avoid floating-point coordinate noise at equality.
        def at(ratio, stamp):
            return tracker.update((replace(base, thumb_index_ratio=ratio,
                                           thumb_index_distance=ratio*base.palm_scale),), stamp)[0].status
        self.assertEqual([at(d, i) for i, d in enumerate((.8, .25, .26, .249, .25, .39, .4, .401, .4))],
                         [S.OPEN, S.OPEN, S.OPEN, S.STARTED, S.HELD, S.HELD, S.HELD, S.RELEASED, S.OPEN])

    def test_startup_closed_requires_observed_open_before_activation(self):
        tracker = PinchTracker()
        first = observed(tracker, .1, 0)
        self.assertEqual(first.status, S.UNAVAILABLE)
        self.assertTrue(first.measurement.valid)
        self.assertEqual(first.reason, "open_to_rearm")
        self.assertEqual([observed(tracker, d, i+1).status for i, d in enumerate((.1, .3, .8, .1))],
                         [S.UNAVAILABLE, S.UNAVAILABLE, S.OPEN, S.STARTED])

    def test_disappearance_reacquisition_cannot_fabricate_release_or_start(self):
        tracker = PinchTracker()
        observed(tracker, .8, 0)
        self.assertEqual(observed(tracker, .1, 30).status, S.STARTED)
        self.assertEqual(tracker.update((), 60), ())
        self.assertEqual(observed(tracker, .1, 90).status, S.UNAVAILABLE)
        self.assertEqual(observed(tracker, .8, 120).status, S.OPEN)
        self.assertEqual(observed(tracker, .1, 150).status, S.STARTED)

    def test_invalid_geometry_clears_active_state(self):
        tracker = PinchTracker()
        observed(tracker, .8, 0)
        observed(tracker, .1, 30)
        bad = replace(features(.1), palm_scale=0)
        result = tracker.update((bad,), 60)[0]
        self.assertEqual(result.status, S.UNAVAILABLE)
        self.assertFalse(result.measurement.valid)
        self.assertEqual(observed(tracker, .1, 90).status, S.UNAVAILABLE)

    def test_reset_and_long_gap_require_rearming(self):
        for explicit_reset in (True, False):
            tracker = PinchTracker()
            observed(tracker, .8, 0)
            observed(tracker, .1, 30)
            if explicit_reset:
                tracker.reset()
            self.assertEqual(observed(tracker, .1, 400).status, S.UNAVAILABLE)

    def test_invalid_and_nonmonotonic_timestamps_invalidate_history(self):
        for invalid in (-1, True, 2.5, None):
            tracker = PinchTracker()
            observed(tracker, .8, 0)
            with self.assertRaises(ValueError):
                tracker.update((features(.1),), invalid)
            self.assertEqual(observed(tracker, .1, 30).status, S.UNAVAILABLE)
        for stamp in (29, 30):
            tracker = PinchTracker()
            observed(tracker, .8, 0)
            observed(tracker, .1, 30)
            result = observed(tracker, .1, stamp)
            self.assertEqual(result.status, S.UNAVAILABLE)
            self.assertEqual(result.reason, "non_monotonic_time")
            self.assertEqual(observed(tracker, .1, 60).status, S.UNAVAILABLE)
        tracker = PinchTracker()
        observed(tracker, .8, 100)
        self.assertEqual(observed(tracker, .8, 90).status, S.UNAVAILABLE)
        self.assertEqual(observed(tracker, .1, 95).status, S.UNAVAILABLE)
        self.assertEqual(observed(tracker, .1, 101).status, S.UNAVAILABLE)
        self.assertEqual(observed(tracker, .8, 102).status, S.OPEN)

    def test_two_hands_independent_and_order_changes(self):
        tracker = PinchTracker()
        def pair(left, right, stamp, reverse=False):
            items = (features(left, side="Left", offset=-.23), features(right, side="Right", offset=.23))
            return tracker.update(items[::-1] if reverse else items, stamp)
        self.assertEqual([r.status for r in pair(.8, .8, 0)], [S.OPEN, S.OPEN])
        self.assertEqual([r.status for r in pair(.1, .8, 30, True)], [S.OPEN, S.STARTED])
        self.assertEqual([r.status for r in pair(.1, .1, 60)], [S.HELD, S.STARTED])
        self.assertEqual([r.status for r in pair(.8, .1, 90, True)], [S.HELD, S.RELEASED])
        self.assertEqual([r.status for r in pair(.8, .8, 120)], [S.OPEN, S.RELEASED])

    def test_simultaneous_activation_and_one_hand_loss(self):
        tracker = PinchTracker()
        left = lambda d: features(d, offset=-.23)
        right = lambda d: features(d, side="Right", offset=.23)
        tracker.update((left(.8), right(.8)), 0)
        self.assertEqual([r.status for r in tracker.update((left(.1), right(.1)), 30)], [S.STARTED]*2)
        self.assertEqual(tracker.update((right(.1),), 60)[0].status, S.HELD)
        self.assertEqual([r.status for r in tracker.update((left(.1), right(.1)), 90)], [S.UNAVAILABLE, S.HELD])

    def test_uncertain_duplicate_unknown_or_conflicting_handedness(self):
        variants = ((), (HandednessPrediction("Left", .79),), (HandednessPrediction("Other", .99),),
                    (HandednessPrediction("Left", None),),
                    (HandednessPrediction("Left", .95), HandednessPrediction("Right", .9)))
        for metadata in variants:
            tracker = PinchTracker()
            observed(tracker, .8, 0)
            observed(tracker, .1, 30)
            base = features(.1)
            changed = replace(base, observation=replace(base.observation, handedness=metadata))
            self.assertEqual(tracker.update((changed,), 60)[0].status, S.UNAVAILABLE)
            self.assertEqual(observed(tracker, .1, 90).status, S.UNAVAILABLE)
        tracker = PinchTracker()
        self.assertEqual([r.status for r in tracker.update((features(.8, offset=-.23), features(.8, offset=.23)), 0)],
                         [S.UNAVAILABLE]*2)

    def test_overlapping_hands_and_large_wrist_jump_invalidate(self):
        tracker = PinchTracker()
        observed(tracker, .8, 0)
        observed(tracker, .1, 30)
        results = tracker.update((features(.1), features(.1, side="Right")), 60)
        self.assertEqual([r.status for r in results], [S.UNAVAILABLE]*2)
        self.assertTrue(all(r.reason == "overlapping_hands" for r in results))
        self.assertEqual(observed(tracker, .1, 90).status, S.UNAVAILABLE)
        observed(tracker, .8, 120)
        observed(tracker, .1, 150)
        self.assertEqual(observed(tracker, .1, 180, offset=.2).status, S.UNAVAILABLE)

    def test_image_size_change_rearms_and_too_many_hands_rejected(self):
        tracker = PinchTracker()
        observed(tracker, .8, 0)
        observed(tracker, .1, 30)
        self.assertEqual(observed(tracker, .1, 60, image_size=ImageSize(640, 480)).status, S.UNAVAILABLE)
        with self.assertRaises(ValueError):
            tracker.update((features(),)*3, 90)


if __name__ == "__main__":
    unittest.main()
