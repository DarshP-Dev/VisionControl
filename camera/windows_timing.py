"""Reversible Windows 11 timer-request policy for the current process only.

Does not request a timer period, change execution-speed QoS or priority, or touch
global power/registry settings. Call before camera/input initialization and restore
after camera/model/input cleanup. No per-frame calls and no extra thread.
"""

import ctypes as C
from ctypes import wintypes as W
import os
import sys


POLICIES = ("system", "honor-requests")
IGNORE_TIMER_RESOLUTION = 0x4
PROCESS_POWER_THROTTLING = 4


class PowerThrottlingState(C.Structure):
    _fields_ = [(name, W.ULONG) for name in ("Version", "ControlMask", "StateMask")]


class Win32TimerAPI:
    def __init__(self):
        if os.name != "nt" or sys.getwindowsversion().build < 22000:
            raise OSError("honor-requests requires Windows 11 and ProcessPowerThrottling support")
        try:
            self.kernel = C.WinDLL("kernel32", use_last_error=True)
            self.kernel.GetCurrentProcess.argtypes = []
            self.kernel.GetCurrentProcess.restype = W.HANDLE
            self.handle = self.kernel.GetCurrentProcess()  # Pseudo-handle; never CloseHandle.
            for name in ("GetProcessInformation", "SetProcessInformation"):
                fn = getattr(self.kernel, name)
                fn.argtypes = [W.HANDLE, C.c_int, C.POINTER(PowerThrottlingState), W.DWORD]
                fn.restype = W.BOOL
        except (AttributeError, OSError) as exc:
            raise OSError(f"Windows timer policy API unavailable: {exc}") from exc

    def get(self):
        state = PowerThrottlingState(1, 0, 0)
        if not self.kernel.GetProcessInformation(self.handle, PROCESS_POWER_THROTTLING,
                                                C.byref(state), C.sizeof(state)):
            raise C.WinError(C.get_last_error())
        return state.Version, state.ControlMask, state.StateMask

    def set(self, values):
        state = PowerThrottlingState(*values)
        if not self.kernel.SetProcessInformation(self.handle, PROCESS_POWER_THROTTLING,
                                                C.byref(state), C.sizeof(state)):
            raise C.WinError(C.get_last_error())


def _state(values):
    return (dict(zip(("version", "control_mask", "state_mask"), values))
            if values is not None else None)


class WindowsTimerPolicy:
    """Single-use scope; exact original masks restored even after partial startup."""
    def __init__(self, mode="system", *, api=None):
        if mode not in POLICIES:
            raise ValueError("Unknown Windows timer policy")
        self.mode, self.api = mode, api
        self.original = self.applied = self.final = None
        self.attempted = self.active = self.owned = self.changed = False
        self.restored = None
        self.error = self.restore_error = None

    def start(self):
        if self.attempted:
            raise RuntimeError("Windows timer policy scope is single-use")
        self.attempted = True
        if self.mode == "system":
            self.active = True
            return self
        try:
            self.api = self.api if self.api is not None else Win32TimerAPI()
            self.original = self.api.get()
            if self.original[0] != 1:
                raise OSError("Unsupported PROCESS_POWER_THROTTLING_STATE version")
            target = (1, self.original[1] | IGNORE_TIMER_RESOLUTION,
                      self.original[2] & ~IGNORE_TIMER_RESOLUTION)
            if target != self.original:
                # An API error must not bypass rollback of a potentially applied set.
                self.owned = True
                self.api.set(target)
                self.changed = True
            self.applied = self.api.get()
            if self.applied != target:
                raise OSError("Windows did not confirm the requested timer policy")
            self.active = True
            return self
        except BaseException as exc:
            self.error = str(exc)
            try:
                self.close()
            except OSError as cleanup:
                raise OSError(f"Timer policy initialization failed ({exc}); rollback failed ({cleanup})") from exc
            raise

    def close(self):
        self.active = False
        if self.owned:
            try:
                self.api.set(self.original)
                self.final = self.api.get()
                if self.final != self.original:
                    raise OSError("Windows did not confirm restoration of the original timer policy")
            except OSError as exc:
                self.restored = False
                self.restore_error = str(exc)
                raise
            self.owned = False
            self.restored, self.restore_error = True, None
        elif self.original is not None:
            self.final = self.original
            self.restored = True

    def snapshot(self):
        return {"requested": self.mode, "active": self.active, "changed": self.changed,
                "original": _state(self.original), "applied": _state(self.applied), "final": _state(self.final),
                "restored": self.restored, "error": self.error, "restore_error": self.restore_error,
                "scope": "current process only; no new timer-period request or execution-speed QoS change",
                "power_note": "Honoring existing timer requests while minimized can increase wakeups/CPU/power; energy not measured."}
