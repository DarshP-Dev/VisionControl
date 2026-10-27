"""Opt-in bounded frame/cursor pacing. No pixels, window titles or input content."""

from collections import Counter
import ctypes as C
from ctypes import wintypes as W
import os

from .performance import Profile


STATES = frozenset(("focused", "unfocused", "minimized", "hidden", "visible_unknown", "headless", "closed"))


class PacingDiagnostics:
    def __init__(self, enabled=False, capacity=8192, stall_seconds=.100):
        self.enabled, self.capacity, self.stall_seconds = enabled, capacity, stall_seconds
        self.profile = Profile(enabled, capacity)
        self.by_state = {}
        self.frames = Counter()
        self.state_seconds = Counter()
        self.stalls = Counter()
        self.transitions = Counter()
        self.previous_end = self.previous_read = self.previous_move = None
        self.previous_state = None
        self.read_at = None
        self.state = "visible_unknown"
        self.state_generation = 0
        self.move_generation = None
        self.moves = 0
        self.cursor_gaps = Counter()

    def add(self, name, seconds, state):
        self.profile.add(name, seconds)
        if state not in self.by_state:
            self.by_state[state] = Profile(capacity=self.capacity)
        self.by_state[state].add(name, seconds)

    def begin(self, read_at, state):
        if not self.enabled:
            return
        if state not in STATES:
            raise ValueError("Unknown preview state")
        if state not in self.by_state:
            self.by_state[state] = Profile(capacity=self.capacity)
        if state != self.state:
            self.state_generation += 1
        self.read_at, self.state = read_at, state
        if self.previous_read is not None:
            self.add("capture_delivery_interval", read_at - self.previous_read, state)
        self.previous_read = read_at

    def moved(self, before, after):
        """Called only after an accepted backend move; includes SendInput duration."""
        if not self.enabled or self.read_at is None:
            return
        self.moves += 1
        self.add("cursor_dispatch", after - before, self.state)
        self.add("host_frame_age_at_dispatch", after - self.read_at, self.state)
        if self.previous_move is not None:
            interval = after - self.previous_move
            self.profile.add("cursor_update_interval", interval)
            if interval > self.stall_seconds:
                self.cursor_gaps[self.state] += 1
            # Separate state transitions instead of attributing a focus switch's
            # gap entirely to either steady-state population.
            if self.move_generation == self.state_generation:
                self.add("cursor_update_interval_same_state", interval, self.state)
            else:
                self.profile.add("cursor_update_interval_transition", interval)
        self.previous_move = after
        self.move_generation = self.state_generation

    def finish(self, before_read, end):
        if not self.enabled:
            return
        state = self.state
        interval = end - (self.previous_end if self.previous_end is not None else before_read)
        self.frames[state] += 1
        self.state_seconds[state] += interval
        if self.previous_state is not None and self.previous_state != state:
            self.transitions[f"{self.previous_state}->{state}"] += 1
        if self.previous_end is not None:
            self.add("frame_completion_interval", interval, state)
        if interval > self.stall_seconds:
            self.stalls[state] += 1
        self.previous_end, self.previous_state = end, state

    def summary(self):
        delivery = self.profile.summary().get("capture_delivery_interval")
        return {"enabled": self.enabled, "percentile_capacity_per_series": self.capacity,
                "stall_threshold_ms": self.stall_seconds * 1000,
                "long_frame_stalls": dict(self.stalls), "transitions": dict(self.transitions),
                "cursor_gaps_over_threshold_including_intentional_pauses": dict(self.cursor_gaps),
                "frames_by_preview_state": dict(self.frames), "cursor_updates": self.moves,
                "capture_delivery_fps": 1000 / delivery["mean_ms"] if delivery and delivery["mean_ms"] > 0 else None,
                "camera_sensor_fps": None, "camera_driver_frame_age_ms": None,
                "dropped_camera_frames": None, "application_frame_queue_capacity": 0,
                "application_queued_frames": 0, "preview_frames_skipped": 0,
                "timings": self.profile.summary(),
                "by_preview_state": {state: {"frames": self.frames[state],
                    "loop_seconds": self.state_seconds[state],
                    "application_fps": self.frames[state] / self.state_seconds[state] if self.state_seconds[state] else None,
                    "timings": profile.summary()} for state, profile in self.by_state.items()},
                "limitations": "Synchronous capture delivery is not independent camera throughput. Host age starts at read completion, not exposure. Cursor intervals include intentional gesture pauses."}


def process_memory():
    """One end-of-run sample; optional Windows process counters, bytes only."""
    if os.name != "nt":
        return {"available": False}
    class Counters(C.Structure):
        _fields_ = [("cb", W.DWORD), ("PageFaultCount", W.DWORD)] + [
            (name, C.c_size_t) for name in ("PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage",
                "QuotaPagedPoolUsage", "QuotaPeakNonPagedPoolUsage", "QuotaNonPagedPoolUsage", "PagefileUsage", "PeakPagefileUsage")]
    try:
        kernel, psapi = C.WinDLL("kernel32"), C.WinDLL("psapi")
        kernel.GetCurrentProcess.restype = W.HANDLE
        kernel.GetCurrentProcess.argtypes = []
        psapi.GetProcessMemoryInfo.argtypes = [W.HANDLE, C.POINTER(Counters), W.DWORD]
        psapi.GetProcessMemoryInfo.restype = W.BOOL
        data = Counters()
        data.cb = C.sizeof(data)
        if not psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(), C.byref(data), data.cb):
            return {"available": False}
        return {"available": True, "working_set_bytes_at_exit": data.WorkingSetSize,
                "peak_working_set_bytes_process_lifetime": data.PeakWorkingSetSize}
    except (OSError, AttributeError):
        return {"available": False}
