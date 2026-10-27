"""Single-owner capture with a one-slot immutable handoff. No GUI or input calls.

Native reads cannot be killed safely from Python. Normal close requests stop and
joins; a failed bounded join is explicit, retains the device lease and never
releases an in-use capture on the caller thread. Daemon status is only the final
process-exit safeguard for a stuck native call, not normal resource cleanup.
"""

from collections import Counter
from dataclasses import dataclass, field
import math
import threading
import time
import uuid

import numpy as np

from hand_tracking.performance import Profile
from .camera_diagnostics import read_frame


_LEASE_LOCK = threading.Lock()
_LEASES = set()
COUNTERS = frozenset(("capture_attempts", "successful_frames", "read_failures", "worker_exceptions",
    "release_failures", "invalid_frames", "overwritten_unconsumed_frames", "duplicate_packets_suppressed", "consumed_frames",
    "consumer_waits", "consumer_wait_timeouts", "startup_timeouts", "delivery_timeouts", "shutdown_timeouts",
    "stale_frames_rejected", "stale_results_rejected", "millisecond_timestamp_collisions_suppressed"))


class CaptureError(OSError):
    pass


class CaptureShutdownError(CaptureError):
    pass


def ensure_camera_available(device_key):
    """Sync fallback must not reopen a device still owned by a capture worker."""
    with _LEASE_LOCK:
        if device_key in _LEASES:
            raise CaptureError("Camera is still owned by a capture worker; finish cleanup or restart the process")


@dataclass(frozen=True, slots=True)
class CapturedFrame:
    session: str
    sequence: int
    read_completed_at: float
    read_seconds: float
    published_at: float
    dimensions: tuple[int, int]
    image: np.ndarray = field(repr=False, compare=False)


class CaptureTimestamp:
    """Use actual capture milliseconds; discard collisions, never invent future ticks."""
    def __init__(self, origin):
        self.origin, self.previous = origin, -1

    def next(self, completed_at):
        if not math.isfinite(completed_at) or completed_at < self.origin:
            raise CaptureError("Invalid capture-completion clock")
        stamp = int((completed_at - self.origin) * 1000)
        if stamp <= self.previous:
            return None
        self.previous = stamp
        return stamp


