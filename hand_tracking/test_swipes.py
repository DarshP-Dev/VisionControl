from contextlib import redirect_stderr
from copy import deepcopy
import io
import json
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

import cv2
import numpy as np

from gestures.events import SWIPE_RIGHT
from gestures.pinch import PinchTracker
from gestures.state_machine import GestureStateManager
from gestures.swipe import SwipeHistory, SwipeSettings
from gestures.tests.test_swipe import sample_hand
from gestures.tests.static_fixtures import SIZE, as_result
from . import gesture_preview, hand_tracker as tracker
from .performance import Profile
from .tracking_utils import PreviewRenderer, make_preview


FLAGS=["--gestures","--pinch","--gesture-states","--swipes"]


def sequence():
    return [as_result(sample_hand(x).observation) for x in ([0]*6+[.4,.8,1.2,1.6,2.,2.,2.])]


class SwipeApplicationTest(unittest.TestCase):
    def test_cli_dependencies_defaults_ranges_and_no_implicit_channels(self):
        args=tracker.parse_args([])
        self.assertFalse(args.swipes)
        self.assertFalse(args.swipe_debug)
        self.assertEqual(tracker.swipe_settings(args),SwipeSettings())
        self.assertEqual((args.width,args.height,args.backend,args.gui_mode),(1920,1080,"msmf","auto"))
        self.assertTrue(tracker.parse_args(FLAGS+["--swipe-debug"]).swipes)
        for flags in (["--swipes"], ["--swipe-debug"], ["--gestures","--gesture-states","--swipes"],
                      FLAGS+["--no-gestures"], FLAGS+["--swipe-distance","0"],
                      FLAGS+["--swipe-velocity","nan"], FLAGS+["--swipe-dominance",".5"],
                      FLAGS+["--swipe-consistency","1.1"], FLAGS+["--swipe-min-ms","20"],
                      FLAGS+["--swipe-max-ms","100"], FLAGS+["--swipe-cooldown-ms","-1"],
                      FLAGS+["--swipe-reset-ms","1600"], FLAGS+["--swipe-feedback-ms","1001"],
                      FLAGS+["--swipe-max-scale-change",".8"], FLAGS+["--swipe-pose","any"]):
            with self.subTest(flags=flags), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                tracker.parse_args(flags)

    def test_disabled_swipes_preserve_existing_states_and_skip_motion_work(self):
        cap,detector=MagicMock(),MagicMock()
        cap.read.return_value=True,np.zeros((1080,1920,3),np.uint8)
        detector.detect_for_video.return_value=as_result(sample_hand().observation)
        mp=SimpleNamespace(Image=lambda **kw:kw["data"],ImageFormat=SimpleNamespace(SRGB=1))
        report={}
        with patch.object(SwipeHistory,"observe") as motion,patch.object(cv2,"imshow"), \
                patch.object(cv2,"waitKey",return_value=ord("q")),self.assertLogs(tracker.LOGGER):
            tracker.process_frames(cap,detector,mp,tracker.parse_args(["--gestures","--gesture-states","--gui-mode","waitkey"]),report)
        motion.assert_not_called()
        self.assertFalse(report["swipes"]["enabled"])
        self.assertNotIn("swipe_processing",report["timings"])

    def test_live_swipe_reuses_geometry_inference_and_native_q_h(self):
        now=0.
        raw=sequence()
        before=deepcopy(raw)
        cap,detector=MagicMock(),MagicMock()
        camera=np.full((1080,1920,3),120,np.uint8)
        def read():
            nonlocal now
            now+=.05
            return True,camera
        cap.read.side_effect=read
        detector.detect_for_video.side_effect=raw
        mp=SimpleNamespace(Image=lambda **kw:kw["data"],ImageFormat=SimpleNamespace(SRGB=1))
        report={}
        with patch.object(tracker.time,"perf_counter",side_effect=lambda:now), \
                patch.object(cv2,"currentUIFramework",return_value="WIN32",create=True), \
                patch.object(cv2,"pollKey",side_effect=[ord("h")]+[-1]*9+[ord("q")],create=True), \
                patch.object(cv2,"waitKey") as wait,patch.object(cv2,"imshow"), \
                patch.object(cv2,"getWindowProperty",return_value=1), \
                patch.object(gesture_preview,"extract_features",wraps=gesture_preview.extract_features) as extract, \
                patch.object(tracker,"make_preview",wraps=make_preview) as preview,self.assertLogs(tracker.LOGGER):
            tracker.process_frames(cap,detector,mp,tracker.parse_args(FLAGS+["--no-smoothing"]),report)
        self.assertEqual(raw,before)
        self.assertEqual(detector.detect_for_video.call_count,11)
        self.assertEqual(extract.call_count,11)
        self.assertEqual(report["swipes"]["confirmation_counts"],{SWIPE_RIGHT:1})
        self.assertEqual(report["gesture_states"]["event_counts"]["GESTURE_STARTED:SWIPE_RIGHT"],1)
        self.assertEqual(report["gesture_states"]["event_counts"]["GESTURE_ENDED:SWIPE_RIGHT"],1)
        self.assertEqual(report["timings"]["swipe_processing"]["count"],11)
        self.assertEqual(report["timings_by_detected_hands"]["1"]["swipe_processing"]["count"],11)
        self.assertFalse(preview.call_args_list[0].args[3])
        self.assertTrue(preview.call_args_list[1].args[3])
        self.assertEqual(report["gui"]["effective"],"pollkey")
        wait.assert_not_called()
        json.dumps(report,allow_nan=False)
        self.assertTrue(np.all(camera==120))

    def test_default_ema_coordinates_are_the_swipe_input(self):
        from .smoothing import LandmarkSmoother
        first=as_result(sample_hand().observation)
        shifted=as_result(sample_hand(.2).observation)
        smoother=LandmarkSmoother()
        smoother.apply(first,0,(1080,1920))
        shown=smoother.apply(shifted,50,(1080,1920))
        cached=gesture_preview.prepare_features(shown,50,SIZE)
        self.assertEqual(cached[0].observation[0].x,shown.hand_landmarks[0][0].x)
        self.assertNotEqual(shown.hand_landmarks[0][0].x,shifted.hand_landmarks[0][0].x)
        history=SwipeHistory(SwipeSettings(reset_ms=0))
        history.observe(cached[0],50,True)
        self.assertEqual(history.samples[0].x,
                         sum(shown.hand_landmarks[0][i].x for i in (0,5,9,13,17))/5)

    def test_headless_benchmark_excludes_warmup_and_needs_no_gui(self):
        now=0.
        raw=sequence()
        cap,detector=MagicMock(),MagicMock()
        camera=np.zeros((1080,1920,3),np.uint8)
        calls=0
        def read():
            nonlocal now
            now+=.05
            return True,camera
        def detect(*_):
            nonlocal calls
            result=raw[min(calls,len(raw)-1)]
            calls+=1
            return result
        cap.read.side_effect=read
        detector.detect_for_video.side_effect=detect
        mp=SimpleNamespace(Image=lambda **kw:kw["data"],ImageFormat=SimpleNamespace(SRGB=1))
        report={}
        with patch.object(tracker.time,"perf_counter",side_effect=lambda:now), \
                patch.object(cv2,"imshow") as display,patch.object(cv2,"pollKey") as keys, \
                self.assertLogs(tracker.LOGGER):
            tracker.process_frames(cap,detector,mp,tracker.parse_args(FLAGS+[
                "--benchmark","--headless","--no-smoothing","--warmup",".1","--duration",".6"]),report)
        display.assert_not_called()
        keys.assert_not_called()
        self.assertEqual(report["status"],"completed")
        self.assertLess(report["frames"],calls)
        self.assertEqual(report["timings"]["swipe_processing"]["count"],report["frames"])
        self.assertEqual(report["swipes"]["confirmation_counts"],{SWIPE_RIGHT:1})

    def test_raw_overlay_stays_distinct_and_optional_trail_clears(self):
        manager=GestureStateManager(swipe_settings=SwipeSettings(),swipe_diagnostics=True)
        pinch=PinchTracker()
        renderer=PreviewRenderer()
        image=np.full((1080,1920,3),100,np.uint8)
        for stamp,dx in [(s,0) for s in range(0,251,50)]+[(300,.4),(350,.8),(400,1.2),(450,1.6)]:
            raw=as_result(sample_hand(dx).observation)
            cached=[]
            static=gesture_preview.classify_result(raw,stamp,SIZE,Profile(),features_out=cached)
            pinches=pinch.update(tuple(cached),stamp)
            result=manager.update(tuple(cached),stamp,static,pinches)
            with patch.object(cv2,"putText",wraps=cv2.putText) as text:
                preview=make_preview(image,raw,36,False,renderer=renderer,gesture_results=static,pinch_results=pinches,
                                     gesture_states=result.hands,swipe_results=result.motion,swipe_config=SwipeSettings())
            labels=[call.args[1] for call in text.call_args_list]
            self.assertTrue(any("Left - OPEN_PALM" in label for label in labels))
            self.assertTrue(any("dx=" in label for label in labels))
        self.assertTrue(any("Motion: SWIPE_RIGHT" in label and "accepted" in label for label in labels))
        self.assertTrue(any("cons=" in label and "dom=" in label for label in labels))
        fresh=make_preview(image,as_result(),36,False,renderer=renderer,swipe_results=())
        self.assertIs(preview,fresh)
        self.assertTrue(np.all(fresh[30:]==100))
        self.assertTrue(np.all(image==100))

    def test_no_debug_numeric_rows_when_disabled(self):
        from gestures.swipe import SwipeObservation
        image=np.zeros((1080,1920,3),np.uint8)
        with patch.object(cv2,"putText",wraps=cv2.putText) as text:
            make_preview(image,as_result(sample_hand().observation),36,False,
                         swipe_results=(SwipeObservation(0,reason="hold_eligible_pose_still"),))
        labels=[call.args[1] for call in text.call_args_list]
        self.assertTrue(any("Motion:" in label for label in labels))
        self.assertFalse(any("dx=" in label for label in labels))

    def test_two_hand_motion_annotations_fit_separate_screen_columns(self):
        from gestures.swipe import SwipeObservation
        raw=as_result(sample_hand(offset=-.2).observation,sample_hand(side="Right",offset=.2).observation)
        image=np.zeros((1080,1920,3),np.uint8)
        with patch.object(cv2,"rectangle",wraps=cv2.rectangle) as rectangles:
            preview=make_preview(image,raw,36,False,swipe_results=(SwipeObservation(0),SwipeObservation(0)),
                                 swipe_config=SwipeSettings())
        # Main hand label plus three motion rows for each current detection.
        self.assertEqual(len(rectangles.call_args_list),8)
        for rectangle in rectangles.call_args_list[:4]:
            self.assertLess(rectangle.args[2][0],preview.shape[1]//2)
        for rectangle in rectangles.call_args_list[4:]:
            self.assertGreaterEqual(rectangle.args[1][0],preview.shape[1]//2)

    def test_event_debug_reuses_existing_log_and_safe_shutdown_no_extra_confirmation(self):
        manager=GestureStateManager(swipe_settings=SwipeSettings())
        pinch=PinchTracker()
        events=[]
        for stamp,dx in [(s,0) for s in range(0,251,50)]+[(300,.4),(350,.8),(400,1.2),(450,1.6)]:
            cached=[]
            static=gesture_preview.classify_result(as_result(sample_hand(dx).observation),stamp,SIZE,Profile(),features_out=cached)
            result=manager.update(tuple(cached),stamp,static,pinch.update(tuple(cached),stamp))
            events.extend(result.events)
        with self.assertLogs(tracker.LOGGER) as logs:
            tracker.log_state_events(events)
            tracker.log_state_events(manager.reset())
        self.assertEqual(sum("SWIPE_RIGHT | GESTURE_STARTED" in line for line in logs.output),1)
        self.assertEqual(sum("SWIPE_RIGHT | GESTURE_ENDED" in line for line in logs.output),1)
        self.assertFalse(any("array(" in line or "data:image" in line for line in logs.output))


if __name__=="__main__":
    unittest.main()
