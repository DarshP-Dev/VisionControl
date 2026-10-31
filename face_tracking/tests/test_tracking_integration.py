from contextlib import redirect_stderr
import io
from pathlib import Path
import tempfile
import time
from unittest.mock import MagicMock, patch
import unittest

import cv2
import numpy as np

from controls.backends import SimulationBackend
from controls.controller import DesktopController
from face_tracking.face_tracker import FaceTracker
from face_tracking.preview import draw_tracks
from face_tracking.face_geometry import adapt_result
from gestures.tests.static_fixtures import as_result
from hand_tracking import hand_tracker as app
from . import test_integration as fixtures
from .test_tracker import face, frame
from .helpers import MP, detection, result


class TrackingIntegrationTest(unittest.TestCase):
    def test_cli_opt_in_and_tuning(self):
        args = app.parse_args(['--face-tracking', '--face-confirmation-hits', '4', '--face-lost-timeout', '1.2',
                               '--face-smoothing-tau', '0', '--face-tracking-debug'])
        self.assertTrue(args.face_detection)
        self.assertEqual(args.face_confirmation_hits, 4)
        self.assertEqual(args.face_lost_timeout, 1.2)
        self.assertEqual(args.face_smoothing_tau, 0)
        self.assertEqual(args.capture_pipeline, 'sync')
        self.assertEqual(args.windows_timer_policy, 'system')
        self.assertEqual(args.max_hands, 2)
        self.assertFalse(app.parse_args(['--face-only']).face_tracking)

    def test_cli_rejects_invalid_tuning_and_face_only_controls(self):
        for flags in (['--face-confirmation-hits', '0'], ['--face-confirmation-hits', '101'],
                      ['--face-lost-timeout', 'nan'], ['--face-lost-timeout', '0'],
                      ['--face-smoothing-tau', '-1'], ['--face-smoothing-tau', 'inf'],
                      ['--face-tracking-debug'], ['--face-only', '--face-tracking', '--controls']):
            with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                app.parse_args(flags)

    def test_face_only_temporal_path_skips_hand_and_uses_current_snapshot(self):
        fixture = fixtures.IntegrationTest()
        self.addCleanup(fixture.doCleanups)
        report, hand, detector, _, overlay, _ = fixture.pipeline(face_only=True, tracking=True)
        hand.detect_for_video.assert_not_called()
        self.assertTrue(report['face_tracking']['enabled'])
        snapshots = [call.args[1] for call in overlay.call_args_list]
        self.assertEqual(snapshots[0].tracks[0].track_id, 1)
        self.assertFalse(snapshots[1].tracks[0].detected)
        self.assertTrue(snapshots[2].tracks[0].detected)
        self.assertEqual(report['face_tracking']['ids_allocated'], 1)

    def test_combined_latest_minimize_restore_does_not_reset_tracker_or_camera(self):
        fixture = fixtures.IntegrationTest()
        self.addCleanup(fixture.doCleanups)
        report, hand, detector, display, overlay, source = fixture.pipeline(latest=True, minimized=True, tracking=True)
        self.assertEqual(hand.detect_for_video.call_count, detector.detect.call_count)
        self.assertEqual(display.call_count, 2)
        self.assertEqual(overlay.call_count, 2)
        self.assertEqual(report['face_tracking']['ids_allocated'], 1)
        self.assertEqual(report['face_tracking']['counters'].get('resets', 0), 0)
        self.assertTrue(source.stop.is_set())

    def test_detection_only_never_initializes_tracker(self):
        fixture = fixtures.IntegrationTest()
        self.addCleanup(fixture.doCleanups)
        with patch('face_tracking.face_tracker.FaceTracker', side_effect=AssertionError('not opted in')):
            report, *_ = fixture.pipeline()
        self.assertEqual(report['face_tracking'], {'enabled': False})

    def test_unfocused_preview_keeps_processing_and_drawing(self):
        fixture = fixtures.IntegrationTest()
        self.addCleanup(fixture.doCleanups)
        report, hand, detector, display, overlay, _ = fixture.pipeline(tracking=True, minimized=True, background_state='unfocused')
        self.assertEqual(display.call_count, 3)
        self.assertEqual(overlay.call_count, 3)
        self.assertEqual(hand.detect_for_video.call_count, detector.detect.call_count)
        self.assertEqual(report['face_tracking']['ids_allocated'], 1)

    def test_camera_read_fault_does_not_arm_or_dispatch_from_faces(self):
        cap, hand, detector, window = (MagicMock() for _ in range(4))
        image = np.zeros((12,20,3), np.uint8)
        reads = iter(((True,image), (True,image), (False,None)))
        def read():
            time.sleep(.002)
            return next(reads)
        cap.read.side_effect = read
        hand.detect_for_video.return_value = as_result()
        detector.last_inference_size = (20,12)
        detector.detect.side_effect = lambda _f, stamp, *_a, **_k: adapt_result(result(detection(2,2,8,6)), (20,12), (20,12), stamp)
        window.state.return_value = 'focused'
        window.should_render.return_value = False
        backend = SimulationBackend()
        controller = DesktopController(backend)
        args = app.parse_args(['--face-tracking','--gestures','--pinch','--gesture-states','--controls','--gui-mode','waitkey'])
        with patch.object(cv2,'waitKey',return_value=-1), patch.object(controller,'arm',wraps=controller.arm) as arm, \
                self.assertLogs(app.LOGGER), self.assertRaises(OSError):
            app.process_frames(cap,hand,MP,args,{},controller,preview_window=window,face_detector=detector)
        arm.assert_not_called()
        self.assertFalse(controller.armed)
        self.assertEqual(backend.counts['move'], 0)
        self.assertEqual(backend.counts['down'], 0)
        self.assertEqual(detector.detect.call_count, 2)

    def test_tracking_fault_releases_simulated_drag_and_disarms(self):
        cap, hand, detector, window = (MagicMock() for _ in range(4))
        cap.read.return_value = True, np.zeros((12, 20, 3), np.uint8)
        hand.detect_for_video.return_value = as_result()
        detector.detect.side_effect = lambda _f, stamp, *_a, **_k: adapt_result(result(detection(2, 2, 8, 6)), (20, 12), (20, 12), stamp)
        detector.last_inference_size = (20, 12)
        window.state.return_value = 'focused'
        controller = DesktopController(SimulationBackend())
        controller.armed = controller.button_down = controller.backend.button_down = True
        args = app.parse_args(['--face-tracking', '--gestures', '--pinch', '--gesture-states', '--controls', '--gui-mode', 'waitkey'])
        with patch.object(cv2, 'waitKey', return_value=-1), patch.object(controller, 'update'), \
                patch.object(FaceTracker, 'update', side_effect=RuntimeError('injected tracker fault')), \
                self.assertLogs(app.LOGGER), self.assertRaisesRegex(RuntimeError, 'tracker fault'):
            app.process_frames(cap, hand, MP, args, {}, controller, preview_window=window, face_detector=detector)
        self.assertFalse(controller.armed)
        self.assertFalse(controller.backend.button_down)

    def test_x_closes_models_and_shared_camera_with_tracking_enabled(self):
        original = app.parse_args
        with patch.object(app, 'parse_args', side_effect=lambda flags: original(flags+['--face-tracking'])):
            fixtures.IntegrationTest().test_combined_run_has_one_camera_owner_and_x_closes_both_models()

    def test_camera_open_failure_closes_face_only_model_with_tracking_enabled(self):
        original = app.parse_args
        with patch.object(app, 'parse_args', side_effect=lambda flags: original(flags+['--face-tracking'])):
            fixtures.IntegrationTest().test_face_only_run_never_initializes_hand_model_or_controller_and_one_camera()

    def test_headless_tracking_profiles_and_writes_json_without_gui_or_hand_model(self):
        import json
        from hand_tracking.performance import write_report
        cap, detector = MagicMock(), MagicMock()
        image = np.zeros((12, 20, 3), np.uint8)
        def read():
            time.sleep(.002)
            return True, image
        cap.read.side_effect = read
        detector.last_inference_size = (20, 12)
        detector.detect.side_effect = lambda _f, stamp, *_a, **_k: adapt_result(result(detection(2, 2, 8, 6)), (20, 12), (20, 12), stamp)
        args = app.parse_args(['--face-only', '--face-tracking', '--benchmark', '--warmup', '.001', '--duration', '.02', '--headless'])
        with patch.object(cv2, 'imshow') as show, patch.object(cv2, 'VideoCapture') as opener, \
                patch.object(app.control_cli, 'create_controller') as controls, self.assertLogs(app.LOGGER):
            report = {}
            app.process_frames(cap, None, MP, args, report, face_detector=detector)
        show.assert_not_called(); opener.assert_not_called(); controls.assert_not_called()
        self.assertGreater(report['frames'], 1)
        self.assertIn('face_tracking', report['timings'])
        self.assertIn('face_association', report['timings_by_preview_state']['headless'])
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            path = Path(directory)/'report.json'
            write_report(path, report)
            saved = json.loads(path.read_text())
        self.assertTrue(saved['face_tracking']['enabled'])
        self.assertIsNone(saved['face_tracking']['identity_switches'])

    def test_overlay_lost_primary_has_no_box_and_no_placeholder_center(self):
        tracker = FaceTracker()
        tracker.update(frame(0, face())); tracker.update(frame(.04, face()))
        tracker.update(frame(.08, face()))
        lost = tracker.update(frame(.12))
        with patch.object(cv2, 'rectangle') as box, patch.object(cv2, 'circle') as dot, patch.object(cv2, 'putText') as text:
            draw_tracks(np.zeros((200, 320, 3), np.uint8), lost, now=.12, debug=True)
        box.assert_not_called(); dot.assert_not_called()
        self.assertIn('PRIMARY LOST', text.call_args.args[1])

    def test_overlay_rechecks_freshness_after_slow_preview_render(self):
        tracker = FaceTracker()
        tracker.update(frame(0, face())); tracker.update(frame(.04, face()))
        snapshot = tracker.update(frame(.08, face()))
        with patch.object(cv2, 'rectangle') as box, patch.object(cv2, 'putText') as text:
            draw_tracks(np.zeros((200, 320, 3), np.uint8), snapshot, now=.4)
        box.assert_not_called()
        self.assertIn('PRIMARY LOST', text.call_args.args[1])

    def test_overlay_raw_debug_and_primary_style(self):
        tracker = FaceTracker()
        tracker.update(frame(0, face())); tracker.update(frame(.04, face()))
        snapshot = tracker.update(frame(.08, face(.21)))
        with patch.object(cv2, 'rectangle') as box, patch.object(cv2, 'circle') as dot, patch.object(cv2, 'putText') as text:
            draw_tracks(np.zeros((200, 320, 3), np.uint8), snapshot, now=.08, debug=True)
        self.assertEqual(box.call_args.args[4], 2)
        self.assertEqual(dot.call_count, 2)
        self.assertIn('FACE #1 | TRACKED | PRIMARY', text.call_args_list[0].args[1])
