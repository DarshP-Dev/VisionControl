"""All Win32 calls below are fakes: never instantiate the real WindowsAPI."""

import ctypes as C
from ctypes import wintypes as W
import threading
import unittest
from unittest.mock import MagicMock

from controls.backends import SimulationBackend
from controls.controller import DesktopController
from controls.models import ControlSettings, Screen
from controls.safety import GlobalSafety
from controls.windows import Input, WindowsAPI, WindowsBackend


class FakeAPI:
    def __init__(self):
        self.user = MagicMock()
        self.user.GetForegroundWindow.return_value = 101
        self.user.GetAsyncKeyState.return_value = 0
        self.sent = []
        self.prepare_dpi = MagicMock()
        self.monitors = MagicMock(return_value=[Screen(), Screen(left=-2560, width=2560, height=1440)])
        self.virtual_screen = MagicMock(return_value=Screen(left=-2560, width=4480, height=1440))
        self.foreground = MagicMock(return_value=(101, "chrome.exe"))

    def cursor_position(self):
        return 100, 200

    def send(self, inputs):
        self.sent.append(inputs)


class WindowsBackendTest(unittest.TestCase):
    def test_constructor_dpi_monitors_and_no_input_until_action(self):
        api = FakeAPI()
        backend = WindowsBackend(1, api=api)
        api.prepare_dpi.assert_called_once()
        self.assertEqual(backend.screen, Screen(left=-2560, width=2560, height=1440))
        self.assertEqual(api.sent, [])
        backend.close()
        self.assertEqual(api.sent, [])

    def test_bad_dpi_and_missing_monitor_fail_without_input(self):
        api = FakeAPI()
        api.prepare_dpi.side_effect = OSError("DPI failure")
        with self.assertRaises(OSError):
            WindowsBackend(api=api)
        api.prepare_dpi.side_effect = None
        with self.assertRaises(ValueError):
            WindowsBackend(5, api=api)
        self.assertEqual(api.sent, [])

    def test_virtual_desktop_coordinates_and_selected_monitor_clamp(self):
        api = FakeAPI()
        backend = WindowsBackend(1, api=api)
        backend.move(-2560, 0)
        self.assertEqual((api.sent[-1][0].mi.dx, api.sent[-1][0].mi.dy), (0, 0))
        self.assertEqual(api.sent[-1][0].mi.dwFlags, 0xC001)
        backend.move(99999, 99999)
        self.assertEqual(api.sent[-1][0].mi.dx, round(2559*65535/4479))
        self.assertEqual(api.sent[-1][0].mi.dy, 65535)

    def test_primary_physical_coordinates_not_scaled_again_by_dpi(self):
        api = FakeAPI()
        backend = WindowsBackend(api=api)
        backend.move(1000, 500)
        self.assertEqual(api.sent[-1][0].mi.dx, round((1000+2560)*65535/4479))
        self.assertEqual(api.sent[-1][0].mi.dy, round(500*65535/1439))

    def test_mouse_input_flags_ownership_and_cleanup_idempotence(self):
        api = FakeAPI()
        backend = WindowsBackend(api=api)
        backend.left_down()
        backend.left_up()
        backend.close()
        self.assertEqual([s[0].mi.dwFlags for s in api.sent], [2, 4])

    def test_physical_button_down_is_not_stolen_or_released(self):
        api = FakeAPI()
        api.user.GetAsyncKeyState.return_value = 0x8000
        backend = WindowsBackend(api=api)
        with self.assertRaisesRegex(OSError, "already held"):
            backend.left_down()
        backend.close()
        self.assertEqual(api.sent, [])

    def test_inconsistent_virtual_desktop_bounds_rejected(self):
        api = FakeAPI()
        api.virtual_screen.return_value = Screen(width=500, height=500)
        with self.assertRaisesRegex(ValueError, "geometry"):
            WindowsBackend(api=api)
        self.assertEqual(api.sent, [])

    def test_tab_keys_down_and_reverse_up_in_one_batch(self):
        for previous, vks in ((False, [0x11, 9]), (True, [0x11, 0x10, 9])):
            api = FakeAPI()
            backend = WindowsBackend(api=api)
            self.assertTrue(backend.switch_tab(previous, ("chrome.exe",)))
            sent = api.sent[0]
            self.assertEqual([i.ki.wVk for i in sent], vks+vks[::-1])
            self.assertEqual([i.ki.dwFlags for i in sent], [0]*len(vks)+[2]*len(vks))
            self.assertEqual(backend.keys_owned, set())

    def test_untrusted_missing_or_changing_foreground_blocks_keys(self):
        for foreground, current in (((101, "notepad.exe"), 101), ((None, ""), None), ((101, "chrome.exe"), 102)):
            api = FakeAPI()
            api.foreground.return_value = foreground
            api.user.GetForegroundWindow.return_value = current
            backend = WindowsBackend(api=api)
            self.assertFalse(backend.switch_tab(False, ("chrome.exe",)))
            self.assertEqual(api.sent, [])

    def test_held_physical_modifiers_block_shortcut_without_releasing_user_keys(self):
        api = FakeAPI()
        api.user.GetAsyncKeyState.return_value = 0x8000
        backend = WindowsBackend(api=api)
        self.assertFalse(backend.switch_tab(False, ("chrome.exe",)))
        backend.close()
        self.assertEqual(api.sent, [])

    def test_partial_key_batch_failure_attempts_every_possible_key_up(self):
        api = FakeAPI()
        original = api.send
        def send(inputs):
            original(inputs)
            if len(inputs) > 1:
                raise OSError("partial batch")
        api.send = send
        backend = WindowsBackend(api=api)
        with self.assertRaises(OSError):
            backend.switch_tab(True, ("chrome.exe",))
        self.assertEqual({s[0].ki.wVk for s in api.sent[1:]}, {0x11, 0x10, 9})
        self.assertTrue(all(s[0].ki.dwFlags == 2 for s in api.sent[1:]))
        self.assertFalse(backend.keys_owned)

    def test_key_up_failure_does_not_skip_other_keys_and_cleanup_retries(self):
        api = FakeAPI()
        backend = WindowsBackend(api=api)
        backend.keys_owned = {0x11, 0x10, 9}
        original = api.send
        def send(inputs):
            original(inputs)
            if inputs[0].ki.wVk == 0x11:
                raise OSError("fake key-up failure")
        api.send = send
        with self.assertRaises(OSError):
            backend.release_keys()
        self.assertEqual(len(api.sent), 3)
        self.assertEqual(backend.keys_owned, {0x11})
        api.send = original
        backend.close()
        self.assertFalse(backend.keys_owned)

    def test_mouse_failure_does_not_prevent_keyboard_cleanup(self):
        api = FakeAPI()
        backend = WindowsBackend(api=api)
        backend.button_owned = True
        backend.keys_owned = {0x11}
        original = api.send
        def send(inputs):
            original(inputs)
            if inputs[0].type == 0:
                raise OSError("fake mouse failure")
        api.send = send
        with self.assertRaises(OSError):
            backend.close()
        self.assertEqual(api.sent[-1][0].ki.wVk, 0x11)


