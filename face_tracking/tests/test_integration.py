from contextlib import redirect_stderr
import io
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace as NS
import unittest
from unittest.mock import MagicMock, patch

import cv2
import numpy as np

from camera.latest_capture import LatestCapture
from camera.test_latest_capture import ScriptedCamera
from controls.backends import SimulationBackend
from controls.controller import DesktopController
from gestures.tests.static_fixtures import as_result
from hand_tracking import hand_tracker as app
from hand_tracking.preview_window import PreviewWindow
from face_tracking.face_geometry import adapt_result
from face_tracking.face_detector import FaceDetectionError
from .helpers import MP, detection, result


class IntegrationTest(unittest.TestCase):
    def test_cli_modes_and_existing_defaults(self):
        self.assertFalse(app.parse_args([]).face_detection)
        self.assertEqual(app.parse_args([]).capture_pipeline,'sync')
        self.assertEqual(app.parse_args([]).windows_timer_policy,'system')
        self.assertTrue(app.parse_args(['--face-only']).face_detection)
        for flags in (['--face-only','--controls'],['--face-only','--gestures'],['--face-only','--track-ids'],
                      ['--face-min-confidence','nan'],['--face-min-confidence','1.1'],['--face-inference-resolution','bad']):
            with redirect_stderr(io.StringIO()),self.assertRaises(SystemExit):app.parse_args(flags)

    def pipeline(self, face_only=False, latest=False, fail=False, minimized=False, tracking=False, background_state='minimized', centering=False):
        cap,hand,face,window=MagicMock(),MagicMock(),MagicMock(),MagicMock()
        frame=np.zeros((12,20,3),np.uint8)
        cap.read.return_value=(True,frame)
        hand.detect_for_video.return_value=as_result()
        face.last_inference_size=(20,12)
        source=camera=None
        if latest:
            camera=ScriptedCamera()
            native_read=camera.read
            def unique_read():
                item=native_read();time.sleep(.002);return item
            camera.read=unique_read
            source=LatestCapture(lambda:camera).start()
            camera.send()
            def cleanup():
                source.request_stop();camera.unblock.set();source.close(1)
            self.addCleanup(cleanup)
        def detect(_frame,stamp,_profile,**kwargs):
            if fail:raise FaceDetectionError('injected face failure')
            n=face.detect.call_count
            if camera is not None and n<4:camera.send(n+1)
            return adapt_result(result() if n==2 else result(detection(2,2,8,6)),(20,12),(20,12),stamp)
        face.detect.side_effect=detect
        window.state.side_effect=lambda:background_state if minimized and face.detect.call_count==2 else 'focused'
        window.should_render.side_effect=PreviewWindow.should_render
        args=app.parse_args((['--face-only'] if face_only else ['--face-detection'])+(['--face-tracking'] if tracking else [])+(['--face-centering'] if centering else [])+
                            ['--gui-mode','waitkey','--capture-pipeline','latest-thread' if latest else 'sync'])
        with patch.object(cv2,'waitKey',side_effect=lambda *_:ord('q') if face.detect.call_count>=4 else -1), \
                patch.object(cv2,'imshow') as display,patch('face_tracking.preview.draw_tracks' if tracking or centering else 'face_tracking.preview.draw_faces') as overlay, \
                patch.object(cv2,'VideoCapture') as opener,self.assertLogs(app.LOGGER):
            report={}
            app.process_frames(None if latest else cap,None if face_only else hand,MP,args,report,
                               preview_window=window,capture_source=source,face_detector=face)
        opener.assert_not_called()
        return report,hand,face,display,overlay,source

    def test_face_only_skips_hand_inference_and_reports_face_loss(self):
        r,hand,face,_,overlay,_=self.pipeline(face_only=True)
        hand.detect_for_video.assert_not_called()
        self.assertFalse(r['hand_tracking_enabled'])
        self.assertEqual(r['inference_resolution_frames'],{})
        self.assertEqual(r['face_detection']['observed_face_count_frames'],{'1':2,'0':1})
        self.assertIsNone(overlay.call_args_list[1].args[1].primary)

    def test_combined_uses_same_capture_and_current_rgb_hint(self):
        r,hand,face,_,_,_=self.pipeline()
        self.assertEqual(hand.detect_for_video.call_count,face.detect.call_count)
        self.assertTrue(all(call.kwargs['rgb_hint'] is not None for call in face.detect.call_args_list))
        self.assertEqual(r['face_detection']['mode'],'combined')
        self.assertEqual(r['frames'],3)

    def test_latest_worker_shared_for_face_and_hand_and_minimize_restore(self):
        r,hand,face,display,overlay,source=self.pipeline(latest=True,minimized=True)
        self.assertEqual(r['frames'],3)
        self.assertEqual(r['pacing']['preview_frames_skipped'],1)
        self.assertEqual(display.call_count,2)
        self.assertEqual(overlay.call_count,2)
        self.assertTrue(source.stop.is_set())
        self.assertEqual(source.max_occupancy,1)

    def test_face_exception_releases_virtual_drag_and_stops_capture(self):
        cap,hand,face,window=MagicMock(),MagicMock(),MagicMock(),MagicMock()
        cap.read.return_value=True,np.zeros((12,20,3),np.uint8)
        hand.detect_for_video.return_value=as_result()
        face.detect.side_effect=FaceDetectionError('native failure')
        controller=DesktopController(SimulationBackend())
        controller.armed=controller.button_down=controller.backend.button_down=True
        window.state.return_value='focused'
        args=app.parse_args(['--face-detection','--gui-mode','waitkey','--gestures','--pinch','--gesture-states','--controls'])
        with patch.object(cv2,'waitKey',return_value=-1),patch.object(controller,'update'), \
                self.assertLogs(app.LOGGER),self.assertRaises(FaceDetectionError):
            app.process_frames(cap,hand,MP,args,{},controller,preview_window=window,face_detector=face)
        self.assertFalse(controller.armed);self.assertFalse(controller.backend.button_down)

    def test_face_only_run_never_initializes_hand_model_or_controller_and_one_camera(self):
        face=MagicMock();face.mp=MP;face.metadata.return_value={'closed':True}
        cap=MagicMock();cap.isOpened.return_value=False
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as directory:
            model=Path(directory)/'fake.tflite';model.write_bytes(b'mock')
            args=app.parse_args(['--face-only','--face-model',str(model),'--model',str(Path(directory)/'missing_hand.task')])
            with patch('face_tracking.face_detector.FaceDetector',return_value=face), \
                    patch.object(app,'create_landmarker') as hand,patch.object(app.control_cli,'create_controller') as control, \
                    patch.object(cv2,'VideoCapture',return_value=cap) as camera,self.assertLogs(app.LOGGER):
                r={};self.assertEqual(app.run(args,r),1)
            hand.assert_not_called();control.assert_not_called();camera.assert_called_once()
            face.close.assert_called_once();cap.release.assert_called_once()

    def test_missing_face_model_fails_before_camera_or_input(self):
        args=app.parse_args(['--face-only','--face-model','definitely_missing_face.tflite'])
        with patch.object(cv2,'VideoCapture') as camera,patch.object(app.control_cli,'create_controller') as controller,self.assertLogs(app.LOGGER):
            self.assertEqual(app.run(args,{}),1)
        camera.assert_not_called();controller.assert_not_called()

    def test_disabled_feature_never_imports_or_runs_face_module(self):
        import builtins
        original=builtins.__import__
        def guarded(name,*a,**k):
            if name.startswith('face_tracking'):raise AssertionError('disabled feature imported')
            return original(name,*a,**k)
        cap,hand=MagicMock(),MagicMock();cap.read.return_value=True,np.zeros((12,20,3),np.uint8)
        hand.detect_for_video.return_value=as_result()
        with patch('builtins.__import__',side_effect=guarded),patch.object(cv2,'waitKey',return_value=ord('q')), \
                patch.object(cv2,'getWindowProperty',return_value=1),patch.object(cv2,'imshow'),self.assertLogs(app.LOGGER):
            r={};app.process_frames(cap,hand,MP,app.parse_args(['--gui-mode','waitkey']),r)
        self.assertFalse(r['face_detection']['enabled'])

    def test_slow_face_result_is_cleared_before_overlay(self):
        cap,hand,face,window=MagicMock(),MagicMock(),MagicMock(),MagicMock()
        cap.read.return_value=True,np.zeros((12,20,3),np.uint8)
        hand.detect_for_video.return_value=as_result();face.last_inference_size=(20,12)
        now=[1.]
        def detect(_frame,stamp,*a,**k):
            now[0]+=.3
            return adapt_result(result(detection(2,2,8,6)),(20,12),(20,12),stamp)
        face.detect.side_effect=detect
        window.state.return_value='focused';window.should_render.return_value=True
        args=app.parse_args(['--face-detection','--gui-mode','waitkey'])
        with patch.object(app.time,'perf_counter',side_effect=lambda:now[0]), \
                patch.object(cv2,'waitKey',side_effect=lambda *_:ord('q') if face.detect.call_count>=2 else -1), \
                patch.object(cv2,'imshow'),patch('face_tracking.preview.draw_faces') as overlay,self.assertLogs(app.LOGGER):
            report={};app.process_frames(cap,hand,MP,args,report,preview_window=window,face_detector=face)
        observation=overlay.call_args.args[1]
        self.assertEqual(observation.status,'expired');self.assertIsNone(observation.primary)
        self.assertEqual(report['face_detection']['observed_face_count_frames'],{'0':1})

    def test_combined_run_has_one_camera_owner_and_x_closes_both_models(self):
        camera=ScriptedCamera();camera.isOpened=lambda:True
        camera.set=lambda *_:True;camera.get=lambda *_:0.;camera.getBackendName=lambda:'MSMF'
        hand,face,window=MagicMock(),MagicMock(),MagicMock()
        face.metadata.return_value={'closed':True};window.state.return_value='closed'
        stop=LatestCapture.request_stop
        def request_stop(source):
            stop(source);camera.unblock.set()
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as directory:
            path=Path(directory)/'mock.model';path.write_bytes(b'mocked models')
            args=app.parse_args(['--face-detection','--model',str(path),'--face-model',str(path),
                                '--capture-pipeline','latest-thread','--gui-mode','waitkey'])
            with patch.object(app,'create_landmarker',return_value=(MP,hand)), \
                    patch('face_tracking.face_detector.FaceDetector',return_value=face), \
                    patch.object(cv2,'VideoCapture',return_value=camera) as opener, \
                    patch.object(cv2,'namedWindow'),patch.object(cv2,'destroyAllWindows'), \
                    patch.object(cv2,'waitKey',return_value=-1),patch.object(app,'create_preview_window',return_value=window), \
                    patch.object(LatestCapture,'request_stop',request_stop), \
                    patch.object(app.control_cli,'create_controller') as controls,self.assertLogs(app.LOGGER):
                report={};self.assertEqual(app.run(args,report),0)
        opener.assert_called_once();controls.assert_not_called()
        hand.close.assert_called_once();face.close.assert_called_once()
        hand.detect_for_video.assert_not_called();face.detect.assert_not_called()
        self.assertEqual(camera.release_count,1)
        self.assertFalse(report['capture_pipeline']['worker_alive'])
        self.assertTrue(report['capture_pipeline']['release_completed'])
        self.assertEqual(report['status'],'preview_closed')