class LatestCapture:
    capacity = 1

    def __init__(self, factory, configure=None, *, device_key=None, profile=False,
                 measuring=True, startup_timeout=15., max_age=.25, clock=time.perf_counter):
        if not all(math.isfinite(v) and v > 0 for v in (startup_timeout, max_age)):
            raise ValueError("Capture deadlines must be finite and positive")
        self.factory, self.configure, self.device_key = factory, configure, device_key
        self.profile_enabled, self.measuring, self.clock = profile, measuring, clock
        self.startup_timeout, self.max_age = startup_timeout, max_age
        self.origin = clock()
        self.session = uuid.uuid4().hex
        self.condition = threading.Condition()
        self.stop = threading.Event()
        self.failed = threading.Event()
        self.initialized = threading.Event()
        self.finished = threading.Event()
        self.thread = None
        self._slot = None
        self._sequence = self._consumed = 0
        self._last_completion = self._previous_publication = None
        self._error = None
        self.metadata = {}
        self.counts, self.measured_counts = Counter(), Counter()
        self.timings = Profile(enabled=profile and measuring)
        self._measurement_start = self.origin if measuring else None
        self._measurement_end = None
        self.initialization_seconds = self.first_frame_seconds = self.shutdown_seconds = None
        self.shutdown_error = None
        self.join_deadline_seconds = None
        self.release_completed = False
        self.max_occupancy = 0

    def _count(self, name, amount=1):
        # Called under condition; native capture/copy/cleanup never hold this lock.
        self.counts[name] += amount
        if self.measuring and self._measurement_end is None:
            self.measured_counts[name] += amount

    def start(self):
        if self.thread is not None or self.stop.is_set():
            raise CaptureError("Capture session is single-use")
        self.thread = threading.Thread(target=self._run, name="VisionControl latest capture", daemon=True)
        self.thread.start()
        return self

    def begin_measurement(self):
        with self.condition:
            if self.stop.is_set():
                raise CaptureError("Cannot measure a stopped capture session")
            self.measuring = True
            self.measured_counts.clear()
            self.timings = Profile(enabled=self.profile_enabled)
            self._measurement_start = self.clock()
            self._previous_publication = None

    def record_rejection(self, name):
        if name not in COUNTERS:
            raise ValueError("Unknown bounded capture counter")
        with self.condition:
            self._count(name)

    def fail(self, reason):
        with self.condition:
            if self._error is None:
                self._error = str(reason)
            self.failed.set()  # Input fence is visible without acquiring this condition.
            if self._measurement_end is None:
                self._measurement_end = self.clock()
            self.stop.set()
            self._slot = None
            self.condition.notify_all()

    def raise_if_failed(self):
        if self.failed.is_set():
            raise CaptureError(self._error or "Capture worker failed")

    def input_allowed(self):
        # Short metadata-only lock; no native work or controller callbacks ever
        # run under it. No reverse controller-lock acquisition exists on producer.
        with self.condition:
            completed = self._last_completion
            return (not self.failed.is_set() and not self.stop.is_set() and completed is not None
                    and 0 <= self.clock() - completed <= self.max_age)

    def check_deadline(self):
        self.raise_if_failed()
        if self.stop.is_set():
            raise CaptureError("Capture session stopped")
        with self.condition:
            completed = self._last_completion
            if completed is None:
                if self.clock() - self.origin > self.startup_timeout:
                    self._count("startup_timeouts")
                    self.fail("Capture initialization/first-frame timeout")
            elif self.clock() - completed > self.max_age:
                self._count("delivery_timeouts")
                self.fail("Capture stopped delivering fresh frames (>250 ms); restart required")
        self.raise_if_failed()

    def take(self, timeout=.01):
        if not math.isfinite(timeout) or timeout < 0 or timeout > 1:
            raise ValueError("Consumer wait must be finite and within [0,1] seconds")
        before = self.clock()
        with self.condition:
            self.raise_if_failed()
            if self._slot is None and not self.stop.is_set():
                self._count("consumer_waits")
                self.condition.wait_for(lambda: self._slot is not None or self.stop.is_set(), timeout)
            self.timings.add("consumer_wait", self.clock()-before)
            self.raise_if_failed()
            if self._slot is None:
                self._count("consumer_wait_timeouts")
                return None
            packet, self._slot = self._slot, None
            if packet.session != self.session or packet.sequence <= self._consumed:
                self._count("duplicate_packets_suppressed")
                return None
            self._consumed = packet.sequence
            self._count("consumed_frames")
            return packet

    def _run(self):
        cap, leased = None, False
        try:
            if self.device_key is not None:
                with _LEASE_LOCK:
                    if self.device_key in _LEASES:
                        raise CaptureError("Camera session already owns this device or is still shutting down")
                    _LEASES.add(self.device_key)
                    leased = True
            if self.stop.is_set():
                return
            cap = self.factory()  # All camera operations, including open, belong here.
            if self.stop.is_set():
                return
            metadata = self.configure(cap) if self.configure is not None else {}
            with self.condition:
                self.metadata = metadata or {}
                self.initialization_seconds = self.clock()-self.origin
                self.initialized.set()
            while not self.stop.is_set():
                with self.condition:
                    self._count("capture_attempts")
                before = self.clock()
                try:
                    frame = read_frame(cap)
                except OSError as exc:
                    if self.stop.is_set():
                        break
                    with self.condition:
                        self._count("read_failures")
                    raise CaptureError(str(exc)) from exc
                completed = self.clock()
                if self.stop.is_set():
                    break
                if not (math.isfinite(before) and math.isfinite(completed) and self.origin <= before <= completed):
                    raise CaptureError("Invalid capture read clock")
                if self._last_completion is not None and completed <= self._last_completion:
                    raise CaptureError("Capture completion clock did not increase")
                if frame.ndim != 3 or frame.shape[2] != 3 or frame.dtype != np.uint8:
                    with self.condition:
                        self._count("invalid_frames")
                    raise CaptureError("Expected a decoded uint8 BGR camera frame")
                # One defensive copy is required: native/custom backends may reuse
                # their storage on the next read. Consumer never copies this again.
                image = frame.copy(order="C")
                image.setflags(write=False)
                copied = self.clock()
                if not math.isfinite(copied) or copied < completed:
                    raise CaptureError("Invalid snapshot clock")
                with self.condition:
                    if self.stop.is_set():
                        break
                    published = self.clock()
                    if (not math.isfinite(published) or published < copied
                            or self._previous_publication is not None and published < self._previous_publication):
                        raise CaptureError("Invalid capture publication clock")
                    self._sequence += 1
                    if self._slot is not None:
                        self._count("overwritten_unconsumed_frames")
                    self._slot = CapturedFrame(self.session, self._sequence, completed, completed-before,
                                              published, (image.shape[1], image.shape[0]), image)
                    self.max_occupancy = 1
                    self._last_completion = completed
                    self._count("successful_frames")
                    self.timings.add("camera_read", completed-before)
                    self.timings.add("snapshot_copy", copied-completed)
                    if self._previous_publication is not None:
                        self.timings.add("publication_interval", published-self._previous_publication)
                    self._previous_publication = published
                    if self.first_frame_seconds is None:
                        self.first_frame_seconds = published-self.origin
                    self.condition.notify_all()
        except BaseException as exc:
            with self.condition:
                if not isinstance(exc, CaptureError):
                    self._count("worker_exceptions")
            self.fail(f"Camera worker failed: {type(exc).__name__}: {exc}")
        finally:
            released = cap is None
            try:
                if cap is not None:
                    cap.release()
                    released = True
            except BaseException as exc:
                with self.condition:
                    self._count("release_failures")
                self.fail(f"Camera release failed: {type(exc).__name__}: {exc}")
            finally:
                if leased and released:
                    with _LEASE_LOCK:
                        _LEASES.discard(self.device_key)
                with self.condition:
                    self.release_completed = released
                    self.finished.set()
                    self.condition.notify_all()

    def request_stop(self):
        with self.condition:
            if self._measurement_end is None:
                self._measurement_end = self.clock()
            self.stop.set()
            self._slot = None
            self.condition.notify_all()

    def close(self, timeout=12.):
        if not math.isfinite(timeout) or timeout < 0:
            raise ValueError("Shutdown timeout must be finite and nonnegative")
        before = self.clock()
        self.join_deadline_seconds = timeout
        self.request_stop()
        if self.thread is not None:
            self.thread.join(timeout)
        self.shutdown_seconds = self.clock()-before
        if self.thread is not None and self.thread.is_alive():
            with self.condition:
                self._count("shutdown_timeouts")
            self.shutdown_error = "Camera shutdown timed out; native read/release still owns camera; restart process before retry"
            self.fail(self.shutdown_error)
            raise CaptureShutdownError(self.shutdown_error)
        if not self.release_completed and self.thread is not None:
            raise CaptureShutdownError(self._error or "Camera release failed")

    def snapshot(self):
        with self.condition:
            end = self._measurement_end if self._measurement_end is not None else self.clock()
            elapsed = (max(0., end-self._measurement_start)
                       if self._measurement_start is not None else 0.)
            return {"mode": "latest-thread", "session": self.session, "buffer_capacity": 1,
                    "max_buffer_occupancy": self.max_occupancy, "buffer_occupancy": int(self._slot is not None),
                    "lifetime_counts": {name: self.counts[name] for name in sorted(COUNTERS)},
                    "measurement_counts": {name: self.measured_counts[name] for name in sorted(COUNTERS)},
                    "measurement_seconds": elapsed,
                    "capture_worker_delivery_fps": self.measured_counts["successful_frames"]/elapsed if elapsed else None,
                    "timings": self.timings.summary(), "initialization_seconds": self.initialization_seconds,
                    "first_frame_seconds": self.first_frame_seconds, "shutdown_seconds": self.shutdown_seconds,
                    "shutdown_error": self.shutdown_error, "join_deadline_seconds": self.join_deadline_seconds,
                    "worker_alive": bool(self.thread and self.thread.is_alive()), "release_completed": self.release_completed,
                    "failed": self.failed.is_set(), "error": self._error, "metadata": dict(self.metadata),
                    "sensor_fps": None, "sensor_exposure_age_ms": None, "driver_dropped_frames": None,
                    "first_frame_timeout_seconds": self.startup_timeout, "max_host_age_seconds": self.max_age,
                    "driver_duplicate_images": None, "snapshot_policy": "one owned read-only BGR copy per publication",
                    "successful_frames_semantics": "published valid snapshots; a final in-flight read can be discarded during stop",
                    "timestamp_semantics": "monotonic host read completion, not exposure time"}