class WindowsSignaturesTest(unittest.TestCase):
    def api(self):
        api = object.__new__(WindowsAPI)  # No WinDLL, hotkeys, screen queries or input.
        api.user = MagicMock()
        return api

    def test_input_structure_matches_windows_abi(self):
        self.assertEqual(C.sizeof(Input), 40 if C.sizeof(C.c_void_p) == 8 else 28)
        self.assertEqual(Input.data.offset, 8 if C.sizeof(C.c_void_p) == 8 else 4)

    def test_missing_windows_api_has_clear_error(self):
        with self.assertRaisesRegex(OSError, "unavailable"):
            WindowsAPI._bind(object(), "MissingFunction", [], None)

    def test_send_checks_complete_batch_and_exact_struct_size(self):
        api = self.api()
        api.user.SendInput.return_value = 1
        api.send([Input()])
        self.assertEqual(api.user.SendInput.call_args.args[0], 1)
        self.assertEqual(api.user.SendInput.call_args.args[2], C.sizeof(Input))
        api.user.SendInput.return_value = 0
        with self.assertRaises(OSError):
            api.send([Input()])

    def test_hotkey_registration_parameters_and_fail_closed(self):
        api = self.api()
        api.user.RegisterHotKey.return_value = 1
        api.register_stop()
        api.user.RegisterHotKey.assert_called_once_with(None, 0x5636, 0x4003, 0x1B)
        api.user.RegisterHotKey.return_value = 0
        with self.assertRaises(OSError):
            api.register_stop()

    def test_hotkey_queue_recognizes_only_our_message(self):
        api = self.api()
        entries = iter([(0x0312, 22), (0x0312, 0x5636), None])
        def peek(pointer, *_):
            entry = next(entries)
            if entry is None:
                return 0
            msg = C.cast(pointer, C.POINTER(W.MSG)).contents
            msg.message, msg.wParam = entry
            return 1
        api.user.PeekMessageW.side_effect = peek
        self.assertTrue(api.stop_requested())

    def test_dpi_requires_per_monitor_awareness(self):
        api = self.api()
        api.user.GetAwarenessFromDpiAwarenessContext.return_value = 2
        api.prepare_dpi()
        api.user.GetAwarenessFromDpiAwarenessContext.return_value = 1
        with self.assertRaises(OSError):
            api.prepare_dpi()


