"""Emergency-only shortcuts, fake Win32 registration and virtual input sinks."""

import ctypes as C
import threading
import unittest
from unittest.mock import MagicMock, patch

from controls.backends import SimulationBackend
from controls.controller import DesktopController
from controls.hotkeys import DEFAULT_EMERGENCY_HOTKEY, EMERGENCY_HOTKEYS, display_hotkey, normalize_hotkey
from controls.models import ControlSettings
from controls.safety import GlobalSafety
from controls.windows import WindowsAPI
from .test_controls import Harness


class HotkeyConfigurationTest(unittest.TestCase):
    def test_default_is_backward_compatible(self):
        self.assertEqual(ControlSettings().emergency_hotkey, "ctrl+alt+esc")
        self.assertEqual(display_hotkey(DEFAULT_EMERGENCY_HOTKEY), "Ctrl+Alt+Esc")

    def test_case_whitespace_and_modifier_order_normalize(self):
        for value in ("CTRL+SHIFT+F10", " shift + Ctrl + f10 ", "ctrl+shift+f10"):
            self.assertEqual(normalize_hotkey(value), "ctrl+shift+f10")
            self.assertEqual(ControlSettings(emergency_hotkey=value).emergency_hotkey, "ctrl+shift+f10")
        self.assertEqual(normalize_hotkey("ALT+CTRL+ESC"), "ctrl+alt+esc")
        self.assertEqual(display_hotkey("shift+ctrl+F10"), "Ctrl+Shift+F10")

    def test_malformed_and_unsupported_combinations_rejected(self):
        for value in (None, 1, "", "+", "ctrl++f10", "ctrl+ctrl+f10", "ctrl+shift+", "f10",
                      "ctrl+f10", "shift+f10", "alt+f10", "meta+shift+f10", "control+shift+f10",
                      "f10+ctrl+shift", "ctrl+alt+shift+f10", "ctrl+shift+f8", "ctrl+shift+a"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                ControlSettings(emergency_hotkey=value)

    def test_reserved_and_inappropriate_system_shortcuts_rejected(self):
        for value in ("ctrl+alt+del", "ctrl+shift+esc", "alt+tab", "alt+f4", "win+l", "ctrl+esc",
                      "win+shift+f10", "ctrl+shift+printscreen", "ctrl+shift+f12", "ctrl+alt+f12"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                normalize_hotkey(value)
        with self.assertRaisesRegex(ValueError, "reserved.*ctrl\\+shift\\+f10"):
            normalize_hotkey("CTRL+SHIFT+F12")


class HotkeyRegistrationTest(unittest.TestCase):
    def api(self):
        api = object.__new__(WindowsAPI)  # Never construct WinDLL or send input.
        api.user = MagicMock()
        return api

    def test_all_supported_win32_modifiers_and_virtual_keys(self):
        expected = {"ctrl+alt+esc": (0x4003, 0x1B), "ctrl+shift+f9": (0x4006, 0x78),
                    "ctrl+shift+f10": (0x4006, 0x79), "ctrl+shift+f11": (0x4006, 0x7A)}
        self.assertEqual(set(expected), set(EMERGENCY_HOTKEYS))
        for name, (modifiers, key) in expected.items():
            api = self.api()
            with patch.object(C, "set_last_error", create=True) as reset:
                api.register_stop(name.upper())
            reset.assert_called_once_with(0)
            api.user.RegisterHotKey.assert_called_once_with(None, 0x5636, modifiers, key)

    def test_rejected_config_never_calls_registration(self):
        api = self.api()
        with self.assertRaises(ValueError):
            api.register_stop("ctrl+shift+f12")
        api.user.RegisterHotKey.assert_not_called()

    def test_conflict_reports_real_windows_code_and_guidance(self):
        api = self.api()
        api.user.RegisterHotKey.return_value = 0
        with patch.object(C, "set_last_error", create=True), \
                patch.object(C, "get_last_error", return_value=1409, create=True), \
                patch.object(C, "FormatError", return_value="Hot key is already registered.", create=True), \
                self.assertRaises(OSError) as raised:
            api.register_stop("ctrl+shift+f10")
        self.assertEqual(raised.exception.errno, 1409)
        for text in ("Ctrl+Shift+F10", "1409", "already owns", "--control-emergency-hotkey", "no automatic fallback"):
            self.assertIn(text, str(raised.exception))
        self.assertEqual(api.user.RegisterHotKey.call_count, 1)

    def test_other_errors_are_not_misreported_as_conflicts(self):
        for code in (5, 87, 0):
            api = self.api()
            api.user.RegisterHotKey.return_value = 0
            with patch.object(C, "set_last_error", create=True), \
                    patch.object(C, "get_last_error", return_value=code, create=True), \
                    patch.object(C, "FormatError", return_value="Specific Windows failure", create=True) as formatter, \
                    self.assertRaises(OSError) as raised:
                api.register_stop("ctrl+shift+f9")
            self.assertIn(f"Windows error {code}", str(raised.exception))
            self.assertNotIn("already owns", str(raised.exception))
            if code:
                formatter.assert_called_once_with(code)
            else:
                formatter.assert_not_called()
                self.assertIn("no error code", str(raised.exception))

    def test_last_error_is_captured_before_formatting(self):
        api = self.api()
        order = []
        api.user.RegisterHotKey.side_effect = lambda *args: order.append("register") or 0
        with patch.object(C, "set_last_error", side_effect=lambda code: order.append("reset"), create=True), \
                patch.object(C, "get_last_error", side_effect=lambda: order.append("get") or 1409, create=True), \
                patch.object(C, "FormatError", side_effect=lambda code: order.append("format") or "occupied", create=True), \
                self.assertRaises(OSError):
            api.register_stop()
        self.assertEqual(order, ["reset", "register", "get", "format"])

    def test_unregister_uses_same_thread_registration_id_and_checks_failure(self):
        api = self.api()
        api.unregister_stop()
        api.user.UnregisterHotKey.assert_called_once_with(None, 0x5636)
        api.user.UnregisterHotKey.return_value = 0
        with self.assertRaises(OSError):
            api.unregister_stop()


class ConfiguredEmergencySafetyTest(unittest.TestCase):
    def harness(self):
        h = Harness()
        h.backend.is_live = True  # Live safety policy, entirely virtual actions.
        h.controller = DesktopController(h.backend, ControlSettings(mode="live", mouse=True, mapping="absolute",
                                                                   emergency_hotkey="ctrl+shift+f10"),
                                         clock=lambda: h.now)
        return h

    def monitor(self, controller):
        api = MagicMock()
        requested = threading.Event()
        api.stop_requested.side_effect = lambda: requested.is_set()
        return GlobalSafety(controller, api), api, requested

    def test_successful_registration_starts_disarmed_and_cleanup_is_idempotent(self):
        h = self.harness()
        safety, api, _ = self.monitor(h.controller)
        safety.start()
        try:
            self.assertTrue(h.controller.safety_ready)
            self.assertFalse(h.controller.armed)
            self.assertEqual(h.backend.counts, {})
            api.register_stop.assert_called_once_with("ctrl+shift+f10")
            with self.assertRaises(RuntimeError):
                safety.start()  # Never leave a second registration on an existing monitor.
        finally:
            safety.close()
            safety.close()
        api.unregister_stop.assert_called_once_with()
        self.assertFalse(safety.thread.is_alive())
        self.assertFalse(h.controller.arm())

    def test_registration_and_unregistration_run_on_the_same_safety_thread(self):
        for _ in range(3):
            h = self.harness()
            safety, api, _ = self.monitor(h.controller)
            owners = []
            api.register_stop.side_effect = lambda name: owners.append(("register", threading.get_ident(), name))
            api.unregister_stop.side_effect = lambda: owners.append(("unregister", threading.get_ident(), None))
            safety.start()
            safety.close()
            self.assertEqual([item[0] for item in owners], ["register", "unregister"])
            self.assertEqual(owners[0][1], owners[1][1])
            self.assertNotEqual(owners[0][1], threading.get_ident())

    def test_registration_failure_blocks_arming_without_fallback_or_unregister(self):
        h = self.harness()
        safety, api, _ = self.monitor(h.controller)
        error = OSError(1409, "Ctrl+Shift+F10 Windows error 1409: already registered")
        api.register_stop.side_effect = error
        with self.assertLogs("controls", level="ERROR"), self.assertRaisesRegex(OSError, "Ctrl\\+Shift\\+F10.*1409") as raised:
            safety.start()
        self.assertIs(raised.exception.__cause__, error)
        self.assertFalse(h.controller.safety_ready)
        self.assertFalse(h.controller.arm())
        self.assertEqual(h.backend.counts, {})
        api.register_stop.assert_called_once_with("ctrl+shift+f10")
        api.unregister_stop.assert_not_called()
        self.assertFalse(safety.thread.is_alive())

    def test_partial_startup_failure_after_registration_unregisters(self):
        h = self.harness()
        safety, api, _ = self.monitor(h.controller)
        # Failing after registration but before readiness still unregisters on its owner thread.
        with patch.object(safety.stop, "is_set", side_effect=[False, OSError("startup failed")]), \
                self.assertLogs("controls", level="ERROR"), self.assertRaisesRegex(OSError, "startup failed"):
            safety.start()
        api.unregister_stop.assert_called_once_with()
        self.assertFalse(h.controller.safety_ready)
        self.assertFalse(h.controller.arm())

    def test_startup_timeout_cleans_successfully_registered_hotkey(self):
        h = self.harness()
        safety, api, _ = self.monitor(h.controller)
        registered = threading.Event()
        api.register_stop.side_effect = lambda name: registered.set()
        # Suppress only readiness notification, not the actual safety thread.
        def timeout(_seconds):
            self.assertTrue(registered.wait(1))
            return False
        with patch.object(safety.ready, "wait", side_effect=timeout), self.assertRaisesRegex(OSError, "timed out"):
            safety.start()
        api.unregister_stop.assert_called_once_with()
        self.assertFalse(h.controller.safety_ready)
        self.assertFalse(safety.thread.is_alive())

    def test_configured_emergency_releases_drag_and_blocks_later_actions(self):
        h = self.harness()
        safety, api, request = self.monitor(h.controller)
        stopped = threading.Event()
        original = h.controller.disarm
        def disarm(reason):
            original(reason)
            if reason.startswith("GLOBAL"):
                stopped.set()
        h.controller.disarm = disarm
        safety.start()
        try:
            h.arm()
            h.start()
            self.assertTrue(h.backend.button_down)
            request.set()
            self.assertTrue(stopped.wait(1))
            self.assertFalse(h.controller.armed)
            self.assertFalse(h.backend.button_down)
            request.clear()
            counts = dict(h.backend.counts)
            h.step(dx=.02)
            h.start()
            self.assertEqual(dict(h.backend.counts), counts)
            self.assertEqual(h.backend.counts["up"], 1)
        finally:
            safety.close()

    def blocked_query(self, *, arming):
        h = self.harness()
        safety, api, request = self.monitor(h.controller)
        safety.start()
        entered, resume, latched = threading.Event(), threading.Event(), threading.Event()
        original = h.backend.cursor_position
        h.step()
        if not arming:
            h.arm()
        def blocked():
            entered.set()
            if not resume.wait(2):
                raise TimeoutError("fake query timed out")
            return original()
        h.backend.cursor_position = blocked
        original_set = h.controller._stop_requested.set
        def latch():
            original_set()
            latched.set()
        answers = []
        worker = threading.Thread(target=(lambda: answers.append(h.controller.arm())) if arming else h.start)
        try:
            with patch.object(h.controller._stop_requested, "set", side_effect=latch):
                worker.start()
                self.assertTrue(entered.wait(1))
                request.set()
                self.assertTrue(latched.wait(1))
                resume.set()
                worker.join(2)
            self.assertFalse(worker.is_alive())
        finally:
            resume.set()
            worker.join(2)
            safety.close()
        self.assertFalse(h.controller.armed)
        self.assertEqual(h.backend.counts["down"], 0)
        self.assertEqual(h.backend.counts["move"], 0)
        if arming:
            self.assertEqual(answers, [False])

    def test_configured_hotkey_cancels_pending_down_during_blocked_preparation(self):
        self.blocked_query(arming=False)

    def test_configured_hotkey_cannot_be_undone_by_in_flight_arm(self):
        self.blocked_query(arming=True)

    def test_alternative_shortcut_preserves_stall_watchdog(self):
        h = self.harness()
        safety, _, _ = self.monitor(h.controller)
        expired = threading.Event()
        original = h.controller.check_timeout
        def check():
            original()
            if not h.controller.armed and "stalled" in h.controller.reason:
                expired.set()
        h.controller.check_timeout = check
        safety.start()
        try:
            h.arm()
            h.start()
            h.now += .501
            self.assertTrue(expired.wait(1))
            self.assertFalse(h.backend.button_down)
            self.assertFalse(h.controller.armed)
        finally:
            safety.close()

    def test_runtime_monitor_failure_with_alternative_shortcut_fails_closed(self):
        h = self.harness()
        safety, api, request = self.monitor(h.controller)
        stopped = threading.Event()
        original = h.controller.safety_failure
        def failure(reason):
            original(reason)
            stopped.set()
        h.controller.safety_failure = failure
        api.stop_requested.side_effect = lambda: (_ for _ in ()).throw(OSError("queue failed")) if request.is_set() else False
        safety.start()
        try:
            h.arm()
            h.start()
            with self.assertLogs("controls", level="ERROR"):
                request.set()
                self.assertTrue(stopped.wait(1))
                safety.thread.join(1)
            self.assertFalse(h.controller.arm())
            self.assertFalse(h.backend.button_down)
        finally:
            safety.close()
        api.unregister_stop.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
