from dataclasses import FrozenInstanceError, replace
import math
import unittest
from unittest.mock import patch

from face_tracking.centering import (CenteringConfig, CenteringStatus as S, CorrectionDirection as D,
                                     DeadZone, FaceCentering)
from face_tracking.centering_geometry import calculate_offsets
from face_tracking.face_geometry import adapt_result, convert_box
from face_tracking.face_tracker import FaceTracker, TrackerConfig
from face_tracking.track_models import FaceTrack, TrackedFaces, TrackState
from hand_tracking.performance import Profile
from .helpers import detection, result
from .test_tracker import face, frame


def observation(t=1., x=0., y=0., *, raw_x=None, raw_y=None, key=1, state=TrackState.TRACKED,
                visible=True, uncertain=False, size=(1920,1080), matches=5):
    def box(ex, ey):
        return convert_box((ex+1)/2-.015, (ey+1)/2-.02, .03, .04, (1,1), size, .9)
    smooth = box(x, y)
    raw = box(x if raw_x is None else raw_x, y if raw_y is None else raw_y)
    track = FaceTrack(key, state, raw if visible else None, smooth if visible else None,
                      .9, 0., t, 0., matches, 0 if visible else 1, True, uncertain)
    return TrackedFaces(round(t*1000), size, (track,), key)


def with_primary(observed, **values):
    return replace(observed, tracks=(replace(observed.primary, **values),))


class GeometryTest(unittest.TestCase):
    def test_exact_center_has_zero_offsets(self):
        output = calculate_offsets((960,540), (1920,1080))
        self.assertEqual(output.target_center, (960,540))
        self.assertEqual(output.pixel_error, (0,0))
        self.assertEqual(output.normalized_error, (0,0))

    def test_left_right_up_down(self):
        for center, expected in (((480,540),(-.5,0)), ((1440,540),(.5,0)),
                                 ((960,270),(0,-.5)), ((960,810),(0,.5))):
            self.assertEqual(calculate_offsets(center,(1920,1080)).normalized_error, expected)

    def test_all_four_corners_and_bounds(self):
        for x in (0,1920):
            for y in (0,1080):
                output = calculate_offsets((x,y),(1920,1080))
                self.assertEqual(output.normalized_error, (-1 if x==0 else 1, -1 if y==0 else 1))

    def test_non_square_and_multiple_resolutions(self):
        for width, height in ((1920,1080),(640,360),(320,640),(1001,503)):
            output = calculate_offsets((width*.7,height*.3),(width,height))
            self.assertAlmostEqual(output.normalized_error[0], .4)
            self.assertAlmostEqual(output.normalized_error[1], -.4)

    def test_custom_target_uses_original_half_frame_denominator(self):
        output = calculate_offsets((960,540),(1920,1080),target=(.75,.25))
        self.assertEqual(output.target_center,(1440,270))
        self.assertEqual(output.normalized_error,(-.5,.5))
        self.assertEqual(calculate_offsets((0,0),(1920,1080),target=(1,1)).normalized_error,(-2,-2))

    def test_invalid_dimensions_rejected(self):
        for size in ((0,1080),(-1,1),(True,1),(1.5,1),(1,),None):
            with self.assertRaises(ValueError):
                calculate_offsets((0,0),size)

    def test_invalid_coordinates_rejected(self):
        for center in ((-1,0),(1921,1),(1,1081),(math.nan,1),(1,math.inf),(True,1),None,(1,)):
            with self.assertRaises(ValueError):
                calculate_offsets(center,(1920,1080))

    def test_invalid_target_rejected(self):
        for target in ((-1,0),(1.1,.5),(math.nan,.5),(False,.5),None):
            with self.assertRaises(ValueError):
                calculate_offsets((960,540),(1920,1080),target=target)

    def test_inference_geometry_maps_to_original_capture_pixels(self):
        detected = adapt_result(result(detection(400,90,160,180)), (640,360),(1920,1080),1000)
        output = calculate_offsets((detected.primary.center_x,detected.primary.center_y),detected.frame_size)
        self.assertEqual(detected.primary.center_x,1440)
        self.assertEqual(output.normalized_error,(.5,0))

    def test_clipped_partial_box_uses_clipped_visible_center(self):
        detected = convert_box(-20,90,160,180,(640,360),(1920,1080),.9)
        output = calculate_offsets((detected.center_x,detected.center_y),(1920,1080))
        self.assertAlmostEqual(output.normalized_error[0], -.78125)
        self.assertEqual(output.normalized_error[1],0)


