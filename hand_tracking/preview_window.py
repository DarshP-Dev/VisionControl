"""Observe only our HighGUI window; minimizing is distinct from destroying it.

No focus manipulation, foreign window titles, input, or background worker.
HighGUI creation, pumping, state checks and destruction stay on the main thread.
"""

import ctypes as C
from ctypes import wintypes as W
import os

import cv2


def create_preview_window(title):
    framework = getattr(cv2, "currentUIFramework", None)
    backend = (framework() if callable(framework) else "") or ""
    return PreviewWindow(title, native=backend.upper() == "WIN32")


class Win32PreviewAPI:
    def __init__(self):
        self.user = C.WinDLL("user32", use_last_error=True)
        self._bind("FindWindowExW", [W.HWND, W.HWND, W.LPCWSTR, W.LPCWSTR], W.HWND)
        self._bind("GetWindowThreadProcessId", [W.HWND, C.POINTER(W.DWORD)], W.DWORD)
        self._bind("IsWindow", [W.HWND], W.BOOL)
        self._bind("IsIconic", [W.HWND], W.BOOL)
        self._bind("IsWindowVisible", [W.HWND], W.BOOL)
        self._bind("GetForegroundWindow", [], W.HWND)
        self._bind("GetWindowTextW", [W.HWND, W.LPWSTR, C.c_int], C.c_int)
        self._bind("GetClassNameW", [W.HWND, W.LPWSTR, C.c_int], C.c_int)
        self.pid = os.getpid()

    def _bind(self, name, args, result):
        fn = getattr(self.user, name)
        fn.argtypes, fn.restype = args, result

    def owned(self, hwnd, title):
        if not self.user.IsWindow(hwnd):
            return False
        pid = W.DWORD()
        self.user.GetWindowThreadProcessId(hwnd, C.byref(pid))
        if pid.value != self.pid:
            return False
        name, kind = C.create_unicode_buffer(len(title) + 2), C.create_unicode_buffer(64)
        self.user.GetWindowTextW(hwnd, name, len(name))
        self.user.GetClassNameW(hwnd, kind, len(kind))
        return name.value == title and kind.value == "Main HighGUI class"

    def find(self, title):
        previous = None
        while True:
            hwnd = self.user.FindWindowExW(None, previous, "Main HighGUI class", title)
            if not hwnd:
                return None
            if self.owned(hwnd, title):
                return hwnd
            previous = hwnd

    def state(self, hwnd, title):
        if not self.owned(hwnd, title):
            return "closed"
        if self.user.IsIconic(hwnd):
            return "minimized"
        if not self.user.IsWindowVisible(hwnd):
            return "hidden"
        return "focused" if self.user.GetForegroundWindow() == hwnd else "unfocused"


class PreviewWindow:
    def __init__(self, title, *, api=None, native=False):
        self.title, self.api, self.hwnd = title, api, None
        self.closed = False
        if self.api is None and native and os.name == "nt":
            self.api = Win32PreviewAPI()
        if self.api is not None:
            self.hwnd = self.api.find(title)
            if self.hwnd is None:
                raise OSError("Cannot identify the owned HighGUI preview window; refusing to run")

    def state(self):
        if self.closed:
            return "closed"
        if self.api is not None:
            state = self.api.state(self.hwnd, self.title)
        else:
            # Portable fallback cannot claim focus/minimize telemetry. On Win32
            # WND_PROP_VISIBLE reports existence, not whether it is minimized.
            try:
                state = "visible_unknown" if cv2.getWindowProperty(self.title, cv2.WND_PROP_VISIBLE) >= 1 else "closed"
            except cv2.error:
                state = "closed"
        self.closed = state == "closed"
        return state

    @staticmethod
    def should_render(state):
        return state not in ("closed", "minimized", "hidden")
