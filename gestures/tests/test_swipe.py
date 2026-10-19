from dataclasses import replace
import unittest

from gestures.arbitration import swipe_eligible
from gestures.events import EventType as E, GestureState as S, SWIPE_LEFT, SWIPE_RIGHT, SWIPES
from gestures.features import extract_features
from gestures.geometry import palm_scale
from gestures.models import Finger, HandednessPrediction, HandObservation, ImageSize, Landmark
from gestures.motion import MotionSample, palm_sample, trajectory_metrics
from gestures.pinch import PinchTracker
from gestures.state_machine import GestureStateManager, StateSettings
from gestures.static_gestures import Gesture as G, classify_hand
from gestures.swipe import MAX_SAMPLES, SwipeHistory, SwipeSettings
from .static_fixtures import SIZE, pose_hand


def sample_hand(dx=0., dy=0., *, side="Left", scale=.04, image_size=SIZE, rotation=0,
                pose="open", offset=0.):
    curled = () if pose == "open" else ((Finger.MIDDLE, Finger.RING, Finger.PINKY) if pose == "point"
                                       else (Finger.INDEX, Finger.MIDDLE, Finger.RING, Finger.PINKY))
    original = pose_hand(side=side, scale=scale, image_size=image_size, rotation=rotation, curled=curled)
    unit = palm_scale(original, image_size=image_size)
    points = tuple(replace(p, x=p.x+dx*unit+offset, y=p.y+dy*unit*image_size.width/image_size.height)
                   for p in original.landmarks)
    return extract_features(HandObservation(points, original.handedness), image_size=image_size)


class Run:
    def __init__(self, settings=None):
        self.manager = GestureStateManager(swipe_settings=settings or SwipeSettings())
        self.pinch = PinchTracker()
        self.frames = []

    def update(self, stamp, items):
        static = tuple(classify_hand(item, stamp) for item in items)
        pinches = self.pinch.update(items, stamp)
        result = self.manager.update(items, stamp, static, pinches)
        self.frames.append(result)
        return result

    def single(self, stamp, dx=0, dy=0, **kwargs):
        return self.update(stamp, (sample_hand(dx, dy, **kwargs),))

    def arm(self, **kwargs):
        for stamp in range(0, 251, 50):
            self.single(stamp, **kwargs)

    def swipe_events(self):
        return [e for frame in self.frames for e in frame.events if e.gesture in SWIPES]


