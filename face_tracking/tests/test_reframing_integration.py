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

from camera.latest_capture import LatestCapture
from camera.test_latest_capture import ScriptedCamera
from controls.backends import SimulationBackend
from controls.controller import DesktopController
from face_tracking.face_geometry import adapt_result
from face_tracking.reframing_preview import ReframeRenderer
from face_tracking.digital_reframing import DigitalReframer
from face_tracking import benchmark_reframing
from gestures.tests.static_fixtures import as_result, pose_hand
from hand_tracking import hand_tracker as app
from hand_tracking.preview_window import PreviewWindow
from .helpers import MP, detection, result
from . import test_integration as old_fixtures
from . import test_tracking_integration as tracking_fixtures


class ReframingIntegrationTest(unittest.TestCase):
    def pipeline(self, *, original_min=False, aux_min=False, aux_closed=False, original_closed=False,
                 headless=False, preview=True, latest=False, face_only=False, enabled=True, controller=None):
        image=np.full((108,192,3),17,np.uint8)
        cap,hand,detector,main_window,aux_window=(MagicMock() for _ in range(5))
        def read():
            time.sleep(.002)
            return True,image
        cap.read.side_effect=read
        hand.detect_for_video.return_value=as_result(pose_hand())
        source=camera=None
        if latest:
            camera=ScriptedCamera()
            native_read=camera.read
            def delayed_read():
                item=native_read();time.sleep(.002);return item
            camera.read=delayed_read
            source=LatestCapture(lambda:camera).start()
            camera.queue.put((True,image))
            def cleanup():
                source.request_stop();camera.unblock.set();source.close(1)
            self.addCleanup(cleanup)
        detector.last_inference_size=(192,108)
        def detect(frame,stamp,*a,**kw):
            self.assertEqual(frame.shape,(108,192,3))
            self.assertTrue(np.all(frame==17),'tracking source was annotated or cropped')
            if camera is not None and detector.detect.call_count<5:
                camera.queue.put((True,image))
            return adapt_result(result(detection(120,30,24,32)),(192,108),(192,108),stamp)
        detector.detect.side_effect=detect
        main_window.state.side_effect=lambda:'closed' if original_closed and detector.detect.call_count>=2 else 'minimized' if original_min and detector.detect.call_count in (2,3) else 'focused'
        aux_window.state.side_effect=lambda:'closed' if aux_closed and detector.detect.call_count>=2 else 'minimized' if aux_min and detector.detect.call_count in (2,3) else 'unfocused'
        main_window.should_render.side_effect=aux_window.should_render.side_effect=PreviewWindow.should_render
        flags=['--digital-reframe' if enabled else '--face-centering','--gui-mode','waitkey',
               '--capture-pipeline','latest-thread' if latest else 'sync']
        if face_only:flags+=['--face-only']
        if not preview:flags+=['--no-reframe-preview']
        if headless:flags+=['--headless','--benchmark','--warmup','.001','--duration','.02']
        if controller is not None:flags+=['--controls','--gestures','--pinch','--gesture-states']
        args=app.parse_args(flags)
        with patch.object(cv2,'waitKey',side_effect=lambda *_:ord('q') if detector.detect.call_count>=5 else -1) as keys, \
                patch.object(cv2,'imshow') as display,patch.object(cv2,'VideoCapture') as opener,self.assertLogs(app.LOGGER):
            report={}
            app.process_frames(None if latest else cap,None if face_only else hand,MP,args,report,controller,
                preview_window=main_window,reframe_window=aux_window,capture_source=source,face_detector=detector)
        opener.assert_not_called()
        self.assertTrue(np.all(image==17))
        for call in hand.detect_for_video.call_args_list:
            self.assertEqual(call.args[0].shape,(108,192,3))
        return report,hand,detector,display,keys,source

    def test_cli_dependencies_and_defaults(self):
        args=app.parse_args(['--digital-reframe'])
        self.assertTrue(args.face_detection and args.face_tracking and args.face_centering)
        self.assertTrue(args.reframe_preview)
        self.assertEqual((args.reframe_scale,args.reframe_follow_tau,args.reframe_max_speed,args.reframe_dead_zone),(2/3,.2,600,.1))
        self.assertEqual((args.capture_pipeline,args.windows_timer_policy,args.width,args.height,args.fps),('sync','system',1920,1080,60))

    def test_invalid_cli_configuration(self):
        for flags in (['--reframe-scale','0'],['--reframe-scale','1.1'],['--reframe-scale','nan'],
                      ['--reframe-follow-tau','-1'],['--reframe-follow-tau','inf'],['--reframe-max-speed','0'],
                      ['--reframe-max-speed','nan'],['--reframe-dead-zone','0'],['--reframe-dead-zone','1.1'],
                      ['--reframe-debug'],['--face-only','--digital-reframe','--controls']):
            with redirect_stderr(io.StringIO()),self.assertRaises(SystemExit):app.parse_args(flags)

    def test_two_previews_share_original_tracking_and_source_pixels(self):
        report,hand,detector,display,_,_=self.pipeline()
        self.assertEqual(hand.detect_for_video.call_count,detector.detect.call_count)
        titles=[c.args[0] for c in display.call_args_list]
        self.assertEqual(titles.count(app.WINDOW),4)
        self.assertEqual(titles.count(app.REFRAME_WINDOW),4)
        self.assertEqual(report['digital_reframing']['secondary_preview']['rendered_frames'],4)
        self.assertEqual(report['detected_hands_frames'],{'1':4})

    def test_no_second_event_loop_for_auxiliary_window(self):
        _,_,_,_,baseline_keys,_=self.pipeline(enabled=False)
        _,_,_,_,dual_keys,_=self.pipeline()
        self.assertEqual(dual_keys.call_count,baseline_keys.call_count)

    def test_closing_auxiliary_disables_only_that_window(self):
        report,_,detector,display,_,_=self.pipeline(aux_closed=True)
        self.assertEqual(detector.detect.call_count,5)
        self.assertTrue(report['digital_reframing']['secondary_preview']['closed'])
        self.assertEqual([c.args[0] for c in display.call_args_list].count(app.REFRAME_WINDOW),1)
        self.assertEqual(report['frames'],4)

    def test_original_close_stops_session(self):
        report,_,detector,_,_,_=self.pipeline(original_closed=True)
        self.assertEqual(report['status'],'preview_closed')
        self.assertEqual(detector.detect.call_count,2)

    def test_original_minimized_auxiliary_still_renders(self):
        report,_,_,display,_,_=self.pipeline(original_min=True)
        titles=[c.args[0] for c in display.call_args_list]
        self.assertEqual(titles.count(app.WINDOW),2)
        self.assertEqual(titles.count(app.REFRAME_WINDOW),4)
        self.assertEqual(sum(report['digital_reframing']['reasons'].values()),5)

    def test_auxiliary_minimized_skips_crop_work_and_restores(self):
        report,_,_,display,_,_=self.pipeline(aux_min=True)
        titles=[c.args[0] for c in display.call_args_list]
        self.assertEqual(titles.count(app.WINDOW),4)
        self.assertEqual(titles.count(app.REFRAME_WINDOW),2)
        self.assertEqual(report['digital_reframing']['secondary_preview']['frames_by_state']['minimized'],2)

    def test_both_minimized_continue_calculation_without_rendering(self):
        report,_,_,display,_,_=self.pipeline(original_min=True,aux_min=True)
        self.assertEqual(display.call_count,4)
        self.assertEqual(sum(report['digital_reframing']['reasons'].values()),5)

    def test_calculations_only_never_constructs_crop_renderer(self):
        with patch('face_tracking.reframing_preview.ReframeRenderer',side_effect=AssertionError('unneeded renderer')):
            report,_,_,display,_,_=self.pipeline(preview=False)
        self.assertTrue(report['digital_reframing']['enabled'])
        self.assertTrue(all(c.args[0]==app.WINDOW for c in display.call_args_list))

    def test_headless_never_creates_or_displays_crop(self):
        with patch('face_tracking.reframing_preview.ReframeRenderer',side_effect=AssertionError('headless renderer')):
            report,hand,_,display,keys,_=self.pipeline(headless=True,face_only=True)
        display.assert_not_called();keys.assert_not_called();hand.detect_for_video.assert_not_called()
        self.assertIn('reframe_update',report['timings'])
        self.assertNotIn('reframe_rendering',report['timings'])
        self.assertFalse(report['digital_reframing']['secondary_preview']['requested'])

    def test_latest_worker_remains_shared_and_is_fenced_on_exit(self):
        report,hand,detector,_,_,source=self.pipeline(latest=True,aux_min=True)
        self.assertEqual(hand.detect_for_video.call_count,detector.detect.call_count)
        self.assertTrue(source.stop.is_set())
        self.assertEqual(source.max_occupancy,1)
        self.assertEqual(report['frames'],4)

    def test_disabled_feature_does_not_import_reframing(self):
        import builtins
        original=builtins.__import__
        def guard(name,*a,**kw):
            if name.startswith(('face_tracking.digital_reframing','face_tracking.reframing_')):
                raise AssertionError('disabled reframe imported')
            return original(name,*a,**kw)
        with patch('builtins.__import__',side_effect=guard):
            report,*_=self.pipeline(enabled=False)
        self.assertEqual(report['digital_reframing'],{'enabled':False})

    def test_render_failure_disarms_and_releases_simulated_drag(self):
        controller=DesktopController(SimulationBackend())
        controller.armed=controller.button_down=controller.backend.button_down=True
        with patch.object(controller,'update'),patch.object(ReframeRenderer,'render',side_effect=RuntimeError('injected render failure')), \
                self.assertRaisesRegex(RuntimeError,'render failure'):
            self.pipeline(controller=controller)
        self.assertFalse(controller.armed)
        self.assertFalse(controller.backend.button_down)

    def test_calculation_failure_disarms_and_releases_simulated_drag(self):
        controller=DesktopController(SimulationBackend())
        controller.armed=controller.button_down=controller.backend.button_down=True
        with patch.object(controller,'update'),patch.object(DigitalReframer,'update',side_effect=RuntimeError('injected viewport failure')), \
                self.assertRaisesRegex(RuntimeError,'viewport failure'):
            self.pipeline(controller=controller)
        self.assertFalse(controller.armed)
        self.assertFalse(controller.backend.button_down)

    def test_camera_fault_never_arms_or_dispatches_from_reframing(self):
        original=app.parse_args
        with patch.object(app,'parse_args',side_effect=lambda flags:original(flags+['--digital-reframe','--no-reframe-preview'])):
            tracking_fixtures.TrackingIntegrationTest().test_camera_read_fault_does_not_arm_or_dispatch_from_faces()

    def test_x_cleanup_keeps_one_camera_owner_for_both_models(self):
        original=app.parse_args
        instance=old_fixtures.IntegrationTest()
        self.addCleanup(instance.doCleanups)
        with patch.object(app,'parse_args',side_effect=lambda flags:original(flags+['--digital-reframe'])):
            instance.test_combined_run_has_one_camera_owner_and_x_closes_both_models()

    def test_run_creates_two_owned_windows_but_one_camera(self):
        cap,hand,detector,window,aux=(MagicMock() for _ in range(5))
        detector.mp=MP;detector.metadata.return_value={'closed':True}
        cap.isOpened.return_value=True
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            path=Path(directory)/'model';path.write_bytes(b'mock')
            args=app.parse_args(['--digital-reframe','--model',str(path),'--face-model',str(path)])
            with patch.object(app,'create_landmarker',return_value=(MP,hand)), \
                    patch('face_tracking.face_detector.FaceDetector',return_value=detector), \
                    patch.object(cv2,'VideoCapture',return_value=cap) as camera, \
                    patch.object(app,'configure_capture'),patch.object(app,'capture_snapshot',return_value={}), \
                    patch.object(app,'capture_control_readbacks',return_value={}),patch.object(cv2,'namedWindow') as named, \
                    patch.object(cv2,'destroyAllWindows') as destroy, \
                    patch.object(app,'create_preview_window',side_effect=(window,aux)) as ownership, \
                    patch.object(app,'process_frames',return_value=0) as process,self.assertLogs(app.LOGGER):
                self.assertEqual(app.run(args,{}),0)
        camera.assert_called_once()
        self.assertEqual([c.args[0] for c in named.call_args_list],[app.WINDOW,app.REFRAME_WINDOW])
        self.assertEqual([c.args[0] for c in ownership.call_args_list],[app.WINDOW,app.REFRAME_WINDOW])
        self.assertIs(process.call_args.kwargs['reframe_window'],aux)
        cap.release.assert_called_once();hand.close.assert_called_once();detector.close.assert_called_once();destroy.assert_called_once()