class SafetyTest(unittest.TestCase):
    def controller(self):
        backend = SimulationBackend()
        backend.is_live = True  # Live policy with a purely virtual input sink.
        return DesktopController(backend, ControlSettings(mode="live"))

    def test_global_stop_outside_preview_loop_and_resource_cleanup(self):
        controller = self.controller()
        api = MagicMock()
        api.stop_requested.return_value = False
        stopped = threading.Event()
        original = controller.disarm
        def disarm(reason):
            original(reason)
            if reason.startswith("GLOBAL"):
                stopped.set()
        controller.disarm = disarm
        safety = GlobalSafety(controller, api).start()
        try:
            self.assertTrue(controller.safety_ready)
            controller.armed = controller.button_down = controller.backend.button_down = True
            api.stop_requested.return_value = True
            self.assertTrue(stopped.wait(1))
            self.assertFalse(controller.armed)
            self.assertFalse(controller.backend.button_down)
        finally:
            safety.close()
        api.register_stop.assert_called_once()
        api.unregister_stop.assert_called_once()
        self.assertFalse(safety.thread.is_alive())

    def test_registration_failure_never_permits_arming(self):
        controller = self.controller()
        api = MagicMock()
        api.register_stop.side_effect = OSError("occupied")
        with self.assertLogs("controls", level="ERROR"), self.assertRaises(OSError):
            GlobalSafety(controller, api).start()
        self.assertFalse(controller.safety_ready)
        self.assertFalse(controller.arm())
        api.unregister_stop.assert_not_called()

    def test_runtime_emergency_monitor_failure_releases_and_latches_unavailable(self):
        controller = self.controller()
        api = MagicMock()
        trigger = threading.Event()
        failed = threading.Event()
        api.stop_requested.side_effect = lambda: (_ for _ in ()).throw(OSError("queue")) if trigger.is_set() else False
        original = controller.safety_failure
        def failure(reason):
            original(reason)
            failed.set()
        controller.safety_failure = failure
        safety = GlobalSafety(controller, api).start()
        controller.armed = controller.button_down = controller.backend.button_down = True
        try:
            with self.assertLogs("controls", level="ERROR"):
                trigger.set()
                self.assertTrue(failed.wait(1))
            self.assertFalse(controller.armed)
            self.assertFalse(controller.backend.button_down)
            self.assertFalse(controller.arm())
        finally:
            safety.close()

    def test_stall_watchdog_runs_while_camera_loop_is_absent(self):
        controller = self.controller()
        controller.armed = controller.button_down = controller.backend.button_down = True
        controller.last_heartbeat -= 1
        api = MagicMock()
        api.stop_requested.return_value = False
        released = threading.Event()
        original = controller.check_timeout
        def check():
            original()
            if not controller.armed:
                released.set()
        controller.check_timeout = check
        safety = GlobalSafety(controller, api).start()
        try:
            self.assertTrue(released.wait(1))
            self.assertFalse(controller.backend.button_down)
        finally:
            safety.close()


if __name__ == "__main__":
    unittest.main()
