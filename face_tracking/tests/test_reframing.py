from dataclasses import FrozenInstanceError, replace
import math
import unittest
from unittest.mock import patch

import numpy as np

from face_tracking.centering import DeadZone, FaceCentering, CenteringStatus
from face_tracking.digital_reframing import (DigitalReframer, ReframeConfig, crop_dimensions,
                                           crop_rectangle, clamp_center)
from face_tracking.reframing_preview import ReframeRenderer, extract_crop
from face_tracking.face_tracker import FaceTracker, TrackerConfig
from hand_tracking.performance import Profile
from .test_centering import observation
from .test_tracker import frame, face


def recommendation(t=1, x=0, y=0, **kwargs):
    return FaceCentering().update(observation(t,x,y,**kwargs),now=t)


def update(reframer,t=1,x=0,y=0,**kwargs):
    size=kwargs.get('size',(1920,1080))
    return reframer.update(recommendation(t,x,y,**kwargs),source_size=size,now=t)


class CropGeometryTest(unittest.TestCase):
    def test_default_crop_and_center_rectangle(self):
        self.assertEqual(crop_dimensions((1920,1080)),(1280,720))
        rect=crop_rectangle((960,540),(1920,1080),(1280,720))
        self.assertEqual((rect.left,rect.top,rect.right,rect.bottom),(320,180,1600,900))

    def test_all_boundaries_and_corners(self):
        for x in (-1e6,1e6):
            for y in (-1e6,1e6):
                rect=crop_rectangle((x,y),(1920,1080),(1280,720))
                self.assertEqual(rect.left,0 if x<0 else 640)
                self.assertEqual(rect.top,0 if y<0 else 360)
                self.assertEqual(rect.size,(1280,720))

    def test_continuous_center_bounds(self):
        self.assertEqual(clamp_center((0,0),(1920,1080),(1280,720)),(640,360))
        self.assertEqual(clamp_center((1920,1080),(1920,1080),(1280,720)),(1280,720))

    def test_odd_dimensions_keep_uniform_scale_to_pixel_precision(self):
        for w,h in ((1921,1081),(641,361),(101,57),(7,11),(1,1)):
            cw,ch=crop_dimensions((w,h))
            self.assertLessEqual(abs(cw-w*2/3),.5)
            self.assertLessEqual(abs(ch-h*2/3),.5)
            rect=crop_rectangle((w/2,h/2),(w,h),(cw,ch))
            self.assertTrue(0<=rect.left<rect.right<=w)
            self.assertTrue(0<=rect.top<rect.bottom<=h)

    def test_scale_limits_never_empty_or_outside(self):
        for scale in (1e-8,.01,.5,2/3,1):
            cw,ch=crop_dimensions((1920,1080),scale)
            self.assertTrue(1<=cw<=1920 and 1<=ch<=1080)
        self.assertEqual(crop_dimensions((1920,1080),1),(1920,1080))

    def test_round_half_up_is_deterministic(self):
        self.assertEqual(crop_dimensions((9,5),.5),(5,3))
        rect=crop_rectangle((3,3),(9,9),(3,3))
        self.assertEqual((rect.left,rect.top),(2,2))

    def test_invalid_crop_and_source_inputs_rejected(self):
        for source in ((0,10),(-1,1),(True,10),(2.5,3)):
            with self.assertRaises(ValueError):crop_dimensions(source)
        for scale in (0,-1,1.1,math.nan,math.inf,True):
            with self.assertRaises(ValueError):crop_dimensions((1920,1080),scale)
        for size in ((1921,720),(1280,1081),(0,720)):
            with self.assertRaises(ValueError):crop_rectangle((960,540),(1920,1080),size)
        with self.assertRaises(ValueError):crop_rectangle((math.nan,0),(1920,1080),(1280,720))