class MotionGeometryTest(unittest.TestCase):
    def test_anchor_ignores_finger_pose_changes(self):
        anchors = [palm_sample(sample_hand(pose=pose), 0) for pose in ("open", "point", "fist")]
        self.assertEqual(anchors[0], anchors[1])
        self.assertEqual(anchors[0], anchors[2])

    def test_exact_displacements_duration_velocity_and_travel(self):
        items = tuple(palm_sample(sample_hand(dx, dy), stamp) for stamp, dx, dy in
                      ((0, 0, 0), (100, .8, .1), (200, 1.6, .2)))
        metrics = trajectory_metrics(items)
        self.assertAlmostEqual(metrics.dx, 1.6)
        self.assertAlmostEqual(metrics.dy, .2)
        self.assertEqual(metrics.duration_ms, 200)
        self.assertAlmostEqual(metrics.velocity_x, 8.)
        self.assertAlmostEqual(metrics.recent_velocity_x, 8.)
        self.assertAlmostEqual(metrics.travel, (1.6**2+.2**2)**.5)
        self.assertAlmostEqual(metrics.consistency, 1.)
        self.assertAlmostEqual(metrics.dominance, 8.)

    def test_resolution_scale_side_and_rotation_independence(self):
        for size in (SIZE, ImageSize(640,480), ImageSize(600,1000)):
            for scale in (.02, .04, .08):
                for side in ("Left", "Right"):
                    for rotation in (0, 45, 90):
                        points = tuple(palm_sample(sample_hand(x, .1*x, side=side, scale=scale,
                                                                 image_size=size, rotation=rotation), stamp)
                                       for stamp, x in ((0,0), (200,1.6)))
                        metrics = trajectory_metrics(points)
                        self.assertAlmostEqual(metrics.dx, 1.6)
                        self.assertAlmostEqual(metrics.dy, .16)

    def test_direction_consistency_and_vertical_path_do_not_cancel_zigzags(self):
        points = tuple(MotionSample(i*50,x,y,1.) for i,(x,y) in
                       enumerate(((0,0), (1,.5), (.2,-.5), (1.6,0))))
        metrics = trajectory_metrics(points)
        self.assertAlmostEqual(metrics.consistency, 1.6/3.2)
        self.assertAlmostEqual(metrics.dominance, .8)

    def test_invalid_geometry_and_timestamps(self):
        base = sample_hand()
        for bad in (None, replace(base,palm_scale=0), replace(base,palm_scale=float("nan")),
                    replace(base,image_size=None), replace(base,observation=None)):
            self.assertIsNone(palm_sample(bad,0))
        for stamp in (-1, None, True, 1.2):
            self.assertIsNone(palm_sample(base, stamp))
        for points in ((), (MotionSample(0,0,0,1),), (MotionSample(0,0,0,1),)*2,
                       (MotionSample(1,0,0,1), MotionSample(0,1,0,1)),
                       (MotionSample(0,0,0,0), MotionSample(1,1,0,1)),
                       (MotionSample(0,0,0,1), MotionSample(1,float("inf"),0,1))):
            with self.assertRaises(ValueError):
                trajectory_metrics(points)

    def test_scale_change_is_measured_without_position_division_artifacts(self):
        first = MotionSample(0,.5,.3,.1)
        last = MotionSample(200,.5,.3,.14)
        metrics = trajectory_metrics((first,last))
        self.assertEqual(metrics.dx,0)
        self.assertAlmostEqual(metrics.scale_change,.4)


