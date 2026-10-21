"""CLI/factory/status integration without a camera, hotkey registration or real input."""

from contextlib import ExitStack, redirect_stderr
import io
import unittest
from unittest.mock import MagicMock, patch

import cv2
import numpy as np

from controls import cli
from controls.backends import SimulationBackend
from controls.controller import DesktopController
from controls.models import ControlSettings
from gestures.tests.static_fixtures import as_result
from . import hand_tracker as tracker
from . import test_controls as application_tests
from .tracking_utils import make_preview


FLAGS = ["--gestures", "--pinch", "--gesture-states", "--controls"]


class EmergencyHotkeyIntegrationTest(unittest.TestCase):
    def test_cli_defaults_and_existing_commands_unchanged(self):
        for flags in ([], FLAGS, FLAGS+["--control-mode", "live"]):
            args = tracker.parse_args(flags)
            self.assertEqual(args.control_emergency_hotkey, "ctrl+alt+esc")
            self.assertEqual(cli.settings(args).emergency_hotkey, "ctrl+alt+esc")

    def test_alternative_in_both_modes_normalizes_before_configuration(self):
        for mode in ("simulate", "live"):
            args = tracker.parse_args(FLAGS+["--control-mode", mode, "--control-emergency-hotkey", "SHIFT+CTRL+F10"])
            self.assertEqual(args.control_emergency_hotkey, "ctrl+shift+f10")
            self.assertEqual(cli.settings(args).emergency_hotkey, "ctrl+shift+f10")

    def test_invalid_cli_reports_useful_reason_including_reserved_f12(self):
        for value in ("ctrl+shift+f12", "ctrl+shift+esc", "win+l", "f10", "ctrl++f10"):
            stream = io.StringIO()
            with redirect_stderr(stream), self.assertRaises(SystemExit):
                tracker.parse_args(FLAGS+["--control-emergency-hotkey", value])
            self.assertIn("ctrl+shift+f10", stream.getvalue())
            if value.endswith("f12"):
                self.assertIn("reserved", stream.getvalue())

    def test_exact_requested_launch_with_approved_f10_parses(self):
        args = tracker.parse_args(FLAGS+["--control-mode", "live", "--control-mapping", "absolute",
                                        "--control-region-width", "0.80", "--control-region-height", "0.80",
                                        "--control-hand", "right", "--control-mouse",
                                        "--control-emergency-hotkey", "ctrl+shift+f10"])
        settings = cli.settings(args)
        self.assertEqual((settings.mode, settings.mapping, settings.region_width, settings.region_height),
                         ("live", "absolute", .8, .8))
        self.assertEqual(settings.hand.value, "Right")
        self.assertTrue(settings.mouse)
        self.assertTrue(settings.invert_x)

    def test_simulation_alternative_never_loads_live_backend_or_safety_monitor(self):
        args = tracker.parse_args(FLAGS+["--control-emergency-hotkey", "ctrl+shift+f10"])
        with patch("controls.windows.WindowsBackend") as windows, patch("controls.safety.GlobalSafety") as monitor, \
                ExitStack() as resources:
            controller = cli.create_controller(args, resources)
            self.assertIsInstance(controller.backend, SimulationBackend)
            self.assertFalse(controller.armed)
            self.assertEqual(controller.settings.emergency_hotkey, "ctrl+shift+f10")
        windows.assert_not_called()
        monitor.assert_not_called()

    def test_live_factory_passes_configuration_to_existing_safety_monitor(self):
        backend = MagicMock(is_live=True)
        backend.screen = cli.simulation_screen(tracker.parse_args([]))
        with patch("controls.windows.WindowsBackend", return_value=backend), \
                patch("controls.safety.GlobalSafety") as monitor, ExitStack() as resources:
            controller = cli.create_controller(tracker.parse_args(FLAGS+["--control-mode", "live",
                                                "--control-emergency-hotkey", "ctrl+shift+f10"]), resources)
            self.assertEqual(monitor.call_args.args[0].settings.emergency_hotkey, "ctrl+shift+f10")
            self.assertIs(monitor.call_args.args[1], backend.api)
            monitor.return_value.start.assert_called_once_with()
            self.assertFalse(controller.armed)
        backend.move.assert_not_called()
        backend.left_down.assert_not_called()

    def test_preview_shows_configured_live_shortcut_without_changing_source(self):
        backend = SimulationBackend()
        backend.is_live = True
        controller = DesktopController(backend, ControlSettings(mode="live", emergency_hotkey="ctrl+shift+f10"))
        source = np.full((480, 640, 3), 120, np.uint8)
        for help_enabled in (False, True):
            with patch.object(cv2, "putText", wraps=cv2.putText) as text:
                make_preview(source, as_result(), 36., help_enabled, control_status=controller.status())
            labels = [call.args[1] for call in text.call_args_list]
            self.assertTrue(any("STOP: Ctrl+Shift+F10" in label for label in labels))
            self.assertFalse(any("Ctrl+Alt+Esc" in label for label in labels))
            self.assertTrue(any("DISARMED" in label for label in labels))
        self.assertTrue(np.all(source == 120))
        simulated = DesktopController(SimulationBackend(), ControlSettings(emergency_hotkey="ctrl+shift+f10"))
        self.assertNotIn("STOP:", " ".join(simulated.status().lines()))

    def test_report_records_selected_shortcut_and_q_h_still_work(self):
        controller, report, preview, *_ = application_tests.ControlApplicationTest().pipeline(
            [as_result(), as_result()], [ord("h"), ord("q")],
            ("--control-emergency-hotkey", "ctrl+shift+f10"))
        self.assertEqual(report["controls"]["settings"]["emergency_hotkey"], "ctrl+shift+f10")
        self.assertIn("ctrl+shift+f10", report["controls"]["emergency_stop"])
        self.assertTrue(preview.call_args_list[1].args[3])
        self.assertFalse(controller.armed)


if __name__ == "__main__":
    unittest.main()