class ReframingBenchmarkTest(unittest.TestCase):
    def test_paired_json_has_geometry_cost_and_never_opens_camera_or_windows(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            path=Path(directory)/'report.json'
            with patch.object(benchmark_reframing,'memory_probe',return_value={}), \
                    patch.object(benchmark_reframing,'render_probe',return_value=[]), \
                    patch.object(cv2,'VideoCapture',side_effect=AssertionError('camera opened')), \
                    patch.object(cv2,'imshow',side_effect=AssertionError('HighGUI opened')),redirect_stdout(io.StringIO()):
                benchmark_reframing.main(['--frames','6','--warmup','3','--repeats','1','--faces','1','--render-frames','2','--report',str(path)])
            saved=json.loads(path.read_text())
            self.assertEqual(len(saved['cases']),4)
            self.assertEqual(len(saved['comparisons']),2)
            self.assertEqual(saved['kind'],'synthetic_host_and_display_preparation')
            for case in saved['cases']:
                self.assertEqual(case['timings']['host_total']['count'],6)
                self.assertEqual('reframe_update' in case['timings'],case['reframing'])
            with redirect_stderr(io.StringIO()),self.assertRaises(SystemExit):benchmark_reframing.main(['--report',str(path)])

    def test_invalid_benchmark_parameters(self):
        for params in ({'faces':3},{'frames':0},{'warmup':-1}):
            with self.assertRaises(ValueError):benchmark_reframing.run_case(**params)