class ReframerTest(unittest.TestCase):
    def test_first_frame_starts_centered_without_snapping(self):
        output=update(DigitalReframer(),x=.8)
        self.assertEqual(output.center,(960,540))
        self.assertTrue(output.fresh_target)
        self.assertFalse(output.moving)

    def test_left_right_up_down_follow(self):
        for x,y in ((-.4,0),(.4,0),(0,-.4),(0,.4)):
            reframer=DigitalReframer()
            first=update(reframer,1,x,y)
            second=update(reframer,1.033,x,y)
            self.assertGreater((second.center[0]-first.center[0])*x+(second.center[1]-first.center[1])*y,0)

    def test_stationary_face_settles_without_original_frame_demand_drift(self):
        reframer=DigitalReframer()
        for i in range(150):output=update(reframer,1+i/60,.2)
        held=output.center
        for i in range(150,250):
            output=update(reframer,1+i/60,.2)
            self.assertEqual(output.center,held)
            self.assertFalse(output.moving)
        self.assertLess(abs(output.composition_error[0]),.065)
        self.assertEqual(recommendation(6,.2).status,CenteringStatus.CORRECTION_NEEDED)

    def test_original_frame_center_does_not_override_current_crop_dead_zone(self):
        reframer=DigitalReframer()
        for i in range(120):output=update(reframer,1+i/60,.3)
        before=output.center
        output=update(reframer,3.1,.3)
        self.assertEqual(output.center,before)

    def test_inside_dead_zone_has_no_micro_motion(self):
        reframer=DigitalReframer()
        for i,x in enumerate((.02,-.01,.03,-.03,.025)):
            self.assertEqual(update(reframer,1+i*.03,x).center,(960,540))

    def test_motion_reactivates_smoothly_outside_crop_dead_zone(self):
        reframer=DigitalReframer()
        update(reframer,1,.02)
        output=update(reframer,1.033,.2)
        self.assertTrue(output.moving)
        self.assertLess(output.center[0],output.desired_center[0])

    def test_diagonal_vector_speed_is_limited(self):
        reframer=DigitalReframer(ReframeConfig(max_speed=120))
        previous=update(reframer,1,.9,.9)
        for i in range(1,40):
            current=update(reframer,1+i/60,.9,.9)
            self.assertLessEqual(math.dist(previous.center,current.center),120/60+1e-8)
            previous=current

    def test_no_overshoot(self):
        reframer=DigitalReframer(ReframeConfig(follow_tau=0,max_speed=1e5))
        update(reframer,1,.2)
        for i in range(1,50):
            output=update(reframer,1+i*.03,.2)
            self.assertLessEqual(output.center[0],1152+1e-8)
            self.assertGreaterEqual(output.center[0],960)

    def test_time_aware_ema_agrees_at_30_and_60_fps(self):
        config=ReframeConfig(max_speed=1e6,horizontal=DeadZone(.001,0),vertical=DeadZone(.001,0))
        centers=[]
        for fps in (30,60):
            reframer=DigitalReframer(config)
            for i in range(fps+1):output=update(reframer,1+i/fps,.2)
            centers.append(output.center)
        self.assertAlmostEqual(centers[0][0],centers[1][0],places=7)

    def test_variable_intervals_are_stable(self):
        reframer=DigitalReframer()
        previous=update(reframer,1,.4,.3)
        for t in (1.001,1.017,1.06,1.09,1.17,1.2):
            output=update(reframer,t,.4,.3)
            self.assertLessEqual(math.dist(previous.center,output.center),600*(t-previous.updated_at)+1e-8)
            self.assertTrue(all(math.isfinite(v) for v in output.center))
            previous=output

    def test_large_time_gap_holds_first_recovery_frame(self):
        reframer=DigitalReframer()
        update(reframer,1,.8)
        before=update(reframer,1.03,.8)
        recovered=update(reframer,2,.8)
        self.assertEqual(recovered.center,before.center)
        resumed=update(reframer,2.03,.8)
        self.assertTrue(resumed.moving)
        self.assertLessEqual(math.dist(resumed.center,recovered.center),18+1e-8)

    def test_tiny_dt_and_repeated_source_do_not_divide_by_zero(self):
        reframer=DigitalReframer()
        first=update(reframer,1,.4)
        duplicate=update(reframer,1.000001,.4)
        self.assertEqual(duplicate.center,first.center)
        self.assertEqual(duplicate.reason,'DUPLICATE_OBSERVATION')

    def test_actual_tiny_dt_has_bounded_movement(self):
        reframer=DigitalReframer()
        before=update(reframer,1,.4)
        observed=replace(recommendation(1.000001,.4),source_timestamp_ms=1001)
        after=reframer.update(observed,source_size=(1920,1080),now=1.000001)
        self.assertLessEqual(math.dist(before.center,after.center),.000601)

    def test_repeated_host_timestamp_never_moves(self):
        reframer=DigitalReframer()
        before=update(reframer,1,.4)
        observed=replace(recommendation(1,.4),source_timestamp_ms=1001)
        after=reframer.update(observed,source_size=(1920,1080),now=1)
        self.assertEqual(after.center,before.center)

    def test_backward_or_invalid_now_holds(self):
        for now in (None,math.nan,math.inf,True,-1,.9):
            reframer=DigitalReframer()
            before=update(reframer,1,.4)
            output=reframer.update(recommendation(1.01,.8),source_size=(1920,1080),now=now)
            self.assertEqual(output.center,before.center)
            self.assertFalse(output.fresh_target)
            self.assertEqual(output.reason,'INVALID_TIMESTAMP')

    def test_backward_source_does_not_resume_motion(self):
        reframer=DigitalReframer()
        update(reframer,1,.4)
        observed=replace(recommendation(1.01,.8),source_timestamp_ms=999)
        self.assertEqual(reframer.update(observed,source_size=(1920,1080),now=1.01).reason,'INVALID_TIMESTAMP')

    def test_stale_source_still_advances_replay_fence(self):
        reframer=DigitalReframer()
        update(reframer,1,.5)
        stale=replace(recommendation(1,.5),source_timestamp_ms=1100)
        reframer.update(stale,source_size=(1920,1080),now=1.3)
        backwards=replace(recommendation(1.35,.5),source_timestamp_ms=1050)
        self.assertEqual(reframer.update(backwards,source_size=(1920,1080),now=1.35).reason,'INVALID_TIMESTAMP')

    def test_boundary_constraints_and_crop_validity(self):
        for x,y,expected in ((.9,0,'RIGHT'),(-.9,0,'LEFT'),(0,.9,'BOTTOM'),(0,-.9,'TOP')):
            reframer=DigitalReframer()
            for i in range(100):output=update(reframer,1+i*.033,x,y)
            self.assertIn(expected,output.boundaries)
            r=output.rectangle
            self.assertTrue(0<=r.left<r.right<=1920 and 0<=r.top<r.bottom<=1080)
            self.assertFalse(output.moving)

    def test_full_frame_scale_cannot_move_and_never_exceeds_bounds(self):
        reframer=DigitalReframer(ReframeConfig(scale=1))
        for i in range(20):output=update(reframer,1+i*.03,.8,-.8)
        self.assertEqual(output.rectangle.size,(1920,1080))
        self.assertEqual(output.center,(960,540))
        self.assertFalse(output.moving)

    def test_target_coordinates_match_actual_integer_slice(self):
        reframer=DigitalReframer()
        update(reframer,1,.3)
        output=update(reframer,1.03,.3)
        self.assertAlmostEqual(output.target_in_crop[0],1248-output.rectangle.left)
        self.assertAlmostEqual(output.composition_error[0],(output.target_in_crop[0]-640)/640)

    def test_custom_fixed_composition(self):
        reframer=DigitalReframer(ReframeConfig(composition=(.25,.75),horizontal=DeadZone(.001,0),vertical=DeadZone(.001,0)))
        for i in range(160):output=update(reframer,1+i*.03)
        self.assertAlmostEqual(output.target_in_crop[0]/1280,.25,places=3)
        self.assertAlmostEqual(output.target_in_crop[1]/720,.75,places=3)

    def test_tracking_loss_holds_and_removes_current_target_coordinates(self):
        reframer=DigitalReframer()
        update(reframer,1,.5)
        before=update(reframer,1.03,.5)
        lost=reframer.update(recommendation(1.06,.5,state='LOST',visible=False),source_size=(1920,1080),now=1.06)
        self.assertEqual(lost.center,before.center)
        self.assertIsNone(lost.desired_center)
        self.assertIsNone(lost.target_in_crop)
        self.assertIsNone(lost.composition_error)
        self.assertFalse(lost.moving)
        self.assertEqual(lost.reason,'TARGET_LOST')

    def test_reacquisition_and_new_ids_resume_without_snap(self):
        for key in (1,2):
            reframer=DigitalReframer()
            update(reframer,1,.5)
            before=update(reframer,1.03,.5)
            reframer.update(recommendation(1.06,visible=False,state='LOST'),source_size=(1920,1080),now=1.06)
            resumed=update(reframer,1.09,-.5,key=key)
            self.assertEqual(resumed.center,before.center)
            self.assertEqual(resumed.primary_id,key)
            next_frame=update(reframer,1.12,-.5,key=key)
            self.assertLess(next_frame.center[0],resumed.center[0])

    def test_stale_uncertain_expired_and_tentative_targets_hold(self):
        for observed,now in ((recommendation(1,.5,uncertain=True),1),
                             (recommendation(1,.5,state='TENTATIVE'),1),
                             (recommendation(1,.5,state='EXPIRED',visible=False),1),
                             (recommendation(1,.5),1.3)):
            output=DigitalReframer().update(observed,source_size=(1920,1080),now=now)
            self.assertEqual(output.center,(960,540))
            self.assertFalse(output.fresh_target)
            self.assertFalse(output.moving)

    def test_invalid_primary_ids_or_centers_hold(self):
        for values in ({'primary_id':None},{'primary_id':True},{'primary_id':-1},
                       {'smoothed_center':None},{'smoothed_center':(math.nan,10)},
                       {'smoothed_center':(-1,540)},{'frame_size':(640,360)}):
            observed=replace(recommendation(1,.5),**values)
            output=DigitalReframer().update(observed,source_size=(1920,1080),now=1)
            self.assertFalse(output.fresh_target)
            self.assertFalse(output.moving)

    def test_future_or_missing_detection_timestamps_hold(self):
        for stamp in (None,math.nan,2,-1):
            output=DigitalReframer().update(replace(recommendation(1,.5),observation_timestamp=stamp),source_size=(1920,1080),now=1)
            self.assertFalse(output.fresh_target)

    def test_no_target_still_has_valid_held_crop(self):
        output=DigitalReframer().update(None,source_size=(1920,1080),now=1)
        self.assertEqual(output.reason,'NO_TARGET')
        self.assertEqual(output.rectangle.size,(1280,720))

    def test_stale_results_do_not_advance_actual_detection_time(self):
        reframer=DigitalReframer()
        observed=recommendation(1,.5)
        reframer.update(observed,source_size=(1920,1080),now=1)
        output=reframer.update(observed,source_size=(1920,1080),now=1.3)
        self.assertEqual(output.observation_timestamp,1)
        self.assertAlmostEqual(output.observation_age,.3)
        self.assertEqual(output.reason,'STALE_OBSERVATION')

    def test_source_resize_reinitializes_valid_crop_without_old_coordinates(self):
        reframer=DigitalReframer()
        update(reframer,1,.5)
        output=update(reframer,1.03,.5,size=(640,360))
        self.assertEqual(output.center,(320,180))
        self.assertEqual(output.crop_size,(427,240))
        self.assertFalse(output.moving)

    def test_reset_retains_clock_fences_but_resets_viewport(self):
        reframer=DigitalReframer()
        update(reframer,1,.5)
        update(reframer,1.03,.5)
        reframer.reset()
        output=update(reframer,1.06,.5)
        self.assertEqual(output.center,(960,540))
        bad=reframer.update(recommendation(.9,.5),source_size=(1920,1080),now=1.07)
        self.assertFalse(bad.fresh_target)

    def test_new_session_has_no_retained_motion(self):
        first=DigitalReframer()
        update(first,1,.5);update(first,1.03,.5)
        self.assertEqual(update(DigitalReframer(),1,.5).center,(960,540))

    def test_immutable_snapshots_and_bounded_metadata(self):
        reframer=DigitalReframer()
        output=update(reframer)
        with self.assertRaises(FrozenInstanceError):output.center=(0,0)
        for i in range(1000):update(reframer,1.01+i*.02,.3 if i%2 else .2)
        metadata=reframer.metadata()
        self.assertLess(len(metadata['reasons']),25)
        self.assertLess(len(metadata['counters']),15)
        self.assertNotIn('center',metadata)

    def test_disabled_profile_does_not_read_timing_clock(self):
        observed=recommendation()
        with patch('face_tracking.digital_reframing.time.perf_counter',side_effect=AssertionError('timer called')):
            DigitalReframer().update(observed,source_size=(1920,1080),now=1,profile=Profile(enabled=False))

    def test_profile_records_bounded_update_and_age_metrics(self):
        reframer,profile=DigitalReframer(),Profile(capacity=2)
        for i in range(10):
            reframer.update(recommendation(1+i*.03,.3),source_size=(1920,1080),now=1.01+i*.03,profile=profile)
        summary=profile.summary()
        self.assertEqual(summary['reframe_update']['count'],10)
        self.assertEqual(summary['reframe_update']['percentile_samples'],2)
        self.assertAlmostEqual(summary['reframe_observation_age']['mean_ms'],10)

    def test_invalid_configuration_rejected(self):
        for kw in ({'scale':0},{'scale':1.1},{'follow_tau':math.nan},{'follow_tau':-1},
                   {'max_speed':0},{'max_speed':math.inf},{'horizontal':None},{'composition':(1.1,0)}):
            with self.assertRaises(ValueError):ReframeConfig(**kw)

    def test_tracker_lock_does_not_switch_to_new_high_confidence_person(self):
        tracker=FaceTracker(TrackerConfig(confirmation_hits=1,confirmation_seconds=0))
        calculator,reframer=FaceCentering(),DigitalReframer()
        for i in range(30):
            t=i*.033
            faces=(face(.7,confidence=.7),) if i<3 else (face(.1,w=.3,confidence=.99),face(.7,confidence=.7))
            tracked=tracker.update(frame(t,*faces))
            output=reframer.update(calculator.update(tracked,now=t),source_size=(1920,1080),now=t)
            self.assertEqual(output.primary_id,1)
        self.assertGreater(output.center[0],960)


