"""Fake process APIs only. Never sets a real process policy or sends input."""

import ctypes as C
from ctypes import wintypes as W
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

from camera.windows_timing import WindowsTimerPolicy, Win32TimerAPI, PowerThrottlingState


class FakeAPI:
    def __init__(self, state=(1, 1, 1)):
        self.state, self.sets, self.gets = state, [], 0
        self.fail_set = self.fail_get = False

    def get(self):
        self.gets += 1
        if self.fail_get:
            raise OSError("get failed")
        return self.state

    def set(self, state):
        self.sets.append(state)
        self.state = state
        if self.fail_set:
            self.fail_set = False  # Simulate partial application; rollback must occur.
            raise OSError("set failed")


class WindowsTimerPolicyTest(unittest.TestCase):
    def test_system_default_never_loads_windows_or_reads_or_changes_policy(self):
        with patch("camera.windows_timing.Win32TimerAPI", side_effect=AssertionError("default API")):
            scope = WindowsTimerPolicy().start()
            scope.close()
            scope.close()
        self.assertFalse(scope.snapshot()["changed"])
        self.assertIsNone(scope.snapshot()["restored"])

    def test_honor_changes_only_timer_bit_and_restores_exact_masks(self):
        for initial in ((1, 0, 0), (1, 1, 1), (1, 5, 5), (1, 1, 0)):
            with self.subTest(initial=initial):
                api = FakeAPI(initial)
                scope = WindowsTimerPolicy("honor-requests", api=api).start()
                self.assertEqual(api.state, (1, initial[1] | 4, initial[2] & ~4))
                self.assertEqual(api.state[1] & ~4, initial[1] & ~4)
                self.assertEqual(api.state[2] & ~4, initial[2] & ~4)
                scope.close()
                self.assertEqual(api.state, initial)
                self.assertTrue(scope.snapshot()["restored"])
                self.assertFalse(scope.active)

    def test_existing_honor_policy_needs_no_mutation_or_timer_period_request(self):
        api = FakeAPI((1, 5, 1))
        scope = WindowsTimerPolicy("honor-requests", api=api).start()
        scope.close()
        self.assertEqual(api.sets, [])
        self.assertFalse(scope.changed)
        self.assertTrue(scope.restored)

    def test_close_is_idempotent_and_scope_cannot_be_started_twice(self):
        api = FakeAPI()
        scope = WindowsTimerPolicy("honor-requests", api=api).start()
        with self.assertRaises(RuntimeError):
            scope.start()
        scope.close()
        scope.close()
        self.assertEqual(len(api.sets), 2)

    def test_failed_initial_read_does_not_attempt_uninformed_set(self):
        api = FakeAPI()
        api.fail_get = True
        scope = WindowsTimerPolicy("honor-requests", api=api)
        with self.assertRaisesRegex(OSError, "get failed"):
            scope.start()
        self.assertEqual(api.sets, [])
        self.assertFalse(scope.active)

    def test_failed_set_after_partial_application_rolls_back(self):
        api = FakeAPI()
        original = api.state
        api.fail_set = True
        scope = WindowsTimerPolicy("honor-requests", api=api)
        with self.assertRaisesRegex(OSError, "set failed"):
            scope.start()
        self.assertEqual(api.state, original)
        self.assertEqual(len(api.sets), 2)
        self.assertTrue(scope.restored)

    def test_unconfirmed_application_restores_and_refuses_success(self):
        api = FakeAPI()
        original_set = api.set
        def ignored(state):
            if state == (1, 5, 1):
                api.sets.append(state)  # Success return without applying request.
            else:
                original_set(state)
        api.set = ignored
        scope = WindowsTimerPolicy("honor-requests", api=api)
        with self.assertRaisesRegex(OSError, "did not confirm"):
            scope.start()
        self.assertTrue(scope.restored)
        self.assertEqual(api.state, (1, 1, 1))

    def test_restore_failure_is_reported_and_can_be_retried(self):
        api = FakeAPI()
        scope = WindowsTimerPolicy("honor-requests", api=api).start()
        api.fail_set = True
        with self.assertRaisesRegex(OSError, "set failed"):
            scope.close()
        self.assertFalse(scope.restored)
        self.assertTrue(scope.owned)
        self.assertIsNotNone(scope.snapshot()["restore_error"])
        scope.close()
        self.assertTrue(scope.restored)
        self.assertFalse(scope.owned)

    def test_unconfirmed_restoration_is_not_reported_successful(self):
        api = FakeAPI()
        scope = WindowsTimerPolicy("honor-requests", api=api).start()
        api.set = lambda _: None
        with self.assertRaisesRegex(OSError, "restoration"):
            scope.close()
        self.assertFalse(scope.restored)

    def test_start_and_rollback_failure_both_remain_visible(self):
        api = FakeAPI()
        api.set = MagicMock(side_effect=OSError("denied"))
        scope = WindowsTimerPolicy("honor-requests", api=api)
        with self.assertRaisesRegex(OSError, "initialization failed.*rollback failed"):
            scope.start()
        self.assertEqual(api.set.call_count, 2)
        self.assertFalse(scope.restored)
        self.assertFalse(scope.active)

    def test_interrupt_during_application_still_restores(self):
        api = FakeAPI()
        original_set = api.set
        first = []
        def interrupted(state):
            original_set(state)
            if not first:
                first.append(True)
                raise KeyboardInterrupt()
        api.set = interrupted
        scope = WindowsTimerPolicy("honor-requests", api=api)
        with self.assertRaises(KeyboardInterrupt):
            scope.start()
        self.assertEqual(api.state, (1, 1, 1))
        self.assertTrue(scope.restored)

    def test_unknown_mode_and_future_structure_version_are_rejected(self):
        with self.assertRaises(ValueError):
            WindowsTimerPolicy("priority")
        api = FakeAPI((2, 0, 0))
        with self.assertRaisesRegex(OSError, "version"):
            WindowsTimerPolicy("honor-requests", api=api).start()
        self.assertEqual(api.sets, [])

    def test_windows_10_and_non_windows_explicit_request_fail_without_loading_dlls(self):
        for name, build in (("posix", 0), ("nt", 19045)):
            with patch("camera.windows_timing.os.name", name), \
                    patch("camera.windows_timing.sys.getwindowsversion", return_value=SimpleNamespace(build=build), create=True), \
                    patch("camera.windows_timing.C.WinDLL") as dll, self.assertRaises(OSError):
                Win32TimerAPI()
            dll.assert_not_called()

    def test_native_bindings_use_current_process_and_correct_structure(self):
        kernel = MagicMock()
        kernel.GetCurrentProcess.return_value = 0x123456789
        def get(_handle, _kind, pointer, _size):
            pointer._obj.ControlMask = 1
            pointer._obj.StateMask = 1
            return 1
        kernel.GetProcessInformation.side_effect = get
        with patch("camera.windows_timing.C.WinDLL", return_value=kernel):
            api = Win32TimerAPI()
            self.assertEqual(api.get(), (1, 1, 1))
            api.set((1, 5, 1))
        self.assertEqual(C.sizeof(PowerThrottlingState), 12)
        self.assertEqual(kernel.GetCurrentProcess.restype, W.HANDLE)
        self.assertEqual(kernel.GetProcessInformation.call_args.args[0:2], (0x123456789, 4))
        self.assertEqual(kernel.SetProcessInformation.call_args.args[-1], 12)
        kernel.CloseHandle.assert_not_called()


if __name__ == "__main__":
    unittest.main()
