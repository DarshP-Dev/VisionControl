from dataclasses import FrozenInstanceError, replace
import math
import unittest
from unittest.mock import patch

from face_tracking.face_geometry import convert_box
from face_tracking.face_models import FaceFrame
from face_tracking.face_tracker import FaceTracker, TrackerConfig
from face_tracking.track_models import TrackState
from hand_tracking.performance import Profile


def face(x=.2, y=.4, w=.14, h=.2, confidence=.9):
    return convert_box(x, y, w, h, (1, 1), (1920, 1080), confidence)


def frame(t, *faces, size=(1920, 1080), status="detected"):
    return FaceFrame(round(t*1000), size, (640, 360), tuple(faces), 0 if faces else None, status)


class TrackerTest(unittest.TestCase):
    def tracker(self, **kwargs):
        return FaceTracker(TrackerConfig(confirmation_hits=1, confirmation_seconds=0, **kwargs))

    def test_default_confirmation_is_three_hits_and_sixty_ms(self):
        tracker = FaceTracker()
        for t in (0, .01, .02):
            result = tracker.update(frame(t, face()))
            self.assertIsNone(result.primary)
        result = tracker.update(frame(.06, face()))
        self.assertEqual(result.primary.state, TrackState.TRACKED)

    def test_confirmation_requires_contiguous_observations(self):
        tracker = FaceTracker()
        tracker.update(frame(0, face())); tracker.update(frame(.04))
        tracker.update(frame(.08, face())); tracker.update(frame(.12, face()))
        self.assertIsNone(tracker.update(frame(.13, face())).primary)
        self.assertIsNotNone(tracker.update(frame(.16, face())).primary)

    def test_confirmation_cannot_span_long_update_gap(self):
        tracker = FaceTracker()
        tracker.update(frame(0, face())); tracker.update(frame(.03, face()))
        self.assertIsNone(tracker.update(frame(.4, face())).primary)

    def test_moving_face_keeps_id_and_primary(self):
        tracker = self.tracker()
        for i in range(100):
            output = tracker.update(frame(i*.033, face(.2+i*.001)))
            self.assertEqual(output.primary_id, 1)
            self.assertEqual(len(output.tracks), 1)
            self.assertTrue(output.primary.detected)

    def test_birth_ids_are_geometric_not_detector_order_or_confidence(self):
        left, right = face(.1, confidence=.6), face(.7, confidence=.99)
        outputs = [self.tracker().update(frame(0, *items)) for items in ((left, right), (right, left))]
        self.assertEqual(outputs[0], outputs[1])
        self.assertEqual(outputs[0].tracks[0].raw.box_normalized.x_min, .1)
        self.assertEqual(outputs[0].primary_id, 2)

    def test_reordered_scores_and_output_preserve_independent_ids(self):
        tracker = self.tracker()
        tracker.update(frame(0, face(.1), face(.7)))
        for i in range(1, 20):
            output = tracker.update(frame(i*.033, face(.7, confidence=.99), face(.1, confidence=.5)))
            self.assertEqual([t.track_id for t in output.tracks if t.detected], [1, 2])
            self.assertAlmostEqual(output.tracks[0].raw.box_normalized.x_min, .1)
            self.assertEqual(output.primary_id, 1)

    def test_bigger_higher_confidence_newcomer_cannot_steal_primary(self):
        tracker = self.tracker()
        tracker.update(frame(0, face(.1, confidence=.6)))
        output = tracker.update(frame(.033, face(.1, confidence=.6), face(.65, w=.3, confidence=.99)))
        self.assertEqual(output.primary_id, 1)
        self.assertEqual(len(output.tracks), 2)

    def test_initial_primary_policy_confidence_area_geometry(self):
        output = self.tracker().update(frame(0, face(.1, w=.1), face(.6, w=.2)))
        self.assertEqual(output.primary_id, 2)

    def test_temporary_loss_has_no_current_coordinates(self):
        tracker = self.tracker()
        tracker.update(frame(0, face()))
        lost = tracker.update(frame(.033)).primary
        self.assertEqual(lost.state, TrackState.LOST)
        self.assertIsNone(lost.raw); self.assertIsNone(lost.smoothed)
        self.assertFalse(lost.detected)
        self.assertEqual(lost.last_detected, 0)
        self.assertEqual(lost.observation_age, .033)
        self.assertEqual(lost.confidence, .9)

    def test_other_visible_person_does_not_replace_lost_primary(self):
        tracker = self.tracker()
        tracker.update(frame(0, face(.1), face(.7)))
        output = tracker.update(frame(.04, face(.7)))
        self.assertEqual(output.primary_id, 1)
        self.assertFalse(output.primary.detected)
        self.assertTrue(output.tracks[1].detected)

    def test_reacquisition_keeps_id_and_resets_ema(self):
        tracker = self.tracker()
        tracker.update(frame(0, face(.2)))
        tracker.update(frame(.04))
        output = tracker.update(frame(.1, face(.24)))
        self.assertEqual(output.primary_id, 1)
        self.assertEqual(output.primary.raw, output.primary.smoothed)
        self.assertEqual(tracker.counts["primary_reacquisitions"], 1)
        self.assertEqual(tracker.counts["primary_loss_events"], 1)

    def test_lost_match_has_stricter_spatial_gate(self):
        tracker = self.tracker()
        tracker.update(frame(0, face(.2)))
        tracker.update(frame(.04))
        result = tracker.update(frame(.2, face(.32)))
        self.assertEqual(result.primary_id, 1)
        self.assertFalse(result.primary.detected)
        self.assertEqual(result.tracks[1].track_id, 2)

    def test_expiration_is_elapsed_time_not_miss_count(self):
        for step in (.01, .1):
            tracker = self.tracker(lost_timeout=.8)
            tracker.update(frame(0, face()))
            for i in range(1, round(.7/step)+1):
                self.assertEqual(tracker.update(frame(i*step)).primary_id, 1)
            output = tracker.update(frame(.81))
            self.assertIsNone(output.primary)
            self.assertEqual(output.tracks[0].state, TrackState.EXPIRED)
            self.assertIsNone(output.tracks[0].raw)
            self.assertEqual(tracker.metadata()["active_tracks"], 0)

    def test_expired_track_appears_once_and_never_revives(self):
        tracker = self.tracker()
        tracker.update(frame(0, face()))
        output = tracker.update(frame(.9, face()))
        self.assertEqual(output.primary_id, 2)
        self.assertEqual([t.state for t in output.tracks], [TrackState.TRACKED, TrackState.EXPIRED])
        self.assertEqual([t.track_id for t in tracker.update(frame(.94, face())).tracks], [2])

    def test_expired_primary_does_not_relock_in_multi_face_scene(self):
        tracker = self.tracker()
        tracker.update(frame(0, face(.1)))
        tracker.update(frame(.04))
        output = tracker.update(frame(.9, face(.1), face(.7)))
        self.assertIsNone(output.primary_id)
        output = tracker.update(frame(.94, face(.7)))
        self.assertIsNotNone(output.primary_id)
        self.assertAlmostEqual(output.primary.raw.box_normalized.x_min, .7)

    def test_far_jump_creates_new_track_but_keeps_lost_lock(self):
        tracker = self.tracker()
        tracker.update(frame(0, face(.1)))
        output = tracker.update(frame(.033, face(.7)))
        self.assertEqual(output.primary_id, 1)
        self.assertFalse(output.primary.detected)
        self.assertEqual(output.tracks[1].track_id, 2)

    def test_implausible_scale_change_rejected(self):
        tracker = self.tracker()
        tracker.update(frame(0, face(.2, w=.04, h=.05)))
        output = tracker.update(frame(.033, face(.2, w=.4, h=.5)))
        self.assertFalse(output.primary.detected)
        self.assertEqual(len(output.tracks), 2)

    def test_gradual_scale_change_matches_and_smooths(self):
        tracker = self.tracker()
        tracker.update(frame(0, face()))
        result = tracker.update(frame(.04, face(w=.15, h=.21)))
        self.assertEqual(result.primary_id, 1)
        self.assertLess(result.primary.smoothed.box_normalized.area, result.primary.raw.box_normalized.area)

    def test_approaching_separated_faces_keep_ids(self):
        tracker = self.tracker()
        for i in range(10):
            output = tracker.update(frame(i*.04, face(.1+i*.015, w=.06), face(.7-i*.015, w=.06)))
            self.assertEqual([t.track_id for t in output.tracks], [1, 2])
            self.assertTrue(all(t.detected and not t.uncertain for t in output.tracks))

    def test_crossing_overlap_quarantines_ids_until_expiry(self):
        tracker = self.tracker()
        tracker.update(frame(0, face(.25), face(.5)))
        tracker.update(frame(.1, face(.30), face(.45)))
        output = tracker.update(frame(.2, face(.37), face(.38)))
        self.assertEqual(output.status, "uncertain")
        self.assertTrue(all(t.uncertain and not t.detected for t in output.tracks))
        output = tracker.update(frame(.3, face(.39), face(.36)))
        self.assertTrue(all(not t.detected for t in output.tracks))
        self.assertIsNone(tracker.update(frame(1.2, face(.4), face(.6))).primary_id)

    def test_single_collapsed_detection_competing_for_two_ids_is_uncertain(self):
        tracker = self.tracker()
        tracker.update(frame(0, face(.2, w=.08), face(.4, w=.08)))
        output = tracker.update(frame(.1, face(.3, w=.08)))
        self.assertEqual(output.status, "uncertain")
        self.assertTrue(all(t.uncertain for t in output.tracks))
        self.assertTrue(all(not t.detected for t in output.tracks))

    def test_duplicate_detections_cannot_update_or_create_duplicate_track(self):
        tracker = self.tracker()
        tracker.update(frame(0, face()))
        output = tracker.update(frame(.04, face(), face(.201)))
        self.assertEqual(len(output.tracks), 1)
        self.assertFalse(output.primary.detected)
        self.assertEqual(len(output.unassigned), 2)

    def test_duplicate_initial_detections_remain_unassigned(self):
        output = self.tracker().update(frame(0, face(), face()))
        self.assertEqual(output.tracks, ())
        self.assertEqual(output.status, "uncertain")

    def test_ambiguity_propagates_to_all_competing_detections_without_rebirth(self):
        tracker = self.tracker()
        tracker.update(frame(0, face(.15, w=.06), face(.4, w=.06)))
        # Two duplicates compete for left, middle connects both tracks, right
        # can match only right. The whole competing component must be withheld.
        output = tracker.update(frame(.1, face(.15, w=.06), face(.151, w=.06),
                                       face(.29, w=.06), face(.48, w=.06)))
        self.assertEqual(len(output.tracks), 2)
        self.assertTrue(all(t.uncertain and not t.detected for t in output.tracks))
        self.assertEqual(len(output.unassigned), 4)

    def test_global_matching_beats_order_dependent_greedy(self):
        # First detection can match either old box; second can only match right.
        tracker = self.tracker()
        tracker.update(frame(0, face(.2, w=.05), face(.38, w=.05)))
        output = tracker.update(frame(.1, face(.3, w=.05), face(.48, w=.05)))
        self.assertEqual(len(output.tracks), 2)
        self.assertTrue(all(t.detected for t in output.tracks))
        self.assertAlmostEqual(output.tracks[0].raw.box_normalized.x_min, .3)
        self.assertAlmostEqual(output.tracks[1].raw.box_normalized.x_min, .48)

    def test_no_face_sequence_does_not_allocate_ids(self):
        tracker = self.tracker()
        for i in range(100):
            self.assertEqual(tracker.update(frame(i*.033)).tracks, ())
        self.assertEqual(tracker.metadata()["ids_allocated"], 0)

    def test_reset_discards_state_without_recycling_ids(self):
        tracker = self.tracker()
        old = tracker.update(frame(0, face())).primary
        tracker.reset()
        new = tracker.update(frame(.04, face(.7))).primary
        self.assertEqual(new.track_id, 2)
        self.assertEqual(new.raw, new.smoothed)
        self.assertEqual(old.track_id, 1)

    def test_reset_retains_timestamp_replay_fence(self):
        tracker = self.tracker()
        tracker.update(frame(1, face())); tracker.reset()
        self.assertEqual(tracker.update(frame(.5, face())).status, "invalid_timestamp")
        self.assertEqual(tracker.metadata()["active_tracks"], 0)

    def test_resolution_change_expires_history(self):
        tracker = self.tracker()
        tracker.update(frame(0, face()))
        output = tracker.update(frame(.04, face(), size=(1280, 720)))
        self.assertEqual(output.primary_id, 2)
        self.assertEqual(output.primary.raw, output.primary.smoothed)
        self.assertEqual(output.tracks[-1].state, TrackState.EXPIRED)

    def test_long_sessions_keep_bounded_active_memory(self):
        tracker = self.tracker(max_tracks=2, lost_timeout=.1)
        for i in range(1000):
            output = tracker.update(frame(i*.11, face(.1 if i%2 else .7)))
            self.assertLessEqual(len(output.tracks), 3)  # includes one-frame expiration event
            self.assertLessEqual(tracker.metadata()["active_tracks"], 2)
        self.assertEqual(tracker.metadata()["ids_allocated"], 1000)
        self.assertLess(len(tracker.counts), 20)

    def test_capacity_excess_is_explicit_and_does_not_select_subset(self):
        tracker = self.tracker(max_tracks=2)
        tracker.update(frame(0, face(.1)))
        output = tracker.update(frame(.04, face(.1), face(.4), face(.7)))
        self.assertEqual(output.status, "capacity_exceeded")
        self.assertFalse(output.primary.detected)
        self.assertEqual(tracker.metadata()["ids_allocated"], 1)

    def test_no_birth_beyond_track_capacity(self):
        tracker = self.tracker(max_tracks=1)
        tracker.update(frame(0, face(.1)))
        output = tracker.update(frame(.04, face(.7)))
        self.assertEqual(len(output.tracks), 1)
        self.assertEqual(len(output.unassigned), 1)

    def test_snapshots_are_immutable_and_not_modified_by_next_update(self):
        tracker = self.tracker()
        previous = tracker.update(frame(0, face())).primary
        tracker.update(frame(.04, face(.21)))
        self.assertEqual(previous.last_detected, 0)
        with self.assertRaises(FrozenInstanceError):
            previous.state = TrackState.LOST

    def test_time_ema_has_expected_coefficient_and_no_overshoot(self):
        tracker = self.tracker(smoothing_tau=.1)
        old = tracker.update(frame(0, face(.2))).primary
        new = tracker.update(frame(.05, face(.24))).primary
        expected = .2+(1-math.exp(-.5))*.04
        self.assertAlmostEqual(new.smoothed.box_normalized.x_min, expected)
        self.assertLess(old.raw.center_x, new.smoothed.center_x)
        self.assertLess(new.smoothed.center_x, new.raw.center_x)

    def test_variable_dt_gives_same_result_for_same_total_elapsed(self):
        trackers = [self.tracker(), self.tracker()]
        results = []
        for tracker, times in zip(trackers, ((.02, .04, .10), (.04, .1))):
            tracker.update(frame(0, face(.2)))
            for t in times:
                result = tracker.update(frame(t, face(.24)))
            results.append(result.primary.smoothed.center_x)
        self.assertAlmostEqual(*results)

    def test_static_smoothing_converges(self):
        tracker = self.tracker()
        tracker.update(frame(0, face(.2)))
        for i in range(1, 60):
            result = tracker.update(frame(i*.02, face(.24)))
        self.assertAlmostEqual(result.primary.smoothed.center_x, result.primary.raw.center_x, places=4)

    def test_smoothing_zero_passes_through(self):
        tracker = self.tracker(smoothing_tau=0)
        tracker.update(frame(0, face()))
        output = tracker.update(frame(.04, face(.24)))
        self.assertEqual(output.primary.raw, output.primary.smoothed)

    def test_smoothing_histories_are_independent(self):
        tracker = self.tracker()
        tracker.update(frame(0, face(.1), face(.7)))
        output = tracker.update(frame(.04, face(.12), face(.68)))
        self.assertLess(output.tracks[0].smoothed.center_x, output.tracks[0].raw.center_x)
        self.assertGreater(output.tracks[1].smoothed.center_x, output.tracks[1].raw.center_x)

    def test_large_dt_resets_smoothing(self):
        tracker = self.tracker()
        tracker.update(frame(0, face()))
        output = tracker.update(frame(.4, face(.24)))
        self.assertEqual(output.primary.raw, output.primary.smoothed)

    def test_invalid_source_times_never_refresh_observation(self):
        for stamp in (-1, True, None, float('nan'), float('inf'), .1, 90, 100, 2**10000):
            tracker = self.tracker()
            tracker.update(frame(.1, face()))
            bad = replace(frame(.2, face()), timestamp_ms=stamp)
            output = tracker.update(bad, observed_at=.2, now=.2)
            self.assertEqual(output.status, "invalid_timestamp")
            self.assertFalse(output.primary.detected)
            self.assertEqual(output.primary.last_detected, .1)
            self.assertAlmostEqual(output.primary.observation_age, .1)

    def test_bad_host_clocks_never_ingest_detection(self):
        for observed, now in ((float('nan'), .2), (.2, float('inf')), (.3, .2), (.05, .05), (.1, .2), (-1, .2)):
            tracker = self.tracker()
            tracker.update(frame(.1, face()))
            output = tracker.update(frame(.2, face()), observed_at=observed, now=now)
            self.assertEqual(output.status, "invalid_timestamp")
            self.assertFalse(output.primary.detected)

    def test_host_age_is_camera_read_age_not_completion_time(self):
        tracker = self.tracker()
        output = tracker.update(frame(5, face()), observed_at=10., now=10.02)
        self.assertEqual(output.primary.last_detected, 10.)
        self.assertAlmostEqual(output.primary.observation_age, .02)

    def test_stale_detection_cannot_create_or_refresh_track(self):
        tracker = self.tracker()
        output = tracker.update(frame(0, face()), observed_at=10, now=10.3)
        self.assertEqual(output.status, "stale_frame")
        self.assertEqual(output.tracks, ())

    def test_expired_detector_frame_marks_loss(self):
        tracker = self.tracker()
        tracker.update(frame(0, face()))
        output = tracker.update(frame(.04, face(), status="expired"))
        self.assertFalse(output.primary.detected)

    def test_invalid_geometry_is_rejected_without_stale_output(self):
        tracker = self.tracker()
        tracker.update(frame(0, face()))
        bad = replace(face(), box_normalized=replace(face().box_normalized, x_min=float('nan')))
        output = tracker.update(frame(.04, bad))
        self.assertEqual(output.status, "invalid_geometry")
        self.assertFalse(output.primary.detected)

    def test_out_of_bounds_geometry_rejected(self):
        tracker = self.tracker()
        bad = replace(face(), box_normalized=replace(face().box_normalized, x_max=1.1))
        self.assertEqual(tracker.update(frame(0, bad)).status, "invalid_geometry")

    def test_profile_is_bounded_and_has_association_smoothing_total_age(self):
        tracker, profile = self.tracker(), Profile(capacity=2)
        for i in range(10):
            tracker.update(frame(i*.033, face()), profile=profile)
        summary = profile.summary()
        self.assertEqual(set(summary), {'face_association', 'face_smoothing', 'face_tracking', 'face_observation_age'})
        self.assertTrue(all(item['count'] == 10 and item['percentile_samples'] == 2 for item in summary.values()))

    def test_disabled_profile_avoids_timing_calls(self):
        tracker = self.tracker()
        with patch('face_tracking.face_tracker.time.perf_counter', side_effect=AssertionError('timer called')):
            tracker.update(frame(0, face()), profile=Profile(enabled=False))

    def test_invalid_configuration_rejected(self):
        for kwargs in ({'confirmation_hits':0}, {'confirmation_hits':True}, {'max_tracks':9},
                       {'lost_timeout':0}, {'smoothing_tau':float('nan')}, {'smoothing_tau':-1},
                       {'confirmation_seconds':float('inf')}, {'confirmation_gap':0}):
            with self.assertRaises(ValueError):
                TrackerConfig(**kwargs)

    def test_identity_switch_metric_does_not_claim_real_world_ground_truth(self):
        metadata = self.tracker().metadata()
        self.assertIsNone(metadata['identity_switches'])
        self.assertIn('ground truth', metadata['identity_switches_reason'])
