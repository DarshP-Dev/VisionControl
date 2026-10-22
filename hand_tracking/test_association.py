"""Stable geometric IDs, ambiguity refusal and bounded track lifetime."""

from dataclasses import replace
import itertools
import unittest

from gestures.tests.static_fixtures import SIZE
from .association import HandAssociator, MAX_LOST_MS
from .multi_hand_fixtures import four, hand
from .smoothing import TrackLandmarkSmoother


class HandAssociationTest(unittest.TestCase):
    def test_valid_counts_and_default_do_not_truncate(self):
        for maximum in (1, 2, 3, 4):
            a = HandAssociator(maximum)
            for count in range(maximum + 1):
                result = a.update(four()[:count], count * 33, SIZE)
                self.assertEqual(len(result), count)
                self.assertTrue(all(x.certain for x in result))
            with self.assertRaises(ValueError):
                a.update(four() + (hand(.95),), 200, SIZE)

    def test_invalid_maxima_rejected(self):
        for count in (0, 5, -1, 2., True, None, "4"):
            with self.assertRaises(ValueError):
                HandAssociator(count)

    def test_all_result_permutations_preserve_ids_under_smooth_motion(self):
        a = HandAssociator()
        expected = tuple(x.track_id for x in a.update(four(), 0, SIZE))
        for step, order in enumerate(itertools.permutations(range(4)), 1):
            moved = tuple(hand(x + step * .001) for x in (.15, .37, .59, .81))
            result = a.update(tuple(moved[i] for i in order), step * 33, SIZE)
            self.assertEqual(tuple(x.track_id for x in result), tuple(expected[i] for i in order))
            self.assertEqual(len(set(x.track_id for x in result)), 4)

    def test_duplicate_labels_and_low_confidence_do_not_define_identity(self):
        for side in ("Left", "Right"):
            a = HandAssociator()
            ids = tuple(x.track_id for x in a.update(four(side=side), 0, SIZE))
            changed = tuple(hand(x, side="Left" if i % 2 else "Right", score=.3 if i == 1 else .99)
                            for i, x in enumerate((.15, .37, .59, .81)))
            self.assertEqual(tuple(x.track_id for x in a.update(changed, 33, SIZE)), ids)

    def test_gradual_scale_change_retains_tracks_and_abrupt_change_gets_new_id(self):
        a = HandAssociator()
        first = a.update((hand(),), 0, SIZE)[0].track_id
        for n in range(1, 6):
            self.assertEqual(a.update((hand(scale=.022 * 1.05 ** n),), n * 50, SIZE)[0].track_id, first)
        self.assertNotEqual(a.update((hand(scale=.07),), 300, SIZE)[0].track_id, first)

    def test_birth_departure_expiry_and_no_immediate_id_reuse(self):
        a = HandAssociator()
        first = a.update((hand(.2),), 0, SIZE)[0].track_id
        a.update((hand(.2), hand(.7)), 33, SIZE)
        for stamp in range(100, MAX_LOST_MS + 201, 100):
            a.update((), stamp, SIZE)
        self.assertEqual(len(a.tracks), 0)
        self.assertGreater(a.update((hand(.2),), 750, SIZE)[0].track_id, first)

    def test_one_or_two_brief_dropouts_retain_unique_geometric_ids(self):
        for missing in ((0,), (0, 2)):
            a = HandAssociator()
            observations = four()
            ids = tuple(x.track_id for x in a.update(observations, 0, SIZE))
            remaining = tuple(h for i, h in enumerate(observations) if i not in missing)
            a.update(remaining, 50, SIZE)
            result = a.update(observations, 100, SIZE)
            self.assertEqual(tuple(x.track_id for x in result), ids)
            self.assertTrue(all(result[i].reason == "reacquired" for i in missing))

    def test_impossible_displacement_not_matched(self):
        a = HandAssociator()
        old = a.update((hand(.2),), 0, SIZE)[0].track_id
        self.assertNotEqual(a.update((hand(.7),), 33, SIZE)[0].track_id, old)

    def test_global_matching_avoids_greedy_assignment_trap(self):
        a = HandAssociator()
        old = a.update((hand(.2), hand(.3)), 0, SIZE)
        result = a.update((hand(.24), hand(.2)), 33, SIZE)
        self.assertEqual(tuple(x.track_id for x in result), (old[1].track_id, old[0].track_id))

    def test_horizontal_and_vertical_crossings_retire_ambiguous_tracks(self):
        for axis in ("x", "y"):
            a = HandAssociator()
            def pair(distance):
                return ((hand(.5 - distance, .65), hand(.5 + distance, .65)) if axis == "x" else
                        (hand(.5, .65 - distance), hand(.5, .65 + distance)))
            original = {x.track_id for x in a.update(pair(.1), 0, SIZE)}
            a.update(pair(.06), 50, SIZE)
            overlap = a.update(pair(.01), 100, SIZE)
            self.assertTrue(all(not x.certain and x.track_id is None for x in overlap))
            separated = a.update(pair(.08), 150, SIZE)
            self.assertTrue(all(x.certain and x.track_id not in original for x in separated))

    def test_ambiguous_lost_candidates_do_not_claim_reacquisition(self):
        a = HandAssociator()
        old = a.update((hand(.44), hand(.56)), 0, SIZE)
        a.update((), 50, SIZE)
        result = a.update((hand(.5),), 100, SIZE)
        self.assertFalse(result[0].certain)
        self.assertIsNone(result[0].track_id)

    def test_overlap_of_two_does_not_invalidate_distant_third_hand(self):
        a = HandAssociator()
        first = a.update((hand(.2), hand(.4), hand(.8)), 0, SIZE)
        result = a.update((hand(.29), hand(.31), hand(.8)), 100, SIZE)
        self.assertFalse(result[0].certain)
        self.assertFalse(result[1].certain)
        self.assertEqual(result[2].track_id, first[2].track_id)

    def test_invalid_hand_has_no_id_and_does_not_shift_other_slots(self):
        a = HandAssociator()
        result = a.update((hand(.2), None, hand(.8)), 0, SIZE)
        self.assertIsNone(result[1].track_id)
        self.assertTrue(result[0].certain and result[2].certain)

    def test_clock_regression_and_geometry_change_do_not_reuse_tracks(self):
        from gestures.models import ImageSize
        a = HandAssociator()
        old = a.update((hand(),), 20, SIZE)[0].track_id
        self.assertFalse(a.update((hand(),), 10, SIZE)[0].certain)
        new = a.update((hand(),), 30, SIZE)[0].track_id
        self.assertGreater(new, old)
        self.assertGreater(a.update((hand(),), 40, ImageSize(1280, 720))[0].track_id, new)

    def test_track_pool_and_transition_counters_remain_bounded(self):
        a = HandAssociator()
        for i in range(1000):
            a.update(tuple(hand(x, y=.35 if i % 2 else .85) for x in (.15, .37, .59, .81)), i * 33, SIZE)
            self.assertLessEqual(len(a.tracks), 8)
        self.assertLessEqual(len(a.counts), 6)