class CenteringTest(unittest.TestCase):
    def test_exact_center_is_actionable_zero_hold(self):
        output = FaceCentering().update(observation(),now=1)
        self.assertEqual(output.status,S.CENTERED)
        self.assertTrue(output.is_centered)
        self.assertTrue(output.actionable)
        self.assertEqual(output.horizontal.demand,0)
        self.assertEqual(output.vertical.demand,0)
        self.assertEqual(output.horizontal.direction,D.NONE)

    def test_conceptual_directions_are_correct(self):
        for x,y,xd,yd in ((-.4,0,D.PAN_LEFT,D.NONE),(.4,0,D.PAN_RIGHT,D.NONE),
                          (0,-.4,D.NONE,D.TILT_UP),(0,.4,D.NONE,D.TILT_DOWN)):
            output = FaceCentering().update(observation(x=x,y=y),now=1)
            self.assertEqual(output.horizontal.direction,xd)
            self.assertEqual(output.vertical.direction,yd)
            self.assertEqual(output.status,S.CORRECTION_NEEDED)

    def test_all_quadrants_and_bounded_demand(self):
        for x in (-.98,.98):
            for y in (-.96,.96):
                output = FaceCentering().update(observation(x=x,y=y),now=1)
                for error,axis in ((x,output.horizontal),(y,output.vertical)):
                    self.assertLessEqual(abs(axis.demand),1)
                    self.assertGreater(axis.demand*error,0)
                    self.assertTrue(math.isfinite(axis.demand))

    def test_proportional_demand_uses_deactivation_threshold(self):
        output = FaceCentering().update(observation(x=.4),now=1)
        self.assertAlmostEqual(output.horizontal.demand,(.4-.07)/.93)

    def test_demand_increases_with_error(self):
        values=[FaceCentering().update(observation(x=x),now=1).horizontal.demand for x in (.13,.3,.6,.95)]
        self.assertEqual(values,sorted(values))

    def test_error_is_preserved_inside_dead_zone(self):
        output = FaceCentering().update(observation(x=.05,y=-.03),now=1)
        self.assertAlmostEqual(output.horizontal.error,.05)
        self.assertAlmostEqual(output.vertical.error,-.03)
        self.assertEqual(output.horizontal.demand,0)
        self.assertEqual(output.vertical.demand,0)

    def test_smoothed_position_drives_decision_raw_is_debug_only(self):
        output = FaceCentering().update(observation(x=.05,raw_x=.5),now=1)
        self.assertEqual(output.status,S.CENTERED)
        self.assertAlmostEqual(output.horizontal.raw_error,.5)
        self.assertAlmostEqual(output.horizontal.error,.05)
        self.assertNotEqual(output.raw_center,output.smoothed_center)

    def test_pixel_error_is_in_capture_pixels(self):
        output = FaceCentering().update(observation(x=.5,y=-.5),now=1)
        self.assertAlmostEqual(output.horizontal.error_px,480)
        self.assertAlmostEqual(output.vertical.error_px,-270)

    def test_custom_target_and_demand_saturation(self):
        calculator = FaceCentering(CenteringConfig(target=(1,1)))
        output = calculator.update(observation(x=-.9,y=-.9),now=1)
        self.assertAlmostEqual(output.horizontal.error,-1.9)
        self.assertEqual(output.horizontal.demand,-1)
        self.assertEqual(output.vertical.demand,-1)

    def test_activation_is_strict_and_deactivation_inclusive(self):
        calculator = FaceCentering()
        self.assertFalse(calculator.update(observation(1,x=.12),now=1).horizontal.active)
        self.assertTrue(calculator.update(observation(1.01,x=.121),now=1.01).horizontal.active)
        self.assertTrue(calculator.update(observation(1.02,x=.071),now=1.02).horizontal.active)
        self.assertFalse(calculator.update(observation(1.03,x=.07),now=1.03).horizontal.active)

    def test_hysteresis_prevents_chatter_in_band(self):
        calculator = FaceCentering()
        for i,x in enumerate((.121,.119,.11,.115,.08)):
            self.assertTrue(calculator.update(observation(1+i*.02,x=x),now=1+i*.02).horizontal.active)
        self.assertFalse(calculator.update(observation(1.1,x=.069),now=1.1).horizontal.active)
        self.assertFalse(calculator.update(observation(1.12,x=.11),now=1.12).horizontal.active)

    def test_small_sign_reversal_becomes_inactive(self):
        calculator = FaceCentering()
        calculator.update(observation(1,x=.2),now=1)
        output = calculator.update(observation(1.02,x=-.08),now=1.02)
        self.assertEqual(output.horizontal.demand,0)
        self.assertEqual(output.horizontal.direction,D.NONE)
        output = calculator.update(observation(1.04,x=-.13),now=1.04)
        self.assertEqual(output.horizontal.direction,D.PAN_LEFT)

    def test_large_reversal_requires_opposite_activation_and_is_deterministic(self):
        calculator = FaceCentering()
        calculator.update(observation(1,x=.3),now=1)
        output=calculator.update(observation(1.02,x=-.3),now=1.02)
        self.assertEqual(output.horizontal.direction,D.PAN_LEFT)
        self.assertEqual(calculator.metadata()['counters']['direction_reversals'],1)

    def test_axes_have_independent_hysteresis(self):
        calculator=FaceCentering()
        calculator.update(observation(1,x=.2,y=.03),now=1)
        output=calculator.update(observation(1.02,x=.1,y=.1),now=1.02)
        self.assertTrue(output.horizontal.active)
        self.assertFalse(output.vertical.active)

    def test_independent_axis_configuration(self):
        calculator=FaceCentering(CenteringConfig(horizontal=DeadZone(.2,.1),vertical=DeadZone(.1,.05)))
        output=calculator.update(observation(x=.15,y=.15),now=1)
        self.assertFalse(output.horizontal.active)
        self.assertTrue(output.vertical.active)

    def test_new_primary_resets_hysteresis(self):
        calculator=FaceCentering()
        calculator.update(observation(1,x=.2),now=1)
        output=calculator.update(observation(1.02,x=.1,key=2),now=1.02)
        self.assertEqual(output.primary_id,2)
        self.assertFalse(output.horizontal.active)

    def test_lost_target_immediately_suppresses_and_clears_coordinates(self):
        calculator=FaceCentering()
        calculator.update(observation(1,x=.5),now=1)
        output=calculator.update(observation(1.02,x=.5,state=TrackState.LOST,visible=False),now=1.02)
        self.assertEqual(output.status,S.TARGET_LOST)
        self.assertIsNone(output.smoothed_center)
        self.assertIsNone(output.raw_center)
        self.assertIsNone(output.horizontal.error)
        self.assertEqual(output.horizontal.demand,0)
        self.assertFalse(output.actionable)

    def test_reacquisition_starts_with_inactive_hysteresis(self):
        calculator=FaceCentering()
        calculator.update(observation(1,x=.2),now=1)
        calculator.update(observation(1.02,state=TrackState.LOST,visible=False),now=1.02)
        output=calculator.update(observation(1.04,x=.1,matches=1),now=1.04)
        self.assertEqual(output.status,S.CENTERED)

    def test_recovery_is_detected_even_if_caller_skipped_missing_snapshot(self):
        calculator=FaceCentering()
        calculator.update(observation(1,x=.2),now=1)
        self.assertFalse(calculator.update(observation(1.04,x=.1,matches=1),now=1.04).horizontal.active)

    def test_long_update_gap_resets_hysteresis(self):
        calculator=FaceCentering()
        calculator.update(observation(1,x=.2),now=1)
        self.assertFalse(calculator.update(observation(1.4,x=.1),now=1.4).horizontal.active)

    def test_expired_primary_produces_no_demand(self):
        output=FaceCentering().update(observation(state=TrackState.EXPIRED,visible=False),now=1)
        self.assertEqual(output.status,S.TARGET_LOST)
        self.assertEqual(output.vertical.demand,0)

    def test_uncertain_primary_produces_no_demand_even_if_coordinates_present(self):
        output=FaceCentering().update(observation(x=.5,uncertain=True),now=1)
        self.assertEqual(output.status,S.TARGET_UNCERTAIN)
        self.assertIsNone(output.raw_center)
        self.assertEqual(output.horizontal.demand,0)

    def test_uncertainty_on_other_tracks_does_not_redirect_locked_primary(self):
        observed=replace(observation(x=.3),status='uncertain')
        output=FaceCentering().update(observed,now=1)
        self.assertEqual(output.primary_id,1)
        self.assertEqual(output.horizontal.direction,D.PAN_RIGHT)

    def test_tentative_target_never_actionable(self):
        output=FaceCentering().update(observation(x=.5,state=TrackState.TENTATIVE),now=1)
        self.assertEqual(output.status,S.WAITING_FOR_TARGET)
        self.assertEqual(output.horizontal.demand,0)

    def test_no_primary_does_not_choose_another_face(self):
        observed=replace(observation(x=.5),primary_id=None)
        output=FaceCentering().update(observed,now=1)
        self.assertEqual(output.status,S.WAITING_FOR_TARGET)
        self.assertIsNone(output.primary_id)
        self.assertFalse(output.actionable)

    def test_no_target_and_dangling_primary(self):
        self.assertEqual(FaceCentering().update(None,now=1).status,S.NO_TARGET)
        empty=TrackedFaces(1000,(1920,1080),(),None)
        self.assertEqual(FaceCentering().update(empty,now=1).status,S.NO_TARGET)
        self.assertEqual(FaceCentering().update(replace(empty,primary_id=1),now=1).status,S.TARGET_LOST)

    def test_stale_target_has_no_coordinates_or_demand(self):
        output=FaceCentering().update(observation(x=.5),now=1.251)
        self.assertEqual(output.status,S.STALE_OBSERVATION)
        self.assertAlmostEqual(output.observation_age,.251)
        self.assertEqual(output.observation_timestamp,1)
        self.assertIsNone(output.smoothed_center)
        self.assertEqual(output.horizontal.demand,0)

    def test_repeated_calculation_never_refreshes_detection_timestamp(self):
        calculator=FaceCentering()
        observed=observation(x=.5)
        a=calculator.update(observed,now=1.1)
        b=calculator.update(observed,now=1.3)
        self.assertEqual(a.observation_timestamp,b.observation_timestamp)
        self.assertEqual(b.status,S.STALE_OBSERVATION)
        self.assertEqual(b.horizontal.demand,0)

    def test_snapshot_age_is_recomputed_from_actual_detection(self):
        observed=with_primary(observation(),observation_age=0)
        self.assertAlmostEqual(FaceCentering().update(observed,now=1.2).observation_age,.2)

    def test_freshness_boundary_and_later_consumer_check(self):
        output=FaceCentering().update(observation(x=.5),now=1.25)
        self.assertTrue(output.actionable)
        self.assertTrue(output.fresh_at(1.25))
        self.assertFalse(output.fresh_at(1.25001))
        self.assertFalse(output.fresh_at(.99))
        self.assertFalse(output.fresh_at(math.nan))

    def test_invalid_detection_timestamps_fail_closed(self):
        for stamp in (None,math.nan,math.inf,-1,2,True):
            output=FaceCentering().update(with_primary(observation(x=.5),last_detected=stamp),now=1)
            self.assertEqual(output.status,S.INVALID_OBSERVATION)
            self.assertEqual(output.horizontal.demand,0)

    def test_invalid_source_timestamps_fail_closed(self):
        for stamp in (None,math.nan,math.inf,-1,1.5,True,2**10000):
            output=FaceCentering().update(replace(observation(x=.5),timestamp_ms=stamp),now=1)
            self.assertEqual(output.status,S.INVALID_OBSERVATION)
            self.assertFalse(output.actionable)

    def test_backwards_source_timestamp_and_clock_fail_closed(self):
        calculator=FaceCentering()
        calculator.update(observation(1,x=.5),now=1)
        output=calculator.update(observation(.99,x=.5),now=1.01)
        self.assertEqual(output.status,S.INVALID_OBSERVATION)
        output=calculator.update(observation(1.01,x=.5),now=.99)
        self.assertEqual(output.status,S.INVALID_OBSERVATION)

    def test_invalid_host_clocks_fail_closed(self):
        for now in (None,math.nan,math.inf,-1,True):
            output=FaceCentering().update(observation(x=.5),now=now)
            self.assertEqual(output.status,S.INVALID_OBSERVATION)
            self.assertEqual(output.horizontal.demand,0)
            self.assertIsNone(output.evaluated_at)

    def test_missing_smoothed_geometry_is_not_replaced_with_raw(self):
        output=FaceCentering().update(with_primary(observation(x=.5),smoothed=None),now=1)
        self.assertEqual(output.status,S.INVALID_OBSERVATION)
        self.assertEqual(output.horizontal.demand,0)

    def test_invalid_coordinates_are_suppressed(self):
        for x in (math.nan,math.inf,-1,1921):
            observed=observation(x=.5)
            observed=with_primary(observed,smoothed=replace(observed.primary.smoothed,center_x=x))
            output=FaceCentering().update(observed,now=1)
            self.assertEqual(output.status,S.INVALID_OBSERVATION)
            self.assertIsNone(output.smoothed_center)

    def test_mixed_inference_pixels_are_rejected(self):
        observed=observation(x=.5)
        observed=with_primary(observed,smoothed=replace(observed.primary.smoothed,center_x=480))
        self.assertEqual(FaceCentering().update(observed,now=1).status,S.INVALID_OBSERVATION)

    def test_invalid_frame_dimensions_are_suppressed(self):
        output=FaceCentering().update(replace(observation(),frame_size=(0,1080)),now=1)
        self.assertEqual(output.status,S.INVALID_OBSERVATION)
        self.assertIsNone(output.frame_size)

    def test_primary_must_be_marked_as_locked(self):
        observed=with_primary(observation(x=.5),primary=False)
        self.assertEqual(FaceCentering().update(observed,now=1).status,S.INVALID_OBSERVATION)

    def test_stale_tracker_status_is_explicit(self):
        observed=replace(observation(x=.5,visible=False),status='stale_frame')
        self.assertEqual(FaceCentering().update(observed,now=1).status,S.STALE_OBSERVATION)

    def test_bad_tracker_status_is_not_actionable(self):
        for status in ('invalid_timestamp','invalid_geometry','capacity_exceeded','unexpected'):
            output=FaceCentering().update(replace(observation(x=.5),status=status),now=1)
            self.assertEqual(output.status,S.INVALID_OBSERVATION)

    def test_reset_clears_hysteresis_and_retains_replay_fence(self):
        calculator=FaceCentering()
        calculator.update(observation(1,x=.2),now=1)
        calculator.reset()
        self.assertFalse(calculator.update(observation(1.02,x=.1),now=1.02).horizontal.active)
        self.assertEqual(calculator.update(observation(.9,x=.5),now=1.03).status,S.INVALID_OBSERVATION)

    def test_new_session_does_not_inherit_state(self):
        first=FaceCentering()
        first.update(observation(x=.5),now=1)
        output=FaceCentering().update(observation(x=.1),now=1)
        self.assertEqual(output.status,S.CENTERED)

    def test_frame_size_change_resets_hysteresis(self):
        calculator=FaceCentering()
        calculator.update(observation(1,x=.2),now=1)
        output=calculator.update(observation(1.02,x=.1,size=(640,360)),now=1.02)
        self.assertFalse(output.horizontal.active)

    def test_result_is_immutable_and_does_not_retain_mutable_input(self):
        output=FaceCentering().update(observation(x=.5),now=1)
        with self.assertRaises(FrozenInstanceError):
            output.horizontal.demand=0
        self.assertIsInstance(output.smoothed_center,tuple)

    def test_diagnostics_are_bounded_numeric_and_exclude_positions(self):
        calculator=FaceCentering()
        for i in range(1000):
            calculator.update(observation(1+i*.01,x=.3 if i%2 else 0),now=1+i*.01)
        metadata=calculator.metadata()
        self.assertEqual(sum(metadata['states'].values()),1000)
        self.assertLessEqual(len(metadata['transitions']),64)
        self.assertNotIn('smoothed_center',metadata)
        self.assertNotIn('raw_center',metadata)

    def test_opt_in_profile_has_correct_units_and_capacity(self):
        calculator=FaceCentering()
        profile=Profile(capacity=2)
        for i in range(10):
            calculator.update(observation(1+i*.01),now=1.02+i*.01,profile=profile)
        summary=profile.summary()
        self.assertEqual(summary['face_centering']['count'],10)
        self.assertEqual(summary['face_centering']['percentile_samples'],2)
        self.assertAlmostEqual(summary['centering_observation_age']['mean_ms'],20)

    def test_disabled_profile_does_not_read_timing_clock(self):
        with patch('face_tracking.centering.time.perf_counter',side_effect=AssertionError('timer called')):
            FaceCentering().update(observation(),now=1,profile=Profile(enabled=False))

    def test_invalid_configurations_are_rejected(self):
        for args in ((.1,.1),(.1,.2),(1.1,.1),(.1,-.1),(math.nan,.1),(.1,True)):
            with self.assertRaises(ValueError):
                DeadZone(*args)
        for kwargs in ({'target':(1.1,0)}, {'target':[.5,.5]}, {'max_observation_age':.5},
                       {'max_observation_age':0}, {'horizontal':None}):
            with self.assertRaises(ValueError):
                CenteringConfig(**kwargs)

    def test_real_tracker_confirmation_lock_loss_and_recovery(self):
        tracker,calculator=FaceTracker(),FaceCentering()
        for t in (0,.04):
            self.assertEqual(calculator.update(tracker.update(frame(t,face(.7))),now=t).status,S.WAITING_FOR_TARGET)
        tracked=tracker.update(frame(.08,face(.7)))
        output=calculator.update(tracked,now=.08)
        self.assertEqual(output.horizontal.direction,D.PAN_RIGHT)
        tracked=tracker.update(frame(.12,face(.7),face(.1,confidence=.99)))
        self.assertEqual(calculator.update(tracked,now=.12).primary_id,1)
        lost=calculator.update(tracker.update(frame(.16,face(.1))),now=.16)
        self.assertEqual(lost.status,S.TARGET_LOST)
        self.assertEqual(lost.horizontal.demand,0)
        recovered=calculator.update(tracker.update(frame(.2,face(.69),face(.1))),now=.2)
        self.assertEqual(recovered.primary_id,1)
        self.assertEqual(recovered.horizontal.direction,D.PAN_RIGHT)

    def test_real_ambiguous_crossing_suppresses_recommendation(self):
        tracker=FaceTracker(TrackerConfig(confirmation_hits=1,confirmation_seconds=0))
        calculator=FaceCentering()
        calculator.update(tracker.update(frame(0,face(.25),face(.5))),now=0)
        calculator.update(tracker.update(frame(.1,face(.3),face(.45))),now=.1)
        output=calculator.update(tracker.update(frame(.2,face(.37),face(.38))),now=.2)
        self.assertEqual(output.status,S.TARGET_UNCERTAIN)
        self.assertEqual(output.horizontal.demand,0)
        self.assertIsNone(output.smoothed_center)
