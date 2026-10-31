from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import time
from unittest.mock import MagicMock, patch
import unittest

import cv2
import numpy as np

from controls.backends import SimulationBackend
from controls.controller import DesktopController
from face_tracking import benchmark_centering
from face_tracking.centering import CenteringStatus, FaceCentering
from face_tracking.centering_preview import draw_centering
from face_tracking.face_geometry import adapt_result
from face_tracking.face_tracker import FaceTracker, TrackerConfig
from gestures.tests.static_fixtures import as_result
from hand_tracking import hand_tracker as app
from hand_tracking.performance import write_report
from . import test_integration as fixtures
from . import test_tracking_integration as tracking_fixtures
from .test_centering import observation
from .helpers import MP, detection, result


class CenteringIntegrationTest(unittest.TestCase):
    def fixture(self):
        instance=fixtures.IntegrationTest()
        self.addCleanup(instance.doCleanups)
        return instance

    def test_cli_implies_tracker_and_preserves_defaults(self):
        args=app.parse_args(['--face-centering','--face-centering-debug'])
        self.assertTrue(args.face_tracking)
        self.assertTrue(args.face_detection)
        self.assertEqual(args.face_centering_activation,.12)
        self.assertEqual(args.face_centering_deactivation,.07)
        self.assertEqual((args.width,args.height,args.fps,args.backend),(1920,1080,60,'msmf'))
        self.assertEqual((args.capture_pipeline,args.windows_timer_policy,args.max_hands),('sync','system',2))

    def test_cli_threshold_tuning_and_explicit_timer_policy(self):
        args=app.parse_args(['--face-only','--face-centering','--face-centering-activation','.2',
                             '--face-centering-deactivation','.1','--windows-timer-policy','honor-requests'])
        self.assertEqual((args.face_centering_activation,args.face_centering_deactivation),(.2,.1))
        self.assertEqual(args.windows_timer_policy,'honor-requests')

    def test_invalid_cli_and_face_only_controls_fail_closed(self):
        for flags in (['--face-centering-debug'], ['--face-centering-activation','nan'],
                      ['--face-centering-activation','1.1'], ['--face-centering-activation','0'],
                      ['--face-centering-deactivation','-.1'], ['--face-centering-deactivation','.12'],
                      ['--face-centering-deactivation','inf'], ['--face-centering','--face-only','--controls']):
            with redirect_stderr(io.StringIO()),self.assertRaises(SystemExit):
                app.parse_args(flags)

    def test_face_only_draws_centering_without_hand_model(self):
        with patch('face_tracking.centering_preview.draw_centering',return_value=False) as draw:
            report,hand,detector,display,_,_=self.fixture().pipeline(face_only=True,centering=True)
        hand.detect_for_video.assert_not_called()
        self.assertEqual(draw.call_count,display.call_count)
        self.assertEqual(draw.call_count,3)
        self.assertEqual(sum(report['face_centering']['states'].values()),detector.detect.call_count)
        self.assertTrue(report['face_tracking']['enabled'])
        self.assertTrue(report['face_centering']['enabled'])
        self.assertEqual(report['face_centering']['config']['horizontal']['activation'],.12)

    def test_latest_minimize_restore_keeps_calculating_and_single_camera(self):
        calls=[]
        original=FaceCentering.update
        def calculate(instance,*a,**kw):
            output=original(instance,*a,**kw)
            calls.append(output)
            return output
        with patch.object(FaceCentering,'update',calculate),patch('face_tracking.centering_preview.draw_centering',return_value=False) as draw:
            report,hand,detector,display,_,source=self.fixture().pipeline(latest=True,minimized=True,centering=True)
        self.assertEqual(len(calls),detector.detect.call_count)
        self.assertEqual(hand.detect_for_video.call_count,detector.detect.call_count)
        self.assertEqual((display.call_count,draw.call_count),(2,2))
        self.assertEqual(report['face_tracking']['ids_allocated'],1)
        self.assertEqual(report['face_centering']['counters'].get('resets',0),0)
        self.assertTrue(source.stop.is_set())

    def test_unfocused_preview_continues_calculation_and_drawing(self):
        with patch('face_tracking.centering_preview.draw_centering',return_value=False) as draw:
            report,_,detector,display,_,_=self.fixture().pipeline(minimized=True,background_state='unfocused',centering=True)
        self.assertEqual(draw.call_count,3)
        self.assertEqual(display.call_count,3)
        self.assertEqual(sum(report['face_centering']['states'].values()),detector.detect.call_count)

    def test_face_overlay_disabled_still_calculates_without_drawing(self):
        original=app.parse_args
        with patch.object(app,'parse_args',side_effect=lambda flags:original(flags+['--no-face-overlay'])), \
                patch('face_tracking.centering_preview.draw_centering') as draw:
            report,*_=self.fixture().pipeline(centering=True)
        draw.assert_not_called()
        self.assertGreater(sum(report['face_centering']['states'].values()),0)

    def test_tracking_only_does_not_import_or_construct_centering(self):
        import builtins
        original=builtins.__import__
        def guard(name,*a,**kw):
            if name.startswith('face_tracking.centering'):
                raise AssertionError('disabled centering imported')
            return original(name,*a,**kw)
        with patch('builtins.__import__',side_effect=guard):
            report,*_=self.fixture().pipeline(tracking=True)
        self.assertEqual(report['face_centering'],{'enabled':False})

    def test_headless_report_contains_centering_without_gui_or_input(self):
        cap,detector=MagicMock(),MagicMock()
        image=np.zeros((12,20,3),np.uint8)
        def read():
            time.sleep(.002)
            return True,image
        cap.read.side_effect=read
        detector.last_inference_size=(20,12)
        detector.detect.side_effect=lambda _f,stamp,*_a,**_k:adapt_result(result(detection(2,2,8,6)),(20,12),(20,12),stamp)
        args=app.parse_args(['--face-only','--face-centering','--benchmark','--headless','--warmup','.001','--duration','.02'])
        with patch.object(cv2,'imshow') as display,patch.object(cv2,'VideoCapture') as opener, \
                patch('face_tracking.face_tracker.FaceTracker',side_effect=lambda _config:FaceTracker(TrackerConfig(confirmation_hits=1,confirmation_seconds=0))), \
                patch.object(app.control_cli,'create_controller') as controls,self.assertLogs(app.LOGGER):
            report={}
            app.process_frames(cap,None,MP,args,report,face_detector=detector)
        display.assert_not_called();opener.assert_not_called();controls.assert_not_called()
        self.assertIn('face_centering',report['timings'])
        self.assertIn('face_centering',report['timings_by_preview_state']['headless'])
        self.assertGreater(report['face_centering']['states'].get('CORRECTION_NEEDED',0),0)
        self.assertEqual(cap.read.call_count,detector.detect.call_count)
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            path=Path(directory)/'report.json'
            write_report(path,report)
            saved=json.loads(path.read_text())
        self.assertTrue(saved['face_centering']['enabled'])
        self.assertNotIn('raw_center',saved['face_centering'])

    def test_centering_failure_disarms_and_releases_simulated_drag(self):
        cap,hand,detector,window=(MagicMock() for _ in range(4))
        cap.read.return_value=True,np.zeros((12,20,3),np.uint8)
        hand.detect_for_video.return_value=as_result()
        detector.detect.side_effect=lambda _f,stamp,*_a,**_k:adapt_result(result(detection(2,2,8,6)),(20,12),(20,12),stamp)
        detector.last_inference_size=(20,12)
        window.state.return_value='focused'
        controller=DesktopController(SimulationBackend())
        controller.armed=controller.button_down=controller.backend.button_down=True
        args=app.parse_args(['--face-centering','--gestures','--pinch','--gesture-states','--controls','--gui-mode','waitkey'])
        with patch.object(cv2,'waitKey',return_value=-1),patch.object(controller,'update'), \
                patch.object(FaceCentering,'update',side_effect=RuntimeError('injected centering failure')), \
                self.assertLogs(app.LOGGER),self.assertRaisesRegex(RuntimeError,'centering failure'):
            app.process_frames(cap,hand,MP,args,{},controller,preview_window=window,face_detector=detector)
        self.assertFalse(controller.armed)
        self.assertFalse(controller.backend.button_down)

    def test_x_closes_both_models_and_shared_camera(self):
        original=app.parse_args
        with patch.object(app,'parse_args',side_effect=lambda flags:original(flags+['--face-centering'])):
            self.fixture().test_combined_run_has_one_camera_owner_and_x_closes_both_models()

    def test_face_only_camera_failure_closes_model_without_hand_or_controls(self):
        original=app.parse_args
        with patch.object(app,'parse_args',side_effect=lambda flags:original(flags+['--face-centering'])):
            self.fixture().test_face_only_run_never_initializes_hand_model_or_controller_and_one_camera()

    def test_faces_never_arm_or_dispatch_when_capture_fails(self):
        original=app.parse_args
        with patch.object(app,'parse_args',side_effect=lambda flags:original(flags+['--face-centering'])):
            tracking_fixtures.TrackingIntegrationTest().test_camera_read_fault_does_not_arm_or_dispatch_from_faces()

    def test_new_sessions_do_not_retain_centering_counts_or_tracking_ids(self):
        reports=[]
        with patch('face_tracking.centering_preview.draw_centering',return_value=False):
            for _ in range(2):
                report,*_=self.fixture().pipeline(face_only=True,centering=True)
                reports.append(report)
        self.assertEqual(reports[0]['face_centering']['states'],reports[1]['face_centering']['states'])
        self.assertEqual(reports[0]['face_tracking']['ids_allocated'],reports[1]['face_tracking']['ids_allocated'])

    def test_overlay_suppresses_stale_positions_and_arrows(self):
        calculator=FaceCentering()
        output=calculator.update(observation(x=.5),now=1)
        with patch.object(cv2,'circle') as circle,patch.object(cv2,'arrowedLine') as arrow,patch.object(cv2,'putText') as text:
            expired=draw_centering(np.zeros((360,640,3),np.uint8),output,now=1.3,config=calculator.config)
        self.assertTrue(expired)
        circle.assert_not_called();arrow.assert_not_called()
        self.assertIn('STALE_OBSERVATION',text.call_args.args[1])

    def test_overlay_lost_target_has_no_current_geometry(self):
        calculator=FaceCentering()
        output=calculator.update(observation(visible=False,state='LOST'),now=1)
        with patch.object(cv2,'circle') as circle,patch.object(cv2,'arrowedLine') as arrow,patch.object(cv2,'putText') as text:
            draw_centering(np.zeros((360,640,3),np.uint8),output,now=1,config=calculator.config)
        circle.assert_not_called();arrow.assert_not_called()
        self.assertIn('TARGET_LOST',text.call_args.args[1])

    def test_overlay_shows_directions_and_optional_dead_zone(self):
        calculator=FaceCentering()
        output=calculator.update(observation(x=.4,y=-.4),now=1)
        with patch.object(cv2,'rectangle') as rectangle,patch.object(cv2,'arrowedLine') as arrow,patch.object(cv2,'putText') as text:
            draw_centering(np.zeros((360,640,3),np.uint8),output,now=1,config=calculator.config,debug=True)
        self.assertEqual(rectangle.call_count,2)
        self.assertEqual(arrow.call_count,1)
        labels=' '.join(call.args[1] for call in text.call_args_list)
        self.assertIn('PAN RIGHT',labels)
        self.assertIn('TILT UP',labels)
        self.assertIn('DEMAND',labels)


