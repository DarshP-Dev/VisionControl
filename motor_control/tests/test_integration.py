from contextlib import redirect_stderr
import io
from pathlib import Path
import tempfile
from unittest.mock import MagicMock, patch
import unittest

import cv2

from controls.backends import SimulationBackend
from controls.controller import DesktopController
from face_tracking.tests import test_reframing_integration as reframing_fixtures
from face_tracking.tests import test_integration as face_fixtures
from face_tracking.tests import test_tracking_integration as tracking_fixtures
from face_tracking.tests.helpers import MP
from hand_tracking import hand_tracker as app
from hand_tracking.preview_window import PreviewWindow
from motor_control.controller import MotorController
from motor_control.visualization import MotorRenderer


class MotorIntegrationTest(unittest.TestCase):
    def pipeline(self,*,motor_enabled=True,coexist=False,motor_preview=True,minimized=False,closed=False,**kwargs):
        fixture=reframing_fixtures.ReframingIntegrationTest()
        self.addCleanup(fixture.doCleanups)
        window=MagicMock()
        window.should_render.side_effect=PreviewWindow.should_render
        window.state.side_effect=lambda:'closed' if closed else 'minimized' if minimized and window.state.call_count<=6 else 'focused'
        original=app.parse_args
        def parse(flags):
            extra=['--motor-simulate'] if motor_enabled else []
            if not motor_preview:extra+=['--no-motor-sim-preview']
            return original(flags+extra)
        with patch.object(app,'parse_args',side_effect=parse),patch.object(app,'PreviewWindow',return_value=window):
            return fixture.pipeline(enabled=coexist,**kwargs)

    def test_cli_opt_in_prerequisites_and_unchanged_capture(self):
        args=app.parse_args(['--motor-simulate','--motor-sim-debug'])
        self.assertTrue(args.face_detection and args.face_tracking and args.face_centering)
        self.assertFalse(args.digital_reframe)
        self.assertEqual((args.motor_pan_limit,args.motor_tilt_limit,args.motor_max_pan_speed,args.motor_max_tilt_speed),(45,25,30,20))
        self.assertEqual((args.capture_pipeline,args.windows_timer_policy,args.width,args.height,args.fps),('sync','system',1920,1080,60))
        self.assertFalse(app.parse_args([]).motor_simulate)

    def test_cli_invalid_settings_and_face_only_desktop_controls_rejected(self):
        for flags in (['--motor-sim-debug'],['--motor-pan-limit','0'],['--motor-pan-limit','181'],
                      ['--motor-tilt-limit','nan'],['--motor-max-pan-speed','361'],['--motor-max-tilt-speed','inf'],
                      ['--motor-simulate','--face-only','--controls']):
            with redirect_stderr(io.StringIO()),self.assertRaises(SystemExit):app.parse_args(flags)

    def test_face_only_uses_one_model_and_separate_motor_window(self):
        report,hand,detector,display,_,_=self.pipeline(face_only=True)
        hand.detect_for_video.assert_not_called()
        titles=[c.args[0] for c in display.call_args_list]
        self.assertEqual(titles.count(app.WINDOW),4)
        self.assertEqual(titles.count(app.MOTOR_WINDOW),4)
        self.assertEqual(report['motor_simulation']['counters']['updates'],detector.detect.call_count)
        self.assertFalse(report['motor_simulation']['hardware_output_enabled'])

    def test_combined_and_digital_outputs_share_original_source(self):
        report,hand,detector,display,_,_=self.pipeline(coexist=True)
        self.assertEqual(hand.detect_for_video.call_count,detector.detect.call_count)
        self.assertTrue(report['digital_reframing']['enabled'])
        self.assertTrue(report['motor_simulation']['enabled'])
        titles=[c.args[0] for c in display.call_args_list]
        self.assertEqual({app.WINDOW,app.REFRAME_WINDOW,app.MOTOR_WINDOW},set(titles))

    def test_no_extra_event_pump(self):
        _,_,_,_,old_keys,_=self.pipeline(motor_enabled=False)
        _,_,_,_,new_keys,_=self.pipeline()
        self.assertEqual(old_keys.call_count,new_keys.call_count)

    def test_minimized_motor_window_skips_drawing_and_restores(self):
        report,_,detector,display,_,_=self.pipeline(minimized=True)
        preview=report['motor_simulation']['preview']
        self.assertGreater(preview['frames_by_state'].get('minimized',0),0)
        self.assertGreater(preview['rendered_frames'],0)
        self.assertLess(preview['rendered_frames'],4)
        self.assertEqual(report['motor_simulation']['counters']['updates'],detector.detect.call_count)

    def test_original_minimized_motor_preview_remains_live(self):
        report,_,_,display,_,_=self.pipeline(original_min=True)
        self.assertEqual([c.args[0] for c in display.call_args_list].count(app.MOTOR_WINDOW),4)
        self.assertEqual(report['pacing']['preview_frames_skipped'],2)

    def test_motor_window_close_disables_simulation_but_not_other_processing(self):
        report,_,detector,display,_,_=self.pipeline(closed=True)
        self.assertEqual(detector.detect.call_count,5)
        self.assertTrue(report['motor_simulation']['preview']['closed'])
        self.assertGreater(report['motor_simulation']['reasons'].get('DISABLED',0),0)
        self.assertFalse(any(c.args[0]==app.MOTOR_WINDOW for c in display.call_args_list))
        self.assertEqual(report['frames'],4)

    def test_no_visualization_when_explicitly_disabled(self):
        with patch('motor_control.visualization.MotorRenderer',side_effect=AssertionError('unneeded renderer')):
            report,_,_,display,_,_=self.pipeline(motor_preview=False)
        self.assertTrue(report['motor_simulation']['enabled'])
        self.assertFalse(any(c.args[0]==app.MOTOR_WINDOW for c in display.call_args_list))

    def test_headless_has_calculations_but_no_renderer_or_input(self):
        with patch('motor_control.visualization.MotorRenderer',side_effect=AssertionError('headless renderer')):
            report,hand,_,display,keys,_=self.pipeline(headless=True,face_only=True)
        hand.detect_for_video.assert_not_called();display.assert_not_called();keys.assert_not_called()
        self.assertIn('motor_total',report['timings'])
        self.assertIn('motor_control_update',report['timings'])
        self.assertNotIn('motor_visualization',report['timings'])

    def test_latest_worker_is_shared_and_fenced_on_exit(self):
        report,hand,detector,_,_,source=self.pipeline(latest=True)
        self.assertEqual(hand.detect_for_video.call_count,detector.detect.call_count)
        self.assertTrue(source.stop.is_set())
        self.assertEqual(report['frames'],4)

    def test_disabled_feature_never_imports_motor_package(self):
        import builtins
        original=builtins.__import__
        def guard(name,*a,**kw):
            if name.startswith('motor_control'):raise AssertionError('disabled motor import')
            return original(name,*a,**kw)
        with patch('builtins.__import__',side_effect=guard):
            report,*_=self.pipeline(motor_enabled=False)
        self.assertEqual(report['motor_simulation'],{'enabled':False,'hardware_output_enabled':False})

    def test_motor_failure_disarms_desktop_and_releases_virtual_drag(self):
        desktop=DesktopController(SimulationBackend())
        desktop.armed=desktop.button_down=desktop.backend.button_down=True
        with patch.object(desktop,'update'),patch.object(MotorController,'update',side_effect=RuntimeError('motor failure')), \
                self.assertRaisesRegex(RuntimeError,'motor failure'):
            self.pipeline(controller=desktop)
        self.assertFalse(desktop.armed);self.assertFalse(desktop.backend.button_down)

    def test_visualization_failure_disarms_desktop_and_releases_virtual_drag(self):
        desktop=DesktopController(SimulationBackend())
        desktop.armed=desktop.button_down=desktop.backend.button_down=True
        with patch.object(desktop,'update'),patch.object(MotorRenderer,'render',side_effect=RuntimeError('visualizer failure')), \
                self.assertRaisesRegex(RuntimeError,'visualizer failure'):
            self.pipeline(controller=desktop)
        self.assertFalse(desktop.armed);self.assertFalse(desktop.backend.button_down)

    def test_capture_fault_does_not_arm_or_dispatch_desktop(self):
        original=app.parse_args
        with patch.object(app,'parse_args',side_effect=lambda flags:original(flags+['--motor-simulate','--no-motor-sim-preview'])):
            tracking_fixtures.TrackingIntegrationTest().test_camera_read_fault_does_not_arm_or_dispatch_from_faces()

    def test_original_x_closes_camera_and_models(self):
        instance=face_fixtures.IntegrationTest()
        self.addCleanup(instance.doCleanups)
        original=app.parse_args
        with patch.object(app,'parse_args',side_effect=lambda flags:original(flags+['--motor-simulate'])):
            instance.test_combined_run_has_one_camera_owner_and_x_closes_both_models()

    def test_run_owns_motor_and_optional_crop_windows_with_one_camera(self):
        for coexist in (False,True):
            cap,hand,detector=(MagicMock() for _ in range(3))
            detector.mp=MP;detector.metadata.return_value={'closed':True};cap.isOpened.return_value=True
            windows=[MagicMock() for _ in range(3)]
            with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
                path=Path(directory)/'mock.model';path.write_bytes(b'mock')
                flags=['--motor-simulate','--model',str(path),'--face-model',str(path)]
                if coexist:flags+=['--digital-reframe']
                args=app.parse_args(flags)
                with patch.object(app,'create_landmarker',return_value=(MP,hand)), \
                        patch('face_tracking.face_detector.FaceDetector',return_value=detector), \
                        patch.object(cv2,'VideoCapture',return_value=cap) as camera,patch.object(app,'configure_capture'), \
                        patch.object(app,'capture_snapshot',return_value={}),patch.object(cv2,'namedWindow') as named, \
                        patch.object(cv2,'destroyAllWindows') as destroy,patch.object(app,'create_preview_window',side_effect=windows), \
                        patch.object(app,'process_frames',return_value=0) as process,self.assertLogs(app.LOGGER):
                    self.assertEqual(app.run(args,{}),0)
                camera.assert_called_once();cap.release.assert_called_once();destroy.assert_called_once()
                hand.close.assert_called_once();detector.close.assert_called_once()
                expected=[app.WINDOW,app.MOTOR_WINDOW]+([app.REFRAME_WINDOW] if coexist else [])
                self.assertEqual([c.args[0] for c in named.call_args_list],expected)
                self.assertIs(process.call_args.kwargs['motor_window'],windows[1])