class SwipeTrajectoryTest(unittest.TestCase):
    def test_clear_left_and_right_minor_vertical_deviation(self):
        for sign, direction in ((-1,SWIPE_LEFT), (1,SWIPE_RIGHT)):
            for side in ("Left", "Right"):
                run=Run()
                run.arm(side=side)
                for i in range(1,5):
                    run.single(250+i*50, sign*i*.4, i*.025, side=side)
                events=run.swipe_events()
                self.assertEqual([(e.gesture,e.event_type) for e in events],
                                 [(direction,E.GESTURE_STARTED),(direction,E.GESTURE_ENDED)])
                self.assertEqual(events[0].timestamp_ms, events[1].timestamp_ms)
                self.assertEqual(events[0].metadata.direction,direction)
                self.assertGreaterEqual(abs(events[0].metadata.motion.dx),1.5)

    def test_stationary_hand_and_slow_reposition_do_not_swipe(self):
        for movement in (0, .03):
            run=Run()
            run.arm()
            for i in range(1,50):
                run.single(250+i*50,i*movement)
            self.assertEqual(run.swipe_events(),[])

    def test_short_or_incomplete_movements_do_not_swipe(self):
        run=Run()
        run.arm()
        for stamp,x in ((280,.1),(310,.3),(340,.6),(400,.6),(600,.6),(850,.6),(900,.6)):
            run.single(stamp,x)
        self.assertEqual(run.swipe_events(),[])
        self.assertEqual(run.frames[-1].motion[0].reason,"duration_exceeded_change_pose")
        self.assertEqual(run.single(950,.6).motion[0].reason,"change_pose_to_reset")

    def test_vertical_diagonal_and_zigzag_rejected(self):
        paths = (((0,i*.4) for i in range(1,6)),
                 ((i*.4,i*.3) for i in range(1,6)),
                 iter(((.6,0),(-.4,0),(.7,0),(-.3,0),(1.6,0))))
        for path in paths:
            run=Run()
            run.arm()
            for i,(x,y) in enumerate(path,1):
                run.single(250+i*50,x,y)
            self.assertEqual(run.swipe_events(),[])

    def test_extremely_short_burst_cannot_confirm_later_while_stationary(self):
        run=Run()
        run.arm()
        for stamp in (290,330,370,410,450):
            run.single(stamp,1.6)
        self.assertEqual(run.swipe_events(),[])

    def test_duration_expiry_cannot_reuse_a_fast_tail(self):
        run=Run()
        run.arm()
        for i in range(1,15):
            run.single(250+i*50,i*.1)
        for i in range(15,20):
            run.single(250+i*50,1.4+(i-14)*.4)
        self.assertEqual(run.swipe_events(),[])

    def test_scale_change_and_capacity_reject_without_unbounded_history(self):
        history=SwipeHistory(SwipeSettings(reset_ms=0),diagnostics=True)
        history.observe(sample_hand(),0,True)
        result=history.observe(sample_hand(scale=.06),50,True)
        self.assertIn("scale_changed",result.reason)
        self.assertFalse(result.confirmed)
        for i in range(1,2000):
            history.observe(sample_hand(),50+i,True)
            self.assertLessEqual(len(history.samples),MAX_SAMPLES)
            self.assertLessEqual(len(history.rest),MAX_SAMPLES)

    def test_invalid_time_disappearance_never_confirms(self):
        for stamp in (None,250,200,-1,True):
            history=SwipeHistory(SwipeSettings(reset_ms=0))
            history.observe(sample_hand(),250,True)
            result=history.observe(sample_hand(1.6),stamp,True)
            self.assertFalse(result.confirmed)
        run=Run()
        run.arm()
        run.single(300,.8)
        lost=run.update(350,())
        self.assertFalse(any(e.gesture in SWIPES for e in lost.events))

    def test_settings_ranges_types_and_duration_order(self):
        for kwargs in ({"min_distance":0}, {"min_velocity":float("nan")}, {"dominance":.5},
                       {"consistency":1.1}, {"min_ms":True}, {"max_ms":100}, {"min_ms":10},
                       {"cooldown_ms":-1}, {"feedback_ms":1001}, {"reset_ms":1.5},
                       {"max_scale_change":.8}, {"pose":"any"}):
            with self.subTest(kwargs=kwargs),self.assertRaises(ValueError):
                SwipeSettings(**kwargs)

    def test_variable_and_low_fps_use_elapsed_time(self):
        for path in (((310,.35),(390,.8),(440,1.25),(500,1.6)),
                     ((350,.55),(450,1.1),(550,1.65))):
            run=Run()
            run.arm()
            for stamp,x in path:
                run.single(stamp,x)
            self.assertEqual(len(run.swipe_events()),2)
            self.assertEqual(run.swipe_events()[0].timestamp_ms,path[-1][0])

    def test_cooldown_deadline_then_new_stationary_hold_is_required(self):
        history=SwipeHistory(SwipeSettings())
        for stamp in range(0,251,50):
            history.observe(sample_hand(),stamp,True)
        for i in range(1,5):
            result=history.observe(sample_hand(i*.4),250+i*50,True)
        self.assertTrue(result.confirmed)
        history.observe(sample_hand(pose="fist"),500,False,1250)
        for stamp in range(550,1250,50):
            history.observe(sample_hand(),stamp,True,1250)
        self.assertEqual(history.observe(sample_hand(),1249,True,1250).state,S.COOLDOWN)
        self.assertEqual(history.observe(sample_hand(),1250,True,1250).reason,"hold_eligible_pose_still")
        for stamp in range(1300,1501,50):
            result=history.observe(sample_hand(),stamp,True,1250)
        self.assertEqual(result.reason,"ready")

    def test_zero_feedback_hides_name_on_next_observation(self):
        history=SwipeHistory(SwipeSettings(reset_ms=0,feedback_ms=0))
        history.observe(sample_hand(),0,True)
        for i in range(1,5):
            result=history.observe(sample_hand(i*.4),i*50,True)
        self.assertTrue(result.confirmed)
        history.outcome(result,True,"confirmed")
        self.assertIsNone(history.observe(sample_hand(1.6),250,True,1000).gesture)