class CropRenderingTest(unittest.TestCase):
    def test_slice_is_correct_read_only_and_shares_source_memory(self):
        source=np.arange(108*192*3,dtype=np.uint8).reshape(108,192,3)
        viewport=update(DigitalReframer(),size=(192,108))
        crop=extract_crop(source,viewport)
        self.assertEqual(crop.shape,(72,128,3))
        self.assertTrue(np.shares_memory(source,crop))
        self.assertFalse(crop.flags.writeable)
        self.assertTrue(source.flags.writeable)
        self.assertTrue(np.array_equal(crop,source[18:90,32:160]))

    def test_renderer_cannot_mutate_source_and_reuses_display_buffer(self):
        source=np.full((108,192,3),90,np.uint8)
        before=source.copy()
        viewport=update(DigitalReframer(),size=(192,108))
        renderer=ReframeRenderer(bounds=(96,54))
        first=renderer.render(source,viewport,now=1)
        second=renderer.render(source,viewport,now=1.1)
        self.assertIs(first,second)
        self.assertEqual(first.shape,(54,96,3))
        self.assertFalse(np.shares_memory(first,source))
        self.assertTrue(np.array_equal(source,before))
        renderer.close();self.assertIsNone(renderer.buffer)

    def test_native_crop_is_copied_before_annotations_without_upscale(self):
        source=np.zeros((30,60,3),np.uint8)
        viewport=update(DigitalReframer(),size=(60,30))
        display=ReframeRenderer().render(source,viewport,now=1)
        self.assertEqual(display.shape,(20,40,3))
        self.assertEqual(int(source.sum()),0)
        self.assertGreater(int(display.sum()),0)

    def test_new_source_pixels_remain_live_while_viewport_holds(self):
        reframer=DigitalReframer()
        initial=update(reframer,1,size=(192,108))
        held=reframer.update(recommendation(1.03,visible=False,state='LOST',size=(192,108)),source_size=(192,108),now=1.03)
        self.assertEqual(initial.rectangle,held.rectangle)
        renderer=ReframeRenderer()
        for value in (20,100,200):
            display=renderer.render(np.full((108,192,3),value,np.uint8),held,now=1.03)
            self.assertEqual(int(display[-1,-1,0]),value)

    def test_mismatched_or_invalid_source_rejected(self):
        viewport=update(DigitalReframer(),size=(192,108))
        for source in (np.zeros((12,20,3),np.uint8),np.zeros((108,192),np.uint8),np.zeros((108,192,3),np.float32)):
            with self.assertRaises(ValueError):extract_crop(source,viewport)

    def test_rendering_profile_separates_slicing_from_display_preparation(self):
        profile=Profile()
        viewport=update(DigitalReframer(),size=(192,108))
        ReframeRenderer().render(np.zeros((108,192,3),np.uint8),viewport,now=1,profile=profile)
        self.assertEqual(set(profile.summary()),{'reframe_crop_extraction','reframe_rendering'})

    def test_late_render_labels_stale_observation_without_freezing_source(self):
        viewport=update(DigitalReframer(),size=(192,108))
        with patch('cv2.putText') as text:
            ReframeRenderer().render(np.full((108,192,3),80,np.uint8),viewport,now=1.3)
        self.assertIn('STALE_OBSERVATION',text.call_args.args[1])
