"""Lazy ctypes Win32 adapter. No API is loaded or input sent at import time."""

import ctypes as C
from ctypes import wintypes as W
import os
from pathlib import PureWindowsPath

from .models import Screen


ULONG_PTR = C.c_size_t


class MouseInput(C.Structure):
    _fields_ = [("dx", C.c_int32), ("dy", C.c_int32), ("mouseData", C.c_uint32),
                ("dwFlags", C.c_uint32), ("time", C.c_uint32), ("dwExtraInfo", ULONG_PTR)]


class KeyboardInput(C.Structure):
    _fields_ = [("wVk", C.c_uint16), ("wScan", C.c_uint16), ("dwFlags", C.c_uint32),
                ("time", C.c_uint32), ("dwExtraInfo", ULONG_PTR)]


class HardwareInput(C.Structure):
    _fields_ = [("uMsg", C.c_uint32), ("wParamL", C.c_uint16), ("wParamH", C.c_uint16)]


class InputUnion(C.Union):
    _fields_ = [("mi", MouseInput), ("ki", KeyboardInput), ("hi", HardwareInput)]


class Input(C.Structure):
    _anonymous_ = ("data",)
    _fields_ = [("type", C.c_uint32), ("data", InputUnion)]


def mouse(flags, x=0, y=0):
    return Input(type=0, mi=MouseInput(dx=x, dy=y, dwFlags=flags))


def key(vk, up=False):
    return Input(type=1, ki=KeyboardInput(wVk=vk, dwFlags=2 if up else 0))


class WindowsAPI:
    """Explicit signatures matter on 64-bit Windows (handles must not truncate)."""

    def __init__(self):
        if os.name != "nt":
            raise OSError("Live controls require Windows; use --control-mode simulate")
        self.user = C.WinDLL("user32", use_last_error=True)
        self.kernel = C.WinDLL("kernel32", use_last_error=True)
        self._bind(self.user, "SendInput", [W.UINT, C.POINTER(Input), C.c_int], W.UINT)
        self._bind(self.user, "GetCursorPos", [C.POINTER(W.POINT)], W.BOOL)
        self._bind(self.user, "GetSystemMetrics", [C.c_int], C.c_int)
        self._bind(self.user, "GetAsyncKeyState", [C.c_int], C.c_short)
        self._bind(self.user, "GetForegroundWindow", [], W.HWND)
        self._bind(self.user, "GetWindowThreadProcessId", [W.HWND, C.POINTER(W.DWORD)], W.DWORD)
        self._bind(self.kernel, "OpenProcess", [W.DWORD, W.BOOL, W.DWORD], W.HANDLE)
        self._bind(self.kernel, "CloseHandle", [W.HANDLE], W.BOOL)
        self._bind(self.kernel, "QueryFullProcessImageNameW", [W.HANDLE, W.DWORD, W.LPWSTR, C.POINTER(W.DWORD)], W.BOOL)
        self._bind(self.user, "SetProcessDpiAwarenessContext", [W.HANDLE], W.BOOL)
        self._bind(self.user, "GetThreadDpiAwarenessContext", [], W.HANDLE)
        self._bind(self.user, "GetAwarenessFromDpiAwarenessContext", [W.HANDLE], C.c_int)
        self._bind(self.user, "RegisterHotKey", [W.HWND, C.c_int, W.UINT, W.UINT], W.BOOL)
        self._bind(self.user, "UnregisterHotKey", [W.HWND, C.c_int], W.BOOL)
        self._bind(self.user, "PeekMessageW", [C.POINTER(W.MSG), W.HWND, W.UINT, W.UINT, W.UINT], W.BOOL)
        self.monitor_callback = C.WINFUNCTYPE(W.BOOL, W.HANDLE, W.HDC, C.POINTER(W.RECT), W.LPARAM)
        self._bind(self.user, "EnumDisplayMonitors", [W.HDC, C.POINTER(W.RECT), self.monitor_callback, W.LPARAM], W.BOOL)

    @staticmethod
    def _bind(dll, name, args, result):
        try:
            fn = getattr(dll, name)
        except AttributeError:
            raise OSError(f"Required Windows API {name} unavailable; use simulation mode") from None
        fn.argtypes, fn.restype = args, result

    def prepare_dpi(self):
        # May already be set by the Python/OpenCV host. Accept only per-monitor awareness.
        self.user.SetProcessDpiAwarenessContext(W.HANDLE(-4))  # PER_MONITOR_AWARE_V2
        context = self.user.GetThreadDpiAwarenessContext()
        if self.user.GetAwarenessFromDpiAwarenessContext(context) != 2:
            raise OSError("Cannot establish per-monitor DPI awareness; live controls disabled")

    def monitors(self):
        found = []
        @self.monitor_callback
        def collect(_monitor, _dc, rect, _data):
            r = rect.contents
            found.append(Screen(r.left, r.top, r.right-r.left, r.bottom-r.top))
            return True
        if not self.user.EnumDisplayMonitors(None, None, collect, 0) or not found:
            raise OSError("Cannot enumerate monitor geometry")
        # Primary monitor contains desktop origin. Other monitors sort by origin.
        return sorted(found, key=lambda s: (not (s.left <= 0 < s.left+s.width and s.top <= 0 < s.top+s.height), s.left, s.top))

    def virtual_screen(self):
        return Screen(*(self.user.GetSystemMetrics(i) for i in (76, 77, 78, 79)))

    def cursor_position(self):
        point = W.POINT()
        if not self.user.GetCursorPos(C.byref(point)):
            raise OSError("GetCursorPos failed")
        return point.x, point.y

    def foreground(self):
        window = self.user.GetForegroundWindow()
        pid = W.DWORD()
        if not window or not self.user.GetWindowThreadProcessId(window, C.byref(pid)):
            return None, ""
        handle = self.kernel.OpenProcess(0x1000, False, pid.value)  # QUERY_LIMITED_INFORMATION
        if not handle:
            return window, ""
        try:
            path = C.create_unicode_buffer(32768)
            length = W.DWORD(len(path))
            if not self.kernel.QueryFullProcessImageNameW(handle, 0, path, C.byref(length)):
                return window, ""
            return window, PureWindowsPath(path.value).name.casefold()
        finally:
            self.kernel.CloseHandle(handle)

    def send(self, inputs):
        batch = (Input * len(inputs))(*inputs)
        if self.user.SendInput(len(batch), batch, C.sizeof(Input)) != len(batch):
            raise OSError("SendInput incomplete/blocked (Windows UIPI may restrict elevated targets)")

    def register_stop(self):
        # Ctrl+Alt+Esc, MOD_NOREPEAT. Registered on the safety thread's queue.
        if not self.user.RegisterHotKey(None, 0x5636, 0x4003, 0x1B):
            raise OSError("Cannot register Ctrl+Alt+Esc emergency stop (shortcut may be occupied)")

    def stop_requested(self):
        message = W.MSG()
        requested = False
        while self.user.PeekMessageW(C.byref(message), None, 0, 0, 1):
            if message.message == 0x0312 and message.wParam == 0x5636:
                requested = True
        return requested

    def unregister_stop(self):
        if not self.user.UnregisterHotKey(None, 0x5636):
            raise OSError("Cannot unregister emergency shortcut")


