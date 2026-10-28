"""CLI/resource integration with fake process APIs, model and camera."""

from contextlib import redirect_stderr
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from camera.test_windows_timing import FakeAPI
from camera.windows_timing import WindowsTimerPolicy
from controls.backends import SimulationBackend
from controls.controller import DesktopController
from controls.models import ControlSettings
from . import hand_tracker as tracker


class TimerIntegrationTest(unittest.TestCase):
    def test_cli_preserves_system_timer_and_sync_defaults_and_validates_policy(self):
        args = tracker.parse_args([])
        self.assertEqual(args.capture_pipeline, "sync")
        self.assertEqual(args.windows_timer_policy, "system")
        self.assertEqual(tracker.parse_args(["--windows-timer-policy", "honor-requests"]).windows_timer_policy,
                         "honor-requests")
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            tracker.parse_args(["--windows-timer-policy", "realtime"])

    def model(self, directory):
        path = Path(directory)/"mock.task"
        path.write_bytes(b"mock, never loaded")
        return path

    def test_failed_timer_policy_precedes_model_camera_and_control_initialization(self):
        api = FakeAPI()
        api.fail_set = True
        scope = WindowsTimerPolicy("honor-requests", api=api)
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as directory, \
                patch.object(tracker, "WindowsTimerPolicy", return_value=scope), \
                patch.object(tracker, "create_landmarker") as model, \
                patch.object(tracker.cv2, "VideoCapture") as camera, \
                patch.object(tracker.control_cli, "create_controller") as controls, self.assertLogs(tracker.LOGGER):
            args = tracker.parse_args(["--model", str(self.model(directory)),
                                       "--windows-timer-policy", "honor-requests"])
            report = {}
            self.assertEqual(tracker.run(args, report), 1)
        model.assert_not_called()
        camera.assert_not_called()
        controls.assert_not_called()
        self.assertTrue(report["windows_timer_policy"]["restored"])
        self.assertEqual(api.state, (1, 1, 1))

    def test_camera_failure_restores_policy_after_camera_and_model_cleanup(self):
        events = []
        api = FakeAPI()
        original_set = api.set
        def setting(state):
            events.append("restore" if state == (1, 1, 1) else "apply")
            original_set(state)
        api.set = setting
        scope = WindowsTimerPolicy("honor-requests", api=api)
        camera, model = MagicMock(), MagicMock()
        camera.isOpened.return_value = False
        camera.release.side_effect = lambda: events.append("camera_release")
        model.close.side_effect = lambda: events.append("model_close")
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as directory, \
                patch.object(tracker, "WindowsTimerPolicy", return_value=scope), \
                patch.object(tracker, "create_landmarker", return_value=(MagicMock(), model)), \
                patch.object(tracker.cv2, "VideoCapture", return_value=camera), self.assertLogs(tracker.LOGGER):
            args = tracker.parse_args(["--model", str(self.model(directory)),
                                       "--windows-timer-policy", "honor-requests"])
            report = {}
            self.assertEqual(tracker.run(args, report), 1)
        self.assertEqual(events, ["apply", "camera_release", "model_close", "restore"])
        self.assertTrue(report["windows_timer_policy"]["restored"])
        self.assertEqual(api.state, (1, 1, 1))

    def test_restore_failure_is_visible_after_other_resources_are_released(self):
        api = FakeAPI()
        scope = WindowsTimerPolicy("honor-requests", api=api)
        camera, model = MagicMock(), MagicMock()
        camera.isOpened.return_value = False
        camera.release.side_effect = lambda: setattr(api, "fail_set", True)
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as directory, \
                patch.object(tracker, "WindowsTimerPolicy", return_value=scope), \
                patch.object(tracker, "create_landmarker", return_value=(MagicMock(), model)), \
                patch.object(tracker.cv2, "VideoCapture", return_value=camera), self.assertLogs(tracker.LOGGER):
            args = tracker.parse_args(["--model", str(self.model(directory)),
                                       "--windows-timer-policy", "honor-requests"])
            report = {}
            self.assertEqual(tracker.run(args, report), 1)
        camera.release.assert_called_once()
        model.close.assert_called_once()
        self.assertFalse(report["windows_timer_policy"]["restored"])
        self.assertEqual(report["windows_timer_policy"]["restore_error"], "set failed")
        scope.close()  # Only a fake policy; prove explicit retry is safe.

    def test_tracking_fault_releases_virtual_drag_before_timer_policy_restoration(self):
        api = FakeAPI()
        events = []
        original_set = api.set
        def set_policy(state):
            if state == (1, 1, 1):
                events.append("restore")
            original_set(state)
        api.set = set_policy
        scope = WindowsTimerPolicy("honor-requests", api=api)
        backend = SimulationBackend()
        controller = DesktopController(backend, ControlSettings(mouse=True))
        controller.armed = controller.button_down = backend.button_down = True
        def controls(_args, resources):
            def release():
                controller.disarm("mock fault cleanup")
                self.assertFalse(backend.button_down)
                self.assertEqual(api.state, (1, 5, 1))
                events.append("input_released")
            resources.callback(release)
            return controller
        camera, model = MagicMock(), MagicMock()
        camera.isOpened.return_value = True
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as directory, \
                patch.object(tracker, "WindowsTimerPolicy", return_value=scope), \
                patch.object(tracker.control_cli, "create_controller", side_effect=controls), \
                patch.object(tracker, "create_landmarker", return_value=(MagicMock(), model)), \
                patch.object(tracker.cv2, "VideoCapture", return_value=camera), \
                patch.object(tracker, "configure_capture"), patch.object(tracker, "capture_snapshot", return_value={}), \
                patch.object(tracker.cv2, "namedWindow"), patch.object(tracker.cv2, "destroyAllWindows"), \
                patch.object(tracker, "create_preview_window", return_value=MagicMock()), \
                patch.object(tracker, "process_frames", side_effect=OSError("mock tracking fault")), \
                self.assertLogs(tracker.LOGGER):
            args = tracker.parse_args(["--model", str(self.model(directory)), "--windows-timer-policy",
                "honor-requests", "--gestures", "--pinch", "--gesture-states", "--controls", "--control-mouse"])
            report = {}
            self.assertEqual(tracker.run(args, report), 1)
        self.assertEqual(events, ["input_released", "restore"])
        self.assertFalse(controller.armed)
        self.assertFalse(backend.button_down)
        self.assertTrue(report["windows_timer_policy"]["restored"])
        camera.release.assert_called_once()
        model.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