class SwipeEventIntegrationTest(unittest.TestCase):
    def test_one_swipe_then_continuation_return_and_feedback_expiry(self):
        run=Run()
        run.arm()
        for i,x in enumerate((.4,.8,1.2,1.6,2.,2.4,2.,1.6,1.2,.8,.4,0,-.4,-.8,-1.2,-1.6),1):
            frame=run.single(250+i*50,x)
        self.assertEqual(len(run.swipe_events()),2)
        self.assertIsNone(frame.motion[0].gesture)
        self.assertFalse(frame.motion[0].trajectory)
        self.assertIn(frame.motion[0].reason,("change_pose_to_reset","cooldown"))

    def test_neutral_pose_cooldown_and_settle_allow_new_deliberate_swipe(self):
        run=Run()
        run.arm()
        for i in range(1,5):
            run.single(250+i*50,i*.4)
        run.single(500,1.6,pose="fist")
        # Reposition while ineligible; open and wait for cooldown + fresh stationary hold.
        run.single(550,.8,pose="fist")
        run.single(600,0,pose="fist")
        for stamp in range(650,1551,50):
            run.single(stamp,0)
        for i in range(1,5):
            run.single(1550+i*50,-i*.4)
        starts=[e for e in run.swipe_events() if e.event_type==E.GESTURE_STARTED]
        self.assertEqual([e.gesture for e in starts],[SWIPE_RIGHT,SWIPE_LEFT])

    def test_static_open_palm_preempted_before_atomic_swipe_events(self):
        run=Run()
        run.arm()
        for i in range(1,5):
            frame=run.single(250+i*50,i*.4)
        self.assertEqual([(e.gesture,e.event_type) for e in frame.events],
                         [(G.OPEN_PALM,E.GESTURE_CANCELED),(SWIPE_RIGHT,E.GESTURE_STARTED),(SWIPE_RIGHT,E.GESTURE_ENDED)])
        self.assertIsNone(frame.hands[0].confirmed)
        self.assertTrue(frame.motion[0].admitted)

    def test_pointing_fist_unknown_and_active_pinch_never_eligible(self):
        for pose in ("point","fist"):
            run=Run()
            for i in range(20):
                run.single(i*50,i*.3,pose=pose)
            self.assertEqual(run.swipe_events(),[])
        feature=sample_hand()
        raw=classify_hand(feature,0)
        pinch=PinchTracker().update((feature,),0)[0]
        from gestures.pinch import PinchStatus
        self.assertFalse(swipe_eligible(replace(raw,gesture=G.UNKNOWN,matched_rules=()),pinch,"open-palm"))
        for status in (PinchStatus.STARTED,PinchStatus.HELD,PinchStatus.UNAVAILABLE):
            self.assertFalse(swipe_eligible(raw,replace(pinch,status=status),"open-palm"))

    def test_configured_fist_policy_is_explicit(self):
        feature=sample_hand(pose="fist")
        raw=classify_hand(feature,0)
        pinch=PinchTracker().update((feature,),0)[0]
        self.assertEqual(raw.gesture,G.FIST)
        self.assertTrue(swipe_eligible(raw,pinch,"open-palm-or-fist"))

    def test_two_hands_independent_and_detection_order_changes(self):
        run=Run()
        for stamp in range(0,251,50):
            run.update(stamp,(sample_hand(offset=-.2),sample_hand(side="Right",offset=.2)))
        for i in range(1,5):
            hands=(sample_hand(i*.4,offset=-.2),sample_hand(side="Right",offset=.2))
            if i%2:
                hands=hands[::-1]
            frame=run.update(250+i*50,hands)
        starts=[e for e in run.swipe_events() if e.event_type==E.GESTURE_STARTED]
        self.assertEqual(len(starts),1)
        self.assertEqual(starts[0].side.value,"Left")

    def test_two_same_direction_swipes_can_complete_independently(self):
        run=Run()
        for stamp in range(0,251,50):
            run.update(stamp,(sample_hand(offset=-.2),sample_hand(side="Right",offset=.2)))
        for i in range(1,5):
            run.update(250+i*50,(sample_hand(i*.4,offset=-.2),sample_hand(i*.4,side="Right",offset=.2)))
        starts=[e for e in run.swipe_events() if e.event_type==E.GESTURE_STARTED]
        self.assertEqual([e.side.value for e in starts],["Left","Right"])
        self.assertTrue(all(e.gesture==SWIPE_RIGHT for e in starts))

    def test_staggered_opposite_swipe_is_suppressed_in_recent_conflict_window(self):
        run=Run()
        for stamp in range(0,251,50):
            run.update(stamp,(sample_hand(offset=-.2),sample_hand(side="Right",offset=.2)))
        for i in range(1,5):
            run.update(250+i*50,(sample_hand(-i*.4,offset=-.2),sample_hand(side="Right",offset=.2)))
        for i in range(1,4):
            frame=run.update(450+i*50,(sample_hand(-1.6,offset=-.2),sample_hand(i*.6,side="Right",offset=.2)))
        starts=[e for e in run.swipe_events() if e.event_type==E.GESTURE_STARTED]
        self.assertEqual(len(starts),1)
        self.assertEqual(starts[0].gesture,SWIPE_LEFT)
        self.assertEqual(frame.motion[1].reason,"opposite_two_hand_motion")

    def test_opposite_two_hand_candidates_suppressed_with_raw_evidence_retained(self):
        run=Run()
        for stamp in range(0,251,50):
            run.update(stamp,(sample_hand(offset=-.2),sample_hand(side="Right",offset=.2)))
        for i in range(1,5):
            frame=run.update(250+i*50,(sample_hand(-i*.4,offset=-.2),
                                           sample_hand(i*.4,side="Right",offset=.2)))
        self.assertEqual(run.swipe_events(),[])
        self.assertTrue(all(item.confirmed and not item.admitted for item in frame.motion))
        self.assertTrue(all(item.reason=="opposite_two_hand_motion" for item in frame.motion))

    def test_one_hand_lost_other_history_continues(self):
        run=Run()
        for stamp in range(0,251,50):
            run.update(stamp,(sample_hand(offset=-.2),sample_hand(side="Right",offset=.2)))
        for i in range(1,5):
            items=(sample_hand(i*.4,side="Right",offset=.2),)
            run.update(250+i*50,items)
        starts=[e for e in run.swipe_events() if e.event_type==E.GESTURE_STARTED]
        self.assertEqual(len(starts),1)
        self.assertEqual(starts[0].side.value,"Right")

    def test_overlap_ambiguity_gaps_and_reacquisition_discard_old_trajectories(self):
        for failure in ("overlap","uncertain","gap","loss"):
            run=Run()
            run.arm()
            run.single(300,.8)
            if failure=="overlap":
                run.update(350,(sample_hand(.8),sample_hand(.8,side="Right")))
            elif failure=="uncertain":
                bad=sample_hand(.8)
                bad=replace(bad,observation=replace(bad.observation,handedness=(HandednessPrediction("Left",.7),)))
                run.update(350,(bad,))
            elif failure=="loss":
                run.update(350,())
            else:
                run.single(700,.8)
            stamp=750 if failure=="gap" else 400
            frame=run.single(stamp,1.6)
            self.assertEqual(run.swipe_events(),[])
            self.assertFalse(any(e.gesture in SWIPES for e in frame.events))

    def test_same_sequences_produce_identical_motion_events_and_shutdown_has_no_extra_swipe(self):
        def sequence():
            run=Run()
            run.arm()
            for i in range(1,5):
                run.single(250+i*50,i*.4)
            events=run.swipe_events()
            cleanup=run.manager.reset()
            self.assertFalse(any(e.gesture in SWIPES for e in cleanup))
            return events
        self.assertEqual(sequence(),sequence())


if __name__=="__main__":
    unittest.main()