class TrackSmoothingTest(unittest.TestCase):
    def test_duplicate_handedness_smooths_independently_after_reordering(self):
        a, smoother = HandAssociator(), TrackLandmarkSmoother(alpha=.75)
        initial = four()
        smoother.apply(initial, a.update(initial, 0, SIZE), 0, SIZE)
        from gestures.models import HandednessPrediction
        moved = tuple(replace(hand(x + dx), handedness=(HandednessPrediction("Left", .93),))
                      for x, dx in ((.15, .002), (.37, -.003), (.59, .004), (.81, -.002)))
        order = (3, 1, 0, 2)
        result = smoother.apply(tuple(moved[i] for i in order), a.update(tuple(moved[i] for i in order), 33, SIZE), 33, SIZE)
        for item, original_index in zip(result, order):
            expected = .75 * moved[original_index][0].x + .25 * initial[original_index][0].x
            self.assertAlmostEqual(item[0].x, expected)
            self.assertEqual(item.handedness[0].category_name, "Left")

    def test_missing_history_is_dropped_even_when_track_id_survives(self):
        a, smoother = HandAssociator(), TrackLandmarkSmoother()
        initial = (hand(),)
        smoother.apply(initial, a.update(initial, 0, SIZE), 0, SIZE)
        self.assertEqual(smoother.apply((), a.update((), 33, SIZE), 33, SIZE), ())
        self.assertEqual(smoother._history, {})
        returned = (hand(.203),)
        result = smoother.apply(returned, a.update(returned, 66, SIZE), 66, SIZE)
        self.assertIs(result[0], returned[0])

    def test_uncertainty_clears_history_then_fresh_ids_start_raw(self):
        a, smoother = HandAssociator(), TrackLandmarkSmoother()
        initial = (hand(.3), hand(.5))
        smoother.apply(initial, a.update(initial, 0, SIZE), 0, SIZE)
        overlap = (hand(.39), hand(.41))
        smoother.apply(overlap, a.update(overlap, 100, SIZE), 100, SIZE)
        self.assertEqual(smoother._history, {})
        result = smoother.apply(initial, a.update(initial, 150, SIZE), 150, SIZE)
        self.assertIs(result[0], initial[0])

    def test_rapid_motion_and_disabled_smoothing_use_raw_observations(self):
        for enabled in (False, True):
            a, smoother = HandAssociator(), TrackLandmarkSmoother(enabled=enabled)
            initial = (hand(.2, scale=.035),)
            smoother.apply(initial, a.update(initial, 0, SIZE), 0, SIZE)
            moved = (hand(.27, scale=.035),)
            self.assertIs(smoother.apply(moved, a.update(moved, 100, SIZE), 100, SIZE)[0], moved[0])


if __name__ == "__main__":
    unittest.main()