class CenteringBenchmarkTest(unittest.TestCase):
    def test_paired_benchmark_json_without_camera_or_native_input(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            path=Path(directory)/'report.json'
            with patch.object(benchmark_centering,'memory_probe',return_value={'separate_probe':True}), \
                    patch.object(benchmark_centering,'render_probe',return_value=[]), \
                    patch.object(cv2,'VideoCapture',side_effect=AssertionError('camera opened')), \
                    patch.object(cv2,'imshow',side_effect=AssertionError('GUI opened')),redirect_stdout(io.StringIO()):
                benchmark_centering.main(['--frames','12','--warmup','3','--repeats','1','--faces','1','--report',str(path)])
            saved=json.loads(path.read_text())
            self.assertEqual(saved['kind'],'synthetic_host_only')
            self.assertEqual(len(saved['cases']),4)
            self.assertEqual(len(saved['comparisons']),2)
            for case in saved['cases']:
                self.assertEqual(case['timings']['host_total']['count'],12)
                self.assertEqual('face_centering' in case['timings'],case['centering'])
            with redirect_stderr(io.StringIO()),self.assertRaises(SystemExit):
                benchmark_centering.main(['--report',str(path)])

    def test_invalid_benchmark_settings_are_rejected(self):
        for values in ({'faces':3},{'frames':0},{'warmup':-1}):
            with self.assertRaises(ValueError):
                benchmark_centering.run_case(**values)