class WindowsBackend:
    is_live = True

    def __init__(self, monitor=0, *, api=None):
        self.api = api if api is not None else WindowsAPI()
        self.api.prepare_dpi()
        monitors = self.api.monitors()
        if not 0 <= monitor < len(monitors):
            raise ValueError(f"Monitor {monitor} unavailable; detected {len(monitors)} monitor(s)")
        self.screen, self.desktop = monitors[monitor], self.api.virtual_screen()
        if (self.screen.left < self.desktop.left or self.screen.top < self.desktop.top
                or self.screen.left+self.screen.width > self.desktop.left+self.desktop.width
                or self.screen.top+self.screen.height > self.desktop.top+self.desktop.height):
            raise ValueError("Selected monitor lies outside virtual desktop geometry")
        self.button_owned = False
        self.keys_owned = set()

    def cursor_position(self):
        return self.api.cursor_position()

    def move(self, x, y):
        x, y = self.screen.clamp(x, y)
        dx = round((x-self.desktop.left)*65535/(self.desktop.width-1))
        dy = round((y-self.desktop.top)*65535/(self.desktop.height-1))
        self.api.send([mouse(0xC001, dx, dy)])  # MOVE | ABSOLUTE | VIRTUALDESK

    def left_down(self):
        if self.api.user.GetAsyncKeyState(1) & 0x8000:
            raise OSError("Left button already held outside VisionControl; disarm before using physical mouse")
        self.button_owned = True
        self.api.send([mouse(0x0002)])

    def left_up(self):
        if self.button_owned:
            self.api.send([mouse(0x0004)])
            self.button_owned = False

    def switch_tab(self, previous, allowed):
        window, name = self.api.foreground()
        if not window or name not in allowed:
            return False
        # Do not interfere with a physically held modifier or tab key.
        keys = (0x11, 0x10, 0x09) if previous else (0x11, 0x09)
        if any(self.api.user.GetAsyncKeyState(k) & 0x8000 for k in (0x10, 0x11, 0x12, 0x5B, 0x5C, 0x09)):
            return False
        if self.api.user.GetForegroundWindow() != window:
            return False
        self.keys_owned.update(keys)  # A partial batch must still have all possible key-ups attempted.
        try:
            self.api.send([key(k) for k in keys]+[key(k, True) for k in reversed(keys)])
        except Exception:
            self.release_keys()
            raise
        else:
            self.keys_owned.clear()
        return True

    def release_keys(self):
        errors = []
        for vk in tuple(self.keys_owned):
            try:
                self.api.send([key(vk, True)])
                self.keys_owned.remove(vk)
            except Exception as exc:
                errors.append(exc)
        if errors:
            raise OSError("Cannot release owned keyboard input") from errors[0]

    def close(self):
        try:
            self.left_up()
        finally:
            self.release_keys()
